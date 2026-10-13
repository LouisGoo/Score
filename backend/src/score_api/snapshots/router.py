from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import APIError, ErrorResponse
from score_api.judge_sessions.dependencies import require_judge
from score_api.judge_sessions.service import JudgePrincipal
from score_api.snapshots import service
from score_api.snapshots.schemas import (
    AdminSnapshot,
    CreatedGrant,
    GrantInfo,
    GrantInput,
    JudgeSnapshot,
    ScreenDisplay,
    ScreenSettings,
    ScreenSnapshot,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["snapshots"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422, 503)},
)
Admin = Annotated[Principal, Depends(require_admin)]
Judge = Annotated[JudgePrincipal, Depends(require_judge)]
ScreenAuth = Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))]


@router.get("/events/{event_id}/snapshot", response_model=AdminSnapshot)
def admin_snapshot(event_id: str, request: Request, principal: Admin):
    return service.admin_snapshot(
        database_for(request), principal.admin.id, event_id, request.app.state.clock
    )


@router.get("/judge/events/{event_id}/snapshot", response_model=JudgeSnapshot)
def judge_snapshot(event_id: str, request: Request, principal: Judge):
    return service.judge_snapshot(
        database_for(request), principal, event_id, request.app.state.clock
    )


@router.get("/screens/{grant_id}/snapshot", response_model=ScreenSnapshot)
def screen_snapshot(grant_id: str, request: Request, authorization: ScreenAuth):
    headers = request.headers.getlist("authorization")
    if len(headers) != 1 or authorization is None:
        raise APIError(401, "SCREEN_GRANT_INVALID", "需要大屏只读授权")
    return service.screen_snapshot(
        database_for(request), grant_id, authorization.credentials, request.app.state.clock
    )


@router.post("/events/{event_id}/screen-grants", response_model=CreatedGrant, status_code=201)
def create_grant(event_id: str, body: GrantInput, request: Request, principal: Admin):
    return service.create_grant(
        database_for(request),
        principal.admin.id,
        event_id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.get("/events/{event_id}/screen-grants", response_model=list[GrantInfo])
def list_grants(event_id: str, request: Request, principal: Admin):
    return service.list_grants(database_for(request), principal.admin.id, event_id)


@router.delete("/events/{event_id}/screen-grants/{grant_id}", status_code=204)
def revoke_grant(event_id: str, grant_id: str, request: Request, principal: Admin):
    service.revoke_grant(
        database_for(request),
        principal.admin.id,
        event_id,
        grant_id,
        request.state.request_id,
        request.app.state.clock,
    )
    return Response(status_code=204)


@router.put("/events/{event_id}/screen", response_model=ScreenDisplay)
def change_display(event_id: str, body: ScreenSettings, request: Request, principal: Admin):
    return service.change_display(
        database_for(request),
        principal.admin.id,
        event_id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )
