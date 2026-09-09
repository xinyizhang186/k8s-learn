"""Run Naive vs Hybrid vs Agentic RAG comparison on the HotpotQA eval subset.

Memory-safe: gc every N questions + incremental partial writes + supports
--start/--end so the 500-question run can be sharded across processes if the
cgroup memory limit becomes tight.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from src.data_loader import load_corpus, load_eval
from src.retriever import HybridRetriever
from src.pipeline import run_naive, run_hybrid, run_agentic
from src.metrics import exact_match, f1, context_recall, context_precision_at_k

METRIC_KEYS = ["em", "f1", "ctx_recall", "ctx_p@2", "ctx_p@4", "latency"]


def evaluate(result, q):
    return {
        "em": exact_match(result.answer, q.answer),
        "f1": f1(result.answer, q.answer),
        "ctx_recall": context_recall(result.retrieved_titles, q.gold_titles),
        "ctx_p@2": context_precision_at_k(result.retrieved_titles, q.gold_titles, 2),
        "ctx_p@4": context_precision_at_k(result.retrieved_titles, q.gold_titles, 4),
        "latency": result.latency,
        "rounds": result.n_retrieval_rounds,
        "pred": result.answer,
        "gold": q.answer,
    }


def summarize(per_q, modes):
    summary = {}
    for m in modes:
        summary[m] = {k: round(sum(r[m][k] for r in per_q) / len(per_q), 4)
                      for k in METRIC_KEYS}
        summary[m]["avg_rounds"] = round(
            sum(r[m]["rounds"] for r in per_q) / len(per_q), 2)
    by_type = {}
    for m in modes:
        by_type[m] = {}
        for ty in ["bridge", "comparison"]:
            rows = [r for r in per_q if r["type"] == ty]
            if not rows:
                continue
            by_type[m][ty] = {k: round(sum(r[m][k] for r in rows) / len(rows), 4)
                              for k in METRIC_KEYS}
            by_type[m][ty]["avg_rounds"] = round(
                sum(r[m]["rounds"] for r in rows) / len(rows), 2)
    return summary, by_type


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=500)
    ap.add_argument("--modes", default="naive,hybrid,agentic")
    ap.add_argument("--out", default="results/exp.json")
    ap.add_argument("--partial", type=int, default=25,
                    help="write partial json every N questions (resumable)")
    args = ap.parse_args()

    corpus = load_corpus("data/corpus_small.json")
    eval_qs = load_eval("data/eval_500.json")[args.start:args.end]
    print(f"corpus={len(corpus)}  eval=[{args.start}:{args.end}] "
          f"{len(eval_qs)} questions", flush=True)

    retriever = HybridRetriever(corpus, cache_dir="cache")
    print("retriever ready", flush=True)

    modes = args.modes.split(",")
    fns = {"naive": run_naive, "hybrid": run_hybrid, "agentic": run_agentic}

    per_q, traj_examples = [], []
    t0 = time.time()
    for i, q in enumerate(eval_qs):
        row = {"id": q.id, "question": q.question, "gold": q.answer,
               "type": q.type, "gold_titles": sorted(q.gold_titles)}
        for m in modes:
            r = fns[m](q.question, retriever)
            e = evaluate(r, q)
            row[m] = e
            if m == "agentic":
                row[m]["query_variants"] = r.query_variants
                if len(traj_examples) < 8:
                    traj_examples.append({
                        "question": q.question, "gold": q.answer,
                        "pred": r.answer, "type": q.type,
                        "trajectory": [{"thought": s.thought, "action": s.action,
                                         "observation": s.observation}
                                        for s in r.trajectory],
                    })
        per_q.append(row)
        # memory management: gc + incremental partial writes
        if (i + 1) % 5 == 0:
            gc.collect()
        if (i + 1) % args.partial == 0:
            summary, by_type = summarize(per_q, modes)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump({"n": len(per_q), "summary": summary,
                           "by_type": by_type, "per_question": per_q},
                          f, ensure_ascii=False)
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  {i+1}/{len(eval_qs)} done  elapsed {time.time()-t0:.0f}s", flush=True)

    summary, by_type = summarize(per_q, modes)
    out = {"n": len(per_q), "summary": summary, "by_type": by_type,
           "per_question": per_q, "trajectory_examples": traj_examples}
    os.makedirs("results", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== OVERALL ===")
    hdr = f"{'metric':<12}" + "".join(f"{m:>14}" for m in modes)
    print(hdr)
    for k in METRIC_KEYS + ["avg_rounds"]:
        print(f"{k:<12}" + "".join(f"{summary[m].get(k,0):>14}" for m in modes))
    print("\n=== BY TYPE ===")
    for ty in ["bridge", "comparison"]:
        print(f"-- {ty} --")
        print(hdr)
        for k in METRIC_KEYS + ["avg_rounds"]:
            print(f"{k:<12}" + "".join(f"{by_type[m].get(ty,{}).get(k,0):>14}" for m in modes))
    print(f"\nresults -> {args.out}")
    print(f"total elapsed {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
