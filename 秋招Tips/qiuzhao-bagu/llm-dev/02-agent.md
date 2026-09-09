# 02 · Agent / 工具调用 / 多智能体

> Agent 是 2024-2026 大模型应用最热方向。秋招必考 Function Calling、ReAct、多 Agent 协作。

---

## 题 1:设计一个能调用工具的 Agent ⭐⭐⭐⭐⭐

### 【场景】
做一个客服 Agent,能根据用户问题查询订单、查物流、退款、转人工。给出完整设计。

### 【考察点】
Agent 架构、Function Calling、循环控制、错误处理

### 【答案要点】

**1. 核心循环(ReAct 模式)**

```
while not finished:
  ① Thought: LLM 推理当前状态 + 决定下一步
  ② Action: 选择工具 + 参数(Function Calling)
  ③ Observation: 执行工具,拿结果
  ④ 把 (Thought, Action, Observation) 加进上下文
→ Final Answer
```

**2. 工具定义(Function Calling)**

```json
{
  "name": "query_order",
  "description": "查询订单状态",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": {"type": "string", "description": "订单号"}
    },
    "required": ["order_id"]
  }
}
```
- 工具描述要清晰,LLM 靠 description 决定用哪个
- 参数用 JSON Schema 严格定义,LLM 输出结构化参数
- 主流模型(GPT-4/Claude/Qwen)原生支持 Function Calling

**3. 工具列表**
- `query_order(order_id)`:查订单
- `query_logistics(order_id)`:查物流
- `refund(order_id, reason)`:退款(需二次确认)
- `transfer_human(reason)`:转人工

**4. 关键工程点**

| 点 | 做法 |
|---|---|
| **循环终止** | 最大步数限制(如 10 步)、LLM 输出 `finish` 标志 |
| **参数校验** | LLM 输出 JSON 后用 Pydantic 校验,失败让 LLM 重试 |
| **工具失败** | try-catch,把错误信息塞回 Observation 让 LLM 自纠 |
| **幂等** | 工具调用记录 ID,重复调用检测 |
| **危险动作** | refund 类操作要 LLM 输出"确认" + 用户二次确认 |
| **超时** | 单步工具调用超时熔断 |
| **审计** | 记录每次工具调用 + 参数 + 结果,便于复盘 |

**5. 上下文管理**
- 多轮对话:维护完整 history(用户/助手/工具调用/工具结果)
- 上下文过长:摘要历史 + 保留最近 N 轮
- 工具结果太长:摘要或截断(如长 JSON 提取关键字段)

**6. 框架选型**
- **LangChain**:生态全,但抽象重、调试难
- **LangGraph**:状态机式 Agent,可控性强,主流推荐
- **LlamaIndex**:擅长 RAG-Agent 结合
- **自研**:简单场景用 OpenAI SDK 原生 Function Calling + 循环即可,过度工程要避免

### 【加分追问】
- **Q: 怎么防止 Agent 死循环?** A: ① 最大步数硬限制 ② 检测连续相同 (Thought, Action) 重复→强制终止 ③ 工具失败超阈值→转人工 ④ 监控每步 token 消耗,超限熔断。
- **Q: LangGraph 比 LangChain AgentExecutor 好在哪?** A: LangGraph 是显式状态图(节点+边),流程可视化、可断点续跑、可并行分支;AgentExecutor 是黑盒循环,难调试难控制。
- **Q: OpenAI Assistants API vs 自己写循环?** A: Assistants API 简单但黑盒、难定制、数据出境;自研可控性强但工程量大。生产环境倾向自研 + 框架(LangGraph)。

---

## 题 2:Function Calling vs ReAct vs Plan-and-Execute ⭐⭐⭐⭐⭐

### 【场景】
三种 Agent 范式有什么区别?分别什么时候用?

### 【答案要点】

**1. 三种范式对比**

| 范式 | 思路 | 优点 | 缺点 | 适用 |
|---|---|---|---|---|
| **Function Calling** | 模型原生输出结构化工具调用 | 快、稳、原生支持 | 无显式推理,复杂任务规划弱 | 单步/少步工具调用 |
| **ReAct** | Thought→Action→Observation 循环 | 推理过程可解释、可纠错 | 慢、token 多、可能死循环 | 多步推理任务 |
| **Plan-and-Execute** | 先 Plan(拆子任务)再 Execute(逐一执行) | 全局规划,减少中途发散 | 计划僵化,出错难纠 | 复杂长任务 |

