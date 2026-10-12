"""认证端点与 Cookie；数据库状态变更委托服务层。"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from score_api.auth import service
from score_api.auth.dependencies import check_csrf, cookie_name, database_for, require_admin
from score_api.auth.schemas import CSRFInfo, LoginInput, SessionInfo
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.core.security import TOKEN_PATTERN

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 422, 429, 500, 503)},
)


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
    # 不自行读取 X-Forwarded-For；只使用 ASGI 层已确定的客户端地址。
    source = request.client.host if request.client else "unknown"
    token, result = service.authenticate(
        database_for(request),
        request.app.state.settings,
        request.app.state.clock,
        request.state.request_id,
        source,
        body,
        request.cookies.get(cookie_name(request, "session"), ""),
    )
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
    service.revoke_session(
        database_for(request),
        principal,
        request.app.state.clock(),
        request.state.request_id,
    )
    response = Response(status_code=204)
    clear_cookie(request, response, "session")
    clear_cookie(request, response, "login_csrf")
    return response
