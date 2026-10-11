# 在线打分系统

为固定评委的比赛、答辩和项目评审提供主持人控制台、手机评分与只读大屏。

目前交付 **03：MySQL 持久化基础**。已有评分纯函数、SQLAlchemy 事务与连接池、Alembic 迁移和存活/就绪检查；登录、评分 HTTP 流程与大屏业务尚未实现。

- [需求与架构设计](./docs/在线打分系统-产品需求与架构设计.md)
- [接口文档与业务约定](./docs/api.md)
- [逐次 commit 计划](./docs/commit-plan.md)
- [当前 review 说明](./docs/review-03.md)

## 环境与目录

推荐在 WSL/Linux 中开发：Python 3.10、Node.js 24、npm、Git。
Python 锁文件在 Python 3.10 下生成，CI 使用相同版本；升级 Python 时应重新解析依赖并 review。
数据库采用 MySQL 8.0 InnoDB；本地 Compose 固定为用户提供的 8.0.40。Redis 本批提供容器，应用通知功能在后续批次接入。

```text
backend/src/score_api/   FastAPI 应用
                        scoring.py 为独立评分核心
backend/tests/          后端测试
frontend/src/           React 页面
docs/                   开发与 review 文档
```

## 本地启动

以下命令均在 WSL/Linux bash 执行。首次安装：

```bash
python3 -m venv .venv
cd backend
../.venv/bin/python -m pip install -r requirements.lock
../.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
cd ../frontend
npm ci
```

如果 Ubuntu 提示缺少 ensurepip，先安装匹配 Python 版本的 venv 系统包。
本次工作目录已准备好项目虚拟环境，无需重复创建；不依赖全局 Python 包。

终端一（从仓库根目录）：

```bash
cd backend
../.venv/bin/uvicorn score_api.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

终端二（从仓库根目录）：

```bash
cd frontend
npm run dev
```

打开 http://localhost:5173 。Vite 将 /api 转发至 127.0.0.1:8000，页面会显示连接状态。
如果端口被占用，可将后端启动参数改为 `--port 18000`，并用 `SCORE_API_PROXY=http://127.0.0.1:18000 npm run dev -- --port 15173` 启动前端，然后访问 http://localhost:15173 。

API 文档：http://localhost:8000/docs 。本地服务默认仅监听本机，手机访问将在部署批次配置。

`GET /api/v1/health/live` 返回 `{"status":"ok"}`，仅代表 API 进程存活，不能作为数据库就绪或评分可用的证明。
`GET /api/v1/health/ready` 检查 MySQL 和迁移版本，成功返回 200；未配置、不可达、连接池耗尽或版本不符返回 503。它不代表某份评分已经保存。

## 数据库与迁移

本地开发可在仓库根目录执行：

```bash
docker compose up -d --wait
cd backend
# 在 .env 中使用 .env.example 的本地连接地址；已有远程配置时不要直接覆盖。
../.venv/bin/alembic upgrade head
../.venv/bin/alembic current
```

Compose 仅绑定本机 3306/6379，示例密码仅供本地使用。首次初始化时创建 `score` 应用库和 `score_test` 测试库；MySQL 数据保存在命名卷，`docker compose down` 保留数据。
远程实例通过服务端 `backend/.env` 的 `DATABASE_URL` 配置，格式为 `mysql+pymysql://用户:URL编码后的密码@主机:端口/数据库`。
凭证不进入源码；生产 TLS 应按提供方的 CA 配置 `ssl_ca`、`ssl_verify_cert=true`、`ssl_verify_identity=true` URL 参数并实际验证，不将驱动默认协商等同于证书验证。

迁移显式运行，不在 API 启动时自动执行。本批基线只建立项目专用的 `score_alembic_version`，不创建未来业务表，也不清空已有表；其他项目的版本表不参与迁移。迁移与就绪检查均使用项目专用表，不能用 `stamp` 覆盖其他项目版本。当前远程实例的四张旧表已按用户授权加 `_old` 后缀归档，数据保留，详见 Review 03。
自动生成迁移会忽略模型之外的既有表，后续有意删表应编写并 review 明确的迁移。MySQL DDL 不保证整批事务回滚，生产变更前仍需备份。

每个 API 进程最多 10 条连接（5+5），worker 使用 `Database(settings, role="worker")`，最多 2 条（2+0）；迁移不保留连接池。
默认池等待 3 秒、连接超时 3 秒、读写超时 5 秒、连接回收 300 秒、InnoDB 锁等待 3 秒，均可通过示例环境变量调整。
每条物理连接使用 UTC、utf8mb4 和 READ COMMITTED。`UTCDateTime` 以 DATETIME(6) 存 UTC，读回带 UTC 时区的时间，拒绝无时区输入。
业务代码使用 `with database.transaction() as session:`，正常退出提交，异常回滚并归还连接；事务内不执行广播或其他外部网络调用。
扩进程、滚动发布、迁移及其他客户端连接需要合计，不能把每进程预算当作实例总预算。

## 验证

从仓库根目录：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/pytest -q
# 完整数据库验收需独立 MySQL 测试库；默认不连接远程业务库。
SCORE_TEST_DATABASE_URL=mysql+pymysql://score:local-score-only@127.0.0.1:3306/score_test ../.venv/bin/pytest -q
cd ../frontend
npm run build
```

CI 使用 MySQL 8.0.40 服务执行完整后端检查。构建已含 TypeScript 检查。
未设置 `SCORE_TEST_DATABASE_URL` 时跳过数据库集成测试；指定库名必须以 `_test` 结尾。测试会升降级迁移并创建/删除临时测试表，不可指向正式库。锁测试使用真实 InnoDB，不使用 SQLite 替代。
前端使用 package-lock.json 和 npm ci；后端使用 requirements.lock 固定依赖。
新增后端依赖时更新 pyproject.toml，在干净环境重新生成锁文件；保留与项目 editable 安装隔离的固定依赖列表。

## 评分核心

`score_api.scoring` 提供 `Criterion`、`ScoringRule`、`personal_total`、`aggregate` 和 `rank_results`。
分数、满分、步长及权重传入十进制字符串或 `Decimal`，权重按 0～1 配置且合计为 1；拒绝 float、空值及 NaN/Infinity。
汇总从原始维度分重新计算，保留各评委原始分和去极值标记；未达到 K 份时 `final_score=None`。
最终成绩按 `ROUND_HALF_UP` 保留两位小数，已公布成绩按 1、2、2、4 并列排名。
本模块无需数据库或 HTTP 服务；完整调用示例、数值约定与验收证据见 [Review 02](./docs/review-02.md)。

真实数据库密码、会话密钥和个人身份码不得写入前端、源码或日志。
.env 已被 Git 忽略，.env.example 只放示例配置。
生产部署、数据库连接预算与权限按需求稿及后续提交逐步落地。

参考：[Vite 官方指南](https://vite.dev/guide/)、[FastAPI 官方入门](https://fastapi.tiangolo.com/tutorial/first-steps/)。
