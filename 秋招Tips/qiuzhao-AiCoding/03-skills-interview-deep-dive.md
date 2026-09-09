# 03 · Skills 面试详解(10 道题答法 + 真实 skill 拆解)

> 适用范围:秋招 AI Infra / Agent / LLM 应用方向,**二面/三面拔高**。
> Skills 是 2025 年下半年 AI Coding 领域的**第三波主流**(Vibe → Spec → Skills),面试官常用来考察深度。
> 本文每题给"答法结构"而非"标准答案"——可背诵、可扩展、可应付追问。

---

## 一、Skills 概念深入(必背)

### 1.1 定义

**Skill** = 可复用、可分发、可组合的**领域专用指令包**。
- 形态:一段 markdown(SKILL.md)+ 引用文档(references/)+ 检查清单(checklist)
- 加载:用户显式 `/skill-name` 或 agent 自动 trigger
- 作用:把"在 X 场景按 Y 流程用 Z 约束"固化为可加载的专项手册

### 1.2 一句话类比

> **system prompt = 职业操守;skill = 专项操作手册。**

| 概念 | 类比 | 时效 |
|---|---|---|
| system prompt | 公司员工手册 | 永远生效 |
| skill | "处理客户投诉 SOP" | 按需加载 |
| tool | "电话、邮件系统" | 被动调 |
| MCP server | "外部供应商" | 独立运行 |
| subagent | "外包专员" | 任务级 |

### 1.3 一个 Skill 的标准结构

```
my-skill/
├── SKILL.md            # 主入口,描述触发 + 工作流
├── references/         # 引用文档(按需读)
│   ├── checklist.md
│   ├── examples.md
│   └── troubleshooting.md
└── tests/              # 触发词测试(可选)
    └── triggers.yaml
```

**SKILL.md 内容**(七要素):
1. **metadata**:name / version / description / scope
2. **触发条件**:什么场景自动加载(关键词 / 任务类型)
3. **工作流**:Plan → ... → Verify 的步骤
4. **引用文档**:references/ 下文件路径
5. **检查清单**:执行完必须满足的验收条件
6. **退出条件**:何时认为完成
7. **评估指标**:怎么判断 skill 是否有效(可选)

### 1.4 与相邻概念边界(面试必考)

| 维度 | Skill | System Prompt | Tool | MCP Server | Plugin | Subagent |
|---|---|---|---|---|---|---|
| 形态 | Markdown 指令 | 字符串 | 函数/JSON Schema | 协议+服务 | 二进制/包 | 独立 agent session |
| 加载 | 按需 | 启动 | 按需调用 | 启动连接 | 安装时 | spawn 时 |
| 范围 | 领域专用 | 全局 | 单操作 | 跨进程 | 跨进程 | 独立 context |
| 组合 | 可叠加 | 唯一 | 可并行 | 可多 server | 可多 plugin | 可多 subagent |
| 修改 | 改 markdown | 改配置 | 改代码 | 改 server | 重新打包 | 改 subagent |
| 复用 | 跨项目 | 项目内 | 项目内 | 跨项目 | 跨项目 | 项目内 |

### 1.5 Skill 的加载机制

```
┌──────────────────────────────────────────┐
│ 1. 用户: /debugging                      │
│    OR                                     │
│    Agent 内置 trigger 检测到关键词          │
│       (如 "why is X broken", "crash")    │
│ ↓                                        │
│ 2. 找到 skill 文件(SKILL.md)             │
│ ↓                                        │
│ 3. 把 SKILL.md 内容塞进 system prompt     │
│    (或作为临时消息注入)                   │
│ ↓                                        │
│ 4. 按需 Read references/ 下文档           │
│    (不是一次全读,按工作流步骤读)         │
│ ↓                                        │
│ 5. Agent 按 SKILL.md 描述的流程执行       │
│ ↓                                        │
│ 6. 执行完跑 checklist 验收                │
└──────────────────────────────────────────┘
```

> **关键**:**不是 skill 替代 agent,而是 skill 给 agent "专项操作手册"**。Agent 的工具(Read/Edit/Bash)还是那套,只是流程被规范了。

---

## 二、Skills 设计原则(SOLID 类比,面试加分)

借用软件工程的 SOLID,给 Skill 设计同样原则:

### 2.1 S - Single Responsibility(单一职责)

- 一个 skill 只解决**一类问题**
- 反例:`/code-do-everything`(写代码+测试+部署+监控)
- 正例:`/debugging`(只负责调试)、`/frontend`(只管前端)

> 判据:**能用一句话说清这个 skill 干啥**。

### 2.2 O - Open-Closed(开闭原则)

- 可通过**叠加新 skill** 扩展,不修改老 skill
- 反例:每次新框架都改 `/frontend` 的内容
- 正例:`/frontend` + `/vue-3-best-practice` 叠加

### 2.3 L - Liskov Substitution(替换)

- 同领域的 skill 应可互相替换
- 例:`/security-review` 和 `/security-research` 都能做安全审计,只是深度不同
- 用户可以选浅的或深的,不冲突

### 2.4 I - Interface Segregation(接口隔离)

- 大而全的 skill 拆成多个小的
- 反例:`/backend` 一锅端
- 正例:`/api-design` + `/db-migration` + `/caching`

### 2.5 D - Dependency Inversion(依赖倒置)

- skill 不直接依赖具体工具,依赖抽象接口
- 反例:`/test` 写死 `pytest`
- 正例:`/test` 描述"运行测试套件"的抽象,具体由项目配置选 pytest/go test/jest

### 2.6 触发词设计原则(关键)

| 原则 | 反例 | 正例 |
|---|---|---|
| 具体 | "frontend" | "react component" / "redesign layout" |
| 不与日常语重叠 | "code" | "scaffold crud" |
| 多语言 | 只英文 | 中英文双语 trigger |
| 不与其他 skill 重叠 | 两个 skill 都匹配 "test" | 一个 trigger "go test",另一个 trigger "integration test" |

> 误触发是 skill 系统的最大坑,触发词设计是第一道防线。

---

## 三、10 道面试题(标准答法)

### 题 1:你设计/用过什么 Skill?⭐⭐⭐⭐⭐

**答法结构**(四段):
1. 名称 + 解决什么问题
2. 触发场景 + 工作流概览
3. 引用了哪些 references
4. 评估指标 + 实测效果

**示例答法**:
> "我设计过一个 `/debugging` skill,解决'agent 反复改代码但不解决根因'的问题。
> 触发词包括 'debug this'、'why is X broken'、'crash' 等。
> 工作流是 hypothesis-driven loop:① 让 agent 列 ≥3 个假设;② 并行调查;
> ③ 2 轮失败后 spawn oracle 从新角度切入;④ 锁定根因;⑤ 写失败测试;
> ⑥ 最小修复;⑦ 用真实系统验证(不是只跑单测)。
> references/ 下有 hypothesis-template.md、常见反模式.md、调试工具速查.md。
> 评估指标:bug 解决率从 45% → 72%(对比没 skill 时),平均尝试次数从 8 → 4。"

**加分追问预答**:
- Q: 怎么知道 skill 是关键?A: A/B 测试,同样 bug 集两组跑,看 skill 组的解决率和效率提升。

### 题 2:Skill 和 System Prompt 的边界?⭐⭐⭐⭐⭐

**答法**:
> "system prompt 是全局稳定的——所有任务都生效,改一次影响所有对话。
> skill 是按需加载的——只在匹配场景时注入上下文,不影响其他场景。
> 经验判断:① 稳定的、所有任务都要的规则进 system prompt;② 领域专用、
> 频率不高的进 skill;③ 超过 100 行的领域规则必抽成 skill,不然 system
> prompt 臃肿,token 浪费。例:不重复使用 print、不引入新依赖这类**通用
> 规范**进 system prompt;安全审计流程、调试 SOP 这类**专项流程**进 skill。"

### 题 3:多 Skill 冲突怎么办?⭐⭐⭐⭐

**答法**(四层防线):
> "① 触发词去重——设计时确保两个 skill 的 trigger 不重叠,这是预防;
> ② 优先级机制——用户级 > 项目级 > 全局,同优先级看加载顺序;
> ③ 显式优于隐式——`/skill-name` 显式调用高于自动 trigger;
> ④ 加载时去重——相同指令不重复注入。
> 如果两个 skill 真冲突,说明设计有问题,该合并或拆分。例如 `/security-review`
> 和 `/security-research` 都做安全,前者是 quick scan、后者是 deep audit,
> 用 description 明确深度差异,触发词分开。"

### 题 4:怎么评估 Skill 质量?⭐⭐⭐⭐⭐

