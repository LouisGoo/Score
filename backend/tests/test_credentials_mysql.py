import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.core.security import verify_password
from score_api.credentials import service
from score_api.credentials.schemas import CredentialInput
from score_api.db import utc_now
from score_api.events.models import Event, EventAudit, EventJudge

pytestmark = pytest.mark.mysql
BASE = "/api/v1/events"


def draft(client):
    event = client.post(BASE, json={"title": "凭证测试"}).json()
    url = f"{BASE}/{event['id']}"
    judges = [
        client.post(url + "/judges", json={"number": n, "name": n}).json() for n in ("001", "002")
    ]
    return event, url, judges


def test_manual_auto_metadata_no_plaintext_or_hash_leaks(clients, event_db, caplog):
    owner, _ = clients
    db, _ = event_db
    event, url, judges = draft(owner)
    target = f"{url}/judges/{judges[0]['id']}"
    assert not judges[0]["credential_is_set"]
    response = owner.put(target + "/credential", json={"code": " abcd1234 "})
    assert response.status_code == 200
    assert response.json()["code"] == "ABCD1234"
    assert response.headers["cache-control"] == "no-store"
    info = owner.get(target).json()
    assert info["credential_is_set"] and info["number"] == "001"
    assert info["credential_source"] == "manual" and info["credential_version"] == 1
    with db.transaction() as session:
        row = session.get(EventJudge, judges[0]["id"])
        assert verify_password("ABCD1234", row.credential_hash)
        assert len(row.credential_lookup) == 32
        private = ("ABCD1234", row.credential_hash, row.credential_lookup.hex())
        audits = list(session.scalars(select(EventAudit).where(EventAudit.event_id == event["id"])))
        visible = json.dumps([info, *[a.before for a in audits], *[a.after for a in audits]])
        for value in private:
            assert value not in visible and value not in caplog.text
    response = owner.put(target + "/credential", json={})
    assert len(response.json()["code"]) == 12
    assert response.json()["credential_version"] == 2
    assert response.json()["credential_source"] == "generated"
    assert "code" not in owner.get(url + "/judges").json()[0]


def test_uniqueness_permissions_states_and_validation(clients, event_db):
    owner, other = clients
    db, _ = event_db
    event, url, judges = draft(owner)
    urls = [f"{url}/judges/{j['id']}/credential" for j in judges]
    assert owner.put(urls[0], json={"code": "ABCD1234"}).status_code == 200
    assert (
        owner.put(urls[1], json={"code": "abcd1234"}).json()["error"]["code"]
        == "CREDENTIAL_CONFLICT"
    )
    assert owner.put(urls[1], json={"code": "12345"}).status_code == 422
    assert other.put(urls[0], json={}).status_code == 404
    another, another_url, _ = draft(owner)
    assert (
        owner.put(f"{another_url}/judges/{judges[0]['id']}/credential", json={}).status_code == 404
    )
    assert owner.put(urls[0], json={}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert owner.put(urls[0], json={}, headers={"Origin": "https://evil.test"}).status_code == 403
    with db.transaction() as session:
        target = session.scalar(select(EventJudge).where(EventJudge.event_id == another["id"]))
        target_id = target.id
    assert (
        owner.put(
            f"{another_url}/judges/{target_id}/credential", json={"code": "ABCD1234"}
        ).status_code
        == 200
    )
    for status in ("READY", "RUNNING", "FINISHED", "ARCHIVED"):
        with db.transaction() as session:
            session.get(Event, event["id"]).status = status
        assert owner.put(urls[0], json={}).json()["error"]["code"] == "EVENT_NOT_DRAFT"


def test_concurrent_duplicate_and_database_constraint(clients, event_db):
    owner, _ = clients
    db, owners = event_db
    event, _, judges = draft(owner)
    barrier = Barrier(2)

    def write(judge):
        barrier.wait(timeout=5)
        try:
            service.set_credential(
                db,
                owner.app.state.settings,
                owners[0],
                event["id"],
                judge["id"],
                CredentialInput(code="ABCD1234"),
                uuid4().hex,
                utc_now,
            )
            return "ok"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, judges)) == ["CREDENTIAL_CONFLICT", "ok"]
    with pytest.raises(IntegrityError), db.transaction() as session:
        rows = list(session.scalars(select(EventJudge).where(EventJudge.event_id == event["id"])))
        source = next(r for r in rows if r.credential_hash)
        target = next(r for r in rows if not r.credential_hash)
        for key in (
            "credential_hash",
            "credential_lookup",
            "credential_source",
            "credential_version",
            "credential_updated_at",
        ):
            setattr(target, key, getattr(source, key))


def test_audit_failure_rolls_back_and_missing_key_fails_closed(clients, event_db):
    owner, _ = clients
    db, _ = event_db
    _, url, judges = draft(owner)
    target = f"{url}/judges/{judges[0]['id']}"

    def fail(*_):
        raise RuntimeError("audit failure")

    sa_event.listen(EventAudit, "before_insert", fail)
    try:
        assert owner.put(target + "/credential", json={}).status_code == 500
    finally:
        sa_event.remove(EventAudit, "before_insert", fail)
    assert not owner.get(target).json()["credential_is_set"]
    owner.app.state.settings.credential_hmac_key = None
    assert (
        owner.put(target + "/credential", json={}).json()["error"]["code"]
        == "CREDENTIAL_KEY_UNAVAILABLE"
    )
    with db.transaction() as session:
        assert session.get(EventJudge, judges[0]["id"]).credential_version == 0


def test_generated_collision_retries_without_overwriting(clients, monkeypatch):
    owner, _ = clients
    _, url, judges = draft(owner)
    urls = [f"{url}/judges/{j['id']}/credential" for j in judges]
    owner.put(urls[0], json={"code": "ABCD1234"})
    candidates = iter(["ABCD1234", "SECOND123"])
    monkeypatch.setattr(
        "score_api.credentials.security.generate_credential", lambda: next(candidates)
    )
    assert owner.put(urls[1], json={}).json()["code"] == "SECOND123"
