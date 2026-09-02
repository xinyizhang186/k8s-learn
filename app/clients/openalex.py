from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.models import Paper


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words = sorted(((position, word) for word, positions in index.items() for position in positions), key=lambda item: item[0])
    return " ".join(word for _, word in words)


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    async def search(self, query: str, top_k: int = 10, year_from: int | None = None, year_to: int | None = None, page: int = 1) -> list[Paper]:
        params: dict[str, Any] = {"search": query, "per-page": top_k, "page": page}
        if get_settings().openalex_email:
            params["mailto"] = get_settings().openalex_email
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        async with httpx.AsyncClient(timeout=get_settings().request_timeout, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
            response = await client.get(f"{self.base_url}/works", params=params)
            response.raise_for_status()
            return [self._to_paper(item) for item in response.json().get("results", [])]

    async def get(self, source_id: str) -> Paper | None:
        url = source_id if source_id.startswith("http") else f"{self.base_url}/works/{source_id}"
        async with httpx.AsyncClient(timeout=get_settings().request_timeout) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return self._to_paper(response.json())

    def _to_paper(self, item: dict[str, Any]) -> Paper:
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        oa = item.get("open_access") or {}
        best_oa = item.get("best_oa_location") or {}
        ids = item.get("ids") or {}
        doi = item.get("doi") or ids.get("doi")
        authors = []
        institutions = []
        for authorship in item.get("authorships") or []:
            author = authorship.get("author") or {}
            if author.get("display_name"):
                authors.append(author["display_name"])
            for institution in authorship.get("institutions") or []:
                if institution.get("display_name") and institution["display_name"] not in institutions:
                    institutions.append(institution["display_name"])
        concepts = [c.get("display_name") for c in item.get("concepts") or [] if c.get("display_name")]
        return Paper(
            source="openalex",
            source_id=item.get("id", ""),
            doi=doi.removeprefix("https://doi.org/") if doi else None,
            title=(item.get("title") or "").strip(),
            abstract=_abstract_from_inverted_index(item.get("abstract_inverted_index")),
            year=item.get("publication_year"),
            journal=source.get("display_name"),
            authors=authors,
            institutions=institutions,
            concepts=concepts,
            cited_by_count=item.get("cited_by_count") or 0,
            is_oa=bool(oa.get("is_oa")),
            landing_page_url=best_oa.get("landing_page_url") or primary.get("landing_page_url") or item.get("id"),
            pdf_url=(best_oa.get("pdf_url") or {}).get("url") if isinstance(best_oa.get("pdf_url"), dict) else best_oa.get("pdf_url"),
            retrieved_at=datetime.now(timezone.utc),
        )
