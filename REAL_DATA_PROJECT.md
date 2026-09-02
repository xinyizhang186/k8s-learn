# KnowledgePilot 真实数据版项目方案

## 一、最终推荐方向

将 KnowledgePilot 定义为：

> 面向科研人员的论文检索、证据问答与研究趋势分析 Agent。

它使用公开科研数据库中的真实论文元数据、摘要、作者、期刊、DOI、引用关系和开放全文。用户可以输入完整标题、部分标题、关键词或自然语言问题，Agent 自动选择检索、详情查询、作者分析、引用网络和趋势统计工具，并返回带真实来源链接的中文结果。

这个方向比虚构企业知识库更适合当前情况：数据可以自动获取，数据来源可验证，搜索结果有 DOI 和数据库 ID，评测集也能基于真实论文 ID 建立。

## 二、真实数据来源

| 数据源 | 数据内容 | 使用方式 | 备注 |
|---|---|---|---|
| OpenAlex | 论文、作者、机构、期刊、主题、引用、开放获取信息 | REST API | 主数据源，免费且适合批量检索 |
| Crossref | DOI、标题、期刊、作者、出版时间、参考文献元数据 | REST API | 用于 DOI 和出版信息校验 |
| Europe PMC | 生物医学论文、摘要、PMCID、开放全文 | REST API | 医学和生命科学方向的真实全文来源 |
| arXiv | 预印本标题、摘要、作者、分类、PDF | API/公开数据 | AI、计算机和数学领域较适合 |
| Semantic Scholar | 论文、作者和引用关系 | API | 作为可选增强源，注意请求限制 |

默认使用 OpenAlex + Crossref，用户可以在配置文件中开启 Europe PMC 或 arXiv。所有在线数据都要保存 `source_id`、`doi`、`url`、`retrieved_at` 和 `source_name`，让每个答案可以回溯到原始记录。

不建议直接爬取需要登录或有访问限制的期刊网站。项目应优先使用官方开放 API、开放获取全文和合法下载链接；这既稳定，也方便在面试中解释数据合规问题。

## 三、真实业务功能

### 1. 论文搜索

支持以下输入形式：

- 完整标题：`Attention Is All You Need`
- 部分标题：`attention all`
- 关键词：`multi-head cross attention ac4C`
- 作者和年份：`检索 2023 年 Zhang 关于 RNA 修饰的论文`
- 主题组合：`找使用 Transformer 进行医学图像分割的论文`

Agent 会对查询进行规范化，分别调用 OpenAlex 和 Crossref，使用标题、摘要、作者、概念和年份进行融合排序，解决只输入部分标题时搜不到的问题。

### 2. 论文证据问答

示例问题：

- “这篇论文提出了什么方法？使用了什么数据集？”
- “SCI TBC-ac4C 这篇论文的作者、期刊、年份和 DOI 是什么？”
- “这两篇论文在模型结构和实验数据上有什么区别？”
- “这篇论文是否开放获取？能否给出原文链接？”

回答只能使用已检索到的摘要、开放全文或结构化元数据，并返回论文标题、DOI、数据库链接和证据片段。没有足够证据时回答“当前公开数据不足以确认”，而不是自行补全。

### 3. 论文对比

用户输入两篇或多篇论文，Agent 提取并对齐：

- 研究问题
- 方法/模型
- 数据集
- 评价指标
- 实验结论
- 局限性
- 发表时间与来源

对比结果以表格输出，并在每一行绑定来源论文。

### 4. 研究趋势分析

按关键词、主题、年份统计真实论文数量、引用数量、热门概念、作者和机构。结果来源于 OpenAlex 聚合数据和本地 MySQL 分析表，Redis 缓存相同查询。

### 5. 引用网络和作者关系

构建轻量知识图谱：

```text
论文 -[由...发表]-> 作者
论文 -[发表于]-> 期刊
论文 -[属于主题]-> 概念
论文 -[引用]-> 论文
作者 -[隶属]-> 机构
```

用户可以询问“这篇论文引用了哪些方法”“某主题的核心作者是谁”“两个研究方向是否存在共同作者”等关系型问题。

## 四、Agent 执行逻辑

```text
用户问题
  -> Query Rewrite：识别标题片段、关键词、作者、年份和领域
  -> Intent Router：搜索 / 详情 / 问答 / 对比 / 趋势 / 引用网络
  -> Planner：决定需要哪些真实数据工具
  -> Tool Calling：OpenAlex、Crossref、Europe PMC、SQL、Graph、RAG
  -> Observation：读取结果、来源、时间和请求状态
  -> Evidence Verifier：检查 DOI、标题、年份和结论是否有证据
  -> ReAct Retry：低召回时扩展同义词、去除噪声、切换数据源
  -> Generator：生成中文答案和来源引用
  -> Harness：保存 trace 并计算检索、回答、引用和延迟指标
```

建议的工具：

```text
search_openalex(query, year_from, year_to, top_k)
search_crossref(query, top_k)
get_paper(paper_id_or_doi)
get_open_access_fulltext(paper_id_or_pmcid)
search_author(name)
build_citation_network(paper_id, depth)
analyze_topic_trend(topic, year_from, year_to)
retrieve_evidence(paper_ids, question)
```

工具必须具备 JSON Schema、参数校验、超时、重试、缓存、速率限制和调用审计。模型不能直接执行任意 URL 或任意 SQL。

## 五、数据库设计

MySQL 中建议建立以下核心表：

