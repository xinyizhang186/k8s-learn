"""面试演示预热脚本：预缓存经典查询结果到本地 DB，API 限流时自动回退。"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.engine import agent  # noqa: E402
from app.db.database import init_db, list_local_papers  # noqa: E402


DEMO_QUERIES = [
    ("attention is all", "paper_search", 8),
    ("BERT pre-training of deep bidirectional transformers", "paper_search", 8),
    ("CNN相关论文", "paper_search", 8),
    ("请详细介绍 CNN的原理分析。", "concept_qa", 5),
    ("请介绍 Attention Is All You Need 这篇论文提出的方法，详细从原理分析。", "evidence_qa", 5),
    ("比较 Attention Is All You Need 和 BERT pre-training", "compare", 5),
]


async def warmup() -> None:
    init_db()
    print("=== KnowledgePilot 演示预热 ===\n")

    for i, (query, intent, top_k) in enumerate(DEMO_QUERIES, 1):
        print(f"[{i}/{len(DEMO_QUERIES)}] 预缓存: {query[:50]}...")
        try:
            result = await agent.run(query, session_id="warmup")
            print(f"  intent={result.intent}, citations={len(result.citations)}, "
                  f"judge={result.judge_verdict}, latency={result.latency_ms:.0f}ms\n")
        except Exception as exc:
            print(f"  失败（不影响后续）: {exc}\n")

    papers = list_local_papers()
    print(f"=== 预热完成 ===")
    print(f"本地数据库已缓存 {len(papers)} 篇论文")
    print(f"面试演示时即使 API 限流，系统也能返回缓存结果。")


if __name__ == "__main__":
    asyncio.run(warmup())
