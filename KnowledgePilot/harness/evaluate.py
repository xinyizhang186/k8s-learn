import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.engine import agent  # noqa: E402


def load_cases() -> list[dict]:
    with (ROOT / "harness" / "cases.jsonl").open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


async def evaluate() -> dict:
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for case in load_cases():
        started = time.perf_counter()
        result = await agent.run(case["query"], session_id="harness")
        latency = (time.perf_counter() - started) * 1000
        await asyncio.sleep(1)
        returned = {citation.doi.lower().replace("https://doi.org/", "") for citation in result.citations if citation.doi}
        expected = {doi.lower().replace("https://doi.org/", "") for doi in case["expected_dois"]}
        rank = next((index for index, citation in enumerate(result.citations, 1) if citation.doi and citation.doi.lower().replace("https://doi.org/", "") in expected), None)
        citation_hit = bool(rank) if expected else (not result.citations if not case.get("must_cite", False) else bool(result.citations))
        answer_required = case.get("answer_must_include", [])
        answer_hits = [term for term in answer_required if term.lower() in result.answer.lower()]
        answer_fact_score = len(answer_hits) / len(answer_required) if answer_required else 1.0
        hit = citation_hit and answer_fact_score == 1.0 and result.intent == case["intent"]
        rows.append(
            {
                "id": case["id"],
                "hit": hit,
                "citation_hit": citation_hit,
                "answer_fact_score": round(answer_fact_score, 4),
                "answer_hits": answer_hits,
                "rank": rank,
                "latency_ms": round(latency, 2),
                "intent": result.intent,
                "expected_intent": case["intent"],
                "tool_selection_correct": result.intent == case["intent"],
                "citations": len(result.citations),
                "cache_hit": result.cache_hit,
                "iterations": result.iterations,
                "judge_verdict": result.judge_verdict,
            }
        )
    # 同一查询重复执行一次，测量热缓存是否真正生效。
    if load_cases():
        await agent.run(load_cases()[0]["query"], session_id="harness-cache-probe")
    latencies = [row["latency_ms"] for row in rows]
    sorted_latency = sorted(latencies)
    p95_index = min(len(sorted_latency) - 1, max(0, int(len(sorted_latency) * 0.95) - 1))
    retrieval_rows = [row for row in rows if row["rank"] is not None]
    mrr = sum(1 / row["rank"] for row in retrieval_rows) / len(retrieval_rows) if retrieval_rows else 0
    no_result_rows = [row for row in rows if row["id"].startswith("no-result")]
    expected_retrieval_rows = [row for row in rows if row["expected_intent"] in {"paper_search", "paper_detail", "evidence_qa"} and row["citations"] > 0]
    return {
        "started_at": started_at,
        "case_count": len(rows),
        "task_success_rate": round(sum(row["hit"] for row in rows) / len(rows), 4) if rows else 0,
        "recall_at_5": round(sum(row["citation_hit"] for row in expected_retrieval_rows) / max(1, len(expected_retrieval_rows)), 4) if rows else 0,
        "mrr": round(mrr, 4),
        "answer_fact_score": round(sum(row["answer_fact_score"] for row in rows) / len(rows), 4) if rows else 0,
        "citation_presence_rate": round(sum(row["citations"] > 0 for row in rows) / len(rows), 4) if rows else 0,
        "refusal_precision": round(sum(row["hit"] for row in no_result_rows) / len(no_result_rows), 4) if no_result_rows else 0,
        "tool_selection_accuracy": round(sum(row["tool_selection_correct"] for row in rows) / len(rows), 4) if rows else 0,
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "p95_latency_ms": round(sorted_latency[p95_index], 2) if latencies else 0,
        "cache_hit_rate": round(agent.papers.cache.hit_rate, 4),
        "judge_rejection_rate": round(sum(1 for r in rows if r["judge_verdict"] == "reject") / len(rows), 4) if rows else 0,
        "avg_iterations": round(sum(r["iterations"] for r in rows) / len(rows), 2) if rows else 0,
        "rows": rows,
        "note": "结果由当前网络、OpenAlex/Crossref 响应和本机环境实时测得。",
    }


def main() -> dict:
    report = asyncio.run(evaluate())
    output = ROOT / "harness" / "reports"
    output.mkdir(exist_ok=True)
    target = output / "latest.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    main()
