# 02 · Spec Coding 实战技巧与避坑指南

> 适用范围:秋招 AI Infra / Agent 方向,讲得出"Vibe 之外的另一种思路"。
> Spec Coding 是 2025 年下半年继 Vibe Coding 后的**第二波主流**,面试官常拿来对比考察工程判断力。

---

## 一、Spec Coding 是什么

### 1.1 定义

**Spec Coding** = 规范先行(Spec First)的 AI Coding 方式:
- 先写**契约规范**(OpenAPI / protobuf / JSON Schema / 自定义 DSL)
- 用 spec 生成**代码骨架、客户端 SDK、文档、Mock、测试**
- AI 在 spec 框架内填充实现,而不是从零生成

一句话:**"先约定接口,再让 agent 写实现"**,与 Vibe Coding 的"边感觉边写"形成对照。

### 1.2 2025 年标志性产品

| 工具 | 厂商 | 出品时间 | 定位 |
|---|---|---|---|
| **Kiro** | AWS | 2025-07 | Spec-driven IDE,从 spec → impl 全流程 |
| **GitHub Spec Kit** | GitHub | 2025-05 | 开源 spec 工具链,可与任何 IDE 集成 |
| **OpenAPI Generator** | OpenAPI 社区 | 多年 | 从 OpenAPI 生成 server/client/SDK |
| **buf** | Buf | 多年 | protobuf spec → 多语言代码 |
| **Quicktype** | quicktype | 多年 | JSON Schema → 多语言 model |
| **Spectral / Stoplight** | Stoplight | 多年 | spec lint + review |

### 1.3 为什么 2025 年 Spec Coding 翻红

- **Vibe Coding 的痛点暴露**:上下文爆炸、风格漂移、不可复现
- **LLM + spec 双重保险**:spec 给确定性骨架,LLM 填创造性实现
- **企业需求**:金融/医疗/合规场景必须可审计,纯 vibe 不行
- **工具链成熟**:Kiro/Spec Kit 把流程整合成一键化

---

## 二、Vibe vs Spec 全面对比

| 维度 | Vibe Coding | Spec Coding |
|---|---|---|
| **起点** | 自然语言 prompt | spec 文件(OpenAPI/protobuf) |
| **粒度** | 整功能/PR | 单接口/单 schema |
| **确定性** | 低(LLM 主导) | 高(spec 锁死契约) |
| **可审计** | 弱(对话历史) | 强(spec 即文档) |
| **协作** | 个人/小团队 | 跨团队/多服务 |
| **上下文成本** | 高(全靠 LLM) | 低(骨架已生成) |
| **灵活性** | 高 | 低 |
| **上手成本** | 低(会说人话就行) | 中(要会 spec 工具链) |
| **复用性** | 低(prompt 难复用) | 高(spec 可生成多端) |
| **失败模式** | 上下文爆炸、风格漂移 | spec 与实现脱节、过度设计 |
| **典型场景** | 原型、个人项目、重构 | 跨服务 API、合规场景、SDK 开发 |

> **结论**:不是二选一,而是分层——**外层用 Spec(API 边界),内层用 Vibe(业务实现)**。

---

## 三、Spec Coding 完整工作流

### 3.1 总流程图

```
┌──────────────────────────────────────────────┐
│  Step 1: 写 Spec                              │
│  ┌──────────────────────────────────┐         │
│  │ OpenAPI / protobuf / JSON Schema │         │
│  └──────────────────────────────────┘         │
│  ↓                                            │
│  Step 2: Spec Review (Spectral / Stoplight)   │
│  ↓                                            │
│  Step 3: 生成 Skeleton (codegen)             │
│  - server interface                          │
│  - client SDK                                │
│  - data models (Pydantic / dataclass)        │
│  - mock server (Prism / Wiremock)            │
│  - API doc (Swagger UI / Redoc)              │
│  ↓                                            │
│  Step 4: AI 填充实现(Vibe Coding 内层)        │
│  ↓                                            │
│  Step 5: Contract Testing (Pact/Schemathesis)│
│  ↓                                            │
│  Step 6: CI + 部署                            │
└──────────────────────────────────────────────┘
```

