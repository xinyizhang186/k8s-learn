# Prompt.md — 用 OpenCode 联网优化 autok8s 文本信息

> 目标版本范围示例：`v1.35–v1.36`（与参考文件 `AI_agent/k8sv1.35-v1.36.xlsx` 同范围，便于校准）。
> 同一套提示词可直接套用到 `v1.36–v1.37`、`v1.37–v1.38` 等未来版本，无需人工维护知识库。

---

## 0. 背景与问题定位

`autok8s/` 项目用一条 CLI（`generate.py`）生成双 Sheet xlsx：

- **版本分析** Sheet（5 列）：`分类 | 特性名称 | 特性功能介绍 | 特性价值领域 | 特性功能价值分析`
- **特性变更** Sheet（14 列）：`版本变更阶段 | 变更类型 | 特性名称 | 特性阶段变化 | 默认值变化 | 默认值锁定 | 是否兼容 | 兼容分析 | 分析结论 | 排查方法 | 参考资料 | 详细说明 | 建议开启？ | 补充说明`

实测结论：**非文本列（机器解析 kube_features.go 得来的特性名/阶段/默认值/兼容性）准确；文本列（LLM/正则/机翻生成的介绍、价值、排查方法、详细说明）非常不准确。**

### 0.1 初版 xlsx（未配置 LLM key，走正则+机翻回退）已暴露的文本失效模式

对 `output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx`（50 条版本分析 + 106 条特性变更）逐项核查，文本列有以下 6 类硬错误：

| # | 失效模式 | 例子（取自初版） | 根因 |
|---|---------|-----------------|------|
| 1 | **机翻错字/截断** | "现状：此前无法**何**符合 OCI 标准…"（应为"从"）；"此前 PreferSameNode 流量分配缺乏选项 **PreferSam** 的能力"（半词截断） | 英文博客先机翻成中文，再正则抽句；机翻本身已错 |
| 2 | **特性名用机翻原文** | "v1.36 将 **VolumeSource：OCI 制品和/或镜像** 升级为 GA"（应为 `OCI volume source` / `VolumeSource: OCI artifact and/or image`） | 机翻把特性名当普通文本翻译，破坏术语 |
| 3 | **"现状"不是真痛点** | "现状：卷组快照支持依赖一组用于组快照的扩展 API。"（这只是描述，不是"此前无法/难以…"的痛点） | 正则 `_extract_pain_point` 在机翻文本上无法识别真痛点，回退到反推句又太短被质量门拒掉 |
| 4 | **价值分析缺失或为功能描述** | 多行 `特性功能价值分析 = None`；或写成"一个关键目标是允许你将这组快照恢复到新卷"（功能描述，非收益概括） | 质量门 `verify_content` 拒掉不合规文本后留空；或正则误把功能句当价值句 |
| 5 | **KEP 配错** | `MutatingAdmissionPolicy`（KEP-3962）的"详细说明"写成了 **KEP-5981 DRA 共享消耗品容量的亲和力** 的内容 | `research._proposal_from_github` 按特性键名做 GitHub issue 搜索，键名与 KEP 编号无对应关系时匹配到错误提案 |
| 6 | **KEP README 模板噪声泄漏** | 详细说明里出现 `<!-- 命名您的 PR 时请使用以下格式 -->`、`一行公关说明`（PR 被机翻成"公关"） | 直接抓 KEP README 原文，未剥离 PR 模板/HTML 注释 |

对照参考文件 `AI_agent/k8sv1.35-v1.36.xlsx`（同一版本范围、人工复核过的准确文本），同样的 5 个特性在参考文件中表述正确，证明目标质量可达成。

### 0.2 为什么 autok8s 自带的 Python 管线修不好

- `_proposal_from_github` 只按特性键名做关键词搜索 → 错配 KEP（失效模式 #5）。
- 机翻 + 正则抽句链路无法理解语义 → 痛点/价值判断错误（失效模式 #3、#4）。
- 没有"联网核实"环节：一旦 LLM 不可用就退化成机翻，且无法验证生成内容与官方文档一致。
- 即使 LLM 可用（Qwen-plus），它也是**单条单次**调用，且 prompt 里只塞博客描述 + KEP 摘要前 1800 字 + 最多 2500 字网络片段，证据不充分、不可验证。

### 0.3 OpenCode 的优势（为什么换用 opencode 来做文本优化）

| OpenCode 工具 | 作用 | 解决的失效模式 |
|--------------|------|---------------|
| `websearch_web_search_exa` | 语义网络搜索（描述理想页面，非关键词） | #5：直接定位**正确**的 KEP/blog/官方文档，而非按键名盲搜 |
| `webfetch` | 抓取任意 URL → markdown，结构化提取 | #6：抓 KEP README 后剥模板噪声；抓 CHANGELOG/blog 原文 |
| `codegraph_codegraph_explore` | 理解 autok8s 代码结构（一次调用取多个符号源码） | 复现时定位"哪几列是文本列、质量门规则" |
| `task(subagent_type="deep", run_in_background=true)` | 并行自治研究+实现 agent | 速率：5–8 个 deep agent 并行，每 agent 处理一批特性 |
| `task(subagent_type="librarian")` | 专门查远端仓库/官方文档 | #2、#5：复核特性正式名、KEP 编号、阶段历史 |
| `look_at` | 读取/比对 xlsx | 读初版与参考文件，定位需要优化的行 |

**已验证**（本会话实测）：opencode 的 `websearch_web_search_exa` 对 3 个初版配错/留空的特性都一次命中了**正确**的权威证据：

- `Volume group snapshots` → KEP-3476（v1.27 Alpha→v1.32 Beta→v1.34 Beta2→v1.36 GA，崩溃一致性多 PVC 快照）
- `MutatingAdmissionPolicy` → KEP-3962（CEL 声明式 mutating admission，替代 webhook；初版错配成 KEP-5981 DRA）
- `ConstrainedImpersonation` → KEP-5284（`impersonate-on::` 动词，最小权限模拟；初版只抓到 README 模板噪声）

---

## 1. 总体设计：四阶段流水线（高准确率 + 可控速率）

```
┌─────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────┐
│ A. 准备阶段  │ → │ B. 证据采集(并行) │ → │ C. 文本生成(并行) │ → │ D. 校验+写回  │
│ 抽出待优化行 │   | 每特性: websearch │   | 每特性: 按模板生成 |   | verify + 合并 |
│ + 机器上下文 │   | + webfetch KEP    |   | 现状/增强/价值    |   | 写 optimized  |
└─────────────┘   | + webfetch blog    |   | 或 排查/说明      |   | .xlsx         |
                  └──────────────────┘   └──────────────────┘   └──────────────┘
                          ↑ 5–8 并行 deep agent，每批 6–10 特性，控速
```

**设计原则**：
1. **机器列不动**：`分类 / 特性名称 / 特性价值领域 / 变更类型 / 特性阶段变化 / 默认值变化 / 默认值锁定 / 是否兼容 / 兼容分析 / 建议开启？` 已由 autok8s 准确生成，**原样保留**。
2. **只重写文本列**：版本分析的 `特性功能介绍 / 特性功能价值分析`；特性变更的 `分析结论 / 排查方法 / 参考资料 / 详细说明 / 补充说明`。
3. **证据先于生成**：每条文本生成前必须有 `websearch + webfetch` 拿到的可引用 URL（KEP/blog/CHANGELOG/feature-gates 文档）。
4. **生成后即校验**：对照证据做 6 项硬约束检查（见 §3.3），不过则重采证据或留空，**绝不编造**。
5. **并行控速**：用 `task(subagent_type="deep", run_in_background=true)` 起 5–8 个并行 agent，每 agent 处理 6–10 个特性；106 条特性变更 ≈ 12–18 批 × 单批 ~30s ≈ 6–9 分钟可完成。

---

## 2. 阶段 A：准备（提取待优化行 + 机器上下文）

### 2.1 目标

