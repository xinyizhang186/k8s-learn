# AutoK8s 项目核心逻辑

> 统一入口：`generate.py`（调用 `autok8s.cli.main`），根据参数自适应选择分析模式。

---

## 1. 版本分析流水线（`autok8s.version_analysis`）

从发布博客抓取特性与弃用项，逐句分类后提取痛点、构建增强句，经正则+机翻回退生成价值分析，通过质量门校验后写出"版本分析"Sheet。

### 1.1 流程

```
博客 URL
  │
  ▼ fetcher.fetch_release_blog（含重试）
抓取博客 HTML → 提取特性列表与弃用项
  │
  ▼ content_gen.generate_analysis（核心）
逐句分类（feature/pain/benefit/stage/background/noise）
  → 提取痛点（现状）→ 构建增强句（本特性增强）→ 生成价值分析
  │
  ▼ quality.py 质量门校验
不可信段落会被清空
  │
  ▼ xlsx_writer.write_workbook
写出 "版本分析" Sheet（"现状："/"本特性增强：" 标签加粗）
```

### 1.2 关键算法（`content_gen.py`）

- **句子分类**（`_classify_sentence`）：优先级 noise > stage > feature > benefit > pain > background > other
- **痛点提取**（`_extract_pain_point`）：pain 句 > background 句 > other 句；无则从 feature 句反推（"此前无法…"/"此前缺乏…"）
- **增强句构建**（`_build_enhancement`）：格式 `v{ver} 将 {name} 升级为 {stage}，{behavior}`
- **阶段冗余清洗**（`_clean_stage_redundancy`）：正则移除重复的阶段声明

### 1.3 质量门校验（`quality.py`）

博客回退路径必须通过 `verify_content` / `_verify_deprecation` 校验，未通过则读者字段留空：

- **痛点**：≥ 14 字，含问题词，非模板前缀
- **增强句**：≥ 20 字，无多余历史陈述，非泛化表述
- **价值分析**：≥ 14 字，含收益词，非功能描述/痛点陈述/背景历史
- **中文占比**：三段拼接后 ≥ 20%

---

## 2. 特性变更流水线（`autok8s.feature_changes`）

解析 `kube_features.go` 对比版本区间内 Feature Gate 的阶段与默认值变化，按三级取证链路补齐排查方法与详细说明，生成"特性变更"Sheet。

### 2.1 流程

```
kube_features.go + 版本范围
  │
  ▼ parser.parse
解析 Go 文件，提取 Feature Gate 名称/阶段/默认值/prelock
  │
  ▼ analyzer.analyze
推导变更类型：Added / Changed / Deprecated
  │
  ▼ research / fetcher 三级取证
1. pkg.go.dev 包文档（特性键+描述+KEP 链接）
2. KEP 提案仓库（README 摘要）
3. CHANGELOG-<版本>.md（仅当包文档无该特性时回退）
  │
  ▼ narrative.finalise_narrative
翻译为中文，生成排查方法/详细说明/兼容分析
  │
  ▼ xlsx_writer
写出 "特性变更" Sheet（14 列）；--audit 另写出核查 JSON
```

### 2.2 兼容性判定

- 默认值变化或行为变更 → 不兼容（需排查）
- 开关状态不变或默认关闭 → 兼容
- "兼容分析"列有内容时，后续列全部留空

### 2.3 资料查找容错（`content_store.lookup`）

`collect_feature_evidence` 抓取在线资料抛异常时（网络超时/解析失败），安全降级返回已收集的部分字段，不崩溃。

---

## 3. 双 Sheet 合并（`autok8s.workbook`）

同时传入 `--blog` 和 `--go-file` 时，将两条流水线结果合并到同一 xlsx 的两个工作表。`_copy_worksheet` 保留 `CellRichText` 富文本（"现状："/"本特性增强："加粗不丢失）。

---

## 4. 自适应入口（`autok8s.cli`）

```
仅 --blog URL              → 版本分析（单 Sheet）
仅 --go-file + --range     → 特性变更（单 Sheet）
两者都给                   → 双 Sheet 合并
都不给                     → 报错退出
```

参数校验：`main()` 解析参数 → 校验 `--go-file` 与 `--range` 互为依赖 → 校验版本范围下界 ≤ 上界 → 博客模式下逐个抓取校验（任一失败立即报错）→ 分发到对应运行函数。

输出路径：默认 `output/v{版本}/`，`--output` 可自定义。

---

## 5. 数据流

