import math
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from score_api.auth.dependencies import check_csrf, database_for
from score_api.auth.schemas import CSRFInfo
from score_api.core.errors import ErrorResponse
from score_api.core.security import TOKEN_PATTERN
from score_api.judge_sessions import service
from score_api.judge_sessions.dependencies import cookie_name, require_judge
from score_api.judge_sessions.schemas import (
    ConfirmationInfo,
    ExchangeInput,
    JudgeSessionInfo,
    PreviewInfo,
    PublicCode,
    VerifyInput,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["judge-sessions"],
    responses={
        status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 429, 500, 503)
    },
)


def set_cookie(request, response, purpose, value, ttl):
    response.set_cookie(
        cookie_name(request, purpose),
        value,
        max_age=ttl,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def bootstrap_for(request):
    bootstrap = request.cookies.get(cookie_name(request, "bootstrap"), "")
    check_csrf(request, bootstrap if TOKEN_PATTERN.fullmatch(bootstrap) else None)
    return bootstrap


@router.get("/join/{code}", response_model=PreviewInfo)
def preview(code: PublicCode, request: Request):
    return service.preview(database_for(request), code)


@router.get("/judge-sessions/csrf", response_model=CSRFInfo)
def csrf(request: Request, response: Response):
    token = secrets.token_urlsafe(32)
    set_cookie(request, response, "bootstrap", token, 600)
    return CSRFInfo(csrf_token=token)


@router.post("/judge-sessions/verify", response_model=ConfirmationInfo)
def verify(body: VerifyInput, request: Request):
    bootstrap = bootstrap_for(request)
    return service.verify_identity(
        database_for(request),
        request.app.state.settings,
        request.app.state.clock,
        request.client.host if request.client else "unknown",
        body,
        bootstrap,
        request.state.request_id,
    )


@router.post("/judge-sessions/exchange", response_model=JudgeSessionInfo)
def exchange(body: ExchangeInput, request: Request, response: Response):
    bootstrap = bootstrap_for(request)
    token, result = service.exchange(
        database_for(request),
        request.app.state.settings,
        request.app.state.clock,
        request.client.host if request.client else "unknown",
        body,
        bootstrap,
        request.cookies.get(cookie_name(request, "session"), ""),
        request.state.request_id,
    )
    ttl = max(0, math.ceil((result.expires_at - request.app.state.clock()).total_seconds()))
    set_cookie(request, response, "session", token, ttl)
    return result


@router.get("/judge-sessions/me", response_model=JudgeSessionInfo)
def me(principal: Annotated[service.JudgePrincipal, Depends(require_judge)]):
    return principal.info


@router.post("/judge-sessions/logout", status_code=204)
def logout(request: Request, principal: Annotated[service.JudgePrincipal, Depends(require_judge)]):
    service.logout(
        database_for(request), principal, request.app.state.clock, request.state.request_id
    )
    response = Response(status_code=204)
    for purpose in ("session", "bootstrap"):
        response.delete_cookie(
            cookie_name(request, purpose),
            path="/",
            secure=request.app.state.settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
    return response
