# API 接口文档

更新时间：2026-10-14。当前新增：14b 后端缺口（活动列表汇总、发布预检），待用户 review。

## 1. 实现状态与文档分工

**当前已实现存活/就绪、主办方认证、活动/名单草稿 CRUD、身份码管理、原子发布/复制、公开预览、评委会话及凭证重置撤销。评分任务控制、幂等写分、回执与改分历史、手动/自动收评、重开、成绩公布、排名、结束和归档已实现。管理/评委/大屏快照、大屏授权与展示设置已实现；实时接口尚未实现。**
提交 02 的后端评分纯函数已由 10 接入写分校验；调用方式与边界见 [Review 02](review-02.md)。提交 03 新增只读就绪检查，见下文及 [Review 03](review-03.md)。
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
- 会话绝对有效期默认 28800 秒，读取不续期；服务端检查 `expires_at > now`、撤销状态和账号启用状态。数据库仅存 256 位随机令牌的 SHA-256 摘要。主办方可使用多个浏览器；同一浏览器成功重登会撤销其携带的旧会话。评委单会话约束由 08 的独立会话表实现。
- 登录尝试按来源 IP 默认 30 次/300 秒、规范化账号 10 次/300 秒限制，成功和失败都消耗配额；来源超限时不建立新账号计数。使用 MySQL 锁和持久化计数，跨进程/重启共享；拒绝不会延长窗口，到期重置。每次登录最多清理 100 条过期计数，未自动删除审计或会话。
- 来源采用 ASGI 客户端地址，不在应用中读取 X-Forwarded-For。Uvicorn/反向代理必须限制可信转发来源。MySQL 故障时认证失败关闭；限流不依赖 Redis。密码 scrypt 参数为 N=131072、r=8、p=1，随机 16 字节盐；计算时释放数据库连接，单 API 进程最多并行两次。
- 建号、登录成功/失败、退出写入认证审计，只含动作、内部账号 ID（不存在时为空）、时间与 request_id，不记录密码、Cookie、CSRF、明文 IP 或尝试账号。会话写入/撤销与审计同事务。活动草稿审计在 05 实现，凭证审计在 06/08 扩展。

认证错误码和重试约定见第 6 节；精确字段以 OpenAPI 中 `LoginInput`、`SessionInfo`、`CSRFInfo`、`ErrorResponse` 为准。

代码入口：[认证路由](../backend/src/score_api/auth/router.py)、[认证服务](../backend/src/score_api/auth/service.py)、[授权依赖](../backend/src/score_api/auth/dependencies.py)、[请求/响应模型](../backend/src/score_api/auth/schemas.py)。目录重构未改变 HTTP 路径、字段、错误码或 Cookie 约定。

### 主办方活动草稿（提交 05）

以下路径均以 `/api/v1` 开头。所有接口需要有效主办方会话；写请求还需可信 Origin 和会话 CSRF。

| 方法与路径 | 成功结果 | 限制 |
| --- | --- | --- |
| POST /events | 201，EventInfo | 服务端指定 owner 和 DRAFT 状态 |
| GET /events | 200，EventListItem 数组 | 仅本人活动，按 created_at、id 倒序；含名单与任务计数 |
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

14b 后端新增 `EventListItem`，保留全部 `EventInfo` 字段，并增加 `entry_count`（对象数）、`judge_count`（评委数）、`round_count`（任务总数）、`finished_round_count`（终态任务数）。终态仅包含 PUBLISHED、SKIPPED、NO_RESULT；CLOSED 仍待公布/补评/无结果处理，不计完成。草稿和复制出的草稿任务数均为 0；空名单计数为 0。列表业务读取只执行一条 SQL，以各表独立计数避免联表重复计数，活动与计数来自同一语句的读视图；不持活动行锁。单活动详情、创建、修改、复制及发布响应仍使用 `EventInfo`，不附加汇总字段。

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
- 同一活动写入先取得活动行锁，再检查状态和修改。编号由 MySQL 复合唯一约束保证，重复创建/改号返回 409 `NUMBER_CONFLICT`，失败不留部分修改或审计。删除活动显式删除草稿名单，不配置数据库级联；07 已为任务及应交名单增加 RESTRICT 外键，保留历史；后续评分表同样须保持历史外键和删除校验。
- 活动及名单增删改与 `score_event_audit` 同事务，记录 actor、action、target、前后字段、UTC 时间与 request_id，活动删除后仍保留。此审计基础因 05 写入要求提前实现，06 复用扩展；凭证等敏感数据不得加入快照。
- 草稿接口不接受幂等键或 expected_version。行锁防止状态竞争，但不检测两个编辑者覆盖同一字段，最后提交的对应字段生效。POST 超时后先查询列表核验，禁止盲目自动重建；PATCH/DELETE 超时后先 GET 核验，删除后 404 表示已不存在。409 需刷新或修改编号；503 按 Retry-After 等待并核验是否已保存。

