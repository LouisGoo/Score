# Review 04：主办方会话与请求安全校验

日期：2026-10-12。基于已提交的 03（`431d953`）创建并切换到 `dev`，后续开发继续使用该分支。本批保留未提交变更供 review，未 push。

后续状态：认证代码已提交为 `f89b945`，本文为功能完成时的验证记录。用户随后执行远程 04 迁移，已只读核验版本与四张认证表；下文交付边界保留最初批次状态。文件链接已更新至[目录重构](review-auth-refactor.md)后的路径，CLI 改为 `python -m score_api.auth.cli`。

建议 commit message：`feat(auth): 实现主办方会话与请求安全校验`

## 范围与文件入口

- [auth/cli.py](../backend/src/score_api/auth/cli.py)：终端隐藏输入及确认密码、规范化账号、拒绝重复建号；账号与认证审计同事务。没有终端时拒绝降级到回显密码输入，无公开注册接口。
- [security.py](../backend/src/score_api/core/security.py)：标准库 scrypt，N=131072、r=8、p=1、16 字节随机盐、32 字节派生结果；常量时间比较，不存在账号执行同成本计算；单进程同时最多两次计算。不新增第三方依赖。
- [auth/router.py](../backend/src/score_api/auth/router.py)：登录前 CSRF、登录、当前身份与退出；授权依赖已拆至 [dependencies.py](../backend/src/score_api/auth/dependencies.py)，数据库共享限流与认证审计已拆至 [service.py](../backend/src/score_api/auth/service.py)。
- [models.py](../backend/src/score_api/auth/models.py)、[0004_admin_auth.py](../backend/src/score_api/migrations/versions/0004_admin_auth.py)：四张 InnoDB 表，管理员、会话、限流计数及认证审计；Alembic 元数据注册、升级与降级。
- [errors.py](../backend/src/score_api/core/errors.py)、[main.py](../backend/src/score_api/main.py)：精确 Origin 校验、服务端 request_id、422/HTTP/数据库/未知异常脱敏包装、API 禁止缓存；保留原有探测响应体。
- [config.py](../backend/src/score_api/core/config.py)、[.env.example](../backend/.env.example)：可信来源、Secure Cookie、绝对会话期限及限流配置。
- [test_auth.py](../backend/tests/test_auth.py)、[test_auth_mysql.py](../backend/tests/test_auth_mysql.py)：密码、安全边界、真实 MySQL 认证/事务/并发测试；原 MySQL fixture 移入 [conftest.py](../backend/tests/conftest.py) 复用。
- [接口文档](api.md)、[README](../README.md)、[提交计划](commit-plan.md)：调用顺序、建号方法、错误及重试约定、当前进度。

## 关键行为与 review 重点

1. 会话令牌使用 256 位随机值，仅存 SHA-256 摘要。默认 8 小时绝对过期，不滑动续期；每次授权访问读取权威数据库，检查撤销、过期及管理员启用状态。退出后重放旧 Cookie 返回 401。
2. 默认 `__Host-` Cookie，Secure、HttpOnly、SameSite=Strict、Path=/、无 Domain。本机 HTTP 必须显式配置 `SCORE_COOKIE_SECURE=false`，此时使用无前缀的开发 Cookie。页面通过同源 Vite 代理调用，未开放 CORS。
3. 所有非安全方法先校验精确 Origin（拒绝缺失、null、恶意及重复值）。登录前随机双提交 CSRF；登录后 CSRF 与会话绑定。重登轮换令牌并撤销浏览器携带的旧会话；主办方允许多个浏览器，评委单会话规则留待 08。
4. 登录来源默认 30 次/300 秒，账号默认 10 次/300 秒，成功失败均计数。MySQL 事务及行锁保证跨进程计数；先来源后账号加锁，超限在计数提交后返回 429，携带 Retry-After，到期恢复。每次最多清理 100 条过期限流记录。
5. 密码计算在事务外进行，不占用数据库连接；计算后锁定账号并重新检查状态和密码哈希，避免校验期间停用仍建立会话。scrypt 每次约 128 MiB、并行两次，繁忙返回 AUTH_BUSY/503。
6. 建号、登录成功/失败及退出有认证审计；会话状态与相应审计同事务，写入失败全部回滚。Cookie 只在提交后设置/清除；审计不含密码、令牌、CSRF、尝试账号或明文 IP。业务审计将在 06 扩展。
7. 每个响应有服务端 X-Request-ID；错误正文携带相同 request_id，不信任客户端值。422 不回显输入，500/503 不回显 SQL/异常/连接信息。health/ready 的 503 保留原 Readiness 响应体兼容探测。

## 验证命令与结果

WSL Ubuntu、Python 3.10.12、本地独立 MySQL 8.0.46，监听 127.0.0.1:13306；使用名称以 `_test` 结尾的 `score_test`，未使用 SQLite。与 Compose/CI 固定的 8.0.40 存在补丁版本差异；未执行 Docker/远程 CI，不声明已经通过 8.0.40 验证。

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
SCORE_TEST_DATABASE_URL=mysql+pymysql://root@127.0.0.1:13306/score_test ../.venv/bin/pytest -q
../.venv/bin/alembic upgrade head --sql
../.venv/bin/pip check
cd ../frontend
npm run build
cd ..
git diff --check
```

- **149 passed**，无数据库测试跳过。新增 37 项，原有 112 项继续通过。
- Ruff 检查与格式检查通过；pip check 无依赖冲突，依赖锁未变。
- MySQL 空库升级、重复升级、降级再升级、Alembic check、就绪版本切换及其他项目版本表隔离通过。
- CLI 成功建号、随机盐/哈希验证、重复账号不覆盖、确认失败/无终端拒绝通过。
- 正确登录、错误密码/不存在/停用账号统一 401、刷新恢复、跨站登录/退出、缺失/错误/旧 CSRF、会话轮换、过期边界、退出重放、停用后失效通过。
- Secure Cookie 与显式本机 HTTP Cookie 两条路径通过；无公开注册、422/404/405/500/503 响应脱敏和 request_id 通过。
- 两个应用实例共享限流、账号跨来源限制、来源跨账号限制、伪造转发头不改变应用读取来源、六线程竞争仅两次获得账号配额、窗口到期恢复通过。
- 密码计算时连接已归还、计算期间账号停用后拒绝登录、登录审计失败回滚会话、退出审计失败回滚撤销通过。
- 前端 TypeScript/Vite 构建、离线迁移 SQL 生成和 Git 空白检查通过。
- 保留已有 Starlette TestClient 对 httpx 的上游弃用提醒；不影响当前结果。

## 交付边界

- 本批没有应用远程 04 迁移、创建真实主办方账号或修改本地 `.env`；远程数据库仍保持此前基线。运行新认证前需在选定目标库显式执行 `alembic upgrade head`。
- 前端登录页在 14，活动 owner 权限在 05，评委会话在 08，生产代理/TLS/结构化日志/容量验证在后续提交。
- 部署方必须限制 Uvicorn 可信代理来源；本机直连可用 `--no-proxy-headers`，不能无条件信任公网转发头。共享 IP 的主办方登录预算可配置，不能直接沿用到后续评委兑换。
- 不自动删除过期会话或审计；清理保留策略在 24 实现。04 降级会删除本批认证表，只用于可丢弃测试库或经确认的数据回退。
