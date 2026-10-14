from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from threading import Event as ThreadEvent
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymysql.err import OperationalError as DriverError
from sqlalchemy import delete, func, select
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError, OperationalError
from test_rounds_mysql import control

from score_api.ballots import service
from score_api.ballots.models import Ballot, BallotAudit, BallotRevision, IdempotencyRecord
from score_api.ballots.schemas import BallotInput
from score_api.core.errors import APIError
from score_api.db import Database, utc_now
from score_api.events.models import Event, EventSnapshot
from score_api.judge_sessions.models import JudgeSession
from score_api.judge_sessions.service import get_principal
from score_api.main import create_app
from score_api.outbox.models import OutboxEvent
from score_api.rounds import service as round_service
from score_api.rounds.models import RoundJudge, ScoringRound
from score_api.rounds.schemas import ControlInput

pytestmark = pytest.mark.mysql


@pytest.fixture
def scoring(rounds_event, mobiles, clients):
    for mobile, credential in zip(mobiles, rounds_event["generated_credentials"], strict=True):
        verify = mobile.post(
            "/api/v1/judge-sessions/verify",
            json={
                "public_code": rounds_event["event"]["public_code"],
                "code": credential["code"],
            },
        )
        assert verify.status_code == 200
        exchange = mobile.post(
            "/api/v1/judge-sessions/exchange",
            json={
                "confirmation_token": verify.json()["confirmation_token"],
            },
        )
        assert exchange.status_code == 200
        mobile.headers["X-CSRF-Token"] = exchange.json()["csrf_token"]
    now = utc_now()
    clients[0].app.state.clock = lambda: now
    for mobile in mobiles:
        mobile.app.state.clock = lambda: now
    opened = control(clients[0], rounds_event["rounds"][0], "open")
    assert opened.status_code == 200, opened.text
    return rounds_event, mobiles, now


def payload(value="90.0", revision=0, rule=1):
    return {
        "rule_version": rule,
        "expected_ballot_revision": revision,
        "scores": [{"criterion_id": "total", "value": value}],
    }


def url(scoring, index=0):
    return f"/api/v1/rounds/{scoring[0]['rounds'][index]['id']}/my-ballot"


def put(scoring, *, body=None, key=None, judge=0, index=0):
    return scoring[1][judge].put(
        url(scoring, index),
        json=body or payload(),
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def principal(scoring, db, judge=0):
    return get_principal(
        db, scoring[1][judge].cookies.get("__Host-score_judge_session"), scoring[2]
    )


def counts(db, event_id):
    with db.transaction() as session:
        return [
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.event_id == event_id,
                    *(
                        [OutboxEvent.type.in_(("ballot.submitted", "ballot.revised"))]
                        if model is OutboxEvent
                        else []
                    ),
                )
            )
            for model in (Ballot, BallotRevision, IdempotencyRecord, BallotAudit, OutboxEvent)
        ]


def test_receipt_revision_count_and_original_retry(scoring, event_db):
    db, _ = event_db
    mobile = scoring[1][0]
    key = str(uuid4())
    assert mobile.get(url(scoring)).json()["error"]["code"] == "BALLOT_NOT_FOUND"
    first = put(scoring, key=key, body=payload("0"))
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1 and first.json()["total_score"] == "0.00"
    assert first.headers["cache-control"] == "no-store"
    assert mobile.get(url(scoring)).json() == first.json()
    revised = put(scoring, body=payload("90", 1))
    assert revised.status_code == 200 and revised.json()["revision"] == 2
    assert revised.json()["ballot_id"] == first.json()["ballot_id"]
    assert revised.json()["receipt_id"] != first.json()["receipt_id"]
    assert put(scoring, key=key, body=payload("0.000")).json() == first.json()
    assert mobile.get(url(scoring), headers={"Idempotency-Key": key}).json() == first.json()
    assert mobile.get(url(scoring)).json() == revised.json()
    assert put(scoring, body=payload("80", 1)).json()["error"]["code"] == "REVISION_CONFLICT"
    assert put(scoring, key=key).json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert counts(db, scoring[0]["event"]["id"]) == [1, 2, 2, 2, 2]
    with db.transaction() as session:
        events = list(
            session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_id == scoring[0]["event"]["id"],
                    OutboxEvent.type.in_(("ballot.submitted", "ballot.revised")),
                )
                .order_by(OutboxEvent.version)
            )
        )
        assert [len(e.payload["streams"]) for e in events] == [4, 2]
        assert all(e.payload["data"] == {} for e in events)
        assert [e.type for e in events] == ["ballot.submitted", "ballot.revised"]
        assert all(e.delivered_at is None and "scores" not in e.payload for e in events)
        audit = session.scalar(
            select(BallotAudit).where(
                BallotAudit.action == "ballot.submitted",
                BallotAudit.ballot_id == first.json()["ballot_id"],
            )
        )
        assert audit.request_id == first.headers["x-request-id"]


