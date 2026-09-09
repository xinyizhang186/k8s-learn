"""
Rule-based answer extractor (no LLM dependency).

A deliberately simple, deterministic extractor shared by all three pipelines
(Naive / Hybrid / Agentic), so any EM/F1 delta isolates the retrieval-strategy
effect (context recall), not extractor differences.

Strategy:
  1. Collect candidate sentences from top retrieved passages.
  2. Detect expected answer TYPE from question cues.
  3. Extract the best matching span of that type, preferring spans NOT already
     present in the question (the answer is usually a NEW entity).
"""
from __future__ import annotations

import re
from typing import List, Optional

from .retriever import RetrievedDoc

_CAP_RE = re.compile(r"[A-Z][a-zA-Z]+(?:[-\s][A-Z][a-zA-Z]+)*")
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_NUM_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b")
_HYPHEN_CAP_RE = re.compile(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)+)\b")
_STOP = set("""the a an of in on at to for and or is was were are be by with from
as that this it its which who whom whose what when where why how many much
did do does has have had been being first last most same also both not""".split())
_NON_ANSWER_CAPS = {"The", "This", "That", "He", "She", "They", "It", "His",
                    "Her", "Their", "These", "Those", "His", "Its", "Who", "What",
                    "Where", "When", "How", "Why", "Which", "There", "Here",
                    "United", "American", "British", "English", "European"}


def _best_sentence(candidates: List[str], q_tokens: List[str]) -> Optional[str]:
    if not candidates:
        return None
    qset = set(q_tokens) - _STOP
    scored = []
    for sent in candidates:
        toks = set(re.findall(r"\w+", sent.lower())) - _STOP
        overlap = len(qset & toks)
        scored.append((overlap, -len(sent), sent))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][2] if scored else None


def _extract_proper_noun(sent: str, q_tokens: List[str]) -> str:
    qwords = {w.lower() for w in q_tokens}
    caps = _CAP_RE.findall(sent)
    # prefer capitalized spans NOT already in the question (the new answer entity)
    not_in_q = [c for c in caps
                if c.lower() not in qwords and c not in _NON_ANSWER_CAPS
                and c.lower() not in _STOP]
    if not_in_q:
        return not_in_q[0]
    filtered = [c for c in caps
                if not all(w.lower() in qwords for w in c.split())
                and c not in _NON_ANSWER_CAPS and c.lower() not in _STOP]
    return filtered[0] if filtered else ""


def _extract_year(sents: List[str]) -> str:
    for s in sents:
        m = _YEAR_RE.findall(s)
        if m:
            return m[0]
    return ""


def _extract_number(sents: List[str]) -> str:
    for s in sents:
        m = _NUM_RE.findall(s)
        if m:
            return m[0]
    return ""


def _extract_nationality(sents: List[str]) -> str:
    """Find a nationality span: 'Greek-American', 'British', etc."""
    blob = " ".join(sents)
    m = _HYPHEN_CAP_RE.findall(blob)
    if m:
        return m[0]
    for s in sents:
        mm = re.search(r"\b(?:was|is|were|are|born|nationality)\s+(?:a\s+|an\s+)?([A-Z][a-z]+)", s)
        if mm:
            w = mm.group(1)
            if w in _NON_ANSWER_CAPS or w.lower() in _STOP:
                continue
            if re.search(r"(ese|ish|ian|nic|ch|ic|er|an|ski|ov|in)$", w.lower()):
                return w
    return ""


def _is_yesno_question(question: str) -> bool:
    q = question.strip().lower()
    triggers = ("same ", "different", "same?", "similar", "also a")
    if q.endswith("?") and any(t in q for t in triggers):
        return True
    if re.search(r"\b(was|were|is|are|did|do|does)\b.*\bsame\b", q):
        return True
    return False


def _predict_yesno(question: str, docs: List[RetrievedDoc]) -> str:
    ents = [e for e in _CAP_RE.findall(question) if e.lower() not in _STOP]
    if len(ents) < 2:
        sents = [s for d in docs[:2] for s in d.sentences]
        blob = " ".join(sents).lower()
        return "no" if any(w in blob for w in ["not", "no ", "never", "different"]) else "yes"
    e1, e2 = ents[0].lower(), ents[1].lower()
    sents = [s for d in docs[:3] for s in d.sentences]
    attrs1, attrs2 = set(), set()
    for s in sents:
        sl = s.lower()
        toks = set(re.findall(r"\w+", sl)) - _STOP - {e1, e2}
        if e1 in sl:
            attrs1 |= toks
        if e2 in sl:
            attrs2 |= toks
    return "yes" if (attrs1 & attrs2) else "no"


def extract_answer(question: str, docs: List[RetrievedDoc]) -> str:
    """Rule-based answer extraction from retrieved passages."""
    if not docs:
        return ""

    if _is_yesno_question(question):
        return _predict_yesno(question, docs)

    q = question.lower()
    q_tokens = re.findall(r"\w+", q)
    candidates = [s for d in docs[:5] for s in d.sentences]
    best = _best_sentence(candidates, q_tokens)
    base = best or (docs[0].sentences[0] if docs[0].sentences else docs[0].text)

    # type-specific extraction
    if re.search(r"\b(nationality|national)\b", q):
        nat = _extract_nationality(candidates)
        if nat:
            return nat
    if re.search(r"\b(when|year|date)\b", q):
        y = _extract_year(candidates)
        if y:
            return y
    if re.search(r"\b(how many|how much|number)\b", q):
        n = _extract_number(candidates)
        if n:
            return n

    # person names: family relations + 'who'
    person_cues = r"\b(grandfather|grandmother|father|mother|brother|sister|son|daughter|" \
                  r"husband|wife|parent|child|spouse|uncle|aunt|cousin|nephew|niece|actor|" \
                  r"actress|singer|author|writer|director|painter|artist|founder|king|queen)\b"
    if re.search(person_cues, q) or re.search(r"\bwho\b", q):
        p = _extract_proper_noun(base, q_tokens)
        if p:
            return p
    # band / group / organization
    if re.search(r"\b(band|group|team|company|organization|club|orchestra|firm)\b", q):
        p = _extract_proper_noun(base, q_tokens)
        if p:
            return p
    # where / location
    if re.search(r"\b(where|born|city|country|located|home|place|capital|river|mountain)\b", q):
        p = _extract_proper_noun(base, q_tokens)
        if p:
            return p

    # default: proper noun from best sentence
    p = _extract_proper_noun(base, q_tokens)
    return p or _extract_proper_noun(docs[0].text, q_tokens)
