# 小范围生产部署（22）

本批只提供基础错误日志，不部署指标平台、链路追踪或告警系统。开发和验证无需购买服务器；正式使用时可选择院内 Linux 主机，MySQL 可以在已有院内数据库或独立实例运行，不要求购买云数据库。

## 文件与前提

- 使用根目录 `compose.production.yaml`，不要与开发 `compose.yaml` 合并。
- 主机安装 Docker Engine 与 Compose v2，能够访问 MySQL。域名解析到主机并开放 HTTPS 443。
- 生产仅一个 API 进程、一个 worker：连接预算分别为 10、2。迁移额外短连接，维护时执行；不要直接增加 API 副本。
- Docker 网络为 `172.30.22.0/24`，Nginx 固定 `172.30.22.10`，API 只信任此代理。若与院内路由冲突，同时修改 Compose 子网/地址与 backend/Dockerfile 信任地址。
- API、Redis 不发布主机端口。Nginx 覆盖转发头，保留真实客户端 IP 供限流使用。
- 内网也使用客户端信任的 HTTPS 证书；公网证书或院内 CA 均可。证书签发、续期和实际域名接入需在目标环境完成。

## 准备配置

```sh
cp infra/.env.example .env.production
chmod 600 .env.production
mkdir -p infra/tls/web infra/tls/mysql
```

编辑 `.env.production`：

- `PUBLIC_BASE_URL`：真实 HTTPS origin，无路径、尾斜线、查询或 fragment，例如 `https://score.example.org`。Compose 用它生成唯一可信 Origin，并作为前端构建参数生成二维码/邀请链接。更换域名后需重建 web 镜像。
- `DATABASE_URL`：真实 MySQL 地址，用户名密码特殊字符须 URL 编码。示例启用 CA 和服务器身份验证；将提供方 CA 放到 `infra/tls/mysql/mysql-ca.pem`。不要用关闭证书验证的方式处理连接失败。
- `SCORE_CREDENTIAL_HMAC_KEY`：用 `python -c 'import secrets; print(secrets.token_hex(32))'` 生成并安全保存。更换会影响既有身份码验证；所有 API/worker 使用同一值。

将站点证书链与私钥分别放到 `infra/tls/web/fullchain.pem`、`privkey.pem`。API 只挂载 MySQL CA 目录，不接触站点私钥。真实配置和证书已从 Git 与 Docker 构建上下文排除。后端生产启动会拒绝 HTTP、关闭安全 Cookie、来源不一致或缺少必要配置。

## 构建与启动

以下命令都在项目根目录执行。迁移会写入指定数据库；正式库先备份并确认目标，再由维护者执行。应用启动不自动迁移。

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml build
docker compose --env-file .env.production -f compose.production.yaml run --rm --no-deps web nginx -t
docker compose --env-file .env.production -f compose.production.yaml run --rm migrate
docker compose --env-file .env.production -f compose.production.yaml up -d api worker redis web
```

管理员建号沿用 README 的交互 CLI，可通过 `docker compose --env-file .env.production -f compose.production.yaml exec api python -m score_api.auth.cli` 调用，按 CLI 帮助传入登录名。不要把密码放进命令参数。

## 验收

- `https://你的域名/api/v1/health/live` 返回 200 只表示进程存活。
- `/api/v1/health/ready` 检查 MySQL 和迁移版本：成功 200，故障或迁移不符 503。容器健康检查只调用 live，避免周期探测消耗数据库配额；就绪接口由部署验收手动调用。
- 刷新主办方、评委、大屏深层链接，页面正常；未知 `/api/` 返回 API 错误，不能回退 HTML；缺失 `/assets/` 返回 404。
- 登录后的 Cookie 应带 Secure、HttpOnly；真实域名提交通过，其他 Origin 被拒。
- 登录后建立 WebSocket，确认 101 升级及消息同步；停止 Redis 时评分 HTTP 仍可用、前端回退轮询；恢复后重新获取一次性票据。Redis 数据可丢弃，outbox 在 MySQL 中保留并重投。
- TLS 仅允许 1.2/1.3。只发布 443，用户必须使用 HTTPS 链接；未提供 HTTP 跳转。
- 证书更新后先运行 `exec web nginx -t`，再 `exec web nginx -s reload`（前面补同一 Compose 命令）。

## 基础错误日志

```sh
docker compose --env-file .env.production -f compose.production.yaml logs --tail=100 api worker web
```

API 5xx 记录时间、请求编号、状态；异常另记录类型与代码位置，不包含异常正文、SQL 参数、请求路径/查询、请求正文、Cookie 或令牌。用响应 `X-Request-ID` 对照错误记录。worker 保留既有收评/扫描失败日志。普通成功请求、业务 4xx 不记日志。

Nginx 仅记录 5xx 的时间、状态与上游请求编号（上游未响应时为空）。原生运行时 error log 会包含带票据的请求 URL，因此禁用，配置/证书问题通过 `nginx -t` 和容器退出状态检查。每个容器日志限制为 3 个 5MB 文件；Redis 的少量生命周期日志保留。无需额外日志服务。

本批不代替 23 的容量与故障演练，也不代替 24 的备份恢复手册。正式服务器上的镜像构建、证书信任、真实域名和 MySQL TLS 必须实测后才能判定可上线。
