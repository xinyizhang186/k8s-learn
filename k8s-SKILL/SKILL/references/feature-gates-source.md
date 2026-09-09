# `kube_features.go` 专业知识

## 权威边界

`pkg/features/kube_features.go` 中的版本化规格是 Kubernetes 核心 FeatureGate 状态的首要来源。主要结构通常包含：

```go
const (
    ExampleGate featuregate.Feature = "ExampleGate"
)

var defaultVersionedKubernetesFeatureGates = map[featuregate.Feature]featuregate.VersionedSpecs{
    ExampleGate: {
        {Version: version.MustParse("1.34"), Default: false, PreRelease: featuregate.Alpha},
        {Version: version.MustParse("1.36"), Default: true, PreRelease: featuregate.Beta},
    },
}
```

有效状态是目标 minor 版本之前或等于目标版本的最后一条规格。不能只比较文件末行，也不能把历史规格误认为当期变化。

## 字段语义

- `PreRelease`: `Alpha`、`Beta`、`GA`、`Deprecated` 等生命周期阶段。
- `Default`: 未显式配置时的默认开关值。
- `LockToDefault`: 为 `true` 时用户不能通过普通 FeatureGate 配置改变默认值。
- Go 标识符不一定等于用户配置字符串。展示名称应采用 `featuregate.Feature` 的字符串值。
- `genericfeatures.Foo` 等带包名前缀的 map key，应解析最后标识符并映射到字符串值。

## 两种事实口径

`特性变更` 主表使用**目标 tag 的范围事件口径**：解析目标版本固定 tag 的完整 `defaultVersionedKubernetesFeatureGates` 历史，只要某项存在版本号落在 `[from, to]`（含两端）的规格，就纳入一行。这样同时包含起始版本与目标版本事件，并避免旧 tag 与目标 tag 的历史记录不一致造成漏项。

- `Added`：该门控第一条规格落在范围内。
- `Deprecated`：范围内任一规格进入 `Deprecated`。
- `Changed`：范围内有规格记录，但不属于以上两类。
- 阶段、默认值：范围前最后状态到范围内最后状态的净变化；相同则写 `->值`。
- 锁定：范围内显式出现 `LockToDefault` 时记录 `->true/false`；未显式出现则留空。

同时生成**跨 tag 有效状态审计**，用于发现回填、撤回和已毕业门控清理，但不直接作为主表行。两种口径有差异时保留审计记录，不用端点差分替换范围事件账本。

一项特性即使同一范围内有多次规格变化，也只生成一行，并在机器事实中保留逐版本 `version_changes`。

## 兼容性推理边界

源码可直接证明状态变化，不能单独证明业务影响。兼容性结论需结合官方文档：

- 默认 `false -> true`：检查是否会启用新行为、API 或控制器路径。
- 阶段 `Beta -> GA`：通常表示成熟，但不自动等于“无升级风险”。
- `LockToDefault false -> true`：检查旧配置是否仍尝试显式关闭/开启。
- 移除或 `Deprecated`：检查启动参数、组件配置和依赖 API。

不要把 FeatureGate 名称机械翻译成中文。不要由阶段名称推测发布日期、KEP 编号或实现细节。

## 解析异常

当脚本无法解析时：

1. 保留原始固定 tag 文件和哈希。
2. 检查变量名、map 类型或 Go 语法是否发生结构变化。
3. 只扩展解析脚本，不使用正则搜索结果手工填充机器事实。
4. 添加最小匿名片段到本地测试，避免把完整上游文件固化进 Skill。
