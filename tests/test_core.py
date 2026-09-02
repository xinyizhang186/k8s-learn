import pytest

from app.agent.engine import KnowledgePilotAgent
from app.agent.judge import JudgeAgent
from app.agent.worker import WorkerAgent
from app.models import Paper
from app.retrieval.hybrid import normalize, search_local
from app.retrieval.vector import vector_similarity
from app.services.paper_service import PaperService


def test_normalize_and_partial_title_search():
    paper = Paper(source="test", source_id="test:1", title="Attention Is All You Need", abstract="Transformer")
    results = search_local("attention all", [paper], top_k=1)
    assert normalize("  Attention  ALL ") == "attention all"
    assert results and results[0][0].title == paper.title


def test_partial_title_respects_word_order():
    target = Paper(source="test", source_id="test:1", title="Attention Is All You Need")
    distractor = Paper(source="test", source_id="test:2", title="Not All Attention Is All You Need")
    results = search_local("attention all", [distractor, target], top_k=2)
    assert results[0][0].title == target.title


def test_router_is_chinese_friendly():
    agent = KnowledgePilotAgent()
    assert agent.worker.classify("这篇论文提出了什么方法") == "evidence_qa"
    assert agent.worker.classify("比较两篇论文") == "compare"
    assert agent.worker.classify("近五年研究趋势") == "trend"
    assert agent.worker.classify("请详细介绍 CNN的原理分析") == "concept_qa"


def test_arxiv_record_wins_same_title_merge():
    arxiv = Paper(
        source="arxiv",
        source_id="arxiv:1",
        doi="10.48550/arXiv.1",
        title="A Real Paper",
        year=2017,
        abstract="real abstract",
    )
    aggregate = Paper(
        source="openalex",
        source_id="https://openalex.org/W1",
        doi="10.9999/wrong",
        title="A Real Paper",
        year=2025,
        journal="错误聚合期刊",
    )
    merged = PaperService._dedupe([aggregate, arxiv])
    assert len(merged) == 1
    assert merged[0].source == "arxiv"
    assert merged[0].doi == "10.48550/arXiv.1"
    assert merged[0].journal is None


def test_chinese_summary_is_not_raw_english():
    summary = WorkerAgent._summarize_cn(
        "Attention Is All You Need",
        "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
    )
    assert "论文提出" in summary
    assert "Transformer" in summary


def test_deep_question_changes_answer_depth():
    abstract = "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms."
    brief = WorkerAgent._summarize_cn("Attention Is All You Need", abstract, "请介绍方法")
    deep = WorkerAgent._summarize_cn("Attention Is All You Need", abstract, "请详细从原理分析")
    assert len(deep) > len(brief) * 3
    assert "自注意力机制" in deep
    assert "多头注意力" in deep


def test_cnn_concept_fallback_is_detailed():
    answer = WorkerAgent._concept_fallback("CNN（卷积神经网络）")
    assert "卷积层" in answer
    assert "池化" in answer
    assert "Transformer" in answer


def test_unrelated_chinese_query_does_not_match_by_single_character():
    paper = Paper(source="test", source_id="test:1", title="Attention Is All You Need")
    assert search_local("不存在的 KnowledgePilot 论文 999999", [paper], top_k=3) == []


def test_query_prepare_expands_cnn_chinese_phrase():
    prepared = PaperService.prepare_query("CNN相关论文")
    assert "convolutional neural network" in prepared
    assert "相关论文" not in prepared


def test_query_prepare_protects_specific_rcnn_titles():
    prepared = PaperService.prepare_query("Mask R-CNN")
    assert prepared == "Mask R-CNN"
    assert "region based" not in prepared


def test_quality_filter_removes_crossref_figure_records():
    paper = Paper(
        source="crossref",
        source_id="crossref:fig",
        doi="10.7717/peerj.19645/fig-3",
        title="Figure 3: Convolutional neural network.",
    )
    assert not PaperService._is_quality_candidate(paper)


def test_hash_vector_similarity_finds_related_text():
    related = vector_similarity("CNN image classification", "convolutional neural network for image classification")
    unrelated = vector_similarity("CNN image classification", "legal policy and economics")
    assert related > unrelated


# ------------------------------------------------------------------ #
# Judge Agent tests
# ------------------------------------------------------------------ #


def test_judge_rejects_fabricated_doi():
    """Judge 规则降级应检测到引用中的 DOI 不在证据列表中。"""
    from app.models import Citation

    class FakeDraft:
        answer = "这是一篇关于 Transformer 的论文分析，内容详实。"
        citations = [Citation(paper_id="test:1", title="Test Paper", doi="10.9999/fake-doi", evidence="")]
        evidence = [{"title": "Real Paper", "doi": "10.48550/arXiv.1706.03762"}]
        cache_hit = False

    judge = JudgeAgent()
    verdict = judge._evaluate_with_rules("介绍 Transformer 原理", FakeDraft())
    assert verdict.verdict == "reject"
    assert any("不在检索证据中" in issue for issue in verdict.issues)


