"""草稿业务事务：所有写入先锁活动行，锁内检查归属与草稿状态。"""

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from score_api.core.errors import APIError
from score_api.db import Database
from score_api.events.models import Entry, Event, EventAudit, EventJudge
from score_api.events.schemas import (
    EntryInfo,
    EventCreate,
    EventInfo,
    EventPatch,
    InputModel,
    JudgeInfo,
)

Member = type[Entry] | type[EventJudge]


def owned_event(
    session: Session, owner_id: str, event_id: str, *, write=False, draft_only=True
) -> Event:
    query = select(Event).where(Event.id == event_id, Event.owner_id == owner_id)
    event = session.scalar(query.with_for_update() if write else query)
    if event is None:
        # 隐藏活动是否存在，不为他人活动暴露名称、名单或状态。
        raise APIError(404, "NOT_FOUND", "活动不存在")
    if write and draft_only and event.status != "DRAFT":
        raise APIError(409, "EVENT_NOT_DRAFT", "仅允许修改或删除草稿活动")
    return event


def audit(session, event, actor_id, action, target_id, before, after, request_id, now):
    session.add(
        EventAudit(
            id=uuid4().hex,
            event_id=event.id,
            actor_id=actor_id,
            action=action,
            target_id=target_id,
            before=before,
            after=after,
            request_id=request_id,
            created_at=now,
        )
    )


def create_event(database: Database, owner_id: str, body: EventCreate, request_id: str, clock):
    with database.transaction() as session:
        now = clock()
        values = body.model_dump()
        values["scoring_rule"] = (
            body.scoring_rule.model_dump(mode="json") if body.scoring_rule else None
        )
        event = Event(
            id=uuid4().hex,
            owner_id=owner_id,
            status="DRAFT",
            created_at=now,
            updated_at=now,
            **values,
        )
        session.add(event)
        session.flush()
        result = EventInfo.model_validate(event)
        audit(
            session,
            event,
            owner_id,
            "event.created",
            event.id,
            None,
            result.model_dump(mode="json"),
            request_id,
            now,
        )
    return result


def list_events(database: Database, owner_id: str, offset: int, limit: int):
    with database.transaction() as session:
        rows = session.scalars(
            select(Event)
            .where(Event.owner_id == owner_id)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [EventInfo.model_validate(row) for row in rows]


def get_event(database: Database, owner_id: str, event_id: str):
    with database.transaction() as session:
        return EventInfo.model_validate(owned_event(session, owner_id, event_id))


def patch_event(
    database: Database,
    owner_id: str,
    event_id: str,
    body: EventPatch,
    request_id: str,
    clock: Callable[[], datetime],
):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True)
        before = EventInfo.model_validate(event).model_dump(mode="json")
        changes = body.model_dump(exclude_unset=True)
        if "scoring_rule" in changes and body.scoring_rule is not None:
            changes["scoring_rule"] = body.scoring_rule.model_dump(mode="json")
        for key, value in changes.items():
            setattr(event, key, value)
        event.updated_at = clock()
        result = EventInfo.model_validate(event)
        audit(
            session,
            event,
            owner_id,
            "event.updated",
            event.id,
            before,
            result.model_dump(mode="json"),
            request_id,
            event.updated_at,
        )
    return result


def delete_event(database: Database, owner_id: str, event_id: str, request_id: str, clock):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True)
        before = EventInfo.model_validate(event).model_dump(mode="json")
        # 不使用级联删除：后续任务/评分表必须保留 RESTRICT 外键，防止删除历史。
        for model in (Entry, EventJudge):
            session.execute(delete(model).where(model.event_id == event.id))
        audit(
            session, event, owner_id, "event.deleted", event.id, before, None, request_id, clock()
        )
        session.delete(event)


def member_info(row):
    return (EntryInfo if isinstance(row, Entry) else JudgeInfo).model_validate(row)


def get_member(session: Session, model: Member, event_id: str, member_id: str):
    row = session.scalar(select(model).where(model.event_id == event_id, model.id == member_id))
    if row is None:
        raise APIError(404, "NOT_FOUND", "名单记录不存在")
    return row


def read_members(database, owner_id, event_id, model: Member, member_id=None, offset=0, limit=100):
    with database.transaction() as session:
        owned_event(session, owner_id, event_id)
        if member_id is not None:
            return member_info(get_member(session, model, event_id, member_id))
        order = (
            (Entry.sort_order, Entry.number, Entry.id)
            if model is Entry
            else (EventJudge.number, EventJudge.id)
        )
        rows = session.scalars(
            select(model)
            .where(model.event_id == event_id)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
        )
        return [member_info(row) for row in rows]


def write_member(
    database: Database,
    owner_id: str,
    event_id: str,
    model: Member,
    operation: str,
    body: InputModel | None,
    member_id: str | None,
    request_id: str,
    clock,
):
    try:
        with database.transaction() as session:
            event = owned_event(session, owner_id, event_id, write=True)
            before = None
            if operation == "created":
                row = model(id=uuid4().hex, event_id=event_id, **body.model_dump())
                session.add(row)
            else:
                row = get_member(session, model, event_id, member_id)
                before = member_info(row).model_dump(mode="json")
                if operation == "updated":
                    for key, value in body.model_dump(exclude_unset=True).items():
                        setattr(row, key, value)
                else:
                    session.delete(row)
            session.flush()
            result = None if operation == "deleted" else member_info(row)
            event.updated_at = clock()
            kind = "entry" if model is Entry else "judge"
            audit(
                session,
                event,
                owner_id,
                f"{kind}.{operation}",
                row.id,
                before,
                result.model_dump(mode="json") if result else None,
                request_id,
                event.updated_at,
            )
        return result
    except IntegrityError as exc:
        # 只映射 MySQL 唯一约束冲突；其他数据库错误仍走统一 503，不泄露 SQL。
        if exc.orig.args[0] == 1062:
            raise APIError(409, "NUMBER_CONFLICT", "该活动内编号已存在") from None
        raise
