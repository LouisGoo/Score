import os
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from score_api.auth.models import Admin, AdminSession
from score_api.core.config import Settings
from score_api.core.security import session_csrf, token_hash
from score_api.db import Database, utc_now
from score_api.events.models import Entry, Event, EventAudit, EventJudge, EventSnapshot
from score_api.main import create_app
from score_api.rounds.models import RoundJudge, ScoringRound

ORIGIN = "https://score.test"


@pytest.fixture
def mysql_settings():
    url = os.environ.get("SCORE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("未设置 SCORE_TEST_DATABASE_URL，不以 SQLite 替代")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("集成测试必须使用名称以 _test 结尾的独立数据库")
    return Settings(_env_file=None, DATABASE_URL=url, db_pool_timeout=0.2)


@pytest.fixture
def database(mysql_settings):
    db = Database(mysql_settings, role="worker")
    yield db
    assert db.engine.pool.checkedout() == 0
    db.dispose()


@pytest.fixture
def event_db(database, mysql_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", mysql_settings.database_url.get_secret_value())
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    ids = [uuid4().hex, uuid4().hex]
    with database.transaction() as session:
        session.add_all([Admin(id=id_, login=id_, password_hash="unused") for id_ in ids])
    yield database, ids
    with database.transaction() as session:
        event_ids = select(Event.id).where(Event.owner_id.in_(ids))
        for model in (RoundJudge, ScoringRound, EventSnapshot, Entry, EventJudge):
            session.execute(delete(model).where(model.event_id.in_(event_ids)))
        session.execute(delete(EventAudit).where(EventAudit.actor_id.in_(ids)))
        session.execute(delete(Event).where(Event.owner_id.in_(ids)))
        session.execute(delete(AdminSession).where(AdminSession.admin_id.in_(ids)))
        session.execute(delete(Admin).where(Admin.id.in_(ids)))


@pytest.fixture
def clients(event_db, mysql_settings):
    db, ids = event_db
    config = mysql_settings.model_copy(
        update={"allowed_origins": [ORIGIN], "credential_hmac_key": SecretStr("ab" * 32)}
    )
    with (
        TestClient(create_app(config), base_url=ORIGIN) as first,
        TestClient(create_app(config), base_url=ORIGIN) as second,
    ):
        for client, owner in zip((first, second), ids, strict=True):
            token = secrets.token_urlsafe(32)
            now = utc_now()
            with db.transaction() as session:
                session.add(
                    AdminSession(
                        token_hash=token_hash(token),
                        admin_id=owner,
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                    )
                )
            client.cookies.set("__Host-score_admin_session", token)
            client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": session_csrf(token)})
        yield first, second
        for client in (first, second):
            assert client.app.state.database.engine.pool.checkedout() == 0
