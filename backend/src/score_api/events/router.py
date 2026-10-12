"""主办方草稿接口，所有端点复用服务端会话和写请求 CSRF 校验。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from score_api.auth.dependencies import database_for, require_admin
from score_api.auth.service import Principal
from score_api.core.errors import ErrorResponse
from score_api.events import service
from score_api.events.models import Entry, EventJudge
from score_api.events.schemas import (
    EntryCreate,
    EntryInfo,
    EntryPatch,
    EventCreate,
    EventInfo,
    EventPatch,
    JudgeCreate,
    JudgeInfo,
    JudgePatch,
)

router = APIRouter(
    prefix="/api/v1/events",
    tags=["events"],
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 500, 503)},
)
Admin = Annotated[Principal, Depends(require_admin)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1000000)]


@router.post("", response_model=EventInfo, status_code=201)
def create_event(body: EventCreate, request: Request, principal: Admin):
    return service.create_event(
        database_for(request),
        principal.admin.id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.get("", response_model=list[EventInfo])
def list_events(request: Request, principal: Admin, offset: Offset = 0, limit: Limit = 100):
    return service.list_events(database_for(request), principal.admin.id, offset, limit)


@router.get("/{event_id}", response_model=EventInfo)
def get_event(event_id: str, request: Request, principal: Admin):
    return service.get_event(database_for(request), principal.admin.id, event_id)


@router.patch("/{event_id}", response_model=EventInfo)
def patch_event(event_id: str, body: EventPatch, request: Request, principal: Admin):
    return service.patch_event(
        database_for(request),
        principal.admin.id,
        event_id,
        body,
        request.state.request_id,
        request.app.state.clock,
    )


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: str, request: Request, principal: Admin):
    service.delete_event(
        database_for(request),
        principal.admin.id,
        event_id,
        request.state.request_id,
        request.app.state.clock,
    )
    return Response(status_code=204)


@router.get("/{event_id}/entries", response_model=list[EntryInfo])
def list_entries(
    event_id: str, request: Request, principal: Admin, offset: Offset = 0, limit: Limit = 100
):
    return service.read_members(
        database_for(request), principal.admin.id, event_id, Entry, offset=offset, limit=limit
    )


@router.get("/{event_id}/entries/{entry_id}", response_model=EntryInfo)
def get_entry(event_id: str, entry_id: str, request: Request, principal: Admin):
    return service.read_members(
        database_for(request), principal.admin.id, event_id, Entry, entry_id
    )


@router.post("/{event_id}/entries", response_model=EntryInfo, status_code=201)
def create_entry(event_id: str, body: EntryCreate, request: Request, principal: Admin):
    return service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        Entry,
        "created",
        body,
        None,
        request.state.request_id,
        request.app.state.clock,
    )


@router.patch("/{event_id}/entries/{entry_id}", response_model=EntryInfo)
def patch_entry(event_id: str, entry_id: str, body: EntryPatch, request: Request, principal: Admin):
    return service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        Entry,
        "updated",
        body,
        entry_id,
        request.state.request_id,
        request.app.state.clock,
    )


@router.delete("/{event_id}/entries/{entry_id}", status_code=204)
def delete_entry(event_id: str, entry_id: str, request: Request, principal: Admin):
    service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        Entry,
        "deleted",
        None,
        entry_id,
        request.state.request_id,
        request.app.state.clock,
    )
    return Response(status_code=204)


@router.get("/{event_id}/judges", response_model=list[JudgeInfo])
def list_judges(
    event_id: str, request: Request, principal: Admin, offset: Offset = 0, limit: Limit = 100
):
    return service.read_members(
        database_for(request), principal.admin.id, event_id, EventJudge, offset=offset, limit=limit
    )


@router.get("/{event_id}/judges/{judge_id}", response_model=JudgeInfo)
def get_judge(event_id: str, judge_id: str, request: Request, principal: Admin):
    return service.read_members(
        database_for(request), principal.admin.id, event_id, EventJudge, judge_id
    )


@router.post("/{event_id}/judges", response_model=JudgeInfo, status_code=201)
def create_judge(event_id: str, body: JudgeCreate, request: Request, principal: Admin):
    return service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        EventJudge,
        "created",
        body,
        None,
        request.state.request_id,
        request.app.state.clock,
    )


@router.patch("/{event_id}/judges/{judge_id}", response_model=JudgeInfo)
def patch_judge(event_id: str, judge_id: str, body: JudgePatch, request: Request, principal: Admin):
    return service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        EventJudge,
        "updated",
        body,
        judge_id,
        request.state.request_id,
        request.app.state.clock,
    )


@router.delete("/{event_id}/judges/{judge_id}", status_code=204)
def delete_judge(event_id: str, judge_id: str, request: Request, principal: Admin):
    service.write_member(
        database_for(request),
        principal.admin.id,
        event_id,
        EventJudge,
        "deleted",
        None,
        judge_id,
        request.state.request_id,
        request.app.state.clock,
    )
    return Response(status_code=204)