- `papers`：OpenAlex ID、DOI、标题、摘要、年份、期刊、引用数、开放获取状态。
- `authors`：作者 ID、姓名、机构和统计信息。
- `paper_authors`：论文与作者的多对多关系。
- `paper_concepts`：论文与主题概念关系。
- `paper_citations`：引用关系和来源。
- `paper_chunks`：开放全文或摘要分块、向量索引 ID、文本哈希。
- `agent_runs`：问题、意图、步骤、延迟、最终答案和 trace ID。
- `tool_calls`：工具名、参数摘要、耗时、状态和错误信息。
- `evaluation_runs`：评测版本、模型、数据源和指标。

Redis 用于缓存 API 响应、论文详情、查询结果和会话上下文，并记录 TTL、命中/未命中和缓存版本。开发模式可使用 SQLite，但 MySQL schema 必须保持兼容。

## 六、真实数据采集流程

```text
用户启动同步任务
  -> 输入主题、关键词和年份范围
  -> 请求 OpenAlex / Crossref
  -> 清洗 DOI、标题、作者和摘要
  -> 按 DOI 或 source_id 去重
  -> 写入 MySQL/SQLite
  -> 抽取实体与引用关系
  -> 摘要/开放全文分块
  -> 建立 BM25 + Embedding 索引
  -> 记录同步批次、耗时、数量和失败原因
```

首轮同步建议抓取 500 至 2,000 条公开论文元数据；真正用于演示的知识库可以先保留 100 至 300 篇。这样既能体现真实数据处理能力，又不会因为第一次请求量过大触发接口限制。

## 七、实测数据与评测设计

### 评测集构造

评测集不使用随意编造的答案，而是保存真实 `paper_id`、DOI 或 PMCID 作为黄金依据：

```json
{
  "query": "attention all",
  "intent": "paper_search",
  "expected_paper_ids": ["https://openalex.org/W2741809807"],
  "expected_doi": "10.48550/arXiv.1706.03762",
  "answer_facts": ["Transformer", "attention", "encoder-decoder"],
  "must_cite": true
}
```

首版建议至少 50 条：20 条论文搜索、10 条详情问答、8 条论文对比、6 条趋势分析、3 条引用网络、3 条无结果或拒答问题。每条用例都应该能在 OpenAlex/Crossref 页面上人工核验。

### 核心指标

- `Recall@5`：目标论文是否出现在前 5 个真实结果中。
- `MRR`：目标论文排名越靠前得分越高。
- `nDCG@10`：多个相关论文的排序质量。
- `Metadata Accuracy`：标题、作者、年份、期刊、DOI 字段准确率。
- `Citation Accuracy`：回答中的 DOI/URL 是否确实对应论据。
- `Answer Faithfulness`：回答事实是否能在摘要/全文证据中找到。
- `Tool Selection Accuracy`：搜索、详情、趋势和图谱工具选择是否正确。
- `Refusal Precision`：没有可靠证据时是否正确拒答。
- `p50/p95 Latency`：端到端延迟。
- `Cache Hit Rate`：第二次执行相同查询时的缓存命中率。

### 必做对比实验

| 实验组 | 方案 | 需要证明的结论 |
|---|---|---|
| Baseline | OpenAlex 标题关键词排序 | 真实 API 基线效果 |
| RAG | 论文摘要/全文向量检索 | 证据问答能力 |
| Hybrid Agent | API 融合 + BM25/向量 + 重排 + 验证 | 最终方案的综合效果 |

每次评测都保存：数据同步时间、论文数量、查询集版本、模型版本、是否使用缓存、硬件配置和原始 trace。报告里只能填写实际运行结果，不能预先承诺准确率。

## 八、这个项目为什么适合秋招

它同时覆盖算法、Agent 和后端工程：

- 算法/检索：查询改写、混合检索、重排和向量索引。
- Agent：Router、Planner、ReAct、Tool Calling、证据验证和拒答。
- 后端：FastAPI、MySQL、Redis、异步任务和接口限流。
- 协议：MCP 工具服务和标准 schema。
- 工程质量：Harness 回归评测、trace、日志、缓存指标和失败恢复。
- 数据真实性：每个结果都来自公开科研数据库，带 DOI、OpenAlex ID 或 PMCID。

推荐的面试演示流程是：

1. 输入一个不完整论文标题，展示 Agent 从 OpenAlex 和 Crossref 找到正确论文。
2. 点击论文详情，展示作者、期刊、年份、DOI 和开放全文链接。
3. 询问“这篇论文解决什么问题、采用什么方法”，展示 RAG 证据片段。
4. 询问两个主题近五年的研究趋势，展示 SQL 聚合和图表。
5. 打开 Agent Trace，展示工具调用、重试、缓存命中和引用校验。
6. 运行 Harness，展示 Recall@5、MRR、引用准确率和 p95 延迟。

## 九、项目边界和诚实表述

这个项目不是替代专业文献数据库，也不保证能访问所有付费期刊全文。它的优势是：公开数据可复现、来源可验证、Agent 流程可观测、工具调用可审计。

简历中可以写：

> 独立设计并实现 KnowledgePilot 科研情报 Agent，接入 OpenAlex、Crossref、Europe PMC 等真实开放数据源，基于 Hybrid RAG、ReAct Tool Calling 和 MCP 完成论文检索、证据问答、引用网络及趋势分析；使用 50+ 条真实论文 ID 标注用例进行 Harness 评测，统计 Recall@5、MRR、引用准确率和 p95 延迟。

其中 `50+`、Recall、MRR 和延迟数值必须在实际运行评测后替换成真实结果。

