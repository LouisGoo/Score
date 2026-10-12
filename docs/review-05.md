# Review 05：主办方活动草稿管理

日期：2026-10-12。基于 `dev` 分支 `be98feb` 开发，保留未提交变更供 review，未 push。

建议 commit message：`feat(events): 实现主办方活动草稿管理`

## 范围与入口

- [events/router.py](../backend/src/score_api/events/router.py)：15 个活动、对象和评委 CRUD 端点，复用主办方会话、Origin/CSRF 与统一错误；分页有界，显式响应模型。
- [events/schemas.py](../backend/src/score_api/events/schemas.py)：基本信息、过程/展示设置、草稿评分规则，PATCH 缺省/null 语义与只读字段保护。复用计分纯函数验证规则，数值输入限定长度和精度。
- [events/service.py](../backend/src/score_api/events/service.py)：owner 过滤、路径与子资源绑定、活动行锁、锁内草稿状态检查、业务与审计同事务。
- [events/models.py](../backend/src/score_api/events/models.py)、[0005_event_drafts.py](../backend/src/score_api/migrations/versions/0005_event_drafts.py)：四张 InnoDB 表，活动、对象、评委、活动审计；名单 `(event_id, number)` 唯一，编号采用 utf8mb4_bin，保留前导零并区分大小写。
- [test_events.py](../backend/tests/test_events.py)、[test_events_mysql.py](../backend/tests/test_events_mysql.py)：输入边界、OpenAPI/鉴权、真实 MySQL CRUD/隔离/约束/回滚/并发测试。
- [API 文档](api.md)、[README](../README.md)、[提交计划](commit-plan.md)：实现状态、调用示例、失败与重试规则、迁移说明。

## Review 重点

1. AT-23 的 HTTP 范围：活动查询和列表均按当前会话 owner 过滤。跨管理员访问统一 404；对象/评委必须同时匹配路径活动和内部 ID，覆盖同一管理员拥有多个活动时的混用。实时权限仍属 18。
2. 所有写入先锁活动，锁内确认 DRAFT；等待事务读取对方新提交的 READY 后拒绝修改。READY/RUNNING/FINISHED/ARCHIVED 的活动修改、删除、名单增删改都被拒绝。行锁不提供草稿编辑版本冲突检测，相同字段最终值取最后提交者，契约已文档化。
3. 对象和评委各自活动内编号唯一；`001`、`1`、`A`、`a` 保持区别。数据库约束兜底，并发重复写入只有一次成功，失败事务不留下审计。
4. 删除仅面向草稿，显式删除名单并保留活动审计，无级联删除。当前没有评分/任务表；后续迁移必须使用历史 RESTRICT 外键并补充有评分删除校验，不能将本批状态检查当作未来任意数据修复后的兜底。
5. 遵照计划“业务写入同时交付审计”，把 06 的活动审计基础提前至本批；06 复用扩展。记录白名单响应字段、操作者、目标、动作、request_id 与 UTC 时间，不记录 Cookie、CSRF 或凭证。审计失败时创建、修改、删除和名单写入均回滚。审计 event_id 不设活动外键，以便活动物理删除后继续保留；actor_id 仍有管理员外键。
6. 草稿可先无名单或无规则；已填写规则须满足维度、权重和步长约束，N/K 与完整名单在 07 发布时统一验证。计划时间输入须带时区，并统一到 UTC；身份码、发布、复制和前端界面均不在本批。
7. 所有成功响应在事务提交后返回。编号冲突 409、非草稿 409、不存在/无权 404，其他数据库错误沿用脱敏 503。无草稿 POST 幂等协议，超时先读取核验，不能自动重复创建。

## 验证

WSL Ubuntu、Python 3.10.12、本地 MySQL 8.0.46，使用仅监听 `127.0.0.1:13306` 的独立 `score_test`，未使用 SQLite。与 Compose/CI 固定的 8.0.40 有补丁版本差异；没有执行 Docker 或远程 CI。

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
../.venv/bin/alembic upgrade head --sql
cd ../frontend
npm run build
cd ..
git diff --check
```

- 完整后端 **193 passed**，本批新增 42 项，无数据库测试跳过；自查修正创建响应时区统一后，活动模块 **42 passed**。保留既有 Starlette/httpx 弃用提醒。
- Ruff、格式、前端 TypeScript/Vite 构建和 Git 空白检查通过。
- 真实 MySQL 空库升级、重复升级、降级再升级、Alembic check、ready 版本切换、共享库旧版本表保留均通过。已修复自动生成降级代码先删外键支撑索引的问题，改为直接随表删除。
- CRUD、分页、时区/可空清空、前导零、大小写及跨活动编号复用、重复创建/改号回滚通过。
- 全部 15 个接口未认证均拒绝；跨管理员所有资源读写拒绝，跨活动子资源 ID 拒绝，CSRF/Origin 检查通过。
- 四种非草稿状态下全部写操作拒绝；两线程重复编号仅一条成功，竞争活动行锁后重新检查状态通过。
- 审计写入故障回滚创建/修改/删除/名单写入；删除后保留审计与 request_id；直接数据库写入的唯一/外键约束通过。
- 离线 SQL 已生成检查，05 只新增四张表和自身索引/约束，不改动既有认证或旧业务表。

## 迁移边界

本批没有连接或升级远程业务库，也未修改 `.env`。远程保持此前 04，部署新代码后 ready 会因版本落后返回 503；使用活动接口前需在选定目标库显式运行 `alembic upgrade head`。05 降级删除本批表及其数据，只用于可丢弃测试库或已确认的数据回退。

本地测试实例验证完成后关闭。依赖和锁文件未改变。