def test_receipt_survives_app_restart_and_is_private(scoring, clients):
    key = str(uuid4())
    first = put(scoring, key=key)
    assert first.status_code == 200
    assert scoring[1][1].get(url(scoring), headers={"Idempotency-Key": key}).status_code == 404
    assert scoring[1][1].get(url(scoring)).status_code == 404
    assert clients[0].get(url(scoring)).status_code == 401
    assert put(scoring, key=key, judge=1, body=payload("70")).status_code == 200
    with TestClient(
        create_app(clients[0].app.state.settings), base_url="https://score.test"
    ) as restarted:
        restarted.cookies.update(scoring[1][0].cookies)
        restarted.headers.update(scoring[1][0].headers)
        assert (
            restarted.put(url(scoring), json=payload(), headers={"Idempotency-Key": key}).json()
            == first.json()
        )


def test_boundary_pause_finish_and_old_task(scoring, clients, event_db):
    db, _ = event_db
    mobile = scoring[1][0]
    key = str(uuid4())
    mobile.app.state.clock = lambda: scoring[2] + timedelta(seconds=60, microseconds=-1)
    first = put(scoring, key=key)
    assert first.status_code == 200
    mobile.app.state.clock = lambda: scoring[2] + timedelta(seconds=60)
    assert put(scoring, body=payload("80", 1)).json()["error"]["code"] == "DEADLINE_EXCEEDED"
    assert put(scoring, key=key).json() == first.json()
    # 11 的收评接口尚未实现；在事务中设置其目标状态以验证写入边界。
    with db.transaction() as session:
        session.get(ScoringRound, scoring[0]["rounds"][0]["id"]).status = "CLOSED"
    assert control(clients[0], scoring[0]["rounds"][1], "open").status_code == 200
    assert put(scoring, body=payload("80", 1)).json()["error"]["code"] == "ROUND_NOT_OPEN"
    assert put(scoring, index=1, key=key).json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    mobile.app.state.clock = lambda: scoring[2]
    assert control(clients[0], scoring[0]["rounds"][1], "pause", 2).status_code == 200
    assert put(scoring, index=1).json()["error"]["code"] == "ROUND_NOT_OPEN"
    with db.transaction() as session:
        session.get(Event, scoring[0]["event"]["id"]).status = "FINISHED"
    assert put(scoring, key=key).json() == first.json()
    assert put(scoring, index=1).json()["error"]["code"] == "EVENT_NOT_RUNNING"
    assert mobile.get(url(scoring)).json() == first.json()


