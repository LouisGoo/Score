# Review 18 — 按角色投递已提交的事务事件

范围：outbox 持久化投递、Redis 跨进程订阅、一次性 WebSocket 票据、授权撤销与角色版本。前端恢复接入留在 19。

## 实现入口

- `backend/src/score_api/outbox/service.py`：在业务事务内冻结管理员、大屏及评委个人流版本；开评等原先缺失 outbox 的路径补齐。
- `backend/src/score_api/outbox/worker.py`：有索引的待投递扫描、SKIP LOCKED 领取、30 秒租约、事务外发布、条件确认与失败退避。发布后确认前崩溃会重投相同 ID/版本。
- `backend/src/score_api/realtime/`：按活动分流、每 API 进程一个 Redis 订阅、每连接 64 条有界队列、慢消费者断开、票据原子消费和逐次数据库授权。
- `backend/src/score_api/worker.py`：到期收评和投递在同一进程顺序执行，共享原有 2 条连接预算。
- `0018_realtime`：仅给 outbox 添加租约字段和索引，不改历史评分/回执。

## 协议与 review 重点

票据绑定活动、角色、会话/授权引用和 Origin；默认 30 秒，WS 第一帧兑换，避免代理 URL 日志记录凭证。票据发行和连接都校验当前数据库授权，Cookie 发行接口需要 CSRF。票据、会话明文与评分不进入 Redis 广播。

推送只有白名单变化通知和冻结版本，payload 为空。新提交更新所有流；改分仅管理员与本人；展示设置仅管理员/大屏；授权管理仅管理员。快照仍提供实际数据。管理员退出、评委退出、身份码重置和大屏授权撤销后，通知触发重新校验并断开失效连接；每次发送前与空闲每 30 秒也校验授权。WebSocket 不长期占数据库连接。

多 worker 可重复或乱序投递；客户端需要按版本去重并回源（19）。Redis 发布成功不等于浏览器收到；历史 outbox 缺少冻结版本，仅要求客户端 resync。Redis 故障保留未投递数据，HTTP 提交照常。

## 验证

本地独立 MySQL 8.0 测试库（13306）和 Redis 7.4.2（16379）；未操作远程库。

- 完整后端 **342 passed**（含两个真实 API 进程）；随后补充身份码重置与 outbox 失败回滚定向验收 **1 passed**。迁移往返及 Alembic check 通过，Ruff 检查/格式检查、git diff --check 通过。
- 实时集成覆盖：三角色与私人改分隔离、票据 Origin/CSRF/活动绑定/重放/失效、三角色退出/撤销、租约恢复、重复投递、并发领取、Redis 故障退避。
- 两个真实 Uvicorn OS 进程接收相同已提交通知，验证跨进程传播、重复消息与跨活动隔离。
- Redis 队列满时断开并要求恢复，防止慢连接无限积压。
- 前端 OpenAPI 类型已重新生成；lint、类型检查和生产构建通过。现有大型组件包提示保留。
- 测试夹具新增 AuthAudit 清理；初轮失败遗留数据导致认证测试初始化失败，已在独立测试库迁移重建后重跑，不以跳过方式通过。

复现命令（backend 目录）：设置 `SCORE_TEST_DATABASE_URL` 与 `SCORE_TEST_REDIS_URL` 后运行 `pytest -q`、`ruff check .`、`ruff format --check .`。CI 已增加 Redis 服务。

本批自验通过后本地提交，不 push。建议提交：`feat(realtime): 按角色投递已提交的事务事件`。