**答法**(五个指标):
> "① 触发率(recall)——该用的时候是否触发了;
> ② 误触发率(false positive)——不该用的时候是否加载了;
> ③ 任务完成率提升——用 skill 后成功率提升多少(对照基线);
> ④ 用户修正次数——是否减少了人工干预;
> ⑤ 可维护性——修改 skill 后回归测试的成本。
> 评估方法:A/B 测试(一组带 skill 一组不带),跑 N 个任务统计指标。
> 长期看,每个 skill 应该有 testset + baseline,改 skill 跑回归。"

### 题 5:Skill 怎么调试?⭐⭐⭐

**答法**:
> "① 加 trace log——记录 skill 加载、references 读取、每步执行;
> ② 单元测试 trigger 匹配——给定输入,断言是否触发期望 skill;
> ③ A/B 测试不同版本——同任务跑两个 skill 版本对比;
> ④ 用户反馈循环——让用户标'这次 skill 是否帮到忙';
> ⑤ references 验证——确保 references/ 下文档路径有效,链接没断。
> 常见 bug:触发词太宽导致误触发、references 太长导致 context 爆炸、
> checklist 太松导致验收走过场。"

### 题 6:Skill 的版本管理怎么做?⭐⭐⭐

**答法**:
> "① git 仓库版本——skill 文件进 git,改动有 commit 历史;
> ② 语义化版本——breaking 改动(改触发词或工作流)major,新增 references
> 是 minor,文档修正 patch;
> ③ changelog——记录每个版本改了什么、为什么;
> ④ 灰度发布——新版本先给少数用户用,收集反馈;
> ⑤ 跨项目复用——用 git submodule 或专门 registry。
> 实战:我们 skill 仓库独立于代码仓库,改 skill 不发版代码,反之亦然。"

### 题 7:Skill 怎么跨工具复用?⭐⭐⭐⭐

**答法**:
> "核心是**抽象掉工具特定语法**。① 用通用 markdown——避免 Claude 特定
> 的 XML tag、OpenCode 特定的 frontmatter;② 抽象 skill 接口——
> '触发词 + 工作流 + references + checklist'四要素是通用结构;③ 工具
> 适配层——每工具写一个 adapter 把通用 skill 翻译成自己的格式;
> ④ 已有标准——Anthropic Agent Skills、OpenCode Skills 等都在向统一格式收敛。
> 实战:我设计的 skill 用纯 markdown,不依赖任何工具特定语法,能在 Claude
> Code、OpenCode、Cursor 三个工具间复用,只需要各自的 frontmatter 适配。"

### 题 8:Skill 与 RAG 区别?⭐⭐⭐

**答法**:
> "Skill 是**人工编写的、明确的流程性指令**;RAG 是**检索的、模糊的事实性内容**。
> 适用边界:① 流程性知识用 skill——'调试 SOP'、'安全审计流程';
> ② 事实性知识用 RAG——'API 文档'、'历史 bug 案例';③ 两者结合:
> skill 工作流的某一步可以查 RAG。
> 例:`/debugging` skill 在'列假设'这一步,可以 RAG 检索历史相似 bug
> 的解决方案作为参考。skill 给方向,RAG 给素材。"

### 题 9:设计一个 Skill 需要哪些部分?⭐⭐⭐⭐

**答法**(七要素 + 例子):
> "① metadata——name、version、description、scope;
> ② 触发条件——关键词 + 任务类型;
> ③ 工作流——明确步骤,如 Plan → Execute → Verify;
> ④ 引用文档——references/ 下的详细文档,按需读;
> ⑤ 检查清单——验收条件,完成前必跑;
> ⑥ 退出条件——何时认为完成;
> ⑦ 评估指标——触发率、完成率、修正次数。
> 例子:设计 `/go-test` skill,metadata(name=go-test,version=1.0),
> 触发('生成 ut'、'go 测试'、'补充测试'),工作流(扫描 .go → 智能过滤 →
> 并发生成 → go fmt → golangci-lint → 验证覆盖率 → codecheck 21 项),
> references(go-test-quickstart.md、edge-cases.md),checklist(覆盖率 ≥ 70%、
> lint 0 error、codecheck 全过),退出(所有新增测试文件 lint+test 通过),
> 指标(生成成功率、平均覆盖率、人工修正行数)。"

### 题 10:Skill 触发词设计原则?⭐⭐⭐⭐

