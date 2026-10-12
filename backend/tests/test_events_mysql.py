"""草稿 CRUD、权限、迁移、同事务审计及真实 InnoDB 竞争。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from threading import Event as ThreadEvent
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.db import utc_now
from score_api.events import service
from score_api.events.models import Entry, Event, EventAudit, EventJudge
from score_api.events.schemas import EntryCreate, EventCreate

pytestmark = pytest.mark.mysql
ORIGIN = "https://score.test"
BASE = "/api/v1/events"


def create(client, **fields):
    response = client.post(BASE, json={"title": "比赛", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_event_crud_pagination_clear_and_delete_audit(clients, event_db):
    client, _ = clients
    db, owners = event_db
    rule = {"criteria": [{"criterion_id": "total", "name": "总分"}]}
    created = create(client, planned_at="2026-10-12T20:00:00+08:00", scoring_rule=rule)
    url = f"{BASE}/{created['id']}"
    assert created["owner_id"] == owners[0] and created["status"] == "DRAFT"
    assert created["planned_at"] == "2026-10-12T12:00:00Z"
    assert client.get(url).json()["planned_at"] == "2026-10-12T12:00:00Z"
    create(client, title="第二场")
    assert [row["title"] for row in client.get(BASE, params={"limit": 1}).json()] == ["第二场"]
    assert client.get(BASE, params={"limit": 1, "offset": 1}).json()[0]["id"] == created["id"]
    assert client.get(BASE, params={"limit": 101}).status_code == 422
    updated = client.patch(url, json={"title": "修改", "planned_at": None, "scoring_rule": None})
    assert updated.status_code == 200
    assert updated.json()["planned_at"] is None and updated.json()["scoring_rule"] is None
    assert client.post(url + "/entries", json={"number": "001", "name": "对象"}).status_code == 201
    assert client.post(url + "/judges", json={"number": "001", "name": "评委"}).status_code == 201
    response = client.delete(url)
    assert response.status_code == 204 and not response.content
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404
    with db.transaction() as session:
        assert not session.scalar(select(Entry).where(Entry.event_id == created["id"]))
        assert not session.scalar(select(EventJudge).where(EventJudge.event_id == created["id"]))
        logs = list(
            session.scalars(
                select(EventAudit)
                .where(EventAudit.event_id == created["id"])
                .order_by(EventAudit.created_at)
            )
        )
        assert len(logs) == 5
        assert logs[-1].action == "event.deleted" and logs[-1].before["title"] == "修改"
        assert logs[-1].request_id == response.headers["x-request-id"]
        assert logs[1].before["title"] == "比赛" and logs[1].after["title"] == "修改"


@pytest.mark.parametrize("kind", ["entries", "judges"])
def test_members_crud_unique_string_numbers_and_cross_event_ids(clients, kind):
    client, _ = clients
    urls = [f"{BASE}/{create(client)['id']}/{kind}" for _ in range(2)]
    first = client.post(urls[0], json={"number": "001", "name": "甲"}).json()
    second = client.post(urls[0], json={"number": "1", "name": "乙"}).json()
    assert first["number"] == "001" and second["number"] == "1"
    assert client.post(urls[1], json={"number": "001", "name": "甲"}).status_code == 201
    for number in ("A", "a"):
        assert client.post(urls[0], json={"number": number, "name": "大小写"}).status_code == 201
    conflict = client.post(urls[0], json={"number": " 001 ", "name": "重复"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "NUMBER_CONFLICT"
    target = f"{urls[0]}/{first['id']}"
    assert client.get(target).json() == first
    assert client.patch(target, json={"number": "1"}).status_code == 409
    assert client.get(target).json() == first
    assert client.patch(target, json={"name": "修改", "number": "002"}).status_code == 200
    assert client.get(urls[0], params={"limit": 1}).json()[0]["number"] == "002"
    wrong = f"{urls[1]}/{first['id']}"
    for method, kwargs in (("get", {}), ("patch", {"json": {"name": "越界"}}), ("delete", {})):
        assert client.request(method, wrong, **kwargs).status_code == 404
    assert client.delete(target).status_code == 204
    assert client.get(target).status_code == 404


def test_owner_isolation_every_route_and_csrf(clients):
    owner, other = clients
    url = f"{BASE}/{create(owner)['id']}"
    operations = [("get", url, None), ("patch", url, {"title": "越权"}), ("delete", url, None)]
    for kind in ("entries", "judges"):
        child = owner.post(url + f"/{kind}", json={"number": "01", "name": "姓名"}).json()
        collection = url + f"/{kind}"
        item = collection + f"/{child['id']}"
        operations.extend(
            [
                ("get", collection, None),
                ("get", item, None),
                ("post", collection, {"number": "02", "name": "入侵"}),
                ("patch", item, {"name": "入侵"}),
                ("delete", item, None),
            ]
        )
    assert other.get(BASE).json() == []
    for method, path, body in operations:
        response = other.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 404, (method, path, response.text)
        assert "姓名" not in response.text
    assert (
        owner.patch(url, json={"title": "x"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    )
    assert owner.delete(url, headers={"Origin": "https://evil.test"}).status_code == 403
    assert owner.get(url).json()["title"] == "比赛"


@pytest.mark.parametrize("status", ["READY", "RUNNING", "FINISHED", "ARCHIVED"])
def test_all_non_draft_writes_rejected(clients, event_db, status):
    owner, _ = clients
    db, _ = event_db
    created = create(owner)
    url = f"{BASE}/{created['id']}"
    writes = [("patch", url, {"title": "changed"}), ("delete", url, None)]
    for kind in ("entries", "judges"):
        collection = f"{url}/{kind}"
        row = owner.post(collection, json={"number": "1", "name": "name"}).json()
        writes.extend(
            [
                ("post", collection, {"number": "2", "name": "name"}),
                ("patch", f"{collection}/{row['id']}", {"name": "changed"}),
                ("delete", f"{collection}/{row['id']}", None),
            ]
        )
    with db.transaction() as session:
        session.get(Event, created["id"]).status = status
    for method, path, body in writes:
        response = owner.request(method, path, **({"json": body} if body else {}))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EVENT_NOT_DRAFT"
    assert owner.get(url).status_code == 200


@pytest.mark.parametrize("operation", ["create", "patch", "delete", "member"])
def test_audit_failure_rolls_back_business(clients, event_db, operation):
    owner, _ = clients
    db, _ = event_db
    created = create(owner)
    url = f"{BASE}/{created['id']}"
    owner.post(url + "/entries", json={"number": "001", "name": "原始对象"})

    def fail(*_args):
        raise RuntimeError("simulate audit failure")

    sa_event.listen(EventAudit, "before_insert", fail)
    try:
        if operation == "create":
            response = owner.post(BASE, json={"title": "不应保存"})
        elif operation == "patch":
            response = owner.patch(url, json={"title": "不应保存"})
        elif operation == "delete":
            response = owner.delete(url)
        else:
            response = owner.post(url + "/entries", json={"number": "002", "name": "不应保存"})
        assert response.status_code == 500
    finally:
        sa_event.remove(EventAudit, "before_insert", fail)
    assert owner.get(url).json()["title"] == "比赛"
    assert len(owner.get(BASE).json()) == 1
    assert len(owner.get(url + "/entries").json()) == 1
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(EventAudit)
                .where(EventAudit.event_id == created["id"])
            )
            == 2
        )


def test_concurrent_duplicate_number_only_one_commit(event_db):
    db, owners = event_db
    created = service.create_event(db, owners[0], EventCreate(title="并发"), uuid4().hex, utc_now)
    barrier = Barrier(2)

    def insert():
        barrier.wait(timeout=3)
        try:
            service.write_member(
                db,
                owners[0],
                created.id,
                Entry,
                "created",
                EntryCreate(number="001", name="对象"),
                None,
                uuid4().hex,
                utc_now,
            )
            return "created"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: insert(), range(2))) == ["NUMBER_CONFLICT", "created"]
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Entry).where(Entry.event_id == created.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(EventAudit)
                .where(EventAudit.event_id == created.id)
            )
            == 2
        )


def test_waiting_write_rechecks_status_after_event_lock(event_db):
    db, owners = event_db
    created = service.create_event(db, owners[0], EventCreate(title="锁"), uuid4().hex, utc_now)
    waiting = ThreadEvent()

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        if "FOR UPDATE" in statement:
            waiting.set()

    def competing_write():
        with pytest.raises(APIError) as error:
            service.write_member(
                db,
                owners[0],
                created.id,
                Entry,
                "created",
                EntryCreate(number="001", name="对象"),
                None,
                uuid4().hex,
                utc_now,
            )
        return error.value.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction() as session:
            row = session.scalar(select(Event).where(Event.id == created.id).with_for_update())
            row.status = "READY"
            session.flush()
            sa_event.listen(db.engine, "before_cursor_execute", before_execute)
            future = pool.submit(competing_write)
            try:
                assert waiting.wait(timeout=3)
                assert not future.done()
            finally:
                sa_event.remove(db.engine, "before_cursor_execute", before_execute)
        assert future.result(timeout=5) == "EVENT_NOT_DRAFT"
    assert service.read_members(db, owners[0], created.id, Entry) == []


@pytest.mark.parametrize("model", [Entry, EventJudge])
def test_database_enforces_member_unique_and_event_foreign_key(event_db, model):
    db, owners = event_db
    created = service.create_event(db, owners[0], EventCreate(title="约束"), uuid4().hex, utc_now)
    with db.transaction() as session:
        session.add(model(id=uuid4().hex, event_id=created.id, number="001", name="原始"))
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.add(model(id=uuid4().hex, event_id=created.id, number="001", name="重复"))
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.add(model(id=uuid4().hex, event_id=uuid4().hex, number="001", name="孤立"))
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.execute(delete(Event).where(Event.id == created.id))
    assert len(service.read_members(db, owners[0], created.id, model)) == 1
