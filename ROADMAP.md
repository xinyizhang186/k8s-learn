# KnowledgePilot 秋招完善路线

## 已完成

- 真实数据源：OpenAlex、Crossref、arXiv。
- 论文搜索：标题、关键词、中文混合缩写查询。
- 论文详情：DOI、作者、年份、来源链接。
- 开放全文：PDF 下载、pypdf 抽取、正文分块。
- RAG：词法检索、Hash 向量相似度、章节关键词重排。
- Agent：Query Rewrite、Router、Planner、Tool Calling、Observation、Verifier、Generator。
- 本地模型：Ollama 接口，默认 qwen2.5:7b，失败自动降级。
- MCP：工具 schema 和调用入口。
- Harness：搜索、详情、概念问答、全文问答、拒答评测。
- UI：对话、搜索、详情/全文、论文对比、趋势、评测、MCP。

## 还可以继续增强

| 优先级 | 优化点 | 面试价值 |
|---|---|---|
| P0 | 安装 Ollama 并实测 qwen2.5:7b 生成效果 | 证明本地私有化部署 |
| P0 | 扩充 50+ Harness 用例 | 指标更可信 |
| P1 | 接入 bge-m3 或 m3e embedding | 比 Hash 向量更像工业 RAG |
| P1 | 加 Cross-Encoder reranker | 提升复杂查询 Top-K |
| P1 | 增加引用网络和作者机构分析图 | 体现 GraphRAG / 科研情报能力 |
| P2 | 后台任务队列批量下载 PDF | 工程化能力 |
| P2 | Dockerfile 一键启动 API/UI | 部署完整性 |
| P2 | 用户上传 PDF 私有解析 | 扩展到企业知识库 |

## 简历建议

不要写“达到商业级准确率”。建议写：

> 实现基于真实科研数据的 KnowledgePilot Agent 平台，支持多源论文检索、开放全文解析、Hybrid RAG、ReAct Tool Calling、Ollama 本地部署、MCP 工具接口和 Harness 评测，并基于真实 DOI 用例统计 Recall@5、MRR、拒答准确率与端到端延迟。
