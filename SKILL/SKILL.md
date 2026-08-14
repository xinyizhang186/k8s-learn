---
name: k8s-release-xlsx
description: 以文本准确性和可读性为首要目标，自动生成可追溯的 Kubernetes 版本分析与 FeatureGate 特性变更双 Sheet XLSX，并交付官方网址 reference.md 与各固定 tag 的 features.go 证据包。适用于 Kubernetes 版本解读、升级分析、发布博客研究、KEP 核验、pkg/features/kube_features.go 差异解析、FeatureGate 阶段/默认值/锁定变化分析，以及需要通过迭代精炼提高中文内容质量的场景。技能包不依赖现有项目或产品专属工具，可整目录迁移到其他 Agent 产品。
---

# Kubernetes 版本分析 XLSX

从官方固定版本源码和官方材料生成 `版本分析`、`特性变更` 双 Sheet XLSX。第一要义是生成文本准确、可读；验证用于定向精炼，不作为阻断式质量门。

## 目录结构

```text
SKILL/
├── SKILL.md                          # 本文件：流程、契约、质量规范
├── assets/
│   └── report-style.json             # XLSX 列宽、配色等样式常量（只由 build_report.py 读取）
├── scripts/                          # Python 3 标准库脚本，无第三方依赖
│   ├── init_run.py                   # 阶段 0：初始化运行目录与 config.json
│   ├── fetch_official.py             # 阶段 1/2：下载固定 Tag 源码、CHANGELOG、发布博客
│   ├── extract_feature_changes.py    # 阶段 1：解析 kube_features.go → machine-facts.json
│   ├── extract_release_catalog.py    # 阶段 2：解析发布博客 → release-catalog.json
│   ├── gen_analysis.py               # 阶段 3a：自动生成特性变更文本（含 GATE_CN 字典）
│   ├── validate_analysis.py          # 阶段 4：质量校验 → validation.json
│   ├── build_report.py               # 阶段 5：构建双 Sheet XLSX
│   ├── verify_report.py              # 阶段 5：验证 XLSX 结构与计数
│   ├── package_output.py             # 阶段 6：打包交付目录与 data/ 证据包
│   ├── validate_skill.py             # 迁移自检：校验 frontmatter 与目录完整性
│   └── self_test.py                  # 端到端冒烟测试（使用 examples/ 固件）
├── references/                       # 按需读取的专题文档，不预加载
│   ├── writing-and-iteration.md      # 写作标准、好/坏示例、迭代与复查清单（阶段 3b/4/4.5 必读）
│   ├── workbook-contract.md          # XLSX 列定义、analysis.json schema、稀疏规则（阶段 5 前读）
│   ├── kubernetes-sources.md         # 官方来源优先级与证据治理（阶段 2 前读）
│   ├── feature-gates-source.md       # kube_features.go 结构与解析口径（仅解析异常时读）
│   └── portability.md                # 跨产品迁移约束（仅首次部署读）
└── examples/                         # 离线测试固件，不作为事实来源
    ├── fixtures/                     # 最小化 kube_features.go 样本
    ├── analysis-record.json          # 冒烟测试用的分析骨架样本
    └── request-and-result.md         # 正确/错误文本与交付形态示例
```

## 质量优先级

按 `准确性 > 可读性 > 完整度 > 样式` 决策，低优先级不得牺牲高优先级：

- **准确**：每个事实与同一特性、同一版本的官方证据一致；机器事实不推断、不改写。证据不足时留空或标记待核实，不补写"合理猜测"。
- **可读**：先说受影响对象和旧问题，再说本版本机制，最后说条件、边界或升级动作；每句只承载一个主要判断，删除重复、口号和逐字机翻。
- **完整**：只补充影响理解或决策的事实，不为达到长度或填满单元格扩写。
- **样式**：在文本正确且清晰后再调整列宽、行高和颜色。

