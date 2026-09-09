# Kubernetes 官方来源与治理

## 来源优先级

1. 固定 tag 的 Kubernetes 源码：FeatureGate 阶段、默认值、锁定状态。
2. `kubernetes.io/blog/` 发布博客：版本重点、用户场景、毕业状态。
3. `github.com/kubernetes/enhancements/.../keps/`：动机、设计、毕业条件、风险。
4. `kubernetes.io/docs/`：当前使用方式、配置入口、排查步骤。
5. 固定 tag 的 `CHANGELOG/CHANGELOG-1.xx.md`：发布项、弃用和变更补充。

不要用第三方博客、搜索摘要或生成文本确认事实。第三方内容最多用于发现官方页面。

## 固定源码

使用完整 tag，例如 `v1.36.0`：

- `https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.0/pkg/features/kube_features.go`
- `https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.0/CHANGELOG/CHANGELOG-1.36.md`

记录 URL、抓取时间和 SHA-256。不要用 `master` 分析已发布版本。预发布分析必须在报告中显示完整 ref，例如 `v1.37.0-beta.0`。

## 发布博客

只接受 `https://kubernetes.io/blog/...`。搜索时使用：

```text
site:kubernetes.io/blog Kubernetes v1.xx release <FeatureName>
```

博客负责回答“本版本为何值得关注”，源码负责回答“FeatureGate 状态到底如何”。二者冲突时，不自行调和：保留源码机器事实，并把博客差异列为待核实。

### 版本分析主体来源

- 每个 `版本分析` 条目的 `primary_source` 必须是 `release-catalog.json` 中该条目的 `source`，即对应版本正式发行博客。
- 先读取该条目标题下的正文，主体叙述不得由其他博客或搜索结果替代。
- 若正文足以支撑问题、机制、边界和价值判断，不再搜索其他页面。
- 若正文存在明确缺口，才补充同项 KEP、`kubernetes.io/docs/` 或范围内固定 Tag 源码/CHANGELOG；不得使用其他发布博客、第三方文章、聚合页、Issue/PR 评论。
- 每个补充来源写入 `supplemental_sources`：`url`、`supports`、`reason`。`supports` 只允许 `current_problem`、`enhancement`、`value_analysis`、`feature_summary`。

## KEP

优先使用：

- `https://kep.k8s.io/<number>`
- `https://github.com/kubernetes/enhancements/tree/master/keps/<sig>/<number>-<slug>`

提取 `Summary`、`Motivation`、`Proposal`、`Risks and Mitigations`、`Graduation Criteria`。忽略 HTML 注释、PR 模板、占位文字和实现清单噪声。

不得只按相似关键词猜 KEP。至少满足一项：源码注释直接给出 KEP；官方博客/文档直接链接；KEP 路径和特性名称、SIG、行为同时一致。

## 证据记录

每项只保存支撑最终文本所需的最小事实：

```json
{
  "claim": "该能力将某阶段从 Beta 提升为 GA",
  "source_url": "https://kubernetes.io/blog/...",
  "source_type": "release_blog",
  "locator": "Feature heading or section name"
}
```

同一 URL 在一次运行中只抓取一次。优先按页面标题或章节定位，不复制大段原文。

## 交付证据包

- 使用 `scripts/package_output.py` 从缓存和索引确定性生成，不要手工整理。
- `data/reference.md` 收录 `source-index.json` 中全部官方输入，以及 `analysis.json`、`release-catalog.json` 实际引用但未缓存的官方 URL；页面按来源角色分组，不使用包含长 URL 与 SHA-256 的宽表格。
- 每个 `config.json.refs` 中的固定 ref 都输出为 `data/<ref>/features.go`；文件内容必须与该 ref 的 `pkg/features/kube_features.go` 缓存逐字一致。
- `reference.md` 记录固定源码 URL、SHA-256 和相对文件路径；不得加入搜索结果页、第三方文章或人工样表路径。

## 清晰治理

- 机器事实归 `machine-facts.json` 管理，写作阶段只读。
- 研究事实和 URL 归 `analysis.json` 管理。
- 抓取元数据归 `source-index.json` 管理。
- 验证结果归 `validation.json` 管理。
- 不在 XLSX 中隐藏来源冲突；使用“待核实”明确暴露不确定性。
