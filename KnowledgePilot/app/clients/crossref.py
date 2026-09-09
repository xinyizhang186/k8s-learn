from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.models import Paper


class CrossrefClient:
    base_url = "https://api.crossref.org/works"

    async def search(self, query: str, top_k: int = 10) -> list[Paper]:
        params = {"query.bibliographic": query, "rows": top_k, "select": "DOI,title,author,published,container-title,URL,type"}
        async with httpx.AsyncClient(timeout=get_settings().request_timeout, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            return [self._to_paper(item) for item in response.json().get("message", {}).get("items", []) if self._is_paper_record(item)]

    async def get(self, doi: str) -> Paper | None:
        async with httpx.AsyncClient(timeout=get_settings().request_timeout, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
            response = await client.get(f"{self.base_url}/{doi}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return self._to_paper(response.json().get("message", {}))

    def _to_paper(self, item: dict[str, Any]) -> Paper:
        date_parts = (item.get("published") or {}).get("date-parts") or [[]]
        year = date_parts[0][0] if date_parts[0] else None
        authors = [a.get("given", "") + " " + a.get("family", "") for a in item.get("author") or []]
        authors = [" ".join(a.split()) for a in authors if a.strip()]
        title = (item.get("title") or [""])[0].strip()
        doi = item.get("DOI")
        return Paper(
            source="crossref",
            source_id=f"crossref:{doi or item.get('URL', title)}",
            doi=doi,
            title=title,
            year=year,
            journal=(item.get("container-title") or [None])[0],
            authors=authors,
            landing_page_url=item.get("URL"),
            retrieved_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _is_paper_record(item: dict[str, Any]) -> bool:
        doi = (item.get("DOI") or "").lower()
        title = " ".join(item.get("title") or []).lower()
        item_type = item.get("type")
        date_parts = (item.get("published") or {}).get("date-parts") or [[]]
        allowed_types = {"journal-article", "proceedings-article", "posted-content", "book-chapter", "book-section"}
        if item_type and item_type not in allowed_types:
            return False
        if not date_parts[0]:
            return False
        if any(marker in doi for marker in ["/fig-", "/figure-", "/table-", "/supp-"]):
            return False
        if title.startswith(("figure ", "table ", "appendix ", "supplementary ")):
            return False
        return bool(title)
