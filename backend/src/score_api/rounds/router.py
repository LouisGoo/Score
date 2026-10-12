from typing import Annotated

from fastapi import APIRouter, Depends, Request

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.rounds import service
from score_api.rounds.schemas import ControlInput, RoundState, SkipInput

router = APIRouter(
    prefix="/api/v1/rounds",
    tags=["rounds"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422, 500, 503)},
)
Admin = Annotated[Principal, Depends(require_admin)]


@router.get("/{round_id}", response_model=RoundState)
def read_round(round_id: str, request: Request, principal: Admin):
    return service.read_round(
        database_for(request), principal.admin.id, round_id, request.app.state.clock
    )


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


@router.post("/{round_id}/open", response_model=RoundState)
def open_round(round_id: str, body: ControlInput, request: Request, principal: Admin):
    return execute(round_id, "open", body, request, principal)


@router.post("/{round_id}/pause", response_model=RoundState)
def pause_round(round_id: str, body: ControlInput, request: Request, principal: Admin):
    return execute(round_id, "pause", body, request, principal)


@router.post("/{round_id}/resume", response_model=RoundState)
def resume_round(round_id: str, body: ControlInput, request: Request, principal: Admin):
    return execute(round_id, "resume", body, request, principal)


@router.post("/{round_id}/skip", response_model=RoundState)
def skip_round(round_id: str, body: SkipInput, request: Request, principal: Admin):
    return execute(round_id, "skip", body, request, principal)
