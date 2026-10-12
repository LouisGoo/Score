import asyncio

import httpx

from score_api.core.config import Settings
from score_api.main import create_app


def test_liveness_without_external_services():
    async def request_liveness():
        transport = httpx.ASGITransport(app=create_app(Settings(_env_file=None)))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/health/live")

    response = asyncio.run(request_liveness())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