### 3.2 Step 1 · 写 Spec

**例子:OpenAPI 3.1**

```yaml
# openapi.yaml
openapi: 3.1.0
info:
  title: Order API
  version: 1.0.0
paths:
  /orders/{order_id}:
    get:
      operationId: getOrder
      parameters:
        - name: order_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Order'
        '404':
          description: Not Found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
components:
  schemas:
    Order:
      type: object
      required: [id, status, total]
      properties:
        id: { type: string }
        status: { type: string, enum: [pending, paid, shipped] }
        total: { type: number, format: double }
    Error:
      type: object
      required: [error]
      properties:
        error: { type: string }
```

**写 Spec 的几条原则**:
1. **先粗后细**:第一版只列 path + method,版本迭代再细化
2. **重用 $ref**:抽 schemas/components,不要复制粘贴
3. **必填字段标注 `required`**:LLM 写实现时按这个生成校验
4. **错误码标准化**:错误用统一 schema(`Error`),不要每个接口自定义
5. **加 examples**:LLM 看 example 比看 schema 更准

### 3.3 Step 2 · Spec Review

工具:
- **Spectral**(JS,开源,最常用):`spectral lint openapi.yaml`
- **Stoplight Studio**(GUI,可视化编辑 + lint)
- **Speccy**(老牌,现在基本被 Spectral 替代)

检查项:
- 是否符合 OpenAPI 3.1 规范
- 命名是否一致(camelCase / snake_case)
- 是否有 `operationId`(codegen 必需)
- 是否所有 response 都有 schema
- 是否有 `examples`
- 是否避免 breaking change(新增字段是否 required)

**最佳实践**:把 Spectral 集成到 pre-commit hook,改 spec 必过 lint。

### 3.4 Step 3 · 生成 Skeleton

```bash
# OpenAPI → Python FastAPI server
openapi-generator-cli generate \
  -i openapi.yaml \
  -g python-fastapi \
  -o ./generated-server

# OpenAPI → TypeScript client
openapi-generator-cli generate \
  -i openapi.yaml \
  -g typescript-axios \
  -o ./generated-client

# OpenAPI → Pydantic models(只生成 model)
datamodel-code-generator \
  --input openapi.yaml \
  --output src/models.py \
  --output-model-type pydantic_v2.BaseModel

# Mock server(前后端并行开发)
prism mock openapi.yaml --port 4010
```

生成的内容:
- server interface(空函数,带 type hint,等实现)
- client SDK(类型安全的调用代码)
- data models(Pydantic / dataclass / TypeScript interface)
- mock server(模拟响应,供前端联调)
- API doc(Swagger UI 自动渲染)

> **关键点**:此时**一行业务代码没写**,但客户端已经能联调、文档已就绪。AI 实现时只需要填空。

### 3.5 Step 4 · AI 填充实现(关键)

```markdown
# 给 agent 的 prompt

## 任务
实现 GET /orders/{order_id} 端点

## 上下文
- Spec: openapi.yaml(已生成 skeleton 在 src/api/orders.py)
- 已生成 Pydantic models 在 src/models.py(参考 Order, Error)
- 数据库 ORM: SQLAlchemy 2.0
- 测试: tests/test_orders.py(已用 client SDK 写好)

## 约束
- 只填 src/api/orders.py::get_order 函数体
- 不动 spec、不动 models、不动 client
- 必须用生成的 Pydantic model 作为返回类型
- 不引入新依赖

## 验收
- pytest tests/test_orders.py 全过
- 200 返回 Order,404 返回 Error
```

> 注意:agent 只在**指定函数体内**填代码,不能改 spec 和骨架。这就是 spec 的"硬约束"作用。

### 3.6 Step 5 · Contract Testing

- **Pact**(最主流):双向 contract test,消费者和提供者各自验证
- **Schemathesis**(Python,OpenAPI 专用):自动生成测试输入,基于 spec 做 fuzzing
- **Dredd**(老牌):OpenAPI → 实际请求验证