每轮先修事实/来源，再修歧义和行动性，最后才修长度与样式。

---

## 文本质量规范

本节是所有文本字段的**唯一权威规则源**。阶段 3a/3b 生成、阶段 4/4.5 校验时统一引用本节，不重复展开。详细的好/坏文本示例和迭代技巧见 [references/writing-and-iteration.md](references/writing-and-iteration.md)。

### 版本分析 — 单特性条目

| 字段 | 字数 | 必含维度 | 禁止项 |
|---|---|---|---|
| `current_problem`（现状） | 150–300 | 受影响对象 · 旧行为 · 具体限制 · 实际后果 | 只写一句话；"此前 Kubernetes 不支持…"模板开头 |
| `enhancement`（本特性增强） | 180–350 | 目标版本与阶段/默认状态 · 阶段演进历史 · 核心机制（如何工作） · 关键 API/配置字段 · 实际收益与边界 | 只复述阶段和默认值；"提升了""增强了"无机制说明 |
| `value_domain`（价值领域） | 一个短标签 | 如 `DFX:安全`、`功能:调度`、`DFX:可观测性` | 逗号并列多项 |
| `value_analysis`（价值分析） | 70–180 | 直接收益（谁获得什么好处） · 受益场景 · 采用前提或残余风险 | "提升效率""增强稳定性"等泛化表述；重复功能介绍；模糊推断 |

### 版本分析 — 多特性条目（sub_features > 1）

多特性条目的 `enhancement` 由阶段 3a 的 `gen_analysis.py` 自动生成，逐行展开子特性：`子特性名称（KEP #<id>，<SIG>）<中文功能描述>，升级为 <阶段> 并默认<启用/关闭>。`。`current_problem`、`value_domain`、`value_analysis` 由阶段 3b 补写，要求同单特性条目。

### 版本分析 — 风险条目

| 字段 | 字数 | 必含维度 | 禁止项 |
|---|---|---|---|
| `feature_summary`（风险详细描述） | 100–300 | 弃用/移除原因 · 影响范围（哪些集群受影响） · 迁移方案 · 时间线 | 留空；只写"待核实" |
| `value_analysis`（技术 or 商业影响） | 按格式 | 严格按下表三类格式之一 | 自由发挥；增删固定词句；混用格式 |

**`value_analysis` 三类固定格式（风险条目专用）：**

| 风险类型 | 格式 |
|---|---|
| 参数或特性弃用 | `关键参数/特性弃用，产品需审视是否使用<具体特性/参数名>字段，及时适配` |
| 特性整体弃用 | `关键特性弃用，产品需审视是否使用<具体特性名>，及时适配` |
| 特性版本弃用 | `关键特性版本弃用，产品需审视是否使用<具体特性名>，及时适配` |

`<...>` 替换为该风险条目的特性名称或被弃用的参数/字段名。

### 特性变更 — 非兼容行

非兼容行（`compatibility_analysis` 为空）须填写以下字段：

| 字段 | 要求 | 禁止项 |
|---|---|---|
| `check_method`（排查方法） | 包含 gate 专属检查对象 + 具体行为变化 + 检查动作 | 通用模板"开启后该特性自动生效"；冗余重复 |
| `details`（详细说明） | >= 100 字；以功能机制描述为主体；含四维度：**功能定义**（是什么）·**行为变化**（改变了什么）·**核心机制**（如何工作，关键 API/字段）·**适用范围**（条件/依赖） | 只复述阶段和默认值；"升级到 vX 后该特性默认启用"模板话术；留空 |
| `conclusion`（分析结论） | 含 gate 专属功能描述 + 明确升级决策 | 只复述"vX 默认启用" |
| `notes`（补充说明） | <= 90 字；一条边界或后续动作 | 与 conclusion 重复 |
| `recommendation`（建议开启） | 仅 `开启`、`关闭` 或空白 | 其他值 |

