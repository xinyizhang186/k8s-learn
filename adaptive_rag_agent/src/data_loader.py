"""
HotpotQA data loader.

Builds a global deduplicated passage corpus from all questions' contexts
(the real-RAG setting: retrieve over the WHOLE corpus, not the per-question
10-passage gold+distractor bucket), and samples a balanced evaluation set.

HotpotQA validation (distractor): 7405 questions (5918 bridge / 1487 comparison),
each with 10 Wikipedia paragraphs (2 gold + 8 distractor) + sentence-level
supporting_facts annotations -> enables Context Recall / Precision.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import List, Set, Tuple

import pandas as pd


@dataclass
class Document:
    """A single retrievable passage (one Wikipedia paragraph)."""
    id: str                       # title acts as unique id across HotpotQA
    title: str
    sentences: List[str]
    text: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.text = " ".join(self.sentences)


@dataclass
class Question:
    """An evaluation question with ground-truth for retrieval + answer metrics."""
    id: str
    question: str
    answer: str
    type: str                     # 'bridge' (multi-hop) | 'comparison'
    level: str
    supporting_facts: List[Tuple[str, int]]   # [(title, sentence_id)]
    gold_titles: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.gold_titles = {t for t, _ in self.supporting_facts}


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------
def load_parquet(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    keep = ["id", "question", "answer", "type", "level", "context", "supporting_facts"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def build_corpus(df: pd.DataFrame) -> List[Document]:
    """Deduplicate passages by title across all questions -> global corpus."""
    seen: dict[str, Document] = {}
    for _, row in df.iterrows():
        ctx = row["context"]
        titles = ctx["title"]
        sents = ctx["sentences"]
        for t, s in zip(titles, sents):
            t = str(t)
            if t not in seen:
                seen[t] = Document(id=t, title=t, sentences=[str(x) for x in s])
    return list(seen.values())


def sample_eval(df: pd.DataFrame, n_bridge: int, n_comparison: int,
                seed: int = 42) -> List[Question]:
    rng = random.Random(seed)
    bridge_df = df[df["type"] == "bridge"].sample(n_bridge, random_state=seed)
    comp_df = df[df["type"] == "comparison"].sample(n_comparison, random_state=seed)
    selected = pd.concat([bridge_df, comp_df]).sample(frac=1.0, random_state=seed)

    qs: List[Question] = []
    for _, row in selected.iterrows():
        sf = row["supporting_facts"]
        facts = [(str(t), int(i)) for t, i in zip(sf["title"], sf["sent_id"])]
        qs.append(Question(
            id=str(row["id"]),
            question=str(row["question"]),
            answer=str(row["answer"]),
            type=str(row["type"]),
            level=str(row["level"]),
            supporting_facts=facts,
        ))
    return qs


# ----------------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------------
def save_corpus(path: str, corpus: List[Document]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"title": d.title, "sentences": d.sentences} for d in corpus],
                  f, ensure_ascii=False)


def load_corpus(path: str) -> List[Document]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Document(id=r["title"], title=r["title"], sentences=r["sentences"])
            for r in raw]


def save_eval(path: str, questions: List[Question]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{
            "id": q.id, "question": q.question, "answer": q.answer,
            "type": q.type, "level": q.level,
            "supporting_facts": [[t, i] for t, i in q.supporting_facts],
            "gold_titles": sorted(q.gold_titles),
        } for q in questions], f, ensure_ascii=False, indent=2)


def load_eval(path: str) -> List[Question]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Question(
        id=r["id"], question=r["question"], answer=r["answer"],
        type=r["type"], level=r["level"],
        supporting_facts=[(t, i) for t, i in r["supporting_facts"]],
    ) for r in raw]


if __name__ == "__main__":
    # quick self-test
    df = load_parquet("data/hotpot_val.parquet")
    print(f"raw questions: {len(df)}")
    corpus = build_corpus(df)
    print(f"corpus passages (dedup by title): {len(corpus)}")
    total_tokens = sum(len(d.text.split()) for d in corpus)
    print(f"corpus words: {total_tokens:,}  avg/passage: {total_tokens//len(corpus)}")
    ev = sample_eval(df, 10, 5, seed=42)
    print(f"sampled eval: {len(ev)}  types: { {q.type for q in ev} }")
    print("first:", ev[0].question, "->", ev[0].answer, "| gold:", ev[0].gold_titles)
