# CloudBase 连接检查

检查时间：2026-10-26 14:43（Asia/Shanghai）。本次使用 HTTPS GET 只读请求，未登录业务账号，未修改云配置、数据库或部署。

## 环境与结论

[项目配置](../.cloudbase/project.json)指向国内站、上海 `ap-shanghai`、环境 `lytfree-d0gbqrris2c23bd09`，与[部署文档](cloudbase-deployment.md)一致。

后端公网接口可访问，应用报告数据库及迁移就绪。前端静态文件存在，但默认域名返回附件下载头，且同源 API 返回 404；当前默认域名尚不具备完整业务使用条件。

## 实测证据

后端：[score-api](https://score-api-329551-4-1320806380.sh.run.tcloudbase.com)。
前端：[score-web](https://score-web-lytfree-d0gbqrris2c23bd09.webapps.tcloudbase.com)。

| 入口 | HTTP | 结果 |
| --- | --- | --- |
| 后端 `/api/v1/health/live` | 200 | `{"status":"ok"}` |
| 后端 `/api/v1/health/ready` | 200 | `{"status":"ok","database":"ready"}` |
| 后端 `/api/v1/auth/me`（未登录） | 401 | 错误码 `SESSION_EXPIRED`，符合预期 |
| 前端 `/` | 200 | HTML 标题为“在线打分系统”，但 `Content-Disposition: attachment` |
| 前端 `/api/v1/health/ready` | 404 | 返回 HTML，未到达后端健康接口 |

后端三个响应均为 `application/json`，也带 `Content-Disposition: attachment`。前端两个响应为 `text/html`。

按仓库[健康接口实现](../backend/src/score_api/main.py)及[数据库检查实现](../backend/src/score_api/db.py)，ready 检查数据库连通与迁移版本；它不证明 Redis、worker、WebSocket 或完整登录评分链路正常，也不能直接证明运行中镜像与本地代码完全一致。

## 管理连接与检查边界

本次会话没有可用的 CloudBase 管理工具，本机 PATH 中也未找到 `cloudbase` / `tcb` CLI。`.cloudbase/project.json` 仅证明项目指定了目标环境，不代表管理端已登录。

因此本次未直接查询腾讯云控制面，未复核运行版本、实例数、VPC、MySQL 账号授权、环境变量或自定义域名绑定；2026-10-16 的这些信息仍作为历史部署记录保存。数据库结论来自公网应用的 ready 响应，未直接建立 MySQL 管理连接。

## 后续处理

1. 依据[部署文档](cloudbase-deployment.md)完成正式自定义域名、HTTPS 及同源 `/api` 转发，并同步 `PUBLIC_BASE_URL` 和 `SCORE_ALLOWED_ORIGINS`。
2. 在正式域名复查首页正常展示、`/api/v1/health/ready` 返回 JSON 200、前端深层路由刷新正常。
3. 使用已授权的 CloudBase 管理连接复核单实例、VPC、运行版本、数据库权限及可信代理配置。
4. 按[上线检查单](go-live-checklist.md)完成主办方登录、评分、收评、WebSocket、导出与实机验收。

## 复查命令

以下命令不携带凭据，仅访问公开健康接口和静态首页。从仓库根目录或任意终端执行：

```bash
curl --connect-timeout 10 --max-time 30 -i https://score-api-329551-4-1320806380.sh.run.tcloudbase.com/api/v1/health/live
curl --connect-timeout 10 --max-time 30 -i https://score-api-329551-4-1320806380.sh.run.tcloudbase.com/api/v1/health/ready
curl --connect-timeout 10 --max-time 30 -I https://score-web-lytfree-d0gbqrris2c23bd09.webapps.tcloudbase.com/
curl --connect-timeout 10 --max-time 30 -i https://score-web-lytfree-d0gbqrris2c23bd09.webapps.tcloudbase.com/api/v1/health/ready
```

首页复查命令使用 HEAD 查看响应头；本次表格中的首页状态来自 GET。每次复查同时核对状态码、Content-Type、Content-Disposition 和响应内容，不能仅凭域名可达或 HTTP 200 判断业务可用。
