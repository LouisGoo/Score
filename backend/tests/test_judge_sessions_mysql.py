import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from threading import Event as ThreadEvent
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.core.security import token_hash
from score_api.credentials import service as credentials
from score_api.credentials.schemas import ResetCredentialInput
from score_api.db import utc_now
from score_api.events.models import Event, EventAudit, EventJudge
from score_api.judge_sessions import service
from score_api.judge_sessions.models import JudgeAuthAudit, JudgeConfirmation, JudgeSession
from score_api.judge_sessions.schemas import ExchangeInput
from score_api.main import create_app

pytestmark = pytest.mark.mysql
ORIGIN = "https://score.test"
BASE = "/api/v1/judge-sessions"


@pytest.fixture
def published(clients):
    owner, _ = clients
    event = owner.post(
        "/api/v1/events",
        json={
            "title": "身份测试",
            "scoring_rule": {"criteria": [{"criterion_id": "total", "name": "总分"}]},
        },
    ).json()
    url = f"/api/v1/events/{event['id']}"
    owner.post(url + "/entries", json={"number": "001", "name": "参赛对象"})
    judges = []
    for number, code in (("001", "FIRST123"), ("002", "SECOND123")):
        judge = owner.post(url + "/judges", json={"number": number, "name": "评委" + number}).json()
        assert (
            owner.put(f"{url}/judges/{judge['id']}/credential", json={"code": code}).status_code
            == 200
        )
        judges.append(judge)
    response = owner.post(url + "/publish")
    assert response.status_code == 200, response.text
    return response.json(), url, judges


@pytest.fixture
def mobiles(clients):
    settings = clients[0].app.state.settings
    with (
        TestClient(create_app(settings.model_copy()), base_url=ORIGIN) as first,
        TestClient(create_app(settings.model_copy()), base_url=ORIGIN) as second,
    ):
        for client in (first, second):
            token = client.get(BASE + "/csrf").json()["csrf_token"]
            client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": token})
        yield first, second


def verify(client, published, code="FIRST123"):
    return client.post(
        BASE + "/verify",
        json={"public_code": published[0]["event"]["public_code"].lower(), "code": code},
    )


def confirm(client, verification):
    assert verification.status_code == 200, verification.text
    return client.post(
        BASE + "/exchange", json={"confirmation_token": verification.json()["confirmation_token"]}
    )


def reset_url(published):
    return f"{published[1]}/judges/{published[2][0]['id']}/reset-credential"


def test_preview_confirmation_cookie_me_and_logout(published, mobiles, clients, event_db, caplog):
    first, second = mobiles
    owner, _ = clients
    db, _ = event_db
    public_code = published[0]["event"]["public_code"]
    preview = first.get("/api/v1/join/" + public_code.lower())
    assert preview.status_code == 200 and preview.json()["exchange_open"]
    assert set(preview.json()) == {
        "public_code",
        "title",
        "description",
        "organization",
        "planned_at",
        "status",
        "exchange_open",
    }
    assert first.get("/api/v1/join/ABCDEFGH2345").status_code == 404
    identity = verify(first, published, " first123 ")
    assert identity.json()["judge"]["number"] == "001"
    assert identity.json()["judge"]["id"] == published[2][0]["id"]
    assert first.get(BASE + "/me").status_code == 401
    # 确认令牌绑定本浏览器 bootstrap，不能把确认令牌单独带到另一台手机。
    assert confirm(second, identity).json()["error"]["code"] == "CONFIRMATION_EXPIRED"
    session = confirm(first, identity)
    assert session.status_code == 200, session.text
    cookie = session.headers["set-cookie"]
    assert all(
        value in cookie
        for value in (
            "__Host-score_judge_session=",
            "HttpOnly",
            "Secure",
            "SameSite=strict",
            "Path=/",
        )
    )
    token = first.cookies.get("__Host-score_judge_session")
    assert token not in session.text and "FIRST123" not in session.text
    assert not session.json()["read_only"]
    assert first.get(BASE + "/me").json() == session.json()
    assert owner.get(BASE + "/me").status_code == 401
    assert first.get("/api/v1/auth/me").status_code == 401
    assert first.get(published[1]).status_code == 401
    assert confirm(first, identity).json()["error"]["code"] == "CONFIRMATION_EXPIRED"
    assert first.post(BASE + "/logout").status_code == 403  # 仍携带 bootstrap CSRF。
    first.headers["X-CSRF-Token"] = session.json()["csrf_token"]
    assert first.post(BASE + "/logout", headers={"Origin": "https://evil.test"}).status_code == 403
    assert first.post(BASE + "/logout").status_code == 204
    first.cookies.set("__Host-score_judge_session", token)
    assert first.get(BASE + "/me").status_code == 401
    with db.transaction() as sql:
        audit = sql.scalar(
            select(JudgeAuthAudit).where(
                JudgeAuthAudit.action == "session_exchanged",
                JudgeAuthAudit.event_id == published[0]["event"]["id"],
            )
        )
        assert audit.request_id == session.headers["x-request-id"]
        row = sql.get(JudgeSession, token_hash(token))
        assert row.revoked_at is not None
    assert token not in caplog.text and "FIRST123" not in caplog.text


