"""
Agentic RAG: adaptive multi-strategy retrieval with self-reflection.

Core innovations (the "Agent" beyond a single retrieve-then-read call):
  1. Query-complexity-aware router -> decides strategy per question.
  2. Iterative multi-hop query decomposition -> for multi-hop questions the
     agent STRUCTURALLY runs a 2nd retrieval hop: extract a bridge entity from
     round-1 evidence, build a next-hop query (bridge + target aspect), retrieve,
     merge. This finds gold passages a single retrieval misses.
  3. Self-reflective re-retrieval -> low confidence triggers query rewrite +
     re-search (bounded by max_iters).
  4. Evidence conflict detection -> contradictory yes/no signals flag low
     confidence and force another retrieval round.

ReAct-style loop (Thought -> Action -> Observation), reasoning is RULE-driven
(no LLM) so the system is self-contained and the retrieval-strategy effect is
cleanly measurable against a fixed extractor.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List

from .retriever import HybridRetriever, RetrievedDoc
from .extractor import extract_answer, _CAP_RE, _STOP, _is_yesno_question


@dataclass
class Step:
    thought: str
    action: str
    observation: str


@dataclass
class AgentResult:
    answer: str
    docs: List[RetrievedDoc]
    retrieved_titles: List[str]
    trajectory: List[Step]
    n_retrieval_rounds: int
    query_variants: List[str]
    latency: float


class QueryRouter:
    """Classify a question into a strategy class without any LLM call."""

    @staticmethod
    def classify(question: str) -> str:
        q = question.lower()
        if _is_yesno_question(question):
            return "yesno"
        ents = [e for e in _CAP_RE.findall(question) if e.lower() not in _STOP]
        compare_cues = [" than ", " versus ", " or ", " compared", " same ", " both "]
        if len(ents) >= 2 and any(c in q for c in compare_cues):
            return "comparison"
        if re.search(r"\bof\b.*\bof\b", q) or re.search(r"\bthat\b", q) or "whose" in q:
            return "multihop"
        return "bridge"


class AgenticRAG:
    def __init__(self, retriever: HybridRetriever, max_iters: int = 2,
                 k: int = 10, recall_k: int = 20,
                 conf_threshold: float = 0.45) -> None:
        self.retriever = retriever
        self.router = QueryRouter()
        self.max_iters = max_iters
        self.k = k
        self.recall_k = recall_k
        self.conf_threshold = conf_threshold

    # ---- helpers ----------------------------------------------------------
    def _extract_bridge_entity(self, question: str, docs: List[RetrievedDoc]):
        """Pick the capitalized span in retrieved evidence most tied to the question,
        preferring entities NOT already in the question (the 'bridge' to the next hop)."""
        q_tokens = set(re.findall(r"\w+", question.lower())) - _STOP
        best, best_score = None, -1
        for d in docs[:5]:
            for s in d.sentences:
                caps = _CAP_RE.findall(s)
                sl = set(re.findall(r"\w+", s.lower())) - _STOP
                overlap = len(q_tokens & sl)
                for c in caps:
                    if c.lower() in _STOP:
                        continue
                    novelty = 2 if c.lower() not in question.lower() else 0
                    score = overlap + novelty
                    if score > best_score:
                        best_score, best = score, c
        return best

    @staticmethod
    def _extract_target(question: str) -> str:
        q = question.lower()
        if any(w in q for w in ("where", "home", "born", "city", "country", "located")):
            return "born location"
        if any(w in q for w in ("when", "year", "date")):
            return "year"
        if "directed" in q:
            return "director"
        if any(w in q for w in ("wrote", "author", "written")):
            return "author"
        if any(w in q for w in ("singer", "sang", "song", "voiced")):
            return "singer"
        if "founded" in q:
            return "founder"
        return ""

    def _confidence(self, question: str, docs: List[RetrievedDoc]) -> float:
        if not docs:
            return 0.0
        q_tokens = set(re.findall(r"\w+", question.lower())) - _STOP
        top_overlap = 0
        for d in docs[:3]:
            dt = set(re.findall(r"\w+", d.text.lower())) - _STOP
            top_overlap = max(top_overlap, len(q_tokens & dt))
        base = min(top_overlap / max(1, len(q_tokens)), 1.0)
        gap = (docs[0].score - docs[1].score) if len(docs) >= 2 else 0.0
        return base + min(max(gap, 0.0), 0.2)

    @staticmethod
    def _detect_conflict(question: str, docs: List[RetrievedDoc], qtype: str) -> bool:
        if qtype != "yesno" or not docs:
            return False
        blob = " ".join(s for d in docs[:3] for s in d.sentences).lower()
        yes_cues = sum(blob.count(c) for c in (" same ", " both ", " also "))
        no_cues = sum(blob.count(c) for c in (" not ", " different ", " never "))
        return yes_cues > 0 and no_cues > 0

    def _rewrite(self, question: str, docs: List[RetrievedDoc]) -> str:
        ents = []
        for d in docs[:3]:
            for c in _CAP_RE.findall(d.text):
                if c.lower() not in _STOP and c.lower() not in question.lower():
                    ents.append(c)
        extra = " ".join(dict.fromkeys(ents[:2]))
        return f"{question} {extra}".strip()

    @staticmethod
    def _merge(docs_a: List[RetrievedDoc], docs_b: List[RetrievedDoc],
               k: int) -> List[RetrievedDoc]:
        merged: dict[str, RetrievedDoc] = {}
        for d in list(docs_a) + list(docs_b):
            if d.id not in merged or d.score > merged[d.id].score:
                merged[d.id] = d
        return sorted(merged.values(), key=lambda x: -x.score)[:k]

    # ---- main loop --------------------------------------------------------
    def answer(self, question: str) -> AgentResult:
        t0 = time.time()
        qtype = self.router.classify(question)
        trajectory: List[Step] = []
        query_variants: List[str] = [question]

        # round 1: full hybrid retrieval + rerank
        docs = self.retriever.search(
            question, k=self.k, rerank=True, recall_k=self.recall_k)
        trajectory.append(Step(
            thought=f"Router classified question as '{qtype}'. Initial hybrid retrieval.",
            action="search(rerank=True)",
            observation=f"round1: {len(docs)} docs, top='{docs[0].title if docs else None}'",
        ))
        rounds = 1

        # INNOVATION 2: multi-hop structural decomposition.
        # Bridge/multi-hop questions structurally need a 2nd retrieval hop:
        # extract the bridge entity from round-1 evidence, form a next-hop query
        # (bridge + target aspect), retrieve, and merge. This recovers gold
        # passages that single-pass retrieval misses.
        if qtype in ("multihop", "bridge"):
            bridge = self._extract_bridge_entity(question, docs)
            target = self._extract_target(question)
            if bridge:
                next_q = f"{bridge} {target}".strip()
                new_docs = self.retriever.search(
                    next_q, k=self.k, rerank=True, recall_k=self.recall_k)
                query_variants.append(next_q)
                docs = self._merge(docs, new_docs, 2 * self.k)
                rounds += 1
                trajectory.append(Step(
                    thought="multi-hop: extracted bridge entity, building next-hop query.",
                    action=f"decompose -> search('{next_q[:50]}...')",
                    observation=f"round{rounds}: merged to {len(docs)} docs, top='{docs[0].title if docs else None}'",
                ))

        # INNOVATION 3 + 4: self-reflective re-retrieval with conflict detection.
        for _ in range(self.max_iters):
            conf = self._confidence(question, docs)
            conflict = self._detect_conflict(question, docs, qtype)
            if conf >= self.conf_threshold and not conflict:
                trajectory.append(Step(
                    thought=f"confidence={conf:.2f} >= {self.conf_threshold}, no conflict.",
                    action="stop", observation="evidence sufficient; proceed to extract."))
                break
            next_q = self._rewrite(question, docs)
            new_docs = self.retriever.search(
                next_q, k=self.k, rerank=True, recall_k=self.recall_k)
            query_variants.append(next_q)
            docs = self._merge(docs, new_docs, self.k)
            rounds += 1
            trajectory.append(Step(
                thought=f"confidence={conf:.2f}, conflict={conflict}. Query rewrite + re-retrieval.",
                action=f"rewrite -> search('{next_q[:50]}...')",
                observation=f"round{rounds}: merged to {len(docs)} docs, top='{docs[0].title if docs else None}'",
            ))

        ans = extract_answer(question, docs)
        return AgentResult(
            answer=ans, docs=docs,
            retrieved_titles=[d.title for d in docs],
            trajectory=trajectory, n_retrieval_rounds=rounds,
            query_variants=query_variants, latency=time.time() - t0,
        )
