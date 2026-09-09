# Claude Code 的 Vibe Coding - 八股速记

> 适用范围：秋招 AI Infra 岗位（推理框架开发 / AI 工具链方向）
> 涵盖：Claude Code 工作流 / Agent 范式 / Skills / Hooks / 配置 / 与传统 IDE 的差异
> 注：Claude Code 是 Anthropic 官方 CLI/IDE agent；本节同样适用于 OpenCode、Cursor 等同类工具

---

## 一、Vibe Coding 是什么

### Q1. "Vibe Coding" 一词来源？
- 2025 年 Andrej Karpathy 提出，指**用自然语言驱动 AI agent 完成代码工作**，开发者只描述"vibe（感觉/意图）"，AI 写代码、跑测试、改 bug、提 PR。
- 不是"无脑生成"：成熟 vibe coding 依赖**结构化的 agent + 工具 + 评审循环**。

### Q2. Vibe Coding vs Copilot/Auto-complete？
| 维度 | Copilot / Tab 补全 | Vibe Coding |
|---|---|---|
| 粒度 | 单行/单函数 | 整个文件/功能/PR |
| 交互 | 静默补全 | 多轮对话 + 工具调用 |
| 自主性 | 低（人确认每步） | 高（agent 自主 plan/execute/verify） |
| 上下文 | 当前文件 + 邻近 | 全仓 + 外部文档 + 运行时 |

### Q3. Claude Code 的核心定位？
- Anthropic 官方的 agentic CLI（开源，2025 年发布）。
- 在终端运行，可读写文件、跑命令、调 MCP server、调用 subagent。
- 同类产品：OpenCode、Cursor、Aider、Continue、GitHub Copilot Workspace。
- 与 LLM 推理框架（vLLM）的关系：vibe coding 是**生产力工具**，与推理框架部署正交。

---

## 二、Agent / Subagent 架构

### Q4. Claude Code 的 agent 模型？
- 主 agent 接收用户指令，可 spawn **subagent**（子任务）并行/串行执行。
- subagent 类型：`explore`（grep 代码）、`oracle`（高级推理）、`build`（实现）、`plan`（规划）、`librarian`（外部文档查询）等。
- 每个 subagent 有独立 context window，避免主 agent 上下文爆炸。
- 通信：主 agent 发 prompt → subagent 执行 → 返回结果（不含中间过程）。

### Q5. 为什么需要 subagent？
- **隔离上下文**：explore 一个大仓库可能读几十个文件，主 agent 不必承担这些 token。
- **并行化**：5 个独立查询可同时跑。
- **专业化**：不同 agent 用不同 system prompt + 不同模型（如 oracle 用 Opus，explore 用 Haiku）。
- **失败隔离**：subagent 失败不污染主流程。

### Q6. Plan → Execute → Verify 循环？
- **Plan**：分析请求、拆解任务、列出 todo。
- **Execute**：按 todo 调用工具（edit/bash/read/write）。
- **Verify**：跑测试 / lsp 诊断 / 手动试运行，确认结果符合预期。
- 失败：读错误 → 改方法 → 重试；3 次失败后停下咨询 oracle 或人。
- 这是所有 vibe coding agent 的核心循环。

### Q7. 上下文管理（Context Engineering）？
- LLM context 窗口有限（200k token），但代码库动辄百万行。
- 策略：
  - **代码索引**（codegraph、ctags）：先建符号图，按需取相关代码片段。
  - **RAG**：把代码 chunk + embedding，检索 top-k。
  - **Todo List**：把长期目标拆成 todo，每步只关注当前 todo。
  - **Subagent 卸载**：把大块探索扔给 subagent。
  - **Compact**：定期压缩历史，保留关键决策。

### Q8. Tool Use 协议？
- Claude/OpenAI 等模型支持 function calling。
- 工具定义：name + description + JSON schema parameters。
- 模型输出 tool_call，agent 执行后返回 tool_result。
- Claude Code 工具集：`Read` / `Edit` / `Write` / `Bash` / `Grep` / `Glob` / `WebFetch` / `Task`（spawn subagent）等。

---

## 三、Skills 与 Hooks

### Q9. Skill 是什么？
- 领域专用指令包：一段 markdown，描述"什么场景下、按什么流程、用什么约束工作"。
- 用法：`/skill-name` 命令加载，或 agent 自动 trigger。
- 例子：`/security-review`（安全审计）、`/refactor`（重构）、`/debugging`（调试）、`/frontend`（前端规范）。
- skill 文件通常含：触发条件 + 工作流 + 引用文档 + 检查清单。

### Q10. Skill vs System Prompt？
- system prompt：全局、固定、对所有任务生效。
- skill：按需加载、领域专用、可叠加。
- 类比：system prompt 是"职业操守"，skill 是"专项操作手册"。

### Q11. Hooks 机制？
- 在 agent 生命周期的特定点注入自定义逻辑。
- 常见 hook 点：
  - `PreToolUse`：工具调用前（可拦截/修改参数）。
  - `PostToolUse`：工具调用后（可校验结果）。
  - `Stop`：agent 决定停止前（可强制继续）。
  - `Notification`：完成任务时（发桌面通知）。
- 用途：自动 lint、commit 前跑测试、敏感操作审批。

