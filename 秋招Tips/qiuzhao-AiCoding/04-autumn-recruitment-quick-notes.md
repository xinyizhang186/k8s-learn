# 04 · 秋招八股速记(面试前一晚刷)

> 适用范围:秋招 AI Infra / Agent / LLM 方向,**面试前一晚必看**。
> 本文件只放**可直接背**的内容:定义、对比表、流程、金句、速记卡。
> 详解见同文件夹 01/02/03。
> 与 `qiuzhao-bagu/` 的关系:bagu 是按主题的深度题,本文件是 Vibe/Spec/Skill 的速记版。

---

## 一、概念定义(一句话背)

| 概念 | 一句话定义 |
|---|---|
| **Vibe Coding** | Karpathy 2025 提出,自然语言驱动 AI agent 写代码,开发者只描述意图 |
| **Spec Coding** | 规范先行,先写 spec(OpenAPI/protobuf)再让 AI 填实现 |
| **Skill** | 领域专用可复用指令包,markdown + references + checklist |
| **System Prompt** | 全局稳定的 agent 行为基线,所有任务生效 |
| **Hook** | 在 agent 生命周期特定点注入自定义逻辑(PreToolUse/PostToolUse/Stop) |
| **Subagent** | 独立 context window 的子任务 agent,主 agent spawn 出来 |
| **MCP** | Model Context Protocol,Anthropic 提出,LLM ↔ 外部工具协议 |
| **A2A** | Agent2Agent,Google 提出,Agent ↔ Agent 互调协议 |
| **AgentCard** | A2A 中描述 agent 能力的 JSON spec |
| **Function Calling** | LLM 原生工具调用协议,输出 JSON 参数 |
| **AGENTS.md / CLAUDE.md** | 项目说明书 markdown,agent 启动自动读入 |
| **.cursorrules / opencode.json** | 工具特定配置,固化 agent 行为 |
| **Codegraph** | 代码符号图索引,AST 精确,按需取相关片段 |
| **RAG** | 检索增强生成,embedding + top-k 检索注入上下文 |
| **Kiro** | AWS 2025 出的 spec-driven IDE |
| **GitHub Spec Kit** | GitHub 2025 出的开源 spec 工具链 |
| **Pact** | 主流 contract testing 框架,双向契约验证 |
| **Schemathesis** | Python OpenAPI 自动 fuzz 测试工具 |
| **Prism** | 从 OpenAPI 启 mock server 的工具 |
| **Spectral** | OpenAPI spec lint 工具,Stoplight 出 |
| **Plan-Execute-Verify** | Agent 核心循环:规划 → 执行 → 验证 |
| **Hypothesis-driven** | 调试方法论:先列假设再调查,避免 shotgun |
| **Boulder / Ralph** | 长任务跨多轮续接机制 |
| **Codegen** | 从 spec 自动生成 skeleton(server/client/SDK/doc/mock) |

---

## 二、对比表(高频必背)

### 2.1 Vibe vs Spec(最高频)

| 维度 | Vibe Coding | Spec Coding |
|---|---|---|
| 起点 | 自然语言 prompt | spec 文件(OpenAPI/protobuf) |
| 粒度 | 整功能/PR | 单接口/schema |
| 确定性 | 低(LLM 主导) | 高(spec 锁死契约) |
| 可审计 | 弱 | 强 |
| 协作 | 个人/小团队 | 跨团队/多服务 |
| 上下文成本 | 高 | 低(骨架已生成) |
| 灵活性 | 高 | 低 |
| 上手 | 低 | 中(要会 spec 工具) |
| 复用 | 低 | 高(一份 spec 生多端) |
| 失败模式 | 上下文爆炸/风格漂移 | spec 与实现脱节/过度设计 |
| 场景 | 原型/个人/重构 | API/合规/SDK |
| 金句 | 边感觉边写 | 先约定后做 |

> **结论**:不是二选一,分层用——外层 Spec,内层 Vibe。

### 2.2 Skills vs 相邻概念

