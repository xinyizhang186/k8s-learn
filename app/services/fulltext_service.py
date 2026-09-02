import hashlib
import re
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from app.config import get_settings
from app.db.database import get_chunks, save_chunks
from app.models import Paper
from app.retrieval.hybrid import score
from app.retrieval.vector import section_bonus, vector_similarity


class FullTextService:
    def __init__(self) -> None:
        self.pdf_dir = Path("data") / "pdfs"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_chunks(self, paper: Paper) -> dict:
        existing = get_chunks(paper.source_id)
        if existing:
            return {"status": "cached", "chunk_count": len(existing), "source": "database"}
        if paper.pdf_url:
            try:
                text = await self._download_and_extract(paper.pdf_url)
                chunks = self.chunk_text(text)
                saved = save_chunks(paper.source_id, chunks)
                if saved:
                    return {"status": "downloaded", "chunk_count": saved, "source": paper.pdf_url}
            except Exception as exc:
                if not paper.abstract:
                    return {"status": "failed", "chunk_count": 0, "error": str(exc)}
        if paper.abstract:
            saved = save_chunks(paper.source_id, self.chunk_text(paper.abstract), replace=True)
            return {"status": "abstract_only", "chunk_count": saved, "source": "abstract"}
        return {"status": "no_open_text", "chunk_count": 0, "source": ""}

    def retrieve(self, paper: Paper, question: str, top_k: int = 4) -> list[dict]:
        chunks = get_chunks(paper.source_id)
        ranked = []
        for text in chunks:
            lexical = score(question, Paper(source=paper.source, source_id=paper.source_id, title=paper.title, abstract=text))
            semantic = vector_similarity(question, text)
            bonus = section_bonus(question, text)
            combined = 0.55 * lexical + 0.35 * semantic + bonus
            ranked.append((text, combined, lexical, semantic, bonus))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [
            {
                "text": text,
                "score": round(combined, 4),
                "lexical_score": round(lexical, 4),
                "vector_score": round(semantic, 4),
                "section_bonus": round(bonus, 4),
            }
            for text, combined, lexical, semantic, bonus in ranked[:top_k]
            if combined >= 0.05
        ]

    async def _download_and_extract(self, url: str) -> str:
        target = self.pdf_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.pdf"
        if target.exists() and target.stat().st_size > 0:
            data = target.read_bytes()
        else:
            async with httpx.AsyncClient(timeout=get_settings().request_timeout, follow_redirects=True, headers={"User-Agent": "KnowledgePilot/0.1"}) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.content
            if not data.startswith(b"%PDF"):
                raise ValueError("下载内容不是 PDF")
            target.write_bytes(data)
        reader = PdfReader(BytesIO(data))
        pages = []
        for page in reader.pages[:30]:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages)
        text = re.sub(r"-\s*\n\s*", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def chunk_text(text: str, size: int = 1200, overlap: int = 180) -> list[str]:
        clean = " ".join(text.split())
        if not clean:
            return []
        chunks = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + size)
            chunks.append(clean[start:end])
            if end == len(clean):
                break
            start = max(0, end - overlap)
        return chunks
