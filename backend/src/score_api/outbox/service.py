"""在业务事务内冻结收件人与版本；投递时不读取当前版本或公开内部 payload。"""

from uuid import uuid4

from sqlalchemy import select

from score_api.events.models import Event, EventJudge
from score_api.outbox.models import OutboxEvent


def record(session, event, action, now, *, public=False, judge_id=None, screen=False, payload=None):
    streams = [{"scope": "admin", "subject_id": event.owner_id, "version": event.version}]
    if public or screen:
        streams.append({"scope": "screen", "subject_id": None, "version": event.screen_version})
    if public or judge_id:
        query = select(EventJudge.id, EventJudge.snapshot_version).where(
            EventJudge.event_id == event.id
        )
        if not public:
            query = query.where(EventJudge.id == judge_id)
        streams.extend(
            {"scope": "judge", "subject_id": id_, "version": version}
            for id_, version in session.execute(query)
        )
    session.add(
        OutboxEvent(
            id=uuid4().hex,
            event_id=event.id,
            version=event.version,
            type=action,
            payload={"protocol": 1, "streams": streams, "data": payload or {}},
            created_at=now,
        )
    )


def authorization_changed(session, event_id, now):
    # 无数据/版本的控制通知：使连接重新查权威授权状态，不改变角色快照版本。
    session.add(
        OutboxEvent(
            id=uuid4().hex,
            event_id=event_id,
            version=0,
            type="authorization.changed",
            payload={"protocol": 1, "streams": [], "data": {}},
            created_at=now,
        )
    )


def admin_authorization_changed(session, admin_id, now):
    for event_id in session.scalars(
        select(Event.id).where(Event.owner_id == admin_id, Event.status != "DRAFT")
    ):
        authorization_changed(session, event_id, now)
