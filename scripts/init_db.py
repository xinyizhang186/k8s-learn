import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.database import init_db  # noqa: E402

init_db()
print("KnowledgePilot 数据库初始化完成")