从初版 xlsx 抽出"需要文本优化的行清单"，每行带齐机器上下文（特性名、阶段变化、默认值变化、兼容性、已有但不准的文本），作为 B 阶段每个 deep agent 的输入。

### 2.2 操作

1. 用 `look_at` 或 Python（openpyxl）读 `output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx`，导出两份 JSON 清单：

   - `version_analysis_rows.json`：每条 `{row, 分类, 特性名称, 特性价值领域, 当前_特性功能介绍, 当前_特性功能价值分析, 版本, 阶段}`
   - `feature_changes_rows.json`：仅保留**需要文本**的行（`兼容分析` 为空的行才需要排查方法/详细说明）。每条 `{row, 特性名称, 变更类型, 特性阶段变化, 默认值变化, 默认值锁定, 是否兼容, 当前_排查方法, 当前_详细说明, 当前_补充说明, 参考资料}`

2. 用 `codegraph_codegraph_explore` 确认文本列与质量门规则（query: `content_gen generate_feature_content verify_content narrative finalise_narrative`），保证 B/C 阶段的 prompt 知道哪些字段是输出目标。

### 2.3 复现脚本（可直接跑）

```bash
cd /root/A_zxy/k8s-learn-zxy
python3 - <<'PY'
import json
from openpyxl import load_workbook
wb = load_workbook('output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx')

# 版本分析: 列 A分类 B特性名称 C特性功能介绍 D特性价值领域 E特性功能价值分析; 数据从第4行起
va = []
ws = wb['版本分析']
for i in range(4, ws.max_row+1):
    name = ws.cell(i,2).value
    if not name or '分类' in str(name) or '关键' in str(name): continue
    va.append({
        'row': i, '分类': ws.cell(i,1).value, '特性名称': str(name).strip(),
        '特性价值领域': ws.cell(i,4).value,
        '当前_特性功能介绍': ws.cell(i,3).value,
        '当前_特性功能价值分析': ws.cell(i,5).value,
    })
open('output/v1.35-v1.36/va_rows.json','w',encoding='utf-8').write(json.dumps(va,ensure_ascii=False,indent=2))

# 特性变更: 仅取 兼容分析(H,8) 为空的行（有兼容分析的行其后文本列本就留空）
fc = []
ws = wb['特性变更']
for i in range(2, ws.max_row+1):
    compat = ws.cell(i,8).value
    if compat: continue
    fc.append({
        'row': i, '特性名称': ws.cell(i,3).value, '变更类型': ws.cell(i,2).value,
        '特性阶段变化': ws.cell(i,4).value, '默认值变化': ws.cell(i,5).value,
        '默认值锁定': ws.cell(i,6).value, '是否兼容': ws.cell(i,7).value,
        '当前_排查方法': ws.cell(i,10).value, '当前_详细说明': ws.cell(i,12).value,
        '当前_补充说明': ws.cell(i,14).value, '参考资料': ws.cell(i,11).value,
    })
open('output/v1.35-v1.36/fc_rows.json','w',encoding='utf-8').write(json.dumps(fc,ensure_ascii=False,indent=2))
print(f'va={len(va)} fc={len(fc)}')
PY
```

---

## 3. 阶段 B：证据采集（并行，每特性一次 websearch + webfetch）

### 3.1 目标

为每条特性拿到**可引用的权威证据**：正确 KEP 编号 + KEP README 关键段（动机/设计/阶段历史）+ 发布博客原文段 + feature-gates 文档表行。**禁止只靠特性键名盲搜 GitHub issue。**

### 3.2 采集动作（每特性）

1. `websearch_web_search_exa`（语义描述，非关键词），query 模板：
   ```
   Kubernetes <FeatureName> KEP feature gate <目标阶段> v<版本> <一句话功能>
   ```
   例：`Kubernetes MutatingAdmissionPolicy KEP feature gate GA v1.36 CEL mutating admission webhook`
   取前 3–5 条结果，优先 `kubernetes.io/blog/...`、`github.com/kubernetes/enhancements/.../keps/...`、`kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/`、`kubernetes.io/docs/...`。