| 维度 | Skill | System Prompt | Tool | MCP | Plugin | Subagent |
|---|---|---|---|---|---|---|
| 形态 | markdown | 字符串 | 函数 | 协议+服务 | 二进制 | 独立 agent |
| 加载 | 按需 | 启动 | 调用时 | 启动连接 | 安装时 | spawn |
| 范围 | 领域 | 全局 | 单操作 | 跨进程 | 跨进程 | 独立 context |
| 修改 | 改 md | 改配置 | 改代码 | 改 server | 重打包 | 改 subagent |
| 复用 | 跨项目 | 项目内 | 项目内 | 跨项目 | 跨项目 | 项目内 |

> **金句**:system prompt = 员工手册;skill = 专项 SOP;tool = 工具;MCP = 外部供应商;subagent = 外包专员。

### 2.3 Vibe vs Copilot 补全

| 维度 | Copilot/Tab 补全 | Vibe Coding |
|---|---|---|
| 粒度 | 单行/单函数 | 整文件/功能/PR |
| 交互 | 静默补全 | 多轮对话+工具调用 |
| 自主性 | 低 | 高(plan/execute/verify) |
| 上下文 | 当前文件+邻近 | 全仓+外部文档+运行时 |

### 2.4 Claude Code vs Cursor vs Aider

| 维度 | Claude Code | Cursor | Aider |
|---|---|---|---|
| 形态 | CLI/agent | GUI IDE | CLI |
| 厂商 | Anthropic | Anysphere | 开源 |
| 工具调用 | 强(MCP/subagent) | 中 | 中 |
| 上下文 | 全仓+codegraph | 项目+chat | 单文件为主 |
| 适合 | 整功能/调试/重构 | 日常编辑 | 单文件迭代 |

### 2.5 Codegraph vs RAG

| 维度 | Codegraph | RAG |
|---|---|---|
| 准确性 | AST 精确符号级 | 模糊检索 |
| 速度 | <1ms | 10-100ms |
| 维护 | 自动建图 | 重建 embedding 慢 |
| 适用 | 自家代码库 | 外部文档/issue |

> **经验**:自家代码库优先 codegraph,外部知识用 RAG。

### 2.6 MCP vs A2A

| Spec | 角色 | 例 |
|---|---|---|
| MCP | LLM ↔ 工具 | Claude 调 GitHub MCP |
| A2A | Agent ↔ Agent | 订单 Agent 调物流 Agent |
| Function Calling | LLM ↔ 用户函数 | OpenAI tool_use |
| OpenAPI | 服务 ↔ 服务 | REST API 契约 |
| AgentCard | Agent 元信息 | "我会查订单+退款" |

### 2.7 Plan-Execute-Verify vs Hypothesis-driven

| 维法 | 适用 | 流程 |
|---|---|---|
| Plan-Execute-Verify | 通用任务 | 列 todo → 执行 → 验证 → 失败重 plan |
| Hypothesis-driven | 调试 | 列 ≥3 假设 → 并行调查 → 2 轮失败 spawn oracle |

---

## 三、流程速记

### 3.1 Vibe Coding 单任务流程(7 步)

```
1. Git 干净 + AGENTS.md + 沙箱
2. 写 prompt 四要素:上下文 + 需求 + 约束 + 验收
3. 让 agent 先 Plan(列 todo + 影响面)
4. Execute(每改一文件跑 lsp)
5. Verify(测试 + lint + security scan)
6. 失败 → 3 次原则:同→换→停
7. 收尾:完整测试 + 人审 diff + commit + CI
```

### 3.2 Spec Coding 完整流程(6 步)

```
1. 写 spec(OpenAPI/protobuf,先粗后细)
2. Spec Review(Spectral lint)
3. Codegen(server interface/client SDK/models/mock/doc)
4. AI 填实现(只改指定函数体,不动 spec)
5. Contract Test(Schemathesis/Pact,CI 强制)
6. 版本管理(SemVer + Sunset header + 兼容窗口)
```

### 3.3 Skill 加载流程(6 步)

```
1. 用户 /name 或 agent 自动 trigger
2. 找到 SKILL.md 文件
3. 注入 system prompt(或临时消息)
4. 按需读 references/(不全读)
5. 按 SKILL.md 工作流执行
6. 跑 checklist 验收
```

### 3.4 Subagent 调用流程(5 步)

```
1. 主 agent 决定 spawn subagent
2. 选 type(explore/librarian/oracle/build/plan/metis/momus)
3. 发 prompt + 上下文
4. subagent 独立 context 执行(主 agent 不见中间过程)
5. 返回结果给主 agent(仅最终消息)
```

