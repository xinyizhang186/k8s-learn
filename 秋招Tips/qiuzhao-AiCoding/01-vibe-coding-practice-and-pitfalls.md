# 01 · Vibe Coding 实战技巧与避坑指南

> 适用范围:秋招 AI Infra / Agent 方向,讲得出"我用 Claude Code/OpenCode 干过什么"。
> 与 `qiuzhao-bagu/phase1-fundamentals/08-claude-vibe-coding.md` 互补:那篇讲**是什么**,本篇讲**怎么做、怎么坑、怎么救**。

---

## 一、Vibe Coding 核心心智模型

### 1.1 不是"无脑生成",是"指挥 agent 干活"

Vibe Coding = 你是**产品经理 + 评审**,agent 是**初级工程师**。
- 你给:目标、约束、上下文、验收标准
- agent 给:计划、代码、测试、验证
- 你做:小步反馈、审查、回滚、决策

> 反模式:把整个项目甩给 agent "写个淘宝",结果上下文爆炸 + 风格漂移 + 安全漏洞。
> 正确:拆成 200-500 行的子任务,每次只让 agent 干一件事。

### 1.2 三大核心循环

```
┌─────────────────────────────────────────┐
│  外循环:Plan → Execute → Verify         │
│  ┌──────┐    ┌──────┐    ┌──────┐        │
│  │ Plan │ →  │Exec  │ →  │Verify│ → 失败回 Plan
│  └──────┘    └──────┘    └──────┘        │
│                                          │
│  内循环(Verify 失败时):                  │
│  读错误 → 换方法 → 重试(最多 3 次)        │
│  3 次失败 → 停下,咨询 oracle 或人         │
└─────────────────────────────────────────┘
```

---

## 二、实战工作流(从 0 到 1 上手)

### 2.1 启动前的环境准备(必做)

| 项 | 为什么 | 怎么做 |
|---|---|---|
| **Git 干净起点** | 失败可回滚 | `git init && git commit --allow-empty -m "init"` |
| **写 AGENTS.md/CLAUDE.md** | 固化项目规范 | 项目结构、技术栈、命令、禁忌 |
| **配 .cursorrules / opencode.json** | 工具特定规则 | 模型选型、权限、skill 列表 |
| **沙箱/容器** | 限制爆炸半径 | Docker/firejail 跑 agent |
| **分支保护** | 防 force push | `git config receive.denyNonFastForwards true` |
| **依赖锁定** | 防 agent 引幻觉包 | lockfile 提交,装包前比对 |

### 2.2 单次任务的完整流程

**Step 1 · 写需求(给 agent 的 prompt)**

```markdown
# 任务:实现订单查询 API

## 上下文
- 项目:基于 FastAPI 的电商后端(见 pyproject.toml)
- 已有代码:src/api/orders.py(参考其风格)
- 数据库:PostgreSQL,ORM 用 SQLAlchemy 2.0
- 测试框架:pytest + httpx

## 需求
- GET /api/v1/orders/{order_id} 返回订单详情
- 404 时返回 {"error": "order not found"}
- 只改 src/api/orders.py 和 tests/test_orders.py

## 约束
- 不引入新依赖
- 不动 src/api/auth.py
- 函数命名 snake_case
- 必须有 type hint

## 验收
- pytest tests/test_orders.py 全过
- curl 实测 200 和 404 都对
```

**关键**:prompt 给四要素——**上下文 / 需求 / 约束 / 验收**。少一个 agent 就容易跑偏。

**Step 2 · 让 agent 先 Plan,再 Execute**

- "先列 todo,列影响面,确认后再动手"——这是反幻觉的关键。
- agent 没列 plan 就直接改代码 → 打断,要求重做。
- 工具实现:`opencode` 的 `plan` agent / `claude --plan` 模式 / Cursor 的 chat 选项。

**Step 3 · Execute 期监控**

- 每改一个文件 → 跑 `lsp_diagnostics`(实时类型检查)
- 改完跑 `pytest -x` 或 `go test ./...`
- 失败 → 把**完整报错文本**(不截图)+ 复现步骤贴给 agent
- agent 没修对 → 换方法,不是再试一次同样的事

**Step 4 · Verify 期审查**

