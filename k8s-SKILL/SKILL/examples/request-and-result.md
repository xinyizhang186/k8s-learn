# 示例请求与结果形态

## 请求

```text
分析 Kubernetes v1.35 到 v1.36，生成版本分析和特性变更双 Sheet XLSX。重点说明默认开启变化、GA 特性、弃用风险和升级排查方法。
```

## 正确过程

1. 用 `v1.35.0`、`v1.36.0` 固定 tag 下载源码和 CHANGELOG。
2. 从目标 tag 的完整版本化规格提取 `[1.35,1.36]` 范围事件，不从发布博客猜默认值。
3. 提取两版发布博客的 Stable/Beta/Alpha 目录，逐项进入版本分析；同名 Spotlight 去重。
4. 把弃用、移除与升级阻断项写入风险区，为每项匹配官方 KEP/文档并形成原子事实。
5. 写一轮草稿，验证目录覆盖、机器事实行数和文本质量，只修改被指出字段。
6. 达到停止条件后构建 XLSX，并用运行目录做计数与覆盖复核。
7. 用 `package_output.py` 生成 `output/<report>.xlsx`、`output/data/reference.md` 和各固定 ref 的 `features.go`，核对源码哈希后再删除运行目录。

## 正确交付形态

```text
output/
├── k8s-v1.35-v1.36.xlsx
└── data/
    ├── reference.md
    ├── v1.35.0/features.go
    └── v1.36.0/features.go
```

## 正确文本形态

```text
功能介绍：该特性让 API Server 直接执行基于 CEL 的声明式变更策略，减少对外部 mutating webhook 服务的依赖。策略与绑定资源分离，便于复用和控制生效范围。

价值分析：适合希望降低 webhook 网络依赖和运维复杂度的集群。迁移前仍需验证 CEL 表达式、匹配条件和失败策略，不能把 GA 简化为“无需测试”。

排查方法：检查集群中的 MutatingAdmissionPolicy 与 MutatingAdmissionPolicyBinding，确认绑定目标、CEL 表达式和 failurePolicy；在升级前用代表性请求验证变更结果，并对照 API Server 审计日志排查拒绝或变更异常。
```

## 错误文本形态

```text
Kubernetes 以前不支持该能力，新版本全面提升了稳定性和效率，建议立即开启。
```

错误原因：没有主体、机制、影响对象、采用条件和证据；“全面提升”“立即开启”无法由阶段变化证明。
