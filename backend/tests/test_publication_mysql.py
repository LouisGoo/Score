import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.db import utc_now
from score_api.events import publication
from score_api.events.models import Entry, Event, EventAudit, EventJudge, EventSnapshot
from score_api.rounds.models import RoundJudge, ScoringRound

pytestmark = pytest.mark.mysql
BASE = "/api/v1/events"


def draft(client, *, count=1, algorithm="mean", minimum=None):
    event = client.post(
        BASE,
        json={
            "title": "发布测试",
            "duration_seconds": 120,
            "allow_revisions": False,
            "scoring_rule": {
                "criteria": [{"criterion_id": "total", "name": "总分"}],
                "algorithm": algorithm,
                "minimum_ballots": minimum,
            },
        },
    ).json()
    url = f"{BASE}/{event['id']}"
    entries = [
        client.post(
            url + "/entries", json={"number": str(i), "name": "项目", "sort_order": 2 - i}
        ).json()
        for i in range(2)
    ]
    judges = [
        client.post(url + "/judges", json={"number": f"{i:03}", "name": "评委"}).json()
        for i in range(count)
    ]
    return event, url, entries, judges


def test_atomic_publication_snapshot_tasks_and_freeze(clients, event_db):
    owner, other = clients
    db, _ = event_db
    event, url, entries, judges = draft(owner, count=5, algorithm="trimmed_mean")
    credential_url = f"{url}/judges/{judges[0]['id']}/credential"
    owner.put(credential_url, json={"code": "MANUAL123"})
    assert other.post(url + "/publish").status_code == 404
    response = owner.post(url + "/publish")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["event"]["status"] == "READY" and result["event"]["version"] == 1
    assert len(result["event"]["public_code"]) == 12
    assert len(result["generated_credentials"]) == 4
    snapshot = result["snapshot"]
    assert snapshot["scoring_rule"]["minimum_ballots"] == 5
    assert snapshot["scoring_rule"]["expected_count"] == 5
    assert snapshot["entries"][0]["id"] == entries[1]["id"]
    assert snapshot["duration_seconds"] == 120 and not snapshot["allow_revisions"]
    assert "credential" not in json.dumps(snapshot)
    assert {r["entry_id"] for r in result["rounds"]} == {e["id"] for e in entries}
    assert all(r["status"] == "PENDING" and r["version"] == 1 for r in result["rounds"])
    public_record = owner.get(url + "/publication")
    assert public_record.json()["snapshot"] == snapshot
    assert "generated_credentials" not in public_record.json()
    assert "MANUAL123" not in public_record.text
    for value in result["generated_credentials"]:
        assert value["code"] not in public_record.text
    assert other.get(url + "/publication").status_code == 404
    assert owner.post(url + "/publish").status_code == 409
    assert owner.patch(url, json={"scoring_rule": None}).status_code == 409
    assert owner.delete(url).status_code == 409
    assert (
        owner.patch(f"{url}/judges/{judges[0]['id']}", json={"name": "changed"}).status_code == 409
    )
    assert owner.put(credential_url, json={}).status_code == 409
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RoundJudge)
                .where(RoundJudge.event_id == event["id"])
            )
            == 10
        )
        audit = session.scalar(
            select(EventAudit).where(
                EventAudit.event_id == event["id"], EventAudit.action == "event.published"
            )
        )
        assert audit.request_id == response.headers["x-request-id"]
    # 即使修复脚本错误地改状态为草稿，历史外键仍阻止名单和活动物理删除。
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.execute(delete(Entry).where(Entry.event_id == event["id"]))


@pytest.mark.parametrize("missing", ["entries", "judges", "rule", "too_few", "k_exceeds_n"])
def test_invalid_publish_leaves_no_partial_data(clients, event_db, missing):
    owner, _ = clients
    db, _ = event_db
    event, url, _, _ = draft(
        owner,
        algorithm="trimmed_mean" if missing == "too_few" else "mean",
        minimum=2 if missing == "k_exceeds_n" else None,
    )
    with db.transaction() as session:
        if missing in ("entries", "judges"):
            model = Entry if missing == "entries" else EventJudge
            session.execute(delete(model).where(model.event_id == event["id"]))
        if missing == "rule":
            session.get(Event, event["id"]).scoring_rule = None
    assert owner.post(url + "/publish").json()["error"]["code"] == "PUBLISH_INVALID"
    with db.transaction() as session:
        assert session.get(Event, event["id"]).status == "DRAFT"
        assert (
            session.scalar(select(EventSnapshot.id).where(EventSnapshot.event_id == event["id"]))
            is None
        )
        assert all(
            not j.credential_is_set
            for j in session.scalars(select(EventJudge).where(EventJudge.event_id == event["id"]))
        )


