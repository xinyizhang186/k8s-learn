"""KnowledgePilot Agent: Worker-Judge dual-agent orchestrator.

Worker Agent: LLM-driven tool selection and answer generation with rule fallback.
Judge Agent: LLM-driven answer evaluation with rule fallback.
Orchestrator: Worker→Judge→feedback→retry loop (max N iterations).

On Judge rejection, Worker changes strategy:
- LLM path: feeds Judge feedback into both planning and generation prompts
- Rule path: broadens search keywords and lowers score threshold
"""

import re
import time
import uuid
from typing import Any

from app.agent.judge import JudgeAgent
from app.agent.worker import WorkerAgent, WorkerDraft
from app.db.database import save_run
from app.models import AgentResponse, Citation, Paper
from app.services.fulltext_service import FullTextService
from app.services.llm_service import llm_service
from app.services.paper_service import PaperService
from app.tools.registry import ToolRegistry

LLM_INTENTS = {"concept_qa", "evidence_qa", "compare"}


class KnowledgePilotAgent:
    """双 Agent 编排器：Worker 生成 → Judge 评估 → 反馈重试循环。"""

    MAX_ITERATIONS = 3
    _session_memory: dict[str, dict[str, str]] = {}

    def __init__(self) -> None:
        self.papers = PaperService()
        self.fulltext = FullTextService()
        self.registry = ToolRegistry()
        self.worker = WorkerAgent(self.registry)
        self.judge = JudgeAgent()

        self.registry.register(
            "search_papers",
            "从 OpenAlex、Crossref 和本地索引检索论文",
            {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
            self.papers.search,
        )
        self.registry.register(
            "get_paper",
            "根据 OpenAlex ID 或 DOI 获取论文详情",
            {"type": "object", "properties": {"identifier": {"type": "string"}}, "required": ["identifier"]},
            self.papers.get,
        )
        self.registry.register(
            "ensure_fulltext",
            "下载开放 PDF、抽取论文正文并写入本地分块库",
            {"type": "object", "properties": {"identifier": {"type": "string"}}, "required": ["identifier"]},
            self.ensure_fulltext,
        )

    async def ensure_fulltext(self, identifier: str) -> dict[str, Any]:
        paper = await self.papers.get(identifier)
        if not paper:
            payload, _ = await self.papers.search(identifier, top_k=1, online=True)
            paper = Paper.model_validate(payload[0]["paper"]) if payload else None
        if not paper:
            return {"status": "not_found", "chunk_count": 0}
        result = await self.fulltext.ensure_chunks(paper)
        result["paper_id"] = paper.source_id
        result["title"] = paper.title
        return result

    @staticmethod
    def rewrite(query: str) -> str:
        text = re.sub(r"[""\"']", " ", query).strip()
        text = re.sub(r"\s+", " ", text)
        return text

    async def run(self, query: str, session_id: str = "default") -> AgentResponse:
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex[:16]
        trace: list[dict[str, Any]] = []

        prev = self._session_memory.get(session_id)
        if prev:
            trace.append({"step": "Session Memory", "prev_query": prev["query"][:80], "prev_intent": prev["intent"]})

        rewritten = self.rewrite(query)
        trace.append({"step": "Query Rewrite", "status": "success", "output": rewritten})

        llm_ready = await llm_service.available()
        trace.append({"step": "LLM Status", "available": llm_ready, "provider": "ollama" if llm_ready else "rule-based"})

        intent = self.worker.classify(rewritten)
        trace.append({"step": "Intent Router", "intent": intent, "llm_eligible": intent in LLM_INTENTS and llm_ready})

        draft = None
        verdict = None
        feedback = ""

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            trace.append({"step": f"Worker Iteration {iteration}", "feedback": feedback or None})

            use_llm = intent in LLM_INTENTS and llm_ready
            context_hint = f"上一轮对话：用户问了「{prev['query'][:100]}」，回答了关于 {prev['intent']}。当前问题可能是追问。" if prev else ""
            if use_llm:
                draft = await self._run_worker_llm(rewritten, intent, trace_id, trace, feedback, iteration, context_hint)
            if draft is None:
                draft = await self.worker.run_rule(rewritten, trace_id, trace, feedback, iteration)

            trace.append({
                "step": f"Worker Draft {iteration}",
                "intent": draft.intent,
                "confidence": draft.confidence,
                "citations": len(draft.citations),
                "cache_hit": draft.cache_hit,
                "answer_preview": draft.answer[:200],
                "worker_mode": "llm" if use_llm else "rule",
            })

            verdict = await self.judge.evaluate(rewritten, draft)
            trace.append({
                "step": f"Judge Verdict {iteration}",
                "verdict": verdict.verdict,
                "issues": verdict.issues,
                "confidence": verdict.confidence,
                "feedback": verdict.feedback,
            })

            if verdict.verdict == "pass":
                break

            feedback = verdict.feedback
            if iteration < self.MAX_ITERATIONS:
                trace.append({"step": "Retry", "reason": verdict.issues, "strategy_change": "broaden_search" if not use_llm else "llm_feedback_rewrite"})

        latency = round((time.perf_counter() - started) * 1000, 2)
        final_verdict = verdict.verdict if verdict else "pass"
        trace.append({"step": "Final Answer", "verdict": final_verdict, "iterations": iteration, "latency_ms": latency})

        save_run(trace_id, session_id, query, draft.intent, draft.answer, latency, trace)

        self._session_memory[session_id] = {"query": query, "intent": draft.intent, "answer": draft.answer[:500]}

        return AgentResponse(
            answer=draft.answer,
            intent=draft.intent,
            confidence=draft.confidence,
            citations=draft.citations,
            trace=trace,
            latency_ms=latency,
            cache_hit=draft.cache_hit,
            iterations=iteration,
            judge_verdict=final_verdict,
        )

    async def _run_worker_llm(self, query: str, intent: str, trace_id: str, trace: list[dict[str, Any]], feedback: str = "", iteration: int = 1, context_hint: str = "") -> WorkerDraft | None:
        """LLM 驱动的 Worker 路径：Thought → 规划 → 执行工具 → 生成答案。

        返回 None 时降级到规则路径。
        """

        if iteration > 1 and feedback:
            trace.append({
                "step": "Thought",
                "iteration": iteration,
                "reasoning": f"上一轮被 Judge 拒绝（{feedback[:200]}），本轮将根据反馈调整搜索策略和答案生成。",
            })
        else:
            thought_msg = f"用户意图为 {intent}，需要通过检索论文获取证据后生成回答。先规划工具调用。"
            if context_hint:
                thought_msg += f" 上下文提示：{context_hint}"
            trace.append({
                "step": "Thought",
                "iteration": iteration,
                "reasoning": thought_msg,
            })

        plan = await self.worker.plan_with_llm(query, feedback if iteration > 1 else "")
        if not plan:
            trace.append({"step": "Worker Planner (LLM)", "status": "fallback_to_rule", "reason": "LLM planning failed"})
            return None

        tool_calls = plan.get("tool_calls", [])
        trace.append({
            "step": "Worker Planner (LLM)",
            "intent": intent,
            "llm_intent": plan.get("intent"),
            "tool_calls": len(tool_calls),
            "reasoning": plan.get("reasoning", ""),
        })

        if not tool_calls:
            trace.append({"step": "Worker Planner (LLM)", "status": "fallback_to_rule", "reason": "no tool_calls in plan"})
            return None

        evidence: list[dict[str, Any]] = []
        cache_hit = False
        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("arguments", {})
            if not name or name not in self.registry.tools:
                continue
            try:
                result = await self.registry.call(name, args, trace_id)
                cache_hit = cache_hit or self._extract_cache_hit(result)
                evidence.extend(self._normalize_evidence(result))
                trace.append({"step": "Tool Calling (LLM)", "tool": name, "args": args, "evidence_count": len(self._normalize_evidence(result))})
            except Exception as exc:
                trace.append({"step": "Tool Calling (LLM)", "tool": name, "status": "error", "error": str(exc)})

        trace.append({"step": "Observation", "evidence_count": len(evidence), "cache_hit": cache_hit})

        if not evidence:
            answer = "当前公开数据不足以确认这个问题。请提供论文 DOI、标题片段，或先搜索目标论文。"
            return WorkerDraft(answer, intent, 0.0, [], cache_hit, evidence)

        llm_answer = await self.worker.generate_with_llm(query, evidence, feedback)
        trace.append({"step": "Worker Generator (LLM)", "used": bool(llm_answer)})

        if llm_answer:
            answer = llm_answer
        else:
            trace.append({"step": "Worker Generator", "status": "fallback_to_rule"})
            return None

        citations = [self._citation_from_evidence(item) for item in evidence[:5]]
        confidence = min(0.95, 0.5 + len(evidence) * 0.08)
        return WorkerDraft(answer, intent, confidence, citations, cache_hit, evidence)

    @staticmethod
    def _extract_cache_hit(result: Any) -> bool:
        if isinstance(result, tuple) and len(result) == 2:
            return result[1]
        return False

    @staticmethod
    def _normalize_evidence(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, list):
            items = result
        elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], list):
            items = result[0]
        else:
            return []
        evidence = []
        for item in items:
            if isinstance(item, dict) and "paper" in item:
                evidence.append(item["paper"])
            elif hasattr(item, "model_dump"):
                evidence.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                evidence.append(item)
        return evidence

    @staticmethod
    def _citation_from_evidence(paper: dict[str, Any]) -> Citation:
        return Citation(
            paper_id=paper.get("source_id", ""),
            title=paper.get("title", ""),
            doi=paper.get("doi"),
            url=paper.get("landing_page_url") or paper.get("pdf_url"),
            evidence=(paper.get("abstract") or paper.get("title", ""))[:350],
        )


agent = KnowledgePilotAgent()
