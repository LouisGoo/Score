from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class ScoringRound(Base):
    __tablename__ = "score_rounds"
    __table_args__ = (
        UniqueConstraint("event_id", "entry_id"),
        UniqueConstraint("event_id", "id", name="uq_score_rounds_event_pk"),
        UniqueConstraint("active_event_id"),
        Index("ix_score_rounds_due", "status", "deadline_at", "id"),
        CheckConstraint("remaining_seconds IS NULL OR remaining_seconds >= 0", name="remaining"),
        ForeignKeyConstraint(
            ["event_id", "entry_id"], ["score_entries.event_id", "score_entries.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "rule_id"], ["score_event_snapshots.event_id", "score_event_snapshots.id"]
        ),
        CheckConstraint(
            "status IN ('PENDING', 'OPEN', 'PAUSED', 'CLOSED', "
            "'PUBLISHED', 'SKIPPED', 'NO_RESULT')",
            name="status",
        ),
        Base.__table_args__,
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    entry_id: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    version: Mapped[int] = mapped_column(default=1)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    remaining_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    active_event_id: Mapped[str | None] = mapped_column(
        String(32),
        Computed(
            "CASE WHEN status IN ('OPEN', 'PAUSED') THEN event_id ELSE NULL END", persisted=True
        ),
    )


class RoundJudge(Base):
    __tablename__ = "score_round_judges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "round_id"], ["score_rounds.event_id", "score_rounds.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "event_judge_id"], ["score_event_judges.event_id", "score_event_judges.id"]
        ),
        Base.__table_args__,
    )

    round_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_judge_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
