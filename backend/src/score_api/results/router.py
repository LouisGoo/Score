from typing import Annotated

from fastapi import APIRouter, Depends, Request

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.events.schemas import EventInfo
from score_api.results import service
from score_api.results.schemas import CloseInput, RankingInfo, ReopenInput, ResultHistory
from score_api.rounds.schemas import ControlInput, RoundState, SkipInput

router = APIRouter(
    prefix="/api/v1",
    tags=["results"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422, 503)},
)
Admin = Annotated[Principal, Depends(require_admin)]


def execute(round_id, action, body, request, principal):
    return service.control(
        database_for(request),
        principal.admin.id,
        round_id,
        action,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.post("/rounds/{round_id}/close", response_model=RoundState)
def close(round_id: str, body: CloseInput, request: Request, principal: Admin):
    return execute(round_id, "close", body, request, principal)


@router.post("/rounds/{round_id}/reopen", response_model=RoundState)
def reopen(round_id: str, body: ReopenInput, request: Request, principal: Admin):
    return execute(round_id, "reopen", body, request, principal)


@router.post("/rounds/{round_id}/publish-result", response_model=RoundState)
def publish(round_id: str, body: ControlInput, request: Request, principal: Admin):
    return execute(round_id, "publish", body, request, principal)


@router.post("/rounds/{round_id}/no-result", response_model=RoundState)
def no_result(round_id: str, body: SkipInput, request: Request, principal: Admin):
    return execute(round_id, "no-result", body, request, principal)


@router.get("/rounds/{round_id}/results", response_model=ResultHistory)
def results(round_id: str, request: Request, principal: Admin):
    return service.history(database_for(request), principal.admin.id, round_id)


@router.get("/events/{event_id}/ranking", response_model=list[RankingInfo])
def ranking(event_id: str, request: Request, principal: Admin):
    return service.read_ranking(database_for(request), principal.admin.id, event_id)


def change_event(event_id, action, body, request, principal):
    return service.lifecycle(
        database_for(request),
        principal.admin.id,
        event_id,
        action,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.post("/events/{event_id}/finish", response_model=EventInfo)
def finish(event_id: str, body: ControlInput, request: Request, principal: Admin):
    return change_event(event_id, "finish", body, request, principal)


@router.post("/events/{event_id}/archive", response_model=EventInfo)
def archive(event_id: str, body: ControlInput, request: Request, principal: Admin):
    return change_event(event_id, "archive", body, request, principal)
