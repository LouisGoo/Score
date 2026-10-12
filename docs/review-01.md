# Review 01：工程初始化

建议提交：`chore: 初始化前后端工程`

状态：实现及本地验证完成，等待用户 review；尚未创建 commit，未配置远程或 push。
需求设计原稿保持不变，可随首次提交纳入版本管理。

## 本次范围

- 初始化 main 分支 Git 仓库、忽略规则、统一换行和缩进。
- 记录 24 个 commit 的范围、依赖顺序和验收重点。
- backend：FastAPI 工厂、环境配置、存活端点、OpenAPI、单项接口测试。
- frontend：React + TypeScript + Vite 开发预览页、API 连通检查、5 秒超时及手动重试、窄屏布局。
- 固定前后端依赖；GitHub Actions 运行后端检查与前端构建。
- 运行说明包含 WSL/Linux 安装、启动、检查命令。
- [接口文档](api.md)：记录已实现存活接口，单独标注规划中的认证、权限、幂等、错误与实时协议；README 提供入口，后续接口提交同步维护。

## 建议 review 顺序

1. [开发计划](commit-plan.md)：范围和节奏是否符合你的预期。
2. [README](../README.md)：本地开发是否清晰。
3. [后端入口](../backend/src/score_api/main.py) 与 [配置](../backend/src/score_api/core/config.py)：应用工厂、存活接口边界。
4. [前端页面](../frontend/src/App.tsx) 与 [代理配置](../frontend/vite.config.ts)：连通检查、取消请求、失败重试。
5. [CI](../.github/workflows/checks.yml) 和依赖锁文件：验证与安装是否可复现。

## 验证记录

日期：2026-10-10。环境：Ubuntu 22.04 / Python 3.10.12 / Node 24.21.0。

| 检查 | 结果 |
| --- | --- |
| 后端按 requirements.lock 安装及 editable 安装 | 通过 |
| pip check | 通过 |
| ruff check . | 通过 |
| ruff format --check . | 4 个文件通过 |
| pytest -q | 1 passed，无告警 |
| npm ci | 通过 |
| npm run build（含 TypeScript 检查） | 通过 |
| 实际启动 API + Vite，访问页面、健康接口、代理和 OpenAPI | 通过，使用临时空闲端口，结束后关闭测试进程 |
| .venv、node_modules、backend/.env 的忽略规则 | 通过 |

GitHub Actions 已配置，尚未在远程执行。未进行浏览器视觉验收或手机实机验证；当前仅为初始化页面。
MySQL、Redis、登录、评分、数据持久化尚未实现，存活接口的成功不代表系统已经可用于正式评分。

## 本地环境说明

默认端口在当前机器上存在占用，联调使用空闲端口。README 提供端口覆盖示例。
WSL 原先缺少 pip/ensurepip；本次仅在仓库 .venv 内安装工具和依赖，未修改系统 Python 包。

## 下一批

02：Decimal 评分核心，覆盖多维加权 87.00、去极值 90.00、最低份数、稳定剔除、输入步长及并列排名。
