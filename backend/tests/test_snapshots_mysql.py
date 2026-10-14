import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event as Signal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event as sa_event
from sqlalchemy import select
from test_ballots_mysql import payload, principal, put
from test_ballots_mysql import scoring as scoring
from test_results_mysql import act, event_action

from score_api.core.errors import APIError
from score_api.events.models import Event, EventAudit
from score_api.outbox.models import OutboxEvent
from score_api.snapshots import service
from score_api.snapshots.models import ScreenGrant
from score_api.worker import DeadlineWorker

pytestmark = pytest.mark.mysql


def grant(owner, event_id, **body):
    result = owner.post(f"/api/v1/events/{event_id}/screen-grants", json=body)
    assert result.status_code == 201, result.text
    return result.json()


def screen(client, credential):
    return client.get(
        f"/api/v1/screens/{credential['id']}/snapshot",
        headers={"Authorization": "Bearer " + credential["token"]},
    )


def snap(client, event_id, role="admin"):
    prefix = "/judge" if role == "judge" else ""
    response = client.get(f"/api/v1{prefix}/events/{event_id}/snapshot")
    assert response.status_code == 200, response.text
    return response.json()


def setting(owner, event_id, mode, round_id=None, **extra):
    version = owner.get(f"/api/v1/events/{event_id}").json()["version"]
    return owner.put(
        f"/api/v1/events/{event_id}/screen",
        json={
            "expected_version": version,
            "mode": mode,
            "round_id": round_id,
            "title": "现场大屏",
            "theme": "dark",
            "show_public_qr": True,
            "leaderboard_limit": 10,
            **extra,
        },
    )


def test_private_scores_and_role_versions(scoring, clients):
    owner = clients[0]
    first, second = scoring[1]
    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    credential = grant(owner, event_id)
    before = [
        snap(owner, event_id),
        snap(first, event_id, "judge"),
        snap(second, event_id, "judge"),
        screen(first, credential).json(),
    ]
    receipt = put(scoring, body=payload("73.1")).json()
    submitted = [
        snap(owner, event_id),
        snap(first, event_id, "judge"),
        snap(second, event_id, "judge"),
        screen(first, credential).json(),
    ]
    assert all(b["version"] + 1 == a["version"] for b, a in zip(before, submitted, strict=True))
    assert submitted[2]["my_ballots"] == []
    assert submitted[3]["current_round"]["submitted_count"] == 1
    revised_receipt = put(scoring, body=payload("74.2", 1)).json()
    revised = [
        snap(owner, event_id),
        snap(first, event_id, "judge"),
        snap(second, event_id, "judge"),
        screen(first, credential).json(),
    ]
    assert [r["version"] - b["version"] for r, b in zip(revised, submitted, strict=True)] == [
        1,
        1,
        0,
        0,
    ]
    assert len(revised[1]["my_ballots"][0]["receipts"]) == 2
    assert len(revised[0]["ballots"][0]["receipts"]) == 2
    assert revised[2] == submitted[2] and revised[3] == submitted[3]
    for result in revised[2:]:
        text = json.dumps(result)
        for forbidden in (
            receipt["receipt_id"],
            revised_receipt["receipt_id"],
            "73.1",
            "74.2",
            "exclusion",
            "credential",
            "owner_id",
        ):
            assert forbidden not in text
        assert result["published_results"] == [] and result["ranking"] == []
    assert put(scoring, judge=1, body=payload("80")).status_code == 200
    assert act(owner, rid, "close").status_code == 200
    assert snap(owner, event_id)["results"][0]["calculation"]["final_score"] == "77.10"
    assert snap(second, event_id, "judge")["published_results"] == []
    assert screen(second, credential).json()["published_results"] == []
    assert act(owner, rid, "publish").status_code == 200
    public = screen(second, credential).json()
    assert public["display"]["mode"] == "result"
    assert public["published_results"][0]["final_score"] == "77.10"
    assert public["published_results"] == snap(second, event_id, "judge")["published_results"]
    assert all(
        f'"{k}":' not in json.dumps(public) for k in ("scores", "ballots", "judge_id", "receipt_id")
    )


