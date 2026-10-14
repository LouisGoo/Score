import json
from pathlib import Path

from score_api.core.config import Settings
from score_api.main import create_app

FRONTEND_SCHEMA = Path(__file__).parents[2] / "frontend" / "src" / "api" / "openapi.json"


def test_frontend_openapi_matches_backend():
    # 前端类型由该文件生成；接口变更后在 frontend 目录运行 npm run gen:api 并一并提交。
    committed = json.loads(FRONTEND_SCHEMA.read_text(encoding="utf-8"))
    assert committed == create_app(Settings(_env_file=None)).openapi()
