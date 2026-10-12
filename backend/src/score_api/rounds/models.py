from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base


class ScoringRound(Base):
    __tablename__ = "score_rounds"
    __table_args__ = (
        UniqueConstraint("event_id", "entry_id"),
        UniqueConstraint("event_id", "id", name="uq_score_rounds_event_pk"),
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