字段以 OpenAPI 中 EventCreate/EventPatch/EventInfo、EntryCreate/EntryPatch/EntryInfo、JudgeCreate/JudgePatch/JudgeInfo 为准。入口：[events/router.py](../backend/src/score_api/events/router.py)，验证与迁移说明见 [Review 05](review-05.md)。

### 评委身份码（提交 06，已实现）

`PUT /api/v1/events/{event_id}/judges/{judge_id}/credential`：活动拥有者的草稿操作，需要主办方 Cookie、Origin、CSRF。请求 `{}` 或 `{"code":null}` 自动生成 12 位易读随机字母数字；`{"code":" abcd1234 "}` 手动设置。手动码去首尾空白后为 8～32 位 ASCII 字母数字，至少各含一种，统一大写；编号不作为身份码。成功 200 `CredentialResult` 仅在本次返回明文及元数据，禁止缓存。普通 JudgeInfo 仅新增 credential_is_set、credential_source、credential_version、credential_updated_at；无明文、哈希或 HMAC 查询接口。

服务端必须配置 `SCORE_CREDENTIAL_HMAC_KEY` 为随机 32 字节的 64 位十六进制文本，各进程使用同一密钥，独立于数据库保存和备份，不得随重启更换。可用 `python -c 'import secrets; print(secrets.token_hex(32))'` 在本机生成并写入受保护环境配置。未配置返回 503 `CREDENTIAL_KEY_UNAVAILABLE`，不使用默认密钥或降级为无密钥摘要。密钥丢失会影响已有码的查找；轮换流程留待运维批次，不可直接改密钥后继续兑换。

验证使用带随机盐的 scrypt，活动 ID 与规范化码的 HMAC-SHA-256 以二进制存储，并有 `(event_id, credential_lookup)` 唯一约束。慢哈希计算释放数据库连接；写入先锁活动，锁内重查草稿及重复码，与审计同事务。不同活动允许使用相同码。审计只记录凭证版本、来源、更新时间，日志与校验错误不回显码或摘要。

错误：格式不合规 422 `VALIDATION_ERROR`，重复码 409 `CREDENTIAL_CONFLICT`，非草稿 409 `EVENT_NOT_DRAFT`，无权或路径绑定错误 404；生成碰撞最多重试 5 次，耗尽 503 `CREDENTIAL_GENERATION_BUSY`（Retry-After: 1），高成本哈希繁忙 503 `AUTH_BUSY`。本操作无幂等 key，超时先查询元数据确认版本；若明文丢失只能重新设置，不可自动重复生成。发布后重置由 08 提供。

### 活动发布与复制（提交 07，已实现）

- `GET /api/v1/events/{event_id}/publish-check`（14b 后端新增）：有效主办方会话且为活动拥有者；无请求体、无需 CSRF。仅草稿可检查，200 `PublishCheck`；业务问题通过 `can_publish=false` 与 `issues` 返回。
- `POST /api/v1/events/{event_id}/publish`：拥有者 + Origin/CSRF；无请求体。成功 200 `PublishResult`，包含 EventInfo、不可变 snapshot、各对象的 PENDING 任务和 **仅本次补齐** 的 generated_credentials。已有手动或自动码不回显、不覆盖。公开活动码为 12 位随机字母数字，仅定位活动。EventInfo 新增 public_code、published_at、version（草稿 0、发布 1）。
- `GET /api/v1/events/{event_id}/publication`：仅拥有者，200 `PublicationInfo`。查询已持久化的规则/名单快照及任务，无凭证；草稿返回 404。用于发布响应丢失后的核验，不等于 13 的按角色状态快照。
- `POST /api/v1/events/{event_id}/copy`：拥有者 + Origin/CSRF；任意活动状态均可复制，无请求体，201 EventInfo。复制配置及名单，所有内部 ID 重新生成，新活动为 DRAFT、version=0，无活动码/发布时间/凭证/会话/任务/评分/结果。

发布要求至少一个对象、一位评委及完整规则；使用实际 N 校验算法最低人数与 K≤N，缺省 K 根据评分核心推导并固化。原始规则字段、维度、名单 ID/编号/姓名/对象顺序、过程设置写入 `score_event_snapshots`，每场只允许一份。每个对象建立一个任务，每个任务冻结全部应交评委；复合外键禁止跨活动关联，RESTRICT 保留历史。快照不含凭证状态、哈希或 HMAC。09 提供开评/暂停/恢复/跳过，10 提供评分提交与本人回执。

