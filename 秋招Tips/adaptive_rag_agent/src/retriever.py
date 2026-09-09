"""
Hybrid retrieval stack: BM25 (lexical) + Dense (semantic) + RRF fusion
+ Cross-Encoder rerank.

Production RAG retrieval pattern:
    Bi-encoder RECALL  (BM25 + Dense fused via RRF)   -> broad top-K
    Cross-encoder PRECISION (rerank)                  -> sharp top-k

Caches BM25 pickle + Dense embeddings to avoid recomputation.
"""
from __future__ import annotations

import os
import pickle
import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

_TOKEN_RE = re.compile(r"\w+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class RetrievedDoc:
    id: str
    title: str
    score: float
    text: str
    sentences: List[str]


# ----------------------------------------------------------------------------
# BM25 (lexical sparse retrieval)
# ----------------------------------------------------------------------------
class BM25Index:
    def __init__(self) -> None:
        self.bm25 = None
        self.ids: List[str] = []

    def build(self, docs) -> None:
        from rank_bm25 import BM25Okapi
        self.ids = [d.id for d in docs]
        tokenized = [tokenize(d.text) for d in docs]
        self.bm25 = BM25Okapi(tokenized)

    def search(self, query: str, k: int) -> List[tuple]:
        scores = self.bm25.get_scores(tokenize(query))
        k = min(k, len(scores))
        if k <= 0:
            return []
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = sorted(idx, key=lambda i: -scores[i])
        return [(self.ids[i], float(scores[i])) for i in idx]


# ----------------------------------------------------------------------------
# Dense (semantic, sentence-transformers + faiss)
# ----------------------------------------------------------------------------
class DenseIndex:
    def __init__(self, encoder, dim: int) -> None:
        self.encoder = encoder
        self.dim = dim
        self.index = None
        self.ids: List[str] = []

    def build(self, docs, batch: int = 256, cache_path: Optional[str] = None) -> None:
        import faiss
        texts = [d.text for d in docs]
        if cache_path and os.path.exists(cache_path):
            embs = np.load(cache_path)
        else:
            embs = self.encoder.encode(
                texts, batch_size=batch, normalize_embeddings=True,
                show_progress_bar=True, convert_to_numpy=True,
            )
            if cache_path:
                np.save(cache_path, embs.astype("float32"))
        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(np.ascontiguousarray(embs.astype("float32")))
        self.ids = [d.id for d in docs]

    def search(self, q_vec, k: int) -> List[tuple]:
        k = min(k, len(self.ids))
        if k <= 0:
            return []
        q = np.ascontiguousarray(q_vec.astype("float32"))
        scores, idx = self.index.search(q, k)
        return [(self.ids[i], float(s)) for s, i in zip(scores[0], idx[0])]


# ----------------------------------------------------------------------------
# Cross-encoder rerank
# ----------------------------------------------------------------------------
class CrossEncoderReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, max_length=512)

    def score_pairs(self, pairs: List[tuple]) -> np.ndarray:
        return self.model.predict(pairs, show_progress_bar=False)


# ----------------------------------------------------------------------------
# Hybrid retriever (orchestrates the two retrievers + fusion + rerank)
# ----------------------------------------------------------------------------
class HybridRetriever:
    def __init__(self, docs, cache_dir: str = "cache") -> None:
        from sentence_transformers import SentenceTransformer

        self.docs = docs
        self.docs_by_id = {d.id: d for d in docs}
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        # BM25 (cache pickle)
        bm25_cache = os.path.join(cache_dir, "bm25.pkl")
        if os.path.exists(bm25_cache):
            with open(bm25_cache, "rb") as f:
                self.bm25 = pickle.load(f)
        else:
            self.bm25 = BM25Index()
            self.bm25.build(docs)
            with open(bm25_cache, "wb") as f:
                pickle.dump(self.bm25, f)
        print(f"[retriever] BM25 ready ({len(self.bm25.ids)} docs)")

        # Dense (cache embeddings npy)
        self.encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self.dim = self.encoder.get_sentence_embedding_dimension()
        dense_cache = os.path.join(cache_dir, "dense.npy")
        self.dense = DenseIndex(self.encoder, self.dim)
        self.dense.build(docs, cache_path=dense_cache)
        print(f"[retriever] Dense ready (dim={self.dim})")

        self._reranker: Optional[CrossEncoderReranker] = None

    @property
    def reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            print("[retriever] loading cross-encoder reranker ...")
            self._reranker = CrossEncoderReranker()
        return self._reranker

    @staticmethod
    def _rrf(ranked_lists: List[List[tuple]], rrf_k: int = 60) -> List[tuple]:
        """Reciprocal Rank Fusion: combine multiple ranked lists by rank only."""
        scores: dict[str, float] = {}
        for rl in ranked_lists:
            for rank, (did, _) in enumerate(rl):
                scores[did] = scores.get(did, 0.0) + 1.0 / (rrf_k + rank + 1)
        return sorted(scores.items(), key=lambda x: -x[1])

    def search(
        self,
        query: str,
        k: int = 10,
        use_bm25: bool = True,
        use_dense: bool = True,
        rerank: bool = False,
        recall_k: int = 50,
    ) -> List[RetrievedDoc]:
        lists: List[List[tuple]] = []
        if use_bm25:
            lists.append(self.bm25.search(query, max(recall_k, k)))
        if use_dense:
            qv = self.encoder.encode([query], normalize_embeddings=True,
                                      convert_to_numpy=True, show_progress_bar=False)
            lists.append(self.dense.search(qv, max(recall_k, k)))
        if not lists:
            return []

        fused = self._rrf(lists) if len(lists) > 1 else lists[0]
        top = fused[: (max(recall_k, k) if rerank else k)]

        if rerank:
            pairs = [(query, self.docs_by_id[did].text[:512]) for did, _ in top]
            scs = self.reranker.score_pairs(pairs)
            top = sorted([(did, float(s)) for (did, _), s in zip(top, scs)],
                         key=lambda x: -x[1])[:k]

        return [
            RetrievedDoc(
                id=did, title=self.docs_by_id[did].title, score=score,
                text=self.docs_by_id[did].text, sentences=self.docs_by_id[did].sentences,
            )
            for did, score in top[:k]
        ]