def test_second_device_blocked_same_device_does_not_extend_and_identity_switch(published, mobiles):
    first, second = mobiles
    session = confirm(first, verify(first, published))
    original = first.cookies.get("__Host-score_judge_session")
    again = confirm(first, verify(first, published))
    assert again.status_code == 200 and again.json()["expires_at"] == session.json()["expires_at"]
    assert first.cookies.get("__Host-score_judge_session") == original
    assert (
        confirm(second, verify(second, published)).json()["error"]["code"] == "JUDGE_SESSION_ACTIVE"
    )
    assert (
        confirm(first, verify(first, published, "SECOND123")).json()["error"]["code"]
        == "SESSION_SWITCH_REQUIRED"
    )
    assert confirm(second, verify(second, published, "SECOND123")).status_code == 200


def test_reset_rejects_current_duplicate_and_invalidates_old_code_sessions_confirmations(
    published, mobiles, clients, event_db
):
    owner, other = clients
    first, second = mobiles
    db, _ = event_db
    session = confirm(first, verify(first, published))
    pending = verify(second, published)
    url = reset_url(published)
    assert owner.post(url, json={"code": "NEWCODE123"}).status_code == 422
    assert owner.post(url, json={"reason": " "}).status_code == 422
    assert (
        owner.post(url, json={"reason": "换机", "code": " first123 "}).json()["error"]["code"]
        == "CREDENTIAL_UNCHANGED"
    )
    assert (
        owner.post(url, json={"reason": "换机", "code": "SECOND123"}).json()["error"]["code"]
        == "CREDENTIAL_CONFLICT"
    )
    assert other.post(url, json={"reason": "换机"}).status_code == 404
    assert (
        owner.post(url, json={"reason": "换机"}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    )
    response = owner.post(url, json={"reason": "更换手机", "code": "NEWCODE123"})
    assert response.status_code == 200 and response.json()["credential_version"] == 2
    assert first.get(BASE + "/me").status_code == 401
    assert confirm(second, pending).status_code == 401
    invalid = verify(second, published)
    assert invalid.status_code == 401 and "FIRST123" not in invalid.text
    assert confirm(second, verify(second, published, "newcode123")).status_code == 200
    assert owner.get(published[1] + "/publication").json()["snapshot"] == published[0]["snapshot"]
    with db.transaction() as sql:
        judge = sql.get(EventJudge, published[2][0]["id"])
        assert judge.number == "001" and judge.name == "评委001"
        audit = sql.scalar(
            select(EventAudit).where(
                EventAudit.target_id == judge.id, EventAudit.action == "credential.reset"
            )
        )
        assert audit.after["reason"] == "更换手机" and audit.before["credential_version"] == 1
        serialized = json.dumps([audit.before, audit.after])
        assert "NEWCODE123" not in serialized and judge.credential_hash not in serialized
    # 旧会话携带旧 CSRF 也不能通过写请求身份校验。
    first.headers["X-CSRF-Token"] = session.json()["csrf_token"]
    assert first.post(BASE + "/logout").status_code == 401
    # 存在真实会话与确认记录后复制，也不能把它们带入新活动。
    copied = owner.post(published[1] + "/copy")
    assert copied.status_code == 201
    copied_id = copied.json()["id"]
    copied_judges = owner.get(f"/api/v1/events/{copied_id}/judges").json()
    assert all(not judge["credential_is_set"] for judge in copied_judges)
    with db.transaction() as sql:
        for model in (JudgeSession, JudgeConfirmation):
            assert sql.scalar(select(model.token_hash).where(model.event_id == copied_id)) is None
    assert second.get(BASE + "/me").status_code == 200


@pytest.mark.parametrize("status", ["FINISHED", "ARCHIVED"])
def test_finished_closes_verify_exchange_reset_but_existing_session_read_only(
    published, mobiles, clients, event_db, status
):
    first, second = mobiles
    owner, _ = clients
    db, _ = event_db
    assert confirm(first, verify(first, published)).status_code == 200
    pending = verify(second, published, "SECOND123")
    with db.transaction() as sql:
        sql.get(Event, published[0]["event"]["id"]).status = status
    preview = first.get("/api/v1/join/" + published[0]["event"]["public_code"])
    assert not preview.json()["exchange_open"]
    assert verify(second, published).json()["error"]["code"] == "EVENT_CLOSED"
    assert confirm(second, pending).json()["error"]["code"] == "EVENT_CLOSED"
    assert (
        owner.post(reset_url(published), json={"reason": "换机"}).json()["error"]["code"]
        == "RESET_NOT_ALLOWED"
    )
    assert first.get(BASE + "/me").json()["read_only"]


def test_confirmation_expiry_session_expiry_and_unique_database_guard(published, mobiles, event_db):
    first, second = mobiles
    db, _ = event_db
    pending = verify(first, published)
    first.app.state.clock = lambda: utc_now() + timedelta(minutes=4)
    assert confirm(first, pending).status_code == 401
    first.app.state.clock = utc_now
    session = confirm(first, verify(first, published))
    old_token = first.cookies.get("__Host-score_judge_session")
    with pytest.raises(IntegrityError), db.transaction() as sql:
        sql.add(
            JudgeSession(
                token_hash=token_hash(secrets.token_urlsafe(32)),
                event_id=published[0]["event"]["id"],
                judge_id=published[2][0]["id"],
                credential_version=1,
                created_at=utc_now(),
                expires_at=utc_now() + timedelta(hours=1),
            )
        )

    def future():
        return utc_now() + timedelta(days=2)

    first.app.state.clock = future
    second.app.state.clock = future
    assert first.get(BASE + "/me").status_code == 401
    assert confirm(second, verify(second, published)).status_code == 200
    with db.transaction() as sql:
        assert sql.get(JudgeSession, token_hash(old_token)).revoked_at is not None
    assert session.json()["expires_at"] != second.get(BASE + "/me").json()["expires_at"]


def test_concurrent_exchange_one_active_and_replay_rejected(published, mobiles, event_db):
    first, second = mobiles
    db, _ = event_db
    pending = [verify(client, published).json() for client in mobiles]
    barrier = Barrier(2)

    def exchange(index):
        barrier.wait(timeout=5)
        client = mobiles[index]
        try:
            service.exchange(
                db,
                client.app.state.settings,
                utc_now,
                "phone" + str(index),
                ExchangeInput(confirmation_token=pending[index]["confirmation_token"]),
                client.cookies.get("__Host-score_judge_bootstrap"),
                "",
                uuid4().hex,
            )
            return "ok"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(exchange, range(2))) == ["JUDGE_SESSION_ACTIVE", "ok"]
    with db.transaction() as sql:
        assert (
            sql.scalar(
                select(func.count())
                .select_from(JudgeSession)
                .where(
                    JudgeSession.judge_id == published[2][0]["id"],
                    JudgeSession.revoked_at.is_(None),
                )
            )
            == 1
        )


