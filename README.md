# 在线打分系统

为固定评委的比赛、答辩和项目评审提供主持人控制台、手机评分与只读大屏。

目前交付 **12：可靠关闭到期评分任务**。支持活动发布、身份码、评委会话、任务控制、幂等提交及改分历史；已支持收评快照、重开补评、公布/无结果、排名、结束、归档和独立到期收评 worker。角色快照、管理前端和实时推送在后续批次。

- [需求与架构设计](./docs/在线打分系统-产品需求与架构设计.md)
- [接口文档与业务约定](./docs/api.md)
- [逐次 commit 计划](./docs/commit-plan.md)
- [认证功能 review](./docs/review-04.md)
- [活动草稿 review](./docs/review-05.md)
- [身份码 review](./docs/review-06.md)
- [发布与复制 review](./docs/review-07.md)
- [评委会话 review](./docs/review-08.md)
- [任务控制 review](./docs/review-09.md)
- [评分持久化 review](./docs/review-10.md)
- [收评与结果 review](./docs/review-11.md)
- [自动收评 worker review](./docs/review-12.md)
- [当前目录重构 review](./docs/review-auth-refactor.md)

## 环境与目录

推荐在 WSL/Linux 中开发：Python 3.10、Node.js 24、npm、Git。
Python 锁文件在 Python 3.10 下生成，CI 使用相同版本；升级 Python 时应重新解析依赖并 review。
数据库采用 MySQL 8.0 InnoDB；本地 Compose 固定为用户提供的 8.0.40。Redis 本批提供容器，应用通知功能在后续批次接入。

```text
backend/src/score_api/
├── main.py              应用工厂、生命周期、路由注册、健康检查
├── core/                跨业务的配置、错误处理、密码与令牌工具
│   ├── config.py
│   ├── errors.py
│   └── security.py
├── auth/                主办方认证
│   ├── router.py        HTTP 端点与 Cookie
│   ├── schemas.py       请求/响应模型
│   ├── dependencies.py  请求中的会话与 CSRF 校验
│   ├── service.py       会话、登录限流、事务与认证审计
│   ├── models.py        认证数据库模型
│   └── cli.py           管理员建号入口
├── events/              草稿 CRUD、owner 校验、规则配置及活动审计
│   ├── router.py
│   ├── schemas.py
│   ├── service.py
│   └── models.py
├── credentials/         自动/手动身份码、规范化、HMAC、重置与撤销
├── judge_sessions/      活动预览、身份确认、会话、限流和认证审计
├── rounds/              已发布任务、应交名单及开评/暂停/恢复/跳过
├── ballots/             评分提交、原始版本、永久回执、事务重试与审计
├── outbox/              内部事务事件模型（投递待 18）
├── db.py                连接池、事务、Base、UTC 类型
├── scoring.py           独立评分纯函数
└── migrations/          Alembic 环境及已有迁移历史
backend/tests/           后端测试
frontend/src/            React 页面
docs/                    开发与 review 文档
```

后续按业务新增其他模块目录，沿用 router/schemas/service/models 的职责划分；只在实际需要时创建文件。共用设施放 `core/`，各业务模型在 `migrations/env.py` 显式导入，确保 Alembic 能发现。路由负责 HTTP 输入输出，服务负责业务事务，不传入 Request/Response；暂不额外引入 repository 层。

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

当前远端已于 2026-10-13 升级至 **0011_results**，Alembic check 与 ready=200 核验通过，既有数据保留，凭证 HMAC 密钥已配置。下文较早批次的远端说明为历史记录；最新证据见 [Review 11](docs/review-11.md)。

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

迁移显式运行，不在 API 启动时自动执行。03 基线建立项目专用的 `score_alembic_version`；04 新增 `score_admins`、`score_admin_sessions`、`score_login_buckets` 和 `score_auth_audit`。迁移不清空既有表，其他项目的版本表不参与迁移；不能用 `stamp` 覆盖其他项目版本。当前远程实例的四张旧表已按用户授权加 `_old` 后缀归档，数据保留，详见 Review 03。04 已由用户执行远程升级，并只读核验版本为 `0004_admin_auth`、四张认证表齐全；随后进行的目录重构不增加迁移，无需再次升级数据库。
自动生成迁移会忽略模型之外的既有表，后续有意删表应编写并 review 明确的迁移。MySQL DDL 不保证整批事务回滚，生产变更前仍需备份。

05 新增 `0005_event_drafts`，创建 `score_events`、`score_entries`、`score_event_judges`、`score_event_audit`。本批仅在本地独立测试库验证，远程数据库未升级；运行活动接口前需对选定目标库显式执行 `alembic upgrade head`。未升级时 ready 将返回 503。活动接口及重试语义见 [API 文档](docs/api.md)。

每个 API 进程最多 10 条连接（5+5），worker 使用 `Database(settings, role="worker")`，最多 2 条（2+0）；迁移不保留连接池。
默认池等待 3 秒、连接超时 3 秒、读写超时 5 秒、连接回收 300 秒、InnoDB 锁等待 3 秒，均可通过示例环境变量调整。
每条物理连接使用 UTC、utf8mb4 和 READ COMMITTED。`UTCDateTime` 以 DATETIME(6) 存 UTC，读回带 UTC 时区的时间，拒绝无时区输入。
业务代码使用 `with database.transaction() as session:`，正常退出提交，异常回滚并归还连接；事务内不执行广播或其他外部网络调用。
扩进程、滚动发布、迁移及其他客户端连接需要合计，不能把每进程预算当作实例总预算。

