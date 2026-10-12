import os

import pytest
from sqlalchemy.engine import make_url

from score_api.config import Settings
from score_api.db import Database


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