@pytest.mark.parametrize("operation", ["verify", "exchange", "logout", "reset"])
def test_audit_failures_roll_back_identity_session_and_reset(
    published, mobiles, clients, event_db, operation
):
    first, _ = mobiles
    owner, _ = clients
    db, _ = event_db
    pending = verify(first, published)
    if operation in {"logout", "reset"}:
        result = confirm(first, pending)
        first.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    model = EventAudit if operation == "reset" else JudgeAuthAudit

    def fail(*_):
        raise RuntimeError("audit failure")

    sa_event.listen(model, "before_insert", fail)
    try:
        if operation == "verify":
            response = verify(first, published)
        elif operation == "exchange":
            response = confirm(first, pending)
        elif operation == "logout":
            response = first.post(BASE + "/logout")
        else:
            response = owner.post(
                reset_url(published), json={"reason": "换机", "code": "NEWCODE123"}
            )
        assert response.status_code == 500
    finally:
        sa_event.remove(model, "before_insert", fail)
    with db.transaction() as sql:
        assert sql.get(EventJudge, published[2][0]["id"]).credential_version == 1
        if operation == "exchange":
            assert (
                sql.get(
                    JudgeConfirmation, token_hash(pending.json()["confirmation_token"])
                ).consumed_at
                is None
            )
            assert (
                sql.scalar(
                    select(JudgeSession.token_hash).where(
                        JudgeSession.judge_id == published[2][0]["id"]
                    )
                )
                is None
            )
    if operation in {"logout", "reset"}:
        assert first.get(BASE + "/me").status_code == 200