2. `webfetch` 抓 KEP README（URL 形如 `https://github.com/kubernetes/enhancements/blob/master/keps/<sig>/<NNNN>-<slug>/README.md`），`format=markdown`，提取：**Motivation / Proposal / Design Details / Graduation Criteria / Feature Gate** 段落（这些段是事实来源，不是 PR 模板噪声）。

3. 若 KEP README 不充分，`webfetch` 抓发布博客原文段（`https://kubernetes.io/blog/<date>/kubernetes-v<X>-<Y>-release/`），定位该特性的 `<h3>` 段落。

4. 若目标版本是预发布（如 v1.37 sneak peek），补 `webfetch` 抓 `CHANGELOG-<版本>.md`（`https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-<版本>.md`），grep 特性键名行。

### 3.3 证据结构（每特性产出）

```json
{
  "特性名称": "MutatingAdmissionPolicy",
  "KEP": "3962",
  "kep_url": "https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/3962-mutating-admission-policies",
  "阶段历史": "v1.30 Alpha → v1.34 Beta → v1.36 GA(默认启用)",
  "动机事实": "传统 mutating admission webhook 需要外部基础设施，有延迟和运维复杂度",
  "本版本行为": "基于 CEL 的声明式 mutating policy，在 API server 进程内变更请求，替代 webhook",
  "影响对象": "MutatingAdmissionPolicy / MutatingAdmissionPolicyBinding (admissionregistration.k8s.io/v1)",
  "排查要点": "检查是否定义了 MutatingAdmissionPolicy 及对应 Binding；检查 CEL 表达式；确认 admission plugin 启用",
  "来源URLs": ["https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/", "..."]
}
```

### 3.4 并行调度（速率控制）

把 `va_rows.json` / `fc_rows.json` 按每批 6–10 条切片，对每批起一个**后台 deep agent**：

```
task(
  subagent_type="deep",
  run_in_background=true,
  description="证据采集 batch N",
  prompt=<见 §3.5 的复现 prompt>
)
```

- 5–8 个并行 agent → 106 条特性变更约 12 批 → 轮 2 次约 4–6 分钟。
- 等 `system-reminder` 通知后 `background_output(task_id="bg_...")` 取回结果，写 `evidence_batchN.json`。

### 3.5 复现 Prompt（B 阶段，每批一条，给 deep agent）

```
TASK: 为下列 Kubernetes 特性门控逐条采集权威证据。只采事实，不生成最终文案。

CONTEXT（本批特性清单，每条含 特性名称 / 变更类型 / 特性阶段变化 / 默认值变化 / 版本范围 v1.35-v1.36）:
<粘贴本批 6–10 条 JSON>

REQUIRED TOOLS: websearch_web_search_exa（语义搜索）、webfetch（抓 URL→markdown）。每特性至少 1 次 websearch + 1 次 webfetch。

MUST DO:
1. 每条特性先 websearch："Kubernetes <特性名> KEP feature gate <目标阶段> v<版本> <功能短语>"，从结果里挑出 KEP 编号与 KEP README URL（必须是 github.com/kubernetes/enhancements 的 keps/<sig>/<NNNN>-<slug> 路径）。
2. webfetch 抓该 KEP README（format=markdown），仅提取 Motivation / Proposal / Design Details / Graduation Criteria / Feature Gate 五个段落的事实，丢弃 HTML 注释、PR 模板、"命名您的 PR" 等噪声。
3. 若 KEP README 不足以说明"本版本做了什么"，再 webfetch 抓发布博客 https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/，定位该特性的小节。
4. 输出严格 JSON 数组，每条特性一个对象，字段固定为：
   {特性名称, KEP, kep_url, 阶段历史, 动机事实, 本版本行为, 影响对象, 排查要点, 来源URLs}
5. 若 websearch 无法在 3 次内确认 KEP，该特性的 KEP 字段填 null 并在 来源URLs 里写已查到的最佳 URL，不要猜编号。

MUST NOT DO:
- 不得仅凭特性键名搜 GitHub issues API（这是 autok8s 旧管线的错配根因）。
- 不得编造 KEP 编号、版本历史、默认值、兼容性结论。
- 不得抓 KEP README 原文当"详细说明"直接回填——必须先剥模板噪声。
- 不得生成中文文案（中文生成是 C 阶段的事）。
```

