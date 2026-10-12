# API 接口文档

更新时间：2026-10-12。当前交付批次：05（主办方活动草稿管理）。

## 1. 实现状态与文档分工

**当前已实现存活、数据库就绪、主办方认证及活动/名单草稿 CRUD；发布、身份码、评分及实时接口尚未实现。**
提交 02 已提供后端评分纯函数，尚未接入 HTTP；调用方式与边界见 [Review 02](review-02.md)。提交 03 新增只读就绪检查，见下文及 [Review 03](review-03.md)。
本文标为“规划中”的内容来自[需求设计稿](在线打分系统-产品需求与架构设计.md)，不能用于当前联调。

| 文档 | 用途 |
| --- | --- |
| 本文 | 接口实现状态、权限、业务限制、调用顺序和典型示例 |
| [Swagger UI](http://localhost:8000/docs) | 运行中应用的字段、类型、响应模型和在线调试 |
| [OpenAPI JSON](http://localhost:8000/openapi.json) | 由代码生成的 HTTP 接口结构，供客户端工具读取 |
| [逐次 commit 计划](commit-plan.md) | 各组接口的开发顺序和验收范围 |

上述链接按默认后端端口 8000 编写；修改启动端口后需相应替换。
Swagger UI 和 OpenAPI 当前由后端直接提供，不经过 Vite 的 /api 代理。
WebSocket 消息协议由本文维护，不假定 HTTP OpenAPI 会自动描述它。

## 2. 当前可用接口

### GET /api/v1/health/live

用途：检查 API 进程能否响应 HTTP 请求。

| 项目 | 当前行为 |
| --- | --- |
| 身份认证 | 无 |
| 路径/查询参数 | 无 |
| 请求体 | 无 |
| 成功状态 | 200 OK |
| 响应类型 | application/json |
| 响应字段 | status：字符串，固定为 ok |
| 外部依赖检查 | 不检查 MySQL 或 Redis |

请求：

```bash
curl -i http://localhost:8000/api/v1/health/live
```

响应体：

```json
{
  "status": "ok"
}
```

前端开发服务器启动后，也可以请求 http://localhost:5173/api/v1/health/live，验证 Vite 代理至后端的连通性。

成功仅表示进程存活，**不代表数据库就绪、允许评分或某份评分已经保存**。
响应头包含 `X-Request-ID`；统一错误包装见第 6 节，探测响应体保持兼容。

实现：[main.py](../backend/src/score_api/main.py)。
验证：[test_health.py](../backend/tests/test_health.py)。

### GET /api/v1/health/ready

用途：检查 MySQL 可连接且项目专用表 `score_alembic_version` 的当前版本与应用迁移 head 一致。无认证、无参数、只读，不自动执行迁移；共享库中其他项目的 `alembic_version` 不参与判断。

| 状态 | 响应体 | 条件 |
| --- | --- | --- |
| 200 | `{"status":"ok","database":"ready"}` | 数据库连通且迁移版本一致 |
| 503 | `{"status":"unavailable","database":"unavailable"}` | 未配置数据库、连接失败、池等待超时或迁移版本缺失/不符 |

始终返回 `Cache-Control: no-store`；503 附带 `Retry-After: 3`，调用方按至少 3 秒间隔退避探测。此接口不执行业务写入，无幂等键要求；不返回主机、账号、SQL 或数据库异常详情。
同步数据库操作在线程池执行；失败不影响存活检查。等待受池、连接和读写超时约束，并非统一的 3 秒总请求截止。
Redis 本批未接入应用，不参与就绪判断；Redis 通知与降级状态随后续批次实现。200 不保证评分功能已经实现或某笔业务已经提交。

```bash
curl -i http://localhost:8000/api/v1/health/ready
```

验证：[test_db.py](../backend/tests/test_db.py)、[test_mysql.py](../backend/tests/test_mysql.py)。探测 503 保留上述专用响应体，并带 `X-Request-ID`。

### 主办方认证（提交 04）

| 方法与路径 | 权限 | 成功结果 |
| --- | --- | --- |
| GET /api/v1/auth/csrf | 无需会话 | 200，返回登录用 csrf_token，并写入有效期 600 秒的 HttpOnly 双提交 Cookie |
| POST /api/v1/auth/login | 可信 Origin + 登录 CSRF | 200，返回 admin、expires_at、会话 csrf_token，并设置会话 Cookie |
| GET /api/v1/auth/me | 有效主办方会话 | 200，返回本人身份、原始过期时间和会话 csrf_token |
| POST /api/v1/auth/logout | 有效主办方会话 + 可信 Origin + 会话 CSRF | 204，无响应体；撤销会话并清除 Cookie |

登录请求体示例（仅测试用）：

```json
{"login":"host.admin","password":"example-password-only"}
```

账号通过服务端 `python -m score_api.auth.cli host.admin` 建立；无公开注册、重置密码或修改账号接口。账号去首尾空白后转小写，采用 3～64 位 ASCII 字母、数字、点、下划线或连字符，首位为字母或数字。CLI 新建密码为 12～128 字符，HTTP 登录允许 1～128 字符并统一校验失败。密码为 SecretStr，参数错误不回显输入。

浏览器通过同源 `/api` 访问（开发期使用 Vite 代理）：

```javascript
const prelogin = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin' }).then(r => r.json());
const response = await fetch('/api/v1/auth/login', {
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': prelogin.csrf_token },
  body: JSON.stringify({ login: 'host.admin', password: enteredPassword }),
});
// 先检查 response.ok；成功后保留响应中的会话 csrf_token，替换登录前令牌。
// Origin 由浏览器发送，值必须在 SCORE_ALLOWED_ORIGINS 中。
```

- 所有非 GET/HEAD/OPTIONS 请求校验单一、精确匹配的 `Origin`；无 Origin 的 curl/脚本也需显式提供。不依据 Host、Referer 或请求头自动扩展可信列表，未开放跨域 CORS。
- 登录前 CSRF 使用随机双提交令牌；登录后 CSRF 从随机会话令牌经独立用途摘要派生，与会话绑定。都通过 JSON 提供并在 `X-CSRF-Token` 回传，不从 URL 接收。退出后不能复用原会话，重新登录会轮换会话和 CSRF。
- 默认 Cookie 名为 `__Host-score_admin_session` / `__Host-score_admin_login_csrf`，`Secure; HttpOnly; SameSite=Strict; Path=/`，不设置 Domain。仅本机 HTTP 显式配置 `SCORE_COOKIE_SECURE=false` 时名称去除 `__Host-`。登录成功清除登录前 Cookie；`/auth/me` 用于刷新页面后的会话恢复。
- 会话绝对有效期默认 28800 秒，读取不续期；服务端检查 `expires_at > now`、撤销状态和账号启用状态。数据库仅存 256 位随机令牌的 SHA-256 摘要。主办方可使用多个浏览器；同一浏览器成功重登会撤销其携带的旧会话。评委单会话约束留待 08。
- 登录尝试按来源 IP 默认 30 次/300 秒、规范化账号 10 次/300 秒限制，成功和失败都消耗配额；来源超限时不建立新账号计数。使用 MySQL 锁和持久化计数，跨进程/重启共享；拒绝不会延长窗口，到期重置。每次登录最多清理 100 条过期计数，未自动删除审计或会话。
- 来源采用 ASGI 客户端地址，不在应用中读取 X-Forwarded-For。Uvicorn/反向代理必须限制可信转发来源。MySQL 故障时认证失败关闭；限流不依赖 Redis。密码 scrypt 参数为 N=131072、r=8、p=1，随机 16 字节盐；计算时释放数据库连接，单 API 进程最多并行两次。
- 建号、登录成功/失败、退出写入认证审计，只含动作、内部账号 ID（不存在时为空）、时间与 request_id，不记录密码、Cookie、CSRF、明文 IP 或尝试账号。会话写入/撤销与审计同事务。活动草稿审计在 05 实现，凭证审计在 06 扩展。

认证错误码和重试约定见第 6 节；精确字段以 OpenAPI 中 `LoginInput`、`SessionInfo`、`CSRFInfo`、`ErrorResponse` 为准。

代码入口：[认证路由](../backend/src/score_api/auth/router.py)、[认证服务](../backend/src/score_api/auth/service.py)、[授权依赖](../backend/src/score_api/auth/dependencies.py)、[请求/响应模型](../backend/src/score_api/auth/schemas.py)。目录重构未改变 HTTP 路径、字段、错误码或 Cookie 约定。

### 主办方活动草稿（提交 05）

以下路径均以 `/api/v1` 开头。所有接口需要有效主办方会话；写请求还需可信 Origin 和会话 CSRF。

| 方法与路径 | 成功结果 | 限制 |
| --- | --- | --- |
| POST /events | 201，EventInfo | 服务端指定 owner 和 DRAFT 状态 |
| GET /events | 200，EventInfo 数组 | 仅本人活动，按 created_at、id 倒序 |
| GET /events/{event_id} | 200，EventInfo | 仅拥有者 |
| PATCH /events/{event_id} | 200，EventInfo | 仅本人草稿；仅修改传入字段 |
| DELETE /events/{event_id} | 204 | 仅本人草稿；同事务删除名单，保留审计 |
| GET /events/{event_id}/entries | 200，EntryInfo 数组 | 按 sort_order、number、id 升序 |
| POST /events/{event_id}/entries | 201，EntryInfo | 仅本人草稿 |
| GET /events/{event_id}/entries/{entry_id} | 200，EntryInfo | 活动拥有者；记录必须属于路径活动 |
| PATCH /events/{event_id}/entries/{entry_id} | 200，EntryInfo | 仅本人草稿 |
| DELETE /events/{event_id}/entries/{entry_id} | 204 | 仅本人草稿 |
| GET /events/{event_id}/judges | 200，JudgeInfo 数组 | 按 number、id 升序 |
| POST /events/{event_id}/judges | 201，JudgeInfo | 仅本人草稿 |
| GET /events/{event_id}/judges/{judge_id} | 200，JudgeInfo | 活动拥有者；记录必须属于路径活动 |
| PATCH /events/{event_id}/judges/{judge_id} | 200，JudgeInfo | 仅本人草稿 |
| DELETE /events/{event_id}/judges/{judge_id} | 204 | 仅本人草稿 |

三个列表均支持 `offset=0`、`limit=100`，limit 为 1～100，offset 为 0～1000000。返回当前页数组；并发增删期间分页不保证快照一致性。

创建示例：`POST /api/v1/events`

```json
{
  "title": "项目评审",
  "organization": "研发部",
  "planned_at": "2026-10-12T14:00:00+08:00",
  "duration_seconds": 180,
  "scoring_rule": {
    "mode": "single",
    "criteria": [{"criterion_id": "total", "name": "综合评分", "maximum": "100", "weight": "1", "step": "0.1"}],
    "algorithm": "mean",
    "minimum_ballots": null
  }
}
```

新增对象：`POST /events/{event_id}/entries`，请求 `{"number":"001","name":"项目甲","description":"介绍","sort_order":0}`。新增评委：`POST /events/{event_id}/judges`，请求 `{"number":"001","name":"评委甲"}`。评委响应包含内部 ID、event_id、编号、姓名及凭证状态元数据；不含凭证秘密。

- 名称去首尾空白后为 1～80 字；编号为 1～32 字的字符串，保留前导零、区分大小写，不接受 JSON 数字。对象与评委分别在活动内唯一，两类可使用同一编号，不同活动可复用编号。
- 简介最多 2000 字，组织名称最多 120 字；计划时间需包含时区，读回 UTC。duration_seconds 为 1～86400 或 null（不限时）；allow_revisions 默认 true。大屏配置 screen_title 默认为空（最多 80 字），screen_theme 为 light/dark，show_public_qr 默认 true，leaderboard_limit 为 1～10000，默认 10。
- 草稿允许空名单、未设置评分规则。提供规则时须满足单项/多维模式、唯一维度 ID、满分/步长及权重合计 1，复用提交 02 的纯函数校验。维度数最多 20，数值必须是最多 9 位整数、6 位小数的非负十进制字符串，不接受浮点、指数、NaN/Infinity。最低有效份数 K 为 1～10000 或 null（发布时按 N 推导），去极值显式 K 不得低于 5；实际名单人数、K≤N 及发布完整性校验在 07。
- PATCH 至少传一个字段；planned_at、scoring_rule、duration_seconds 可用 null 清空，其余字段拒绝 null，简介等文本可用空字符串清空。scoring_rule 为整块替换；禁止传入 owner_id、status、id、event_id、凭证等未声明字段。
- 他人活动与不存在活动统一返回 404 `NOT_FOUND`。同一管理员把另一活动的子资源 ID 放入当前路径也返回 404。所有非草稿修改/删除均返回 409 `EVENT_NOT_DRAFT`；发布后的展示字段编辑留待后续批次。
- 同一活动写入先取得活动行锁，再检查状态和修改。编号由 MySQL 复合唯一约束保证，重复创建/改号返回 409 `NUMBER_CONFLICT`，失败不留部分修改或审计。删除活动显式删除草稿名单，不配置数据库级联；当前尚无任务/评分表，后续须保持历史外键 RESTRICT 与删除校验。
- 活动及名单增删改与 `score_event_audit` 同事务，记录 actor、action、target、前后字段、UTC 时间与 request_id，活动删除后仍保留。此审计基础因 05 写入要求提前实现，06 复用扩展；凭证等敏感数据不得加入快照。
- 草稿接口不接受幂等键或 expected_version。行锁防止状态竞争，但不检测两个编辑者覆盖同一字段，最后提交的对应字段生效。POST 超时后先查询列表核验，禁止盲目自动重建；PATCH/DELETE 超时后先 GET 核验，删除后 404 表示已不存在。409 需刷新或修改编号；503 按 Retry-After 等待并核验是否已保存。

字段以 OpenAPI 中 EventCreate/EventPatch/EventInfo、EntryCreate/EntryPatch/EntryInfo、JudgeCreate/JudgePatch/JudgeInfo 为准。入口：[events/router.py](../backend/src/score_api/events/router.py)，验证与迁移说明见 [Review 05](review-05.md)。

### 评委身份码（提交 06，已实现）

`PUT /api/v1/events/{event_id}/judges/{judge_id}/credential`：活动拥有者的草稿操作，需要主办方 Cookie、Origin、CSRF。请求 `{}` 或 `{"code":null}` 自动生成 12 位易读随机字母数字；`{"code":" abcd1234 "}` 手动设置。手动码去首尾空白后为 8～32 位 ASCII 字母数字，至少各含一种，统一大写；编号不作为身份码。成功 200 `CredentialResult` 仅在本次返回明文及元数据，禁止缓存。普通 JudgeInfo 仅新增 credential_is_set、credential_source、credential_version、credential_updated_at；无明文、哈希或 HMAC 查询接口。

服务端必须配置 `SCORE_CREDENTIAL_HMAC_KEY` 为随机 32 字节的 64 位十六进制文本，各进程使用同一密钥，独立于数据库保存和备份，不得随重启更换。可用 `python -c 'import secrets; print(secrets.token_hex(32))'` 在本机生成并写入受保护环境配置。未配置返回 503 `CREDENTIAL_KEY_UNAVAILABLE`，不使用默认密钥或降级为无密钥摘要。密钥丢失会影响已有码的查找；轮换流程留待运维批次，不可直接改密钥后继续兑换。

验证使用带随机盐的 scrypt，活动 ID 与规范化码的 HMAC-SHA-256 以二进制存储，并有 `(event_id, credential_lookup)` 唯一约束。慢哈希计算释放数据库连接；写入先锁活动，锁内重查草稿及重复码，与审计同事务。不同活动允许使用相同码。审计只记录凭证版本、来源、更新时间，日志与校验错误不回显码或摘要。

错误：格式不合规 422 `VALIDATION_ERROR`，重复码 409 `CREDENTIAL_CONFLICT`，非草稿 409 `EVENT_NOT_DRAFT`，无权或路径绑定错误 404；生成碰撞最多重试 5 次，耗尽 503 `CREDENTIAL_GENERATION_BUSY`（Retry-After: 1），高成本哈希繁忙 503 `AUTH_BUSY`。本操作无幂等 key，超时先查询元数据确认版本；若明文丢失只能重新设置，不可自动重复生成。发布后重置由 08 提供。

## 3. 通用业务约定（认证与草稿已实现，其余规划中）

主办方认证、请求来源校验、草稿权限/编号及通用错误已实现；其余业务约定将在相应功能提交中实现并验证。

| 项目 | 约定 |
| --- | --- |
| HTTP 前缀 | /api/v1；下文接口清单中的 HTTP 路径均相对于此前缀 |
| 数据格式 | 普通业务请求/响应使用 JSON；CSV 导出和 WebSocket 分别约定 |
| ID | 客户端视为不透明字符串，不能根据格式推断权限 |
| 编号 | 对象编号、评委编号使用字符串，保留前导零 |
| 分数 | 请求分数与响应成绩使用十进制字符串；服务端 Decimal 计算 |
| 时间 | 对外使用带 UTC 时区的 ISO 8601 时间；截止以服务端锁内校验时间为准 |
| 管理认证 | 管理员服务端会话，通过 Secure、HttpOnly Cookie 传递 |
| 评委认证 | 活动内身份码兑换独立评委会话；客户端不能指定他人评委身份 |
| 写请求保护 | Cookie 写请求校验 Origin 和 CSRF；WebSocket 校验 Origin |
| 大屏授权 | 独立、可撤销、只读；仅允许展示公开数据 |
| 乐观并发 | 控制操作携带 expected_version；改分携带 expected_ballot_revision |
| 评分幂等 | 每次确认操作生成 UUID 作为 Idempotency-Key，重试复用原 key |
| 权限隔离 | 每个接口校验身份及活动归属，不依赖前端隐藏按钮 |

主办方 Cookie、有效期、CSRF 与错误包装见第 2、6 节；评委会话和分页结构随相关提交补齐。
活动码仅用于定位活动，不能直接获得评分权限。身份码、会话凭证不进入普通查询响应、日志和公共二维码。

## 4. 后续接口清单（规划中）

本表用于定位功能范围。暂不提前复制尚未实现的字段模型；正式实现后更新状态，并链接对应 OpenAPI operation 和本文业务说明。
名单子资源 CRUD 已在第 2 节明确；授权撤销路径在对应提交中明确。

| 提交 | 方法与路径（省略 /api/v1） | 用途及权限 |
| --- | --- | --- |
| 07 | POST /events/{id}/publish、POST /events/{id}/copy | 发布/复制；活动拥有者 |
| 08 | GET /join/{code} | 公开活动预览；公共 |
| 08 | POST /judge-sessions/exchange | 身份码兑换评委会话 |
| 08 | POST /events/{id}/judges/{judge_id}/reset-credential | 重置并撤销旧会话；活动拥有者 |
| 09 | POST /rounds/{id}/open、POST /rounds/{id}/pause、POST /rounds/{id}/resume、POST /rounds/{id}/skip | 任务控制；活动拥有者 |
| 10 | PUT /rounds/{id}/my-ballot、GET /rounds/{id}/my-ballot | 提交/改分、查询本人有效评分及回执；对应评委 |
| 11 | POST /rounds/{id}/close、POST /rounds/{id}/reopen | 收评、重开补评；活动拥有者 |
| 11 | POST /rounds/{id}/publish-result、POST /rounds/{id}/no-result | 公布、标记无结果；活动拥有者 |
| 11 | POST /events/{id}/finish、POST /events/{id}/archive | 结束、归档；活动拥有者 |
| 11、13 | GET /events/{id}/results | 结果查询；按角色裁剪，非管理员只见已公布成绩 |
| 13 | POST /events/{id}/screen-grants | 创建大屏只读授权；活动拥有者 |
| 13 | GET /events/{id}/snapshot | 角色专属状态快照；有效授权 |
| 18 | POST /realtime/tickets | 兑换短时一次性连接票据；有效会话/展示授权，细节随实现明确 |
| 18 | WS /api/v1/events/{id}/stream（完整路径） | 授权实时订阅；一次性票据 |
| 20 | GET /events/{id}/exports/{kind} | 汇总/明细/审计 CSV；活动拥有者 |

## 5. 关键业务流程（规划中）

### 5.1 主持人流程与状态限制

登录 → 创建草稿 → 配置名单/规则/身份码 → 发布 → 开评 → 收评 → 核对并公布 → 结束 → 导出/归档。

- 发布时冻结名单和规则；副本回到草稿，不携带原活动凭证、会话或成绩。
- 同场最多一个 OPEN 或 PAUSED 任务，后台并发操作也必须满足此限制。
- 暂停冻结剩余时长并禁止提交；恢复重新计算截止时间。
- 提前收评未收齐时填写原因；收评不等于公布，未达到最低有效份数 K 时不能公布。
- 仅尚未公布的 CLOSED 任务可以重开补评，需填写原因；保留已有评分。
- PUBLISHED、SKIPPED、NO_RESULT 为任务终态。全部任务进入终态后才能结束活动。

### 5.2 评委加入与凭证重置

公开活动预览 → 输入个人身份码 → 验证并确认身份 → 建立评委会话 → 读取快照 → 等待/评分。

身份码去除前后空白并统一大写；手动码为 8～32 位 ASCII 字母数字，至少各含一个字母和数字。
同活动身份码唯一，每位评委默认仅一个有效会话。
发布后至活动结束前由管理员填写原因重置凭证，原子撤销旧会话；评委 ID 和历史评分归属不变。
活动结束后停止新会话兑换，已有未过期会话只读。身份确认的具体请求步骤以实现后的接口模型为准。

### 5.3 提交、改分与超时核验

以下为需求稿中的示例，接口尚不可调用；ID 为占位值。

`PUT /api/v1/rounds/{id}/my-ballot`

请求头携带 `Content-Type: application/json` 和 `Idempotency-Key: <本次确认操作的 UUID>`，同时遵守会话及 CSRF 约定。

```json
{
  "rule_version": 1,
  "expected_ballot_revision": 0,
  "scores": [
    { "criterion_id": "content", "value": "90.0" },
    { "criterion_id": "performance", "value": "8.0" },
    { "criterion_id": "innovation", "value": "18.0" }
  ]
}
```

在满分分别为 100、10、20，权重分别为 50%、30%、20% 的规则下，个人总分为 87.00。
预期回执内容示例（成功 HTTP 状态码随实现明确）：

```json
{
  "ballot_id": "ballot_example",
  "receipt_id": "receipt_example",
  "revision": 1,
  "total_score": "87.00",
  "accepted_at": "2026-10-10T06:03:21.123Z",
  "round_id": "round_example"
}
```

- 首次提交 expected_ballot_revision=0；改分使用已有 revision 和新的幂等 key，保留旧版本，人数不增加。
- 所有维度一次提交；零分有效，空值不等于零分。后端验证完整性、范围、步长和规则版本。
- 请求必须指向明确任务。新提交/改分仅在 OPEN 且锁内校验时 server_now < deadline_at 时接受；不限时不校验截止时间。
- 在身份仍有效的前提下，已完成的同 key 同内容请求返回原回执，即使任务已经截止；同 key 不同内容冲突。
- 未收到回执不能显示成功。超时后复用原 key 重试，或查询本人有效评分/回执核对内容及版本，不能盲目创建新提交。
- 断线恢复后先同步状态，由评委确认提交；不自动补交过期草稿。
- 收评与提交通过同一任务锁串行处理，回执仅在数据库事务提交成功后返回。

## 6. 错误响应与业务错误码

当前通用错误统一为 `{"error":{"code":"...","message":"..."},"request_id":"32位十六进制标识"}`，与响应头 `X-Request-ID` 一致。所有 HTTP 响应都有服务端生成的请求 ID，不采用客户端传入的值；API 响应设 `Cache-Control: no-store`。422 不回显请求体或校验 input，500/503 不返回内部异常、SQL 或凭证。存活/就绪接口保留原有探测响应体，就绪 503 仍是 `Readiness` 模型。

| HTTP | 已实现错误码 | 含义与处理 |
| --- | --- | --- |
| 401 | INVALID_CREDENTIALS | 账号不存在、密码错误或账号停用；统一提示，人工修正 |
| 401 | SESSION_EXPIRED | 会话缺失、非法、撤销、过期或账号停用；重新登录 |
| 403 | ORIGIN_FORBIDDEN | 非可信、缺失、null 或重复 Origin；修正来源配置，不自动重试 |
| 403 | CSRF_INVALID | 缺失或错误 CSRF；登录前重新取 `/auth/csrf`，登录后取 `/auth/me` |
| 404 | NOT_FOUND | 活动/名单不存在或不属于当前主办方/路径活动；不自动重试 |
| 409 | EVENT_NOT_DRAFT | 活动已不处于草稿；刷新状态 |
| 409 | NUMBER_CONFLICT | 当前活动同类名单中编号重复；修改编号 |
| 422 | VALIDATION_ERROR | 请求结构、账号格式或字段长度错误；修正参数 |
| 429 | RATE_LIMITED | 登录限流；按 `Retry-After` 秒数等待后由用户重试 |
| 503 | AUTH_BUSY | 密码计算并发已满；`Retry-After: 1` |
| 503 | SERVICE_UNAVAILABLE | 数据库未配置、不可用、事务失败或池等待超时；`Retry-After: 3` |
| 404 / 405 | NOT_FOUND / METHOD_NOT_ALLOWED | 路径不存在或方法错误，405 保留 Allow |
| 500 | INTERNAL_ERROR | 未预期异常；使用 request_id 排查，不回显内部细节 |

登录/退出无幂等 key。登录响应丢失时先用 `/auth/me` 检查浏览器会话，必要时重新登录；不自动反复提交密码。退出响应丢失后查询 `/auth/me`，401 表示会话已失效；已失效会话再次退出返回 401。认证写入与其审计同事务，提交后才返回成功与设置/删除 Cookie。

以下业务错误码仍为后续提交规划：

| 错误码 | 含义 | 客户端处理方向 |
| --- | --- | --- |
| SESSION_EXPIRED | 会话失效 | 引导重新验证身份，不把待核验评分当作失败重交 |
| FORBIDDEN | 身份无操作/活动权限 | 停止操作，提示权限问题 |
| ROUND_NOT_OPEN | 任务不允许评分 | 刷新状态，保留对应任务草稿 |
| DEADLINE_EXCEEDED | 已到截止时间 | 停止新提交，核验已有回执 |
| RULE_VERSION_MISMATCH | 客户端规则版本不一致 | 重新获取规则，要求重新确认评分 |
| SCORE_INVALID | 维度、范围或步长不合规 | 就地提示并修正 |
| REVISION_CONFLICT | 评分版本已变化 | 读取本人最新评分，重新确认修改 |
| INSUFFICIENT_BALLOTS | 未达最低有效份数 | 主持人选择补评或无结果 |
| IDEMPOTENCY_CONFLICT | 相同 key 对应不同内容 | 停止自动重试，核验原操作 |

以上并非完整业务错误目录。控制操作版本冲突等错误将在对应业务实现时明确，不能推断复用上述某个码。

## 7. 实时订阅与恢复（规划中）

1. 获取短时一次性票据，建立授权 WebSocket 连接并缓冲消息。
2. 获取当前角色快照，丢弃不高于快照版本的缓冲事件，再顺序应用后续事件。
3. 忽略旧版本；版本跳号、重连或页面回到前台时拉取快照。
4. 每 30 秒轻量核对版本；持续连接失败时降级为带抖动的 5 秒轮询，并按负载退避。

消息字段规划为 event_id、message_id、type、scope、version、server_time、payload。
事件类型包括 round.opened/paused/resumed/closed、progress.updated、result.published、screen.changed、session.revoked、event.finished。

管理员流、大屏流、每位评委个人流分别递增版本；各角色独立序列化。
大屏和评委不能收到其他评委原始分或未公布汇总分。
Redis 只负责通知，数据库为权威来源；重复投递、断线恢复不能重复计分。
具体票据交换字段、连接传参方式和消息 schema 随提交 18 补齐。

## 8. 随代码维护

每个新增或修改接口的 commit 必须同时：

- 更新本文中的实现状态、业务限制及示例，将已完成接口移入“当前可用接口”。
- 用代码声明请求/响应模型，使运行时 OpenAPI 与实现一致，不手工维护第二套完整字段表。
- 明确权限、成功/失败状态、错误码及重试语义；涉及状态变更时补并发和截止规则。
- 验证文档示例与真实响应一致，在对应 review 说明记录证据。
- 尚未确定的契约继续标为规划中，不将设计示例包装成已经可用的 API。

未来接口数量增多后，可按 auth/events/rounds/realtime 拆分至 docs/api/，本文保留总索引。