```
kube_features.go（权威源）
    ├──→ feature_changes 流水线 → 特性变更 xlsx
    │         ↑ 回退: CHANGELOG-*.md / pkg-features.html
    └──→ --audit 写出 feature-change-audit-*.json（逐条核查）

博客 URL（在线）
    └──→ version_analysis 流水线 → 版本分析 xlsx
              ↑ 正则+机翻回退
```

- **权威源优先**：`kube_features.go` 是阶段/默认值/移除的 100% 权威定义
- **三级回退**：pkg.go.dev 文档 → KEP 仓库 → CHANGELOG
- **核查留痕**：`--audit` 写出逐条核查 JSON

---

## 6. 初步 xlsx 文本优化流水线（按 `Prompt.md`）

`generate.py` 生成的初步 xlsx 中，机器列准确但文本列走正则+机翻回退，存在 6 类失效：机翻错字截断、特性名被机翻破坏、"现状"非痛点、价值分析缺失/为功能描述、KEP 配错、KEP README 模板噪声泄漏。

优化流水线**只替换文本列**，机器列原样保留，分四阶段执行：

### 6.1 流程

```
初步 xlsx
  │
  ▼ 阶段 A：提取待优化行
抽出"兼容分析"为空的特性变更行 + 版本分析全部特性/弃用行
  │
  ▼ 阶段 B：证据采集（并行，5-8 个 agent，每批 6-10 特性）
websearch 语义搜索 → 命中正确 KEP 编号 + URL
webfetch 抓 KEP README → 提取 Motivation/Proposal/Design 段，剥模板噪声
  │
  ▼ 阶段 C：文本生成（证据驱动，不再联网）
版本分析行：{特性功能介绍, 特性功能价值分析}
特性变更行：{分析结论, 排查方法, 参考资料, 详细说明, 补充说明}
  │
  ▼ 阶段 D：校验 + 写回 optimized.xlsx
六项硬约束校验 → 不过则留空绝不编造 → 保留机器列，仅替换文本列
```

### 6.2 文本来源优先级

| 来源 | 覆盖范围 | 用法 |
|------|---------|------|
| **参考文件** `AI_agent/k8sv1.35-v1.36.xlsx` | v1.35-v1.36 已人工复核 | 模糊匹配特性名，直接合并 |
| **预生成文本** | 参考文件未覆盖的版本（v1.33/v1.34） | 用 `fetcher` 抓官方中文博客描述生成 |
| **websearch 现场生成** | 参考文件和博客均未覆盖的新特性 | `websearch` + `webfetch` 采集证据后生成 |

### 6.3 字段规范

**版本分析**（特性功能介绍 + 特性功能价值分析）：

| 字段 | 格式 | 硬约束 |
|------|------|--------|
| 特性功能介绍 | `现状：<痛点>\n本特性增强：v<X.Y> 将 <特性名> 升级为 <阶段>，<行为>` | 现状是真痛点；增强含版本号+阶段+行为 |
| 特性功能价值分析 | 一句话收益概括 | 是收益（提升/降低/简化…），非功能描述 |

**特性变更**（排查方法 + 参考资料 + 详细说明）：

| 字段 | 硬约束 |
|------|--------|
| 排查方法 | 含检查动词 + 针对该特性具体对象，非通用模板 |
| 参考资料 | `http://kep.k8s.io/<NNNN>`；有详细说明必有参考资料 |
| 详细说明 | 该特性"做什么+影响什么"；非排查方法复述；无模板噪声 |

### 6.4 六项硬约束校验

1. **现状是痛点**：含"此前/无法/难以/缺乏…"等痛点词
2. **增强含版本+阶段**：含 `v1.\d+` + `GA/Beta/Alpha`
3. **价值是收益非功能**：无"该特性使…/公关/租赁/吊舱"等机翻腔
4. **排查方法非通用模板**：含检查动词且针对具体对象
5. **有详细说明必有参考资料**：KEP 为 null 时详细说明留空
6. **无机翻腔/模板噪声**：无"公关"=PR、"租赁"=Lease、"命名您的PR"、`<!--` 等

### 6.5 关键设计

- **机器列不动**：机器列已由 autok8s 准确生成，原样保留
- **证据先于生成**：每条文本生成前必须有 websearch + webfetch 的可引用 URL
- **生成后即校验**：六项硬约束不过则留空，绝不编造
- **富文本保留**：写回时重新应用 `_make_rich_text`，保持标签加粗