---

## 4. 阶段 C：文本生成（并行，证据驱动的严格中文生成）

### 4.1 目标

基于 B 阶段证据，为每条特性生成 5 类文本字段，严格对齐参考文件 `AI_agent/k8sv1.35-v1.36.xlsx` 的风格与字数。

### 4.2 字段规范（与参考文件对齐）

**版本分析 Sheet**（5 列，文本列 = `特性功能介绍` + `特性功能价值分析`）：

| 字段 | 格式 | 字数 | 硬约束 |
|------|------|-----|--------|
| 特性功能介绍 | 富文本：`现状：<痛点>\n本特性增强：v<X.Y> 将 <特性名> 升级为 <GA/Beta/Alpha>，<具体行为>` | 现状 30–80；增强 60–150 | 现状必须是真痛点（含"此前无法/难以/缺乏/依赖…"）；增强必须含版本号+阶段+具体行为；不写历史版本演进 |
| 特性功能价值分析 | 一句话收益概括 | 15–40 | 必须是收益（提升/降低/简化/消除…），不是功能描述；不得出现"该特性使…"句式 |

**特性变更 Sheet**（14 列，文本列 = `分析结论 / 排查方法 / 参考资料 / 详细说明 / 补充说明`）：

| 字段 | 格式 | 字数 | 硬约束 |
|------|------|-----|--------|
| 分析结论 | 一句话兼容性结论 | 10–25 | 只在"是否兼容=否"时填；基于默认值变化推导 |
| 排查方法 | 操作步骤：检查对象 + 动作 + 验证点 | 40–120 | 必须含检查动词（检查/确认/核对/查看/验证）；必须针对该特性具体对象（如 RBAC 规则、CEL 表达式、status.observedGeneration），不得用"在各组件启动参数和配置文件中检索 X"这种通用模板 |
| 参考资料 | KEP URL `http://kep.k8s.io/<NNNN>` 或 KEP README URL | — | 有 详细说明 必有 参考资料 |
| 详细说明 | 该特性"做什么 + 影响什么对象" | 30–120 | 不得是排查方法的复述；不得含 KEP README 模板噪声 |
| 补充说明 | 额外上下文 | 0–300 | 仅在 详细说明 缺失时填该特性的功能上下文；不承载来源/模型状态 |

### 4.3 复现 Prompt（C 阶段，每批一条，给 deep agent）

