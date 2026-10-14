# Web 前端开发计划

更新时间：2026-10-14。基线：01～13 及 13a 已交付，后端 HTTP 闭环完整；14～17 为前端批次。需求以[产品需求与架构设计](在线打分系统-产品需求与架构设计.md)为准，接口以[接口文档](api.md)及运行时 OpenAPI 为准，批次顺序见[逐次 commit 计划](commit-plan.md)。

## 1. 现状

- 后端：54 个 HTTP 接口，覆盖认证、活动草稿、身份码、发布/复制、评委会话、任务控制、幂等评分、收评/公布/排名/结束/归档、三角色快照、大屏授权与展示控制。实时推送（18）、导出（20）未实现。
- 前端：仅 `App.tsx` 连接检查骨架；依赖只有 React 19.3、Vite 8.3、TypeScript 7.0.2；无路由、请求状态、二维码、测试或 lint；CI 只执行 `npm run build`。
- TypeScript 7.0.2 为原生编译器，不再提供 TS 5 的 JS 编译器 API。依赖该 API 的工具（如 `openapi-typescript`、`typescript-eslint`）需在 14a 实测兼容性，不能默认可用。

2026-10-14 用户确认：接受“发布后仅可改大屏展示字段”（G4 不补）；管理端引入 Ant Design 组件库；前端联调使用远端数据库。14a 已按第 4 节落地，见 [Review 14a](review-14a.md)。

## 2. 页面与接口对应

路由沿用需求第 10 节；admin、judge、screen 三个模块分别懒加载，手机端不加载管理端代码。

| 路由 | 批次 | 主要接口（省略 /api/v1） |
| --- | --- | --- |
| `/admin/login` | 14b | `GET auth/csrf`、`POST auth/login`、`GET auth/me`、`POST auth/logout` |
| `/admin/events`、`/admin/events/new` | 14b | `GET/POST events`、`POST events/{id}/copy`、`DELETE events/{id}` |
| `/admin/events/:id/settings` | 14b | `PATCH events/{id}`、`entries`/`judges` 子资源、`PUT .../credential`、`POST .../reset-credential`、`POST events/{id}/publish`、`GET events/{id}/publication` |
| `/admin/events/:id/control` | 15 | `GET events/{id}/snapshot`、`POST rounds/{id}/open\|pause\|resume\|skip\|close\|reopen\|publish-result\|no-result`、`POST events/{id}/finish\|archive` |
| `/admin/events/:id/results` | 15 | `GET events/{id}/snapshot`（含收评快照、评分历史与排名，与控制台同一读视图）；导出入口留待 20 |
| 大屏管理（控制台内） | 17 | `POST/GET/DELETE events/{id}/screen-grants`、`PUT events/{id}/screen` |
| `/join`、`/join/:publicCode` | 16 | `GET join/{code}`、`GET judge-sessions/csrf`、`POST judge-sessions/verify`、`POST judge-sessions/exchange` |
| `/judge/events/:id`、`.../history` | 16 | `GET judge-sessions/me`、`GET judge/events/{id}/snapshot`、`PUT/GET rounds/{id}/my-ballot`、`POST judge-sessions/logout` |
| `/screen/:grantId#<token>` | 17 | `GET screens/{grant_id}/snapshot`（`Authorization: Bearer`） |

## 3. 后端缺口评估

| 编号 | 缺口 | 建议 | 处理批次 |
| --- | --- | --- | --- |
| G1 | 三角色快照持活动行锁，轮询与评分提交串行，锁等待 3 秒后 503 | 必须先修 | 13a 已修复：改为无锁一致性读 |
| G2 | 活动列表缺对象数、任务完成进度（需求 6.1） | 已补，前端已接入 | 14b，见 [后端](review-14b-backend.md)、[前端](review-14b.md) |
| G3 | 发布校验仅两条笼统 `PUBLISH_INVALID` 消息 | 已补，前端已接入 | 14b，见 [后端](review-14b-backend.md)、[前端](review-14b.md) |
| G4 | 发布后不能修改活动标题、简介 | 不补 | 用户已确认接受；大屏标题/主题经 `PUT /screen` 修改 |
| G5 | 无评委在线/离线状态 | 依赖实时 | 15 已按已交/未交展示；在线状态随 18 |
| G6 | 无 `PUBLIC_BASE_URL`，二维码地址无来源 | 前端处理 | 14b/17 用构建变量，缺省回退 `location.origin`；22 统一配置 |
| G7 | `UNFINISHED_ROUNDS` 消息内为任务 ID | 前端处理 | 15 已用快照映射对象编号/名称，结束前另做本地检查 |
| G8 | 管理快照每次返回全部评分历史和收评快照 | 暂不补 | P0 规模可接受；15 控制台有进行中对象时 3 秒、其余 10 秒、结束后停止，18 后改增量 |
| G9 | `GET my-ballot` 仍持活动锁 | 保持 | 仅超时核验时调用，不轮询 |

