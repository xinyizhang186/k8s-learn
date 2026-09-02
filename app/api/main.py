from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent.engine import agent
import json
from pathlib import Path

from app.db.database import count_chunks, init_db, list_local_papers
from app.mcp.server import router as mcp_router
from app.models import ChatRequest, FullTextRequest, SearchRequest, SyncRequest
from app.services.llm_service import llm_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="KnowledgePilot 科研检索与推理 Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(mcp_router)


@app.get("/")
async def root():
    return {
        "service": "KnowledgePilot",
        "message": "API 服务已启动。网页请打开 http://127.0.0.1:8501，接口文档请打开 http://127.0.0.1:8000/docs。",
        "ui": "http://127.0.0.1:8501",
        "docs": "http://127.0.0.1:8000/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "KnowledgePilot", "local_papers": len(list_local_papers()), "fulltext_chunks": count_chunks()}


@app.post("/api/search")
async def search(request: SearchRequest):
    try:
        results, cache_hit = await agent.papers.search(request.query, request.top_k, request.year_from, request.year_to, request.online)
        if not results and request.online:
            results, cache_hit = await agent.papers.search(request.query, request.top_k, request.year_from, request.year_to, online=False)
        return {"query": request.query, "cache_hit": cache_hit, "count": len(results), "results": results, "source": "online" if request.online and not cache_hit else "cache"}
    except Exception as exc:
        try:
            results, _ = await agent.papers.search(request.query, request.top_k, online=False)
            if results:
                return {"query": request.query, "cache_hit": False, "count": len(results), "results": results, "source": "local_fallback"}
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"论文数据源请求失败，请稍后重试或先运行 python scripts/warmup_demo.py 预热缓存: {exc}") from exc


@app.get("/api/papers/{source_id:path}")
async def paper_detail(source_id: str):
    paper = await agent.papers.get(source_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


@app.post("/api/chat")
async def chat(request: ChatRequest):
    return await agent.run(request.query, request.session_id)


@app.post("/api/sync")
async def sync(request: SyncRequest):
    try:
        return await agent.papers.sync(request.query, request.pages, request.per_page)
    except Exception as exc:
        local = list_local_papers()
        if local:
            return {"fetched": 0, "unique": len(local), "saved": 0, "source": "local_fallback", "message": f"数据源繁忙，已使用本地 {len(local)} 条缓存论文"}
        raise HTTPException(status_code=502, detail=f"同步失败，请先运行 python scripts/warmup_demo.py 预热缓存: {exc}") from exc


@app.post("/api/fulltext")
async def fulltext(request: FullTextRequest):
    return await agent.ensure_fulltext(request.identifier)


@app.get("/api/evaluation/latest")
async def latest_evaluation():
    path = Path("harness") / "reports" / "latest.json"
    if not path.exists():
        return {"status": "empty", "message": "尚未运行评测，请先执行 python harness/evaluate.py"}
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/evaluation/run")
async def run_evaluation():
    from harness.evaluate import evaluate

    report = await evaluate()
    output = Path("harness") / "reports"
    output.mkdir(exist_ok=True)
    (output / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


@app.get("/api/stats")
async def stats():
    cache = agent.papers.cache
    return {"local_papers": len(list_local_papers()), "fulltext_chunks": count_chunks(), "cache_hits": cache.hits, "cache_misses": cache.misses, "cache_hit_rate": round(cache.hit_rate, 4)}


@app.get("/api/model/status")
async def model_status():
    return await llm_service.status()


def run():
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
