# Kubernetes 版本分析参考资料

> 报告：**k8s-v1.37-v1.37.xlsx**  
> 范围：**v1.37 → v1.37**  
> 版本分析以对应版本的正式发行博客为主体；仅在博客信息不足时补充同项 KEP、官方文档或固定 Tag 资料。

## 核心发行博客

- **Kubernetes v1.37**：[正式发行博客](https://kubernetes.io/blog/2026/07/31/kubernetes-v1-37-sneak-peek/)

这些页面决定“版本分析”的条目名称、版本归属和主体叙述。

## 版本 CHANGELOG

- [Kubernetes v1.37 CHANGELOG](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.37.0-rc.0/CHANGELOG/CHANGELOG-1.37.md)

## 固定 Tag 源码

### Kubernetes v1.37 · `v1.37.0-rc.0`

- [在线查看 `pkg/features/kube_features.go`](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.37.0-rc.0/pkg/features/kube_features.go)
- [打开本地副本](./v1.37.0-rc.0/features.go)

<details>
<summary>校验信息</summary>

- SHA-256：`7f2c61046c31b81a5555499440589b576e74a8af4e6daed803e7335f8d8e249c`
- 本地路径：`./v1.37.0-rc.0/features.go`

</details>

## 来源说明

- FeatureGate 阶段、默认值和锁定状态只以固定 Tag 源码为准。
- 搜索结果仅用于发现候选页面，不作为事实来源。
- 不收录第三方博客、聚合页或人工样表。
