import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.dialects.mysql import insert

from score_api.db import Database
from score_api.errors import APIError, ErrorResponse
from score_api.models import Admin, AdminSession, AuthAudit, LoginBucket
from score_api.security import (
    DUMMY_HASH,
    TOKEN_PATTERN,
    normalize_login,
    session_csrf,
    token_hash,
    verify_password,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 422, 429, 500, 503)},
)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("login")
    @classmethod
    def valid_login(cls, value: str) -> str:
        return normalize_login(value)


class AdminInfo(BaseModel):
    id: str
    login: str


class SessionInfo(BaseModel):
    admin: AdminInfo
    expires_at: datetime
    csrf_token: str


class CSRFInfo(BaseModel):
    csrf_token: str


@dataclass(frozen=True)
class Principal:
    admin: AdminInfo
    expires_at: datetime
    token_hash: str
    csrf_token: str


def database_for(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise APIError(503, "SERVICE_UNAVAILABLE", "服务暂时不可用", retry_after=3)
    return database


def cookie_name(request: Request, purpose: str) -> str:
    prefix = "__Host-" if request.app.state.settings.cookie_secure else ""
    return prefix + "score_admin_" + purpose


def set_cookie(request: Request, response: Response, purpose: str, value: str, ttl: int):
    response.set_cookie(
        cookie_name(request, purpose),
        value,
        max_age=ttl,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_cookie(request: Request, response: Response, purpose: str):
    response.delete_cookie(
        cookie_name(request, purpose),
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def check_csrf(request: Request, expected: str | None) -> None:
    supplied = request.headers.get("X-CSRF-Token", "")
    if (
        not expected
        or not supplied
        or len(supplied) > 128
        or not secrets.compare_digest(expected.encode(), supplied.encode())
    ):
        raise APIError(403, "CSRF_INVALID", "CSRF 校验失败，请重新获取令牌")


def require_admin(request: Request) -> Principal:
    token = request.cookies.get(cookie_name(request, "session"), "")
    if not TOKEN_PATTERN.fullmatch(token):
        raise APIError(401, "SESSION_EXPIRED", "会话失效，请重新登录")
    now = request.app.state.clock()
    with database_for(request).transaction() as session:
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
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, principal.csrf_token)
    return principal


def consume_login_limits(request: Request, login: str) -> None:
    settings = request.app.state.settings
    now = request.app.state.clock()
    # 不自行读取 X-Forwarded-For；只使用 ASGI 层已确定的客户端地址。
    ip = request.client.host if request.client else "unknown"
    retry_after = None
    with database_for(request).transaction() as session:
        # 清理过期的限流计数，保持每次工作量有界；不会删除会话或审计。
        session.execute(
            text("DELETE FROM score_login_buckets WHERE expires_at <= :now LIMIT 100"),
            {"now": now.replace(tzinfo=None)},
        )
        # 固定锁顺序：来源 -> 账号；先拒绝来源超限，避免任意账号撑大计数表。
        for dimension, value, limit in (
            ("ip", ip, settings.login_ip_limit),
            ("account", login, settings.login_account_limit),
        ):
            key = token_hash(dimension + ":" + value)
            session.execute(
                insert(LoginBucket)
                .values(
                    key=key,
                    attempts=0,
                    expires_at=now + timedelta(seconds=settings.login_window_seconds),
                )
                .on_duplicate_key_update(key=key)
            )
            bucket = session.scalar(
                select(LoginBucket).where(LoginBucket.key == key).with_for_update()
            )
            if bucket.expires_at <= now:
                bucket.attempts = 0
                bucket.expires_at = now + timedelta(seconds=settings.login_window_seconds)
            if bucket.attempts >= limit:
                retry_after = max(1, math.ceil((bucket.expires_at - now).total_seconds()))
                break
            bucket.attempts += 1
    # 必须在事务提交后拒绝，使错误密码与超限请求不能回滚已消耗配额。
    if retry_after is not None:
        raise APIError(429, "RATE_LIMITED", "登录尝试过于频繁", retry_after=retry_after)


def audit(session, request: Request, action: str, admin_id: str | None = None):
    session.add(
        AuthAudit(
            id=uuid4().hex,
            admin_id=admin_id,
            action=action,
            request_id=request.state.request_id,
            created_at=request.app.state.clock(),
        )
    )


@router.get("/csrf", response_model=CSRFInfo)
def login_csrf(request: Request, response: Response) -> CSRFInfo:
    """登录前获取双提交 CSRF 令牌；响应禁止缓存。"""
    token = secrets.token_urlsafe(32)
    set_cookie(request, response, "login_csrf", token, 600)
    return CSRFInfo(csrf_token=token)


@router.post("/login", response_model=SessionInfo)
def login(body: LoginInput, request: Request, response: Response) -> SessionInfo:
    bootstrap = request.cookies.get(cookie_name(request, "login_csrf"), "")
    check_csrf(request, bootstrap if TOKEN_PATTERN.fullmatch(bootstrap) else None)
    consume_login_limits(request, body.login)
    database = database_for(request)
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
            audit(session, request, "login_failed", current.id if current else None)
        else:
            now = request.app.state.clock()
            expires_at = now + timedelta(seconds=request.app.state.settings.session_ttl_seconds)
            token = secrets.token_urlsafe(32)
            # 再次登录时撤销此浏览器携带的旧会话，避免会话固定或遗留。
            old_token = request.cookies.get(cookie_name(request, "session"), "")
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
            audit(session, request, "login_succeeded", current.id)
            result = SessionInfo(
                admin=AdminInfo(id=current.id, login=current.login),
                expires_at=expires_at,
                csrf_token=session_csrf(token),
            )
    if not accepted:
        raise APIError(401, "INVALID_CREDENTIALS", "账号或密码错误")
    set_cookie(request, response, "session", token, request.app.state.settings.session_ttl_seconds)
    clear_cookie(request, response, "login_csrf")
    return result


@router.get("/me", response_model=SessionInfo)
def me(principal: Annotated[Principal, Depends(require_admin)]) -> SessionInfo:
    """查询当前身份，页面刷新后恢复 CSRF 令牌；不延长绝对会话期限。"""
    return SessionInfo(
        admin=principal.admin, expires_at=principal.expires_at, csrf_token=principal.csrf_token
    )


@router.post("/logout", status_code=204)
def logout(request: Request, principal: Annotated[Principal, Depends(require_admin)]) -> Response:
    now = request.app.state.clock()
    with database_for(request).transaction() as session:
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
        audit(session, request, "logout", principal.admin.id)
    response = Response(status_code=204)
    clear_cookie(request, response, "session")
    clear_cookie(request, response, "login_csrf")
    return response
