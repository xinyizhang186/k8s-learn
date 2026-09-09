import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings
from app.models import Paper


class Base(DeclarativeBase):
    pass


class PaperRow(Base):
    __tablename__ = "papers"
    source_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    doi: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    institutions_json: Mapped[str] = mapped_column(Text, default="[]")
    concepts_json: Mapped[str] = mapped_column(Text, default="[]")
    cited_by_count: Mapped[int] = mapped_column(Integer, default=0)
    is_oa: Mapped[bool] = mapped_column(Boolean, default=False)
    landing_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChunkRow(Base):
    __tablename__ = "paper_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(String(300), index=True)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[str] = mapped_column(String(100), index=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(60))
    answer: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column()
    trace_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(80), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    args_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    latency_ms: Mapped[float] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


def _normalise_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return url


engine = create_engine(
    _normalise_url(get_settings().database_url),
    connect_args={"check_same_thread": False} if get_settings().database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    init_db()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_papers(papers: list[Paper]) -> int:
    if not papers:
        return 0
    with session_scope() as session:
        saved = 0
        for paper in papers:
            row = session.get(PaperRow, paper.source_id)
            payload = {
                "source": paper.source,
                "doi": paper.doi,
                "title": paper.title,
                "abstract": paper.abstract,
                "year": paper.year,
                "journal": paper.journal,
                "authors_json": json.dumps(paper.authors, ensure_ascii=False),
                "institutions_json": json.dumps(paper.institutions, ensure_ascii=False),
                "concepts_json": json.dumps(paper.concepts, ensure_ascii=False),
                "cited_by_count": paper.cited_by_count,
                "is_oa": paper.is_oa,
                "landing_page_url": paper.landing_page_url,
                "pdf_url": paper.pdf_url,
                "retrieved_at": paper.retrieved_at or datetime.now(timezone.utc),
            }
            if row is None:
                session.add(PaperRow(source_id=paper.source_id, **payload))
                saved += 1
            else:
                for key, value in payload.items():
                    setattr(row, key, value)
        return saved


def row_to_paper(row: PaperRow) -> Paper:
    return Paper(
        source=row.source,
        source_id=row.source_id,
        doi=row.doi,
        title=row.title,
        abstract=row.abstract or "",
        year=row.year,
        journal=row.journal,
        authors=json.loads(row.authors_json or "[]"),
        institutions=json.loads(row.institutions_json or "[]"),
        concepts=json.loads(row.concepts_json or "[]"),
        cited_by_count=row.cited_by_count or 0,
        is_oa=bool(row.is_oa),
        landing_page_url=row.landing_page_url,
        pdf_url=row.pdf_url,
        retrieved_at=row.retrieved_at,
    )


def get_paper(source_id: str) -> Paper | None:
    with session_scope() as session:
        row = session.get(PaperRow, source_id)
        return row_to_paper(row) if row else None


def list_local_papers(limit: int = 500) -> list[Paper]:
    with session_scope() as session:
        rows = session.scalars(select(PaperRow).order_by(PaperRow.cited_by_count.desc()).limit(limit)).all()
        return [row_to_paper(row) for row in rows]


def save_chunks(paper_id: str, chunks: list[str], replace: bool = True) -> int:
    if not chunks:
        return 0
    with session_scope() as session:
        if replace:
            session.execute(delete(ChunkRow).where(ChunkRow.paper_id == paper_id))
        saved = 0
        for text in chunks:
            clean = " ".join(text.split())
            if len(clean) < 80:
                continue
            digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
            session.add(ChunkRow(paper_id=paper_id, text=clean, text_hash=digest))
            saved += 1
        return saved


def get_chunks(paper_id: str) -> list[str]:
    with session_scope() as session:
        rows = session.scalars(select(ChunkRow).where(ChunkRow.paper_id == paper_id).order_by(ChunkRow.id.asc())).all()
        return [row.text for row in rows]


def count_chunks(paper_id: str | None = None) -> int:
    with session_scope() as session:
        if paper_id:
            return len(session.scalars(select(ChunkRow.id).where(ChunkRow.paper_id == paper_id)).all())
        return len(session.scalars(select(ChunkRow.id)).all())


def save_run(trace_id: str, session_id: str, query: str, intent: str, answer: str, latency_ms: float, trace: list[dict[str, Any]]) -> None:
    with session_scope() as session:
        session.add(
            AgentRunRow(
                trace_id=trace_id,
                session_id=session_id,
                query=query,
                intent=intent,
                answer=answer,
                latency_ms=latency_ms,
                trace_json=json.dumps(trace, ensure_ascii=False),
            )
        )


def save_tool_call(trace_id: str, name: str, args: dict[str, Any], status: str, latency_ms: float, error: str | None = None) -> None:
    with session_scope() as session:
        session.add(
            ToolCallRow(
                trace_id=trace_id,
                tool_name=name,
                args_json=json.dumps(args, ensure_ascii=False),
                status=status,
                latency_ms=latency_ms,
                error=error,
            )
        )