补码慢哈希在事务外准备；提交时锁活动并重新读取规则/名单/凭证。发布状态、活动码、补码、快照、任务、应交名单及审计在同一事务提交；任何失败均回滚。准备期间新增未设码评委或新码冲突返回 409 `PUBLISH_CONFLICT`，核验后可重新发布；并发发布只有一个成功，另一请求 409 `EVENT_NOT_DRAFT`。校验不合格返回 422 `PUBLISH_INVALID`，14b 起附 `error.issues`，与预检共用同一校验逻辑。活动码唯一碰撞最多重试 5 次，耗尽 503 `PUBLIC_CODE_BUSY`。权限及通用错误同草稿接口。

发布后所有草稿编辑及名单增删改被拒绝；展示设置编辑仍留后续。重复发布不重新返回明文。发布超时先 GET publication；成功时即视为发布完成，若补码明文丢失只能由 08 重置后分发。复制没有幂等键，超时先核验活动列表，不能自动重复复制。所有响应禁止缓存。

#### 发布预检（14b 后端）

响应例子：

```json
{
  "can_publish": false,
  "issues": [{"code": "MINIMUM_BALLOTS_EXCEEDS_JUDGES", "message": "最低有效份数不能超过评委人数", "field": "scoring_rule.minimum_ballots"}],
  "entry_count": 2,
  "judge_count": 3,
  "missing_credential_count": 2,
  "minimum_ballots": null
}
```

`minimum_ballots` 为依据实际评委人数 N 校验后的 K；未显式指定时复用评分核心推导：平均法 `max(1, ceil(0.8N))`，去极值平均法 `max(5, ceil(0.8N))`。规则或人数不满足条件时为 null；仅缺对象不影响合法 K 的显示。`missing_credential_count` 只表示发布时需补码的人数，不是阻塞问题。预检不生成明文、不计算凭证哈希、不修改数据或审计；活动/规则/名单在 REPEATABLE READ 同一读视图内无锁读取。

每条问题包含稳定 `code`、中文 `message` 和点分隔定位 `field`（数组索引从 0 开始，如 `scoring_rule.criteria.0.step`）。问题码不属于顶层 HTTP 错误码：

| code | 定位字段 | 含义 |
| --- | --- | --- |
| ENTRIES_REQUIRED | entries | 至少一个对象 |
| JUDGES_REQUIRED | judges | 至少一位评委 |
| SCORING_RULE_REQUIRED | scoring_rule | 尚未配置规则 |
| TRIMMED_MEAN_JUDGES_REQUIRED | scoring_rule.algorithm | 去极值需要至少 5 位评委 |
| MINIMUM_BALLOTS_EXCEEDS_JUDGES | scoring_rule.minimum_ballots | K>N |
| MINIMUM_BALLOTS_BELOW_FLOOR | scoring_rule.minimum_ballots | K 低于算法下限 |
| WEIGHTS_SUM_INVALID | scoring_rule.criteria | 权重合计不为 1 |
| RULE_INVALID | scoring_rule 或具体子字段 | 其他格式、模式、维度、满分或步长问题 |

草稿写入原有规则校验保持不变：非法权重等通常已在创建/修改时以 422 `VALIDATION_ERROR` 被拒绝；预检仍校验已存储规则。问题列表可同时报告缺对象、缺评委及规则问题，规则内部按现有核心校验顺序报告，不承诺穷举所有错误；不回显非法输入值或异常正文。

预检未登录返回 401 `SESSION_EXPIRED`，无权/不存在返回 404 `NOT_FOUND`，非草稿返回 409 `EVENT_NOT_DRAFT`，数据库故障返回 503 `SERVICE_UNAVAILABLE`（`Retry-After: 3`）。响应 `Cache-Control: no-store`；这是只读请求，可按退避策略重试。

`can_publish=true` 表示当前业务配置通过，不预留名单、锁或凭证，不保证稍后的发布成功；实际发布在准备前和活动锁内均重新校验。密钥配置、凭证生成等运行条件仍由发布接口检查。POST 校验失败时保留 `{error:{code,message},request_id}` 包装并附 `error.issues`；其他错误不额外返回此字段。前端发布失败后可重新 GET 预检展示最新问题；14a 的 `ApiError` 当前仅解析顶层 code/message，直接展示 POST 问题列表时需在页面批次扩展解析。

### 评委预览、会话与重置（提交 08，已实现）

