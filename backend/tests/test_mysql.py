"""真实 MySQL 验证；迁移测试只允许显式指定名称以 _test 结尾的独立库。"""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table, inspect, select, text
from sqlalchemy.exc import TimeoutError

from score_api.core.config import Settings
from score_api.db import VERSION_TABLE, Database, UTCDateTime
from score_api.main import create_app

pytestmark = pytest.mark.mysql


@pytest.fixture
def sample_table(database):
    table = Table(
        "score_probe_" + uuid4().hex,
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
        Column("at", UTCDateTime(), nullable=True),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    table.create(database.engine)
    try:
        yield table
    finally:
        table.drop(database.engine)


def test_migration_upgrade_downgrade_and_readiness(mysql_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", mysql_settings.database_url.get_secret_value())
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    db = Database(mysql_settings)
    legacy = Table(
        "alembic_version", MetaData(), Column("version_num", String(32), primary_key=True)
    )
    legacy_created = not inspect(db.engine).has_table(legacy.name)
    if legacy_created:
        legacy.create(db.engine)
        with db.engine.begin() as connection:
            connection.execute(legacy.insert().values(version_num="unrelated_project_revision"))
    with db.engine.connect() as connection:
        previous_revisions = list(connection.execute(select(legacy)).scalars())
    try:
        # CI 和本地 Compose 提供独立测试库；不得向业务库运行此测试。
        command.downgrade(config, "base")
        assert not db.is_ready()
        command.upgrade(config, "head")
        assert db.is_ready()
        assert inspect(db.engine).has_table(VERSION_TABLE)
        command.upgrade(config, "head")
        assert db.is_ready()
        with TestClient(create_app(mysql_settings)) as client:
            assert client.get("/api/v1/health/ready").status_code == 200
        command.check(config)
        command.downgrade(config, "base")
        assert not db.is_ready()
        command.upgrade(config, "head")
        with db.engine.connect() as connection:
            assert list(connection.execute(select(legacy)).scalars()) == previous_revisions
    finally:
        if legacy_created:
            legacy.drop(db.engine)
        db.dispose()


def test_session_settings_and_transaction_release(database, sample_table):
    with database.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT @@session.time_zone, @@session.transaction_isolation, "
                "@@session.innodb_lock_wait_timeout, @@character_set_connection"
            )
        ).one()
        assert tuple(row) == ("+00:00", "READ-COMMITTED", 3, "utf8mb4")
        assert inspect(connection).get_table_options(sample_table.name)["mysql_engine"] == "InnoDB"
    timestamp = datetime(2026, 10, 11, 1, 2, 3, 123456, tzinfo=timezone.utc)
    with database.transaction() as session:
        session.execute(sample_table.insert().values(id=1, value=10, at=timestamp))
    assert database.engine.pool.checkedout() == 0
    with pytest.raises(RuntimeError), database.transaction() as session:
        session.execute(sample_table.update().values(value=99))
        raise RuntimeError("模拟业务异常")
    assert database.engine.pool.checkedout() == 0
    with database.transaction() as session:
        row = session.execute(select(sample_table)).one()
        assert row.value == 10
        assert row.at == timestamp


@pytest.mark.parametrize("role,limit", [("api", 10), ("worker", 2)])
def test_pool_exhaustion_has_bounded_wait(mysql_settings, role, limit):
    db = Database(mysql_settings, role)
    try:
        with ExitStack() as stack:
            for _ in range(limit):
                stack.enter_context(db.engine.connect())
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                db.engine.connect()
            elapsed = time.monotonic() - started
            assert 0.15 <= elapsed < 2
        assert db.engine.pool.checkedout() == 0
        with db.engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        db.dispose()


def test_real_mysql_row_lock_waits_and_reads_committed_value(database, sample_table):
    waiting = Event()
    with database.transaction() as session:
        session.execute(sample_table.insert().values(id=1, value=10))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.transaction() as first:
            first.execute(select(sample_table).where(sample_table.c.id == 1).with_for_update())
            first.execute(sample_table.update().values(value=20))

            def competing_update():
                with database.transaction() as second:
                    # 先建立读取，再等待行锁，验证解锁后读到刚提交的新值。
                    assert second.scalar(select(sample_table.c.value)) == 10
                    waiting.set()
                    value = second.scalar(
                        select(sample_table.c.value).where(sample_table.c.id == 1).with_for_update()
                    )
                    second.execute(sample_table.update().values(value=value + 1))
                    return value

            future = executor.submit(competing_update)
            assert waiting.wait(timeout=3)
            time.sleep(0.2)
            assert not future.done()
        assert future.result(timeout=5) == 20
    with database.transaction() as session:
        assert session.scalar(select(sample_table.c.value)) == 21


def test_unreachable_mysql_still_has_live_endpoint():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="mysql+pymysql://u:p@127.0.0.1:1/missing",
        db_connect_timeout=1,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/ready").status_code == 503
        assert client.get("/api/v1/health/live").status_code == 200
