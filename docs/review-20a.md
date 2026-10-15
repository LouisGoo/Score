# Review 20a：成绩与审计 CSV 导出接口

状态：开发、自查与本地验收完成，按用户授权独立提交。无数据库迁移。

## 实现与自查

- `backend/src/score_api/exports/router.py`：GET `/api/v1/events/{event_id}/exports/{kind}`，三种类型、显式未公布参数、中文下载名、二进制 CSV 契约与统一 JSON 错误。
- `exports/service.py`：活动拥有者校验与单一无锁读视图；复用页面的冻结结果/排名读取，保留评分历史，区分当前有效版本、快照采用版本、重开后的历史收评及缺交；零分与空分分开。
- 汇总/明细默认只有已公布任务，包含未公布时逐行标注；审计的任务记录遵循相同过滤，活动级记录保留并明确标记。
- 审计采用白名单元数据，覆盖开评、暂停、收评、补评、公布、改分、凭证重置及生命周期；不导出凭证、令牌、哈希、HMAC 或完整 before/after。
- UTF-8 BOM、CRLF、标准 CSV 引号转义；危险前缀（含空白/控制符、全角触发符）加单引号。文件名清理路径/控制字符。
- API 文档、OpenAPI 和 TypeScript 生成文件已同步。路由总数契约断言从 29 更新到 30。

自查重点：查询均限定活动；认证在生成文件前执行；数据库读视图覆盖活动版本、过滤、结果和审计；采用版本的原始分/总分/剔除标记直接读冻结快照。不会以最新评分缓存重新计算已公布成绩。

## 验收

本地独立 MySQL 8 + Redis 7.4.2，未操作远端业务库。

| 检查 | 结果 |
| --- | --- |
| 全量后端 | 367 passed；唯一失败为新增端点后的原有错误响应/接口数量契约，已修正 |
| 修正后事件契约、CSV 单元与 OpenAPI 定向复验 | 40 passed；连同全量已通过项，368 项均有通过证据 |
| 新增 CSV 验收 | 20 项通过，含 7 项真实 MySQL 接口测试 |
| 现有前端 | 148 passed；类型、lint、生产构建通过 |
| Ruff 与差异检查 | 通过 |

新增验收覆盖默认空结果、显式未公布、缺交、零分、改分、重开、再次收评及归档；冻结结果/页面排名一致；多维加权、同极值稳定剔除；跨主办方与评委拒绝、退出失效、草稿及非法参数；敏感字段和跨活动数据隔离；中文/引号/换行/前导零与公式注入；导出中途公布仍保持同一读视图。

```bash
cd backend
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test SCORE_TEST_REDIS_URL=redis://127.0.0.1:16379/15 ../.venv/bin/pytest -q
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
cd ../frontend
npm run gen:api
npm test
npm run lint
npm run build
```

日志位于忽略目录 `.tools/20a-full-tests.log`、`20a-front-tests.log`、`20a-build.log`。浏览器下载交互与前后端联调由 20b 交付。内存生成 CSV 适用于当前 P0 规模，未声明通过大规模导出负载测试。现有 Starlette/httpx 弃用提示和前端 chunk 大小提示不影响本次检查。
