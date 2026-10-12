"""迁移配置只读取服务端环境，不在 ini 或日志内保存凭证。"""

from alembic import context

from score_api.auth import models  # noqa: F401 -- 注册本批模型供 Alembic 比较
from score_api.core.config import Settings
from score_api.db import VERSION_TABLE, Base, create_db_engine


def include_object(obj, name, type_, reflected, compare_to):
    # 共享数据库内的既有非项目表不参与自动生成的删除操作。
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations():
    if context.is_offline_mode():
        context.configure(
            dialect_name="mysql",
            version_table=VERSION_TABLE,
            target_metadata=Base.metadata,
            literal_binds=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_db_engine(Settings(), role="migration")
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                version_table=VERSION_TABLE,
                target_metadata=Base.metadata,
                include_object=include_object,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
