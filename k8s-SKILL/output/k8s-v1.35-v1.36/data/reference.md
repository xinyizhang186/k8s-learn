# Kubernetes 版本分析参考资料

> 报告：**k8s-v1.35-v1.36.xlsx**  
> 范围：**v1.35 → v1.36**  
> 版本分析以对应版本的正式发行博客为主体；仅在博客信息不足时补充同项 KEP、官方文档或固定 Tag 资料。

## 核心发行博客

- **Kubernetes v1.35**：[正式发行博客](https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/)
- **Kubernetes v1.36**：[正式发行博客](https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/)

这些页面决定“版本分析”的条目名称、版本归属和主体叙述。

## 版本 CHANGELOG

- [Kubernetes v1.35 CHANGELOG](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.35.0/CHANGELOG/CHANGELOG-1.35.md)
- [Kubernetes v1.36 CHANGELOG](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.0/CHANGELOG/CHANGELOG-1.36.md)

## 固定 Tag 源码

### Kubernetes v1.35 · `v1.35.0`

- [在线查看 `pkg/features/kube_features.go`](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.35.0/pkg/features/kube_features.go)
- [打开本地副本](./v1.35.0/features.go)

<details>
<summary>校验信息</summary>

- SHA-256：`705a7ece25d3daee77e1af969d10c4014e76851c0ca0e8cf4720e96398eaef40`
- 本地路径：`./v1.35.0/features.go`

</details>

### Kubernetes v1.36 · `v1.36.0`

- [在线查看 `pkg/features/kube_features.go`](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.0/pkg/features/kube_features.go)
- [打开本地副本](./v1.36.0/features.go)

<details>
<summary>校验信息</summary>

- SHA-256：`c170e0e53e485674820e0a6e54feba77e5bc74b66365ec20a2a245157084e639`
- 本地路径：`./v1.36.0/features.go`

</details>

## 来源说明

- FeatureGate 阶段、默认值和锁定状态只以固定 Tag 源码为准。
- 搜索结果仅用于发现候选页面，不作为事实来源。
- 不收录第三方博客、聚合页或人工样表。