## 主办方建号与认证

在 `backend` 目录，确认 `.env` 指向目标数据库，然后执行：

```bash
../.venv/bin/alembic upgrade head
../.venv/bin/python -m score_api.auth.cli host.admin
```

CLI 通过隐藏输入两次确认密码；密码为 12～128 个字符，不通过命令行参数传递。账号为 3～64 位 ASCII 字母、数字、点、下划线或连字符，首位为字母或数字，去除首尾空白并转为小写。重复账号被拒绝，不覆盖密码；无公开注册接口。

认证调用顺序：`GET /api/v1/auth/csrf` → 携带 Cookie、`Origin` 和 `X-CSRF-Token` 执行 `POST /api/v1/auth/login` → `GET /api/v1/auth/me` 恢复当前身份与会话 CSRF → 携带会话 CSRF 执行 `POST /api/v1/auth/logout`。详细请求示例与错误处理见 [接口文档](docs/api.md)。

默认会话绝对有效期 8 小时；退出在数据库撤销会话，旧 Cookie 无法继续使用。默认启用 Secure、HttpOnly、SameSite=Strict，使用 `__Host-` Cookie。本机 HTTP 开发按 `.env.example` 显式设置 `SCORE_COOKIE_SECURE=false`；生产保持 true。可信页面来源由 `SCORE_ALLOWED_ORIGINS` JSON 数组明确配置，默认只接受本机 5173；使用 15173 等端口时同步修改。通过 Vite 同源 `/api` 代理调用，未开放跨域 CORS。

登录按来源 IP（每 5 分钟 30 次）与规范化账号（每 5 分钟 10 次）共享限流，成功和失败都计数；MySQL 不可用时认证返回 503。服务只使用 ASGI 客户端地址：本机直连启动可加 `--no-proxy-headers`；部署代理时必须显式配置 Uvicorn 的可信代理 IP，禁止无条件信任公网 `X-Forwarded-For`。scrypt 每次约需 128 MiB，单进程最多同时计算两次，繁忙时返回 503。

## 验证

到期收评需在 `backend` 目录独立运行 `../.venv/bin/python -m score_api.worker`；仅运行 API 不会自动改变到期任务状态，但提交接口始终拒绝过期评分。`--once` 处理一批后退出，`--batch-size 50` 控制批量。启动前检查迁移版本，不自动迁移；连接预算 2，失败/空闲退避，支持正常停止及重启恢复。详见 [Review 12](docs/review-12.md)。

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

06 新增迁移 `0006_judge_credentials`，扩展评委凭证字段、完整性和唯一约束；运行凭证接口前需配置独立稳定的 `SCORE_CREDENTIAL_HMAC_KEY`，详见 [API 文档](docs/api.md) 与 [Review 06](docs/review-06.md)。本次只升级本地独立测试库。

07 新增迁移 `0007_event_publication`，扩展活动发布字段并建立发布快照、评分任务、应交评委表与复合外键。发布和复制均与审计同事务，见 [Review 07](docs/review-07.md)。仅对本地独立测试库执行迁移。

08 新增迁移 `0008_judge_sessions`，建立独立评委会话、一次性确认令牌和评委认证审计，生成列唯一约束保证每位评委至多一条未撤销会话。兑换流程为 `/judge-sessions/csrf` → `/verify` → 用户确认姓名编号 → `/exchange`；`/me` 恢复身份，`/logout` 撤销。重置需填写原因并同时撤销旧会话和旧确认令牌。详见 [API 文档](docs/api.md) 与 [Review 08](docs/review-08.md)。

06～08 均只在独立本地测试库迁移验收，未连接/升级远程业务库，未修改 `.env`。部署前显式迁移选定目标库到 head，并先配置稳定独立的 `SCORE_CREDENTIAL_HMAC_KEY`；各 API 进程共享同一密钥，密钥独立备份。现有前端仍为工程骨架，管理/评委页面在 14～16 批次交付。

09 新增迁移 `0009_round_controls`。2026-10-13 已按授权将远端从 05 补齐至 09，项目业务表迁移前均为空，旧表及记录数保留，Alembic check 与 ready=200 核验通过。此记录取代上文的历史远端版本说明。当前配置仍须在使用身份码前设置稳定的 `SCORE_CREDENTIAL_HMAC_KEY`。详见 [Review 09](docs/review-09.md)。

10 新增迁移 `0010_ballots`，建立逻辑评分单、原始评分历史、永久幂等回执、评委评分审计与 outbox 五张表。PUT/GET `/api/v1/rounds/{id}/my-ballot` 支持提交、改分和本人回执核验；任务锁内验证状态/截止，死锁及锁超时完整事务最多重试 3 次。事务成功后才返回回执，改分不增加已交人数。详见 [API 文档](docs/api.md) 与 [Review 10](docs/review-10.md)。

2026-10-13：10 已同步到远端 `0010_ballots`，本地完整后端 **287 passed**，前端构建通过。迁移仅增加项目结构，既有表及记录数保留；尚未配置的身份码 HMAC 密钥须在正式使用前补齐。
