from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class OutboxEvent(Base):
    """内部事务事件；18 再转换为各角色的独立序列，不直接公开 payload。"""

    __tablename__ = "score_outbox"
    __table_args__ = (
        Index("ix_score_outbox_pending", "delivered_at", "created_at", "id"),
        Base.__table_args__,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("score_events.id"))
    version: Mapped[int]
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retry_count: Mapped[int] = mapped_column(default=0, server_default="0")
