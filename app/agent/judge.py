"""Judge Agent: LLM-driven answer evaluation with rule-based fallback."""

import re
from typing import Any

from app.models import JudgeVerdict
from app.services.llm_service import llm_service, parse_json_response


class JudgeAgent:
    """Judge Agent：评估 Worker 草稿质量，输出 PASS / REJECT + 反馈。

    LLM 可用时：LLM 从证据充分性、引用真实性、问题匹配度、拒答正确性四个维度评估。
    LLM 不可用时：规则检查 DOI 存在性、答案非空、拒答场景正确性。
    """

    # 问题匹配度检查的关键词
    _REFUSAL_MARKERS = ("没有找到", "不足以确认", "未找到", "暂不", "当前公开数据不足")

    async def evaluate(self, question: str, draft: Any) -> JudgeVerdict:
        """评估 Worker 草稿。

        对需要语义理解的意图（evidence_qa, concept_qa）用 LLM 评估；
        对结构化意图（paper_search, paper_detail, compare, trend）用规则检查足够。
        """
        if draft.intent in ("evidence_qa", "concept_qa", "compare"):
            llm_verdict = await self._evaluate_with_llm(question, draft)
            if llm_verdict:
                return llm_verdict
        return self._evaluate_with_rules(question, draft)

    # ------------------------------------------------------------------ #
    # LLM-driven path
    # ------------------------------------------------------------------ #

    async def _evaluate_with_llm(self, question: str, draft: Any) -> JudgeVerdict | None:
        citations_data = [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in draft.citations]
        prompt = llm_service.build_judge_prompt(question, draft.answer, citations_data)
        raw = await llm_service.generate(prompt, temperature=0.1)
        if not raw:
            return None
        data = parse_json_response(raw)
        if not data or "verdict" not in data:
            return None
        verdict_str = str(data["verdict"]).strip().lower()
        if verdict_str not in ("pass", "reject"):
            return None
        return JudgeVerdict(
            verdict=verdict_str,
            issues=data.get("issues", []) if isinstance(data.get("issues"), list) else [],
            feedback=str(data.get("feedback", "")),
            confidence=float(data.get("confidence", 0.5)),
        )

    # ------------------------------------------------------------------ #
    # Rule-based fallback path
    # ------------------------------------------------------------------ #

    def _evaluate_with_rules(self, question: str, draft: Any) -> JudgeVerdict:
        """规则降级评估：检查引用 DOI 真实性 + 答案非空 + 拒答正确性。"""
        issues: list[str] = []

        # 1. 答案非空检查
        if not draft.answer or len(draft.answer.strip()) < 10:
            issues.append("答案过短或为空")
            return JudgeVerdict(verdict="reject", issues=issues, feedback="答案内容过短，请补充证据和分析。", confidence=0.9)

        # 2. 引用真实性：检查 citations 中的 DOI 是否在 evidence 中存在
        evidence_dois = self._extract_evidence_dois(draft.evidence)
        fabricated = []
        for citation in draft.citations:
            if citation.doi:
                normalized = citation.doi.lower().replace("https://doi.org/", "")
                if normalized and normalized not in evidence_dois:
                    fabricated.append(citation.doi)
        if fabricated:
            issues.append(f"引用的 DOI 不在检索证据中: {', '.join(fabricated[:3])}")

        # 3. 拒答正确性：如果证据不足但答案没有拒答标记，可能是硬编答案
        has_evidence = bool(draft.citations) or len(draft.evidence) > 0
        has_refusal = any(marker in draft.answer for marker in self._REFUSAL_MARKERS)
        if not has_evidence and not has_refusal:
            issues.append("没有检索到证据，但答案未明确拒答")

        # 4. 问题匹配度：检查答案是否包含问题中的关键内容（中英文均检查）
        #    先清理查询意图词（"介绍""原理""分析"等），只保留内容词参与匹配
        cleaned = question
        for w in ["请", "详细", "介绍", "原理", "分析", "是什么", "怎么样", "如何",
                   "比较", "对比", "区别", "查询", "搜索", "查找", "关于", "有关",
                   "方法", "机制", "结构", "逐步", "为什么", "讲解"]:
            cleaned = cleaned.replace(w, "")
        question_english_words = set(word.lower() for word in question.split() if len(word) > 3 and word.isascii())
        question_chinese_words = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", cleaned):
            for i in range(len(run) - 1):
                question_chinese_words.add(run[i : i + 2])
        if (question_english_words or question_chinese_words) and has_evidence:
            answer_lower = draft.answer.lower()
            matched = sum(1 for word in question_english_words if word in answer_lower)
            matched += sum(1 for word in question_chinese_words if word in draft.answer)
            if matched == 0:
                issues.append("答案可能没有直接回答用户问题")

        if issues:
            return JudgeVerdict(
                verdict="reject",
                issues=issues,
                feedback="请检查以下问题并重新生成：" + "；".join(issues),
                confidence=0.7,
            )
        return JudgeVerdict(verdict="pass", issues=[], feedback="", confidence=0.8)

    @staticmethod
    def _extract_evidence_dois(evidence: list[dict[str, Any]]) -> set[str]:
        """从证据数据中提取所有 DOI。"""
        dois: set[str] = set()
        for item in evidence:
            doi = item.get("doi")
            if doi:
                dois.add(doi.lower().replace("https://doi.org/", ""))
        return dois
