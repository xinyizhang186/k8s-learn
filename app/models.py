from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Paper(BaseModel):
    source: str
    source_id: str
    doi: str | None = None
    title: str
    abstract: str = ""
    year: int | None = None
    journal: str | None = None
    authors: list[str] = Field(default_factory=list)
    institutions: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    cited_by_count: int = 0
    is_oa: bool = False
    landing_page_url: str | None = None
    pdf_url: str | None = None
    retrieved_at: datetime | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=30)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    online: bool = True


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str = "default"


class Citation(BaseModel):
    paper_id: str
    title: str
    doi: str | None = None
    url: str | None = None
    evidence: str = ""


class JudgeVerdict(BaseModel):
    verdict: str  # "pass" | "reject"
    issues: list[str] = Field(default_factory=list)
    feedback: str = ""
    confidence: float = 0.0


class AgentResponse(BaseModel):
    answer: str
    intent: str
    confidence: float
    citations: list[Citation] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float
    cache_hit: bool = False
    iterations: int = 1
    judge_verdict: str = "pass"


class SyncRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    pages: int = Field(default=1, ge=1, le=5)
    per_page: int = Field(default=50, ge=1, le=200)


class FullTextRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=500)
