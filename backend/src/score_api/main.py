import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from redis import Redis
from sqlalchemy.exc import SQLAlchemyError

from score_api.auth.router import router as auth_router
from score_api.ballots.router import router as ballots_router
from score_api.core.config import Settings
from score_api.core.errors import install_error_handlers
from score_api.credentials.router import router as credentials_router
from score_api.db import Database, utc_now
from score_api.events.router import router as events_router
from score_api.exports.router import router as exports_router
from score_api.judge_sessions.router import router as judge_sessions_router
from score_api.realtime.broker import Broker, stop
from score_api.realtime.router import router as realtime_router
from score_api.results.router import router as results_router
from score_api.rounds.router import router as rounds_router
from score_api.snapshots.cache import SnapshotCache
from score_api.snapshots.router import router as snapshots_router


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ready", "unavailable"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings) if settings.database_url is not None else None
        app.state.database = database
        task = None
        if settings.redis_url is not None:
            url = settings.redis_url.get_secret_value()
            app.state.realtime = Broker(url)
            app.state.ticket_redis = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            task = asyncio.create_task(app.state.realtime.run())
        try:
            yield
        finally:
            if task is not None:
                await stop(task)
                app.state.ticket_redis.close()
            if database is not None:
                database.dispose()
            app.state.database = None

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.database = None
    app.state.realtime = None
    app.state.snapshot_cache = SnapshotCache()
    app.state.settings = settings
    app.state.clock = utc_now
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(events_router)
    app.include_router(exports_router)
    app.include_router(credentials_router)
    app.include_router(judge_sessions_router)
    app.include_router(rounds_router)
    app.include_router(ballots_router)
    app.include_router(results_router)
    app.include_router(snapshots_router)
    app.include_router(realtime_router)

    @app.get("/api/v1/health/live", response_model=Liveness, tags=["health"])
    def liveness() -> Liveness:
        """仅检查进程存活，不代表数据库就绪。"""
        return Liveness()

    @app.get(
        "/api/v1/health/ready",
        response_model=Readiness,
        responses={503: {"model": Readiness, "description": "数据库不可用或迁移未就绪"}},
        tags=["health"],
    )
    def readiness(response: Response) -> Readiness:
        """只读检查数据库与迁移版本；不返回内部连接信息。"""
        database = app.state.database
        try:
            ready = database is not None and database.is_ready()
        except SQLAlchemyError:
            ready = False
        response.headers["Cache-Control"] = "no-store"
        if not ready:
            response.status_code = 503
            response.headers["Retry-After"] = "3"
        return Readiness(
            status="ok" if ready else "unavailable",
            database="ready" if ready else "unavailable",
        )

    return app
