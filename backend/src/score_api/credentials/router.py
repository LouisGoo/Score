from typing import Annotated

from fastapi import APIRouter, Depends, Request

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.credentials import service
from score_api.credentials.schemas import CredentialInput, CredentialResult, ResetCredentialInput

router = APIRouter(
    prefix="/api/v1/events",
    tags=["credentials"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 500, 503)},
)


@router.post("/{event_id}/judges/{judge_id}/reset-credential", response_model=CredentialResult)
def reset_credential(
    event_id: str,
    judge_id: str,
    body: ResetCredentialInput,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
):
    return service.reset_credential(
        database_for(request),
        request.app.state.settings,
        principal.admin.id,
        event_id,
        judge_id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.put("/{event_id}/judges/{judge_id}/credential", response_model=CredentialResult)
def set_credential(
    event_id: str,
    judge_id: str,
    body: CredentialInput,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
):
    return service.set_credential(
        database_for(request),
        request.app.state.settings,
        principal.admin.id,
        event_id,
        judge_id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )
