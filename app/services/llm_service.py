import json
import re
from typing import Any

import httpx

from app.config import get_settings


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def status(self) -> dict[str, Any]:
        if not self.settings.use_ollama:
            return {"provider": "rule-based", "available": False, "model": self.settings.model_name, "message": "Ollama 已关闭，使用规则降级回答。"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                models = [item.get("name") for item in response.json().get("models", [])]
            return {
                "provider": "ollama",
                "available": self.settings.ollama_model in models,
                "model": self.settings.ollama_model,
                "installed_models": models,
                "message": "Ollama 可用" if self.settings.ollama_model in models else "Ollama 已启动，但未安装配置的模型。",
            }
        except Exception as exc:
            return {"provider": "ollama", "available": False, "model": self.settings.ollama_model, "installed_models": [], "message": f"Ollama 不可用：{exc}"}

    async def generate(self, prompt: str, temperature: float = 0.2) -> str | None:
        if not self.settings.use_ollama:
            return None
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "top_p": 0.9},
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.ollama_timeout) as client:
                response = await client.post(f"{self.settings.ollama_base_url}/api/generate", json=payload)
                response.raise_for_status()
                text = response.json().get("response", "").strip()
                return text or None
        except Exception:
            return None

    async def available(self) -> bool:
        """检查 LLM 是否可用于 Agent 编排（区别于仅生成文本）。"""
        if not self.settings.use_ollama:
            return False
        status = await self.status()
        return bool(status.get("available"))

    # ------------------------------------------------------------------ #
    # Worker Agent prompts
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_worker_plan_prompt(question: str, tool_schemas: list[dict[str, Any]], feedback: str = "") -> str:
        tools_desc = "\n".join(
            f"- {t['name']}: {t['description']} | 参数: {json.dumps(t['inputSchema'], ensure_ascii=False)}"
            for t in tool_schemas
        )
        feedback_section = f"\n\n上一轮 Judge 反馈（请据此调整工具选择和搜索词）：\n{feedback}" if feedback else ""
        return f"""你是 KnowledgePilot 的 Worker Agent。请分析用户问题，决定使用哪些工具获取证据。

可用工具：
{tools_desc}

用户问题：{question}{feedback_section}

请输出工具调用计划，严格使用 JSON 格式（不要加 markdown 代码块标记）：
{{"intent": "paper_search|paper_detail|evidence_qa|concept_qa|compare|trend", "tool_calls": [{{"name": "工具名", "arguments": {{...}}}}], "reasoning": "分析原因"}}
"""

    @staticmethod
    def build_worker_answer_prompt(question: str, evidence: list[dict[str, Any]], feedback: str = "") -> str:
        evidence_text = "\n\n".join(
            f"[证据 {i}] 标题: {item.get('title', '未知')} | DOI: {item.get('doi', '无')}\n摘要/片段: {(item.get('abstract') or item.get('text') or '')[:1200]}"
            for i, item in enumerate(evidence[:6], 1)
        )
        feedback_section = f"\n\n上一轮 Judge 反馈（请改进）：\n{feedback}" if feedback else ""
        return f"""你是 KnowledgePilot 的 Worker Agent。请基于证据回答用户问题。

用户问题：{question}
{feedback_section}

检索证据：
{evidence_text or "未检索到证据。"}

回答要求：
1. 使用中文。
2. 严格基于证据回答，不能编造证据中没有的信息。
3. 证据不足时明确说明"当前公开数据不足以确认"。
4. 如果用户要求详细分析，请分层深入讲解原理。
5. 结尾列出引用的论文标题和 DOI。
"""

    @staticmethod
    def build_compare_prompt(question: str, paper_a: dict[str, Any], paper_b: dict[str, Any]) -> str:
        return f"""你是 KnowledgePilot 的 Worker Agent。请基于两篇论文的元数据和摘要，生成方法层面的对比分析。

用户问题：{question}

论文一：
- 标题：{paper_a.get('title', '未知')}
- 年份：{paper_a.get('year', '未知')}
- 摘要：{(paper_a.get('abstract') or '无摘要')[:1500]}

论文二：
- 标题：{paper_b.get('title', '未知')}
- 年份：{paper_b.get('year', '未知')}
- 摘要：{(paper_b.get('abstract') or '无摘要')[:1500]}

对比要求：
1. 使用中文。
2. 按"研究问题、核心方法、关键技术差异、适用场景"四个维度对比。
3. 严格基于摘要内容，不能编造。
4. 摘要缺失的维度明确标注"公开摘要未提供相关信息"。
5. 输出 Markdown 表格 + 简短总结。
"""

    # ------------------------------------------------------------------ #
    # Judge Agent prompt
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_judge_prompt(question: str, answer: str, citations: list[dict[str, Any]]) -> str:
        citations_text = "\n".join(
            f"- [{i}] {c.get('title', '未知')} | DOI: {c.get('doi', '无')} | 证据: {c.get('evidence', '')[:400]}"
            for i, c in enumerate(citations[:6], 1)
        )
        return f"""你是 KnowledgePilot 的 Judge Agent。请评估 Worker Agent 的回答质量。

用户问题：{question}

Worker 的回答：
{answer[:3000]}

引用证据：
{citations_text or "无引用证据"}

评估维度：
1. 证据充分性：回答中的结论是否都有证据支持？有没有幻觉？
2. 引用真实性：引用的 DOI 是否在证据列表中？
3. 问题匹配度：回答是否真正回答了用户问题？
4. 拒答正确性：证据不足时是否正确拒答，而不是硬编答案？

请输出评估结果，严格使用 JSON 格式（不要加 markdown 代码块标记）：
{{"verdict": "pass" 或 "reject", "issues": ["问题1", "问题2"], "feedback": "给 Worker 的改进建议", "confidence": 0.0到1.0}}
"""

    # ------------------------------------------------------------------ #
    # Legacy prompts (kept for rule-fallback answer generation)
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_paper_qa_prompt(title: str, question: str, abstract: str, evidence_chunks: list[dict[str, Any]]) -> str:
        chunks_text = "\n\n".join(
            f"[证据片段 {index}]\n{item.get('text', '')[:1500]}" for index, item in enumerate(evidence_chunks[:5], 1)
        )
        if not chunks_text:
            chunks_text = "[证据片段 1]\n" + (abstract[:1800] if abstract else "无开放摘要。")
        return f"""你是 KnowledgePilot 科研论文分析 Agent。请严格基于给定证据回答用户问题，不能编造证据里没有的信息。

论文标题：{title}
用户问题：{question}

摘要：
{abstract[:2500] if abstract else "无开放摘要。"}

正文/检索证据：
{chunks_text}

回答要求：
1. 使用中文。
2. 如果用户要求"详细、原理、机制、结构"，请给出分层、深入但不空泛的原理分析。
3. 必须区分"证据中能确认"和"证据不足以确认"。
4. 不要输出英文长段原文，必要时只用简短证据说明。
5. 结尾给出"证据依据"小节，列出使用了哪些证据片段。
"""

    @staticmethod
    def build_concept_prompt(question: str, concept: str, evidence_papers: list[dict[str, Any]]) -> str:
        papers = "\n".join(
            f"[论文 {index}] {item['paper'].get('title')} | DOI: {item['paper'].get('doi') or '无'} | 摘要: {(item['paper'].get('abstract') or '')[:900]}"
            for index, item in enumerate(evidence_papers[:5], 1)
        )
        return f"""你是 KnowledgePilot 科研技术分析 Agent。请回答一个技术原理问题。

用户问题：{question}
技术主题：{concept}

可参考论文证据：
{papers or "未检索到足够论文证据。"}

回答要求：
1. 必须使用中文。
2. 面向研究生秋招项目答辩，解释要系统、准确、分层。
3. 按"核心思想、结构组成、计算流程、训练方式、优缺点、典型应用、与相关方法区别"组织。
4. 如果论文证据不足，可以使用通用机器学习知识，但要标注为"通用知识解释"，不能伪装成论文原文证据。
"""


def parse_json_response(text: str) -> dict[str, Any] | None:
    """从 LLM 输出中提取 JSON，兼容 markdown 代码块和额外文本。"""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


llm_service = LLMService()
