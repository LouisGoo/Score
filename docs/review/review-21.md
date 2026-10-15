# Review 21：完整评分流程自动化验收

范围：5 评委、3 对象的 API 自动化闭环，跨角色/并发/失败路径补充，AT-01～26/29 证据登记。保留未提交变更供 review；没有新增依赖、业务接口或数据库迁移。

## 实现

`backend/tests/test_workflow_mysql.py` 新增 4 项测试：

- 两种算法（平均分 K=4、去极值 K=5）分别从主办方登录、创建名单/规则、发布、五位评委确认身份，走完三对象评分、暂停恢复、改分与旧版本冲突、提前收评和重开补评、公布、排名、导出、结束及归档。断言 90.00/80.00/80.00、并列 1/2/2、15 份初始评分和 2 份修订、冻结快照 ID、规则版本、审计及归档后原回执。
- outbox 写入失败后，评委与大屏均看不到未提交评分；随后五个独立评委客户端并发提交，原失败 key 可复用，五份回执唯一，人数准确，收评后每个原 key 仍返回原回执。
- 两个独立控制台并发重开不同 CLOSED 对象：恰好一个成功，另一个 ACTIVE_ROUND_EXISTS；只有一个 OPEN，历史收评快照保留。

业务操作均经公开 HTTP 路由；仅主办方测试账号预置密码使用 SQL。复用已有 fixture 的独立 `_test` 库保护、随机实体 ID、关联数据清理及连接池归还断言。每个设备有独立 Cookie jar 与应用实例；并发使用 Barrier，不用定时睡眠猜测执行顺序。

新增测试由已有 CI `pytest -q` 自动发现，不增加重复 CI 作业。断言固定预期结果，不用被测计分函数生成预期值。

## 验证

2026-10-15，本地 WSL、独立 MySQL `127.0.0.1:13306/score_test` 与 Redis `127.0.0.1:16379/15`：

| 检查 | 结果 |
| --- | --- |
| 后端全量（新增前 3 项时） | 371 passed，无跳过，229.73 秒 |
| 最终工作 21 全部测试（含最后补充的并发重开） | 4 passed，19.71 秒；连同全量已有 372 个不同用例的通过证据 |
| 前端全量 | 14 文件，166 passed |
| Ruff lint / 格式 | 全部通过，112 文件格式检查 |
| 前端 Oxlint / TypeScript / Vite 构建 | 全部通过 |
| Git 差异空白检查 | 通过 |

命令（WSL/Linux，仓库根目录）：

```bash
cd backend
export SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test
export SCORE_TEST_REDIS_URL=redis://127.0.0.1:16379/15
../.venv/bin/pytest -q tests/test_workflow_mysql.py
../.venv/bin/pytest -q
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
cd ../frontend
npm run lint
npm test
npm run build
```

本机示例连接仅用于已有隔离测试服务。其他环境使用其专用测试账号；未设置测试连接时 pytest 会跳过数据库测试，不能据此宣称完整验收。完整回归涉及迁移往返，禁止与其他使用同一测试库的作业并行运行。

日志在忽略目录 `.tools/21-backend.log`、`21-workflow.log`、`21-frontend.log`、`21-build.log`。现有 Starlette/httpx 弃用提示、jsdom/Ant Design 提示和大 chunk 构建提示仍保留。

## Review 重点与边界

- [验收证据索引](acceptance-21.md) 逐项标记证据层次；没有把分散的单元测试写成真实终端全流程结果。
- [实机验收记录](device-acceptance.md) 单独维护，iOS/Android/微信均明确待测。
- 本批闭环使用 TestClient + 真 MySQL；前端回归使用 jsdom，未新增浏览器点击全流程。已有真实 Chrome 下载和布局证据见 Review 20b。本批不声明摄像头扫码、移动 OS 后台恢复或微信下载已通过。
- 多进程和 Redis 集成随全量后端复验；生产强制重启/网络中断及容量演练仍归 23，备份恢复归 24。

建议 commit message：`test(e2e): 覆盖完整评分流程`。
