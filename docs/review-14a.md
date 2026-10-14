# Review 14a：前端基础层

2026-10-14。未提交，等待用户 review。约定依据 [前端开发计划](frontend-plan.md) 第 4 节；用户已确认使用 Ant Design、远端数据库联调，并接受发布后仅改大屏展示字段。

## 范围

- **依赖**（精确版本锁定）：antd 6.6.6、@ant-design/icons 6.3.4、react-router 8.4.0、@tanstack/react-query 5.104.2、big.js 7.0.1；开发依赖 Vitest 5.0.4、jsdom、Testing Library、Oxlint 1.88.0。`package-lock.json` 的下载地址统一为 registry.npmjs.org（本机 npmrc 指向镜像，新增条目已改写，完整性哈希不变），干净 `npm ci` 通过。
- **路由**：需求第 10 节全部路由已注册；首页、admin、judge、screen 各自懒加载为独立分包；`/admin` 重定向到活动列表；未实现页面以占位页标明交付批次；路由错误边界处理分包加载失败。
- **API 客户端**（`src/api/`）：同源 `/api/v1`、`no-store`、15 秒超时；统一解析错误包装（code、message、request_id、Retry-After）；超时/断网标为“结果未知”（status 0）。按身份创建客户端：
  - 主办方：登录前双提交 CSRF → 会话 CSRF，`me` 恢复，退出时无论成功与否清空。
  - 评委：verify/exchange 使用 bootstrap CSRF，兑换后切换为会话 CSRF；bootstrap Cookie 过期时自动重新获取。
  - 大屏：token 仅作 Bearer 请求头，不进入 URL。
  - CSRF 只存内存；仅 `CSRF_INVALID` 自动刷新后重试一次，其他写请求失败不自动重发。
- **错误表**（`errors.ts`）：后端全部错误码映射为处理方式（重新登录/刷新/修正/等待/核验/停止）及提示；优先显示服务端中文消息。
- **查询**：TanStack Query 只对读请求的断网/503 最多重试 2 次，遵守 Retry-After；写操作不重试。缓存键首段为角色并含身份 ID。
- **工具**（`src/lib/`）：个人总分预览与分数校验、服务端时钟偏差与倒计时、带抖动且后台暂停的轮询选项与版本保护、fragment 读取并清除、幂等键（非安全上下文回退）、按活动/评委/任务/规则版本隔离的草稿。
- **类型生成**：`npm run gen:api` 生成 `openapi.json` 与 `schema.d.ts`（TS 5 仅在临时 npx 环境使用）；后端新增 `test_openapi_contract.py` 防止接口与前端类型脱节。
- **CI**：前端任务增加 `npm run lint`、`npm test`。

## Review 重点

- 个人总分预览与后端一致性：采用与 `scoring.py` 相同的通分方式，乘法精确，仅最后一次除法（截断 60 位）后 ROUND_HALF_UP。测试用例的期望值由后端 `personal_total` 实际计算，覆盖 87.00、循环小数 33.33/66.67、浮点易错的 1.005→1.01 和非整权重。
- 错误码覆盖测试扫描后端源码中的 `APIError(状态, "CODE")`；新增错误码未登记时前端测试失败。
- 包体：手机直接打开 `/join` 时加载入口约 114 KB + 共享运行时约 98 KB（gzip，含 React DOM 与 antd 样式运行时）；首页卡片等组件已移出入口。16 实现评分页后需复核。
- TypeScript 7 与 antd、React Router 8、TanStack Query 的类型声明均通过 `tsc --noEmit`。

## 验收证据

```bash
cd frontend
npm ci
npm run lint     # 0 warnings
npm test         # 4 files, 50 passed
npm run build    # 类型检查 + 构建；admin/judge/screen/Home 独立分包
cd ../backend
../.venv/bin/pytest -q tests/test_openapi_contract.py   # 1 passed
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
```

本机开发服务器联调：经 Vite 代理访问 live=200，`/auth/me`、`/judge-sessions/me` 未登录返回 401 `SESSION_EXPIRED`，无 Origin 的写请求返回 403 `ORIGIN_FORBIDDEN`；`/`、`/join/...`、`/admin/events`、`/screen/...` 均返回页面，浏览器中首页及主办方占位页正常渲染。

远端数据库 ready 当时返回 503：TCP 可连通，但 TLS 握手超时，与此前记录的本机代理（TUN）阻断现象一致，属于环境问题；本批页面不访问数据库。14b 联调前需恢复远端连接。

## 边界

不含任何业务页面（14b 起）。WebSocket 接入（18/19）时轮询改为降级通道，客户端接口不变。
