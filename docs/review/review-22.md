# Review 22：生产部署与基础错误日志

## 交付范围

按用户要求，可观测范围缩减为基础错误日志，不增加监控平台、告警、指标采集或链路追踪。

- `compose.production.yaml`：一个 API（10 条连接上限）、一个 worker（2 条）、Redis、Nginx；MySQL 为外部实例，可使用院内已有数据库。迁移为显式 tools profile，不随启动执行。
- `backend/Dockerfile`、`infra/nginx/Dockerfile`：前后端镜像；后端非 root 运行；前端使用锁文件构建。
- `PUBLIC_BASE_URL` 同时决定前端邀请链接和后端可信来源；生产强制 HTTPS/Secure Cookie 与必要配置。
- Nginx HTTPS、SPA/API 分流、缺失资源 404、WebSocket 升级、Docker DNS 重新解析。只公开 443；API 只信任 Nginx 固定 IP。
- API 5xx 脱敏错误日志、request_id、异常类型及代码位置；不保存异常正文、请求数据、SQL 参数。worker/Redis 发布失败有错误记录，订阅连接持续故障仅首条记录，恢复后重新计数。
- 日志每容器 3 × 5MB。Nginx 仅输出不含 URI 的 5xx 日志，禁用可能暴露 WS 票据的原生请求错误日志。
- 沿用既有 live/ready 和 Redis 故障时 HTTP/轮询降级；未变更接口响应、数据库结构或业务规则。

入口：[部署说明](deployment.md)。CI 新增生产 Compose 校验、镜像构建及 Nginx TLS 配置检查。

## 已运行验证（2026-10-15）

- 后端：`cd backend && ../.venv/bin/pytest -q -m "not mysql"`：**228 passed，157 deselected**。其中新增 13 项覆盖生产配置拒绝条件、500/503 请求编号关联、凭证/异常正文脱敏、第三方日志脱敏。
- `ruff check backend infra/nginx/smoke.py`、后端 `ruff format --check`、`git diff --check`：通过。
- 前端：`npm run build`（含类型检查）、`npm run lint`：通过。保留已有大 chunk 提示。
- 系统 PyYAML 解析生产 Compose 与 CI YAML，并核对仅 web 暴露端口、日志轮转、worker/迁移命令、Nginx 固定 IP：通过。这不是 Docker Compose 的运行验证。
- 解包到临时目录的 Nginx **1.18.0**，执行 `infra/nginx/smoke.py`：配置检查、临时自签名 HTTPS、SPA 深层链接、API JSON 404、静态资源 404、WebSocket 升级、上游 502/503、请求编号及查询票据不入日志均通过。测试用模拟上游和临时端口，未连接数据库。
- Nginx 解包验证时有系统默认日志目录不存在提示；临时配置检查及运行均成功，不是目标镜像的运行结果。

## 验收边界

本机无 Docker：尚未执行完整镜像构建、实际 Compose 容器启动及新增 CI job。目标镜像使用 nginx:stable-alpine，与本地解包版本不同，需通过新增 CI 与实际部署的 `nginx -t` 再验证。

未连接或迁移远端数据库；157 项 MySQL 集成测试本批未运行。真实域名、客户端证书信任、MySQL TLS、跨设备访问与 Docker 网络冲突检查留待目标环境验收。23 容量测试与 24 备份恢复仍未完成，不能据此宣称可正式上线。

## Review 重点

1. 子网 `172.30.22.0/24` 是否与院内网络冲突；调整时同步 API 信任代理地址。
2. 配置与证书不进入 Git/镜像，后端只挂载数据库 CA。
3. PUBLIC_BASE_URL 变更需要重建 web，HMAC 密钥需要稳定保存。
4. 5xx 的诊断信息足够且无敏感内容；故障日志能用 X-Request-ID 对照。
5. 保持单 API/worker 的连接预算，迁移与建号在维护时进行。

建议 commit message：`feat(ops): 添加生产部署与基础错误日志`。

变更保留未提交，未 push。实现过程中“信任全部代理”的参数被自动审批拒绝，已采用仅信任固定 Nginx IP 的方案，无待审批阻塞。
