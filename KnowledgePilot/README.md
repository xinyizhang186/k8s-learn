# KnowledgePilot

KnowledgePilot 是一个基于真实公开科研数据的中文论文检索、证据问答与趋势分析 **双 Agent 系统**。它采用 Worker Agent + Judge Agent 协作架构：Worker 负责理解问题、调用工具检索证据并生成回答，Judge 负责评估回答的证据充分性、引用真实性和问题匹配度，不通过时反馈给 Worker 重试。

## 当前已实现

- **Worker-Judge 双 Agent 架构**：Worker 生成草稿 → Judge 评估 → 反馈重试循环（最多 3 轮），LLM 不可用时自动降级到规则路径。
- OpenAlex + Crossref + arXiv 多源论文检索，支持完整标题、标题片段和关键词。
- DOI/OpenAlex ID 详情查询、结果去重和本地 SQLite 持久化。
- 基于摘要/元数据/开放 PDF 全文的中文证据问答、论文对比和样本趋势统计。
- 开放 PDF 自动下载、pypdf 文本抽取、正文分块入库和全文证据检索。
- Ollama 本地模型生成，默认 `qwen2.5:7b`；不可用时自动规则降级。
- ReAct 风格执行轨迹：Thought、Query Rewrite、Intent Router、Tool Calling、Observation、Judge Verdict、Answer。
- Tool Registry 和 MCP-compatible `/mcp/tools`、`/mcp/call` 接口。
- Redis 可选缓存；没有 Redis 时自动使用内存缓存。
- MySQL 可选配置；默认 SQLite，保证普通 Windows 环境直接运行。
- Harness 实时评测（50 条用例覆盖 6 种意图），输出 Recall@5、MRR、Judge 拒绝率、平均迭代轮数、p50/p95 延迟和逐条结果。
- 面试演示防翻车：预热脚本预缓存数据，API 限流时自动回退本地缓存。

## 启动

```bash
cd KnowledgePilot
pip install -e .
python scripts/init_db.py
python scripts/warmup_demo.py   # 预热演示数据（可选但推荐）
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/docs` 可以查看接口；另开一个终端启动中文页面：

```bash
streamlit run app/ui/streamlit_app.py
```

也可以使用项目脚本：

```powershell
.\scripts\run_api.ps1
.\scripts\run_ui.ps1
```

## Worker-Judge 协作流程

```text
用户问题
  → Query Rewrite + Intent Router
  → Worker Agent（LLM 驱动，规则降级）
      → Thought：分析问题，决定工具调用计划
      → Tool Calling：search_papers / get_paper / ensure_fulltext
      → Observation：收集证据
      → Generator：基于证据生成中文答案 + 引用
  → Judge Agent（LLM 驱动，规则降级）
      → 证据充分性检查：结论是否有证据支持？
      → 引用真实性校验：DOI 是否在检索结果中？
      → 问题匹配度检查：是否答非所问？
      → 拒答正确性检查：证据不足时是否正确拒答？
      → PASS → 返回答案
      → REJECT → 反馈给 Worker，改写搜索词后重试（最多 3 轮）
  → Harness Metrics
```

## 使用顺序

1. 在页面左侧输入主题，例如 `retrieval augmented generation`，点击"同步真实论文"。
2. 在"论文搜索"输入 `attention is all`、`BERT pre-training`、`CNN相关论文` 或作者/关键词。
3. 在"详情/全文"输入 DOI 或 arXiv ID，点击"自动下载/解析开放全文"。
4. 在"中文 Agent 对话"询问"请介绍 Attention Is All You Need 这篇论文提出的方法，详细从原理分析"。
5. 展开 Trace 查看 Worker 的 Thought、工具调用、Judge 评审、迭代轮数和耗时。
6. 运行评测：

```bash
python harness/evaluate.py
```

报告写入 `harness/reports/latest.json`，包含任务成功率、Recall@5、MRR、答案事实覆盖率、拒答准确率、工具选择准确率、Judge 拒绝率、平均迭代轮数、p50/p95 延迟。报告中的数字是本机当前网络和数据源实时产生的实测结果，不是预设指标。

## 可选增强

启动 Redis 和 MySQL：

```bash
docker compose up -d
```

然后在 `.env` 配置 `KP_REDIS_URL=redis://127.0.0.1:6379/0`。

## Ollama 部署

推荐安装本地模型：

```bash
ollama pull qwen2.5:7b
python scripts/check_ollama.py
```

完整说明见 [OLLAMA_DEPLOY.md](OLLAMA_DEPLOY.md)，架构说明见 [ARCHITECTURE.md](ARCHITECTURE.md)，秋招展示话术见 [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md)。

## 面试表达

可以描述为：独立实现基于真实科研数据的双 Agent 系统，Worker Agent 负责工具调用和答案生成，Judge Agent 负责证据充分性、引用真实性和问题匹配度评估，不通过时反馈重试；融合 OpenAlex/Crossref 检索、混合排序、全文 RAG、ReAct Tool Calling、MCP 工具协议、Redis 缓存、SQLAlchemy 持久化和 50 条 Harness 回归评测。