**答法**(六原则):
> "① 具体——'react component'而非'frontend',减少误触发;
> ② 不与日常用语重叠——'code'太通用,'scaffold crud'更准;
> ③ 多语言支持——中英文双语 trigger,覆盖国际化场景;
> ④ 避免与其他 skill 重叠——设计时画 trigger 矩阵,确保不冲突;
> ⑤ 留 alias——主词 + 同义词,如 'security review'/'安全审计'/'취약점 감사';
> ⑥ 有 fallback——所有 trigger 都不匹配时,允许用户 `/skill-name` 显式调用。
> 实测:我们一个 skill 的 trigger 从 3 个扩到 12 个(含中英韩),触发率从
> 60% 提升到 92%,但误触发率只涨了 2pp,因为 alias 都是同义不重叠。"

---

## 四、真实 Skill 例子拆解(面试可背)

### 4.1 `/debugging`(调试 skill)

```
触发词: debug this / why is X broken / hanging / crash / silent failure / 调试
工作流: hypothesis-driven loop
  ① 列 ≥3 个假设(避免单一思路)
  ② 并行调查(每个假设独立 subagent)
  ③ 2 轮失败 → spawn oracle 从新角度切入
  ④ 锁定根因(写失败测试证明)
  ⑤ 最小修复(只改必要的)
  ⑥ 用真实系统验证(不只跑单测)
references/:
  - hypothesis-template.md(假设书写模板)
  - common-anti-patterns.md(常见反模式:shotgun debug)
  - debugger-cheatsheet.md(pwndbg/gdb/lldb/dlv/pdb 速查)
检查清单:
  - 有失败测试证明根因吗?
  - 修复最小吗(没扩大范围)?
  - 用真实系统跑过吗(不只单测)?
退出条件: 失败测试变绿 + 真实系统行为正常
```

**面试金句**:
> "调试 skill 的核心是 hypothesis-driven——强制 agent 先列假设再动手,
> 避免了 shotgun debug(乱改一通)。2 轮失败 spawn oracle 是为了打破
> agent 思路定势,oracle 是另一个模型实例,从新角度看问题。"

### 4.2 `/frontend`(前端 skill)

```
触发词: frontend / UI / UX / design / redesign / styling / React / Lighthouse / WCAG
工作流: design taste router(多 persona 路由)
  ① 识别任务类型(建组件/重设计/性能审计/视觉 QA)
  ② 路由到对应 ruleset:
     - design taste router + brand references
     - Playwright/Lighthouse/Core Web Vitals
     - ui-ux-db palettes/fonts/guidelines
     - designpowers personas/accessibility
  ③ 加载 references/ 下对应文档
  ④ 执行 + 跑 Core Web Vitals
  ⑤ visual-qa 收尾
references/:
  - design-taste.md(品味原则)
  - brand-references/(各大品牌设计参考)
  - accessibility.md(WCAG 2.2)
  - core-web-vitals.md(LCP/INP/CLS)
```

**面试金句**:
> "前端 skill 的设计哲学是**路由而非命令**——根据任务类型路由到不同
> ruleset,每个 ruleset 有独立参考。比 'frontend' 大而全更准,因为
> 重设计和性能审计的关注点完全不同。"

### 4.3 `/security-review`(安全审计 skill)

```
触发词: security review / vulnerability audit / exploitability audit / 보안 리뷰
工作流: Team Mode(3 hunters + 2 PoC engineers)
  ① 3 个 vulnerability hunter 并行扫描(各负责 OWASP 一类)
  ② 汇总候选漏洞
  ③ 2 个 PoC engineer 验证 exploitability
  ④ 按实际 exploitability 校准 severity
  ⑤ 输出报告(不是理论漏洞,是可利用漏洞)
references/:
  - owasp-top-10.md
  - cwe-database.md
  - exploit-templates/
```

**面试金句**:
> "安全 skill 的关键是**分类 root cause + 校准 severity by exploitability**——
> 不是理论漏洞清单,而是真的能利用的漏洞。3 hunters 并行避免漏检,2 PoC
> engineers 验证避免误报。比单个 agent 全扫准确率高 40%。"

### 4.4 `/review-work`(代码审查 skill)

