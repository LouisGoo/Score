"""运维通过终端建号；不提供公开注册或命令行明文密码参数。"""

import argparse
import getpass
import warnings
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from score_api.auth.models import Admin, AuthAudit
from score_api.core.config import Settings
from score_api.core.security import hash_password, normalize_login
from score_api.db import Database


def create_admin(database: Database, login: str, password: str) -> str:
    login = normalize_login(login)
    encoded = hash_password(password)
    admin_id = uuid4().hex
    with database.transaction() as session:
        session.add(Admin(id=admin_id, login=login, password_hash=encoded, enabled=True))
        session.flush()
        session.add(
            AuthAudit(
                id=uuid4().hex,
                admin_id=admin_id,
                action="admin_created",
                request_id=uuid4().hex,
            )
        )
    return admin_id


def main() -> int:
    parser = argparse.ArgumentParser(description="创建主办方账号（无公开注册入口）")
    parser.add_argument("login", help="3～64 位 ASCII 账号，不区分大小写")
    args = parser.parse_args()
    database = None
    try:
        login = normalize_login(args.login)
        # getpass 无可用终端时默认会降级为回显输入，显式拒绝该路径。
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("密码（12～128 字符）：")
            confirmed = getpass.getpass("再次输入密码：")
        if password != confirmed:
            print("两次密码不一致，未创建账号")
            return 1
        settings = Settings()
        database = Database(settings)
        if not database.is_ready():
            print("数据库迁移未就绪，请先执行 alembic upgrade head")
            return 1
        admin_id = create_admin(database, login, password)
        print(f"主办方账号已创建：{login}（{admin_id}）")
        return 0
    except IntegrityError:
        print("账号已存在，未修改原账号")
    except ValueError as error:
        print(str(error))
    except SQLAlchemyError:
        print("数据库操作失败，请检查连接和迁移；未输出连接凭证")
    except (EOFError, KeyboardInterrupt):
        print("已取消")
    except getpass.GetPassWarning:
        print("无法隐藏密码输入，请在交互式终端运行")
    finally:
        if database is not None:
            database.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
