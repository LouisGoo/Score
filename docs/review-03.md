# Review 03：MySQL 持久化基础

日期：2026-10-11。状态：代码、本地 MySQL 验证及远程基线迁移完成，未提交，等待 review。

建议 commit message：`feat(db): 建立 MySQL 持久化基础`。

## 交付范围

- [db.py](../backend/src/score_api/db.py)：SQLAlchemy 2、MySQL/PyMySQL、InnoDB 模型基类、UTC DATETIME(6)、显式事务边界及进程连接预算。
- [config.py](../backend/src/score_api/config.py)：服务端 DATABASE_URL（SecretStr）及有界等待配置。
- [migrations](../backend/src/score_api/migrations/) 与 [alembic.ini](../backend/alembic.ini)：基线 `0003_database_baseline`。只创建 Alembic 版本表，不提前建立业务表。
- [main.py](../backend/src/score_api/main.py)：进程生命周期内创建和释放数据库资源；新增 GET /api/v1/health/ready。
- [compose.yaml](../compose.yaml)：本地 MySQL 8.0.40、Redis 7.4.2；[初始化 SQL](../infra/mysql/init-test-db.sql) 提供独立测试库。
- [test_db.py](../backend/tests/test_db.py)、[test_mysql.py](../backend/tests/test_mysql.py)：配置、时间、就绪、真实数据库事务、池等待和行锁验证。
- CI 新增 MySQL 8.0.40 服务，更新依赖及锁文件、README、接口文档与提交计划。

worker 本批仅提供独立连接预算及构造入口；任务扫描和 outbox worker 分别在后续批次实现。Redis 本批只提供本地服务，不参与应用就绪判断。

## 数据库变更与远程验证

**已按用户明确授权向远程实例执行基线迁移，并将原有四张表改名归档；未删除或清空数据。当前项目使用 `score_alembic_version`。**

用户提供的连接信息已写入被 Git 忽略的 backend/.env，并设置文件权限 600；密码未写入源码、示例、锁文件或 review 文档。
此前远程连接经 TUN 路径时 TLS 握手超时；用户关闭 TUN 后，通过真实 IP 直连成功，客户端实际协商 TLS 1.3。当前驱动未校验证书，严格证书校验仍报自签名错误；证书信任配置留待部署验收。
实际服务端版本为 `8.0.41-SQLPub-0.0.1`。迁移前发现旧 `alembic_version` 包含其他项目版本 `20516c9690da`，因此将本项目迁移及就绪检查统一隔离到 `score_alembic_version`，保留旧历史。

远程执行 `alembic upgrade head`（通过 Alembic command API）成功，当前版本为 `0003_database_baseline`；`alembic current` 确认为 head，`alembic check` 无待生成操作。
迁移前后核对 `alembic_version`、`revoked_token`、`user`、`zz_user` 的 DDL 和精确行数均一致，旧版本记录未变。
通过 FastAPI TestClient 连接真实远程库验证：ready 返回 200 和 `{"status":"ok","database":"ready"}`，live 返回 200。本次未启动公网 API 服务。
本机迁移证据保存在被 Git 忽略的 `.tools/remote-migration-evidence.json`，包含前后表结构、行数和就绪结果，不包含密码或业务行内容。

基线迁移完成后，用户授权删除或加 old 标识归档原有四张表。本次选择保留数据，检查目标表名无冲突后，以单条 `RENAME TABLE` 执行：

| 原表名 | 归档表名 |
| --- | --- |
| alembic_version | alembic_version_old |
| revoked_token | revoked_token_old |
| user | user_old |
| zz_user | zz_user_old |

改名前后逐表精确行数一致，旧版本记录仍为 `20516c9690da`，项目版本仍为 `0003_database_baseline`，就绪接口仍返回 200。
这是本实例的旧表归档操作，不加入新环境通用迁移。核验记录保存在 `.tools/remote-old-tables-evidence.json`。

本地 MySQL 由 Ubuntu 包解压到仓库忽略目录 .tools，监听 127.0.0.1:13306，使用独立 score_test；测试完成后停止临时服务。
本地实测版本为 **8.0.46**，与用户提供的 **8.0.40** 存在补丁版本差异。Compose 和 CI 固定 8.0.40，但当前环境没有 Docker，未实际启动 Compose，也未触发远程 CI；不能将本地结果记为 8.0.40 验收。

## 验证证据

在 WSL、Python 3.10.12 下，使用全新虚拟环境按 requirements.lock 安装，并执行：

```bash
cd backend
../.tools/verify-venv/bin/python -m pip check
../.tools/verify-venv/bin/ruff check .
../.tools/verify-venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.tools/verify-venv/bin/pytest -q
../.tools/verify-venv/bin/alembic upgrade head --sql
cd ../frontend
npm run build
cd ..
git diff --check
```

结果：

- 全新锁文件安装及 pip check 通过。
- Ruff 检查及格式检查通过。
- **112 passed**，无数据库测试跳过；有一条 Starlette TestClient 对 httpx 的上游弃用提醒，不影响当前测试。
- 初次空库迁移、重复 upgrade、downgrade/upgrade、Alembic check、就绪状态切换通过。版本表隔离调整后重新运行全部 112 项测试，确认升级和降级不改动其他项目的迁移记录。
- 每条连接的 UTC、READ COMMITTED、utf8mb4、锁等待配置，以及表引擎 InnoDB 通过。
- DATETIME(6) 微秒往返、成功提交、异常回滚、连接归还通过。
- API 10 条/worker 2 条连接耗尽后有界等待，释放后恢复连接通过。
- 两个真实 InnoDB 事务竞争同一行，后者等待前者提交，并读取新提交值后更新通过；未使用 SQLite。
- MySQL 不可达时 ready=503、live=200；响应不回显内部异常。
- 前端 TypeScript 和 Vite 构建通过。
- 离线迁移 SQL 仅包含版本表及版本记录；Git 空白检查通过。

本地重跑推荐使用 README 中的 Compose 和独立 score_test；不要将测试库环境变量指向真实业务库。测试会升降级该库迁移并创建/删除本次 UUID 命名的测试表。

## Review 重点

1. 单 API 进程 5+5、单 worker 2+0 的预算；维护连接和多进程需要额外合计，迁移使用 NullPool。
2. API 启动不依赖即时连接成功、不自动迁移；同步探测在线程池运行，所有失败路径释放连接。
3. 事务只包围数据库操作，业务服务使用 `Database.transaction()`；正常提交、异常回滚。会话不得长期附着 WebSocket。
4. 写入时间必须带时区，数据库统一 UTC；前端显示时区处理留给后续业务。
5. 自动迁移忽略模型之外的既有表，保护共享库数据；有意删表必须写显式迁移。未来每批模型须在迁移环境导入后才能参与自动生成。
6. 就绪探测同时验证迁移版本，空库不能返回成功；503 含 Retry-After，客户端避免高频探测。
7. 远程迁移和就绪检查已通过；TLS 证书验证、同版本容器运行与真实实例性能仍未验收，不声称生产安全或容量达标。