| 验证维度 | 工具/动作 |
|---|---|
| 类型/语法 | `lsp_diagnostics` / `tsc --noEmit` / `mypy` |
| 测试 | `pytest` / `go test` / `npm test` |
| Lint | `ruff` / `golangci-lint` / `biome` |
| 安全 | `gitleaks` / `semgrep` / `bandit` |
| 行为 | curl / 浏览器 / interactive_bash |
| Diff | `git diff --stat` 看是否动了不该动的文件 |

**Step 5 · 收尾**

- 跑完整测试套件(不只 agent 跑过的)
- 人审 diff(尤其关键路径)
- commit(让 agent 写 commit message 也可以)
- 跑 CI

---

## 三、Prompt 写法八条军规

### 3.1 结构化胜过自然语言

```markdown
# 反例(模糊)
帮我加个登录功能,要安全一点

# 正例(结构化)
## 任务
实现 JWT 登录,access_token 15min,refresh_token 7d
## 文件
- src/auth/login.py(新增)
- tests/test_login.py(新增)
## 约束
- 密码用 bcrypt(cost=12)
- 不存明文密码
- refresh_token 存 Redis,键前缀 "rjwt:"
## 验收
- pytest tests/test_login.py 全过
- 错误密码返回 401,不泄露用户是否存在
```

### 3.2 给示例,不要只描述(example-driven)

```python
# 让 agent 模仿这种风格:
def calculate_price(items: list[Item]) -> Price:
    """Calculate total price with tax."""
    ...
```

### 3.3 给"反例"也很有效

```python
# 不要写成这样:
def calc(x, y):  # 缺 type hint
    return x+y*0.7  # 魔法数字 0.7
```

### 3.4 给验收标准,不只给需求

> "做完长什么样"——可执行的标准。例:`curl /api/health` 返回 `{"status":"ok"}`

### 3.5 限制范围,明确"不要动什么"

> "不要动 src/auth.py、不要加新依赖、不要写 print"

### 3.6 复杂任务先要 plan

> "先列 todo + 影响面,我确认后再写代码"

### 3.7 失败时给完整上下文

```
# 反例
报错了,你看看

# 正例
跑 `pytest tests/test_orders.py::test_404` 报:
  AssertionError: expected 404, got 200
复现:启动 `uvicorn src.main:app`,curl /api/orders/non-existent-id
期望:404 + {"error":"order not found"}
实际:200 + 完整订单对象(明显查到了不存在的 ID)
```

### 3.8 一次性原则:任务 ≤ 一次能读完的 diff

经验值:**单次任务改动 ≤ 500 行**,超过就拆。否则 agent 上下文丢、人审也累。

---

## 四、上下文工程(Context Engineering)实战

LLM context 窗口有限(200k token),代码库动辄百万行,**不管理上下文 = 等死**。

### 4.1 五大策略

| 策略 | 工具 | 何时用 |
|---|---|---|
| **代码索引** | codegraph / ctags / LSIF | 大仓库,按符号取相关片段 |
| **RAG** | embedding + 检索 top-k | 文档/知识库类 |
| **Subagent 卸载** | opencode explore / claude subagent | 大块探索扔出去 |
| **Todo 持久化** | todo list / boulder / ralph | 长任务跨多轮 |
| **Compact** | 自动压缩历史 | 上下文过半时 |

### 4.2 优先级:代码索引 > RAG

| 维度 | 代码索引(codegraph) | RAG(embedding) |
|---|---|---|
| 准确性 | AST 精确,符号级 | 模糊,可能漏 |
| 速度 | <1ms | 10-100ms |
| 维护 | 自动建图 | 重建 embedding 慢 |
| 适用 | 自己代码库 | 外部文档/issue |
| 失败模式 | 跨文件分析弱 | 召回不全 |

经验:**自家代码库优先用 codegraph,外部知识用 RAG**。

### 4.3 AGENTS.md / CLAUDE.md 写什么

