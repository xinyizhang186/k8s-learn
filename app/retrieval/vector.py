import hashlib
import math
import re
from collections import Counter

from app.retrieval.hybrid import normalize


def _features(text: str) -> list[str]:
    normalized = normalize(text)
    words = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", normalized)
    bigrams = [f"{words[index]}_{words[index + 1]}" for index in range(len(words) - 1)]
    return words + bigrams


def hash_vector(text: str, dimensions: int = 512) -> dict[int, float]:
    counts = Counter(_features(text))
    vector: dict[int, float] = {}
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1 if digest[4] % 2 == 0 else -1
        vector[index] = vector.get(index, 0.0) + sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm == 0:
        return {}
    return {index: value / norm for index, value in vector.items()}


def cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def vector_similarity(query: str, text: str) -> float:
    return max(0.0, cosine(hash_vector(query), hash_vector(text)))


def section_bonus(question: str, text: str) -> float:
    q = normalize(question)
    t = normalize(text[:500])
    bonuses = {
        "method": ["method", "model", "architecture", "attention", "算法", "方法", "结构", "原理"],
        "experiment": ["experiment", "dataset", "bleu", "accuracy", "实验", "数据集", "指标"],
        "conclusion": ["result", "conclusion", "outperform", "achieve", "结果", "结论"],
    }
    score = 0.0
    for terms in bonuses.values():
        if any(term in q for term in terms) and any(term in t for term in terms):
            score += 0.08
    return min(score, 0.2)
