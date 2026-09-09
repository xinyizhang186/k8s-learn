"""
Evaluation metrics.

- exact_match / f1: SQuAD-style answer matching (normalize + EM + token F1).
- context_recall: fraction of gold passages (supporting_facts titles) retrieved.
- context_precision_at_k: fraction of top-k retrieved that are gold.
"""
from __future__ import annotations

import re
import string
from collections import Counter
from typing import List, Set

_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)
_PUNCT = set(string.punctuation)


def normalize_answer(s: str) -> str:
    """SQuAD normalization: lowercase, strip punctuation/articles, collapse whitespace."""
    s = s.lower()
    s = "".join(ch for ch in s if ch not in _PUNCT)
    s = _ARTICLES_RE.sub(" ", s)
    return " ".join(s.split())


def exact_match(pred: str, gold: str) -> float:
    return float(normalize_answer(pred) == normalize_answer(gold))


def f1(pred: str, gold: str) -> float:
    p_tokens = normalize_answer(pred).split()
    g_tokens = normalize_answer(gold).split()
    if not p_tokens or not g_tokens:
        return float(p_tokens == g_tokens)
    common = Counter(p_tokens) & Counter(g_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(p_tokens)
    recall = num_same / len(g_tokens)
    return 2 * precision * recall / (precision + recall)


def context_recall(retrieved_titles: List[str], gold_titles: Set[str]) -> float:
    """Fraction of gold passages found in the retrieved set (recall over gold)."""
    if not gold_titles:
        return 0.0
    found = set(retrieved_titles) & gold_titles
    return len(found) / len(gold_titles)


def context_precision_at_k(retrieved_titles: List[str], gold_titles: Set[str], k: int) -> float:
    """Fraction of top-k retrieved passages that are gold (precision@k)."""
    top_k = retrieved_titles[:k]
    if not top_k:
        return 0.0
    return len(set(top_k) & gold_titles) / len(top_k)


if __name__ == "__main__":
    assert exact_match("Paris", "paris") == 1.0
    assert exact_match("the Eiffel Tower", "Eiffel Tower") == 1.0
    assert 0 < f1("Barack Obama", "Obama") < 1
    assert context_recall(["A", "B"], {"A", "C"}) == 0.5
    assert context_precision_at_k(["A", "B", "C"], {"A", "C"}, 3) == (2 / 3)
    print("metrics self-test OK")