def test_bad_inputs_rule_and_headers_do_not_write(scoring, event_db):
    mobile = scoring[1][0]
    for value in (None, "", "NaN", "Infinity", -1, 90.0, True, "1e1", "-1", "1000.00", "1.01"):
        response = put(scoring, body=payload(value))
        assert response.status_code == 422, (value, response.text)
    for scores in ([], [{"criterion_id": "unknown", "value": "1"}], payload()["scores"] * 2):
        assert put(scoring, body={**payload(), "scores": scores}).status_code == 422
    assert put(scoring, body=payload(rule=2)).json()["error"]["code"] == "RULE_VERSION_MISMATCH"
    assert mobile.put(url(scoring), json=payload()).status_code == 422
    assert put(scoring, key="invalid").status_code == 422
    assert (
        mobile.put(
            url(scoring),
            json=payload(),
            headers=[("Idempotency-Key", str(uuid4())), ("Idempotency-Key", str(uuid4()))],
        ).status_code
        == 422
    )
    assert (
        mobile.put(
            url(scoring),
            json=payload(),
            headers={"Idempotency-Key": str(uuid4()), "X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    assert (
        mobile.put(
            url(scoring),
            json=payload(),
            headers={"Idempotency-Key": str(uuid4()), "Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert put(scoring, body={**payload(), "judge_id": "other"}).status_code == 422
    assert counts(event_db[0], scoring[0]["event"]["id"]) == [0] * 5


def test_multidimensional_score_and_canonical_order(scoring, event_db):
    db, _ = event_db
    with db.transaction() as session:
        snapshot = session.get(EventSnapshot, scoring[0]["snapshot"]["id"])
        snapshot.scoring_rule = {
            "mode": "multi",
            "algorithm": "mean",
            "expected_count": 2,
            "minimum_ballots": 2,
            "criteria": [
                {
                    "criterion_id": "content",
                    "name": "内容",
                    "maximum": "100",
                    "weight": "0.5",
                    "step": "0.1",
                },
                {
                    "criterion_id": "performance",
                    "name": "表现",
                    "maximum": "10",
                    "weight": "0.3",
                    "step": "0.1",
                },
                {
                    "criterion_id": "innovation",
                    "name": "创新",
                    "maximum": "20",
                    "weight": "0.2",
                    "step": "0.1",
                },
            ],
        }
    body = {
        **payload(),
        "scores": [
            {"criterion_id": key, "value": val}
            for key, val in (("content", "90.0"), ("performance", "8.0"), ("innovation", "18.0"))
        ],
    }
    key = str(uuid4())
    response = put(scoring, body=body, key=key)
    assert response.status_code == 200 and response.json()["total_score"] == "87.00"
    body["scores"].reverse()
    assert put(scoring, body=body, key=key).json() == response.json()
    assert scoring[1][0].get(url(scoring)).json() == response.json()
    with db.transaction() as session:
        revision = session.get(BallotRevision, response.json()["receipt_id"])
        assert revision.computed_total == Decimal("87")
        assert {v["criterion_id"] for v in revision.scores} == {
            "content",
            "performance",
            "innovation",
        }


def test_revisions_disabled_and_unlimited_frozen_rule(scoring, event_db):
    db, _ = event_db
    with db.transaction() as session:
        session.get(EventSnapshot, scoring[0]["snapshot"]["id"]).allow_revisions = False
        session.get(Event, scoring[0]["event"]["id"]).allow_revisions = True
        session.get(ScoringRound, scoring[0]["rounds"][0]["id"]).deadline_at = None
    scoring[1][0].app.state.clock = lambda: scoring[2] + timedelta(hours=2)
    key = str(uuid4())
    first = put(scoring, key=key)
    assert first.status_code == 200
    assert put(scoring, key=key).json() == first.json()
    assert put(scoring, body=payload("80", 1)).json()["error"]["code"] == "REVISIONS_DISABLED"


@pytest.mark.parametrize("mode", ["same_key", "different_content", "revision", "two_judges"])
def test_concurrent_submissions(scoring, event_db, mode):
    db, _ = event_db
    people = [principal(scoring, db), principal(scoring, db, 1)]
    if mode == "revision":
        assert put(scoring).status_code == 200
    gate = Barrier(2)
    common_key = str(uuid4())

    def run(index):
        body = BallotInput.model_validate(
            payload("90" if mode == "same_key" else str(80 + index), 1 if mode == "revision" else 0)
        )
        gate.wait(timeout=5)
        try:
            return service.submit_ballot(
                db,
                people[index if mode == "two_judges" else 0],
                scoring[0]["rounds"][0]["id"],
                body,
                common_key if mode in {"same_key", "different_content"} else str(uuid4()),
                uuid4().hex,
                lambda: scoring[2],
            )
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, (0, 1)))
    if mode == "same_key":
        assert outcomes[0] == outcomes[1]
        assert not isinstance(outcomes[0], str)
    elif mode in {"different_content", "revision"}:
        assert sum(not isinstance(result, str) for result in outcomes) == 1
        assert (
            "IDEMPOTENCY_CONFLICT" if mode == "different_content" else "REVISION_CONFLICT"
        ) in outcomes
    else:
        assert all(not isinstance(result, str) for result in outcomes)
    expected = (
        [2] * 5 if mode == "two_judges" else ([1, 2, 2, 2, 2] if mode == "revision" else [1] * 5)
    )
    assert counts(db, scoring[0]["event"]["id"]) == expected


@pytest.mark.parametrize("model", [BallotRevision, IdempotencyRecord, BallotAudit, OutboxEvent])
def test_failure_rolls_back_all_writes_and_key_is_reusable(scoring, event_db, model):
    db, _ = event_db
    key = str(uuid4())

    def fail(*args):
        raise RuntimeError("simulated write failure")

    sa_event.listen(model, "before_insert", fail)
    try:
        assert put(scoring, key=key).status_code == 500
    finally:
        sa_event.remove(model, "before_insert", fail)
    assert counts(db, scoring[0]["event"]["id"]) == [0] * 5
    with db.transaction() as session:
        assert session.get(Event, scoring[0]["event"]["id"]).version == 2
    assert put(scoring, key=key).status_code == 200
    assert counts(db, scoring[0]["event"]["id"]) == [1] * 5


@pytest.mark.parametrize("code,failures", [(1213, 1), (1205, 2), (1213, 3), (2006, 1)])
def test_transaction_retry_is_bounded_and_whole(scoring, event_db, code, failures):
    attempts = []

    def fail(*args):
        attempts.append(1)
        if len(attempts) <= failures:
            raise OperationalError("redacted", {}, DriverError(code, "simulated"))

    sa_event.listen(OutboxEvent, "before_insert", fail)
    try:
        result = put(scoring)
    finally:
        sa_event.remove(OutboxEvent, "before_insert", fail)
    success = code != 2006 and failures < 3
    assert result.status_code == (200 if success else 503)
    assert len(attempts) == (failures + 1 if success else (1 if code == 2006 else 3))
    assert counts(event_db[0], scoring[0]["event"]["id"]) == ([1] * 5 if success else [0] * 5)
    if not success:
        assert result.headers["retry-after"] == "3"


def test_revocation_rechecked_after_dependency_and_existing_receipt(scoring, event_db, clients):
    db, _ = event_db
    person = principal(scoring, db)
    key = str(uuid4())
    assert put(scoring, key=key).status_code == 200
    credential = scoring[0]["generated_credentials"][0]
    reset = clients[0].post(
        f"/api/v1/events/{person.event_id}/judges/{credential['judge_id']}/reset-credential",
        json={"reason": "换手机"},
    )
    assert reset.status_code == 200
    assert put(scoring, key=key).status_code == 401
    with pytest.raises(APIError) as error:
        service.submit_ballot(
            db,
            person,
            scoring[0]["rounds"][0]["id"],
            BallotInput.model_validate(payload()),
            key,
            uuid4().hex,
            lambda: scoring[2],
        )
    assert error.value.code == "SESSION_EXPIRED"
    # 使用新凭证重新登录后，旧回执归属仍为同一评委。
    mobile = scoring[1][0]
    bootstrap = mobile.get("/api/v1/judge-sessions/csrf").json()["csrf_token"]
    mobile.headers["X-CSRF-Token"] = bootstrap
    verified = mobile.post(
        "/api/v1/judge-sessions/verify",
        json={"public_code": scoring[0]["event"]["public_code"], "code": reset.json()["code"]},
    )
    exchanged = mobile.post(
        "/api/v1/judge-sessions/exchange",
        json={"confirmation_token": verified.json()["confirmation_token"]},
    )
    assert exchanged.status_code == 200
    mobile.headers["X-CSRF-Token"] = exchanged.json()["csrf_token"]
    assert mobile.get(url(scoring)).json()["revision"] == 1
    assert put(scoring, key=key).status_code == 200


@pytest.mark.parametrize("expire_session", [False, True])
def test_clock_checked_after_waiting_for_task_lock(scoring, event_db, expire_session):
    db, _ = event_db
    person = principal(scoring, db)
    row_id = scoring[0]["rounds"][0]["id"]
    current = [scoring[2]]
    if expire_session:
        with db.transaction() as session:
            session.get(JudgeSession, person.token_hash).expires_at = scoring[2] + timedelta(
                seconds=30
            )
    waiting = ThreadEvent()

    def observe(conn, cursor, statement, params, context, many):
        if "score_rounds" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def run():
        try:
            service.submit_ballot(
                db,
                person,
                row_id,
                BallotInput.model_validate(payload()),
                str(uuid4()),
                uuid4().hex,
                lambda: current[0],
            )
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as session:
            session.execute(select(ScoringRound).where(ScoringRound.id == row_id).with_for_update())
            sa_event.listen(db.engine, "before_cursor_execute", observe)
            future = pool.submit(run)
            assert waiting.wait(timeout=5)
            current[0] += timedelta(seconds=60)
        assert future.result(timeout=5) == (
            "SESSION_EXPIRED" if expire_session else "DEADLINE_EXCEEDED"
        )
    sa_event.remove(db.engine, "before_cursor_execute", observe)
    assert counts(db, person.event_id) == [0] * 5


def test_membership_foreign_key_and_http_qualification(scoring, event_db):
    db, _ = event_db
    person = principal(scoring, db)
    row_id = scoring[0]["rounds"][0]["id"]
    with db.transaction() as session:
        session.execute(
            delete(RoundJudge).where(
                RoundJudge.round_id == row_id, RoundJudge.event_judge_id == person.judge_id
            )
        )
    assert put(scoring).status_code == 403
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.add(
            Ballot(
                id=uuid4().hex,
                event_id=person.event_id,
                round_id=row_id,
                judge_id=person.judge_id,
                current_revision=1,
            )
        )


def test_pool_saturation_returns_explicit_retry_response(scoring):
    db = scoring[1][0].app.state.database
    with ExitStack() as stack:
        for _ in range(10):
            stack.enter_context(db.engine.connect())
        result = put(scoring)
        assert result.status_code == 503 and result.headers["retry-after"] == "3"
    assert put(scoring).status_code == 200


def test_response_lost_after_commit_recovers_original_receipt(scoring, event_db, monkeypatch):
    original = service.submit_once
    receipts = []

    def lost_response(*args):
        result = original(*args)
        receipts.append(result)
        raise OperationalError("redacted", {}, DriverError(2013, "connection lost after commit"))

    monkeypatch.setattr(service, "submit_once", lost_response)
    key = str(uuid4())
    assert put(scoring, key=key).status_code == 503
    assert len(receipts) == 1
    assert counts(event_db[0], scoring[0]["event"]["id"]) == [1] * 5
    monkeypatch.setattr(service, "submit_once", original)
    assert put(scoring, key=key).json() == receipts[0].model_dump(mode="json")
    assert scoring[1][0].get(url(scoring), headers={"Idempotency-Key": key}).json() == receipts[
        0
    ].model_dump(mode="json")


def test_real_lock_timeouts_are_bounded_then_original_key_succeeds(
    scoring, event_db, mysql_settings
):
    db, _ = event_db
    person = principal(scoring, db)
    retry_db = Database(
        mysql_settings.model_copy(update={"db_lock_wait_timeout": 1}), role="worker"
    )
    attempts = []

    def observe(conn, cursor, statement, params, context, many):
        if "score_events" in statement and "FOR UPDATE" in statement:
            attempts.append(1)

    sa_event.listen(retry_db.engine, "before_cursor_execute", observe)
    key = str(uuid4())

    def run():
        try:
            return service.submit_ballot(
                retry_db,
                person,
                scoring[0]["rounds"][0]["id"],
                BallotInput.model_validate(payload()),
                key,
                uuid4().hex,
                lambda: scoring[2],
            )
        except APIError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with db.transaction() as session:
                session.execute(select(Event).where(Event.id == person.event_id).with_for_update())
                assert pool.submit(run).result(timeout=8) == "SERVICE_UNAVAILABLE"
        assert len(attempts) == 3 and retry_db.engine.pool.checkedout() == 0
        assert counts(db, person.event_id) == [0] * 5
        assert run().revision == 1
    finally:
        retry_db.dispose()


def test_pause_and_submission_serialize(scoring, event_db):
    db, owners = event_db
    person = principal(scoring, db)
    gate = Barrier(2)
    row = scoring[0]["rounds"][0]

    def run(action):
        gate.wait(timeout=5)
        if action == "pause":
            return round_service.control(
                db,
                owners[0],
                row["id"],
                "pause",
                ControlInput(expected_version=2),
                uuid4().hex,
                lambda: scoring[2],
            ).status
        try:
            return service.submit_ballot(
                db,
                person,
                row["id"],
                BallotInput.model_validate(payload()),
                str(uuid4()),
                uuid4().hex,
                lambda: scoring[2],
            ).revision
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        paused, submitted = list(pool.map(run, ("pause", "submit")))
    assert paused == "PAUSED" and submitted in (1, "ROUND_NOT_OPEN")
    assert counts(db, person.event_id) == ([1] * 5 if submitted == 1 else [0] * 5)


def test_cross_event_rejected_and_copy_has_no_ballots(scoring, clients, event_db):
    assert put(scoring).status_code == 200
    owner = clients[0]
    copied = owner.post(f"/api/v1/events/{scoring[0]['event']['id']}/copy").json()
    published = owner.post(f"/api/v1/events/{copied['id']}/publish")
    assert published.status_code == 200
    foreign_url = f"/api/v1/rounds/{published.json()['rounds'][0]['id']}/my-ballot"
    assert (
        scoring[1][0]
        .put(foreign_url, json=payload(), headers={"Idempotency-Key": str(uuid4())})
        .status_code
        == 404
    )

    assert scoring[1][0].get(foreign_url).status_code == 404
    assert counts(event_db[0], copied["id"]) == [0] * 5
    with pytest.raises(IntegrityError), event_db[0].transaction() as session:
        person = scoring[0]["generated_credentials"][0]
        session.add(
            Ballot(
                id=uuid4().hex,
                event_id=copied["id"],
                round_id=scoring[0]["rounds"][0]["id"],
                judge_id=person["judge_id"],
                current_revision=1,
            )
        )


def test_failed_revision_keeps_previous_effective_ballot(scoring, event_db):
    original_key = str(uuid4())
    original = put(scoring, key=original_key)

    def fail(*args):
        raise RuntimeError("outbox unavailable")

    sa_event.listen(OutboxEvent, "before_insert", fail)
    try:
        assert put(scoring, body=payload("70", 1)).status_code == 500
    finally:
        sa_event.remove(OutboxEvent, "before_insert", fail)
    assert scoring[1][0].get(url(scoring)).json() == original.json()
    assert put(scoring, key=original_key).json() == original.json()
    assert counts(event_db[0], scoring[0]["event"]["id"]) == [1] * 5
