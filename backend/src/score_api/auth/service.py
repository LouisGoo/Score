"""认证业务、事务和共享限流；不依赖 HTTP Request/Response。"""

import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from score_api.auth.models import Admin, AdminSession, AuthAudit, LoginBucket
from score_api.auth.schemas import AdminInfo, LoginInput, SessionInfo
from score_api.core.config import Settings
from score_api.core.errors import APIError
from score_api.core.security import (
    DUMMY_HASH,
    TOKEN_PATTERN,
    session_csrf,
    token_hash,
    verify_password,
)
from score_api.db import Database


@dataclass(frozen=True)
class Principal:
    admin: AdminInfo
    expires_at: datetime
    token_hash: str
    csrf_token: str


def get_principal(database: Database, token: str, now: datetime) -> Principal:
    if not TOKEN_PATTERN.fullmatch(token):
        raise APIError(401, "SESSION_EXPIRED", "会话失效，请重新登录")
    with database.transaction() as session:
        row = session.execute(
            select(AdminSession, Admin)
            .join(Admin, Admin.id == AdminSession.admin_id)
            .where(
                AdminSession.token_hash == token_hash(token),
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
                Admin.enabled.is_(True),
            )
        ).one_or_none()
        if row is None:
            raise APIError(401, "SESSION_EXPIRED", "会话失效，请重新登录")
        auth_session, admin = row
        principal = Principal(
            AdminInfo(id=admin.id, login=admin.login),
            auth_session.expires_at,
            auth_session.token_hash,
            session_csrf(token),
        )
    return principal


def consume_login_limits(
    database: Database,
    settings: Settings,
    now: datetime,
    source: str,
    login: str,
) -> None:
    consume_limits(
        database,
        now,
        settings.login_window_seconds,
        (
            ("ip", source, settings.login_ip_limit),
            ("account", login, settings.login_account_limit),
        ),
    )


def consume_limits(database, now, window_seconds, dimensions) -> None:
    """按调用方固定顺序锁定多个维度；错误尝试仍提交计数。"""
    retry_after = None
    with database.transaction() as session:
        # 清理过期的限流计数，保持每次工作量有界；不会删除会话或审计。
        session.execute(
            text("DELETE FROM score_login_buckets WHERE expires_at <= :now LIMIT 100"),
            {"now": now.replace(tzinfo=None)},
        )
        # 固定锁顺序：来源 -> 账号；先拒绝来源超限，避免任意账号撑大计数表。
        for dimension, value, limit in dimensions:
            key = token_hash(dimension + ":" + value)
            session.execute(
                insert(LoginBucket)
                .values(
                    key=key,
                    attempts=0,
                    expires_at=now + timedelta(seconds=window_seconds),
                )
                .on_duplicate_key_update(key=key)
            )
            bucket = session.scalar(
                select(LoginBucket).where(LoginBucket.key == key).with_for_update()
            )
            if bucket.expires_at <= now:
                bucket.attempts = 0
                bucket.expires_at = now + timedelta(seconds=window_seconds)
            if bucket.attempts >= limit:
                retry_after = max(1, math.ceil((bucket.expires_at - now).total_seconds()))
                break
            bucket.attempts += 1
    # 必须在事务提交后拒绝，使错误密码与超限请求不能回滚已消耗配额。
    if retry_after is not None:
        raise APIError(429, "RATE_LIMITED", "登录尝试过于频繁", retry_after=retry_after)


def audit(
    session: Session,
    request_id: str,
    now: datetime,
    action: str,
    admin_id: str | None = None,
) -> None:
    session.add(
        AuthAudit(
            id=uuid4().hex,
            admin_id=admin_id,
            action=action,
            request_id=request_id,
            created_at=now,
        )
    )


def authenticate(
    database: Database,
    settings: Settings,
    clock: Callable[[], datetime],
    request_id: str,
    source: str,
    body: LoginInput,
    old_token: str,
) -> tuple[str, SessionInfo]:
    consume_login_limits(database, settings, clock(), source, body.login)
    with database.transaction() as session:
        admin = session.scalar(select(Admin).where(Admin.login == body.login))
        encoded = admin.password_hash if admin is not None else DUMMY_HASH
    valid = verify_password(body.password.get_secret_value(), encoded)
    # scrypt 在数据库事务外执行。加锁重新验证账号状态与密码版本。
    with database.transaction() as session:
        current = session.scalar(select(Admin).where(Admin.login == body.login).with_for_update())
        accepted = (
            valid and current is not None and current.enabled and current.password_hash == encoded
        )
        if not accepted:
            audit(session, request_id, clock(), "login_failed", current.id if current else None)
        else:
            now = clock()
            expires_at = now + timedelta(seconds=settings.session_ttl_seconds)
            token = secrets.token_urlsafe(32)
            # 再次登录时撤销此浏览器携带的旧会话，避免会话固定或遗留。
            if TOKEN_PATTERN.fullmatch(old_token):
                session.execute(
                    update(AdminSession)
                    .where(
                        AdminSession.token_hash == token_hash(old_token),
                        AdminSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            session.add(
                AdminSession(
                    token_hash=token_hash(token),
                    admin_id=current.id,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            audit(session, request_id, clock(), "login_succeeded", current.id)
            result = SessionInfo(
                admin=AdminInfo(id=current.id, login=current.login),
                expires_at=expires_at,
                csrf_token=session_csrf(token),
            )
    if not accepted:
        raise APIError(401, "INVALID_CREDENTIALS", "账号或密码错误")
    return token, result


def revoke_session(
    database: Database,
    principal: Principal,
    now: datetime,
    request_id: str,
) -> None:
    with database.transaction() as session:
        result = session.execute(
            update(AdminSession)
            .where(
                AdminSession.token_hash == principal.token_hash,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
            )
            .values(revoked_at=now)
        )
        if not result.rowcount:
            raise APIError(401, "SESSION_EXPIRED", "会话失效，请重新登录")
        audit(session, request_id, now, "logout", principal.admin.id)
