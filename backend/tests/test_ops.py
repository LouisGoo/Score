import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from score_api.core.config import Settings
from score_api.core.logging import ErrorFormatter, log_failure
from score_api.main import create_app


def production(**changes):
    values = dict(
        environment="production",
        PUBLIC_BASE_URL="https://score.example.org",
        allowed_origins=["https://score.example.org"],
        DATABASE_URL="mysql+pymysql://unused:unused@localhost/score",
        credential_hmac_key="ab" * 32,
    )
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_production_configuration():
    assert production().cookie_secure


@pytest.mark.parametrize(
    "changes",
    [
        {"PUBLIC_BASE_URL": None},
        {"PUBLIC_BASE_URL": "http://score.example.org"},
        {"PUBLIC_BASE_URL": "https://score.example.org/path"},
        {"PUBLIC_BASE_URL": "https://user:password@score.example.org"},
        {"cookie_secure": False},
        {"allowed_origins": ["http://localhost:5173"]},
        {"DATABASE_URL": None},
        {"credential_hmac_key": None},
    ],
)
def test_production_rejects_unsafe_configuration(changes):
    with pytest.raises(ValidationError):
        production(**changes)


@pytest.mark.parametrize(
    "error,status",
    [
        (RuntimeError("PASSWORD_SQL_SECRET"), 500),
        (SQLAlchemyError("PASSWORD_SQL_SECRET"), 503),
    ],
)
def test_request_failures_are_correlated_and_redacted(error, status):
    app = create_app(Settings(_env_file=None))

    @app.get("/api/v1/test-failure")
    def fail():
        raise error

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ErrorFormatter())
    logger = logging.getLogger("score.api")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/test-failure?ticket=QUERY_SECRET",
                headers={"Authorization": "Bearer HEADER_SECRET", "X-Request-ID": "FORGED_ID"},
            )
        assert response.status_code == status
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert records
        assert all(r["request_id"] == response.headers["X-Request-ID"] for r in records)
        assert any(r.get("error_type") == type(error).__name__ and r["frames"] for r in records)
        for secret in ("PASSWORD_SQL_SECRET", "QUERY_SECRET", "HEADER_SECRET", "FORGED_ID"):
            assert secret not in stream.getvalue() + response.text
    finally:
        logger.removeHandler(handler)


def test_failure_record_safe_even_with_default_formatter(caplog):
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("PRIVATE_EXCEPTION")
        except ValueError as error:
            log_failure(logging.getLogger("score.test"), "failed", error)
    assert "PRIVATE_EXCEPTION" not in caplog.text
    assert caplog.records[-1].exc_info is None


def test_third_party_message_omitted():
    record = logging.LogRecord("uvicorn.error", logging.ERROR, "", 1, "TOKEN_SECRET", (), None)
    assert "TOKEN_SECRET" not in ErrorFormatter().format(record)