### 3.5 Hook 触发流程(4 类)

| Hook 点 | 时机 | 用途 |
|---|---|---|
| PreToolUse | 工具调用前 | 拦截/改参数/审批 |
| PostToolUse | 工具调用后 | 校验结果/记日志 |
| Stop | agent 决定停 | 强制继续(如 todo 没完) |
| Notification | 任务完成 | 桌面通知 |

### 3.6 调试 Skill 工作流(hypothesis-driven,7 步)

```
1. 列 ≥3 假设(避免单一思路)
2. 并行调查(每假设独立 subagent)
3. 2 轮失败 → spawn oracle 从新角度
4. 锁定根因(写失败测试证明)
5. 最小修复(只改必要)
6. 用真实系统验证(不只单测)
7. 收尾:失败测试变绿 + 真实行为正常
```

### 3.7 安全审计 Skill 工作流(Team Mode)

```
1. 3 vulnerability hunters 并行扫描(各负责 OWASP 一类)
2. 汇总候选漏洞
3. 2 PoC engineers 验证 exploitability
4. 按实际 exploitability 校准 severity
5. 输出报告(可利用漏洞,非理论漏洞)
```

### 3.8 代码审查 Skill 工作流(5 并行 subagent)

```
1. Oracle: 目标/约束验证
2. Oracle: 代码质量
3. Oracle: 安全
4. unspecified-high: QA 执行
5. unspecified-high: context mining(GitHub/Slack/Notion)
→ 5 项全过才放行
```

---

## 四、避坑速记表(高频坑)

### 4.1 Vibe Coding 通用坑

| 坑 | 现象 | 解 |
|---|---|---|
| 上下文爆炸 | agent 忘早期约定 | 拆任务+subagent+compact |
| 风格漂移 | 每次生成风格不同 | AGENTS.md+prettier+biome |
| 魔法数字 | 到处 0.7、42 | AGENTS.md 规定常量提取 |
| 代码冗余 | 重复函数 | refactor skill + 周期重构 |
| 类型 any 滥用 | `as any` 满天 | 禁 `as any`/`@ts-ignore` |
| 空 catch | `except: pass` | lint 禁空 catch |
| SQL 注入 | 拼字符串 | 强制 ORM+lint |
| 密钥泄露 | API key 进 git | gitleaks+pre-commit |
| 依赖幻觉 | import 不存在的包 | 装包前验证 |
| License 污染 | 引 GPL 到商业 | license-checker CI |
| 推送事故 | 误推 main | branch protection |
| 审计困难 | 谁改的哪行 | 强制操作日志 |
| 不可复现 | 同 prompt 不同结果 | 跑 N 次取众数 |
| token 烧光 | 一天 $100 | 模型分级+cache |
| PR 噴射 | 一次改 50 文件 | 规定 PR ≤ 500 行 |

### 4.2 Spec Coding 通用坑

| 坑 | 现象 | 解 |
|---|---|---|
| 前期成本高 | 卡在 spec 阶段 | 渐进式,先粗后细 |
| 过度设计 | 把边角塞 spec | YAGNI,只 spec 稳定接口 |
| spec 与代码脱节 | 改代码没改 spec | contract test CI |
| 生成代码质量差 | 默认模板烂 | 自定义 template |
| AI 越界改 spec | 改了 openapi.yaml | prompt 明确禁止+CI 校验 |
| 重复生成覆盖手改 | codegen 冲掉手改 | `_generated.py` 后缀+gitignore |
| breaking change 没察觉 | 客户端崩 | oasdiff CI |
| 多版本维护地狱 | v1/v2/v3 并行 | Sunset+兼容窗口 |
| enum 加值 breaking | 老客户端崩 | 客户端宽容+unknown 兜底 |
| codegen 慢 | 改一行等 10s | 增量生成+缓存 |

### 4.3 Skills 通用坑

