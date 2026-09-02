import asyncio
import re
from typing import Any

from app.clients.arxiv import ArxivClient
from app.clients.crossref import CrossrefClient
from app.clients.openalex import OpenAlexClient
from app.db.database import get_paper, list_local_papers, save_papers
from app.models import Paper
from app.retrieval.hybrid import normalize, search_local, score
from app.services.cache import Cache


class PaperService:
    def __init__(self) -> None:
        self.openalex = OpenAlexClient()
        self.crossref = CrossrefClient()
        self.arxiv = ArxivClient()
        self.cache = Cache()

    async def search(self, query: str, top_k: int = 8, year_from: int | None = None, year_to: int | None = None, online: bool = True) -> tuple[list[dict[str, Any]], bool]:
        effective_query = self.prepare_query(query)
        cache_key = self.cache.key("search", f"{query}|{effective_query}|{top_k}|{year_from}|{year_to}|{online}")
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached, True
        query_variants = self.query_variants(query, effective_query)
        local_papers = list_local_papers()
        papers: list[Paper] = []
        for variant in query_variants:
            papers.extend(paper for paper, _ in search_local(variant, local_papers, top_k * 2))
        if online:
            tasks = []
            for variant in query_variants:
                tasks.append(self.openalex.search(variant, top_k=top_k * 2, year_from=year_from, year_to=year_to))
                ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", variant)
                if len(ascii_words) >= 2:
                    tasks.extend([self.crossref.search(variant, top_k=top_k * 2), self.arxiv.search(variant, top_k=top_k * 2)])
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    papers.extend(result)
            papers = self._dedupe(papers)
            if papers:
                save_papers(papers)
        candidates = [paper for paper in self._dedupe(papers) if self._is_quality_candidate(paper)]
        ranked = sorted(
            ((paper, self._best_score(query_variants, paper)) for paper in candidates),
            key=lambda item: (item[1], self._source_priority(item[0]), item[0].cited_by_count),
            reverse=True,
        )
        # 相关度阈值是拒答的重要组成部分：仅因关键词偶然重叠的论文不应冒充命中。
        payload = [
            {"paper": paper.model_dump(mode="json"), "score": round(value, 4)}
            for paper, value in ranked[:top_k]
            if value >= 0.28
        ]
        self.cache.set(cache_key, payload)
        return payload, False

    async def get(self, identifier: str) -> Paper | None:
        normalized = identifier.strip()
        local = get_paper(normalized)
        if local:
            return local
        if normalized.startswith("10."):
            cached = self.cache.get(self.cache.key("detail", normalized))
            if cached:
                return Paper.model_validate(cached)
            if "arxiv." in normalized.lower():
                arxiv_id = normalized[normalized.lower().index("arxiv.") + len("arxiv."):]
                try:
                    item = await self.arxiv.get(arxiv_id)
                    if item:
                        save_papers([item])
                        self.cache.set(self.cache.key("detail", normalized), item.model_dump(mode="json"))
                        return item
                except Exception:
                    pass
            try:
                item = await self.crossref.get(normalized)
                if item:
                    save_papers([item])
                    self.cache.set(self.cache.key("detail", normalized), item.model_dump(mode="json"))
                    return item
            except Exception:
                pass
        try:
            return await self.openalex.get(normalized)
        except Exception:
            return None

    async def sync(self, query: str, pages: int = 1, per_page: int = 50) -> dict[str, int]:
        papers: list[Paper] = []
        effective_query = self.prepare_query(query)
        for page in range(1, pages + 1):
            result = await self.openalex.search(effective_query, top_k=per_page, page=page)
            papers.extend(result)
            if page < pages:
                await asyncio.sleep(0.2)
        unique = self._dedupe(papers)
        return {"fetched": len(papers), "unique": len(unique), "saved": save_papers(unique)}

    @staticmethod
    def prepare_query(query: str) -> str:
        text = query.strip()
        for word in ["相关论文", "论文", "文献", "相关", "检索", "搜索", "查找", "请找", "请搜索", "有关", "关于"]:
            text = text.replace(word, " ")
        text = re.sub(r"\s+", " ", text).strip()
        aliases = {
            "cnn": "CNN convolutional neural network",
            "rag": "RAG retrieval augmented generation",
            "llm": "LLM large language model",
            "gru": "GRU gated recurrent unit",
            "lstm": "LSTM long short term memory",
        }
        if not PaperService._looks_like_specific_rcnn_title(text):
            aliases.update(
                {
                    "r-cnn": "R-CNN region based convolutional neural network",
                    "rcnn": "R-CNN region based convolutional neural network",
                }
            )
        query_tokens = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", text)}
        additions = [value for key, value in aliases.items() if key in query_tokens]
        return " ".join([text, *additions]).strip() if additions else text

    @staticmethod
    def query_variants(query: str, effective_query: str) -> list[str]:
        variants = []
        for value in [query.strip(), effective_query.strip()]:
            if value and value not in variants:
                variants.append(value)
        return variants

    @staticmethod
    def _best_score(queries: list[str], paper: Paper) -> float:
        return max(score(query, paper) for query in queries)

    @staticmethod
    def _looks_like_specific_rcnn_title(text: str) -> bool:
        return bool(re.search(r"\b(mask|faster|fast|cascade|dynamic)\s+r-?cnn\b", text, re.I))

    @staticmethod
    def _dedupe(papers: list[Paper]) -> list[Paper]:
        seen: dict[str, Paper] = {}
        for paper in papers:
            key = (paper.doi or normalize(paper.title)).lower()
            if not key:
                continue
            existing = seen.get(key)
            if existing is None:
                seen[key] = paper
                continue
            winner, other = PaperService._preferred(existing, paper)
            winner.abstract = winner.abstract or other.abstract
            winner.journal = winner.journal or (other.journal if winner.source != "arxiv" else None)
            winner.authors = winner.authors or other.authors
            winner.institutions = winner.institutions or other.institutions
            winner.concepts = winner.concepts or other.concepts
            winner.cited_by_count = max(winner.cited_by_count, other.cited_by_count)
            winner.is_oa = winner.is_oa or other.is_oa
            winner.landing_page_url = winner.landing_page_url or other.landing_page_url
            winner.pdf_url = winner.pdf_url or other.pdf_url
            seen[key] = winner
        # 不同来源可能使用不同 DOI，但标题完全一致；再做一次规范化标题合并，
        # 这样 arXiv 的原始开放记录可以覆盖聚合库中的错误同名 DOI。
        by_title: dict[str, Paper] = {}
        for paper in seen.values():
            title_key = normalize(paper.title)
            if not title_key:
                continue
            existing = by_title.get(title_key)
            if existing is None:
                by_title[title_key] = paper
                continue
            winner, other = PaperService._preferred(existing, paper)
            winner.abstract = winner.abstract or other.abstract
            winner.journal = winner.journal or (other.journal if winner.source != "arxiv" else None)
            winner.authors = winner.authors or other.authors
            winner.institutions = winner.institutions or other.institutions
            winner.concepts = winner.concepts or other.concepts
            winner.cited_by_count = max(winner.cited_by_count, other.cited_by_count)
            winner.is_oa = winner.is_oa or other.is_oa
            winner.landing_page_url = winner.landing_page_url or other.landing_page_url
            winner.pdf_url = winner.pdf_url or other.pdf_url
            by_title[title_key] = winner
        return list(by_title.values())

    @staticmethod
    def _preferred(left: Paper, right: Paper) -> tuple[Paper, Paper]:
        left_key = (PaperService._source_priority(left), bool(left.abstract), bool(left.doi), left.cited_by_count)
        right_key = (PaperService._source_priority(right), bool(right.abstract), bool(right.doi), right.cited_by_count)
        return (right, left) if right_key > left_key else (left, right)

    @staticmethod
    def _source_priority(paper: Paper) -> int:
        # AI/计算机论文中，arXiv 原始记录通常比聚合库的同名转载更容易核验。
        return {"arxiv": 3, "openalex": 2, "crossref": 1}.get(paper.source, 0)

    @staticmethod
    def _is_quality_candidate(paper: Paper) -> bool:
        title = paper.title.strip()
        lower_title = title.lower()
        lower_doi = (paper.doi or "").lower()
        if lower_title.startswith(("figure ", "table ", "appendix ", "supplementary ")):
            return False
        if any(marker in lower_doi for marker in ["/fig-", "/figure-", "/table-", "/supp-"]):
            return False
        if paper.source == "crossref" and not (paper.abstract or paper.journal or paper.year):
            return False
        ascii_chars = sum(1 for char in title if char.isascii())
        if paper.source == "crossref" and title and ascii_chars / len(title) < 0.65 and not paper.abstract:
            return False
        return True