```
触发词: review work / review my work / QA my work / verify implementation
工作流: 5 个并行 subagent
  ① Oracle: 目标/约束验证(是否满足原需求)
  ② Oracle: 代码质量(可读性/复杂度/重复)
  ③ Oracle: 安全(扫描 + 审计)
  ④ unspecified-high: QA 执行(实际跑系统)
  ⑤ unspecified-high: context mining(从 GitHub/Slack/Notion 挖上下文)
  ⑥ 汇总 → 5 项全过才放行
```

**面试金句**:
> "审查 skill 用 5 个并行 subagent 而不是一个全能 agent——因为视角
> 隔离更彻底,QA 和 code review 是两种思维。全过才放行,任何一项
> 不达标都打回,这是质量门。"

### 4.5 `/go-test`(Go 单测 skill)

```
触发词: 生成 ut / 单元测试 / 创建测试 / go 测试 / 给 xxx.go 写测试
工作流: 自动化批量生成
  ① 扫描 .go 文件
  ② 智能过滤(跳过 main/初始化/无逻辑文件)
  ③ 并发生成测试代码(每文件独立)
  ④ go fmt(仅新增/修改文件)
  ⑤ golangci-lint 检查
  ⑥ 验证覆盖率(目标 ≥ 70%)
  ⑦ codecheck 21 项清单(空函数体/重复/超大函数/类型断言/nil 指针方法/go fmt 等)
退出条件: 所有新增测试文件 lint+test 通过 + 覆盖率达标
```

**面试金句**:
> "go-test skill 的关键是**codecheck 21 项清单**——agent 生成的测试
> 常见坑是空函数体(只占位不验证)、重复代码(几个 test 用例 90% 重复)、
> 超大函数(几百行 test 一锅端)。21 项清单是反 AI slop,锁定这些坑。"

---

## 五、Skills 高级话题(三面拔高)

### 5.1 Skill 组合(Composition)

- **链式**:A 完成后调 B(如 `/debugging` → `/review-work`)
- **并行**:A 和 B 同时跑(如 `/security-review` + `/visual-qa`)
- **嵌套**:A 内部调 B 作为子步骤(如 `/frontend` 内调 `/visual-qa`)

> 关键:**组合不是简单拼接,要管理 context 隔离和步骤交接**。

### 5.2 Skill 资源限制

每个 skill 应该有资源预算:
- **max_tokens**:加载 skill + references 不能爆 context
- **max_steps**:执行步数硬限制
- **max_subagents**:并发 subagent 数限制
- **max_runtime**:总执行时间限制

> 反例:一个 skill 加载 100 个 reference 文件,直接爆 context。
> 正例:references/ 只在需要时按需读。

### 5.3 Skill 沙箱

- 限制 skill 调用的工具集(`/security-review` 不允许 `git push`)
- 限制文件读写范围(只能读 src/ 不能读 ~/.ssh)
- 限制网络出站(不能上传第三方)
- 实现:工具白名单 + 路径白名单 + 出网白名单

### 5.4 Skill 评估的"假阳性陷阱"

> Skill 看起来让任务完成率提升,实际只是因为加了几个流程让 agent 多思考了一会儿——**任何流程都可能短期提升**。要排除这个干扰,对照组应该是"相同流程但没固化成 skill 的 inline prompt"。如果 inline 也能达到一样效果,说明 skill 没必要——可以用 prompt 模板替代。

### 5.5 Skill 与 Agent 的进化方向

| 阶段 | 主导 | 形态 |
|---|---|---|
| 2024 | prompt | 一长串 inline prompt |
| 2025 上 | skill | 固化成 markdown skill |
| 2025 下 | spec + skill | spec 给确定性,skill 给流程 |
| 2026(预测) | agent 自进化 | agent 自己写/改 skill |

> 面试金句:"Skill 是把高频 prompt 模板沉淀成可复用资产的第一步,
> 未来 agent 可能自己写 skill 给自己用——这叫'self-improving agent'。"

---

## 六、Skills 面试常见追问预答

### Q: Skill 太多会怎样?
> "三个问题:① context 爆炸——加载多个 skill 时 references 累加超 token;
> ② 触发词冲突——多个 skill 抢同一场景;③ 用户认知负担——记不住哪个
> skill 干啥。解法:① 按需加载,不一次性全读 references;② 严格 trigger
> 设计 + 优先级;③ 提供 skill catalog UI,让用户浏览而非记忆。"

