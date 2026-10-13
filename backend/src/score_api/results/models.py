"""每次收评追加不可变快照；重开保留旧快照，公布冻结最新一份。"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class ResultSnapshot(Base):
    __tablename__ = "score_result_snapshots"
    __table_args__ = (
        UniqueConstraint("round_id", "round_version"),
        ForeignKeyConstraint(
            ["event_id", "round_id"], ["score_rounds.event_id", "score_rounds.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "rule_id"], ["score_event_snapshots.event_id", "score_event_snapshots.id"]
        ),
        Base.__table_args__,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    round_id: Mapped[str] = mapped_column(String(32))
    round_version: Mapped[int]
    rule_id: Mapped[str] = mapped_column(String(32))
    calculation: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(16))
    closed_at: Mapped[datetime] = mapped_column(UTCDateTime())
