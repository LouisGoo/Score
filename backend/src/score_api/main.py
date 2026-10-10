from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from score_api.config import Settings


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    @app.get("/api/v1/health/live", response_model=Liveness, tags=["health"])
    def liveness() -> Liveness:
        """Process liveness only; this does not indicate database readiness."""
        return Liveness()

    return app