### Q: 你怎么看 Skills 的未来?
> "三个趋势:① 标准化——各工具的 skill 格式在收敛(纯 markdown);
> ② 自进化——agent 会自动写/改 skill(已见雏形,如 skill-creator);
> ③ marketplace——会出现 skill 商店,类似 npm/pypi,跨工具复用。
> 现在还在'手写 skill'阶段,未来会走向'agent 生成 skill'。"

### Q: Skill 和微服务有什么相似?
> "有意思的类比:① 单一职责——一个 skill 一个微服务;② 独立部署——
> skill 独立 git 仓库;③ 接口契约——skill 的 trigger+description 类似
> API spec;④ 组合——skill 链式调用类似微服务调用链;⑤ 治理——
> skill registry 类似服务注册中心。但 skill 是 prompt 层的,微服务是
> 代码层的——这是'prompt 工程的服务化'。"

### Q: 写过 Skill 的 PRD 吗?
> "写过。一个 skill 的 PRD 包含:① 目标问题(为什么需要这个 skill);
> ② 触发场景(用户在什么场景调用);③ 工作流大纲(分步描述);
> ④ references 清单(需要哪些文档);⑤ checklist(验收条件);
> ⑥ 评估指标(怎么判断 skill 有效);⑦ 失败兜底(skill 不工作时降级方案)。
> 写完 PRD 才写 SKILL.md,避免边写边跑偏。"

### Q: Skill 之间怎么共享上下文?
> "两种模式:① 显式传递——A 把结果作为 prompt 参数传给 B;② 共享
> 状态——A 写文件,B 读文件(慢但稳)。生产环境倾向后者——状态持久化,
> 失败可重试。subagent 模式天然不支持共享 context(各自独立),所以
> skill 组合通常用文件或数据库作为状态中介。"

---

## 七、一页速记卡

| 类别 | 必背 |
|---|---|
| 定义 | 领域专用可复用指令包(markdown + references + checklist) |
| 类比 | system prompt=员工手册;skill=专项 SOP |
| 七要素 | metadata/触发/工作流/引用/检查清单/退出/指标 |
| 加载机制 | 用户显式 or 自动 trigger → 注入 system → 按需读 references |
| SOLID | 单一职责/开闭/可替换/接口隔离/依赖倒置 |
| 触发词 | 具体、不重叠、多语言、留 alias |
| 五指标 | 触发率/误触发率/完成率/修正次数/可维护性 |
| 评估方法 | A/B 测试 + baseline + 回归 |
| 调试 | trace log + trigger 单测 + A/B + 用户反馈 |
| 版本 | git + SemVer + changelog + 灰度 |
| 跨工具 | 纯 markdown + 通用接口 + adapter 层 |
| 与 RAG | skill=流程性, RAG=事实性, 可结合 |
| 高级 | 组合/资源限制/沙箱/假阳性陷阱 |
| 真实 skill | debugging / frontend / security-review / review-work / go-test |
| 反模式 | 一锅端 skill / trigger 太宽 / references 全读 |
| 金句 | "skill 不替代 agent,是给 agent 专项操作手册" |

---

## 八、面试实战模板(可直接背)

### 8.1 "你做过 Skill 吗?" 三句话模板

> "我设计过 [skill 名],解决 [问题]。工作流是 [步骤概要],references 在
> [文件目录]。实测 [指标] 从 [基线] 提升到 [结果],关键设计是 [亮点]。"

### 8.2 "Skill vs System Prompt" 三句话模板

> "system prompt 是 [全局稳定],skill 是 [按需加载]。判断标准是
> [稳定且通用→system;领域且频次低→skill]。实战中 [举例] 这种规则进
> system,[举例] 这种流程进 skill。"

### 8.3 "怎么评估 Skill" 三句话模板

> "五个指标:[触发率/误触发率/完成率/修正次数/可维护性]。评估方法
> 是 A/B 测试,[带 skill 组 vs 不带],跑 N 个任务统计指标。长期每个
> skill 都有 [testset + baseline],改 skill 跑回归。"

### 8.4 "Skill 跨工具复用" 三句话模板

> "核心是 [抽象掉工具特定语法]。用 [纯 markdown + 通用四要素] 写 skill,
> 每工具写 [adapter 层] 翻译。已有标准 [Anthropic Agent Skills / OpenCode
> Skills] 在向统一收敛。实战我的 skill 能跨 [Claude Code/OpenCode/Cursor]
> 三工具复用,只需要 frontmatter 适配。"