| 坑 | 现象 | 解 |
|---|---|---|
| 一锅端 skill | 一个 skill 干所有 | 单一职责,拆 |
| trigger 太宽 | 误触发频繁 | 具体词+不与日常语重叠 |
| references 全读 | context 爆炸 | 按需读,不全读 |
| checklist 太松 | 验收走过场 | 必须可执行+可验证 |
| 多 skill 冲突 | 抢同一场景 | trigger 矩阵+优先级 |
| 假阳性提升 | 加流程就涨 | 对照 inline prompt 验证 |
| 跨工具不可复用 | 工具特定语法 | 纯 markdown+adapter |
| 没版本管理 | 改了不知道改啥 | git+SemVer+changelog |
| 无评估指标 | 不知道 skill 有没有用 | A/B 测试+baseline |

---

## 五、必背金句(可直接背到面试)

### 5.1 关于 Vibe Coding

1. **"Vibe Coding 不是无脑生成,是 PM 指挥初级工程师。"**
2. **"Vibe Coding 的核心循环是 Plan-Execute-Verify,失败 3 次找 oracle。"**
3. **"Vibe Coding 在生产环境不能纯用,三层防线:CI+人工审+规范固化。"**
4. **"Prompt 四要素:上下文+需求+约束+验收,少一个就跑偏。"**
5. **"任务粒度 ≤ 500 行,超了就拆。"**

### 5.2 关于 Spec Coding

1. **"Vibe 是边感觉边写,Spec 是先约定后做,生产环境两者分层用。"**
2. **"没有 contract test 的 spec 就是装饰品。"**
3. **"Spec 价值:多端复用+可审计+前后端并行。"**
4. **"渐进式 spec:V1 只列 path,迭代细化,避免卡死前期。"**
5. **"AI 看例子比看 schema 准,examples > schema。"**

### 5.3 关于 Skills

1. **"system prompt 是员工手册,skill 是专项 SOP。"**
2. **"Skill 不替代 agent,是给 agent 专项操作手册。"**
3. **"Skill 五指标:触发率/误触发率/完成率/修正次数/可维护性。"**
4. **"Skill 跨工具复用核心是抽象掉工具特定语法,用纯 markdown。"**
5. **"未来 agent 会自己写 skill,叫 self-improving agent。"**

### 5.4 关于 Agent 通用

1. **"Subagent 隔离上下文+并行+专业化+失败隔离,四价值。"**
2. **"自家代码库优先 codegraph,外部知识用 RAG。"**
3. **"模型分级:Haiku 探索/Sonnet 实现/Opus 决策,省成本。"**
4. **"MCP 是 LLM↔工具,A2A 是 Agent↔Agent,各管一段。"**
5. **"Agent 时代三种 spec 协同:OpenAPI 业务 API、MCP 工具、A2A agent。"**

---

## 六、高频面试问答(精简版)

### Q1: Vibe Coding 是什么?⭐⭐⭐⭐⭐
> "2025 年 Karpathy 提出,自然语言驱动 AI agent 写代码。开发者只描述意图,
> agent 负责 plan/execute/verify。核心循环 Plan→Execute→Verify,失败重试
> 3 次找 oracle。不是无脑生成,是 PM 指挥初级工程师。"

### Q2: Vibe Coding 怎么保证质量?⭐⭐⭐⭐⭐
> "三层防线:① 工具层 CI 跑 lint+test+security;② 流程层关键模块(auth/
> payment/crypto)强制人工逐行审;③ 规范层 AGENTS.md 固化风格和禁忌。
> 没审查的 vibe coding 在生产环境就是定时炸弹。"

### Q3: Vibe vs Spec 你怎么看?⭐⭐⭐⭐⭐
> "分层用,不是二选一。外层接口用 Spec(OpenAPI/MCP/A2A)——多端复用、
> 跨团队协作、合规可审计。内层实现用 Vibe——agent 在 spec 锁死的契约里
> 自由发挥。生产环境不能纯 vibe,也不能纯 spec,纯 spec 卡死前期。"

### Q4: Skill 是什么?⭐⭐⭐⭐⭐
> "领域专用可复用指令包,markdown+references+checklist 三件套。按需加载,
> 用户 `/name` 或自动 trigger。与 system prompt 区别:system 全局稳定,skill
> 按需领域专用。类比:system 是员工手册,skill 是专项 SOP。"