```markdown
# AGENTS.md(项目说明书)

## 项目结构
- src/api/      # REST API
- src/core/     # 业务逻辑
- src/db/       # 数据库
- tests/        # pytest 测试

## 编码规范
- Python 3.11+,type hint 必填
- 函数 ≤ 50 行,文件 ≤ 250 行
- 不用 print,用 loguru
- 常量提取到 src/constants.py

## 命令
- 测试: `pytest tests/`
- 启动: `uvicorn src.main:app --reload`
- lint: `ruff check . && mypy src/`

## 禁忌
- 不要改 src/legacy/ (遗留代码,即将下线)
- 不要引入新的 ORM
- 不要直接连生产 DB

## PR 流程
- 分支命名: feature/xxx
- commit 信息: conventional commits
- 必须: 测试全过 + 1 人 review
```

> agent 启动时自动读入,相当于"入职文档"。**写得越清楚,agent 越不跑偏**。

### 4.4 Subagent 何时用

| 场景 | 用 subagent | 不用 subagent |
|---|---|---|
| 探索陌生仓库 50+ 文件 | ✅ explore | - |
| 查外部库文档 | ✅ librarian | - |
| 改一个已知文件 | ❌ | 直接 Edit |
| 跑一个测试 | ❌ | 直接 Bash |
| 架构决策咨询 | ✅ oracle | - |

> 经验:**explore 用便宜模型(Haiku),build 用中等模型(Sonnet),oracle 用贵模型(Opus)**。模型分级省成本。

---

## 五、错误恢复策略

### 5.1 三次失败原则

```
第 1 次失败:读错误 → 同样思路重试(可能只是偶然)
第 2 次失败:换思路(改方法,不重复)
第 3 次失败:停下 → 咨询 oracle 或人
```

**反模式**:让 agent 死磕同一个错误 10 次,耗光 token 还污染上下文。

### 5.2 回滚策略

- **频繁 commit**:每完成一个 todo commit 一次
- **WIP commit**:`git commit -am "wip:xxx"` 兜底
- **branch 隔离**:每任务一个分支,失败就 `git checkout main`
- **不依赖 stash**:agent 容易忘 stash 内容

### 5.3 常见错误恢复表

| 错误 | 根因 | 恢复 |
|---|---|---|
| 模型说"我无法..." | 越权/敏感词 | 改 prompt 措辞,避开触发词 |
| 反复改同一行 | 上下文丢 | compact + 重述需求 |
| 引幻觉包 | `import foo`(foo 不存在) | 让 agent 跑 `pip install` 验证 |
| 测试永远 pass | agent 写 `assert True` | 强制 mutation testing |
| 删错文件 | 误判冗余 | `git checkout <file>` |
| 改了不该改的 | 范围失控 | 看完 `git diff --stat` 再继续 |

---

## 六、代码审查策略(agent 写的代码 ≠ 信任)

### 6.1 必审项

| 类别 | 工具 | 关注 |
|---|---|---|
| 安全 | `semgrep`/`bandit`/`gitleaks` | SQL 注入、密钥泄露、SSRF |
| 类型 | `mypy`/`tsc`/`pyright` | `as any`、`Optional[...]` 滥用 |
| 测试质量 | `pytest --cov`/mutation | 覆盖率 ≠ 有效,看 mutation |
| 复杂度 | `radon`/`eslint-complexity` | 圈复杂度 > 10 警惕 |
| Diff | `git diff` | 是否动了不该动的文件 |
| License | `license-checker` | 引入了 GPL? |

### 6.2 关键模块人工逐行审

- 认证/授权(auth)
- 支付(payment)
- 数据库迁移(DDL)
- 加密实现(crypto)
- 与外部系统交互的 API client

> 这些模块**永远人工审**,agent 写的也要逐行。

### 6.3 团队级 CI

```yaml
# .github/workflows/agent-pr.yml 示例
- 跑测试
- 跑 lint
- 跑 security scan
- 跑 license check
- 强制 1 人 review
- 关键路径改动 → 标签 require-architecture-review
```

---

## 七、性能与成本控制

### 7.1 模型分级

| 任务类型 | 推荐模型 | 例子 |
|---|---|---|
| 大量探索/检索 | 便宜模型(Haiku/Flash) | explore subagent |
| 主流程实现 | 中等模型(Sonnet/Pro) | build agent |
| 架构/难 bug | 贵模型(Opus/Gemini Ultra) | oracle |
| 单行补全 | 本地小模型 | Copilot 式补全 |