> **兼容行**（`compatibility_analysis` 非空）的 `conclusion`、`check_method`、`details`、`notes`、`recommendation` 全部留空。

### 通用禁止项

- 所有中文文本不得保留英文源码注释原文；技术标识符（FeatureGate 名、API 字段名、KEP 编号）保留英文。
- 不得使用机械翻译或单词替换；须理解英文内容后用通顺中文重新表述。
- 禁止跨特性复用文本模板；同名特性跨版本时分别确认当期状态。
- 禁止为凑字数添加"提升效率、增强稳定性"等空泛句子。
- 禁止把推导写成官方结论；区分"官方明确说明"与"由机制推导的分析"。

---

## 运行契约

### 输入与输出

- **输入**：起始版本、目标版本、最终 XLSX 路径；预发布 ref、博客 URL、运行目录可选。
- **输出**：`<output-dir>/k8s-v<from>-v<to>/<report>.xlsx` 和 `<output-dir>/k8s-v<from>-v<to>/data/`。不在 `<output-dir>` 下单独放置 xlsx，只保留版本子目录。
- **中间态**：全部写入用户指定的 `<run-dir>`；不写入 Skill 目录或最终输出目录。

### 权威边界

| 字段 | 唯一来源 | 不可替代 |
|---|---|---|
| 版本分析特性名称与主体 | 对应版本正式发行博客（由 `catalog_id` 锁定） | KEP、CHANGELOG、源码注释、模型知识 |
| FeatureGate 阶段/默认值/锁定 | 固定 Tag `kube_features.go` 源码解析 | 发布博客、KEP、模型知识 |
| `primary_source` | `release-catalog.json` 中该条目的 `source` | 其他博客、搜索结果 |

### 分类限定

`版本分析` 关键特性区的 `分类` 列严格限定三类：
- `孵化成熟特性:<version>` — Stable 毕业 + Spotlight 未标注前缀的特性
- `增强特性:<version>` — Beta
- `新增特性:<version>` — Alpha

风险区使用 `特性剔除:<version>`。禁止 `关键特性`、`highlight` 或其他分类值。

### 完整性基线

- `版本分析` 覆盖发布博客 Stable/Beta/Alpha 目录全部条目，或有逐项排除理由（记入 `catalog_omissions`）。
- `特性变更` 覆盖目标 Tag 中版本落在闭区间 `[from,to]` 的全部版本化规格。
- 不得把两者缩减为"精选重点"或"端点差异"。

### 独立性

生成时不读取旧 XLSX、现有项目脚本或人工样表作为事实依赖。人工样表只可用于性能评估和回归测试。

---

## 文本生成协议

先证据、后判断、再成句。每个分析项先建立最小证据卡，不直接根据特性名称生成正文：

```text
主体 | 目标版本 | 机器变化 | 官方机制 | 影响对象 | 条件/边界 | 来源
```

按以下顺序生成并复核：

1. **锁定事实**：机器变化逐字取自 `machine-facts.json`。`版本分析` 先以对应版本正式发行博客正文建立主体事实；仅当博客不足以说明机制、配置、边界或价值判断时，才搜索并打开同项 KEP、官方文档或固定 Tag 资料。
2. **结构成句**：`现状` 写"对象/场景 → 旧行为 → 限制/后果"；`本特性增强` 写"版本/状态 → 机制/API → 条件/边界"；价值、风险和建议分别回答"收益是什么、谁受影响、升级做什么"。
3. **压缩表达**：保留必要技术名词英文原样；删除来源复述、发布历史、模板话术、同义重复和无法改变决策的细节。
4. **逐项复核**：检查主体、版本、阶段/默认值、机制、影响对象、边界和来源是否一致；任一项不确定则回到证据卡，不靠改写解决。

---

## 阶段路由