### Q5: Skill 怎么评估?⭐⭐⭐⭐⭐
> "五指标:触发率(recall)、误触发率(false positive)、任务完成率提升、
> 用户修正次数、可维护性。A/B 测试,带 skill vs 不带,跑 N 任务统计。
> 注意假阳性陷阱——加任何流程都短期提升,对照 inline prompt 才公平。"

### Q6: 多 Skill 冲突怎么办?⭐⭐⭐⭐
> "四层防线:① 触发词去重(设计时不重叠);② 优先级机制(用户级>项目级
> >全局);③ 显式优于隐式(`/name` 高于自动);④ 加载时去重相同指令。
> 真冲突说明设计有问题,该合并或拆分。"

### Q7: MCP 和 A2A 区别?⭐⭐⭐⭐
> "MCP(Anthropic)是 LLM 与工具的协议——Claude 通过 MCP 调 GitHub、Notion、
> Postgres。A2A(Google)是 Agent 与 Agent 的协议——订单 Agent 调物流 Agent。
> 一个解决模型调工具,一个解决 agent 互调。完整 Agent 系统同时用:OpenAPI
> 描述业务、MCP 接外部工具、A2A 调其他 Agent,三种 spec 协同。"

### Q8: Kiro 和 Claude Code 怎么选?⭐⭐⭐
> "Claude Code/OpenCode 是 Vibe 工具,适合个人项目、原型、重构、补测试——快、
> 灵活。Kiro 是 Spec-driven IDE,适合跨团队 API、合规场景、SDK 开发——稳、
> 可复用、可审计。我用 Claude Code 写实现、Spec Kit 管 spec,两者结合。"

### Q9: 你做过 Skill 吗?(模板)⭐⭐⭐⭐
> "我设计过 [skill 名],解决 [问题]。触发词 [词],工作流 [步骤],references
> 在 [目录]。实测 [指标] 从 [基线] 到 [结果],关键设计 [亮点]。例:/debugging
> skill,hypothesis-driven loop,bug 解决率 45% → 72%。"

### Q10: Agent 死循环怎么办?⭐⭐⭐⭐
> "① 最大步数硬限制;② 检测连续相同 (Thought, Action) 重复强制终止;
> ③ 工具失败超阈值转人工;④ 监控每步 token 超限熔断;⑤ 加调试 skill
> 用 hypothesis-driven,2 轮失败 spawn oracle 打破定势。"

### Q11: 上下文爆炸怎么办?⭐⭐⭐⭐
> "五大策略:① 代码索引(codegraph)按符号取片段;② RAG 外部知识;
> ③ subagent 卸载大块探索;④ todo list 持久化跨多轮;⑤ compact 压缩历史。
> 自家代码库优先 codegraph,外部知识用 RAG,大块探索扔 subagent。"

### Q12: Vibe Coding 不适合什么场景?⭐⭐⭐
> "三类:① 高安全/合规(金融医疗)——LLM 难保证审计合规;② 极致性能优化
> (算子 tiling)——需深度领域知识;③ 一次性小改动——启动 agent 比直接改慢。
> 适合:重复性高、模板化、新框架探索、调试卡住时多角度探索、大重构批量改。"

---

## 七、终极速记卡(一页背完)

