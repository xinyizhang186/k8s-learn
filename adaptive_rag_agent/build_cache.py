"""One-shot cache build for the retriever (BM25 pickle + Dense embeddings)."""
import os
import sys

os.environ["TRANSFORMERS_NO_TF"] = "1"
sys.path.insert(0, ".")

from src.data_loader import load_corpus
from src.retriever import HybridRetriever

corpus = load_corpus("data/corpus_small.json")
print(f"corpus loaded: {len(corpus)} passages", flush=True)

r = HybridRetriever(corpus, cache_dir="cache")
print("retriever built", flush=True)

docs = r.search("Where was Albert Einstein born?", k=5, rerank=False, recall_k=50)
for d in docs:
    print(f"  {d.title:<40} score={d.score:.4f}", flush=True)
print("BUILD_OK", flush=True)