def test_judge_rejects_short_answer():
    """Judge 规则降级应拒绝过短答案。"""

    class FakeDraft:
        answer = "好的"
        citations = []
        evidence = []
        cache_hit = False

    judge = JudgeAgent()
    verdict = judge._evaluate_with_rules("介绍论文方法", FakeDraft())
    assert verdict.verdict == "reject"
    assert any("过短" in issue for issue in verdict.issues)


def test_judge_passes_valid_answer_with_real_doi():
    """Judge 规则降级应通过包含真实 DOI 的充分答案。"""
    from app.models import Citation

    class FakeDraft:
        answer = "论文提出了 Transformer 架构，完全基于注意力机制，去除了循环网络。这是一个重要的架构创新。"
        citations = [Citation(paper_id="arxiv:1706.03762", title="Attention Is All You Need", doi="10.48550/arxiv.1706.03762", evidence="attention mechanism")]
        evidence = [{"title": "Attention Is All You Need", "doi": "10.48550/arxiv.1706.03762", "abstract": "We propose the Transformer"}]
        cache_hit = False

    judge = JudgeAgent()
    verdict = judge._evaluate_with_rules("介绍 Attention Is All You Need 这篇论文的方法", FakeDraft())
    assert verdict.verdict == "pass"


def test_judge_detects_missing_refusal():
    """Judge 规则降级应检测到无证据但未拒答的情况。"""

    class FakeDraft:
        answer = "Transformer 是一种基于自注意力的架构，它通过 Query、Key、Value 计算相关性。这是一个非常详细的回答，内容充分。"
        citations = []
        evidence = []
        cache_hit = False

    judge = JudgeAgent()
    verdict = judge._evaluate_with_rules("介绍 Transformer 原理", FakeDraft())
    assert verdict.verdict == "reject"
    assert any("拒答" in issue for issue in verdict.issues)


def test_lstm_concept_fallback_is_detailed():
    answer = WorkerAgent._concept_fallback("LSTM")
    assert "LSTM" in answer
    assert "门控" in answer
    assert "记忆" in answer
    assert "Transformer" in answer


def test_gru_concept_fallback_is_detailed():
    answer = WorkerAgent._concept_fallback("GRU")
    assert "GRU" in answer
    assert "门控" in answer
    assert "LSTM" in answer


# ------------------------------------------------------------------ #
# Worker-Judge integration tests
# ------------------------------------------------------------------ #


def test_worker_judge_loop_rejects_then_fixes():
    """Judge 拒绝伪造 DOI 的草稿，Worker 重试时应改写搜索词。"""
    from app.agent.worker import WorkerAgent, WorkerDraft
    from app.agent.judge import JudgeAgent
    from app.models import Citation

    judge = JudgeAgent()

    draft_with_fake_doi = WorkerDraft(
        answer="这是一篇关于 Transformer 的论文分析，内容详实且充分。",
        intent="evidence_qa",
        confidence=0.8,
        citations=[Citation(paper_id="fake:1", title="Fake Paper", doi="10.9999/fake-doi", evidence="")],
        cache_hit=False,
        evidence=[{"title": "Real Paper", "doi": "10.48550/arxiv.1706.03762"}],
    )
    verdict = judge._evaluate_with_rules("介绍 Transformer 原理", draft_with_fake_doi)
    assert verdict.verdict == "reject"
    assert any("不在检索证据中" in issue for issue in verdict.issues)

    fixed_draft = WorkerDraft(
        answer="这是一篇关于 Transformer 的论文分析，内容详实且充分。",
        intent="evidence_qa",
        confidence=0.8,
        citations=[Citation(paper_id="arxiv:1706.03762", title="Attention Is All You Need", doi="10.48550/arxiv.1706.03762", evidence="attention mechanism")],
        cache_hit=False,
        evidence=[{"title": "Attention Is All You Need", "doi": "10.48550/arxiv.1706.03762", "abstract": "We propose the Transformer"}],
    )
    fixed_verdict = judge._evaluate_with_rules("介绍 Transformer 原理", fixed_draft)
    assert fixed_verdict.verdict == "pass"


def test_worker_rule_path_broadens_query_on_retry():
    """规则路径重试时应改写搜索词（去掉噪声词）。"""
    from app.agent.worker import WorkerAgent
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    worker = WorkerAgent(registry)

    original = "请详细介绍 Attention Is All You Need 这篇论文提出的方法"
    broadened = original
    for word in ["请", "详细", "介绍", "的", "是", "什么", "提出", "了", "方法", "原理", "分析", "这篇论文"]:
        broadened = broadened.replace(word, " ")
    import re as _re
    broadened = _re.sub(r"\s+", " ", broadened).strip()

    assert broadened != original
    assert "Attention Is All You Need" in broadened
    assert "请" not in broadened
    assert "详细" not in broadened


def test_engine_trace_contains_thought_step():
    """Engine 的 Trace 应包含 Thought 推理步骤（LLM 路径）。"""
    from app.agent.engine import KnowledgePilotAgent, LLM_INTENTS

    assert "concept_qa" in LLM_INTENTS
    assert "evidence_qa" in LLM_INTENTS
    assert "compare" in LLM_INTENTS
    assert "paper_search" not in LLM_INTENTS
    assert "trend" not in LLM_INTENTS
