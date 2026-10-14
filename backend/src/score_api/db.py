"""MySQL 连接与事务边界；每个进程独立创建并释放连接池。"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from score_api.core.config import Settings

MIGRATIONS = Path(__file__).with_name("migrations")
# 与共享数据库中其他应用的 Alembic 历史隔离。
VERSION_TABLE = "score_alembic_version"
# 配额按进程计算：一个 API 最多 10 条连接，一个 worker 最多 2 条连接。
POOL_BUDGETS = {"api": (5, 5), "worker": (2, 0)}


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class UTCDateTime(TypeDecorator):
    """MySQL 存 UTC 无时区值，Python 读写使用带时区时间，保留微秒。"""

    impl = DATETIME(fsp=6)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("数据库时间必须包含时区")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_db_engine(
    settings: Settings, role: Literal["api", "worker", "migration"] = "api"
) -> Engine:
    if settings.database_url is None:
        raise ValueError("请配置 DATABASE_URL")
    try:
        url = make_url(settings.database_url.get_secret_value())
        if url.drivername != "mysql+pymysql" or not url.database:
            raise ValueError
    except Exception:
        raise ValueError("DATABASE_URL 必须使用 mysql+pymysql 并指定数据库") from None
    if role not in {*POOL_BUDGETS, "migration"}:
        raise ValueError("未知数据库进程角色")
    pool_options = {"poolclass": NullPool}
    if role != "migration":
        size, overflow = POOL_BUDGETS[role]
        pool_options = {
            "pool_size": size,
            "max_overflow": overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
            "pool_pre_ping": True,
        }
    engine = create_engine(
        url,
        isolation_level="READ COMMITTED",
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": settings.db_connect_timeout,
            "read_timeout": settings.db_read_timeout,
            "write_timeout": settings.db_write_timeout,
        },
        hide_parameters=True,
        **pool_options,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _record):
        # 逐条物理连接初始化，避免依赖数据库实例的全局配置。
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION time_zone = '+00:00'")
            cursor.execute("SET SESSION default_storage_engine = InnoDB")
            cursor.execute(
                "SET SESSION innodb_lock_wait_timeout = %s", (settings.db_lock_wait_timeout,)
            )

    return engine


class Database:
    def __init__(self, settings: Settings, role: Literal["api", "worker"] = "api"):
        self.engine = create_db_engine(settings, role)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.snapshot_sessions = sessionmaker(
            self.engine.execution_options(isolation_level="REPEATABLE READ"),
            expire_on_commit=False,
        )
        self.expected_heads = set(ScriptDirectory(str(MIGRATIONS)).get_heads())

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """正常退出提交，异常回滚；两条路径均关闭会话并归还连接。"""
        with self.sessions.begin() as session:
            yield session

    @contextmanager
    def read_snapshot(self) -> Iterator[Session]:
        """只读一致性读：InnoDB 在首条查询建立读视图，后续查询共用，不加行锁也不等待写事务。

        仅用于不写入的读取；需要锁内校验的写路径仍使用 transaction()。
        """
        with self.snapshot_sessions.begin() as session:
            yield session

    def is_ready(self) -> bool:
        # 既检查连通性，也检查版本；空库或迁移落后不能宣称业务就绪。
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            heads = set(
                MigrationContext.configure(
                    connection, opts={"version_table": VERSION_TABLE}
                ).get_current_heads()
            )
            return heads == self.expected_heads

    def dispose(self) -> None:
        self.engine.dispose()
