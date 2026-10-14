from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import func, select

from score_api.events import publication, service
from score_api.events.models import Event, EventAudit, EventJudge, EventSnapshot
from score_api.rounds.models import ScoringRound

pytestmark = pytest.mark.mysql
BASE = "/api/v1/events"
RULE = {"criteria": [{"criterion_id": "total", "name": "总分"}]}


def draft(client, *, entries=2, judges=3, **fields):
    response = client.post(BASE, json={"title": "后端缺口验收", "scoring_rule": RULE, **fields})
    assert response.status_code == 201, response.text
    data = response.json()
    url = f"{BASE}/{data['id']}"
    for kind, count in (("entries", entries), ("judges", judges)):
        for i in range(count):
            assert (
                client.post(f"{url}/{kind}", json={"number": str(i), "name": str(i)}).status_code
                == 201
            )
    return data, url


def counts(row):
    return tuple(
        row[key] for key in ("entry_count", "judge_count", "round_count", "finished_round_count")
    )


def test_list_counts_one_query_owner_isolation_and_pagination(clients, event_db):
    owner, other = clients
    db, owners = event_db
    first, _ = draft(owner)
    second, _ = draft(owner, entries=0, judges=0)
    draft(other, entries=4, judges=1)
    queries = []

    def capture(_conn, _cursor, statement, *_args):
        queries.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", capture)
    try:
        rows = service.list_events(db, owners[0], 0, 100)
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", capture)
    assert len(queries) == 1
    assert "FOR UPDATE" not in queries[0].upper()
    assert [row.id for row in rows] == [second["id"], first["id"]]
    assert counts(rows[0].model_dump()) == (0, 0, 0, 0)
    assert counts(rows[1].model_dump()) == (2, 3, 0, 0)
    page = owner.get(BASE, params={"limit": 1, "offset": 1}).json()
    assert len(page) == 1 and page[0]["id"] == first["id"]
    assert counts(page[0]) == (2, 3, 0, 0)
    assert owner.get(BASE, params={"offset": 99}).json() == []


def test_list_progress_only_counts_terminal_rounds_and_copy_resets(clients, event_db):
    owner, _ = clients
    db, _ = event_db
    event, url = draft(owner, entries=7, judges=1)
    response = owner.post(url + "/publish")
    assert response.status_code == 200, response.text
    assert counts(owner.get(BASE).json()[0]) == (7, 1, 7, 0)
    statuses = ("PENDING", "OPEN", "CLOSED", "PUBLISHED", "SKIPPED", "NO_RESULT", "PENDING")
    with db.transaction() as session:
        rounds = list(
            session.scalars(select(ScoringRound).where(ScoringRound.event_id == event["id"]))
        )
        for row, status in zip(rounds, statuses, strict=True):
            row.status = status
    assert counts(owner.get(BASE).json()[0]) == (7, 1, 7, 3)
    # OPEN/PAUSED 受活动唯一约束保护，分开验证二者均不计为终态。
    with db.transaction() as session:
        active = session.get(ScoringRound, rounds[1].id)
        active.status = "PAUSED"
        session.get(ScoringRound, rounds[3].id).status = "CLOSED"
    assert counts(owner.get(BASE).json()[0]) == (7, 1, 7, 2)
    copied = owner.post(url + "/copy").json()
    rows = {row["id"]: row for row in owner.get(BASE).json()}
    assert counts(rows[copied["id"]]) == (7, 1, 0, 0)


def test_check_reports_all_missing_and_publish_reuses_errors(clients):
    owner, other = clients
    _, url = draft(owner, entries=0, judges=0, scoring_rule=None)
    response = owner.get(url + "/publish-check")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    report = response.json()
    assert not report["can_publish"]
    assert [issue["field"] for issue in report["issues"]] == ["entries", "judges", "scoring_rule"]
    failure = owner.post(url + "/publish")
    assert failure.status_code == 422
    assert failure.json()["error"]["issues"] == report["issues"]
    assert failure.json()["request_id"] == failure.headers["x-request-id"]
    assert other.get(url + "/publish-check").status_code == 404
    assert owner.get(BASE + "/missing/publish-check").status_code == 404
    owner.cookies.clear()
    assert owner.get(url + "/publish-check").status_code == 401