| 阶段 | 目标 | 命令 | 读取 | 主要产物 |
|---|---|---|---|---|
| 0 | 固定范围 | `init_run.py` | 本文件 | `config.json` |
| 1 | 提取机器事实 | `fetch_official.py` + `extract_feature_changes.py` | 异常时读 feature-gates-source.md | `source-index.json`、`machine-facts.json` |
| 2 | 建立发布目录与证据 | `fetch_official.py --add` + `extract_release_catalog.py` | kubernetes-sources.md | `release-catalog.json`、最小证据卡 |
| 3a | 自动生成特性变更文本 | `gen_analysis.py` | 无需读取 reference | `analysis.json`（特性变更全部 ready） |
| 3b | 补写版本分析中文文本 | LLM 人工 | writing-and-iteration.md | `analysis.json`（版本分析全部 ready） |
| 4 | 定向精炼 | `validate_analysis.py` | validation.json 指向的字段 | 通过诊断的 `analysis.json` |
| 4.5 | 文本质量复查与扩写 | LLM 人工 | writing-and-iteration.md 复查清单 | 扩写后的 `analysis.json` |
| 5 | 构建复核 | `build_report.py` + `verify_report.py` | workbook-contract.md（首次） | 已验证候选 XLSX |
| 6 | 打包交付 | `package_output.py` | 无 | XLSX 与 `data/` 证据包 |

严格按顺序执行；阶段的退出条件满足后再进入下一阶段。

---

## 阶段 0：固定范围

```bash
python scripts/init_run.py --from 1.35 --to 1.36 --run-dir <run-dir>
```

- 只给目标版本时省略 `--from`（默认取 `to - 1`）。预发布版本用 `--to-ref v1.37.0-rc.0` 指定固定 Tag。
- **退出**：`config.json` 中版本连续、refs 明确、`<run-dir>` 不在最终输出目录内。

## 阶段 1：生成机器事实

```bash
python scripts/fetch_official.py --run-dir <run-dir>
python scripts/extract_feature_changes.py --run-dir <run-dir>
```

- **产物**：`source-index.json`（带 URL/SHA-256）、`machine-facts.json`（不可改写）、分析骨架。每个变更事件含从 `kube_features.go` 注释提取的 `gate_description` 和 `kep_url`，供阶段 3a 使用。
- **退出**：每个版本都有固定 Tag 源码与 CHANGELOG；所有范围事件有唯一 ID；主表数量与范围事件数一致。
- **异常**：解析失败时读 [references/feature-gates-source.md](references/feature-gates-source.md)；修解析器，不手填机器事实。

## 阶段 2：建立发布目录并收集官方证据

```bash
python scripts/fetch_official.py --run-dir <run-dir> --add release_blog=<official-release-blog-url>
python scripts/extract_release_catalog.py --run-dir <run-dir>
```

- **产物**：`release-catalog.json`；每项含 `catalog_id`、博客原文名称、`source`。含子特性的条目自动提取 `sub_features`（KEP ID、SIG、description）。
- **来源规则**（详见 [references/kubernetes-sources.md](references/kubernetes-sources.md)）：
  - 先读取正式发行博客标题下正文；正文不能支撑判断时才搜索补充来源。
  - 补充来源仅允许同项 `kep.k8s.io/<id>`、KEP 仓库、`kubernetes.io/docs/` 或范围内固定 Tag 源码/CHANGELOG。
  - 禁止其他发布博客、第三方文章、聚合页、Issue/PR 评论。
  - 每个补充来源记入 `supplemental_sources`（`url`、`supports`、`reason`）。
- **退出**：Stable/Beta/Alpha 目录逐项进入分析，Spotlight 同名去重；弃用/移除项进入风险区。无关条目可排除但须记入 `catalog_omissions`。

## 阶段 3a：自动生成特性变更文本

```bash
python scripts/gen_analysis.py --run-dir <run-dir>
```

