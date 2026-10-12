from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from score_api.auth.router import router as auth_router
from score_api.core.config import Settings
from score_api.core.errors import install_error_handlers
from score_api.credentials.router import router as credentials_router
from score_api.db import Database, utc_now
from score_api.events.router import router as events_router
from score_api.judge_sessions.router import router as judge_sessions_router


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
        try:
            yield
        finally:
            if database is not None:
                database.dispose()
            app.state.database = None

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.database = None
    app.state.settings = settings
    app.state.clock = utc_now
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(events_router)
    app.include_router(credentials_router)
    app.include_router(judge_sessions_router)

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