```bash
# Schemathesis: 从 OpenAPI 自动 fuzz 测试
schemathesis run openapi.yaml --base-url http://localhost:8000

# Pact: 消费者写期望,提供者验证
pact-broker verify
```

> Contract test **必须进 CI**,任何 spec 与实现不一致都阻断合并。

### 3.7 Step 6 · 版本管理

| 变更类型 | 是否 breaking | SemVer |
|---|---|---|
| 加 optional 字段 | 否 | minor |
| 加新 path / method | 否 | minor |
| 删字段 | 是 | major |
| 改字段类型 | 是 | major |
| optional → required | 是 | major |
| required → optional | 否 | minor |
| 加 enum 值 | 否(消费端宽松)/ 是(严格) | 看团队约定 |

策略:
- **兼容窗口**:N 个 minor 版本(如 3 个)同时支持
- **Deprecation 期**:删字段前先标 deprecated,留 6 个月
- **Sunset header**:HTTP Sunset header 告知客户端下线时间

---

## 四、Spec 驱动的工具生态全景

### 4.1 按场景分类

| 场景 | Spec 格式 | 工具 |
|---|---|---|
| REST API | OpenAPI 3.1 | openapi-generator / Spectral / Prism |
| gRPC | Protocol Buffers | buf / grpcurl / protoc |
| GraphQL | GraphQL SDL | graphql-codegen / Apollo |
| 数据契约 | JSON Schema | quicktype / datamodel-code-generator |
| 事件驱动 | AsyncAPI | asyncapi-generator |
| Agent 协议 | A2A (Google 2025) | google-a2a / agentcard |
| LLM-工具协议 | MCP(Anthropic) | mcp-server / mcp-client |
| 数据库 schema | Prisma schema / SQL DDL | prisma / atlas |
| 配置 | CUE / Jsonnet / Kustomize | cue / jsonnet / kustomize |

### 4.2 AI Agent 场景的 Spec

这是 2025 年新增的热点:
- **MCP**(Model Context Protocol):Anthropic 提出,LLM 与外部工具/数据源通信的 spec
- **A2A**(Agent2Agent):Google 提出,agent 之间互调的 spec
- **AgentCard**:A2A 中描述 agent 能力的 JSON spec
- **OpenAI function calling schema**:OpenAI 原生工具调用 spec

```json
// AgentCard 示例(A2A)
{
  "name": "order-agent",
  "version": "1.0.0",
  "capabilities": ["query_order", "refund"],
  "skills": [
    {
      "id": "query_order",
      "name": "查询订单",
      "input_schema": {...},
      "output_schema": {...}
    }
  ],
  "authentication": {"type": "bearer"}
}
```

> 面试热点:**MCP vs A2A 区别**(MCP 是模型↔工具,A2A 是 agent↔agent)。

---

## 五、Spec Coding 的实战技巧

### 5.1 Spec First,但渐进式

**反模式**:一上来把所有接口、所有字段、所有错误码都塞 spec → 项目卡死在 spec 阶段。

**正确做法**:
- V1:只列 path + method,字段用 `object` 不细化
- V2:加主要字段和 required
- V3:加 enum、examples、错误码
- 每个版本对应一组可工作的代码

### 5.2 用 examples 而非 schema 喂 LLM

```yaml
# 反例:只有 schema(LLM 容易理解错)
Order:
  type: object
  properties:
    id: { type: string }
    status: { type: string, enum: [pending, paid, shipped] }

# 正例:schema + example
Order:
  type: object
  properties:
    id: { type: string }
    status: { type: string, enum: [pending, paid, shipped] }
  examples:
    - id: "ord_123"
      status: "paid"
```

> LLM 看 example 写实现,准确率显著高于只看 schema。

### 5.3 一份 spec,多端复用

```bash
# 同一份 openapi.yaml
openapi-generator -g python-fastapi     # Python 后端
openapi-generator -g typescript-axios    # 前端 client
openapi-generator -g kotlin              # Android client
openapi-generator -g swift               # iOS client
openapi-generator -g openapi-as-html    # 文档站
```

