#!/usr/bin/env bash
# 从后端应用导出 OpenAPI 并生成前端接口类型；接口变更后在仓库根目录的虚拟环境下运行。
# openapi-typescript 依赖 TypeScript 5 编译器 API，项目使用 TypeScript 7，故在独立 npx 环境中运行。
set -euo pipefail
cd "$(dirname "$0")/.."

../.venv/bin/python - > src/api/openapi.json <<'PY'
import json
import sys

from score_api.core.config import Settings
from score_api.main import create_app

json.dump(create_app(Settings(_env_file=None)).openapi(), sys.stdout, ensure_ascii=False, indent=2)
sys.stdout.write("\n")
PY

npx --yes -p typescript@5.9.3 -p openapi-typescript@7.13.0 \
  openapi-typescript src/api/openapi.json -o src/api/schema.d.ts