G2：列表响应使用继承 `EventInfo` 的 `EventListItem`，增加 `entry_count`、`judge_count`、`round_count`、`finished_round_count`（终态任务数）。一条 SQL 完成，草稿任务计数为 0，避免前端逐个活动拉名单；其他 `EventInfo` 响应保持原结构。

G3：新增只读 `GET /events/{id}/publish-check`，返回问题列表（`code`、`message`、`field`）、实际 K、名单数量及补码数；`publish` 的 422 在 `error.issues` 复用同一校验输出。前端仍做就地输入校验，发布结论以该接口为准。详细字段与错误见 [API](api.md)。

G4 理由：需求 6.1 写明“标题、主题等展示字段可改并留痕”。主题与大屏标题已可改；活动标题和简介的发布后修改需推进评委/大屏版本并留审计，影响面大于收益，建议 P0 末尾或按现场需要再定。

## 4. 前端基础层约定（14a）

### 4.1 工程与依赖

- 已锁定：Ant Design 6.6.6（含 QRCode 组件，不另装二维码库）及 @ant-design/icons、React Router 8.4（数据路由 + 路由级 `lazy`）、TanStack Query 5.104、big.js 7（个人总分预览）。
- 接口类型：`npm run gen:api` 从后端应用导出 `src/api/openapi.json`，再在独立 npx 环境用 TypeScript 5.9.3 运行 `openapi-typescript` 生成 `src/api/schema.d.ts`，两者均提交。项目本身不安装 TS 5。后端测试 `test_openapi_contract.py` 比对提交的 JSON 与运行时 OpenAPI，接口变更未重新生成时 CI 失败。
- 测试使用 Vitest 5 + Testing Library（jsdom）；lint 使用 Oxlint（不依赖 TS 编译器 API）。CI 前端任务依次执行 lint、test、build。

### 4.2 目录

```text
frontend/src/
├── main.tsx / router.tsx     入口与懒加载路由
├── api/                      fetch 封装、错误解析、生成类型、按角色的接口函数
├── lib/                      小数预览、服务端时钟偏差、轮询、fragment 读取、幂等键、草稿存储
├── components/               跨模块的基础组件（占位页、路由错误边界）
├── pages/                    首页（独立懒加载分包）
├── admin/                    主办方页面（14b、15、17 的大屏管理）
├── judge/                    评委手机页面（16）
└── screen/                   只读大屏（17）
```

### 4.3 API 客户端与三种身份

- 统一同源 `/api/v1`，`credentials: 'same-origin'`，不开放跨域；写请求由浏览器自动携带 Origin。
- 主办方：登录前 CSRF 取自 `GET /auth/csrf`；登录后使用 `login`/`me` 响应中的会话 CSRF。评委：`verify`/`exchange` 使用 `GET /judge-sessions/csrf` 的 bootstrap CSRF，之后使用 `exchange`/`me` 返回的会话 CSRF。两套 CSRF 分开保存，不互相替代。
- CSRF 仅存内存，刷新后经 `me` 恢复，不写 localStorage。`CSRF_INVALID` 表示请求在业务处理前被拒，允许刷新 CSRF 后自动重试一次。
- 大屏：token 只从 URL fragment 读取，读取后立即 `history.replaceState` 清除；之后只经 `Authorization: Bearer` 发送，不进入查询参数、日志或本地存储。

### 4.4 错误与重试

- 统一解析 `{error:{code,message},request_id}`，界面显示中文提示并附 request_id 便于排查；错误码到提示和处理方式集中维护一张表。
- 401 `SESSION_EXPIRED`：清空对应角色缓存，主办方回登录页，评委回加入页。503：按 `Retry-After` 退避，提示服务繁忙。
- 任务控制、发布、复制、凭证、重置均无幂等键：超时或网络中断时不自动重发，先重新读取状态并提示“结果未知，请核对”。版本冲突 `VERSION_CONFLICT` 刷新后由用户重新确认。

### 4.5 分数与提交

- 分数全程使用十进制字符串，输入框保留原文本；提交不使用 `parseFloat`。个人总分预览用小数库按 `100 × Σ(x/M × w)` 计算，只做展示，权威值以回执为准。
- 每次“确认提交”生成一个 UUID 作为 `Idempotency-Key`，与请求体一起持久保存直到确认结果；超时用原 key 重试或 `GET my-ballot` 携带该 key 核验，未确认前显示“正在核验提交结果”。
- 草稿按“活动、评委、任务、规则版本”分键存储；切换任务保留旧草稿但不套用；退出身份时清理。断网恢复后先同步快照，再由评委确认，不自动补交。