> 这才是 spec 的最大价值——**写一次,生多端**,避免手写 client SDK 的同步地狱。

### 5.4 Mock Server 让前后端并行

```bash
# 启 Prism mock,根据 spec 返回 example
prism mock openapi.yaml --port 4010 --dynamic

# 前端立刻能联调
curl http://localhost:4010/orders/123
# 返回 spec 里 example 的内容
```

> 不用等后端实现完,前端开发期就能用 mock 跑通。

### 5.5 Spec 即测试(Schemathesis)

```python
# 从 OpenAPI 自动 fuzz 测试
import schemathesis

schema = schemathesis.from_path("openapi.yaml")

@schema.parametrize()
def test_api(case):
    case.call_and_validate()
```

> 不用写测试用例,spec 已经描述了所有合法输入输出,Schemathesis 自动 fuzz 出 bug。

### 5.6 Spec 即文档(Swagger UI)

- 启动后端时挂载 Swagger UI:`/docs` 路径
- 团队成员看 UI 就能学 API
- 改 spec → 文档自动更新,不写手文档

### 5.7 Spec 版本兼容性的工程技巧

- **Additive-only 原则**:能加字段就别删字段,能加 enum 就别改
- **Optional 兜底**:新字段默认 optional,客户端宽容解析
- **Strict Mode 仅在 server 端**:client 宽松接受,server 严格校验
- **Sunset header**:删字段前先发 Sunset 告知客户端

### 5.8 跨团队 Spec 治理

- **API Owner 制**:每个 spec 有 owner,改动需 owner review
- **Spec PR 流程**:类似 RFC,跨团队 spec 改动需多方签字
- **Spec Registry**:类似 Maven Central,所有 spec 统一注册中心
- **Breaking change 检测**:CI 自动检测 diff,标 breaking 标签

---

## 六、常见问题与解决方案(必背避坑表)

### 6.1 设计阶段

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **前期成本高** | 项目卡在 spec 阶段 | 一上来细化太多 | 渐进式 spec,先粗后细 |
| **过度设计** | 把边角都塞 spec | 不懂 YAGNI | 只 spec 稳定接口,实验性用 Vibe |
| **spec 不一致** | 命名混乱 | 没 lint | Spectral + 命名规则 |
| **跨团队边界模糊** | 谁定义 spec? | 没治理 | API Owner + Spec Registry |
| **schema 学习曲线** | 团队不会 OpenAPI | 缺培训 | 内部模板 + workshop |

### 6.2 实现阶段

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **生成代码质量差** | 默认模板烂 | openapi-generator 模板问题 | 自定义 template + 后处理 |
| **AI 越界改 spec** | agent 改了 openapi.yaml | 没约束 | prompt 明确"禁止动 spec";CI 校验 spec 不变 |
| **生成 model 缺校验** | 没必填校验 | generator 默认 | 显式开 `--validation` |
| **手写代码与 spec 偏离** | 实现偷偷改字段 | 没 contract test | Pact / Schemathesis CI |
| **重复生成覆盖手改** | 重跑 codegen 冲掉手改 | 没分 generated/handwritten | 用 `_generated.py` 后缀 + .gitignore |

### 6.3 版本兼容类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **breaking change 没察觉** | 客户端崩 | 没检测 | CI 跑 `oasdiff` 检测 breaking |
| **多版本维护地狱** | 同时维护 v1/v2/v3 | 没 deprecation 期 | Sunset header + 兼容窗口 N 个 minor |
| **客户端不升级** | 老客户端用 v1 三年 | 没 sunset | Sunset + 邮件通知 + 强制下线 |
| **enum 加值 breaking** | 老客户端解析崩 | 严格模式 | 客户端宽容 + unknown 兜底 |

### 6.4 工具链类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **codegen 慢** | 改一行 spec 等 10s | 全量生成 | 增量生成 + 缓存 |
| **生成的 client 不符合习惯** | 命名风格违和 | 模板默认 | 自定义 mustache 模板 |
| **多语言 codegen 难统一** | 各语言风格不同 | 一份模板不够 | 每语言一套 template |
| **mock 返回数据假** | Prism 返回固定 example | example 单一 | 写多组 example + dynamic mock |
| **Spectral 规则太严** | 一堆 warn 阻塞 | 规则没分级 | 自定义 ruleset,分 error/warn/info |