### 7.2 上下文窗口管理

- 监控 token 用量,过 70% → compact
- 长任务用 boulder/ralph 自动续
- 不必要的 history 不要带(用户对话外的)
- 工具结果太长 → 摘要/截断

### 7.3 缓存策略

- 相同 prompt → cache(TTL 5min-1h)
- 相同 RAG 查询 → cache
- 相同 skill 加载 → 不重复加载

### 7.4 并行化

- 5+ 独立探索任务 → 并行 subagent
- 多文件 lint → 并行
- 跑测试 → pytest-xdist / `go test -p`

---

## 八、常见问题与解决方案(必背避坑表)

### 8.1 上下文/记忆类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **上下文爆炸** | agent 忘早期约定 | 单次任务太大 | 拆任务 + subagent + compact |
| **风格漂移** | 每次生成代码风格不同 | 没固化规范 | AGENTS.md + prettier + biome |
| **早期约定丢失** | 改了又改回 | todo 没 track | todo list + boulder 持续 |
| **跨会话遗忘** | 重启后不知道之前做了啥 | session 无状态 | 用 handoff/续接 ses_id |

### 8.2 代码质量类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **魔法数字** | 代码到处 0.7、42 | 没约定提取常量 | AGENTS.md 规定 + lint |
| **代码冗余** | 重复函数、未清理 | agent 没全局视野 | refactor skill + 周期重构 |
| **过度抽象** | 一堆 one-liner helper | agent 喜欢抽 | 规定"helper 复用 ≥ 3 次才抽" |
| **类型 any 滥用** | `as any` 满天飞 | agent 图省事 | 禁 `as any` / `@ts-ignore` |
| **空 catch** | `except: pass` | agent 偷懒 | lint 禁空 catch |
| **死代码** | 注释掉的不删 | agent 不敢删 | 规定"注释代码直接删" |

### 8.3 安全/合规类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **SQL 注入** | 拼字符串 | agent 偷懒 | 强制 ORM + lint |
| **密钥泄露** | API key 进 git | 没扫描 | `gitleaks` + pre-commit hook |
| **SSRF** | agent 信任用户 URL | 不懂安全 | URL 白名单 + 出网限制 |
| **依赖幻觉** | import 不存在的包 | 模型幻觉 | 装包前验证 |
| **License 污染** | 引入 GPL 到商业项目 | 不查 license | `license-checker` CI |
| **数据出境** | 敏感代码上传第三方 | 没分级 | 本地模型 + 配置 mask |
| **权限越权** | agent 改 ~/.ssh | 权限失控 | disallowedTools + 沙箱 |

### 8.4 流程/团队类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **推送事故** | 误推 main、force push | 权限失控 | branch protection + disallow |
| **审计困难** | 谁改的哪行为什么? | 无操作日志 | 强制操作日志 trace |
| **不可复现** | 同 prompt 不同结果 | LLM 非确定性 | 跑 N 次取众数 + seed |
| **协作摩擦** | 团队不会用 agent | 缺规范 | 共享 .claude/.opencode + 培训 |
| **PR 噴射** | 一次改 50 文件 | agent 没分批 | 规定 PR ≤ 500 行 |

### 8.5 性能/成本类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **token 烧光** | 一天 $100 | 没分级 | 模型分级 + cache |
| **等待太久** | 5 分钟才出结果 | 没并行 | 独立任务并行 subagent |
| **重复查询** | 同 RAG 查 10 次 | 没缓存 | 结果 cache |
| **大文件全读** | 5000 行文件全读 | 没用 codegraph | codegraph 按符号取 |

---

## 九、典型工作流示例(面试讲得出)

### 9.1 给 vllm-ascend 贡献新 attention backend