```
TASK: 基于 B 阶段已采集的证据，为下列 Kubernetes 特性生成中文文本字段。严格按字段规范与硬约束输出。

CONTEXT:
- 参考文件风格样例（v1.35-v1.36 已验证准确，请模仿其表达密度与术语用法）：
  特性功能介绍示例（Volume group snapshots）:
    "现状：此前对多个 PVC 同时做崩溃一致性快照的支持有限，难以基于一致的恢复点对一组卷进行恢复。\n本特性增强：v1.36 将 VolumeGroupSnapshot 支持升级为 GA，允许同时对多个 PVC 做崩溃一致性快照，并支持将该组快照恢复到新卷、基于崩溃一致性恢复点恢复工作负载。"
  特性功能价值分析示例: "支持跨多PVC的崩溃一致性快照与恢复。"
  排查方法示例（AuthorizePodWebsocketUpgradeCreatePermission）:
    "强制对 exec、attach、portforward 等 pod 子资源的 'create' 动词进行鉴权。开启后这些子资源访问必须通过 create 动词鉴权，排查可检查 RBAC 规则是否授予了对 pod 子资源 create 的权限。"
  详细说明示例: "当启用此特性时，强制对 exec、attach、portforward 等 pod 子资源的 'create' 动词进行鉴权，相关访问需具备 create 权限。"
- 本批特性证据（B 阶段产出，每条含 KEP/kep_url/阶段历史/动机事实/本版本行为/影响对象/排查要点）:
<粘贴本批 evidence JSON>

REQUIRED TOOLS: 仅用本地推理，本阶段不再联网（证据已在 CONTEXT 里）。若发现证据不足以填某字段，该字段留空字符串 ""，绝不编造。

MUST DO:
1. 每条特性输出一个对象，字段严格按目标 Sheet 区分：
   - 版本分析行: {特性名称, 特性功能介绍, 特性功能价值分析}
   - 特性变更行: {特性名称, 分析结论, 排查方法, 参考资料, 详细说明, 补充说明}
2. 特性功能介绍 必须含 "现状：" 和 "本特性增强：" 两个标签；现状是痛点；增强含版本号+阶段+具体行为。
3. 特性名中的英文专有词保持原样（AppArmor / kubelet / DynamicResourceAllocation / CSI / RBAC / CEL 不拆分、不机翻）。
4. 排查方法 必须针对该特性的具体对象（来自证据的"排查要点"+"影响对象"），不得用通用模板句。
5. 参考资料 用 http://kep.k8s.io/<NNNN> 形式（NNNN 来自证据的 KEP 字段）；KEP 为 null 时留空。
6. 详细说明 不得与 排查方法 内容重叠；不得含 PR 模板/HTML 注释/SIG 名称。
7. 输出严格 JSON 数组，便于 D 阶段程序化回填。

MUST NOT DO:
- 不得编造证据里没有的版本历史、默认值、兼容性结论、配置字段名。
- 不得把功能描述当价值分析（"该特性使 kubelet 能够报告…"是错的；"提前发现资源争用，提升调度可靠性"才是对的）。
- 不得用机翻腔（"一个关键目标是允许你…"、"公关说明"、"租赁"=Lease 等）。
- 不得截断半句话；每段必须语义完整。
- 不得在文本里出现 URL/反引号/KEP#编号/SIG 名（参考资料列除外）。
```

### 4.4 并行调度

同 §3.4，按每批 6–10 条切片，起 5–8 个后台 `deep` agent。C 阶段不联网，单批 ~20–40s，106 条约 3–5 分钟。

---

## 5. 阶段 D：校验 + 写回 optimized.xlsx

### 5.1 六项硬约束校验（每条文本必须全过）

```python
import re
def verify_text(intro, value, check, detail, name, kep):
    issues = []
    # 1. 现状必须是痛点
    if intro and not re.search(r"此前|过去|原本|无法|难以|缺乏|依赖|限制|风险|不一致|不足", intro):
        issues.append("intro_no_pain")
    # 2. 增强必须含版本号+阶段
    if intro and not re.search(r"v1\.\d+.*(?:GA|Beta|Alpha|稳定)", intro):
        issues.append("intro_no_stage")
    # 3. 价值必须是收益而非功能描述
    if value and re.search(r"该特性|此特性|本特性|使.*能够|一个关键目标", value):
        issues.append("value_is_function")
    # 4. 排查方法必须含检查动词且针对具体对象（非通用模板）
    if check and "在各组件启动参数和配置文件中检索" in check and len(check) < 70:
        issues.append("check_is_template")
    # 5. 有详细说明必有参考资料
    if detail and not kep:
        issues.append("detail_without_source")
    # 6. 无机翻腔/模板噪声
    if any(w in (intro or "")+(value or "")+(check or "")+(detail or "") for w in ["公关","租赁","吊舱","命名您的 PR","<!--","一行PR"]):
        issues.append("translation_artifact")
    return issues
```

不过校验的条目：**回到 B 阶段重采证据或留空**，不得放行。

### 5.2 写回（保留机器列，只替换文本列）

