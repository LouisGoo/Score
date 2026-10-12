# Review：score_api 目录重构

在 `dev` 分支、认证代码 `f89b945` 基础上整理目录。本次变更保留未提交供 review，原有未提交文档继续保留，并同步更新路径和进度。

建议 commit message：`refactor(api): 按基础设施与认证职责整理目录`

## 文件入口与职责

| 位置 | 职责 |
| --- | --- |
| [main.py](../backend/src/score_api/main.py) | 应用工厂、生命周期、路由注册和健康检查 |
| [core/config.py](../backend/src/score_api/core/config.py) | 应用与数据库配置 |
| [core/errors.py](../backend/src/score_api/core/errors.py) | 请求 ID、来源校验和错误包装 |
| [core/security.py](../backend/src/score_api/core/security.py) | 密码哈希、账号规范化和令牌工具 |
| [auth/router.py](../backend/src/score_api/auth/router.py) | HTTP 输入输出、Cookie、调用认证服务 |
| [auth/schemas.py](../backend/src/score_api/auth/schemas.py) | 请求与响应模型 |
| [auth/dependencies.py](../backend/src/score_api/auth/dependencies.py) | 请求会话提取、CSRF 校验、require_admin |
| [auth/service.py](../backend/src/score_api/auth/service.py) | 身份查询、登录、退出、限流和认证审计事务 |
| [auth/models.py](../backend/src/score_api/auth/models.py) | 四张认证表的 ORM 模型 |
| [auth/cli.py](../backend/src/score_api/auth/cli.py) | 交互式管理员建号 |
| [db.py](../backend/src/score_api/db.py)、[scoring.py](../backend/src/score_api/scoring.py) | 保留独立连接/事务基础和评分纯函数 |
| [migrations/env.py](../backend/src/score_api/migrations/env.py) | 显式导入新位置的 ORM 模型；迁移历史保持原位 |

服务层接收数据库、配置、时钟及必要业务参数，不接收 HTTP Request/Response。HTTP 路由完成 Cookie 与 CSRF 处理后调用服务，服务提交成功才写响应。原有事务边界、密码计算时释放连接、来源→账号锁顺序、会话撤销与审计原子性保持。

所有源码和测试已改用新导入路径，原平铺模块已移除；没有保留旧模块兼容入口。应用启动入口 `score_api.main:create_app` 不变。建号命令改为从 `backend` 执行：

```bash
../.venv/bin/python -m score_api.auth.cli host.admin
```

后续业务按 `events/`、`rounds/` 等目录增加实际需要的 router/schemas/service/models，不预建空目录；新增模型须在 Alembic 环境显式注册。

## 验证证据

- Ruff 检查和格式检查通过。
- 本地 MySQL 8.0.46、独立 `score_test` 库完整回归：**151 passed**，无跳过。包含原有 149 项和新增两项匿名/非法 Cookie 请求在数据库查询前返回 401 的行为保护。
- 并发限流测试改为直接调用服务，仍验证六个不同来源竞争同账号时仅两次放行；登录/退出审计失败回滚、账号停用、过期、CSRF 等原有行为继续通过。
- 重构前后的 OpenAPI 完整字典一致，包括路径、operationId、请求/响应模型和错误结构。
- 重构前后的 `alembic upgrade head --sql` 输出完全一致；已有 MySQL 集成测试中的 upgrade/downgrade、Alembic check 及就绪检查通过。
- `python -m score_api.auth.cli --help` 正常；离线 wheel 构建通过，产物包含新 auth/core 包、迁移脚本和模板，不包含已移除的旧模块。
- Git 空白检查通过。保留已有 Starlette TestClient/httpx 弃用提醒。

主要复验命令：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
../.venv/bin/alembic upgrade head --sql
../.venv/bin/python -m score_api.auth.cli --help
```

数据库端口与账号按实际独立测试库调整。仍未执行 MySQL 8.0.40 容器或远程 CI；本次没有运行远程迁移、改变数据库结构或配置，也不需要用户再次升级数据库。前端与 HTTP 契约未变，本次未重复前端构建。