| 类别 | 必背 |
|---|---|
| Vibe | Karpathy 2025;自然语言驱动 agent;Plan→Execute→Verify;3 次失败找 oracle |
| Spec | 规范先行;Kiro(AWS)/Spec Kit(GitHub)2025;OpenAPI/protobuf/MCP/A2A |
| Skill | 领域指令包;md+references+checklist;按需加载;SOLID 类比 |
| Hook | PreToolUse/PostToolUse/Stop/Notification |
| Subagent | 隔离上下文+并行+专业化+失败隔离 |
| MCP | LLM ↔ 工具(Anthropic) |
| A2A | Agent ↔ Agent(Google) |
| Codegraph | AST 精确,自家代码;RAG 外部知识 |
| 配置 | ~/.claude/ + .claude/ + .claude/settings.local.json |
| AGENTS.md | 项目说明书;agent 启动自动读 |
| 权限 | ask/allowed/disallowed;危险操作必确认 |
| Prompt 四要素 | 上下文+需求+约束+验收 |
| 任务粒度 | ≤ 500 行/次 |
| 模型分级 | Haiku 探索/Sonnet 实现/Opus 决策 |
| 失败原则 | 同→换→停;3 次找 oracle |
| 必审项 | 安全/类型/测试质量/复杂度/Diff/License |
| 关键模块人工审 | auth/payment/DDL/crypto/外部 API |
| Vibe 适合 | 重复/模板/新框架/调试/重构 |
| Vibe 不适合 | 高安全/极致性能/一次性小改 |
| Spec 流程 | 写 spec→lint→codegen→AI 实现→contract test→版本管理 |
| Spec 价值 | 多端复用+可审计+前后端并行 |
| Spec 渐进 | V1 只列 path,迭代细化 |
| LLM 喂法 | examples > schema |
| Contract Test | Schemathesis/Pact;CI 强制 spec==实现 |
| 版本兼容 | Additive-only;Sunset header;兼容窗口 |
| Skill 七要素 | metadata/触发/工作流/引用/清单/退出/指标 |
| Skill 类比 | system=员工手册;skill=专项 SOP |
| Skill SOLID | 单一职责/开闭/可替换/接口隔离/依赖倒置 |
| Skill 五指标 | 触发率/误触发率/完成率/修正次数/可维护性 |
| Skill 评估 | A/B 测试+baseline+回归;防假阳性 |
| Skill 调试 | trace log+trigger 单测+A/B+用户反馈 |
| Skill 版本 | git+SemVer+changelog+灰度 |
| Skill 跨工具 | 纯 md+通用接口+adapter |
| Skill vs RAG | skill 流程性,RAG 事实性,可结合 |
| 真实 skill | debugging/frontend/security-review/review-work/go-test |
| 金句 1 | Vibe 边感觉边写,Spec 先约定后做,生产分层用 |
| 金句 2 | 没有 contract test 的 spec 是装饰品 |
| 金句 3 | Skill 不替代 agent,是给 agent 专项手册 |
| 金句 4 | 自家代码 codegraph,外部知识 RAG |
| 金句 5 | MCP 调工具,A2A 调 agent |

---

## 八、口诀(背到考试前)

> **"Vibe 边感觉边写,Spec 先约定后做,Skill 是专项手册,八股背对比表。"**

> **"Vibe 三层防线:CI + 人工审 + AGENTS.md"**

> **"Spec 五步:写 spec → lint → codegen → AI 实现 → contract test"**

> **"Skill 五指标:触发率、误触发率、完成率、修正次数、可维护性"**

> **"Agent 三种 spec:OpenAPI 业务、MCP 工具、A2A agent"**

> **"模型分级:Haiku 探索,Sonnet 实现,Opus 决策"**

> **"Prompt 四要素:上下文+需求+约束+验收"**

> **"3 次失败原则:同思路→换方法→停咨询"**

---

## 九、面试前最后一晚 checklist

- [ ] 背 6 个金句(第 5 节)
- [ ] 背 3 张对比表(Vibe vs Spec / Skills vs 邻近 / MCP vs A2A)
- [ ] 背 7 个流程(Vibe 7 步 / Spec 6 步 / Skill 6 步 / Subagent 5 步 / Hook 4 类 / 调试 7 步 / 审查 5 并行)
- [ ] 背 12 个高频问答(第 6 节)
- [ ] 背终极速记卡(第 7 节)
- [ ] 准备 1 个"我做过 X skill"的故事(题 9 模板)
- [ ] 准备 1 个"我解决过 X 坑"的故事(Vibe/Spec 通用坑任挑)
- [ ] 看一眼最新动态:Kiro/Spec Kit/MCP/A2A 官方文档(防止追问)

---

## 十、参考文档(深挖用)

- 详解/01-vibe-coding-practice-and-pitfalls.md(实操细节)
- 详解/02-spec-coding-practice-and-pitfalls.md(Spec 全流程)
- 详解/03-skills-interview-deep-dive.md(Skill 10 题答法)
- qiuzhao-bagu/phase1-fundamentals/08-claude-vibe-coding.md(概念入门)
- qiuzhao-bagu/llm-dev/02-agent.md(Agent 基础)
- qiuzhao-bagu/llm-dev/12-agent-advanced.md(Agent 生产进阶)

> 工具版本迭代快,具体命令以官方文档为准。本文为速记版,详解见同文件夹其他文件。
