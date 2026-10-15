# Review 09：评分任务控制与并发锁

日期：2026-10-13。按用户授权自行开发、验收、本地提交，并更新远端数据库；不 push。

## 交付

- `rounds/router.py`、`schemas.py`、`service.py`：拥有者查询任务，开评/暂停/恢复/跳过；写请求校验 Origin、CSRF 与任务 expected_version。跳过仅限 PENDING 且必须填写原因。
- 活动锁 → 任务锁；锁内检查版本、状态与当前时间。首次开评将 READY 活动变为 RUNNING；任务及活动版本递增，与完整前后状态审计同事务。
- 使用发布快照的时限。暂停保存 Decimal 秒（6 位小数）并清空截止时间；恢复用精确微秒重建截止时间。不限时的时钟字段保持 null；到期后不能暂停延长窗口。
- `0009_round_controls`：截止与剩余时长字段、OPEN/PAUSED 共用生成列唯一约束、到期扫描索引。后续收评/重开沿用相同锁顺序。

## 验收

WSL、Python 3.10、本地 MySQL 8.0.46，独立 `127.0.0.1:13306/score_test`。完整后端 **251 passed**；09 专项 8 项，含真实 InnoDB 并发、锁等待与时间推进。Ruff lint/format、前端 TypeScript/Vite、空库升级/重复升级/降级再升级、Alembic check 均通过。仅保留既有 Starlette/httpx 弃用提醒。

- AT-04 后端：任务正确开评，活动 RUNNING，客户端可查询任务版本和服务端时间；手机/大屏随动待前端批次。
- AT-09 后端：不限时、暂停剩余微秒、恢复、新截止、截止相等拒绝；等待任务锁后推进时钟仍拒绝暂停。
- AT-29 当前范围：两个对象并发开评仅一成功；同任务并发恢复仅一成功；直接数据库插入 OPEN + PAUSED 也被唯一约束拒绝。重开属 11。
- 跨 owner 隔离、错误 CSRF、严格整数版本、缺少跳过原因、旧版本冲突及审计失败回滚均覆盖。

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
cd ../frontend
npm run build
```

## 远端同步

远端实际原版本为 `0005_event_drafts`。只读确认项目业务表全部为空后，执行 06～09 增量迁移至 `0009_round_controls`；所有既有表记录数保持一致，旧项目表结构保持不变。Alembic check 无差异，真实远端连接的 `/health/ready` 返回 200。没有写入测试账号、名单或评分，没有修改 `.env`。

完整项目表本地备份方案被自动审批以“敏感数据导出未获具体授权”拒绝，未发生导出。改用经过重新审批的空表断言及增量结构迁移；不把此过程宣称为备份恢复演练。远端迁移核验仅保存表名、记录数、DDL 摘要和版本至被 Git 忽略的 `.tools/remote-0009_round_controls-evidence.json`。

当前配置尚未设置 `SCORE_CREDENTIAL_HMAC_KEY`，正式使用身份码/发布/兑换前仍需配置稳定独立密钥。数据库 ready 仅证明连通与版本一致。收评/结果、worker、角色快照、前端与实时推送按后续计划实现。
