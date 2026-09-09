"""Build global corpus + balanced 500-question eval set from HotpotQA."""
from __future__ import annotations
from src.data_loader import (
    load_parquet, build_corpus, sample_eval, save_corpus, save_eval,
)


def main() -> None:
    df = load_parquet("data/hotpot_val.parquet")
    print(f"raw questions: {len(df)}")

    corpus = build_corpus(df)
    save_corpus("data/corpus.json", corpus)
    print(f"corpus: {len(corpus)} passages -> data/corpus.json")

    ev = sample_eval(df, n_bridge=400, n_comparison=100, seed=42)
    save_eval("data/eval_500.json", ev)
    print(f"eval set: {len(ev)} questions -> data/eval_500.json")

    by_type: dict[str, int] = {}
    for q in ev:
        by_type[q.type] = by_type.get(q.type, 0) + 1
    print(f"  by type: {by_type}")
    ans_kinds = {"yes": 0, "no": 0, "other": 0}
    for q in ev:
        a = q.answer.strip().lower()
        ans_kinds["yes" if a == "yes" else "no" if a == "no" else "other"] += 1
    print(f"  answer kinds: {ans_kinds}")


if __name__ == "__main__":
    main()
