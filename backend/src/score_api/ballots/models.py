"""有效评分指针、追加版本与永久幂等回执，均保留历史外键。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class Ballot(Base):
    __tablename__ = "score_ballots"
    __table_args__ = (
        UniqueConstraint("round_id", "judge_id"),
        UniqueConstraint("event_id", "id", name="uq_score_ballots_event_pk"),
        ForeignKeyConstraint(
            ["event_id", "round_id"], ["score_rounds.event_id", "score_rounds.id"]
        ),
        ForeignKeyConstraint(
            ["round_id", "judge_id"],
            ["score_round_judges.round_id", "score_round_judges.event_judge_id"],
        ),
        CheckConstraint("current_revision >= 1", name="revision"),
        Base.__table_args__,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    round_id: Mapped[str] = mapped_column(String(32))
    judge_id: Mapped[str] = mapped_column(String(32))
    current_revision: Mapped[int]


class BallotRevision(Base):
    __tablename__ = "score_ballot_revisions"
    __table_args__ = (
        UniqueConstraint("ballot_id", "revision"),
        ForeignKeyConstraint(
            ["event_id", "ballot_id"], ["score_ballots.event_id", "score_ballots.id"]
        ),
        CheckConstraint("revision >= 1", name="revision"),
        Base.__table_args__,
    )
    # 每个已接受版本对应一个永久回执。
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    ballot_id: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int]
    rule_version: Mapped[int]
    scores: Mapped[list] = mapped_column(JSON)
    # 仅作查询缓存；成绩复算必须使用原始 scores 与冻结规则。
    computed_total: Mapped[Decimal] = mapped_column(Numeric(65, 30))
    display_total: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime())


class IdempotencyRecord(Base):
    __tablename__ = "score_ballot_idempotency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "judge_id"], ["score_event_judges.event_id", "score_event_judges.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "ballot_id"],
            ["score_ballots.event_id", "score_ballots.id"],
            name="fk_score_idempotency_ballot",
        ),
        Base.__table_args__,
    )
    judge_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(36, collation="ascii_bin"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    ballot_id: Mapped[str] = mapped_column(String(32))
    request_hash: Mapped[str] = mapped_column(String(64, collation="ascii_bin"))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class BallotAudit(Base):
    __tablename__ = "score_ballot_audit"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "ballot_id"], ["score_ballots.event_id", "score_ballots.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "judge_id"],
            ["score_event_judges.event_id", "score_event_judges.id"],
            name="fk_score_ballot_audit_judge",
        ),
        Index("ix_score_ballot_audit_event_created", "event_id", "created_at"),
        Base.__table_args__,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    ballot_id: Mapped[str] = mapped_column(String(32))
    judge_id: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    before_revision: Mapped[int | None]
    after_revision: Mapped[int]
    request_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