- **自动生成**（零 LLM token）：
  - 全部 `feature_changes` 的 `check_method`、`details`、`conclusion`、`recommendation`、`notes`，由 `GATE_CN` 和 `GATE_NAME_CN_FALLBACK` 字典中的预置中文内容生成。
  - 多特性版本分析条目的 `enhancement` 逐行展开。
  - 兼容行的兼容分析字段。
- **字典覆盖限制**：`GATE_CN`/`GATE_NAME_CN_FALLBACK` 仅覆盖约 120 个常用 FeatureGate。不在字典中的 gate，`details` 仅由 `gate_description`（英文源码注释）+ 阶段过渡模板生成，通常 40–80 字，**达不到 100 字要求**。这些条目虽标记 `status=ready`，但需阶段 4.5 扩写。
- **退出**：`feature_changes` 全部 `status=ready`；多特性条目 `enhancement` 非空。

## 阶段 3b：LLM 补写版本分析中文文本

- **输入**：`analysis.json`（3a 产出）、正式发行博客缓存。
- **范围**：全部 `status != ready` 的 `version_analysis` 条目（单特性条目 + 风险条目）。多特性条目和全部 `feature_changes` 已由 3a 处理。
- **流程**：
  1. 读取 `analysis.json`，按版本分组找出 `status != ready` 的条目。
  2. 每个版本：读取博客缓存 HTML，提取特性标题下正文段落。
  3. 每个条目：阅读英文博客正文，**用中文编写**各字段。具体字数和维度要求见上方[文本质量规范](#文本质量规范)。
  4. 写入 `analysis.json`，`status` 设为 `ready`。
- **质量自检**（写入前执行）：逐条对照[文本质量规范](#文本质量规范)的表格检查字数、维度和禁止项。
- **Token 效率**：按版本分批，不累积全量上下文。
- **退出**：版本分析覆盖 `release-catalog.json` 全部目录项；`catalog_id` 唯一；名称和 `primary_source` 与博客逐字一致；所有文本中文撰写。

## 阶段 4：定向精炼

```bash
python scripts/validate_analysis.py --run-dir <run-dir>
```

- **产物**：`validation.json`（含 severity/code/field/message 的定向诊断）。
- **流程**：先做事实复核，再做读者复核。按 `事实/来源 → 主体/版本 → 歧义/行动性 → 重复/长度/样式` 处理，同级再按 `error → warning → info`。每轮只加载失败项，最多 3 轮。
- **停止**：问题数不下降或连续两轮只改措辞时停止。
- **退出**：无事实冲突、错误版本、主体错配或缺失关键来源；关键文本无歧义、无重复。

## 阶段 4.5：文本质量复查与扩写

- **输入**：通过 `validate_analysis.py` 的 `analysis.json`。
- **范围**：对全部 `version_analysis` 和非兼容 `feature_changes` 逐项复查，定向扩写不足项。复查不是整表重写。
- **检查清单**：逐项对照[文本质量规范](#文本质量规范)表格。重点扩写：
  - 阶段 3a 中 `details` 不足 100 字的 gate（字典未覆盖项）。
  - `current_problem` < 150 字或 `enhancement` < 180 字的版本分析条目。
  - `value_analysis` 含泛化表述或 < 70 字的条目。
  - 风险条目 `value_analysis` 不符合三类格式的条目。
- **扩写原则**：只补充影响理解或决策的事实（受影响对象、旧行为、核心机制、关键 API/配置、适用条件）。禁止凑字空话、禁止跨特性复用模板。
- **退出**：全部字段满足[文本质量规范](#文本质量规范)；重新运行 `validate_analysis.py` 无新增 error。

## 阶段 5：构建复核

```bash
python scripts/build_report.py --run-dir <run-dir> --output <report.xlsx>
python scripts/verify_report.py <report.xlsx> --run-dir <run-dir>
```

- **退出**：Sheet 名称（`版本分析`+`特性变更`）、列、版本顺序、稀疏规则正确；特性变更行数 = 机器事实范围事件数；版本分析覆盖目录基线；长文本完整显示。样式只由 `build_report.py` 和 `assets/report-style.json` 管理。

## 阶段 6：打包交付与清理

```bash
python scripts/package_output.py --run-dir <run-dir> --report <verified-report.xlsx> --output-dir <output-dir>
```

交付结构：

```text
<output-dir>/
└── k8s-v<from>-v<to>/
    ├── <report>.xlsx
    └── data/
        ├── reference.md
        ├── <from-ref>/features.go
        └── <to-ref>/features.go
```

- `reference.md` 由 `source-index.json`、`analysis.json` 和 `release-catalog.json` 确定性生成，按核心发行博客、CHANGELOG、固定源码和来源说明分组；禁止手写或加入第三方 URL。
- 范围超过两个 minor 时，每个 `config.json.refs` 中的固定 ref 都建立同名子目录。预发布版本保留完整 ref（如 `v1.37.0-rc.0`）。
- **退出**：交付目录只含 XLSX 与 `data/`；`reference.md` 列出全部官方参考网址；每个 `features.go` 的 SHA-256 与 `source-index.json` 一致。完成后删除运行目录，除非用户要求保留。

---

## 中断恢复

不从头重跑。检查 `<run-dir>`，从最早未满足退出条件的阶段继续：

| `<run-dir>` 状态 | 恢复到 |
|---|---|
| 无 `config.json` | 阶段 0 |
| 无 `source-index.json` 或 `machine-facts.json` | 阶段 1（下载脚本复用缓存） |
| `analysis.json` 仍有无 `catalog_id` 的条目 | 阶段 2 |
| `feature_changes` 有 `status=research` | 阶段 3a |
| `version_analysis` 单特性条目 `current_problem` 或 `value_analysis` 为空 | 阶段 3b |
| `validation.json` 有需修订项 | 阶段 4 |
| 任一条目不满足[文本质量规范](#文本质量规范) | 阶段 4.5 |
| XLSX 不存在或验证失败 | 阶段 5 |
| XLSX 已验证但 `data/` 不完整 | 阶段 6 |

---

## 安装与迁移

要求 Python 3 标准库、网络和文件读写能力，无第三方包。命令中的 `python` 可由宿主替换为 `python3`。

1. 复制完整 `SKILL/` 文件夹，保持内部相对结构。不要只复制 `SKILL.md`。
2. 放入宿主 Skill 目录；宿主无 Skill 机制时在任务中指定此文件夹并读取 `SKILL.md`。
3. 首次部署运行迁移自检：

   ```bash
   python scripts/validate_skill.py .
   python scripts/self_test.py
   ```

跨产品迁移细节见 [references/portability.md](references/portability.md)。

---

## Token 纪律

- 按阶段路由读取 references，不预加载全部资料。
- 阶段 3a 由 `gen_analysis.py` 完成，零 LLM token。
- 阶段 3b/4.5 按版本/sheet 分批，不在上下文中累积全部条目。
- 不把源码、CHANGELOG 或网页全文放入上下文；只保留相关原子事实。
- 不重新研究或改写已通过字段；验证轮次只加载失败项。
- XLSX 由脚本构建，不在上下文中维护 OOXML 或样式代码。

---

## 完成定义

全部满足时完成：

- [ ] 固定来源及 SHA-256 完整。
- [ ] 发布博客目录全量覆盖或逐项说明排除理由。
- [ ] 目标 Tag 范围事件全部覆盖。
- [ ] 每个非空关键判断可追溯且无已知事实冲突。
- [ ] 全部文本字段满足[文本质量规范](#文本质量规范)。
- [ ] 最终 XLSX 通过 `verify_report.py` 计数与覆盖验证。
- [ ] 输出目录只含 XLSX 与 `data/`，`reference.md` 和每个固定 ref 的 `features.go` 均通过来源与哈希核验。
