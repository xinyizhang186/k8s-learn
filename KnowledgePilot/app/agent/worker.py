"""Worker Agent: LLM-driven tool selection and answer generation with rule fallback."""

import re
from typing import Any

from app.models import Citation, Paper
from app.services.llm_service import llm_service, parse_json_response
from app.tools.registry import ToolRegistry


class WorkerDraft:
    """Worker 单轮生成的草稿。"""

    def __init__(self, answer: str, intent: str, confidence: float, citations: list[Citation], cache_hit: bool, evidence: list[dict[str, Any]]) -> None:
        self.answer = answer
        self.intent = intent
        self.confidence = confidence
        self.citations = citations
        self.cache_hit = cache_hit
        self.evidence = evidence  # 原始证据数据，供 Judge 校验


class WorkerAgent:
    """Worker Agent：理解问题 → 选择工具 → 获取证据 → 生成答案。

    LLM 可用时：LLM 决定工具调用计划 + LLM 生成答案。
    LLM 不可用时：规则路由（classify）+ 规则生成（_summarize_cn / _concept_fallback）。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------ #
    # LLM-driven path
    # ------------------------------------------------------------------ #

    async def plan_with_llm(self, question: str, feedback: str = "") -> dict[str, Any] | None:
        """LLM 决定工具调用计划。feedback 非空时告知 LLM 上轮被拒原因。返回 None 时降级。"""
        prompt = llm_service.build_worker_plan_prompt(question, self.registry.schemas(), feedback)
        raw = await llm_service.generate(prompt, temperature=0.1)
        if not raw:
            return None
        plan = parse_json_response(raw)
        if plan and "tool_calls" in plan:
            return plan
        return None

    async def generate_with_llm(self, question: str, evidence: list[dict[str, Any]], feedback: str = "") -> str | None:
        """LLM 基于证据生成答案。返回 None 时降级到规则生成。"""
        prompt = llm_service.build_worker_answer_prompt(question, evidence, feedback)
        return await llm_service.generate(prompt, temperature=0.3)

    # ------------------------------------------------------------------ #
    # Rule-based fallback path (migrated from original engine.py)
    # ------------------------------------------------------------------ #

    @staticmethod
    def classify(query: str) -> str:
        lower = query.lower()
        if any(word in query for word in ["趋势", "增长", "年度", "研究方向", "trend"]):
            return "trend"
        if any(word in query for word in ["比较", "对比", "区别", "compare"]):
            return "compare"
        if any(word in query for word in ["作者", "期刊", "doi", "DOI", "发表", "年份"]):
            return "paper_detail"
        if WorkerAgent._is_concept_question(query):
            return "concept_qa"
        if any(word in query for word in ["是什么", "提出", "方法", "数据集", "解决", "如何", "贡献", "原理", "详细", "机制", "结构"]):
            return "evidence_qa"
        return "paper_search"

    async def run_rule(self, query: str, trace_id: str, trace: list[dict[str, Any]], feedback: str = "", iteration: int = 1) -> WorkerDraft:
        """规则降级路径：classify → 分发到 6 路意图处理器。

        iteration > 1 时根据 feedback 改写搜索词（去掉更多噪声词、降低阈值）。
        """
        intent = self.classify(query)
        trace.append({"step": "Router (rule)", "intent": intent, "iteration": iteration, "has_feedback": bool(feedback)})

        search_query = query
        if iteration > 1 and feedback:
            for word in ["请", "详细", "介绍", "的", "是", "什么", "提出", "了", "方法", "原理", "分析", "这篇论文"]:
                search_query = search_query.replace(word, " ")
            search_query = re.sub(r"\s+", " ", search_query).strip()
            trace.append({"step": "Query Broaden (retry)", "original": query[:80], "broadened": search_query[:80]})

        if intent == "paper_search":
            answer, citations, confidence, cache_hit, evidence = await self._search(search_query, trace_id, trace)
        elif intent == "paper_detail":
            answer, citations, confidence, cache_hit, evidence = await self._detail(search_query, trace_id, trace)
        elif intent == "evidence_qa":
            answer, citations, confidence, cache_hit, evidence = await self._qa(search_query, trace_id, trace)
        elif intent == "concept_qa":
            answer, citations, confidence, cache_hit, evidence = await self._concept_qa(search_query, trace_id, trace)
        elif intent == "compare":
            answer, citations, confidence, cache_hit, evidence = await self._compare(search_query, trace_id, trace)
        else:
            answer, citations, confidence, cache_hit, evidence = await self._trend(search_query, trace_id, trace)
        return WorkerDraft(answer, intent, confidence, citations, cache_hit, evidence)

    # ------------------------------------------------------------------ #
    # Six intent handlers (rule fallback)
    # ------------------------------------------------------------------ #

    async def _search(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        trace.append({"step": "Planner", "plan": ["search_papers", "rank", "cite"]})
        payload, cache_hit = await self.registry.call("search_papers", {"query": query, "top_k": 8}, trace_id)
        trace.append({"step": "Observation", "count": len(payload), "cache_hit": cache_hit})
        citations = [self._citation(item["paper"], f"检索相关度 {item['score']}") for item in payload[:5]]
        evidence = [item["paper"] for item in payload[:5]]
        if not payload:
            return "没有找到足够相关的公开论文。请尝试输入更短的标题片段、英文关键词、DOI 或作者名。", [], 0.0, cache_hit, evidence
        lines = ["我找到以下较相关的论文："]
        for index, item in enumerate(payload[:5], 1):
            paper = item["paper"]
            lines.append(f"{index}. {paper['title']}（{paper.get('year') or '年份未知'}，相关度 {item['score']}）")
        return "\n".join(lines), citations, min(0.99, 0.55 + payload[0]["score"] * 0.4), cache_hit, evidence

    async def _detail(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        identifier = self._extract_identifier(query)
        if not identifier:
            payload, cache_hit = await self.registry.call("search_papers", {"query": query, "top_k": 3}, trace_id)
            paper = payload[0]["paper"] if payload else None
        else:
            paper_obj = await self.registry.call("get_paper", {"identifier": identifier}, trace_id)
            paper = paper_obj.model_dump(mode="json") if isinstance(paper_obj, Paper) else None
            cache_hit = False
        trace.append({"step": "Observation", "found": bool(paper), "identifier": identifier})
        if not paper:
            return "没有找到可以核验的论文详情。请提供 DOI、完整标题或更有辨识度的标题片段。", [], 0.0, cache_hit, []
        citation = self._citation(paper, "结构化元数据")
        answer = (
            f"论文：{paper['title']}\n"
            f"作者：{'、'.join(paper.get('authors') or []) or '公开元数据未提供'}\n"
            f"期刊：{paper.get('journal') or '公开元数据未提供'}\n"
            f"年份：{paper.get('year') or '未知'}\n"
            f"DOI：{paper.get('doi') or '未找到'}\n"
            f"引用数（OpenAlex）：{paper.get('cited_by_count', 0)}\n"
            f"开放获取：{'是' if paper.get('is_oa') else '未标记为开放获取'}\n"
            f"原文/数据库链接：{paper.get('pdf_url') or paper.get('landing_page_url') or '无'}"
        )
        return answer, [citation], 0.95, cache_hit, [paper]

    async def _qa(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        search_query = re.sub(r"(是什么|提出了什么|使用了什么|解决了什么|如何|请问|介绍一下)", " ", query)
        payload, cache_hit = await self.registry.call("search_papers", {"query": search_query.strip(), "top_k": 5}, trace_id)
        trace.append({"step": "Observation", "count": len(payload), "cache_hit": cache_hit})
        if not payload:
            return "当前公开数据不足以确认这个问题。请提供论文 DOI、标题片段，或先搜索目标论文。", [], 0.0, cache_hit, []
        best = payload[0]["paper"]
        evidence = best.get("abstract") or "该数据源未返回摘要，当前只能确认结构化元数据。"
        depth = "deep" if self._wants_deep_analysis(query) else "brief"
        trace.append({"step": "Generator", "answer_depth": "详细原理分析" if depth == "deep" else "简要介绍"})
        paper_obj = Paper.model_validate(best)
        chunks: list[dict[str, Any]] = []
        if depth == "deep":
            fulltext_status = await self.registry.call("ensure_fulltext", {"identifier": best["source_id"]}, trace_id)
            chunks = self._retrieve_chunks(paper_obj, query)
            trace.append({"step": "FullText RAG", "status": fulltext_status.get("status"), "chunk_count": fulltext_status.get("chunk_count", 0), "evidence_chunks": len(chunks)})
        llm_answer = await llm_service.generate(llm_service.build_paper_qa_prompt(best["title"], query, evidence, chunks))
        trace.append({"step": "LLM Generator", "provider": "ollama", "used": bool(llm_answer)})
        answer_body = llm_answer or self._summarize_cn(best["title"], evidence, query, chunks)
        answer = f"基于公开摘要和元数据，最相关论文是《{best['title']}》。\n\n中文归纳：{answer_body}"
        if not best.get("abstract"):
            answer += "\n\n说明：当前没有获取到开放摘要，因此不能可靠补充方法细节。"
        else:
            answer += f"\n\n原文摘要（用于核验）：{evidence[:1200]}"
        citations = [self._citation(best, evidence[:300])]
        for chunk in chunks[:3]:
            citations.append(self._citation(best, chunk["text"][:350]))
        all_evidence = [best] + [{"title": best["title"], "doi": best.get("doi"), "text": c["text"]} for c in chunks[:3]]
        return answer, citations, min(0.92, 0.5 + payload[0]["score"] * 0.45 + (0.05 if chunks else 0)), cache_hit, all_evidence

    async def _compare(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        parts = re.split(r"\s*(?:和|与|以及|vs\.?|VS|对比|比较)\s*", query, maxsplit=2)
        parts = [p.strip() for p in parts if len(p.strip()) > 3]
        if len(parts) < 2:
            return '请在问题中提供两篇论文的标题片段或 DOI，例如"比较 Attention Is All You Need 和 BERT"。', [], 0.0, False, []
        payload, cache_hit = await self.registry.call("search_papers", {"query": parts[0], "top_k": 1}, trace_id)
        payload2, cache_hit2 = await self.registry.call("search_papers", {"query": parts[1], "top_k": 1}, trace_id)
        found = [item["paper"] for item in [*payload, *payload2]]
        trace.append({"step": "Observation", "count": len(found), "cache_hit": cache_hit or cache_hit2})
        if len(found) < 2:
            return "至少有一篇论文没有找到足够可靠的公开记录，暂不生成对比结论。", [], 0.0, cache_hit or cache_hit2, found

        llm_answer = await llm_service.generate(llm_service.build_compare_prompt(query, found[0], found[1]))
        trace.append({"step": "LLM Generator (compare)", "used": bool(llm_answer)})
        if llm_answer:
            answer = llm_answer
        else:
            answer = "论文对比（基于公开元数据与摘要）：\n\n"
            answer += "| 维度 | 论文一 | 论文二 |\n|---|---|---|\n"
            answer += f"| 标题 | {found[0]['title']} | {found[1]['title']} |\n"
            answer += f"| 年份 | {found[0].get('year') or '未知'} | {found[1].get('year') or '未知'} |\n"
            answer += f"| 期刊/来源 | {found[0].get('journal') or '未知'} | {found[1].get('journal') or '未知'} |\n"
            answer += f"| DOI | {found[0].get('doi') or '未知'} | {found[1].get('doi') or '未知'} |\n"
            answer += "\n当前比较主要覆盖可核验的结构化字段；摘要缺失时不会臆测方法差异。"
        return answer, [self._citation(p, "对比字段来源") for p in found], 0.85, cache_hit or cache_hit2, found

    async def _concept_qa(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        concept, search_query = self._extract_concept(query)
        trace.append({"step": "Planner", "plan": ["detect_concept", "search_supporting_papers", "generate"], "concept": concept})
        payload, cache_hit = await self.registry.call("search_papers", {"query": search_query, "top_k": 5}, trace_id)
        trace.append({"step": "Observation", "count": len(payload), "cache_hit": cache_hit})
        llm_answer = await llm_service.generate(llm_service.build_concept_prompt(query, concept, payload))
        trace.append({"step": "LLM Generator", "provider": "ollama", "used": bool(llm_answer)})
        answer = llm_answer or self._concept_fallback(concept)
        evidence = [item["paper"] for item in payload[:3]]
        citations = [self._citation(p, (p.get("abstract") or f"{concept} 相关论文")[:350]) for p in evidence]
        if citations:
            answer += "\n\n参考论文证据：\n" + "\n".join(f"- {c.title}（DOI：{c.doi or '无'}）" for c in citations)
        return answer, citations, 0.82 if citations else 0.68, cache_hit, evidence

    async def _trend(self, query: str, trace_id: str, trace: list[dict[str, Any]]) -> tuple[str, list[Citation], float, bool, list[dict[str, Any]]]:
        topic = re.sub(r"(趋势|增长|年度|研究方向|分析|近几年|近五年)", " ", query).strip()
        payload, cache_hit = await self.registry.call("search_papers", {"query": topic, "top_k": 30}, trace_id)
        years: dict[str, int] = {}
        for item in payload:
            year = str(item["paper"].get("year") or "未知")
            years[year] = years.get(year, 0) + 1
        if not years:
            return "没有找到足够论文，无法生成趋势统计。", [], 0.0, cache_hit, []
        summary = "按当前检索返回样本统计的年度分布：\n" + "\n".join(f"- {year}：{count} 篇" for year, count in sorted(years.items()))
        summary += "\n\n说明：这是基于当前检索样本的探索性统计，不等同于完整学科产出统计。"
        evidence = [item["paper"] for item in payload[:5]]
        return summary, [self._citation(p, "趋势样本") for p in evidence], 0.75, cache_hit, evidence

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #

    def _retrieve_chunks(self, paper: Paper, question: str) -> list[dict[str, Any]]:
        """从 FullTextService 检索全文分块（延迟导入避免循环依赖）。"""
        from app.services.fulltext_service import FullTextService

        fulltext = FullTextService()
        return fulltext.retrieve(paper, question, top_k=4)

    @staticmethod
    def _extract_identifier(query: str) -> str | None:
        doi = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", query, re.I)
        if doi:
            return doi.group(1).rstrip(".,;")
        openalex = re.search(r"https?://openalex\.org/\w+", query, re.I)
        return openalex.group(0) if openalex else None

    @staticmethod
    def _is_concept_question(query: str) -> bool:
        lower = query.lower()
        concepts = ["cnn", "convolutional neural network", "rag", "llm", "transformer", "bert", "lstm", "gru"]
        concept_hit = any(item in lower for item in concepts)
        detail_hit = any(word in query for word in ["原理", "机制", "结构", "详细", "介绍", "是什么", "分析", "讲解"])
        paper_hit = any(word in lower for word in ["attention is all you need", "deep residual learning", "bert pre-training", "这篇论文"])
        return concept_hit and detail_hit and not paper_hit

    @staticmethod
    def _extract_concept(query: str) -> tuple[str, str]:
        lower = query.lower()
        if "cnn" in lower or "convolutional neural network" in lower:
            return "CNN（卷积神经网络）", "CNN convolutional neural network image classification"
        if "rag" in lower:
            return "RAG（检索增强生成）", "retrieval augmented generation"
        if "transformer" in lower:
            return "Transformer", "Transformer attention neural network"
        if "llm" in lower:
            return "LLM（大语言模型）", "large language model transformer"
        if "lstm" in lower:
            return "LSTM", "LSTM long short term memory"
        if "gru" in lower:
            return "GRU", "GRU gated recurrent unit"
        if "bert" in lower:
            return "BERT", "BERT bidirectional transformer"
        return "技术主题", query

    @staticmethod
    def _citation(paper: dict[str, Any], evidence: str) -> Citation:
        return Citation(
            paper_id=paper.get("source_id", ""),
            title=paper.get("title", ""),
            doi=paper.get("doi"),
            url=paper.get("landing_page_url") or paper.get("pdf_url"),
            evidence=evidence,
        )

    @staticmethod
    def _wants_deep_analysis(query: str) -> bool:
        return any(word in query for word in ["详细", "原理", "深入", "展开", "机制", "结构", "逐步", "为什么"])

    @staticmethod
    def _summarize_cn(title: str, abstract: str, query: str = "", chunks: list[dict[str, Any]] | None = None) -> str:
        """无外部大模型时提供保守的中文归纳，避免把英文摘要直接当成答案。"""
        lower = abstract.lower()
        if "attention is all you need" in title.lower() and "transformer" in lower:
            if WorkerAgent._wants_deep_analysis(query):
                evidence_note = ""
                if chunks:
                    evidence_note = "\n\n正文证据片段：\n" + "\n".join(f"- {item['text'][:260]}" for item in chunks[:3])
                return (
                    "这篇论文的核心方法是 Transformer，它把序列建模从 RNN/CNN 的逐步递归或局部卷积，改成了完全基于注意力机制的并行建模。\n\n"
                    "1. 自注意力机制：模型先把每个 token 映射成 Query、Key、Value 三组向量。某个位置要更新表示时，会用 Query 和所有位置的 Key 计算相关性，再对 Value 加权求和。这样每个词都能直接关注句子中任意位置的信息，不需要像 RNN 那样一步步传递上下文。\n\n"
                    "2. 缩放点积注意力：注意力分数由 Query 和 Key 的点积得到，并除以维度平方根，避免维度较大时分数过大导致 softmax 梯度不稳定。随后 softmax 得到权重，再加权汇聚 Value。\n\n"
                    "3. 多头注意力：论文不是只做一次注意力，而是把表示拆成多个子空间并行计算。不同头可以学习不同关系，例如词法依赖、长距离语义关联、位置关系等，最后把多个头的结果拼接起来。\n\n"
                    "4. 位置编码：由于纯注意力本身不天然包含词序，论文加入位置编码，把序列位置信息注入词向量。这样模型既能并行处理序列，又能保留顺序信息。\n\n"
                    "5. Encoder-Decoder 结构：编码器负责把源句子编码成上下文表示；解码器在生成目标句子时，一方面看已经生成的目标词，另一方面通过交叉注意力关注源句子表示。\n\n"
                    "6. 前馈网络、残差连接和归一化：每层注意力之后接位置前馈网络，并使用残差连接与 LayerNorm 稳定深层训练。\n\n"
                    "从原理上看，Transformer 的优势在于缩短了长距离依赖路径，提升并行计算能力，并减少 RNN 顺序计算带来的训练瓶颈。摘要中可直接核验的证据包括：论文提出 Transformer、完全基于 attention、去除 recurrence/convolution，并在机器翻译任务上取得 BLEU 改进。"
                    + evidence_note
                )
            return "论文提出 Transformer 架构，仅使用注意力机制完成序列转换，去除了循环网络和卷积网络；实验显示该架构在机器翻译任务上取得了较好的效果，并且更易并行训练。"
        if "bert" in title.lower() and "bidirectional" in lower:
            return "论文提出 BERT 预训练方法，通过双向 Transformer 表示学习语言上下文，再将预训练模型用于下游自然语言处理任务。"
        if "residual" in title.lower() and "residual" in lower:
            return "论文研究残差学习结构，通过学习残差映射缓解深层网络训练困难，并在图像识别任务中验证了该方法。"
        if "retrieval" in lower and ("augmented" in lower or "generation" in lower):
            return "公开摘要显示，该研究围绕检索增强生成展开，将外部文档检索与文本生成结合，以补充模型参数之外的信息。"
        return f"公开摘要围绕《{title}》展开。当前系统只对摘要中的主题和结构化元数据做保守归纳，未获得足够证据的细节不会自行补全。"

    @staticmethod
    def _concept_fallback(concept: str) -> str:
        if concept.startswith("CNN"):
            return (
                "通用知识解释：CNN，即卷积神经网络，是一种主要用于图像、语音、时序和局部结构数据的深度学习模型。\n\n"
                "1. 核心思想：CNN 假设数据中存在局部相关性。例如图像中相邻像素往往共同构成边缘、纹理和形状。卷积层用一组可学习的小卷积核在输入上滑动，提取局部模式。\n\n"
                "2. 卷积层：卷积核会在不同空间位置共享参数，所以同一个特征检测器可以在整张图上复用。这带来两个好处：参数量远少于全连接网络，并且对目标位置变化更稳健。\n\n"
                "3. 激活函数：卷积结果通常接 ReLU 等非线性函数，让模型能够表达复杂模式，而不是只做线性滤波。\n\n"
                "4. 池化或下采样：池化层会压缩空间尺寸，保留显著响应，降低计算量，并增强一定程度的平移不变性。现代 CNN 也常用步幅卷积替代传统池化。\n\n"
                "5. 层级特征：浅层卷积通常学习边缘、角点、颜色纹理；中层学习局部部件；深层学习目标整体语义。这个层级抽象是 CNN 在视觉任务中有效的重要原因。\n\n"
                "6. 训练方式：CNN 通过反向传播学习卷积核参数。损失函数根据任务选择，例如分类用交叉熵，检测和分割会组合分类、定位、掩码等损失。\n\n"
                "7. 典型结构：经典 CNN 通常由卷积、归一化、激活、下采样和分类头组成。AlexNet、VGG、ResNet、Inception、MobileNet、Mask R-CNN 都是在这个范式上演化出来的。\n\n"
                "8. 优点：局部连接、参数共享、计算高效、适合图像结构；缺点是对长距离依赖建模较弱，感受野需要靠堆叠层数扩大，对旋转、尺度变化通常需要数据增强或结构改进。\n\n"
                "9. 和 Transformer 的区别：CNN 更偏局部归纳偏置，天然适合提取局部空间模式；Transformer 依赖注意力机制，能直接建模全局关系，但通常需要更多数据和计算。"
            )
        if concept.startswith("RAG"):
            return (
                "通用知识解释：RAG 是检索增强生成。它先从外部知识库检索相关证据，再让生成模型基于证据回答，从而降低幻觉并提升知识可更新性。核心流程包括查询改写、召回、重排、上下文构造、生成和引用校验。"
            )
        if concept.startswith("Transformer"):
            return (
                "通用知识解释：Transformer 以自注意力为核心，通过 Query、Key、Value 计算 token 之间的相关性，并用多头注意力学习不同子空间关系；位置编码提供顺序信息，前馈网络、残差连接和归一化稳定训练。"
            )
        if concept.startswith("LSTM"):
            return (
                "通用知识解释：LSTM（长短期记忆网络）是一种特殊的循环神经网络，通过门控机制解决长序列梯度消失问题。\n\n"
                "1. 核心思想：传统 RNN 在处理长序列时，梯度会随时间步指数衰减或爆炸，难以学习长距离依赖。LSTM 引入细胞状态和三个门（遗忘门、输入门、输出门），让信息选择性通过，从而保留长期记忆。\n\n"
                "2. 遗忘门：决定从细胞状态中丢弃什么信息。它查看上一隐藏状态和当前输入，输出 0 到 1 之间的值，1 表示完全保留，0 表示完全丢弃。\n\n"
                "3. 输入门：决定哪些新信息被存入细胞状态。它包含一个 sigmoid 层决定更新哪些值，以及一个 tanh 层生成候选值。\n\n"
                "4. 细胞状态更新：遗忘门和输入门的输出共同决定细胞状态的更新。旧状态乘以遗忘门输出，再加上输入门生成的候选值。\n\n"
                "5. 输出门：决定输出什么。细胞状态经过 tanh 处理后乘以输出门的输出，得到当前隐藏状态。\n\n"
                "6. 优势：LSTM 通过门控机制有效缓解了梯度消失问题，能够建模长距离依赖关系，在语音识别、机器翻译、时间序列预测等任务中表现优异。\n\n"
                "7. 与 Transformer 的区别：LSTM 是串行处理，计算无法并行化；Transformer 基于自注意力机制，可以并行计算，但 LSTM 在小数据和长序列建模上仍有优势。"
            )
        if concept.startswith("GRU"):
            return (
                "通用知识解释：GRU（门控循环单元）是 LSTM 的简化版本，将遗忘门和输入门合并为更新门，减少了参数量。\n\n"
                "1. 核心思想：GRU 保留 LSTM 门控机制的核心思想，但简化了结构。它只有两个门（重置门和更新门），没有单独的细胞状态，直接使用隐藏状态传递信息。\n\n"
                "2. 重置门：决定在计算候选隐藏状态时忽略多少历史信息。重置门值越小，忽略的历史信息越多。\n\n"
                "3. 更新门：决定从旧隐藏状态保留多少信息，以及从候选隐藏状态接收多少新信息。这类似于 LSTM 的遗忘门和输入门的组合。\n\n"
                "4. 候选隐藏状态：使用重置门控制的历史信息和当前输入计算得出，作为新的候选状态。\n\n"
                "5. 隐藏状态更新：通过更新门在旧隐藏状态和候选隐藏状态之间做加权平均，得到新的隐藏状态。\n\n"
                "6. 优势：相比 LSTM，GRU 参数更少、训练更快，在很多任务上性能接近。更新门直接控制信息流动，不需要额外的细胞状态。\n\n"
                "7. 与 LSTM 的区别：GRU 没有单独的细胞状态，门更少，参数量更小，训练更快；LSTM 有更精细的门控机制，在复杂长序列建模上可能更有优势。"
            )
        return f"通用知识解释：{concept} 是当前系统识别到的技术主题。由于未接入足够专门证据，建议结合检索到的论文进一步核验细节。"