**2. Function Calling 详解**
- 模型训练时就支持(JSON 模式 + 工具 schema),输出工具名 + 参数 JSON
- 适合"用户问 → 调一个工具 → 答案"的简单流程
- 主流模型都支持:GPT-4/GPT-4o、Claude 3.5+、Qwen2.5+、DeepSeek
- 工具描述好 = 成功一半:description 要写清"什么时候用""参数含义""返回什么"

**3. ReAct 详解**
- 论文 2022,经典:Reasoning + Acting 交替
- 适合需要"看一步走一步"的任务:搜索→分析→再搜索
- Prompt 模板:`Thought: ... Action: ... Observation: ...`
- 缺点:每步都要 LLM 推理,慢;长任务上下文爆炸

**4. Plan-and-Execute**
- 先让 LLM 一次性生成任务计划(子步骤列表)
- 再逐个执行(可并行/可分给子 Agent)
- 优点:全局视野,减少反复横跳;缺点:计划错了全错,需中途重新规划
- 代表:LangChain Plan-and-Execute、BabyAGI

**5. 选型决策**
- 简单工具调用(查天气/查订单)→ **Function Calling** 直接用
- 需要观察中间结果决策(查→分析→再查)→ **ReAct**
- 复杂长任务(写报告/做项目)→ **Plan-and-Execute** 或 ReWOO
- 实际多混合:Plan 拆解 + ReAct 执行子任务

**6. 趋势**
- **OpenAI Swarm / 多 Agent**:把任务分给不同角色 Agent 协作(见题 4)
- **Anthropic Computer Use**:Agent 直接操作 GUI
- **MCP 协议**:标准化工具接入(见题 7)

### 【加分追问】
- **Q: ReAct 的 Observation 怎么塞回 LLM?** A: 作为 `tool`/`function` role 的消息追加到上下文,下一轮 LLM 看到结果继续 Thought。
- **Q: 为什么 Function Calling 比 Prompt 引导的 ReAct 稳?** A: 模型训练时学过 JSON Schema 输出,结构化更稳;Prompt 引导靠模型自觉,复杂参数易出错。

---

## 题 3:Agent 陷入死循环/工具调用错误怎么处理? ⭐⭐⭐⭐

### 【场景】
Agent 上线后出现:反复调同一工具、参数填错、调不存在工具、卡在某步不出结果。怎么治?

### 【答案要点】

**1. 死循环检测**
- **硬限制**:最大步数(如 10)、最大 token、最大时长
- **重复检测**:连续 N 步 (Thought, Action, 参数) 完全相同 → 强制终止
- **状态哈希**:对"上下文指纹"做 LRU,重复状态触发兜底
- **回退策略**:死循环后转人工 / 给默认答案 / 换更简单策略

**2. 参数错误**
- **Schema 校验**:LLM 输出 JSON 后用 Pydantic/jsonschema 严格校验,失败重试
- **重试上限**:最多重试 N 次,超出转人工
- **错误反馈**:把校验错误信息塞回 Observation,LLM 会自纠(如"order_id 缺失,请提供")
- **参数填充**:槽位没填全 → LLM 主动反问用户(如"请提供订单号")

**3. 工具调用错误**
- **工具不存在**:LLM 幻觉编工具名 → 限制 tool 集合 + Prompt 明确"只能用这些工具"
- **工具执行失败**:网络错误/API 超时 → 重试 + 熔断;失败 N 次后转人工
- **工具返回异常**:返回 null/错误 JSON → 兜底返回 + 让 LLM 决定下一步

**4. 通用鲁棒性**
- **结构化输出**:用 JSON Mode / Constrained Decoding 强制 LLM 输出合法 JSON
- **少样本示例**:Prompt 给 2-3 个正确调用的例子,降低出错率
- **工具描述精炼**:description 写清"何时用""参数""返回",减少 LLM 选错
- **监控埋点**:每步工具调用 + 参数 + 结果 + 耗时,异常告警
- **降级路径**:Agent 复杂流程失败 → 退化为简单 RAG 或人工

**5. 评估**
- 离线:构造 Agent 测试集(任务 + 期望工具调用序列),算工具选择准确率、参数准确率、任务完成率
- 在线:监控任务完成率、平均步数、转人工率、用户满意度

