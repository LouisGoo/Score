from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.exports.service import export_csv

router = APIRouter(
    prefix="/api/v1/events",
    tags=["exports"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422, 503)},
)


@router.get(
    "/{event_id}/exports/{kind}",
    response_class=Response,
    responses={
        200: {
            "description": "UTF-8 BOM CSV；默认仅已公布任务，审计另含活动级操作。",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {"Content-Disposition": {"schema": {"type": "string"}}},
        }
    },
)
def download(
    event_id: str,
    kind: Literal["summary", "details", "audit"],
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    include_unpublished: bool = False,
):
    content, filename = export_csv(
        database_for(request),
        principal.admin.id,
        event_id,
        kind,
        include_unpublished,
        request.app.state.clock,
    )
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{kind}.csv\"; filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
