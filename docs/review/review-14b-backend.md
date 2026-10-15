# Review 14b：后端缺口 G2 / G3

2026-10-14。按用户要求单独完成 14b 后端，保留未提交变更供用户 review。14b 登录、活动编辑等业务页面仍待实现。

## 范围与入口

- G2：`GET /api/v1/events` 返回 `EventListItem[]`，保留 `EventInfo` 原字段，增加对象、评委、任务及终态任务计数。单条 SQL、无行锁、按 owner 过滤后分页，各表独立计数避免重复。其他活动响应继续使用 `EventInfo`，避免写入审计时混入汇总字段。入口：[服务](../backend/src/score_api/events/service.py)、[模型](../backend/src/score_api/events/schemas.py)。
- G3：新增 `GET /api/v1/events/{id}/publish-check`，返回是否可发布、问题列表、名单数、待补码数和实际有效份数门槛。使用现有一致性读事务，不生成凭证、不改变状态或审计。入口：[发布服务](../backend/src/score_api/events/publication.py)、[响应模型](../backend/src/score_api/events/publication_schemas.py)、[路由](../backend/src/score_api/events/router.py)。
- 预检和发布准备前、发布锁内均复用 `inspect_publication`；`PUBLISH_INVALID` 的 422 响应增加 `error.issues`。评分核心异常补充稳定 code/field 元数据，保留 ValueError 兼容性和原有算法，不通过解析英文异常消息判断问题。入口：[评分核心](../backend/src/score_api/scoring.py)、[错误包装](../backend/src/score_api/core/errors.py)。
- 已重新生成前端 [OpenAPI](../frontend/src/api/openapi.json) 和 [TypeScript 类型](../frontend/src/api/schema.d.ts)，并同步 [接口文档](api.md)、[前端计划](frontend-plan.md)、[提交计划](commit-plan.md)。

## Review 重点

1. 任务完成仅统计 PUBLISHED、SKIPPED、NO_RESULT，CLOSED 不计完成。草稿和复制后任务数为 0；列表没有额外逐活动查询。
2. `minimum_ballots` 从现有评分核心解析，支持默认 80% 向上取整、去极值至少 5 人、显式 K 和 K≤N。没有有效规则/人数时为 null；仅缺对象时仍可显示有效 K。缺少身份码不是发布阻塞项，只返回补码数量。
3. 问题项包含 code/message/field，可同时报告缺对象、缺评委和规则问题；规则内部沿用既有验证顺序，不承诺一次穷举。草稿规则输入仍执行原有严格校验，预检也防御非法存储值，不回显值或异常正文。
4. 预检返回的是读取时的配置结论，不预留状态，也不检查运行时密钥/生成资源。非草稿 409、他人或不存在活动 404、未登录 401；发布仍在活动锁内重新验证。错误 code/message/request_id 保持兼容，非发布错误不附 issues。
5. 预检在 REPEATABLE READ 中读活动与名单；并发提交不会造成混合读视图，也不等待活动写锁。实际写事务锁顺序及审计回滚机制保持原有实现。

## 验证

新增 [预检单元测试](../backend/tests/test_publish_check.py) 与 [MySQL 集成测试](../backend/tests/test_event_management_mysql.py)，共 19 项，覆盖阈值边界、字段定位/脱敏、空名单、owner 隔离、分页、单查询计数、所有任务状态、复制、预检无写入、发布二次校验回滚、并发一致性读与锁。

WSL/Linux，在仓库目录执行：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
cd ../frontend
npm run gen:api
npm run lint
npm test
npm run build
```

本机仅使用独立本地 MySQL `score_test`；无新增迁移，未修改远端数据库或 `.env`。

- 定向后端测试：152 passed。
- 前端：50 passed；lint 0 warnings / 0 errors；类型检查与构建通过。
- Ruff check / format check、`git diff --check` 通过。
- 全量后端：333 passed（183.12 秒），含真实 MySQL 集成测试、迁移检查及 OpenAPI 契约检查，无跳过。

测试环境保留现有的 Starlette TestClient/httpx 弃用提示与前端 HydrateFallback 提示，本轮没有新增运行依赖。

## 前端接入与提交建议

列表使用生成类型 `EventListItem`；发布检查页读取 `PublishCheck`。14a `ApiError` 目前只保留顶层 code/message，页面可在发布 422 后重新 GET 预检展示最新问题；若要直接展示 POST 的问题列表，需在前端页面批次扩展解析 `error.issues`。本轮只更新生成契约，不开发业务页面。

建议 commit message：`feat(events): 补齐活动列表汇总与发布预检`
