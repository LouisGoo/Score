# 在线打分系统

为固定评委的比赛、答辩和项目评审提供主持人控制台、手机评分与只读大屏。

目前交付 **02：十进制评分核心**。已有前端开发预览、后端存活检查及独立的评分纯函数；登录、数据库、评分 HTTP 流程与大屏业务尚未实现。

- [需求与架构设计](./docs/在线打分系统-产品需求与架构设计.md)
- [接口文档与业务约定](./docs/api.md)
- [逐次 commit 计划](./docs/commit-plan.md)
- [当前 review 说明](./docs/review-02.md)

## 环境与目录

推荐在 WSL/Linux 中开发：Python 3.10、Node.js 24、npm、Git。
Python 锁文件在 Python 3.10 下生成，CI 使用相同版本；升级 Python 时应重新解析依赖并 review。
初始化批次无需 MySQL/Redis。后续采用 MySQL InnoDB（权威数据）和 Redis（通知）。

```text
backend/src/score_api/   FastAPI 应用
                        scoring.py 为独立评分核心
backend/tests/          后端测试
frontend/src/           React 页面
docs/                   开发与 review 文档
```

## 本地启动

以下命令均在 WSL/Linux bash 执行。首次安装：

```bash
python3 -m venv .venv
cd backend
../.venv/bin/python -m pip install -r requirements.lock
../.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
cd ../frontend
npm ci
```

如果 Ubuntu 提示缺少 ensurepip，先安装匹配 Python 版本的 venv 系统包。
本次工作目录已准备好项目虚拟环境，无需重复创建；不依赖全局 Python 包。

终端一（从仓库根目录）：

```bash
cd backend
../.venv/bin/uvicorn score_api.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

终端二（从仓库根目录）：

```bash
cd frontend
npm run dev
```

打开 http://localhost:5173 。Vite 将 /api 转发至 127.0.0.1:8000，页面会显示连接状态。
如果端口被占用，可将后端启动参数改为 `--port 18000`，并用 `SCORE_API_PROXY=http://127.0.0.1:18000 npm run dev -- --port 15173` 启动前端，然后访问 http://localhost:15173 。

API 文档：http://localhost:8000/docs 。本地服务默认仅监听本机，手机访问将在部署批次配置。

`GET /api/v1/health/live` 返回 `{"status":"ok"}`，仅代表 API 进程存活，不能作为数据库就绪或评分可用的证明。
就绪检查随数据库接入实现；业务服务不可用时不会靠存活接口判断提交成功。

## 验证

从仓库根目录：

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/ruff format --check .
../.venv/bin/pytest -q
cd ../frontend
npm run build
```

CI 执行相同检查。构建已含 TypeScript 检查。
前端使用 package-lock.json 和 npm ci；后端使用 requirements.lock 固定依赖。
新增后端依赖时更新 pyproject.toml，在干净环境重新生成锁文件；保留与项目 editable 安装隔离的固定依赖列表。

## 评分核心

`score_api.scoring` 提供 `Criterion`、`ScoringRule`、`personal_total`、`aggregate` 和 `rank_results`。
分数、满分、步长及权重传入十进制字符串或 `Decimal`，权重按 0～1 配置且合计为 1；拒绝 float、空值及 NaN/Infinity。
汇总从原始维度分重新计算，保留各评委原始分和去极值标记；未达到 K 份时 `final_score=None`。
最终成绩按 `ROUND_HALF_UP` 保留两位小数，已公布成绩按 1、2、2、4 并列排名。
本模块无需数据库或 HTTP 服务；完整调用示例、数值约定与验收证据见 [Review 02](./docs/review-02.md)。

真实数据库密码、会话密钥和个人身份码不得写入前端、源码或日志。
.env 已被 Git 忽略，.env.example 只放示例配置。
生产部署、数据库连接预算与权限按需求稿及后续提交逐步落地。

参考：[Vite 官方指南](https://vite.dev/guide/)、[FastAPI 官方入门](https://fastapi.tiangolo.com/tutorial/first-steps/)。