### 【加分追问】
- **Q: 怎么测 Agent 的工具选择对不对?** A: ① 离线 golden set:人工标"该任务应调哪些工具",对比实际 ② 用更强模型当裁判判断调用是否合理 ③ 上线后业务指标(任务完成率)反向评估。
- **Q: 工具太多(100+) LLM 选不准怎么办?** A: ① 工具检索:把工具描述 Embedding,先检索 Top10 相关工具再给 LLM ② 分层:先选大类(订单/物流/退款)再选具体工具 ③ 按场景裁剪工具集。

---

## 题 4:多 Agent 协作架构怎么设计? ⭐⭐⭐⭐

### 【场景】
复杂任务(如"分析竞品并写报告")一个 Agent 搞不定,想拆成多个 Agent 协作。怎么设计?

### 【答案要点】

**1. 经典多 Agent 模式**

| 模式 | 结构 | 适用 |
|---|---|---|
| **Hierarchical(主从)** | 主 Agent 拆任务 → 子 Agent 执行 → 主汇总 | 复杂可分解任务,主流 |
| **Sequential(流水线)** | A→B→C 串行,前一个输出喂下一个 | 流程固定(研究→写作→校对) |
| **Parallel(并行)** | 多 Agent 同时做不同子任务,合并 | 独立子任务(多源调研) |
| **Debate(辩论)** | 多 Agent 辩论,裁判 Agent 综合 | 需要降低单 Agent 偏见 |
| **Swarm(群体)** | Agent 自治协调,无中心 | 探索性任务(OpenAI Swarm) |

**2. 关键设计**

- **任务分解**:主 Agent 用 Plan-and-Execute,把"分析竞品写报告"拆成"调研 A 公司""调研 B 公司""写大纲""写章节""校对"
- **角色定义**:每个 Agent 有清晰 system prompt(角色 + 工具 + 输出格式),减少越界
- **通信机制**:
  - 共享黑板(blackboard):所有 Agent 读写同一上下文
  - 消息传递:Agent 间显式发消息(LangGraph/AutoGen)
  - 文件传递:Agent 把产出写文件,下一个读
- **状态管理**:LangGraph 的 Graph State,显式管理中间状态
- **错误处理**:子 Agent 失败 → 主 Agent 决定重试/换策略/降级

**3. 框架选型**
- **LangGraph**:状态图式,可控性强,主流推荐
- **AutoGen**(微软):多 Agent 对话,易上手
- **CrewAI**:角色化,简单易用,适合固定流程
- **OpenAI Swarm**:轻量,Agent 间 handoff
- **MetaGPT**:软件公司角色化(PM/架构师/工程师)

**4. 坑**
- **过度工程**:简单任务别上多 Agent,单 Agent + RAG 够了
- **通信成本**:Agent 间消息多 = token 暴涨,要控上下文
- **调试难**:多 Agent 失败链路长,要全链路 trace
- **一致性**:多 Agent 结论冲突 → 加裁判 Agent / 投票

**5. 实战经验**
- 先单 Agent + 工具跑通,效果不够再拆
- 拆分维度:按领域(订单/物流)/按流程(研究/写作)/按角色(提问/回答/批判)
- 子 Agent 用小模型(便宜),主 Agent 用大模型(决策)

### 【加分追问】
- **Q: 多 Agent 一定比单 Agent 好吗?** A: 不一定。多 Agent 增加通信成本 + 调试复杂度;简单任务单 Agent + 好工具 + 好 Prompt 更优。论文/实践表明多 Agent 在复杂任务才有显著提升。
- **Q: Agent 间怎么共享状态?** A: LangGraph 用全局 Graph State(类 dict)在节点间传递;AutoGen 用对话历史;也可用 Redis/DB 共享。
- **Q: OpenAI Swarm 的 handoff 是什么?** A: Agent A 处理不了就把控制权和上下文交给 Agent B,无缝衔接;比硬编码流程灵活。

---

## 题 5:Agent 的记忆和状态怎么管理? ⭐⭐⭐

### 【场景】
Agent 长期运行(如私人助手),需要记住用户偏好、历史任务。怎么设计记忆系统?

### 【答案要点】

**1. 记忆分类**

| 类型 | 内容 | 实现 |
|---|---|---|
| **短期记忆** | 当前任务上下文(对话历史) | LLM 上下文窗口 |
| **长期记忆** | 用户偏好、历史事实 | 向量库 / KV 存储 |
| **工作记忆** | 当前任务的中间状态 | 状态图(LangGraph State) |
| **情景记忆** | 具体事件(上次说了什么) | 向量库 + 时间戳 |
| **语义记忆** | 抽象知识(用户偏好) | KV/图数据库 |

