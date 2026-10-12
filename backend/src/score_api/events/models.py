"""活动草稿及名单；编号使用区分大小写的字符串唯一约束。"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class Event(Base):
    __tablename__ = "score_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'READY', 'RUNNING', 'FINISHED', 'ARCHIVED')", name="status"
        ),
        Index("ix_score_events_owner_created", "owner_id", "created_at", "id"),
        Base.__table_args__,
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("score_admins.id"))
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(2000), default="")
    organization: Mapped[str] = mapped_column(String(120), default="")
    planned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    scoring_rule: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    duration_seconds: Mapped[int | None]
    allow_revisions: Mapped[bool] = mapped_column(default=True)
    screen_title: Mapped[str] = mapped_column(String(80), default="")
    screen_theme: Mapped[str] = mapped_column(String(8), default="light")
    show_public_qr: Mapped[bool] = mapped_column(default=True)
    leaderboard_limit: Mapped[int] = mapped_column(default=10)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Entry(Base):
    __tablename__ = "score_entries"
    __table_args__ = (UniqueConstraint("event_id", "number"), Base.__table_args__)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("score_events.id"))
    number: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(2000), default="")
    sort_order: Mapped[int] = mapped_column(default=0)


class EventJudge(Base):
    __tablename__ = "score_event_judges"
    __table_args__ = (UniqueConstraint("event_id", "number"), Base.__table_args__)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("score_events.id"))
    number: Mapped[str] = mapped_column(String(32, collation="utf8mb4_bin"))
    name: Mapped[str] = mapped_column(String(80))


class EventAudit(Base):
    """草稿变更审计；不级联删除，保留已删除活动与对象的内部 ID。"""

    __tablename__ = "score_event_audit"
    __table_args__ = (
        Index("ix_score_event_audit_event_created", "event_id", "created_at"),
        Base.__table_args__,
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(ForeignKey("score_admins.id"))
    action: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(32))
    before: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    after: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    request_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