def test_grant_auth_isolated_revocation_expiry_and_no_plaintext(scoring, clients, event_db):
    owner, other = clients
    mobile = scoring[1][0]
    event_id = scoring[0]["event"]["id"]
    base = f"/api/v1/events/{event_id}"
    credential = grant(owner, event_id, ttl_seconds=60)
    route = f"/api/v1/screens/{credential['id']}/snapshot"
    assert mobile.get(route).status_code == 401
    assert mobile.get(route + "?token=" + credential["token"]).status_code == 401
    assert screen(mobile, {**credential, "token": "x" * 43}).status_code == 401
    assert screen(mobile, {**credential, "id": "missing"}).status_code == 401
    assert mobile.get(base + "/snapshot").status_code == 401
    assert other.get(base + "/snapshot").status_code == 404
    assert other.post(base + "/screen-grants", json={}).status_code == 404
    assert other.delete(base + f"/screen-grants/{credential['id']}").status_code == 404
    assert mobile.post(base + "/screen-grants", json={}).status_code == 401
    assert mobile.get(f"/api/v1/judge/events/{uuid4().hex}/snapshot").status_code == 404
    assert (
        owner.post(base + "/screen-grants", json={}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    listed = owner.get(base + "/screen-grants")
    assert credential["token"] not in listed.text and "token_hash" not in listed.text
    with event_db[0].transaction() as session:
        stored = session.get(ScreenGrant, credential["id"])
        assert stored.token_hash != credential["token"]
        logs = list(session.scalars(select(EventAudit).where(EventAudit.event_id == event_id)))
        assert credential["token"] not in json.dumps([r.after for r in logs])
    mobile.app.state.clock = lambda: scoring[2] + timedelta(seconds=60)
    assert screen(mobile, credential).status_code == 401
    mobile.app.state.clock = lambda: scoring[2]
    assert screen(mobile, credential).status_code == 200
    assert owner.delete(base + f"/screen-grants/{credential['id']}").status_code == 204
    assert owner.delete(base + f"/screen-grants/{credential['id']}").status_code == 204
    assert screen(mobile, credential).status_code == 401
    assert grant(owner, event_id)["token"] != credential["token"]


def test_modes_versions_worker_and_ended_read_only(scoring, clients, event_db):
    owner = clients[0]
    mobile = scoring[1][0]
    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    credential = grant(owner, event_id)
    assert screen(mobile, credential).json()["display"]["mode"] == "progress"
    assert setting(owner, event_id, "result", rid).status_code == 409
    assert setting(owner, event_id, "ended").status_code == 409
    assert setting(owner, event_id, "paused", "foreign").status_code == 404
    assert setting(owner, event_id, "progress").status_code == 422
    before = snap(mobile, event_id, "judge")
    old_version = snap(owner, event_id)["version"]
    assert setting(owner, event_id, "leaderboard", leaderboard_limit=1).status_code == 200
    assert setting(owner, event_id, "waiting", expected_version=old_version).status_code == 409
    assert snap(mobile, event_id, "judge") == before
    assert act(owner, rid, "pause").status_code == 200
    assert screen(mobile, credential).json()["display"]["mode"] == "paused"
    assert act(owner, rid, "resume").status_code == 200
    assert screen(mobile, credential).json()["display"]["mode"] == "progress"
    assert (
        DeadlineWorker(event_db[0], clock=lambda: scoring[2] + timedelta(seconds=60))
        .run_once()
        .closed
        == 1
    )
    assert screen(mobile, credential).json()["display"]["mode"] == "waiting"
    assert act(owner, rid, "no-result", reason="缺席").status_code == 200
    assert act(owner, scoring[0]["rounds"][1]["id"], "skip", reason="弃权").status_code == 200
    assert event_action(owner, event_id, "finish").status_code == 200
    assert screen(mobile, credential).json()["display"]["mode"] == "ended"
    assert event_action(owner, event_id, "archive").status_code == 200
    assert snap(mobile, event_id, "judge")["event"]["status"] == "ARCHIVED"


@pytest.mark.parametrize("model", [EventAudit, OutboxEvent])
def test_grant_and_display_failure_rolls_back(scoring, clients, event_db, model):
    owner = clients[0]
    event_id = scoring[0]["event"]["id"]
    before = snap(owner, event_id)

    def fail(*_):
        raise RuntimeError("injected")

    sa_event.listen(model, "before_insert", fail)
    try:
        assert owner.post(f"/api/v1/events/{event_id}/screen-grants", json={}).status_code == 500
        assert setting(owner, event_id, "waiting").status_code == 500
    finally:
        sa_event.remove(model, "before_insert", fail)
    assert snap(owner, event_id) == before
    with event_db[0].transaction() as session:
        assert session.scalar(select(ScreenGrant).where(ScreenGrant.event_id == event_id)) is None


def test_revoked_judge_cannot_reuse_resolved_principal(scoring, clients, event_db):
    db, _ = event_db
    stale = principal(scoring, db)
    base = f"/api/v1/events/{stale.event_id}/judges/{stale.judge_id}/reset-credential"
    response = clients[0].post(base, json={"reason": "换设备"})
    assert response.status_code == 200, response.text
    with pytest.raises(APIError) as error:
        service.judge_snapshot(db, stale, stale.event_id, lambda: scoring[2])
    assert error.value.status == 401


def test_screen_snapshot_skips_held_lock_and_sees_committed_revocation(scoring, clients, event_db):
    db, _ = event_db
    event_id = scoring[0]["event"]["id"]
    credential = grant(clients[0], event_id)

    def read():
        return service.screen_snapshot(
            db, credential["id"], credential["token"], lambda: scoring[2]
        )

    with ThreadPoolExecutor(1) as pool:
        with db.transaction() as session:
            session.scalar(select(Event).where(Event.id == event_id).with_for_update())
            session.get(ScreenGrant, credential["id"]).revoked_at = scoring[2]
            session.flush()
            assert pool.submit(read).result(timeout=2).event.id == event_id
        with pytest.raises(APIError) as error:
            read()
        assert error.value.status == 401


def test_tied_rankings_only_published_and_limit(clients, mobiles):
    owner = clients[0]
    event = owner.post(
        "/api/v1/events",
        json={
            "title": "排名验收",
            "scoring_rule": {
                "criteria": [{"criterion_id": "total", "name": "总分"}],
                "minimum_ballots": 1,
            },
        },
    ).json()
    base = f"/api/v1/events/{event['id']}"
    for i in range(4):
        owner.post(base + "/entries", json={"number": str(i), "name": str(i), "sort_order": i})
    owner.post(base + "/judges", json={"number": "1", "name": "评委"})
    published = owner.post(base + "/publish").json()
    mobile = mobiles[0]
    verified = mobile.post(
        "/api/v1/judge-sessions/verify",
        json={
            "public_code": published["event"]["public_code"],
            "code": published["generated_credentials"][0]["code"],
        },
    ).json()
    exchanged = mobile.post(
        "/api/v1/judge-sessions/exchange",
        json={"confirmation_token": verified["confirmation_token"]},
    ).json()
    mobile.headers["X-CSRF-Token"] = exchanged["csrf_token"]
    for i, row in enumerate(published["rounds"]):
        rid = row["id"]
        assert act(owner, rid, "open").status_code == 200
        assert (
            mobile.put(
                f"/api/v1/rounds/{rid}/my-ballot",
                json=payload(["90", "80", "80", "70"][i]),
                headers={"Idempotency-Key": str(uuid4())},
            ).status_code
            == 200
        )
        assert act(owner, rid, "close").status_code == 200
        assert len(snap(mobile, event["id"], "judge")["ranking"]) == i
        assert act(owner, rid, "publish").status_code == 200
    admin = snap(owner, event["id"])
    judges = snap(mobile, event["id"], "judge")
    assert [r["rank"] for r in admin["ranking"]] == [1, 2, 2, 4]
    assert [r["number"] for r in admin["ranking"]] == ["0", "1", "2", "3"]
    assert admin["ranking"] == judges["ranking"] == owner.get(base + "/ranking").json()
    credential = grant(owner, event["id"])
    assert setting(owner, event["id"], "leaderboard", leaderboard_limit=2).status_code == 200
    assert screen(mobile, credential).json()["ranking"] == admin["ranking"][:2]


def test_migration_preserves_existing_activity_and_initializes_roles(
    scoring, clients, mysql_settings, monkeypatch
):
    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    receipt = put(scoring).json()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    monkeypatch.setenv("DATABASE_URL", mysql_settings.database_url.get_secret_value())
    command.downgrade(config, "0011_results")
    command.upgrade(config, "head")
    command.check(config)
    mobile = snap(scoring[1][0], event_id, "judge")
    assert mobile["version"] == 1
    assert mobile["my_ballots"][0]["receipts"][0] == receipt
    credential = grant(clients[0], event_id)
    public = screen(scoring[1][0], credential).json()
    assert public["version"] == 1
    assert public["display"]["mode"] == "progress" and public["current_round"]["id"] == rid


def test_bearer_alone_cannot_read_management_or_write(scoring, clients):
    from fastapi.testclient import TestClient

    from score_api.main import create_app

    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    credential = grant(clients[0], event_id)
    with TestClient(
        create_app(clients[0].app.state.settings), base_url="https://score.test"
    ) as client:
        client.headers.update(
            {"Authorization": "Bearer " + credential["token"], "Origin": "https://score.test"}
        )
        assert screen(client, credential).status_code == 200
        for route in (
            f"/events/{event_id}/snapshot",
            f"/rounds/{rid}/results",
            f"/judge/events/{event_id}/snapshot",
            f"/rounds/{rid}/my-ballot",
        ):
            assert client.get("/api/v1" + route).status_code == 401
        assert (
            client.post(
                f"/api/v1/rounds/{rid}/close", json={"expected_version": 2, "reason": "越权"}
            ).status_code
            == 401
        )


def test_snapshot_does_not_wait_for_uncommitted_submission(scoring, clients, event_db):
    from score_api.ballots import service as ballot_service
    from score_api.ballots.schemas import BallotInput

    db, _ = event_db
    event_id = scoring[0]["event"]["id"]
    owner_id = scoring[0]["event"]["owner_id"]
    rid = scoring[0]["rounds"][0]["id"]
    actor = principal(scoring, db)
    before = service.judge_snapshot(db, actor, event_id, lambda: scoring[2])
    entered, release = Signal(), Signal()
    errors = []

    def hold_after_insert(*_):
        entered.set()
        if not release.wait(5):
            errors.append("lock test timed out")

    sa_event.listen(OutboxEvent, "after_insert", hold_after_insert)
    try:
        with ThreadPoolExecutor(3) as pool:
            saved = pool.submit(
                ballot_service.submit_ballot,
                db,
                actor,
                rid,
                BallotInput.model_validate(payload()),
                str(uuid4()),
                uuid4().hex,
                lambda: scoring[2],
            )
            assert entered.wait(2)
            during = pool.submit(
                service.judge_snapshot, db, actor, event_id, lambda: scoring[2]
            ).result(timeout=2)
            admin = pool.submit(
                service.admin_snapshot, db, owner_id, event_id, lambda: scoring[2]
            ).result(timeout=2)
            release.set()
            receipt = saved.result()
    finally:
        release.set()
        sa_event.remove(OutboxEvent, "after_insert", hold_after_insert)
    assert not errors
    assert during == before
    assert admin.ballots == []
    assert next(r for r in admin.rounds if r.id == rid).submitted_count == 0
    after = service.judge_snapshot(db, actor, event_id, lambda: scoring[2])
    assert after.version == before.version + 1
    assert after.my_ballots[0].receipts[0] == receipt
    assert next(r for r in after.rounds if r.id == rid).submitted_count == 1


def test_open_snapshot_keeps_one_read_view_without_blocking_writes(scoring, clients, event_db):
    db, _ = event_db
    event_id = scoring[0]["event"]["id"]
    owner_id = scoring[0]["event"]["owner_id"]
    with db.read_snapshot() as session:
        first = service.public_data(session, session.get(Event, event_id))[1][0]
        assert put(scoring).status_code == 200
        again = service.public_data(session, session.get(Event, event_id))[1][0]
    assert first.submitted_count == again.submitted_count == 0
    fresh = service.admin_snapshot(db, owner_id, event_id, lambda: scoring[2])
    assert fresh.rounds[0].submitted_count == 1
