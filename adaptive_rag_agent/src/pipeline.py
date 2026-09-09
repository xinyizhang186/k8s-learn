"""
Three pipelines compared in the experiments:

  - Naive RAG : BM25-only single retrieval, no rerank.            (weak baseline)
  - Hybrid RAG: BM25 + Dense + RRF + Cross-encoder rerank, single. (strong baseline)
  - Agentic RAG: adaptive multi-round retrieval + self-reflection. (this system)

All three share the SAME extractor, so EM/F1 deltas isolate retrieval effect.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from .retriever import HybridRetriever, RetrievedDoc
from .extractor import extract_answer
from .agent import AgenticRAG


@dataclass
class PipelineResult:
    answer: str
    retrieved_titles: List[str]
    docs: List[RetrievedDoc]
    n_retrieval_rounds: int
    latency: float
    trajectory: list = field(default_factory=list)
    query_variants: list = field(default_factory=list)


def run_naive(question: str, retriever: HybridRetriever, k: int = 10) -> PipelineResult:
    """BM25-only single retrieval (weakest baseline, no semantic / no rerank)."""
    t0 = time.time()
    docs = retriever.search(question, k=k, use_bm25=True, use_dense=False, rerank=False)
    ans = extract_answer(question, docs)
    return PipelineResult(ans, [d.title for d in docs], docs, 1, time.time() - t0)


def run_hybrid(question: str, retriever: HybridRetriever, k: int = 10,
               recall_k: int = 20) -> PipelineResult:
    """Hybrid (BM25+Dense+RRF) + cross-encoder rerank, single round."""
    t0 = time.time()
    docs = retriever.search(question, k=k, use_bm25=True, use_dense=True,
                            rerank=True, recall_k=recall_k)
    ans = extract_answer(question, docs)
    return PipelineResult(ans, [d.title for d in docs], docs, 1, time.time() - t0)


def run_agentic(question: str, retriever: HybridRetriever, k: int = 10,
                max_iters: int = 2) -> PipelineResult:
    """Adaptive multi-round agentic retrieval with self-reflection."""
    agent = AgenticRAG(retriever, max_iters=max_iters, k=k)
    r = agent.answer(question)
    return PipelineResult(
        answer=r.answer, retrieved_titles=r.retrieved_titles, docs=r.docs,
        n_retrieval_rounds=r.n_retrieval_rounds, latency=r.latency,
        trajectory=r.trajectory, query_variants=r.query_variants,
    )
