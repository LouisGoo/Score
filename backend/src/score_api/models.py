"""本批只建立主办方认证所需表；不预建评委或活动表。"""

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from score_api.db import Base, UTCDateTime, utc_now


class Admin(Base):
    __tablename__ = "score_admins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AdminSession(Base):
    __tablename__ = "score_admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[str] = mapped_column(ForeignKey("score_admins.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class LoginBucket(Base):
    __tablename__ = "score_login_buckets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class AuthAudit(Base):
    __tablename__ = "score_auth_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    admin_id: Mapped[str | None] = mapped_column(ForeignKey("score_admins.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