**2. 实现方案**

- **短期**:对话 history 直接放 prompt;超长用摘要压缩
- **长期**:
  - 每轮对话结束后,LLM 抽取"关键事实/偏好"写入向量库(Mem0 思路)
  - 下次对话开始,用当前 Query 检索相关记忆拼进 system prompt
  - 定期整合(避免碎片化):LLM 把多条记忆合并成"用户画像"
- **工作**:LangGraph 的 State 对象显式管理;或外部 Redis/DB

**3. 主流方案**
- **Mem0**:开源记忆层,自动抽取/检索/更新记忆
- **LangGraph Memory**:内置 checkpointer,持久化 Graph State
- **Letta(MemGPT)**:虚拟内存思路,LLM 自己管理记忆分页
- **手写**:向量库 + LLM 抽取 + Prompt 注入,最灵活

**4. 关键问题**
- **什么写入记忆**:不是所有对话都值得记;LLM 判断"是否值得长期保存"
- **记忆更新**:偏好变化要覆盖旧记忆;用 LLM 整合而非简单追加
- **记忆检索**:按语义检索 + 时间衰减(近期优先)
- **遗忘**:过期/低价值记忆定期清理,避免噪声
- **隐私**:敏感数据脱敏后再存

### 【加分追问】
- **Q: MemGPT 的虚拟内存是什么?** A: LLM 上下文当"内存",外部存储当"磁盘",LLM 主动决定何时把上下文内容"换出"到外部存储、何时"换入"。类 OS 分页思想。
- **Q: 记忆会让 Agent 变好吗?** A: 关键在质量。坏记忆(噪声/过时)反而拉低效果;好记忆(准确/相关)显著提升个性化和一致性。要配套评估和清理。

---

## 题 6:LangChain vs LlamaIndex vs 自研,怎么选? ⭐⭐⭐

### 【场景】
公司要建 LLM 应用,框架怎么选?

### 【答案要点】

**1. 三者定位**

| 框架 | 定位 | 强项 | 弱项 |
|---|---|---|---|
| **LangChain** | 通用 LLM 应用框架 | 生态全、社区大、组件多 | 抽象重、调试难、版本不兼容多 |
| **LangGraph** | LangChain 系状态图 Agent | 可控、可视化、可持久化 | 学习曲线 |
| **LlamaIndex** | 数据/RAG 框架 | RAG/索引强、文档处理优 | Agent 弱一些 |
| **自研** | 直接用 OpenAI/Anthropic SDK | 简单可控、无框架债 | 重复造轮子,工程量大 |

**2. 选型决策**

- **纯 RAG(检索问答)** → LlamaIndex 数据处理强
- **复杂 Agent / 多 Agent** → LangGraph 可控
- **简单工具调用** → 直接用模型 SDK + 几十行代码,别上框架
- **快速原型** → LangChain 生态全(但生产慎用)
- **大厂生产** → 自研核心 + 框架辅助(避免黑盒)

**3. 业界趋势**
- 反 LangChain 声音多:抽象过重、debug 难、性能损耗
- 趋势:**轻量 + 可控**:LangGraph(状态图)、OpenAI Agents SDK、自研
- RAG 框架:Dify/LangChain/LlamaIndex,核心都是"检索+生成"模板,选哪个看团队熟悉度

**4. 实战经验**
- 起步用模型原生 SDK + 100 行代码验证可行性
- 复杂度上来再加框架,优先 LangGraph(显式状态好调)
- 别一上来就 LangChain 全家桶,后期重构成本高

### 【加分追问】
- **Q: Dify / Coze / n8n 这类低代码平台怎么样?** A: 适合非技术用户快速搭应用,生产环境定制性差、难调试。开发者场景自研或框架更可控。
- **Q: 为什么有人说"LangChain 是反模式"?** A: 抽象层太多(Runnable/Chain/Agent/LCEL),简单事情复杂化,debug 困难,生产环境难维护。但生态和文档是优势,学习用没问题。

---

## 题 7:MCP 是什么?解决了什么问题? ⭐⭐⭐

### 【场景】
Anthropic 推的 MCP(Model Context Protocol)是什么?为什么要用它?

### 【答案要点】

