from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime


class ScreenGrant(Base):
    __tablename__ = "score_screen_grants"
    __table_args__ = (
        Index("ix_score_screen_grants_event", "event_id", "created_at"),
        Base.__table_args__,
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("score_events.id"))
    token_hash: Mapped[str] = mapped_column(String(64, collation="ascii_bin"), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