### 6.5 团队/流程类

| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| **Spec 与代码脱节** | spec 改了代码没改 | 没 contract test CI | Schemathesis / Pact 进 CI |
| **PR Review 不知道改了 spec** | reviewer 漏看 | diff 不显眼 | 标签 require-spec-review |
| **没人维护 spec** | spec 落后于代码 | 没 owner | API Owner 制 + 改 spec 必须过 owner |
| **新人不知道改哪** | spec 一团乱 | 没 registry | Spec Registry + 文档 |

---

## 七、Spec Coding 与 AI Agent 的结合(面试热点)

### 7.1 为什么 Agent 时代需要 Spec Coding

- **Agent 自主性强**:Vibe Coding 让 agent 自由发挥,但容易跑偏
- **Spec 给确定性边界**:spec 锁死接口,agent 只在框内创造
- **可审计**:agent 写的代码必须符合 spec,审计有据
- **跨团队 agent**:A 团队的 agent 调 B 团队的 API,必须 spec

### 7.2 Kiro 的工作流(AWS 2025)

```
1. 写 Spec (Kiro 内置 spec editor)
2. Kiro 自动生成代码 skeleton
3. Kiro 调用 AI(默认 Claude / 可配别的)填充实现
4. Kiro 自动跑 contract test
5. Kiro 自动跑 security scan
6. 输出可部署的代码 + 文档
```

> 与 Vibe Coding 工具(Claude Code/Cursor)的区别:**Kiro 把 spec 强制为第一步**,而 Vibe 是从自然语言直接开始。

### 7.3 GitHub Spec Kit 的工作流

```
1. 写 spec (Markdown + frontmatter)
2. spec-kit validate (lint)
3. spec-kit generate (多语言代码)
4. spec-kit ai-implement (AI 填充)
5. spec-kit test (contract test)
6. spec-kit publish (发布到 registry)
```

> Spec Kit 是开源、与 IDE 无关,可以集成到任何 vibe coding 流程里。

### 7.4 MCP / A2A:Agent 自己也需要 spec

| Spec | 角色 | 例子 |
|---|---|---|
| **MCP** | LLM ↔ 工具 | Claude 调 GitHub MCP server |
| **A2A** | Agent ↔ Agent | 订单 Agent 调物流 Agent |
| **Function Calling schema** | LLM ↔ 用户函数 | OpenAI tool_use |
| **AgentCard** | Agent 元信息 | "我会查订单+退款" |

> 一个完整 Agent 系统会用 MCP 接工具、A2A 接别的 Agent、OpenAPI 接业务 API,**三种 spec 协同**。

---

## 八、典型工作流示例(面试讲得出)

### 8.1 给一个微服务写新接口

```bash
# 1. 写 spec(先粗)
cat > openapi.yaml << 'EOF'
# 见上文完整示例
EOF

# 2. lint
spectral lint openapi.yaml

# 3. 生成 skeleton
openapi-generator-cli generate -i openapi.yaml -g python-fastapi -o ./gen

# 4. 启动 mock 前端联调
prism mock openapi.yaml --port 4010 &

# 5. AI 填实现(此处接 Claude Code / OpenCode)
> "实现 GET /orders/{order_id},只改 src/api/orders.py::get_order
>  约束:用 gen/models.py 的 Pydantic model,不引入新依赖"

# 6. contract test
schemathesis run openapi.yaml --base-url http://localhost:8000

# 7. CI 跑完整测试 + security scan
pytest tests/ && bandit -r src/ && semgrep --config=auto

# 8. PR + 部署
```

### 8.2 给 Agent 加一个新工具(MCP)