def test_copy_only_config_and_roster_with_fresh_ids(clients, event_db):
    owner, other = clients
    db, _ = event_db
    event, url, entries, judges = draft(owner)
    owner.put(f"{url}/judges/{judges[0]['id']}/credential", json={"code": "MANUAL123"})
    owner.post(url + "/publish")
    assert other.post(url + "/copy").status_code == 404
    copied = owner.post(url + "/copy")
    assert copied.status_code == 201, copied.text
    result = copied.json()
    assert result["status"] == "DRAFT" and result["version"] == 0
    assert result["public_code"] is None and result["published_at"] is None
    assert result["scoring_rule"] == event["scoring_rule"]
    copied_url = f"{BASE}/{result['id']}"
    copied_entries = owner.get(copied_url + "/entries").json()
    copied_judges = owner.get(copied_url + "/judges").json()
    assert {e["number"] for e in entries} == {e["number"] for e in copied_entries}
    assert {e["id"] for e in entries}.isdisjoint(e["id"] for e in copied_entries)
    assert copied_judges[0]["number"] == "000" and not copied_judges[0]["credential_is_set"]
    assert copied_judges[0]["credential_version"] == 0
    assert owner.get(copied_url + "/publication").status_code == 404
    with db.transaction() as session:
        assert (
            session.scalar(select(ScoringRound.id).where(ScoringRound.event_id == result["id"]))
            is None
        )
    # 草稿也可以复制，且不继承原凭证。
    assert owner.post(copied_url + "/copy").status_code == 201


@pytest.mark.parametrize("action", ["publish", "copy"])
def test_audit_failure_rolls_back_entire_publish_or_copy(clients, event_db, action):
    owner, _ = clients
    db, owners = event_db
    event, url, _, judges = draft(owner)

    def fail(_mapper, _conn, target):
        if target.action == ("event.published" if action == "publish" else "event.copied"):
            raise RuntimeError("audit unavailable")

    sa_event.listen(EventAudit, "before_insert", fail)
    try:
        assert owner.post(url + "/" + action).status_code == 500
    finally:
        sa_event.remove(EventAudit, "before_insert", fail)
    with db.transaction() as session:
        row = session.get(Event, event["id"])
        assert row.status == "DRAFT" and row.public_code is None
        assert session.get(EventJudge, judges[0]["id"]).credential_version == 0
        assert (
            session.scalar(
                select(func.count()).select_from(Event).where(Event.owner_id == owners[0])
            )
            == 1
        )
        for model in (EventSnapshot, ScoringRound, RoundJudge):
            assert (
                session.scalar(select(model.event_id).where(model.event_id == event["id"])) is None
            )


def test_concurrent_publish_one_snapshot(clients, event_db):
    owner, _ = clients
    db, owners = event_db
    event, url, _, judges = draft(owner)
    owner.put(f"{url}/judges/{judges[0]['id']}/credential", json={"code": "MANUAL123"})
    barrier = Barrier(2)

    def publish(_):
        barrier.wait(timeout=5)
        try:
            publication.publish_event(
                db, owner.app.state.settings, owners[0], event["id"], uuid4().hex, utc_now
            )
            return "ok"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(publish, range(2))) == ["EVENT_NOT_DRAFT", "ok"]


def test_roster_change_during_hash_preparation_aborts(clients, event_db, monkeypatch):
    owner, _ = clients
    db, _ = event_db
    event, url, _, _ = draft(owner)
    original = publication.prepare_credential

    def prepare(*args):
        result = original(*args)
        owner.post(url + "/judges", json={"number": "new", "name": "新增"})
        return result

    monkeypatch.setattr(publication, "prepare_credential", prepare)
    assert owner.post(url + "/publish").json()["error"]["code"] == "PUBLISH_CONFLICT"
    with db.transaction() as session:
        assert session.get(Event, event["id"]).status == "DRAFT"
        assert all(
            not j.credential_is_set
            for j in session.scalars(select(EventJudge).where(EventJudge.event_id == event["id"]))
        )


def test_public_code_collision_retries_and_composite_foreign_keys(clients, event_db, monkeypatch):
    owner, _ = clients
    db, _ = event_db
    _, url, _, judges = draft(owner)
    first = owner.post(url + "/publish").json()
    second_event, second_url, _, _ = draft(owner)
    candidates = iter([first["event"]["public_code"], "ABCDEFGH2345"])
    monkeypatch.setattr(publication, "generate_public_code", lambda: next(candidates))
    second = owner.post(second_url + "/publish")
    assert second.status_code == 200, second.text
    assert second.json()["event"]["public_code"] == "ABCDEFGH2345"
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.add(
            RoundJudge(
                round_id=second.json()["rounds"][0]["id"],
                event_id=second_event["id"],
                event_judge_id=judges[0]["id"],
            )
        )