| 方法与路径（/api/v1 前缀） | 成功结果 | 权限/用途 |
| --- | --- | --- |
| GET /join/{code} | 200 PreviewInfo | 公共，仅已发布活动的基本信息、状态和 exchange_open；不含名单/规则/成绩/凭证 |
| GET /judge-sessions/csrf | 200 CSRFInfo | 公共，建立独立评委 bootstrap Cookie |
| POST /judge-sessions/verify | 200 ConfirmationInfo | 可信 Origin + bootstrap CSRF，校验活动码及个人身份码，返回本人姓名/编号和短期确认令牌 |
| POST /judge-sessions/exchange | 200 JudgeSessionInfo + HttpOnly Cookie | 同一浏览器 bootstrap CSRF + 确认令牌，用户确认身份后建立会话 |
| GET /judge-sessions/me | 200 JudgeSessionInfo | 有效评委会话，返回本人信息、expires_at、会话 CSRF、read_only |
| POST /judge-sessions/logout | 204 | 有效评委会话 + Origin + 会话 CSRF，数据库撤销并清除评委 Cookie |
| POST /events/{event_id}/judges/{judge_id}/reset-credential | 200 CredentialResult | 活动拥有者 + Origin/主办方 CSRF；仅 READY/RUNNING |

调用顺序：公共预览 → `/judge-sessions/csrf` → `verify` → 展示返回姓名编号由用户确认 → `exchange` → `/me` 恢复会话。公共活动码前后去空白、统一大写后为 12 位 ASCII 字母数字。verify 与设置身份码使用相同规范化，必须提供个人码，禁止客户端指定 judge_id。

verify 请求：

```json
{"public_code":"ABCDEFGH2345","code":" FIRST123 "}
```

exchange 请求（confirmation_token 取自 verify 响应）：

```json
{"confirmation_token":"<本次确认令牌>"}
```

确认令牌为 256 位随机值，数据库只存 SHA-256 摘要，默认 180 秒有效、一次消费，绑定活动/评委/凭证版本及本浏览器 bootstrap Cookie。verify 不建立评分会话。消费令牌、建立会话及评委审计同事务；默认会话绝对有效期 86400 秒，读取及同浏览器重新确认均不续期。数据库仅存会话令牌摘要。所有请求/响应禁止缓存，身份码和确认令牌只经 POST 传递，不放 URL、日志或公共二维码。

Cookie 分离为 `__Host-score_judge_bootstrap`（600 秒）和 `__Host-score_judge_session`，Secure/HttpOnly/SameSite=Strict/Path=/，无 Domain。本机关闭 Secure 时去除 __Host- 前缀。verify/exchange 使用 bootstrap CSRF；logout 使用 `/me` 返回的会话 CSRF。主办方 Cookie、评委 Cookie 及各自 CSRF 互不替代。前端私人邀请 fragment 读取/清除在 14/16 实现。

单有效会话由活动 → 评委 → 确认令牌/会话行锁及生成列 UNIQUE(active_judge_id) 共同保证。第二台设备返回 409 `JUDGE_SESSION_ACTIVE`，需主办方重置换机；原浏览器携带同一有效 Cookie 可通过新的身份确认取得原会话，期限不延长。同一浏览器已有另一评委身份返回 409 `SESSION_SWITCH_REQUIRED`，需先主动退出。过期会话在下次兑换锁内撤销后允许重建。每次鉴权检查服务端到期时间、撤销状态、凭证版本及活动状态；不依赖缓存或客户端判断。

重置请求 `{"reason":"更换手机","code":"NEWCODE123"}`；省略 code 或 null 自动生成。reason 去空白后为 1～500 字。新码不能是本人当前码，也不能是同活动其他评委的码，分别返回 409 `CREDENTIAL_UNCHANGED` / `CREDENTIAL_CONFLICT`。成功时凭证版本 +1、撤销所有旧会话/未消费确认令牌、写入重置原因和版本审计、活动 version +1，在同一事务提交；评委 ID/姓名/编号、冻结规则/名单与历史归属保持不变。响应只返回当次新明文。草稿应使用 PUT credential，结束/归档不允许重置，返回 409 `RESET_NOT_ALLOWED`。

FINISHED/ARCHIVED 的公共预览仍可读，verify 与 exchange（包括此前已获得的确认令牌）均返回 409 `EVENT_CLOSED`；已有有效会话 `/me` 返回 read_only=true。当前交付会话及本人评分回执读接口，活动成绩查询在后续实现；结束/归档操作接口属 11。WebSocket 撤销通知属 18，但 HTTP 鉴权在重置提交后立即拒绝旧会话。

验证按来源（默认 600 次/300 秒，verify/exchange 共用）、活动（3000 次/300 秒）与活动内规范化码的 HMAC 摘要（10 次/300 秒）共享限流；失败和成功都计数，事务提交后才返回 429，重启/多进程不重置计数。同一会场共用 IP 不会把不同码当作同一身份；这不是容量验收结论。数据仅保存摘要、不保存尝试码或 IP 明文。scrypt 仍受每进程最多两次计算限制，503 AUTH_BUSY 按 Retry-After 等待。短期确认令牌每次成功验证最多清理 100 条已过期记录，正式会话与审计不自动删除。