**1. MCP 是什么**
- Model Context Protocol,Anthropic 2024 推出的开放协议
- 标准化 LLM 应用与外部数据源/工具的连接方式
- 类比:USB-C 之于设备,统一 LLM ↔ 工具的接口

**2. 解决的问题**
- 之前:每个 LLM 应用接每个工具都要写专门的集成( NxM 问题)
- 之后:工具实现 MCP server,任何 MCP 客户端(LLM 应用)都能用(N+M)

**3. 架构**
- **MCP Server**:暴露资源(Resources)/工具(Tools)/提示(Prompts)
- **MCP Client**:LLM 应用(如 Claude Desktop、Cursor、Cline)
- **协议**:JSON-RPC 2.0 over stdio/SSE
- 一个 Client 可连多个 Server,聚合多个工具源

**4. 价值**
- 工具复用:写一次 MCP server,GitHub/Slack/DB 通用
- 解耦:换 LLM 不用改工具集成
- 生态:官方/社区已有大量 MCP server(GitHub/Slack/Postgres/文件系统等)

**5. 现状与局限**
- 2024 末发布,生态在快速成长
- 局限:协议仍在演进,性能(大量数据传输)/安全(权限)在完善
- 与 Function Calling 互补:Function Calling 是模型能力,MCP 是工具接入协议

### 【加分追问】
- **Q: MCP 和 Function Calling 冲突吗?** A: 不冲突。MCP 是"LLM 应用如何发现和调用工具"的协议;Function Calling 是"模型如何输出工具调用"。MCP server 把工具暴露给应用,应用把工具列表转成 Function Calling 格式给模型。
- **Q: MCP 适合生产吗?** A: 中小规模可用;大规模生产要注意安全(工具权限)、性能(大数据传输)、监控。生态成熟度在提升。

---

## 题 8:Computer Use / 浏览器 Agent 怎么实现? ⭐⭐⭐

### 【场景】
Anthropic Computer Use、OpenAI Operator 让 Agent 操控 GUI,原理是什么?

### 【答案要点】

**1. 核心思路**
- Agent 看屏幕截图 → 决定下一步动作(点击坐标/输入/滚动)→ 执行 → 再看截图
- 本质:多模态模型 + 视觉理解 + 工具调用,把"屏幕"当工具

**2. 实现要素**

| 组件 | 作用 |
|---|---|
| 屏幕截图 | 模型输入(视觉) |
| 动作空间 | click(x,y)/type(text)/scroll/key/screenshot |
| 状态历史 | 之前的截图+动作序列 |
| 执行器 | 真正操作 OS(PyAutoGUI)或浏览器(Playwright) |

**3. Anthropic Computer Use**
- Claude 3.5 Sonnet Computer Use:模型直接输出 `click`、`type`、`key`、`screenshot` 工具调用
- 在虚拟机/沙箱里跑,截图 → Claude 决策 → 执行 → 循环
- 适合:GUI 自动化、复杂网页操作、跨应用流程

**4. 浏览器 Agent(更轻量)**
- Playwright/Puppeteer 控制 Chromium,不靠视觉而靠 DOM/可访问性树
- 优势:快、准(像素坐标 vs DOM 选择器)、便宜(不需多模态)
- 劣势:不能操控非浏览器 GUI;Canvas/复杂 JS 渲染页难

**5. 挑战**
- **精度**:视觉模型点坐标偏差几像素就点错 → 加 accessibility tree 辅助
- **延迟**:每步截图 + 推理慢(秒级)
- **鲁棒性**:页面变化/UI 改版导致失败
- **成本**:多模态推理贵
- **安全**:沙箱隔离,防 Agent 误删/误操作

**6. 适用场景**
- ✅ 重复 GUI 操作(填表单/抓数据/跨应用流程)
- ✅ 没有 API 的旧系统自动化
- ❌ 高频实时(太慢)、高精度(易点错)、安全关键(误操作风险)

### 【加分追问】
- **Q: 视觉 Agent vs DOM Agent 选哪个?** A: 有 API/DOM 优先用结构化方式(快、准、便宜);只有纯视觉(Canvas/图片/桌面 GUI)才上视觉 Agent。混合方案:DOM 为主,视觉兜底。
- **Q: 怎么评估 Computer Use Agent?** A: OSWorld / WebArena / VisualWebArena benchmark;任务完成率 + 步数 + 时间;真实场景灰度上线看业务指标。
