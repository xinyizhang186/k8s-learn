import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.llm_service import llm_service  # noqa: E402


async def main() -> None:
    status = await llm_service.status()
    print(status)
    if not status.get("available"):
        print("Ollama 未就绪。请执行：ollama serve，然后执行：ollama pull qwen2.5:7b")


if __name__ == "__main__":
    asyncio.run(main())
