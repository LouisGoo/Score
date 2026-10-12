"""把请求中的会话与 CSRF 转为已验证的主办方身份。"""

import secrets

from fastapi import Request

from score_api.auth.service import Principal, get_principal
from score_api.core.errors import APIError
from score_api.core.security import TOKEN_PATTERN
from score_api.db import Database


def database_for(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise APIError(503, "SERVICE_UNAVAILABLE", "服务暂时不可用", retry_after=3)
    return database


def cookie_name(request: Request, purpose: str) -> str:
    prefix = "__Host-" if request.app.state.settings.cookie_secure else ""
    return prefix + "score_admin_" + purpose


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
    principal = get_principal(
        database_for(request),
        token,
        request.app.state.clock(),
    )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, principal.csrf_token)
    return principal