def test_check_does_not_write_or_expose_credentials_and_matches_publish(clients, event_db):
    owner, _ = clients
    db, _ = event_db
    event, url = draft(owner)
    judges = owner.get(url + "/judges").json()
    assert (
        owner.put(
            f"{url}/judges/{judges[0]['id']}/credential", json={"code": "PRIVATE123"}
        ).status_code
        == 200
    )
    before = owner.get(url).json()

    def audit_count():
        with db.transaction() as session:
            return session.scalar(
                select(func.count())
                .select_from(EventAudit)
                .where(EventAudit.event_id == event["id"])
            )

    audits = audit_count()
    for _ in range(2):
        response = owner.get(url + "/publish-check")
        assert response.status_code == 200
        assert response.json() == {
            "can_publish": True,
            "issues": [],
            "entry_count": 2,
            "judge_count": 3,
            "missing_credential_count": 2,
            "minimum_ballots": 3,
        }
        assert "PRIVATE123" not in response.text
    assert owner.get(url).json() == before and audit_count() == audits
    assert owner.get(url + "/judges").json()[1]["credential_version"] == 0
    published = owner.post(url + "/publish").json()
    assert published["snapshot"]["scoring_rule"]["minimum_ballots"] == 3
    assert len(published["generated_credentials"]) == 2
    assert owner.get(url + "/publish-check").status_code == 409


def test_publish_revalidates_rule_after_preparation_and_rolls_back(clients, event_db, monkeypatch):
    owner, _ = clients
    db, _ = event_db
    event, url = draft(owner, judges=1)
    assert owner.get(url + "/publish-check").json()["can_publish"]
    original = publication.prepare_credential

    def prepare(*args):
        prepared = original(*args)
        assert (
            owner.patch(url, json={"scoring_rule": {**RULE, "minimum_ballots": 2}}).status_code
            == 200
        )
        return prepared

    monkeypatch.setattr(publication, "prepare_credential", prepare)
    response = owner.post(url + "/publish")
    assert response.status_code == 422
    assert response.json()["error"]["issues"] == owner.get(url + "/publish-check").json()["issues"]
    with db.transaction() as session:
        assert session.get(Event, event["id"]).status == "DRAFT"
        assert (
            session.scalar(select(EventSnapshot.id).where(EventSnapshot.event_id == event["id"]))
            is None
        )
        assert not session.scalar(
            select(EventJudge).where(EventJudge.event_id == event["id"])
        ).credential_is_set


def test_check_does_not_wait_for_writer_and_uses_one_read_view(clients, event_db, monkeypatch):
    owner, _ = clients
    db, owners = event_db
    event, url = draft(owner, judges=1)
    original = publication.members

    def changed_members(session, event_id):
        # 活动已读，接着提交新的规则与名单，当前预检仍须使用原读视图。
        assert (
            owner.patch(url, json={"scoring_rule": {**RULE, "minimum_ballots": 2}}).status_code
            == 200
        )
        assert owner.post(url + "/judges", json={"number": "new", "name": "new"}).status_code == 201
        return original(session, event_id)

    monkeypatch.setattr(publication, "members", changed_members)
    check = publication.check_publication(db, owners[0], event["id"])
    assert check.can_publish and check.minimum_ballots == check.judge_count == 1
    monkeypatch.setattr(publication, "members", original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as session:
            row = session.scalar(select(Event).where(Event.id == event["id"]).with_for_update())
            row.scoring_rule = None
            session.flush()
            future = pool.submit(publication.check_publication, db, owners[0], event["id"])
            check = future.result(timeout=2)
            assert check.can_publish and check.minimum_ballots == check.judge_count == 2
    assert not owner.get(url + "/publish-check").json()["can_publish"]