错误还包括 401 `CONFIRMATION_EXPIRED`（缺失/过期/已消费/重置/浏览器不匹配）、`SESSION_EXPIRED`（会话缺失或失效）、`INVALID_CREDENTIALS`（身份码无效），以及通用 Origin/CSRF/参数/数据库错误。verify/exchange/reset 均无自动幂等重试：兑换响应丢失先 GET me；若浏览器没收到 Cookie 而服务端已建会话，需主办方重置，不能抢占已有会话。重置响应丢失先查评委版本，明文无法恢复；必要时主动再次重置并分发。确认过期需重新 verify 后再次确认姓名编号。

### 评分任务控制（提交 09，已实现）

活动拥有者可 `GET /api/v1/rounds/{id}` 查询任务；`POST /rounds/{id}/open`、`/pause`、`/resume`、`/skip`（前缀 `/api/v1`）控制任务。写请求需主办方 Cookie、Origin、CSRF，成功均为 200 RoundState，含任务 version、deadline_at、remaining_seconds、server_time 和 event_version。发布查询中的任务也增加两个时钟字段。

普通控制请求 `{"expected_version":1}`，跳过为 `{"expected_version":1,"reason":"对象缺席"}`。expected_version 指任务版本（初始 1），为严格正整数；不是活动版本。所有成功控制将任务/活动版本各增 1，与审计同事务。

- open：PENDING → OPEN，使用发布快照时限；READY 活动变 RUNNING。
- pause：OPEN → PAUSED，必须锁内当前时间严格早于截止。冻结 Decimal 剩余秒（响应为十进制字符串，精确到微秒），deadline_at 清空。
- resume：PAUSED → OPEN，按剩余时间重算截止。不限时两字段始终为 null。
- skip：仅 PENDING → SKIPPED；原因去空白后 1～500 字，写入审计。已开始任务的无结果处理在 11。
- 活动必须为 READY/RUNNING；同场最多一个 OPEN/PAUSED，活动行锁及数据库生成列唯一约束共同保证。先锁活动后锁任务，再读取时钟和状态。

错误：无权/不存在 404 NOT_FOUND；旧任务版本 409 VERSION_CONFLICT；状态不允许 409 ROUND_STATE_CONFLICT；活动结束 409 EVENT_NOT_RUNNING；已有活跃任务 409 ACTIVE_ROUND_EXISTS；截止或恰好截止 409 DEADLINE_EXCEEDED。422 表示版本/原因/字段不合法。

控制接口无幂等 key；超时先 GET 当前任务核验，不能盲目重复操作。版本冲突需刷新并重新确认；503 按 Retry-After 退避后先查询。收评、重开、成绩公布在 11，自动截止收评在 12；即使尚未自动关闭，截止后也不能暂停或提交新评分。

### 评分提交与回执（提交 10，已实现）

`PUT /api/v1/rounds/{id}/my-ballot`：有效评委 Cookie、可信 Origin、评委会话 CSRF，必须提供一个 `Idempotency-Key` UUID 请求头。首次提交和改分均返回 200 BallotReceipt，只有事务提交成功才返回。

`GET /api/v1/rounds/{id}/my-ballot`：有效评委会话，只能查询本人；无 Idempotency-Key 时返回当前有效版本，携带该请求头时返回该次成功操作的原回执，包括后续已被改分替代的版本。没有有效评分返回 404 BALLOT_NOT_FOUND，没有该次操作回执返回 404 RECEIPT_NOT_FOUND。活动结束后已有有效会话仍可查询。

请求示例和多维 87.00 回执见 5.3。BallotReceipt 同时包含 scores、rule_version、ballot_id、receipt_id、round_id、revision、total_score、accepted_at；原始分为十进制字符串。total_score 是个人百分制分数的两位小数展示值，不代表活动最终成绩。

