from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from score_api.auth import cli as admin_cli
from score_api.auth.models import Admin, AdminSession, AuthAudit, LoginBucket
from score_api.auth.service import consume_login_limits
from score_api.core.errors import APIError
from score_api.core.security import token_hash, verify_password
from score_api.main import create_app

pytestmark = pytest.mark.mysql
ORIGIN = "https://score.test"
PASSWORD = "test-only-correct-password"


@pytest.fixture
def auth_database(database, mysql_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", mysql_settings.database_url.get_secret_value())
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")

    def clear():
        with database.transaction() as session:
            for model in (AuthAudit, AdminSession, LoginBucket, Admin):
                session.execute(delete(model))

    clear()
    yield database
    clear()


@pytest.fixture
def admin_id(auth_database):
    return admin_cli.create_admin(auth_database, " Host.Admin ", PASSWORD)


@pytest.fixture
def client(auth_database, mysql_settings, admin_id):
    config = mysql_settings.model_copy(update={"allowed_origins": [ORIGIN]})
    with TestClient(create_app(config), base_url=ORIGIN) as client:
        yield client
        assert client.app.state.database.engine.pool.checkedout() == 0


def login(client, name="host.admin", password=PASSWORD):
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/v1/auth/login",
        json={"login": name, "password": password},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )


def test_cli_creates_hash_and_audit_and_duplicate_is_atomic(auth_database, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["score_api.auth.cli", "Admin"])
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda _: PASSWORD)
    assert admin_cli.main() == 0
    assert admin_cli.main() == 1
    assert PASSWORD not in capsys.readouterr().out
    with auth_database.transaction() as session:
        admin = session.scalar(select(Admin))
        assert admin.login == "admin"
        encoded = admin.password_hash
        assert session.scalar(select(func.count()).select_from(Admin)) == 1
        assert session.scalar(select(func.count()).select_from(AuthAudit)) == 1
    assert verify_password(PASSWORD, encoded)
    with pytest.raises(IntegrityError):
        admin_cli.create_admin(auth_database, "ADMIN", PASSWORD)


def test_login_me_logout_and_revoked_cookie(client, auth_database, admin_id):
    response = login(client, "HOST.ADMIN")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["admin"] == {"id": admin_id, "login": "host.admin"}
    assert PASSWORD not in response.text and "password_hash" not in response.text
    cookie = client.cookies.get("__Host-score_admin_session")
    assert cookie not in response.text
    assert all(
        flag in response.headers.get_list("set-cookie")[0]
        for flag in ("Secure", "HttpOnly", "SameSite=strict", "Max-Age=28800")
    )
    with auth_database.transaction() as session:
        stored = session.get(AdminSession, token_hash(cookie))
        assert stored.admin_id == admin_id
        assert stored.revoked_at is None
        audit = session.scalar(select(AuthAudit).where(AuthAudit.action == "login_succeeded"))
        assert audit.request_id == response.headers["x-request-id"]
    assert client.get("/api/v1/auth/me").json() == result
    headers = {"Origin": ORIGIN, "X-CSRF-Token": result["csrf_token"]}
    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204 and not response.content
    assert client.cookies.get("__Host-score_admin_session") is None
    client.cookies.set("__Host-score_admin_session", cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 401
    with auth_database.transaction() as session:
        assert session.get(AdminSession, token_hash(cookie)).revoked_at is not None
        assert (
            session.scalar(
                select(func.count()).select_from(AuthAudit).where(AuthAudit.action == "logout")
            )
            == 1
        )


def test_wrong_unknown_disabled_accounts_have_same_error(client, auth_database, admin_id):
    wrong = login(client, password="wrong")
    unknown = login(client, name="unknown")
    with auth_database.transaction() as session:
        session.execute(update(Admin).where(Admin.id == admin_id).values(enabled=False))
    disabled = login(client)
    assert [r.status_code for r in (wrong, unknown, disabled)] == [401, 401, 401]
    assert wrong.json()["error"] == unknown.json()["error"] == disabled.json()["error"]
    with auth_database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(AdminSession)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthAudit)
                .where(AuthAudit.action == "login_failed")
            )
            == 3
        )


