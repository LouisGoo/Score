import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from score_api.auth.dependencies import database_for, require_admin
from score_api.core.errors import APIError, ErrorResponse
from score_api.core.security import TOKEN_PATTERN, token_hash
from score_api.judge_sessions.dependencies import require_judge
from score_api.realtime.service import (
    Authorization,
    TicketInfo,
    TicketInput,
    authorize,
    issue_ticket,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["realtime"],
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404, 422, 503)},
)


@router.post("/realtime/tickets", response_model=TicketInfo)
def ticket(body: TicketInput, request: Request):
    database = database_for(request)
    if body.role == "admin":
        principal = require_admin(request)
        subject, reference = principal.admin.id, principal.token_hash
    elif body.role == "judge":
        principal = require_judge(request)
        subject, reference = principal.judge_id, principal.token_hash
    else:
        headers = request.headers.getlist("authorization")
        if len(headers) != 1 or not headers[0].startswith("Bearer "):
            raise APIError(401, "SCREEN_GRANT_INVALID", "需要大屏授权")
        token = headers[0][7:]
        if not body.grant_id or not TOKEN_PATTERN.fullmatch(token):
            raise APIError(401, "SCREEN_GRANT_INVALID", "大屏授权无效")
        subject, reference = body.grant_id, token_hash(token)
    auth = Authorization(
        event_id=body.event_id, role=body.role, subject_id=subject, reference=reference
    )
    now = request.app.state.clock()
    authorize(database, auth, now)
    broker = request.app.state.realtime
    if broker is None or not broker.ready:
        raise APIError(503, "REALTIME_UNAVAILABLE", "实时服务暂不可用", retry_after=5)
    try:
        return issue_ticket(
            request.app.state.ticket_redis,
            auth,
            request.headers["origin"],
            now,
            request.app.state.settings.realtime_ticket_ttl_seconds,
        )
    except RedisError:
        raise APIError(503, "REALTIME_UNAVAILABLE", "实时服务暂不可用", retry_after=5) from None


async def send(websocket, message):
    # 慢客户端不能无限占用协程或积压消息。
    await asyncio.wait_for(websocket.send_json(message), timeout=5)


@router.websocket("/events/{event_id}/stream")
async def stream(websocket: WebSocket, event_id: str):
    state = websocket.app.state
    origins = websocket.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in state.settings.allowed_origins:
        await websocket.close(code=4403)
        return
    broker = state.realtime
    if broker is None or not broker.ready or state.database is None:
        await websocket.close(code=1013)
        return
    await websocket.accept()
    queue = None
    receiver = pending = None
    try:
        # 票据放在第一帧，避免 URL/代理访问日志记录任何凭证。
        first = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(first) > 256:
            raise ValueError
        token = json.loads(first).get("ticket", "")
        if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
            raise ValueError
        raw = await broker.redis.getdel("score:ticket:" + token_hash(token))
        if raw is None:
            raise ValueError
        claim = json.loads(raw)
        auth = Authorization.model_validate(claim["authorization"])
        if claim["origin"] != origins[0] or auth.event_id != event_id:
            raise ValueError
        queue = broker.attach(event_id)
        await run_in_threadpool(authorize, state.database, auth, state.clock())
        await send(websocket, {"type": "stream.ready", "event_id": event_id})
        # 只读协议；仍读取断开通知，避免空闲断线连接直到下一次事件才释放。
        receiver = asyncio.create_task(websocket.receive())
        pending = asyncio.create_task(queue.get())
        while broker.ready:
            done, _ = await asyncio.wait(
                {receiver, pending},
                timeout=state.settings.realtime_auth_interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                break
            await run_in_threadpool(authorize, state.database, auth, state.clock())
            if pending not in done:
                await send(websocket, {"type": "stream.heartbeat"})
                continue
            message = pending.result()
            pending = asyncio.create_task(queue.get())
            if message is None:
                break
            if message["type"] == "stream.resync":
                await send(websocket, {"type": "stream.resync", "event_id": event_id})
                continue
            for item in message.get("streams", []):
                if item["scope"] == auth.role and (
                    auth.role == "screen" or item["subject_id"] == auth.subject_id
                ):
                    # 明确白名单：永不转发内部 data、授权引用、评委 ID 或原始分。
                    await send(
                        websocket,
                        {
                            "event_id": event_id,
                            "message_id": message["message_id"],
                            "type": message["type"],
                            "scope": auth.role,
                            "version": item["version"],
                            "server_time": message["server_time"],
                            "payload": {},
                        },
                    )
        await websocket.close(code=1013)
    except APIError:
        with suppress(WebSocketDisconnect, RuntimeError, TimeoutError):
            await send(websocket, {"type": "session.revoked"})
            await websocket.close(code=4401)
    except (ValueError, KeyError, TypeError, AttributeError):
        await websocket.close(code=4401)
    except (RedisError, SQLAlchemyError, TimeoutError):
        with suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(code=1013)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if queue is not None:
            broker.detach(queue)
        for task in (receiver, pending):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
