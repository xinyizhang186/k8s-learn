# 秋招展示讲稿

## 一句话介绍

KnowledgePilot 是一个基于真实科研数据的双 Agent 论文检索与推理系统，采用 Worker Agent + Judge Agent 协作架构，Worker 负责工具调用和答案生成，Judge 负责证据充分性、引用真实性和问题匹配度评估，不通过时反馈重试；支持 OpenAlex/Crossref/arXiv 多源检索、Ollama 本地部署、ReAct Tool Calling、MCP 工具接口和 50 条 Harness 自动评测。

## 推荐演示流程

1. 打开中文页面，展示侧边栏 Ollama 模型状态。
2. 在论文搜索中输入 `CNN相关论文`，展示缩写扩展、多源检索和真实 DOI。
3. 在详情/全文中输入 `10.48550/arXiv.1706.03762`，点击自动下载/解析开放全文。
4. 在中文 Agent 对话中输入 `请介绍 Attention Is All You Need 这篇论文提出的方法，详细从原理分析。`
5. 展开 Trace，说明 Worker 的 Thought 推理、工具调用、Judge 评审（verdict=pass/reject）和迭代轮数。
6. 如果 Judge 拒绝过，展示重试过程：Worker 如何根据 Judge 反馈改写搜索词。
7. 打开评测报告，展示 Recall@5、MRR、Judge 拒绝率、平均迭代轮数、p50/p95 延迟。

## 双 Agent 架构讲法

### Worker Agent 做什么

- 理解用户问题，用 LLM 决定调用哪些工具（search_papers / get_paper / ensure_fulltext）
- 执行工具调用，从 OpenAlex/Crossref/arXiv 获取真实论文证据
- 基于证据用 LLM 生成中文答案和引用
- LLM 不可用时降级到规则路由（关键词匹配 + 6 路意图分发）

### Judge Agent 做什么

- 评估 Worker 答案的证据充分性：结论是否有证据支持？有没有幻觉？
- 校验引用真实性：答案引用的 DOI 是否在工具实际返回的结果中？
- 检查问题匹配度：答案是否真正回答了用户问题？
- 检查拒答正确性：证据不足时是否正确拒答？
- 不通过时给 Worker 反馈，Worker 改写搜索词后重试（最多 3 轮）

### 为什么用双 Agent

- 单 Agent 生成答案后无法自我纠错，容易产生幻觉和编造引用
- Judge 的反馈机制让 Agent 有真正的迭代循环，不是一次性管道
- Judge 的 DOI 伪造检测能防止 LLM 编造不存在的引用
- 面试讲点：LLM-as-Judge、Actor-Critic 模式、证据约束生成

## 当前成熟度判断

这个项目可以作为秋招项目，但不应该包装成"已经达到商业级文献助手"。更稳妥的表述是：已经完成可运行的工程闭环，覆盖双 Agent 协作、真实数据源、Agent 编排、全文 RAG、本地模型部署和自动评测。

## 面试可讲难点

- **双 Agent 协作**：Worker 生成 → Judge 评估 → 反馈重试，如何设计评估维度和降级策略
- **LLM-as-Judge**：用 LLM 评估 LLM 生成的答案质量，如何防止 Judge 本身误判
- **查询改写**：处理 `CNN相关论文`、`RAG文献` 这类中文混合缩写查询
- **多源融合**：OpenAlex 召回广，Crossref 校验 DOI，arXiv 提供开放 PDF
- **全文 RAG**：开放 PDF 下载后用 pypdf 抽取正文，分块入库，按词法分数、向量相似度和章节关键词重排证据
- **降级保障**：LLM 不可用时规则降级，API 限流时本地缓存兜底，面试演示不翻车
- **可观测 Agent**：Trace 记录 Thought、Router、Tool Calling、Judge Verdict 和迭代过程
- **可靠性**：证据不足时拒答；Judge 拒绝时重试；Ollama 不可用时规则降级；Redis/MySQL 不存在时使用内存和 SQLite

## 简历表述

独立设计并实现 KnowledgePilot 双 Agent 论文检索与推理系统，采用 Worker Agent + Judge Agent 协作架构：Worker 负责工具调用和答案生成，Judge 负责证据充分性、引用真实性和问题匹配度评估，不通过时反馈重试（最多 3 轮）；接入 OpenAlex、Crossref、arXiv 真实开放数据源，支持论文检索、开放 PDF 全文解析、Hybrid RAG、ReAct Tool Calling、MCP 工具接口和 Ollama 本地模型部署；设计 50 条 Harness 评测用例统计 Recall@5、MRR、Judge 拒绝率、平均迭代轮数和 p95 延迟。

## 项目完善度表达

推荐这样说：

> 这个项目已经完成从真实数据采集、双 Agent 协作、全文解析、Worker-Judge 迭代闭环到 Harness 评测的完整链路。它不是简单 demo，而是一个可继续工程化扩展的科研 Agent 系统原型。

不要这样说：

> 这个项目已经超过专业数据库或商业文献助手。

更成熟的后续优化方向：

- 将 Hash 向量替换成 bge-m3 或 Ollama embedding
- 增加 Cross-Encoder reranker
- 把评测集扩展到 100 条
- 增加引用网络图谱和作者机构分析
- 多轮对话记忆