def test_server_expiry_boundary_and_no_sliding_refresh(client):
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    client.app.state.clock = lambda: now
    response = login(client)
    assert response.status_code == 200
    now += timedelta(seconds=28799)
    assert client.get("/api/v1/auth/me").json() == response.json()
    now += timedelta(seconds=1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_disabling_account_invalidates_existing_session(client, auth_database, admin_id):
    assert login(client).status_code == 200
    with auth_database.transaction() as session:
        session.execute(update(Admin).where(Admin.id == admin_id).values(enabled=False))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_relogin_rotates_session_and_csrf(client):
    first = login(client)
    old_cookie = client.cookies.get("__Host-score_admin_session")
    second = login(client)
    new_cookie = client.cookies.get("__Host-score_admin_session")
    assert old_cookie != new_cookie
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]},
        ).status_code
        == 403
    )
    client.cookies.clear()
    client.cookies.set("__Host-score_admin_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cross_site_logout_does_not_revoke(client):
    result = login(client).json()
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://evil.test", "X-CSRF-Token": result["csrf_token"]},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200


def test_shared_limit_across_apps_and_reset(client, mysql_settings):
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    client.app.state.clock = lambda: now
    client.app.state.settings.login_account_limit = 1
    assert login(client, password="wrong").status_code == 401
    config = client.app.state.settings.model_copy()
    with TestClient(create_app(config), base_url=ORIGIN) as other:
        other.app.state.clock = lambda: now
        limited = login(other)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "300"
        now += timedelta(seconds=300)
        assert login(other).status_code == 200


def test_ip_limit_counts_distinct_accounts_and_ignores_forwarded_header(client):
    client.app.state.settings.login_ip_limit = 1
    assert login(client, name="unknown-one").status_code == 401
    client.headers["X-Forwarded-For"] = "203.0.113.99"
    assert login(client, name="unknown-two").status_code == 429


def test_account_limit_across_sources_and_concurrent_atomicity(auth_database, mysql_settings):
    settings = mysql_settings.model_copy(update={"login_account_limit": 2})
    now = datetime.now(timezone.utc)
    barrier = Barrier(6)

    def consume(index):
        barrier.wait(timeout=3)
        try:
            consume_login_limits(auth_database, settings, now, f"192.0.2.{index}", "same-account")
            return 200
        except APIError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(consume, range(6)))
    assert sorted(statuses) == [200, 200, 429, 429, 429, 429]


def test_audit_failure_rolls_back_session_and_does_not_set_cookie(
    client, monkeypatch, auth_database
):
    def fail(*args, **kwargs):
        raise RuntimeError("secret-audit-error")

    monkeypatch.setattr("score_api.auth.service.audit", fail)
    response = login(client)
    assert response.status_code == 500
    assert "secret" not in response.text
    assert client.cookies.get("__Host-score_admin_session") is None
    with auth_database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_logout_audit_failure_rolls_back_revocation(client, monkeypatch):
    result = login(client).json()

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("score_api.auth.service.audit", fail)
    response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": result["csrf_token"],
        },
    )
    assert response.status_code == 500
    assert client.get("/api/v1/auth/me").status_code == 200


def test_password_verification_releases_connections_and_rechecks_account(
    client,
    monkeypatch,
    auth_database,
    admin_id,
):
    from score_api.auth import service as auth

    original = auth.verify_password

    def verify_and_disable(password, encoded):
        assert client.app.state.database.engine.pool.checkedout() == 0
        valid = original(password, encoded)
        with auth_database.transaction() as session:
            session.execute(update(Admin).where(Admin.id == admin_id).values(enabled=False))
        return valid

    monkeypatch.setattr(auth, "verify_password", verify_and_disable)
    assert login(client).status_code == 401
    with auth_database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(AdminSession)) == 0


def test_explicit_local_http_cookie_mode(auth_database, mysql_settings, admin_id):
    config = mysql_settings.model_copy(
        update={
            "cookie_secure": False,
            "allowed_origins": ["http://localhost:5173"],
        }
    )
    with TestClient(create_app(config), base_url="http://localhost:5173") as client:
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        response = client.post(
            "/api/v1/auth/login",
            json={
                "login": "host.admin",
                "password": PASSWORD,
            },
            headers={"Origin": "http://localhost:5173", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert client.cookies.get("score_admin_session")
        cookie = response.headers.get_list("set-cookie")[0]
        assert "Secure" not in cookie and "HttpOnly" in cookie
        assert client.get("/api/v1/auth/me").status_code == 200