- 首次 expected_ballot_revision=0；改分用当前 revision 和新 UUID。规则冻结时 allow_revisions=false 则禁止改分。不同评委可各自使用相同 UUID；同一评委的 UUID 跨任务唯一，换任务复用会发生幂等冲突。
- 请求摘要包括明确 round_id、rule_version、expected_ballot_revision 和所有维度。忽略维度顺序与等值十进制文本差别（90、90.0 相同），重复维度仍被拒绝。相同 key 不同请求返回 409 IDEMPOTENCY_CONFLICT；同 key 同内容始终返回原回执，之后的改分不覆盖它。
- 先验证会话、活动归属和冻结应交资格，再锁内查询幂等记录；命中成功记录时不再检查任务截止/开放状态，因此暂停、收评、结束后仍可核验。已撤销或过期会话不能借此取得回执，凭证重置后用新会话可继续查询本人历史。
- 新提交/改分只接受 OPEN 且锁内 server_now < deadline_at（null 为不限时）。活动结束只读，不能将旧任务请求写入新任务。完整维度、范围、步长、规则版本和评分版本均检查。
- 统一活动 → 评委/会话 → 任务锁；任务锁等待后重新读取时间并检查会话到期。收评/暂停/提交共用任务锁，所有事务 READ COMMITTED。成功写入一张逻辑评分单、追加版本、永久幂等回执、评委审计及内部 outbox；任一失败全部回滚。已交数按逻辑评分单数计算，改分不增加人数。
- 原始 scores 保存在 JSON 十进制字符串中；computed_total 为 DECIMAL(65,30) 查询缓存，display_total 为从评分核心结果直接 ROUND_HALF_UP 的 DECIMAL(5,2)。后续成绩汇总必须从冻结规则及原始分重算，不使用上述缓存或展示分替代。历史版本无覆盖或删除接口。
- 死锁 1213 或锁等待超时 1205 最多尝试 3 次，每次完整回滚并释放连接后短暂随机退避，沿用原 key、重新检查时钟/权限。耗尽返回 503 SERVICE_UNAVAILABLE / Retry-After: 3。连接中断和提交结果不明不在服务内自动重试，调用方使用原 key 核验；不会显示假成功。
- outbox 本批只持久化、暂不投递；包含内部事件版本及任务/评委/评分版本/已交数，不包含原始分或凭证。18 再按各角色授权转换为独立流序列，不能将内部版本直接用作大屏或评委流版本。

错误：401 SESSION_EXPIRED；403 FORBIDDEN（不属应交名单）；404 NOT_FOUND（跨活动/不存在任务）；409 ROUND_NOT_OPEN、DEADLINE_EXCEEDED、EVENT_NOT_RUNNING、RULE_VERSION_MISMATCH、REVISION_CONFLICT、REVISIONS_DISABLED、IDEMPOTENCY_CONFLICT；422 SCORE_INVALID（维度/范围/步长）、VALIDATION_ERROR（请求结构/UUID/非字符串分数等）。Origin/CSRF 及服务错误沿用第 6 节。不能仅凭 404 回执断言正在处理的请求最终不会提交，继续复用同一 key 核验。

## 3. 通用业务约定（实现边界见第 1、2 节）

主办方/评委认证、凭证、发布/复制、请求来源、草稿权限/编号及通用错误已实现；评分控制、幂等写分已实现；大屏及实时约定仍待后续提交。

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

主办方/评委 Cookie、有效期、CSRF、分页与错误包装见第 2、6 节。
活动码仅用于定位活动，不能直接获得评分权限。身份码、会话凭证不进入普通查询响应、日志和公共二维码。

### 收评、冻结结果与活动结束（11）

以下接口均要求主办方会话及活动 owner；写请求要求可信 Origin 和会话 CSRF。

| 方法与路径（省略 /api/v1） | 请求与响应 |
| --- | --- |
| POST /rounds/{id}/close | `expected_version`、可选 `reason`；OPEN/PAUSED → CLOSED，返回 RoundState |
| POST /rounds/{id}/reopen | `expected_version`、必填原因、必填 `duration_seconds`（1～86400 或 null 不限时）；CLOSED → OPEN |
| POST /rounds/{id}/publish-result | `expected_version`；CLOSED 且达到 K → PUBLISHED |
| POST /rounds/{id}/no-result | `expected_version`、必填原因；CLOSED 且未形成成绩 → NO_RESULT |
| GET /rounds/{id}/results | 全部历次不可变收评快照，含规则版本、有效评分回执/版本、原始分、高精度个人总分、剔除标记、缺交 ID、最终分及收评原因 |
| GET /events/{id}/ranking | 仅已公布成绩，按两位小数采用 1、2、2、4 并列名次 |
| POST /events/{id}/finish | 活动 `expected_version`；全部任务已公布/跳过/无结果后结束 |
| POST /events/{id}/archive | 活动 `expected_version`；仅 FINISHED 可归档，数据保留 |

收评与提交均先锁活动后锁任务，再读取有效评分。未收齐时未填原因返回 422 `CLOSE_REASON_REQUIRED`；缺交不补零。n<K 可以收评，公布返回 409 `INSUFFICIENT_BALLOTS`。无结果、跳过、公布均为终态。已有 OPEN/PAUSED 任务时不能重开另一任务。重开保留评分、旧快照和原幂等回执，新截止时间从锁内服务端时间计算；是否允许改分继续遵循冻结规则。

