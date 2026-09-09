"""Build a retrieval corpus sized for the eval set (gold + distractor passages).

Instead of the full 66K passages (OOMs on encode in 3GB RAM), we keep:
  - ALL passages referenced by the 500 eval questions (gold + their distractors)
  - a random sample of extra distractor passages from the rest of HotpotQA

Result: ~8-10K passages -> dense encode fits in memory, still much larger than
the per-question 10-passage bucket, so retrieval is non-trivial.
"""
import random

from src.data_loader import load_parquet, load_eval, Document, save_corpus

N_EXTRA_DISTRACTORS = 4000


def main() -> None:
    df = load_parquet("data/hotpot_val.parquet")
    eval_qs = load_eval("data/eval_500.json")
    eval_ids = {q.id for q in eval_qs}
    print(f"eval questions: {len(eval_qs)}")

    eval_titles: set[str] = set()
    for _, row in df.iterrows():
        if row["id"] in eval_ids:
            for t in row["context"]["title"]:
                eval_titles.add(str(t))
    print(f"eval-related passage titles (gold + their distractors): {len(eval_titles)}")

    passages: dict[str, list[str]] = {}
    distractor_pool: list[tuple] = []
    for _, row in df.iterrows():
        titles = row["context"]["title"]
        sents = row["context"]["sentences"]
        for t, s in zip(titles, sents):
            t = str(t)
            s = [str(x) for x in s]
            if t in eval_titles:
                if t not in passages:
                    passages[t] = s
            else:
                if len(distractor_pool) < N_EXTRA_DISTRACTORS * 2:
                    distractor_pool.append((t, s))

    rng = random.Random(123)
    rng.shuffle(distractor_pool)
    for t, s in distractor_pool[:N_EXTRA_DISTRACTORS]:
        if t not in passages:
            passages[t] = s

    corpus = [Document(id=t, title=t, sentences=passages[t]) for t in passages]
    save_corpus("data/corpus_small.json", corpus)
    print(f"small corpus: {len(corpus)} passages -> data/corpus_small.json")
    words = sum(len(d.text.split()) for d in corpus)
    print(f"  words: {words:,}  avg/passage: {words // max(1, len(corpus))}")

    # sanity: all gold titles present?
    all_gold = set()
    for q in eval_qs:
        all_gold |= q.gold_titles
    present = all_gold & {d.id for d in corpus}
    print(f"  gold titles present: {len(present)}/{len(all_gold)}")


if __name__ == "__main__":
    main()
