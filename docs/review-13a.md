# Review 13a：快照改为无锁一致性读

2026-10-14，前端开发前的后端修正，已提交（`da44fe6`）。无迁移，不改变 HTTP 路径、字段或错误码。

## 问题

13 的三角色快照对活动行（评委快照另含评委、会话行）加 `FOR UPDATE`，与评分提交、任务控制、收评使用同一把活动锁。18 实时投递前，管理端、评委手机和大屏只能轮询快照；集中评分时轮询与提交串行，超过 3 秒 InnoDB 锁等待即返回 503，读请求也会拖慢评分。

## 修改

- `Database.read_snapshot()`：使用 REPEATABLE READ 的独立会话工厂（同一连接池，归还时恢复 READ COMMITTED）。InnoDB 在首条查询建立读视图，事务内所有查询共用，版本号与进度、评分、结果、排名来自同一已提交状态。
- `admin_snapshot`、`judge_snapshot`、`screen_snapshot` 改用该读视图，不再加行锁。评委快照通过 `lock_principal(..., write=False)` 在同一读视图校验会话撤销、到期与凭证版本；大屏快照在同一读视图校验授权摘要、撤销与到期。
- 写路径（提交、控制、收评、授权、展示设置等）锁顺序与隔离级别不变。

语义变化：并发写事务未提交时，快照立即返回提交前状态，而不是等待后返回提交后状态。撤销、重置提交后的读取立即拒绝；与提交并发的那次读取视为发生在提交之前，与此前锁等待语义的差别只在并发窗口内。

## 验收证据

- 改写 `test_screen_snapshot_skips_held_lock_and_sees_committed_revocation`：另一事务持活动锁且撤销未提交时，大屏快照 2 秒内返回；提交后 401。
- 改写 `test_snapshot_does_not_wait_for_uncommitted_submission`：评分事务持锁且挂起在 outbox 写入时，评委与管理快照均不等待、不见未提交评分；提交后版本 +1、回执和已交数可见。
- 新增 `test_open_snapshot_keeps_one_read_view_without_blocking_writes`：读视图打开期间完成一次 HTTP 评分提交（不被阻塞），视图内两次读取已交数一致；新快照可见。临时将隔离级别改为 READ COMMITTED 时此测试失败，确认其覆盖读视图语义。
- 既有 AT-14/22/23 隔离、重置后旧 principal 拒绝、撤销/过期拒绝等测试保持通过。

全量后端 **313 passed**（190.20 秒），Ruff、格式检查、`git diff --check`、前端构建通过。环境同 Review 13：WSL Python 3.10、本地 MySQL 8.0.46 `127.0.0.1:13306/score_test`。

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
cd ../frontend
npm run build
```

## 边界

远端数据库无需变更。`GET /rounds/{id}/my-ballot` 仍持锁读取，仅用于超时核验，不作轮询接口。轮询请求量仍计入数据库预算，服务端合并回源在 19 实现。
