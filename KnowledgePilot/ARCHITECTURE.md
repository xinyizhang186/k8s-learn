# KnowledgePilot 架构说明

## 项目定位

KnowledgePilot 是面向科研场景的双 Agent 检索与推理系统。它采用 Worker-Judge 协作架构，把真实数据源、开放全文解析、RAG、Tool Calling、ReAct Trace、MCP 工具接口、Redis 缓存、数据库审计和 Harness 评测组合成一个可运行系统。

## 核心链路

```text
用户问题
  → Query Rewrite + Intent Router
  → Worker Agent
     → Thought（LLM 推理：分析问题，决定工具调用计划）
     → Tool Calling（search_papers / get_paper / ensure_fulltext）
     → Observation（收集证据，读取 DOI、摘要、全文分块）
     → Generator（LLM 基于证据生成中文答案 + 引用）
  → Judge Agent
     → 证据充分性检查
     → 引用真实性校验（DOI 是否在检索结果中）
     → 问题匹配度检查
     → 拒答正确性检查
     → PASS → 返回答案
     → REJECT → 反馈给 Worker（改写搜索词 / 调整策略），最多 3 轮
  → Harness Metrics
```

## 模块划分

| 模块 | 路径 | 作用 |
|---|---|---|
| API | `app/api/main.py` | FastAPI 接口、健康检查、搜索、对话、全文、评测 |
| 编排器 | `app/agent/engine.py` | Worker-Judge 迭代循环、意图路由、降级策略 |
| Worker Agent | `app/agent/worker.py` | LLM 规划工具调用 + 生成答案，规则降级 6 路意图处理 |
| Judge Agent | `app/agent/judge.py` | LLM 评估 + 规则降级（DOI 校验、拒答检查、问题匹配） |
| 数据源 | `app/clients/` | OpenAlex、Crossref、arXiv 真实公开数据接入 |
| RAG | `app/retrieval/`、`app/services/fulltext_service.py` | 标题/摘要排序、PDF 抽取、正文分块检索 |
| 工具协议 | `app/tools/registry.py`、`app/mcp/server.py` | Tool Calling schema、MCP-compatible 接口 |
| 持久化 | `app/db/database.py` | 论文、全文块、运行 trace、工具调用记录 |
| 模型 | `app/services/llm_service.py` | Ollama 本地模型生成，Worker/Judge prompt 构建，失败自动降级 |
| UI | `app/ui/streamlit_app.py` | 中文操作台，展示 Worker Trace 和 Judge 评审 |
| 评测 | `harness/evaluate.py` | Recall@5、MRR、拒答、工具选择、Judge 拒绝率、迭代轮数、延迟 |

## Worker-Judge 协作机制

### Worker Agent

- **LLM 路径**：LLM 分析问题 → 输出工具调用计划（JSON）→ 执行工具 → LLM 基于证据生成答案。Trace 中记录 Thought 推理步骤。
- **规则降级路径**：关键词路由（classify）→ 6 路意图处理器（paper_search / paper_detail / evidence_qa / concept_qa / compare / trend）→ 规则生成答案。
- **重试策略**：Judge 拒绝时，Worker 根据反馈改写搜索词（去掉噪声词、降低阈值），LLM 路径还将反馈传入规划和生成 prompt。

### Judge Agent

- **LLM 路径**：LLM 从四个维度评估回答质量（证据充分性、引用真实性、问题匹配度、拒答正确性），输出 JSON 格式的 verdict + issues + feedback。
- **规则降级路径**：检查答案非空、引用 DOI 是否在证据列表中、无证据时是否正确拒答、答案是否包含问题中的关键词。
- **降级触发条件**：LLM 不可用、LLM 返回非 JSON、LLM 返回的 verdict 值非法。

## 降级保障

| 组件 | LLM 可用时 | LLM 不可用时 |
|---|---|---|
| Worker | LLM 规划工具 + LLM 生成答案 | 规则路由 + 规则生成 |
| Judge | LLM 四维评估 | 规则检查 DOI + 拒答 + 关键词匹配 |
| 搜索 | OpenAlex + Crossref + arXiv 在线 | 本地 SQLite 缓存兜底 |

## 检索与重排策略

1. 查询改写：清理中文泛化词，扩展 `CNN`、`RAG`、`LLM` 等缩写。
2. 多源召回：OpenAlex 提供广覆盖，Crossref 校验 DOI，arXiv 提供开放 PDF。
3. 去重清洗：按 DOI 和规范化标题合并，过滤 figure/table/supplementary 记录。
4. 本地重排：标题匹配、摘要重合、词序匹配、来源质量、引用量综合排序。
5. 全文 RAG：开放 PDF 抽取后，使用词法分数、Hash 向量相似度和章节关键词加权重排。
6. 证据验证：没有足够相关证据时拒答，不把低相关结果包装成确定结论。

## Ollama 部署形态

```text
Streamlit UI
  → FastAPI
  → Agent Engine (Worker-Judge Orchestrator)
  → Tool Registry / MCP
  → OpenAlex/Crossref/arXiv + SQLite/MySQL + Redis
  → FullText RAG
  → Ollama qwen2.5:7b (Worker 生成 + Judge 评估)
```

Ollama 负责 Worker 的工具规划和答案生成，以及 Judge 的回答评估。论文检索、工具调用、证据选择和引用校验仍由业务代码控制。