### Q12. MCP（Model Context Protocol）是什么？
- Anthropic 提出的开放协议，让 LLM 与外部数据源/工具通信。
- MCP server 暴露 resources（数据）+ tools（操作）+ prompts（模板）。
- Claude Code / Cursor / Continue 都支持。
- 典型 MCP server：GitHub、Slack、Notion、PostgreSQL、Playwright（浏览器）。

---

## 四、配置与定制

### Q13. Claude Code 的配置层级？
- `~/.claude/settings.json`：用户全局。
- `<project>/.claude/settings.json`：项目级（提交到 git）。
- `<project>/.claude/settings.local.json`：项目本地（gitignore）。
- 命令行参数：临时覆盖。
- 优先级：CLI > local > project > user。

### Q14. AGENTS.md / CLAUDE.md 是什么？
- 项目根的 markdown 文件，给 agent 提供"项目说明书"。
- 内容：项目结构、编码规范、依赖、测试命令、PR 流程、特殊注意事项。
- agent 启动时自动读入，相当于"入职文档"。
- 层级：根目录 + 子目录都可有，agent 进入子目录时叠加。

### Q15. 权限模型？
- 默认 ask：编辑文件、跑 bash 命令前需用户确认。
- `allowedTools`：白名单，自动放行。
- `disallowedTools`：黑名单，永远禁止。
- 危险操作：`rm -rf`、`git push --force`、生产数据库写、发送外部消息——永远要确认。
- 容器/沙箱：在 Docker/firejail 里跑 agent，限制爆炸半径。

---

## 五、与传统 IDE 的差异

### Q16. Claude Code vs VS Code + Copilot？
| 维度 | VS Code + Copilot | Claude Code |
|---|---|---|
| 形态 | GUI 插件 | CLI/Agent |
| 自主性 | 补全为主 | 自主 plan/execute |
| 跨文件 | 弱 | 强（subagent + codegraph） |
| 工具调用 | 无 | bash/edit/read/write/MCP |
| 测试运行 | 手动 | 自动 |
| 适合 | 单文件细节 | 整功能/重构/调试 |

### Q17. Vibe Coding 的工程化挑战？
- **可复现性**：同样 prompt 不同结果，难回归。
- **质量评估**：怎么判断 agent 写的代码"够好"？
- **上下文成本**：每次跑都消耗 token，大仓库 RAG 贵。
- **安全**：agent 跑 bash 命令有提权风险。
- **审计**：谁改了哪行？为什么？需要完整 trace。
- 解决：CI 跑 agent PR、代码评审、强制 lint+test、操作日志。

### Q18. 何时用 vibe coding？
**适合**：
- 重复性高、模板化任务（CRUD、迁移、补测试、写文档）。
- 不熟悉的新框架/库（agent 帮查文档）。
- 调试时卡住（agent 多角度探索）。
- 大重构（agent 列影响面 + 批量改）。

**不适合**：
- 高安全/合规场景（金融、医疗）。
- 极致性能优化（需深度领域知识）。
- 一次性小改动（启动 agent 比直接改慢）。
- 涉及未公开业务逻辑的代码。

---

## 六、AI Infra 岗位相关

### Q19. Agent 在 AI Infra 工作中的应用？
- **写算子**：让 agent 参考同类算子写新 op（aclnn 注册 + tiling + 测试）。
- **调优报告**：agent 跑 profiling → 解析 op_summary.csv → 写调优建议。
- **PR 流程**：fork → 改 → 跑 CI → 修 lint → 提 PR 全自动。
- **文档**：从代码生成 API 文档、写教程。
- **回归测试**：改一行代码，agent 自动找受影响的测试并跑。

### Q20. 用 Claude Code 贡献 vllm_ascend 的典型流程？
1. fork vllm-project/vllm-ascend 到个人 GitHub。
2. `git clone <my-fork>` + `git remote add upstream <原仓>`。
3. 启动 Claude Code（或 OpenCode）在仓库目录。
4. 描述任务："实现一个新的 attention backend，参考 attention_v1.py"。
5. agent 自动读相关代码、写实现、加测试、跑 lint。
6. 人审改动、跑完整 CI、提 PR。

### Q21. Vibe Coding 与 LLM 推理部署的关系？
- 正交：vibe coding 是开发态工具，推理部署是运行态产品。
- 但 vibe coding 的流行**直接拉动了 LLM 推理需求**：每个开发者都用 LLM，需要部署更多推理服务。
- 这也是为什么 vLLM / vllm_ascend / TensorRT-LLM 等推理框架火热。

---

## 七、一页速记卡

| 类别 | 必背 |
|---|---|
| Vibe Coding | Karpathy 2025；自然语言驱动 agent 写代码 |
| Claude Code | Anthropic 官方 CLI；同类 OpenCode/Cursor/Aider |
| Agent 循环 | Plan → Execute → Verify；失败重试 3 次咨询 |
| Subagent | 隔离上下文、并行、专业化、失败隔离 |
| Skills | 领域专用指令包；`/skill-name` 加载 |
| Hooks | PreToolUse/PostToolUse/Stop/Notification |
| MCP | 模型 ↔ 外部工具协议；resources/tools/prompts |
| 配置 | ~/.claude/ + .claude/ + .claude/settings.local.json |
| AGENTS.md | 项目说明书；agent 自动读入 |
| 权限 | ask/allowed/disallowed；危险操作必确认 |
| 适合 | 重复/模板/新框架/调试/重构 |
| 不适合 | 高安全/极致性能/一次性小改 |
