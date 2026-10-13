from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from threading import Event as ThreadEvent
from uuid import uuid4

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.db import utc_now
from score_api.events.models import Event, EventAudit
from score_api.rounds import service
from score_api.rounds.models import ScoringRound
from score_api.rounds.schemas import ControlInput

pytestmark = pytest.mark.mysql
NOW = utc_now()


def control(client, row, action, version=1, **extra):
    return client.post(
        f"/api/v1/rounds/{row['id']}/{action}",
        json={
            "expected_version": version,
            **extra,
        },
    )


def test_clock_pause_resume_and_versions(rounds_event, clients, event_db):
    owner, _ = clients
    row = rounds_event["rounds"][0]
    owner.app.state.clock = lambda: NOW
    opened = control(owner, row, "open")
    assert opened.status_code == 200, opened.text
    assert opened.json()["version"] == 2
    assert opened.json()["deadline_at"] == (NOW + timedelta(seconds=60)).isoformat().replace(
        "+00:00", "Z"
    )
    owner.app.state.clock = lambda: NOW + timedelta(seconds=10, microseconds=123456)
    paused = control(owner, row, "pause", 2).json()
    assert paused["deadline_at"] is None
    assert Decimal(paused["remaining_seconds"]) == Decimal("49.876544")
    assert control(owner, row, "pause", 2).json()["error"]["code"] == "VERSION_CONFLICT"
    assert control(owner, row, "pause", 3).json()["error"]["code"] == "ROUND_STATE_CONFLICT"
    assert (
        control(owner, rounds_event["rounds"][1], "open").json()["error"]["code"]
        == "ACTIVE_ROUND_EXISTS"
    )
    owner.app.state.clock = lambda: NOW + timedelta(minutes=10)
    resumed = control(owner, row, "resume", 3).json()
    deadline = NOW + timedelta(minutes=10, seconds=49, microseconds=876544)
    assert resumed["deadline_at"] == deadline.isoformat().replace("+00:00", "Z")
    owner.app.state.clock = lambda: deadline
    assert control(owner, row, "pause", 4).json()["error"]["code"] == "DEADLINE_EXCEEDED"
    assert owner.get(f"/api/v1/rounds/{row['id']}").json()["version"] == 4
    db, _ = event_db
    with db.transaction() as session:
        event = session.get(Event, rounds_event["event"]["id"])
        assert event.status == "RUNNING" and event.version == 4
        assert (
            len(
                list(
                    session.scalars(
                        select(EventAudit).where(
                            EventAudit.event_id == event.id, EventAudit.action.like("round.%")
                        )
                    )
                )
            )
            == 3
        )


def test_unlimited_uses_frozen_config(rounds_event, clients, event_db):
    from score_api.events.models import EventSnapshot

    db, _ = event_db
    row = rounds_event["rounds"][0]
    with db.transaction() as session:
        session.get(EventSnapshot, row["rule_id"]).duration_seconds = None
        session.get(Event, row["event_id"]).duration_seconds = 9
    owner = clients[0]
    for action, version in (("open", 1), ("pause", 2), ("resume", 3)):
        response = control(owner, row, action, version)
        assert response.status_code == 200
        assert response.json()["deadline_at"] is None
        assert response.json()["remaining_seconds"] is None


def test_skip_reason_permissions_and_input(rounds_event, clients, event_db):
    owner, other = clients
    row = rounds_event["rounds"][0]
    path = f"/api/v1/rounds/{row['id']}"
    assert other.get(path).status_code == 404
    assert control(other, row, "open").status_code == 404
    assert control(owner, row, "skip").status_code == 422
    assert control(owner, row, "skip", reason=" ").status_code == 422
    assert control(owner, row, "open", True).status_code == 422
    assert (
        owner.post(
            path + "/open", json={"expected_version": 1}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    skipped = control(owner, row, "skip", reason="对象缺席")
    assert skipped.status_code == 200 and skipped.json()["status"] == "SKIPPED"
    assert control(owner, row, "open", 2).status_code == 409
    db, _ = event_db
    with db.transaction() as session:
        audit = session.scalar(
            select(EventAudit).where(
                EventAudit.action == "round.skip", EventAudit.target_id == row["id"]
            )
        )
        assert audit.after["reason"] == "对象缺席"
        assert audit.request_id == skipped.headers["x-request-id"]


@pytest.mark.parametrize("action", ["open", "resume"])
def test_concurrent_control_only_one_wins(rounds_event, event_db, action):
    db, owners = event_db
    rows = rounds_event["rounds"]
    if action == "resume":
        with db.transaction() as session:
            session.get(ScoringRound, rows[0]["id"]).status = "PAUSED"
        targets = [rows[0], rows[0]]
    else:
        targets = rows
    gate = Barrier(2)

    def run(row):
        gate.wait(timeout=5)
        try:
            return service.control(
                db,
                owners[0],
                row["id"],
                action,
                ControlInput(expected_version=1),
                uuid4().hex,
                lambda: NOW,
            ).status
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, targets))
    assert results.count("OPEN") == 1
    assert ("VERSION_CONFLICT" if action == "resume" else "ACTIVE_ROUND_EXISTS") in results
    with db.transaction() as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(ScoringRound).where(
                            ScoringRound.event_id == rows[0]["event_id"],
                            ScoringRound.status.in_(("OPEN", "PAUSED")),
                        )
                    )
                )
            )
            == 1
        )


def test_database_constraint_blocks_open_plus_paused(rounds_event, event_db):
    db, _ = event_db
    rows = rounds_event["rounds"]
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.get(ScoringRound, rows[0]["id"]).status = "OPEN"
        session.get(ScoringRound, rows[1]["id"]).status = "PAUSED"


def test_audit_failure_rolls_back(rounds_event, event_db, monkeypatch):
    db, owners = event_db
    row = rounds_event["rounds"][0]

    def fail(*args):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "audit", fail)
    with pytest.raises(RuntimeError):
        service.control(
            db,
            owners[0],
            row["id"],
            "open",
            ControlInput(expected_version=1),
            uuid4().hex,
            lambda: NOW,
        )
    with db.transaction() as session:
        saved = session.get(ScoringRound, row["id"])
        assert saved.status == "PENDING" and saved.version == 1 and saved.deadline_at is None
        assert session.get(Event, row["event_id"]).status == "READY"


def test_pause_checks_clock_after_waiting_for_round_lock(rounds_event, event_db):
    db, owners = event_db
    row = rounds_event["rounds"][0]
    service.control(
        db, owners[0], row["id"], "open", ControlInput(expected_version=1), uuid4().hex, lambda: NOW
    )
    waiting = ThreadEvent()
    current = [NOW + timedelta(seconds=1)]

    def observe(conn, cursor, statement, parameters, context, many):
        if "score_rounds" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def pause():
        try:
            service.control(
                db,
                owners[0],
                row["id"],
                "pause",
                ControlInput(expected_version=2),
                uuid4().hex,
                lambda: current[0],
            )
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as session:
            session.execute(
                select(ScoringRound).where(ScoringRound.id == row["id"]).with_for_update()
            )
            sa_event.listen(db.engine, "before_cursor_execute", observe)
            future = pool.submit(pause)
            assert waiting.wait(timeout=5)
            current[0] = NOW + timedelta(seconds=60)
        assert future.result(timeout=5) == "DEADLINE_EXCEEDED"
    sa_event.remove(db.engine, "before_cursor_execute", observe)