### 4.6 时间、轮询与缓存（18 之前）

- 每次快照用 `server_time` 计算本机时钟偏差，倒计时按 `deadline_at` 本地计算，不每秒请求。暂停时显示 `remaining_seconds`。
- 18 之前只能轮询快照。13a 后快照不再阻塞评分提交，但仍计入数据库请求量。开发期建议：评委端 5 秒、大屏 3 秒、控制台 3 秒，均带 ±20% 随机抖动，页面不可见时暂停、回到前台立即刷新，自身写操作成功后立即刷新。实际间隔以 23 压测结果为准。
- 缓存键包含“活动、角色、身份或授权 ID”；版本只在同一缓存键内比较，忽略不高于当前版本的响应。退出、撤销、重新登录时清空对应缓存。
- 18/19 接入 WebSocket 后，轮询改为降级通道，接口层保持不变。

### 4.7 凭证展示

- 身份码明文只在设置、生成、重置、发布补码的当次响应中显示，提供复制与私人邀请二维码；离开页面即丢弃，不进入查询缓存。
- 私人邀请链接为 `/join/{public_code}#code=<身份码>`：页面读取后清除地址栏，自动 verify，仍需评委确认姓名编号后才 exchange。公共二维码、大屏只含活动码链接。

## 5. 批次范围

| 编号 | 范围 | 验收重点 |
| --- | --- | --- |
| 14a | 依赖、目录、路由懒加载、API 客户端、错误表、类型生成、小数/时钟/轮询/fragment 工具、测试与 lint、CI | 工具单元测试；三模块分包；TS 7 下构建通过 |
| 14b | 登录、活动列表/创建/复制/删除、基本信息/对象/评委/规则编辑、身份码管理与私人邀请、发布检查与发布；后端 G2、G3 | 表单边界与后端一致；凭证只当次展示；发布后只读 |
| 15 | 控制台：对象列表、开评/暂停/恢复/跳过/收评/重开、进度与已交状态、结果核对/公布/无结果、结束/归档、原因确认 | 版本冲突刷新；无代填分入口；未完成结束时定位对象 |
| 16 | 加入、身份确认、等待/评分/提交确认、回执、改分、本人历史、草稿隔离 | 360px；零分与空值；超时核验；旧对象草稿不混用 |
| 17 | 大屏授权管理与展示设置、独立大屏六种模式、主题、全屏、二维码、同步提示 | 1080p；无凭证与管理按钮；仅已公布对象排名 |

## 6. 联调环境

- 默认：后端 `127.0.0.1:8000`，前端 `npm run dev`，Vite 代理 `/api`。登录账号用 CLI 在目标库建立。
- 手机真机（16 起）：`npm run dev -- --host 0.0.0.0`，在 `SCORE_ALLOWED_ORIGINS` 加入 `http://<局域网 IP>:5173`，保持 `SCORE_COOKIE_SECURE=false`；后端仍只监听本机，由 Vite 代理转发。生产 HTTPS 与 Secure Cookie 在 22 验证。
- 前端联调使用远端数据库（用户已确认），会写入测试活动；测试活动建议标题统一加“联调”前缀，便于识别和归档。远端连接受本机网络代理影响，ready 返回 503 时先检查 TLS 握手是否被代理（如 TUN 模式）阻断。
- 远端账号限每小时 36000 条语句（`max_questions`），超限后 503 直至窗口重置；每次快照约 20 条。联调时少开标签页，模拟评委脚本放慢轮询，见 [Review 15](review-15.md)。

## 7. 待确认

- 14b 已提交，见 [Review 14b](review-14b.md)。15 控制台的“重置身份码”入口跳转到设置页评委页签，复用同一对话框。
- 15 控制台与成绩页已完成待 review，见 [Review 15](review-15.md)。成绩页改用管理快照（第 2 节表格已更新）。
- 16 评委手机流程已完成待 review：弹性单列布局，加入/确认/评分/回执/改分/本人历史、持久化提交核验与草稿隔离；113 项前端测试、六种视口的 24 个布局检查通过。浏览器接口为模拟响应，真机与远端联调边界见 [Review 16](review-16.md)。
- 17 只读大屏已完成待 review：控制台授权与展示管理、六种模式、主题/全屏/公共二维码、轮询同步；Flex/Grid 响应式布局与榜单分页。135 项前端测试、60 项浏览器布局检查及模拟接口管理到大屏流程通过，见 [Review 17](review-17.md)。