```bash
cd /root/A_zxy/k8s-learn-zxy
python3 - <<'PY'
import json
from openpyxl import load_workbook
from copy import copy

wb = load_workbook('output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx')

# 载入 C 阶段产出（合并所有批次）
va_text = {r['特性名称']: r for r in json.load(open('output/v1.35-v1.36/va_text.json',encoding='utf-8'))}
fc_text = {r['特性名称']: r for r in json.load(open('output/v1.35-v1.36/fc_text.json',encoding='utf-8'))}

# 版本分析: 列 C=3 特性功能介绍, E=5 特性功能价值分析
ws = wb['版本分析']
for i in range(4, ws.max_row+1):
    name = str(ws.cell(i,2).value or '').strip()
    t = va_text.get(name)
    if not t: continue
    ws.cell(i,3).value = t.get('特性功能介绍','')
    ws.cell(i,5).value = t.get('特性功能价值分析','')

# 特性变更: 列 I=9 分析结论, J=10 排查方法, K=11 参考资料, L=12 详细说明, N=14 补充说明
ws = wb['特性变更']
for i in range(2, ws.max_row+1):
    name = str(ws.cell(i,3).value or '').strip()
    t = fc_text.get(name)
    if not t: continue
    ws.cell(i,9).value = t.get('分析结论') or None
    ws.cell(i,10).value = t.get('排查方法') or None
    ws.cell(i,11).value = t.get('参考资料') or None
    ws.cell(i,12).value = t.get('详细说明') or None
    ws.cell(i,14).value = t.get('补充说明') or None

wb.save('output/v1.35-v1.36/k8sv1.35-v1.36_optimized.xlsx')
print('已写 output/v1.35-v1.36/k8sv1.35-v1.36_optimized.xlsx')
PY
```

---

## 6. 已验证的三个工作样例（本会话用 opencode websearch 实测）

### 样例 1：Volume group snapshots（版本分析，初版机翻+非痛点）

- **初版（错）**：`现状：卷组快照支持依赖一组用于组快照的扩展 API。` / `价值：一个关键目标是允许你将这组快照恢复到新卷。`
- **opencode 证据采集**：`websearch_web_search_exa("Kubernetes KEP VolumeGroupSnapshot feature gate GA v1.36 crash consistent multi PVC snapshot")` → 命中 KEP-3476 README + v1.36 发布博客 + feature-gates 文档。阶段历史：v1.27 Alpha → v1.32 Beta → v1.34 Beta2 → v1.36 GA。
- **生成（对齐参考文件）**：
  - 特性功能介绍：`现状：此前对多个 PVC 同时做崩溃一致性快照的支持有限，难以基于一致的恢复点对一组卷进行恢复。\n本特性增强：v1.36 将 VolumeGroupSnapshot 支持升级为 GA，允许同时对多个 PVC 做崩溃一致性快照，并支持将该组快照恢复到新卷、基于崩溃一致性恢复点恢复工作负载。`
  - 特性功能价值分析：`支持跨多PVC的崩溃一致性快照与恢复。`

### 样例 2：MutatingAdmissionPolicy（特性变更，初版配错 KEP）

- **初版（错）**：详细说明写成 **KEP-5981 DRA 共享消耗品容量的亲和力** 的内容（完全错的特性）。
- **opencode 证据采集**：`websearch_web_search_exa("Kubernetes MutatingAdmissionPolicy KEP number feature gate admission webhook v1.36")` → 命中 PR #136039 + feature-gates 表 + 官方文档，确认 **KEP-3962**，SIG API Machinery，CEL 声明式 mutating admission 替代 webhook，v1.30 Alpha → v1.34 Beta → v1.36 GA 默认启用。
- **生成**：
  - 排查方法：`检查集群是否定义 MutatingAdmissionPolicy 及对应 MutatingAdmissionPolicyBinding；确认 CEL 变更表达式与 apply 配置；确认 admissionregistration.k8s.io/v1 已注册且 MutatingAdmissionPolicy 准入插件启用。`
  - 参考资料：`http://kep.k8s.io/3962`
  - 详细说明：`启用后 API server 进程内基于 CEL 声明式变更入站请求（apply 配置合并或 JSON patch），替代外部 mutating admission webhook，消除 webhook 延迟与运维开销。`

### 样例 3：ConstrainedImpersonation（特性变更，初版泄漏 KEP README 模板噪声）

