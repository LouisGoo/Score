from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from score_api.config import Settings
from score_api.db import UTCDateTime, create_db_engine
from score_api.main import create_app


def settings(**kwargs):
    return Settings(_env_file=None, DATABASE_URL=None, **kwargs)


def test_pool_budgets_and_no_eager_connection():
    config = Settings(_env_file=None, DATABASE_URL="mysql+pymysql://u:p@127.0.0.1/test")
    for role, size, overflow in [("api", 5, 5), ("worker", 2, 0)]:
        engine = create_db_engine(config, role)
        assert engine.pool.size() == size
        assert engine.pool._max_overflow == overflow
        assert engine.pool.checkedout() == 0
        assert engine.pool.timeout() == 3
        engine.dispose()
    engine = create_db_engine(config, "migration")
    assert isinstance(engine.pool, NullPool)
    engine.dispose()


@pytest.mark.parametrize("url", [None, "sqlite://", "broken-secret", "mysql+pymysql://host"])
def test_requires_mysql_and_redacts_invalid_url(url):
    with pytest.raises(ValueError) as error:
        create_db_engine(Settings(_env_file=None, DATABASE_URL=url))
    assert "broken-secret" not in str(error.value)


def test_utc_microseconds_and_reject_naive_time():
    column = UTCDateTime()
    value = datetime(2026, 10, 11, 12, 1, 2, 123456, tzinfo=timezone(timedelta(hours=8)))
    stored = column.process_bind_param(value, None)
    assert stored == datetime(2026, 10, 11, 4, 1, 2, 123456)
    assert column.process_result_value(stored, None) == value
    with pytest.raises(ValueError, match="时区"):
        column.process_bind_param(datetime(2026, 10, 11), None)
    assert column.process_bind_param(None, None) is None
    assert column.process_result_value(None, None) is None


def test_unconfigured_database_is_not_ready_but_live():
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable", "database": "unavailable"}
        assert response.headers["retry-after"] == "3"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("ready", [True, False])
def test_readiness_response_and_lifecycle(monkeypatch, ready):
    class StubDatabase:
        disposed = False

        def __init__(self, config):
            pass

        def is_ready(self):
            return ready

        def dispose(self):
            self.disposed = True

    monkeypatch.setattr("score_api.main.Database", StubDatabase)
    app = create_app(Settings(_env_file=None, DATABASE_URL="mysql+pymysql://u:p@localhost/db"))
    with TestClient(app) as client:
        database = app.state.database
        assert client.get("/api/v1/health/ready").status_code == (200 if ready else 503)
    assert database.disposed
    assert app.state.database is None


def test_database_error_response_is_sanitized(monkeypatch):
    class FailingDatabase:
        def __init__(self, config):
            pass

        def is_ready(self):
            raise OperationalError("secret-host secret-password", {}, Exception("secret"))

        def dispose(self):
            pass

    monkeypatch.setattr("score_api.main.Database", FailingDatabase)
    app = create_app(Settings(_env_file=None, DATABASE_URL="mysql+pymysql://u:p@localhost/db"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert "secret" not in response.text
        assert client.get("/api/v1/health/live").status_code == 200