成绩直接从冻结规则与原始分复算，不使用舍入后的个人总分缓存。每次收评新增快照；公布只冻结最新一份，不改写历史。成功回执在截止、收评、公布、结束及归档后仍可用原 key 复查（要求有效本人会话）；新提交被拒绝。

版本落后返回 409 `VERSION_CONFLICT`，状态不合法返回 `ROUND_STATE_CONFLICT` / `EVENT_STATE_CONFLICT`，提前结束返回 `UNFINISHED_ROUNDS`，消息列出待处理任务 ID。网络超时先读取状态及结果，再决定操作，不能自动套用新版本重发。结果、状态、审计和 outbox 在同一事务提交；数据库故障返回 503，失败不保留半成品。其他管理员得到 404，评委和大屏无权访问上述管理接口。

### 到期自动收评（12）

独立 `python -m score_api.worker` 扫描已到期 OPEN 任务，复用手动收评事务。自动记录原因为“评分时间已到”，快照 `source=deadline`，审计 actor=null。暂停和不限时任务不参与扫描；worker 延迟或停机不延长提交截止时间。多实例竞争只冻结一次；失败不改变状态，下轮重试；重启按数据库截止时间恢复。暂不自动公布结果。

### 角色快照、大屏授权与展示（13）

所有快照要求活动已发布，草稿返回 409 `EVENT_NOT_PUBLISHED`。快照在 REPEATABLE READ 只读事务的单一 InnoDB 读视图中读取（13a），版本与进度、评分、结果来自同一已提交状态；不持行锁，不等待也不阻塞评分提交和任务控制，看不到未提交的写入。响应 `Cache-Control: no-store`，包含 `server_time`。路径明确区分角色，不能通过查询参数切换权限。

| 方法与路径（省略 /api/v1） | 授权与响应 |
| --- | --- |
| GET /events/{id}/snapshot | 主办方 Cookie 且 owner；AdminSnapshot，含规则、名单、原始评分历史、全部收评快照、排名、展示设置与大屏授权元数据 |
| GET /judge/events/{id}/snapshot | 评委 Cookie 且属于活动；JudgeSnapshot，含本人身份、冻结规则、任务进度、本人回执/改分历史、已公布成绩和排名 |
| GET /screens/{grant_id}/snapshot | `Authorization: Bearer <token>`；ScreenSnapshot，仅安全活动信息、展示设置、当前对象进度、已公布成绩及受数量限制的排行榜 |
| POST /events/{id}/screen-grants | owner + Origin/CSRF；JSON `ttl_seconds` 可省略（默认 86400，60～2592000），201 CreatedGrant；随机 token 仅当次返回 |
| GET /events/{id}/screen-grants | owner；仅 ID、活动 ID、创建/到期/撤销时间，不返回 token 或摘要 |
| DELETE /events/{id}/screen-grants/{grant_id} | owner + Origin/CSRF；204，重复撤销同一授权仍 204，其他活动的授权 404 |
| PUT /events/{id}/screen | owner + Origin/CSRF；完整 ScreenSettings，返回 ScreenDisplay |

评委响应不含他人的评分、回执、缺交评委明细或未公布汇总分。大屏不含个人评分、回执、评委名单或任何身份凭证；只有任务状态为 PUBLISHED 的成绩可输出。只读授权不能调用管理、评委、提交、结果历史接口。授权每次读取都在同一读视图中核验摘要、撤销及到期时间，撤销或凭证重置提交后的读取立即拒绝；不接受 URL 查询参数中的 token，公开活动码也不能充当授权。数据库仅保存随机 256 位 token 的 SHA-256 摘要；客户端可在未来大屏页面的 fragment 中传递 token，读取后清除，调用 API 时使用请求头。最大同时有效授权 20 个，超出返回 `SCREEN_GRANT_LIMIT`。

展示请求必填：`expected_version`（管理活动版本）、`mode`、`title`、`theme`（light/dark）、`show_public_qr`、`leaderboard_limit`；`round_id` 在 progress/paused/result 模式必填，其他模式必须为空。任务必须属于当前活动，并分别处于 OPEN/PAUSED/PUBLISHED；ended 要求活动已结束或归档，否则 409 `DISPLAY_STATE_CONFLICT`。展示字段不修改冻结规则和名单，结束后仍可切换已公布单项成绩。

默认开评/恢复/重开切 progress，暂停切 paused，当前任务收评切 waiting，公布切 result，结束切 ended（最终榜单）。手动可切 waiting、progress、paused、result、leaderboard、ended。所有展示和授权变更与审计/outbox 同事务；审计及 outbox 不含 token。

