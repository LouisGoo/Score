from datetime import datetime

from sqlalchemy import Computed, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class JudgeSession(Base):
    __tablename__ = "score_judge_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "judge_id"], ["score_event_judges.event_id", "score_event_judges.id"]
        ),
        UniqueConstraint("active_judge_id"),
        Index("ix_score_judge_sessions_expiry", "expires_at"),
        Base.__table_args__,
    )

    token_hash: Mapped[str] = mapped_column(String(64, collation="ascii_bin"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    judge_id: Mapped[str] = mapped_column(String(32))
    credential_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 过期会话在下一次兑换的锁内撤销；数据库独立保证至多一条未撤销记录。
    active_judge_id: Mapped[str | None] = mapped_column(
        String(32),
        Computed("CASE WHEN revoked_at IS NULL THEN judge_id ELSE NULL END", persisted=True),
    )


class JudgeConfirmation(Base):
    __tablename__ = "score_judge_confirmations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "judge_id"], ["score_event_judges.event_id", "score_event_judges.id"]
        ),
        Index("ix_score_judge_confirmations_expiry", "expires_at"),
        Base.__table_args__,
    )

    token_hash: Mapped[str] = mapped_column(String(64, collation="ascii_bin"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    judge_id: Mapped[str] = mapped_column(String(32))
    credential_version: Mapped[int]
    bootstrap_hash: Mapped[str] = mapped_column(String(64, collation="ascii_bin"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class JudgeAuthAudit(Base):
    __tablename__ = "score_judge_auth_audit"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "judge_id"], ["score_event_judges.event_id", "score_event_judges.id"]
        ),
        Index("ix_score_judge_auth_audit_event_created", "event_id", "created_at"),
        Base.__table_args__,
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("score_events.id", name="fk_judge_audit_event")
    )
    judge_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
