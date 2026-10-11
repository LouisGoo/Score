# API 接口文档

更新时间：2026-10-10。当前交付批次：02（十进制评分核心）。

## 1. 实现状态与文档分工

**当前仅实现存活检查业务端点，尚未实现登录、活动管理、评分及实时接口。**
提交 02 已提供后端评分纯函数，尚未接入 HTTP；调用方式与边界见 [Review 02](review-02.md)。本批未新增接口、权限或 HTTP 错误/重试契约。
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
数据库就绪检查将在提交 03 实现，其路径和响应结构届时补齐。
当前尚无统一业务错误格式或 request_id 中间件；不要将下文规划中的错误约定当作现有行为。

实现：[main.py](../backend/src/score_api/main.py)。
验证：[test_health.py](../backend/tests/test_health.py)。

## 3. 通用业务约定（规划中）

除 /api/v1 前缀已用于存活接口外，下列约定将在相应功能提交中实现并验证。

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

Cookie 名称、有效期、CSRF 头名、分页结构及通用错误 JSON 包装尚未确定，随实现补齐。
活动码仅用于定位活动，不能直接获得评分权限。身份码、会话凭证不进入普通查询响应、日志和公共二维码。

## 4. 接口清单（全部规划中）

本表用于定位功能范围。暂不提前复制尚未实现的字段模型；正式实现后更新状态，并链接对应 OpenAPI operation 和本文业务说明。
名单子资源的具体 CRUD 路径以及授权撤销路径在对应提交中明确。

| 提交 | 方法与路径（省略 /api/v1） | 用途及权限 |
| --- | --- | --- |
| 04 | POST /auth/login、POST /auth/logout | 管理登录/退出；退出需管理会话 |
| 05 | POST /events、GET /events | 创建/列出本人活动；管理会话 |
| 05 | GET /events/{id}、PATCH /events/{id} | 查询/编辑草稿配置；活动拥有者 |
| 05 | /events/{id}/entries、/events/{id}/judges 子资源 | 草稿名单 CRUD；活动拥有者 |
| 06 | PUT /events/{id}/judges/{judge_id}/credential | 草稿身份码设置；活动拥有者，仅本次返回明文 |
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

## 6. 业务错误码（规划中）

统一响应需携带 request_id。具体 JSON 结构、各码对应的 HTTP 状态及框架参数校验错误的包装方式，将在提交 04 和对应业务提交中补齐。

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

以上并非完整错误目录。控制操作版本冲突、限流和依赖故障等错误将在实现时明确，不能推断复用上述某个码。

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