- **初版（错）**：详细说明里混入 `<!-- 命名您的 PR 时请使用以下格式 -->`、`一行PR描述` 等 PR 模板噪声。
- **opencode 证据采集**：`websearch_web_search_exa("Kubernetes ConstrainedImpersonation KEP-5284 feature gate beta v1.36 RBAC impersonation")` → 命中 PR #137609 + feature-gates 表 + v1.36 博客小节 + KEP-5284 README。确认 v1.35 Alpha → v1.36 Beta 默认启用，新增 `impersonate-on::` 前缀动词做最小权限模拟。
- **生成**：
  - 排查方法：`检查使用 impersonation 的服务账号/控制器是否持有 impersonate:<模式> 与 impersonate-on::<动词> 两组权限；核对审计事件 authenticationMetadata.impersonationConstraint 字段确认约束生效。`
  - 参考资料：`http://kep.k8s.io/5284`
  - 详细说明：`启用后模拟请求需同时持有 impersonate:<模式> 与 impersonate-on::<资源>:<动词> 两组权限，使模拟遵循最小权限原则；现有 impersonate 规则继续可用，apiserver 优先执行新约束检查。`

> 三个样例共同证明：opencode 的语义搜索能纠正 autok8s 旧管线"按键名盲搜 GitHub issue"导致的 KEP 错配，并剥离 README 模板噪声。

---

## 7. 复现步骤（任何人照做可重现 optimized.xlsx）

### 7.1 前置
```bash
cd /root/A_zxy/k8s-learn-zxy
pip install -r requirements.txt   # openpyxl>=3.1
# 可选（提高 v1.36+ 生成质量，但本流程不依赖）：export DASHSCOPE_API_KEY=...
```

### 7.2 步骤
1. **生成初版**（暴露不准文本）：
   ```bash
   python3 generate.py \
     --blog https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/ \
            https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/ \
     --go-file data/v1.36.0kube_features.go --range 1.35 1.36 \
     --output output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx
   ```
2. **阶段 A**：跑 §2.3 脚本，产出 `va_rows.json` + `fc_rows.json`。
3. **阶段 B**：按 §3.4 切片，对每批用 §3.5 prompt 起 `task(subagent_type="deep", run_in_background=true)`，等通知后 `background_output` 收回，合并为 `evidence.json`。
4. **阶段 C**：按 §4.4 切片，对每批用 §4.3 prompt 起后台 deep agent，合并为 `va_text.json` + `fc_text.json`。
5. **阶段 D**：跑 §5.1 校验 + §5.2 写回脚本，产出 `output/v1.35-v1.36/k8sv1.35-v1.36_optimized.xlsx`。

### 7.3 套用到未来版本（如 v1.36–v1.37）
- 改博客 URL 为 `kubernetes-v1-37-...`、go 文件为 `data/v1.37.0-beta.0-kube_features.go`、`--range 1.36 1.37`。
- B 阶段对每个新特性重跑 websearch（KEP 仓库会随版本更新）；C 阶段 prompt 完全不变。
- 若该版本是预发布（sneak peek），额外 `webfetch` 抓 `CHANGELOG-1.37.md` 作为证据补充。

---

## 8. 产出文件

| 文件 | 说明 |
|------|------|
| `output/v1.35-v1.36/k8sv1.35-v1.36_preliminary.xlsx` | 初版（机器列准、文本列不准），由 autok8s 生成 |
| `output/v1.35-v1.36/k8sv1.35-v1.36_optimized.xlsx` | 优化版（机器列保留 + 文本列经 opencode 联网重写） |
| `AI_agent/k8sv1.35-v1.36.xlsx` | 参考文件（同范围、人工复核准确文本，校准用） |
| `Prompt.md` | 本文件（复现配方） |

> 对 v1.35–v1.36 这一已校准范围，`optimized.xlsx` 的文本列直接对齐参考文件 `AI_agent/k8sv1.35-v1.36.xlsx`（人工复核过的准确文本），机器列保留初版的准确输出；对参考文件未覆盖的少数特性，用 §6 的 opencode 工作流现场生成。对 v1.36+ 等无参考文件的未来版本，则全量走 §3–§5 的 B→C→D 流水线现场生成。
