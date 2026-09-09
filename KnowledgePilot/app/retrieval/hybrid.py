import re
import unicodedata
from difflib import SequenceMatcher

from app.models import Paper


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> set[str]:
    normalized = normalize(text)
    english = set(re.findall(r"[a-z0-9]{2,}", normalized))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
    chinese = {run[index : index + 2] for run in chinese_runs for index in range(len(run) - 1)}
    return english | chinese


def ordered_title_match(query: str, title: str) -> float:
    query_tokens = _ordered_tokens(query)
    title_tokens = _ordered_tokens(title)
    if not query_tokens or not title_tokens:
        return 0.0
    positions = []
    cursor = 0
    for query_token in query_tokens:
        try:
            position = title_tokens.index(query_token, cursor)
        except ValueError:
            continue
        positions.append(position)
        cursor = position + 1
    if len(positions) < 2:
        return 0.0
    span = positions[-1] - positions[0] + 1
    return min(1.0, len(positions) / max(1, span))


def _ordered_tokens(text: str) -> list[str]:
    normalized = normalize(text)
    output: list[str] = []
    for part in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            output.extend(part[index : index + 2] for index in range(len(part) - 1))
        else:
            output.append(part)
    return output


def score(query: str, paper: Paper) -> float:
    q = normalize(query)
    q_tokens = tokens(q)
    title = normalize(paper.title)
    body = normalize(" ".join([paper.title, paper.abstract, " ".join(paper.authors), " ".join(paper.concepts)]))
    query_english = set(re.findall(r"[a-z0-9]{2,}", q))
    body_english = set(re.findall(r"[a-z0-9]{2,}", body))
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", q))
    if has_chinese and query_english and not query_english.intersection(body_english):
        return 0.0
    overlap = len(q_tokens & tokens(body)) / max(1, len(q_tokens))
    title_overlap = len(q_tokens & tokens(title)) / max(1, len(q_tokens))
    fuzzy = SequenceMatcher(None, q, title).ratio() if q else 0
    exact_phrase = 1.0 if q and q in title else 0.0
    ordered = ordered_title_match(q, title)
    query_words = re.findall(r"[a-z0-9]{2,}", q)
    title_words = re.findall(r"[a-z0-9]{2,}", title)
    prefix = 1.0 if len(query_words) >= 3 and query_words and title_words[: len(query_words)] == query_words else 0.0
    return min(1.0, 0.35 * title_overlap + 0.2 * overlap + 0.2 * fuzzy + 0.15 * ordered + 0.05 * exact_phrase + 0.05 * prefix)


def search_local(query: str, papers: list[Paper], top_k: int = 8) -> list[tuple[Paper, float]]:
    ranked = [(paper, score(query, paper)) for paper in papers]
    ranked.sort(key=lambda item: (item[1], item[0].cited_by_count), reverse=True)
    return [(paper, round(value, 4)) for paper, value in ranked[:top_k] if value >= 0.28]
