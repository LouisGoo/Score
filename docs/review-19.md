# Review 19：断线重连与轮询状态恢复

状态：开发与本地验收完成，保留未提交变更，交用户 review。前置工作 18 已提交为 `8996848`；本批没有新增迁移，没有 push 或操作远端数据库。

建议 commit message：`feat(web): 实现断线重连与轮询状态恢复`。

## 行为与入口

- `frontend/src/lib/realtime.ts`：三角色共用恢复状态机。连接成功后缓冲事件并读取新快照，按版本忽略重复/旧消息，合并突发刷新；跳号、重连、前台恢复触发同步。30 秒轻量校对覆盖最后一条通知丢失，45 秒心跳看门狗发现无声断线。
- `frontend/src/lib/useRealtime.ts`：React Query 接入、身份键隔离、前后台/网络事件、一次性票据、首帧认证。连接建立前已开始的查询完成后仍重新取快照，避免使用旧读视图；过时票据响应不能覆盖新连接。
- `frontend/src/admin/control/data.ts`、`frontend/src/judge/data.ts`、`frontend/src/screen/data.ts`：控制台、手机、大屏接入；断线默认 5 秒抖动轮询，失败退避，尊重 Retry-After。成绩记录静态页面保留原刷新语义。评委恢复不发送评分请求，授权失效清理当前身份并回到活动加入页。
- `backend/src/score_api/realtime/router.py`：新增 GET `/api/v1/realtime/version`，每次查授权及角色版本，Redis 不可用时仍可使用。OpenAPI 与前端类型已同步。
- `backend/src/score_api/snapshots/cache.py`、`snapshots/router.py`：逐次授权和版本检查后短时缓存，1 秒 TTL、128 项、有界并发合并；等待回源不占数据库连接。个人数据按身份/会话隔离，大屏公共内容可跨有效授权共享，授权校验结果不缓存。

Vite 已支持 WebSocket 代理。运行 API、Redis、worker 后，控制台/评委/大屏使用实时通知；Redis 不可用时通过 HTTP 恢复。部署反向代理的 WS 升级配置仍属工作 22。

## 验收证据

在本地独立 MySQL 8 测试库与 Redis 7.4.2 上完成，未使用远端业务库。

| 检查 | 结果 |
| --- | --- |
| 后端完整 pytest | 347 passed；包括真实双 API 进程实时投递及既有业务回归 |
| 随后补充的大屏跨授权缓存/撤销用例 | 1 passed；与上述用例不重复，共 348 项 |
| 前端完整 Vitest | 12 个文件、144 passed |
| 前端 TypeScript / Oxlint / 生产构建 | 全部通过 |
| 后端 Ruff 检查与格式 | 通过 |

复验命令（仓库根目录，WSL/Linux）：

```bash
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
cd backend
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test SCORE_TEST_REDIS_URL=redis://127.0.0.1:16379/15 ../.venv/bin/pytest -q
cd ../frontend
npm test
npm run typecheck
npm run lint
npm run build
```

测试库必须专用，迁移测试会重建结构。日志保存在本地忽略目录 `.tools/19-full-backend.log`、`19-public-cache.log`、`19-front-tests.log`、`19-build.log`。

## 建议 review 顺序

1. `realtime.test.ts`：连接/读快照交错、跳号与重复、最后事件丢失、反复建连失败不饿死轮询、Retry-After、后台恢复、撤销、迟到票据、心跳超时。状态机只读恢复，不重放评分。
2. `screen/pages.test.tsx`：通过模拟 WebSocket 验证真实 hook 的 ready 后刷新、通知同步和撤销清屏；既有评委测试覆盖失效跳转、草稿清理及不跨身份重放评分。
3. `test_snapshot_cache.py` 与 `test_snapshot_cache_mysql.py`：12 个并发读取合并、拷贝隔离、TTL/容量/失败、角色与身份隔离、命中缓存后的撤销、跨大屏授权共享、轻量版本 SQL 及无 Redis 降级。
4. `snapshots/router.py` 与 `realtime/service.py`：确认所有缓存命中前均重新校验权限，版本接口使用对应角色版本，不泄露评分。

## 验证边界

前端 WebSocket 恢复测试使用受控模拟，后端跨进程投递使用真实 API/MySQL/Redis；本批未声称完成真实手机弱网或正式并发负载验收。这些记录留给工作 21、23。缓存按 API 进程合并，不能据此推断远端 SQL 配额达标。

构建仍提示部分包超过 500 kB；后端仍有 Starlette/httpx 弃用提示，页面测试仍有 jsdom 伪元素样式提示，均未导致失败。