def test_failed_codes_consume_shared_limits_without_affecting_other_judges(published, mobiles):
    first, second = mobiles
    first.app.state.settings.judge_attempt_limit = 2
    second.app.state.settings.judge_attempt_limit = 2
    for _ in range(2):
        result = verify(first, published, "INVALID123")
        assert result.status_code == 401
    limited = verify(second, published, "INVALID123")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert confirm(first, verify(first, published)).status_code == 200
    assert confirm(second, verify(second, published, "SECOND123")).status_code == 200
    first.app.state.clock = lambda: utc_now() + timedelta(minutes=6)
    assert verify(first, published, "INVALID123").status_code == 401


def test_reset_during_verification_rechecks_version(published, mobiles, clients, monkeypatch):
    owner, _ = clients
    first, _ = mobiles
    original = service.verify_password

    def verify_then_reset(*args):
        result = original(*args)
        assert (
            owner.post(
                reset_url(published), json={"reason": "泄露", "code": "NEWCODE123"}
            ).status_code
            == 200
        )
        return result

    monkeypatch.setattr(service, "verify_password", verify_then_reset)
    assert verify(first, published).status_code == 401


def test_waiting_exchange_rechecks_reset_and_logout_rechecks_session(
    published, mobiles, clients, event_db
):
    first, _ = mobiles
    owner, _ = clients
    db, owners = event_db
    pending = verify(first, published)
    body = ExchangeInput(confirmation_token=pending.json()["confirmation_token"])
    prepared = credentials.prepare_credential(
        owner.app.state.settings, published[0]["event"]["id"], "NEWCODE123"
    )
    waiting = ThreadEvent()

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        if "FOR UPDATE" in statement:
            waiting.set()

    def exchange():
        try:
            service.exchange(
                db,
                owner.app.state.settings,
                utc_now,
                "waiting-phone",
                body,
                first.cookies.get("__Host-score_judge_bootstrap"),
                "",
                uuid4().hex,
            )
            return "ok"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as sql:
            event = sql.scalar(
                select(Event).where(Event.id == published[0]["event"]["id"]).with_for_update()
            )
            judge = sql.get(EventJudge, published[2][0]["id"])
            credentials.apply_credential(
                sql, event, judge, prepared, owners[0], uuid4().hex, utc_now(), reason="测试锁竞争"
            )
            sa_event.listen(db.engine, "before_cursor_execute", before_execute)
            future = pool.submit(exchange)
            try:
                assert waiting.wait(timeout=5) and not future.done()
            finally:
                sa_event.remove(db.engine, "before_cursor_execute", before_execute)
        assert future.result(timeout=5) == "CONFIRMATION_EXPIRED"
    assert confirm(first, verify(first, published, "NEWCODE123")).status_code == 200
    token = first.cookies.get("__Host-score_judge_session")
    principal = service.get_principal(db, token, utc_now())
    credentials.reset_credential(
        db,
        owner.app.state.settings,
        owners[0],
        published[0]["event"]["id"],
        published[2][0]["id"],
        ResetCredentialInput(reason="再次换机"),
        uuid4().hex,
        utc_now,
    )
    with pytest.raises(APIError) as error:
        service.logout(db, principal, utc_now, uuid4().hex)
    assert error.value.code == "SESSION_EXPIRED"
