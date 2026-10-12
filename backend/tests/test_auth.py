from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from score_api import admin_cli, security
from score_api.config import Settings
from score_api.errors import APIError
from score_api.main import create_app

ORIGIN = "https://score.test"
PASSWORD = "test-only-correct-password"


@pytest.fixture
def client():
    app = create_app(Settings(_env_file=None, DATABASE_URL=None, allowed_origins=[ORIGIN]))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def test_scrypt_random_salt_and_wrong_password():
    first = security.hash_password(PASSWORD)
    second = security.hash_password(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert security.verify_password(PASSWORD, first)
    assert not security.verify_password("wrong", first)
    assert not security.verify_password(PASSWORD, security.DUMMY_HASH)
    assert not security.verify_password(PASSWORD, "corrupt")
    assert not security.verify_password(PASSWORD, first.replace("131072", "999999999"))
    assert not security.verify_password("x" * 129, first)


@pytest.mark.parametrize("password", ["", "too-short", "x" * 129])
def test_admin_password_policy(password):
    with pytest.raises(ValueError):
        security.hash_password(password)


def test_password_work_is_bounded():
    with security.PASSWORD_SLOTS, security.PASSWORD_SLOTS, pytest.raises(APIError) as error:
        security.hash_password(PASSWORD)
    assert error.value.code == "AUTH_BUSY"


@pytest.mark.parametrize("origin", ["*", "null", "https://x/path", "https://u:p@x", "https://x/"])
def test_origin_config_rejects_ambiguous_values(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL=None, allowed_origins=[origin])


@pytest.mark.parametrize("origin", [None, "null", "https://evil.test", ORIGIN + ".evil.test"])
def test_login_rejects_cross_site_or_missing_origin(client, origin):
    headers = {"Origin": origin} if origin is not None else {}
    response = client.post("/api/v1/auth/login", headers=headers, json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_FORBIDDEN"


def test_duplicate_origin_is_rejected(client):
    response = client.post("/api/v1/auth/login", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])
    assert response.status_code == 403


def test_bootstrap_cookie_and_csrf_required_even_for_login(client):
    response = client.get("/api/v1/auth/csrf")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-score_admin_login_csrf=")
    assert all(part in cookie for part in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert "Domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    for csrf in (None, "wrong"):
        headers = {"Origin": ORIGIN}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        response = client.post(
            "/api/v1/auth/login", headers=headers, json={"login": "admin", "password": PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_unconfigured_database_fails_closed(client):
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        json={"login": "admin", "password": PASSWORD},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_validation_not_found_method_errors_are_sanitized(client):
    responses = [
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"login": "invalid", "password": {"secret": PASSWORD}},
        ),
        client.get("/api/v1/auth/register"),
        client.get("/api/v1/auth/login"),
    ]
    assert [r.status_code for r in responses] == [422, 404, 405]
    for response in responses:
        assert PASSWORD not in response.text
        assert response.json()["request_id"] == response.headers["x-request-id"]
        UUID(response.json()["request_id"])
    assert "POST" in responses[-1].headers["allow"]


@pytest.mark.parametrize(
    "exception,status,code",
    [
        (RuntimeError("secret-password"), 500, "INTERNAL_ERROR"),
        (
            OperationalError("secret-password", {}, Exception("secret-host")),
            503,
            "SERVICE_UNAVAILABLE",
        ),
    ],
)
def test_unexpected_errors_hide_internal_details(client, exception, status, code):
    @client.app.get("/test-error")
    def fail():
        raise exception

    response = client.get("/test-error", headers={"X-Request-ID": "attacker-controlled"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text
    assert response.headers["x-request-id"] != "attacker-controlled"


def test_no_public_registration(client):
    assert "/api/v1/auth/register" not in client.get("/openapi.json").json()["paths"]
    response = client.post("/api/v1/auth/register", headers={"Origin": ORIGIN})
    assert response.status_code == 404


def test_cli_confirmation_mismatch_does_not_open_database(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["score_api.admin_cli", "admin"])
    entries = iter([PASSWORD, "different"])
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda _: next(entries))
    assert admin_cli.main() == 1
    assert PASSWORD not in capsys.readouterr().out


def test_cli_refuses_echoed_password_fallback(monkeypatch, capsys):
    import warnings

    monkeypatch.setattr("sys.argv", ["score_api.admin_cli", "admin"])

    def prompt(_):
        warnings.warn("no terminal", admin_cli.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("不得降级到回显密码输入")

    monkeypatch.setattr(admin_cli.getpass, "getpass", prompt)
    assert admin_cli.main() == 1
    assert "交互式终端" in capsys.readouterr().out
