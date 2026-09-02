项目经验
KnowledgePilot · 科研检索与证据推理双 Agent 系统  2026.03–2026.06
技术栈：Python、FastAPI、RAG、ReAct、Tool Calling、MCP、Redis、SQLAlchemy、Ollama、Harness
项目内容：面向科研文献检索与论文分析场景，独立设计并实现基于真实学术数据源的双 Agent 系统，实现论文
检索、开放 PDF 全文解析、证据推理与可追溯源引用答案生成。
• 双 Agent 协作架构：Worker 基于 ReAct 完成推理→工具调用→证据观测→答案生成，Judge 从证据充分
性、引用真实性、问题匹配度、拒答正确性四维评估，不通过时反馈重试（最多 3 轮），形成自我纠错闭环。
• 多源检索与两级 Hybrid RAG：融合 OpenAlex、Crossref、arXiv，经 Query Rewrite、多源召回、DOI/标题
去重；论文级 6 维词法重排，全文级 512 维 sign-hash 向量 + 章节关键词重排；支持开放 PDF 下载、pypdf
分块与 Top-K 证据召回，通过 Tool Registry 暴露 MCP 兼容接口。
• 本地模型与自动化评测：Ollama 部署 Qwen2.5 驱动 Worker/Judge，LLM 不可用时规则降级、API 限流时
本地缓存兜底；基于真实论文 DOI 构建测试集，量化评估 Recall@5、MRR、任务成功率、工具选择准确率、
拒答准确率及 p50/p95 延迟，结合 Redis 缓存与 SQLAlchemy 持久化 Trace，支撑策略持续迭代。
