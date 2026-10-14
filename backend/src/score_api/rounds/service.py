"""控制操作统一先锁活动，再锁任务；时钟在锁内读取。"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from score_api.core.errors import APIError
from score_api.core.streams import advance_views, automatic_screen
from score_api.events.models import EventSnapshot
from score_api.events.service import audit, owned_event
from score_api.outbox.service import record
from score_api.rounds.models import ScoringRound
from score_api.rounds.schemas import RoundInfo, RoundState


def round_in_event(session, event_id, round_id, *, write=False):
    query = select(ScoringRound).where(
        ScoringRound.id == round_id, ScoringRound.event_id == event_id
    )
    if write:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(query)
    if row is None:
        raise APIError(404, "NOT_FOUND", "评分任务不存在")
    return row


def owned_round(session, owner_id, round_id, *, write=False):
    # 只读定位不持有任务锁，避免反向加锁。
    event_id = session.scalar(select(ScoringRound.event_id).where(ScoringRound.id == round_id))
    event = owned_event(session, owner_id, event_id, write=write, draft_only=False)
    return event, round_in_event(session, event.id, round_id, write=write)


def state(event, row, now):
    return RoundState(
        **RoundInfo.model_validate(row).model_dump(), server_time=now, event_version=event.version
    )


def read_round(database, owner_id, round_id, clock):
    with database.transaction() as session:
        event, row = owned_round(session, owner_id, round_id)
        return state(event, row, clock())


def require_before_deadline(row, now):
    if row.deadline_at is not None and now >= row.deadline_at:
        raise APIError(409, "DEADLINE_EXCEEDED", "评分任务已到截止时间")


def control(database, owner_id, round_id, action, body, request_id, clock):
    with database.transaction() as session:
        event, row = owned_round(session, owner_id, round_id, write=True)
        now = clock()
        if event.status not in {"READY", "RUNNING"}:
            raise APIError(409, "EVENT_NOT_RUNNING", "活动当前不可操作")
        if row.version != body.expected_version:
            raise APIError(409, "VERSION_CONFLICT", "任务版本已变化，请刷新后确认")
        required = {"open": "PENDING", "pause": "OPEN", "resume": "PAUSED", "skip": "PENDING"}
        if row.status != required[action]:
            raise APIError(409, "ROUND_STATE_CONFLICT", "任务状态不允许此操作")
        before = RoundInfo.model_validate(row).model_dump(mode="json")
        if action in {"open", "resume"}:
            active = session.scalar(
                select(ScoringRound.id).where(
                    ScoringRound.event_id == event.id,
                    ScoringRound.status.in_(("OPEN", "PAUSED")),
                    ScoringRound.id != row.id,
                )
            )
            if active is not None:
                raise APIError(409, "ACTIVE_ROUND_EXISTS", "活动已有开放或暂停的评分任务")
            if action == "open":
                snapshot = session.get(EventSnapshot, row.rule_id)
                seconds = snapshot.duration_seconds
            else:
                seconds = row.remaining_seconds
            row.deadline_at = (
                now + timedelta(microseconds=int(Decimal(seconds) * 1000000))
                if seconds is not None
                else None
            )
            row.remaining_seconds = None
            row.status = "OPEN"
            event.status = "RUNNING"
        elif action == "pause":
            require_before_deadline(row, now)
            if row.deadline_at is not None:
                delta = row.deadline_at - now
                micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
                row.remaining_seconds = Decimal(micros) / Decimal(1000000)
            row.deadline_at = None
            row.status = "PAUSED"
        else:
            row.status = "SKIPPED"
        row.version += 1
        event.version += 1
        event.updated_at = now
        automatic_screen(event, action, row)
        advance_views(session, event)
        names = {
            "open": "round.opened",
            "pause": "round.paused",
            "resume": "round.resumed",
            "skip": "round.skipped",
        }
        record(session, event, names[action], now, public=True)
        after = RoundInfo.model_validate(row).model_dump(mode="json")
        if action == "skip":
            after["reason"] = body.reason
        audit(session, event, owner_id, f"round.{action}", row.id, before, after, request_id, now)
        session.flush()
        result = state(event, row, now)
    return result