```bash
# 1. fork + clone
git clone <my-fork> vllm-ascend && cd vllm-ascend
git remote add upstream <origin>

# 2. 写 AGENTS.md(若没有)
#    描述:项目结构、算子注册流程、ACL/tiling 规范、测试命令

# 3. 启动 Claude Code / OpenCode

# 4. 第一轮(探索)
> "读 vllm_ascend/attention/ 下所有 backend,告诉我它们的共同结构、
>  注册流程、和 tiling 的关系。先列 plan,不要写代码。"

# 5. 第二轮(设计)
> "参考 attention_v1.py 的结构,设计一个新的 flash_attn backend,
>  列出要新增哪些文件、改哪些注册点、需要哪些测试。"

# 6. 第三轮(实现)
> "按你的 plan,先实现 _flash_attn_fwd 函数和单元测试。
>  约束:不能动 vllm/core/,必须复用 aclnn 接口。"

# 7. 验证
pytest tests/ops/test_flash_attn.py
python -m vllm_ascend.profiler ...  # 性能 baseline

# 8. 收尾
git commit -m "feat(attention): add flash_attn backend"
gh pr create
```

### 9.2 调试线上 Agent 死循环

```
场景:生产 Agent 卡在"调工具 → 失败 → 重调"循环

步骤:
1. 拿 trace(操作日志)
2. 让 agent 读 trace,定位循环点
3. 咨询 oracle:"为什么 Agent 会在 X 步循环"
4. oracle 给假设:工具返回错误信息模糊,LLM 以为重试能成功
5. 改 prompt:工具失败 → 明确告知"不可重试,转人工"
6. 加最大步数硬限制(代码层)
7. 跑回归测试(模拟原 trace)
8. 部署 + 监控
```

---

## 十、一页速记卡

| 类别 | 必背 |
|---|---|
| 心智模型 | 你是 PM,agent 是初级工程师;Plan→Execute→Verify |
| 启动准备 | Git 干净 + AGENTS.md + 沙箱 + 分支保护 |
| Prompt 四要素 | 上下文 + 需求 + 约束 + 验收 |
| 任务粒度 | ≤ 500 行/次,超了就拆 |
| 上下文策略 | codegraph > RAG(自家代码) |
| Subagent | explore 便宜模型 / build 中等 / oracle 贵 |
| 失败处理 | 3 次原则:同→换→停 |
| 必审项 | 安全 / 类型 / 测试质量 / 复杂度 / Diff / License |
| 关键模块人工审 | auth / payment / DDL / crypto / 外部 API client |
| 模型分级 | Haiku 探索 / Sonnet 实现 / Opus 决策 |
| 避坑共性 | 安全审查 + 权限模型 + 操作日志 + 规范固化 |
| 反模式 | 甩整个项目 / 死磕同一错误 / 信任 agent 写的代码 |

---

## 十一、面试加分话术

### 11.1 "你做过 Vibe Coding 吗?"
> "做过,我用 Claude Code 给 vllm-ascend 贡献过 attention backend。
> 我的流程是:先写 AGENTS.md 固化规范,然后小步迭代——每个子任务
> 不超过 500 行,prompt 给上下文+需求+约束+验收四要素。Agent 写
> 完我必跑 lsp_diagnostics+pytest+security scan,关键模块人工逐行
> 审。遇到过最大坑是上下文爆炸和魔法数字,后来用 codegraph 替代
> RAG,在 AGENTS.md 规定常量提取,基本就解决了。"

### 11.2 "Vibe Coding 怎么保证代码质量?"
> "三层防线:① 工具层——CI 跑 lint+test+security scan;② 流程层
> ——关键模块(auth/payment/crypto)强制人工逐行审;③ 规范层——
> AGENTS.md 固化风格、AGENTS.md 规定禁忌文件。三者缺一不可,
> 没有审查的 vibe coding 在生产环境就是定时炸弹。"

### 11.3 "agent 失败循环怎么办?"
> "三次原则:第一次同思路重试,第二次换方法,第三次停下咨询 oracle
> 或人。配合 git 频繁 commit,失败就 `git checkout` 回滚到上个稳定
> 点,不让坏代码污染上下文。如果连续多次失败,说明任务太大或上下文
> 不足,我会拆任务或加载更多上下文。"

### 11.4 "Vibe Coding 在生产环境的限制?"
> "三类场景不适合:① 高安全/合规(金融医疗)——LLM 难保证审计
> 合规;② 极致性能优化(算子 tiling)——需深度领域知识;③ 一次性
> 小改动——启动 agent 比直接改慢。适合:重复性高、模板化、新框架
> 探索、调试卡住时多角度探索、大重构批量改。"
