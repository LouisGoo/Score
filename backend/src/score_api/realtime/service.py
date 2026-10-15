"""短时票据只存授权引用；兑换、连接、发送前均以数据库授权为准。"""

import json
import secrets
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from score_api.auth.models import Admin, AdminSession
from score_api.core.errors import APIError
from score_api.core.security import token_hash
from score_api.events.models import Event, EventJudge
from score_api.judge_sessions.models import JudgeSession
from score_api.snapshots.models import ScreenGrant


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=32, max_length=32)
    role: Literal["admin", "judge", "screen"]
    grant_id: str | None = Field(default=None, min_length=32, max_length=32)


class TicketInfo(BaseModel):
    ticket: str
    expires_at: str
    stream_path: str


class VersionInfo(BaseModel):
    version: int
    server_time: datetime


class Authorization(BaseModel):
    event_id: str
    role: Literal["admin", "judge", "screen"]
    subject_id: str
    reference: str


def authorize(database, auth, now, *, snapshot=False):
    with database.read_snapshot() as session:
        event = session.get(Event, auth.event_id)
        if snapshot and auth.role == "admin" and event is not None:
            if event.owner_id != auth.subject_id:
                raise APIError(404, "NOT_FOUND", "活动不存在")
            if event.status == "DRAFT":
                raise APIError(409, "EVENT_NOT_PUBLISHED", "活动尚未发布")
        if event is None or event.status == "DRAFT":
            raise APIError(404, "NOT_FOUND", "活动不存在或尚未发布")
        if auth.role == "admin":
            valid = session.scalar(
                select(AdminSession.token_hash)
                .join(Admin)
                .where(
                    AdminSession.token_hash == auth.reference,
                    AdminSession.admin_id == auth.subject_id,
                    AdminSession.revoked_at.is_(None),
                    AdminSession.expires_at > now,
                    Admin.enabled.is_(True),
                    Admin.id == event.owner_id,
                )
            )
        elif auth.role == "judge":
            valid = session.scalar(
                select(EventJudge.snapshot_version)
                .select_from(JudgeSession)
                .join(EventJudge, EventJudge.id == JudgeSession.judge_id)
                .where(
                    JudgeSession.token_hash == auth.reference,
                    JudgeSession.event_id == event.id,
                    EventJudge.event_id == event.id,
                    JudgeSession.judge_id == auth.subject_id,
                    JudgeSession.revoked_at.is_(None),
                    JudgeSession.expires_at > now,
                    JudgeSession.credential_version == EventJudge.credential_version,
                )
            )
        else:
            valid = session.scalar(
                select(ScreenGrant.id).where(
                    ScreenGrant.id == auth.subject_id,
                    ScreenGrant.event_id == event.id,
                    ScreenGrant.token_hash == auth.reference,
                    ScreenGrant.revoked_at.is_(None),
                    ScreenGrant.expires_at > now,
                )
            )
        if valid is None:
            raise APIError(401, "SESSION_EXPIRED", "实时授权已失效")
        return (
            valid
            if auth.role == "judge"
            else (event.version if auth.role == "admin" else event.screen_version)
        )


def issue_ticket(redis, auth, origin, now, ttl):
    token = secrets.token_urlsafe(32)
    redis.set(
        "score:ticket:" + token_hash(token),
        json.dumps({"authorization": auth.model_dump(), "origin": origin}),
        ex=ttl,
    )
    return TicketInfo(
        ticket=token,
        expires_at=(now + timedelta(seconds=ttl)).isoformat(),
        stream_path=f"/api/v1/events/{auth.event_id}/stream",
    )