版本按活动管理员流、大屏流、每位评委个人流独立保存。首次交分推进所有角色的进度版本；改分只推进管理员及该评委版本，幂等重放不推进版本；任务状态、公布、结束推进全部角色。展示设置只推进管理员和大屏；授权创建/撤销只推进管理员。服务器时间变化不推进版本。客户端按 `(活动, 角色, 当前身份或授权)` 隔离版本和缓存，不能跨角色比较版本；退出、撤销或重新登录时清空个人缓存。此批只提供 HTTP 快照和持久化版本，WS/Redis/outbox 投递属于 18。

## 4. 后续接口清单（规划中）

本表用于定位功能范围。暂不提前复制尚未实现的字段模型；正式实现后更新状态，并链接对应 OpenAPI operation 和本文业务说明。
名单子资源 CRUD 已在第 2 节明确；授权撤销路径在对应提交中明确。

| 提交 | 方法与路径（省略 /api/v1） | 用途及权限 |
| --- | --- | --- |
| 18 | POST /realtime/tickets | 兑换短时一次性连接票据；有效会话/展示授权，细节随实现明确 |
| 18 | WS /api/v1/events/{id}/stream（完整路径） | 授权实时订阅；一次性票据 |
| 20 | GET /events/{id}/exports/{kind} | 汇总/明细/审计 CSV；活动拥有者 |

## 5. 关键业务流程

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
活动结束后停止新会话兑换，已有未过期会话只读。身份确认按第 2 节 verify → exchange 两步接口执行，用户确认姓名编号后才提交 exchange。

### 5.3 提交、改分与超时核验

以下提交接口已实现；示例 ID 为占位值，需替换为实际任务和回执。

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
回执内容示例（成功 HTTP 200；字段需与实际提交一致）：

```json
{
  "ballot_id": "ballot_example",
  "receipt_id": "receipt_example",
  "revision": 1,
  "rule_version": 1,
  "scores": [
    { "criterion_id": "content", "value": "90" },
    { "criterion_id": "innovation", "value": "18" },
    { "criterion_id": "performance", "value": "8" }
  ],
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
| 401 | INVALID_CREDENTIALS | 主办方账号/密码无效，或评委身份码无效；人工修正 |
| 401 | SESSION_EXPIRED | 会话缺失、非法、撤销、过期或账号停用；重新登录 |
| 403 | ORIGIN_FORBIDDEN | 非可信、缺失、null 或重复 Origin；修正来源配置，不自动重试 |
| 403 | CSRF_INVALID | 缺失或错误 CSRF；登录前重新取 `/auth/csrf`，登录后取 `/auth/me` |
| 404 | NOT_FOUND | 活动/名单不存在或不属于当前主办方/路径活动；不自动重试 |
| 409 | EVENT_NOT_DRAFT | 活动已不处于草稿；刷新状态 |
| 409 | NUMBER_CONFLICT | 当前活动同类名单中编号重复；修改编号 |
| 422 | VALIDATION_ERROR | 请求结构、账号格式或字段长度错误；修正参数 |
| 429 | RATE_LIMITED | 登录/评委验证兑换限流；按 `Retry-After` 秒数等待后由用户重试 |
| 503 | AUTH_BUSY | 密码计算并发已满；`Retry-After: 1` |
| 503 | SERVICE_UNAVAILABLE | 数据库未配置、不可用、事务失败或池等待超时；`Retry-After: 3` |
| 404 / 405 | NOT_FOUND / METHOD_NOT_ALLOWED | 路径不存在或方法错误，405 保留 Allow |
| 500 | INTERNAL_ERROR | 未预期异常；使用 request_id 排查，不回显内部细节 |

登录/退出无幂等 key。登录响应丢失时先用 `/auth/me` 检查浏览器会话，必要时重新登录；不自动反复提交密码。退出响应丢失后查询 `/auth/me`，401 表示会话已失效；已失效会话再次退出返回 401。认证写入与其审计同事务，提交后才返回成功与设置/删除 Cookie。

以下评分业务错误码已在 10 实现；INSUFFICIENT_BALLOTS 随 11 实现：

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

以上并非完整业务错误目录；任务控制和评分的新增错误及重试语义见第 2 节。

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
- 在 `frontend` 目录运行 `npm run gen:api` 更新前端 `src/api/openapi.json` 与 `schema.d.ts` 并一并提交；后端契约测试会拒绝未同步的变更。
- 明确权限、成功/失败状态、错误码及重试语义；涉及状态变更时补并发和截止规则。
- 验证文档示例与真实响应一致，在对应 review 说明记录证据。
- 尚未确定的契约继续标为规划中，不将设计示例包装成已经可用的 API。

未来接口数量增多后，可按 auth/events/rounds/realtime 拆分至 docs/api/，本文保留总索引。