```python
# 1. 写 MCP server spec(server.py)
from mcp.server import Server
server = Server("order-tools")

@server.tool("query_order")
async def query_order(order_id: str) -> dict:
    """Query order by id."""
    # AI 实现:从 DB 查
    return await db.get_order(order_id)

# 2. 生成 tool definition(从函数签名自动)
# 3. AI 客户端加载 MCP server
# 4. AI 自动调 query_order("ord_123")
```

> MCP 把"agent 工具"也 spec 化了,不用手写 function calling JSON。

---

## 九、一页速记卡

| 类别 | 必背 |
|---|---|
| 定义 | 规范先行:先 spec 后实现 |
| 起源 | 2025 Kiro(AWS) / Spec Kit(GitHub)翻红 |
| 核心流程 | Spec → Review → Codegen → AI 实现 → Contract Test → 部署 |
| Spec 格式 | OpenAPI / protobuf / JSON Schema / AsyncAPI / MCP / A2A |
| 工具 | openapi-generator / Spectral / Prism / Schemathesis / Pact |
| 价值 | 多端复用 + 可审计 + 前后端并行 |
| 与 Vibe 关系 | 分层:外层 Spec,内层 Vibe |
| 渐进式 | 先粗后细,V1 只列 path,迭代细化 |
| LLM 喂法 | examples > schema(给例子更准) |
| 版本管理 | Additive-only / Sunset header / 兼容窗口 |
| Contract Test | CI 强制 spec == 实现 |
| 反模式 | 一上来细化所有 / spec 与代码脱节 / 过度设计 |
| 面试金句 | "Vibe 是边感觉边写,Spec 是先约定后做,生产环境两者分层用" |

---

## 十、面试加分话术

### 10.1 "Vibe Coding 和 Spec Coding 你怎么看?"
> "不是二选一,是分层。外层接口契约用 Spec——比如 REST API 用
> OpenAPI、agent 协议用 MCP,这样多端能复用、跨团队能协作、合规能
> 审计。内层业务实现用 Vibe——agent 在 spec 锁死的契约里自由发挥,
> 写 CRUD、写测试、写文档。生产环境不能纯 vibe,但也不能纯 spec,
> 纯 spec 会卡死在前期。"

### 10.2 "Spec Coding 怎么避免 spec 和代码脱节?"
> "三层防线:① contract testing——CI 跑 Schemathesis 或 Pact,
> 任何 spec 与实现不一致阻断合并;② codegen 隔离——生成的 model
> 用 `_generated.py` 后缀,gitignore,手写代码不进 generated 文件;
> ③ spec owner 制——每个 spec 有 owner,改 spec 必过 owner review。
> 没有 contract test 的 spec 就是装饰品。"

### 10.3 "Kiro 和 Claude Code 你怎么选?"
> "看场景。Claude Code / OpenCode 是 Vibe 工具,适合个人项目、
> 原型、重构、补测试——快、灵活。Kiro 是 Spec-driven IDE,适合
> 跨团队 API、合规场景、SDK 开发——稳、可复用、可审计。我的
> 实践是:用 Claude Code 写实现,用 Spec Kit(开源)管 spec,
> 两者结合,不是替代关系。"

### 10.4 "MCP 和 A2A 有什么区别?"
> "MCP(Anthropic)是 LLM 与工具的协议——Claude 通过 MCP server
> 调 GitHub、Notion、Postgres。A2A(Google)是 Agent 与 Agent 的
> 协议——订单 Agent 通过 A2A 调物流 Agent。一个解决'模型调工具',
> 一个解决'Agent 互调'。完整 Agent 系统会同时用:用 OpenAPI 描述
> 业务 API、用 MCP 接外部工具、用 A2A 调其他 Agent,三种 spec 协同。"

### 10.5 "Spec Coding 最大的坑是什么?"
> "三个坑:① 一上来细化所有字段,项目卡死在 spec 阶段——解法是
> 渐进式 spec,V1 只列 path;② spec 与代码脱节——解法是 contract
> test 进 CI;③ 生成的 client 不符合团队习惯——解法是自定义模板,
> openapi-generator 默认模板通常需要二次定制。这三个坑踩过一遍,
> Spec Coding 就稳了。"
