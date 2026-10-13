from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from score_api.auth.dependencies import database_for
from score_api.ballots import service
from score_api.ballots.schemas import BallotInput, BallotReceipt
from score_api.core.errors import APIError, ErrorResponse
from score_api.judge_sessions.dependencies import require_judge
from score_api.judge_sessions.service import JudgePrincipal

router = APIRouter(
    prefix="/api/v1/rounds",
    tags=["ballots"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422, 500, 503)},
)
Judge = Annotated[JudgePrincipal, Depends(require_judge)]
KeyHeader = Annotated[
    list[str] | None,
    Header(alias="Idempotency-Key", description="本次确认操作的 UUID；重试复用原值"),
]


def idempotency_key(values, *, required=True):
    if not values and not required:
        return None
    try:
        if not values or len(values) != 1 or len(values[0]) != 36:
            raise ValueError
        key = UUID(values[0])
        if str(key) != values[0].lower():
            raise ValueError
    except ValueError:
        raise APIError(422, "VALIDATION_ERROR", "Idempotency-Key 必须为单一 UUID") from None
    return str(key)


@router.put("/{round_id}/my-ballot", response_model=BallotReceipt)
def submit_ballot(
    round_id: str,
    body: BallotInput,
    request: Request,
    principal: Judge,
    idempotency: KeyHeader,
):
    return service.submit_ballot(
        database_for(request),
        principal,
        round_id,
        body,
        idempotency_key(idempotency),
        request.state.request_id,
        request.app.state.clock,
    )


@router.get("/{round_id}/my-ballot", response_model=BallotReceipt)
def read_ballot(round_id: str, request: Request, principal: Judge, idempotency: KeyHeader = None):
    return service.read_ballot(
        database_for(request),
        principal,
        round_id,
        idempotency_key(idempotency, required=False),
        request.app.state.clock,
    )
