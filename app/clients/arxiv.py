import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.models import Paper


class ArxivClient:
    """轻量 arXiv Atom 客户端，作为计算机/AI 论文的开放数据增强源。"""

    base_url = "https://export.arxiv.org/api/query"
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    async def search(self, query: str, top_k: int = 10) -> list[Paper]:
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", query)
        if not words:
            return []
        # Atom API 对 title AND 查询比直接把整句塞进 ti 更稳定。
        stop_words = {"is", "are", "the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "with"}
        meaningful = [word for word in words if word.lower() not in stop_words]
        search_query = "ti:(" + " AND ".join(meaningful[:8] or words[:8]) + ")"
        params = {"search_query": search_query, "start": 0, "max_results": top_k, "sortBy": "relevance"}
        async with httpx.AsyncClient(timeout=get_settings().request_timeout, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        root = ET.fromstring(response.text)
        return [self._to_paper(entry) for entry in root.findall("atom:entry", self.ns)]

    async def get(self, identifier: str) -> Paper | None:
        arxiv_id = identifier
        if "arxiv.org" in identifier:
            arxiv_id = identifier.rstrip("/").rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        async with httpx.AsyncClient(timeout=get_settings().request_timeout, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
            response = await client.get(self.base_url, params={"id_list": arxiv_id, "max_results": 1})
            response.raise_for_status()
        root = ET.fromstring(response.text)
        entry = root.find("atom:entry", self.ns)
        return self._to_paper(entry) if entry is not None else None

    def _to_paper(self, entry: ET.Element) -> Paper:
        identifier = (entry.findtext("atom:id", default="", namespaces=self.ns) or "").strip()
        abs_url = re.sub(r"v\d+$", "", identifier.replace("http://", "https://"))
        arxiv_id = abs_url.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        title = " ".join((entry.findtext("atom:title", default="", namespaces=self.ns) or "").split())
        abstract = " ".join((entry.findtext("atom:summary", default="", namespaces=self.ns) or "").split())
        published = entry.findtext("atom:published", default="", namespaces=self.ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            " ".join((author.findtext("atom:name", default="", namespaces=self.ns) or "").split())
            for author in entry.findall("atom:author", self.ns)
        ]
        authors = [author for author in authors if author]
        pdf_url = None
        for link in entry.findall("atom:link", self.ns):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
                break
        return Paper(
            source="arxiv",
            source_id=f"arxiv:{arxiv_id}",
            doi=f"10.48550/arXiv.{arxiv_id.split('v')[0]}",
            title=title,
            abstract=abstract,
            year=year,
            authors=authors,
            is_oa=True,
            landing_page_url=abs_url,
            pdf_url=pdf_url,
            retrieved_at=datetime.now(timezone.utc),
        )
