# CloudBase 部署

本部署对应 `cb` 分支、上海国内站环境 `lytfree-d0gbqrris2c23bd09`。
前端采用静态托管，后端使用容器型云托管，数据库采用环境已有的 MySQL 8.0。
现有 SQLAlchemy、事务和 Alembic 迁移保持不变。

## 后端

`infra/cloudbase/Dockerfile` 使用 Python 3.10，与锁文件及 CI 一致。
`python -m score_api.cloudrun` 启动 API、到期收评/outbox worker 和本机 Redis。
任意子进程退出会停止整个实例；平台重启后恢复服务。Redis 仅监听 127.0.0.1，
不持久化，票据与通知允许丢失；评分和待发送事件保存在 MySQL。

本方案必须设置 `MinNum=MaxNum=1`，确保 worker 常驻且 API/worker 共享 Redis。
滚动发布期间浏览器可能重连并重新获取快照；不能依赖 Pub/Sub 补齐消息。
如需多实例，应先改为所有实例共享的 Redis，并重新核算数据库连接预算。
每个实例最多使用 API 10 + worker 2 条连接，滚动发布要计入旧实例。

从仓库根目录运行 `python3 infra/cloudbase/package.py`，生成 `.tools/cloudbase-build`。
脚本只复制 Python 源码、依赖锁文件、构建配置与 Dockerfile，不上传 `.env` 或工具凭据。
该目录作为 `manageCloudRun(action="deploy", serverType="container")` 的绝对 `targetPath`。
服务名使用 `score-api`，非敏感配置参考同目录的 `server-config.example.json`。

服务端注入以下环境变量，切勿写入 Git：

- `SCORE_ENVIRONMENT=production`
- `PUBLIC_BASE_URL`：真实前端 HTTPS origin
- `SCORE_ALLOWED_ORIGINS`：仅包含该 origin 的 JSON 数组
- `SCORE_COOKIE_SECURE=true`
- `DATABASE_URL`：CloudBase MySQL 内网连接，使用专用 `score_app` 账号
- `SCORE_CREDENTIAL_HMAC_KEY`：稳定随机密钥，必须保留备份
- `SCORE_TRUSTED_PROXY_IPS`：仅当平台代理来源已经核实时设置；禁止 `*`

未配置可信代理时 Uvicorn 忽略转发头，以直接连接方为限流来源。
上线前需验证平台代理来源及真实客户端 IP，避免多用户共享代理限流额度。
云托管必须接入数据库所在的 VPC 和子网；数据库不需要开启公网。

当前环境的网络信息是 `vpc-5cucrzze`（`172.17.0.0/16`）、
`subnet-k478dqxr`（`172.17.0.0/20`）。本次部署发现，只提交 VPC/子网 ID
时，工具可能返回成功，但服务和版本的 `VpcConf` 仍为空。必须读取
`queryCloudRun(detail)` 和 `DescribeVersionDetail` 复核实际配置。
遇到此情况，使用官方 `tcbr.UpdateCloudRunServer`，保留现有镜像和配置，
仅通过 `Items` 显式更新网络（`Business=tcb`、`DeployInfo.ReleaseType=FULL`）：

```json
{
  "Key": "VpcConf",
  "VpcConf": {
    "VpcId": "vpc-5cucrzze",
    "VpcCIDR": "172.17.0.0/16",
    "SubnetId": "subnet-k478dqxr",
    "SubnetCIDR": "172.17.0.0/20"
  }
}
```

新环境须重新查询网络信息，不能复制这里的资源 ID。只有健康检查和数据库
连接都通过，才能判断部署成功；平台版本状态 `normal` 本身并不足够。

数据库迁移显式执行，不在容器启动时自动运行。空库可用
`cd backend && ../.venv/bin/alembic upgrade head --sql` 生成 SQL，审核后
通过 CloudBase MySQL 管理接口按顺序执行。非空库先备份并核对当前版本，
只生成当前版本至 head 的增量，不能重复运行初始迁移或使用 stamp 跳过迁移。
运行账号仅需目标库的 SELECT、INSERT、UPDATE、DELETE；迁移走独立管理通道。

## 前端与路由

在 `frontend` 执行 `npm ci`、`npm test`、`npm run build`，产物为 `dist`。
没有固定构建域名时，页面使用当前 origin 生成邀请链接。
保持前端同源 `/api/v1` 调用、安全 Cookie 和 WebSocket 路径。

同一 HTTPS 域名下，静态文件交给托管服务，`/api` 路由交给 `score-api`，
转发时保留原路径。前端 BrowserRouter 的刷新需要 SPA 回退到 `index.html`；
API 路由不能回退到 HTML。不要把前端随意切换为跨站 Cookie 模式。

2026-10-16 实测当前环境的静态默认域名返回 `Content-Disposition: attachment`。
上传成功不代表浏览器可正常打开页面；正式网页访问需绑定平台允许的自定义域名，
完成备案、证书和 DNS 配置后再验收。环境已有 `__auth/`、`cloud-admin/` 文件，
发布时不得清空这些目录。

已发布的静态应用为 `score-web`，默认地址：
<https://score-web-lytfree-d0gbqrris2c23bd09.webapps.tcloudbase.com>。
该系统默认域名同时禁止手工新增 `/api` 路由；因此当前无自定义域名时，
前端产物虽然已发布，同源登录和业务流程仍不能正式验收。
取得已备案域名后，在同一域名配置 `/` → `STATIC_STORE/staticstore`，
`/api` → `CBR/score-api`（`EnablePathTransmission=true`），然后更新后端
`PUBLIC_BASE_URL` 和 `SCORE_ALLOWED_ORIGINS` 为该域名。

## 验收

检查 `/api/v1/health/live` 和 `/api/v1/health/ready`（数据库及迁移版本），
并验证真实域名登录、安全 Cookie、评分提交回执、到期收评、WebSocket 与 CSV 导出。
前端上传、容器构建成功或 live=200 都不能代替完整业务验收。
首次初始化的空库没有主办方账号，需通过现有管理员建号流程创建。

### 2026-10-16 部署记录

- 后端 `score-api-003` 已发布，流量 100%，单实例 0.5 CPU / 1 GiB。
- 后端地址：<https://score-api-329551-4-1320806380.sh.run.tcloudbase.com>。
- `/api/v1/health/live` 与 `/api/v1/health/ready` 均返回 200，后者返回
  `{"status":"ok","database":"ready"}`；MySQL 中也确认了 `score_app` 的连接。
- 数据库初始化到 `0018_realtime`，共 22 张项目表；未导入旧环境业务数据。
- `/auth/me` 和活动列表的未登录请求返回 401，缺失 CSRF 的登录请求返回 403，
  携带有效 CSRF 的不存在账号登录返回 401；Cookie 的 Secure、HttpOnly、
  SameSite=Strict 和 `__Host-` 属性已检查。
- 本地验证：前端 166 项测试通过并构建成功；后端 245 项通过、157 项跳过
  （未提供隔离的数据库集成测试环境），Ruff 检查通过。
- 待完成：自定义域名及同源路由、主办方建号、真实客户端 IP 配置、
  登录到评分/收评/WebSocket/导出的完整业务验收。

SQL 运行账号当前由控制台授予四项全局 DML 权限（`*.*`），未授予 DDL 权限。
正式投入使用前可将权限范围收窄为本项目数据库，避免账号访问将来新增的其他库。
