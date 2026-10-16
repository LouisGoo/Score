"""构造白名单部署目录，避免上传 .env、备份、测试数据和本地工具凭据。"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".tools" / "cloudbase-build"
if DEST.exists():
    raise SystemExit(f"部署目录已存在，请检查后移走再重建：{DEST}")
DEST.mkdir(parents=True)
(DEST / "backend").mkdir()
for name in ("requirements.lock", "pyproject.toml", "alembic.ini"):
    shutil.copyfile(ROOT / "backend" / name, DEST / "backend" / name)
for path in (ROOT / "backend" / "src").rglob("*.py"):
    if path.is_symlink():
        raise SystemExit("拒绝打包符号链接")
    target = DEST / path.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
shutil.copyfile(ROOT / "infra" / "cloudbase" / "Dockerfile", DEST / "Dockerfile")
print(DEST)
