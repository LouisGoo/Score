import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from score_api.core.config import Settings
from score_api.credentials.schemas import ResetCredentialInput
from score_api.judge_sessions.schemas import ExchangeInput, VerifyInput
from score_api.main import create_app


@pytest.mark.parametrize(
    "changes",
    [
        {"code": None},
        {"code": "12345"},
        {"code": "ABC１２３４５"},
        {"judge_id": "somebody"},
        {"public_code": "too_short"},
        {"public_code": "ＡBCDEFGH2345"},
    ],
)
def test_identity_input_rejects_invalid_codes_and_client_identity(changes):
    with pytest.raises(ValidationError):
        VerifyInput.model_validate({"public_code": "ABCDEFGH2345", "code": "FIRST123", **changes})


def test_identity_normalization_and_secret_schema():
    request = VerifyInput(public_code=" abcdefgh2345 ", code=" first123 ")
    assert request.public_code == "ABCDEFGH2345" and request.code.get_secret_value() == "FIRST123"
    assert "FIRST123" not in repr(request)
    token = secrets.token_urlsafe(32)
    assert token not in repr(ExchangeInput(confirmation_token=token))
    for body in ({}, {"reason": " "}, {"reason": "x" * 501}):
        with pytest.raises(ValidationError):
            ResetCredentialInput.model_validate(body)
    for token in ("", "x" * 42, "x" * 44, "中" * 43):
        with pytest.raises(ValidationError):
            ExchangeInput(confirmation_token=token)


def test_public_auth_endpoints_origin_csrf_and_no_credential_echo():
    with TestClient(create_app(Settings(_env_file=None)), base_url="https://score.test") as client:
        bootstrap = client.get("/api/v1/judge-sessions/csrf")
        assert bootstrap.status_code == 200 and bootstrap.headers["cache-control"] == "no-store"
        body = {"public_code": "ABCDEFGH2345", "code": "FIRST123"}
        assert client.post("/api/v1/judge-sessions/verify", json=body).status_code == 403
        response = client.post(
            "/api/v1/judge-sessions/verify", json=body, headers={"Origin": "http://localhost:5173"}
        )
        assert response.json()["error"]["code"] == "CSRF_INVALID"
        response = client.post(
            "/api/v1/judge-sessions/verify",
            json={**body, "code": "secret_bad_code"},
            headers={
                "Origin": "http://localhost:5173",
                "X-CSRF-Token": bootstrap.json()["csrf_token"],
            },
        )
        assert response.status_code == 422 and "secret_bad_code" not in response.text
        assert client.get("/api/v1/judge-sessions/me").status_code == 503
        # 无数据库配置时也不伪装已经登录或验证成功。
        assert client.get("/api/v1/join/ABCDEFGH2345").status_code == 503
