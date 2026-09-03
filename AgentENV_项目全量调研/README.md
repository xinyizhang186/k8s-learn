# AgentENV 项目全量调研：阅读导航与资料索引

> 调研日期：2026-08-31  
> 范围：AgentENV 官方 `latest` 文档、GitHub `kvcache-ai/AgentENV` 主仓库与 Releases。  
> 版本提示：当前 GitHub 最新 tagged release 为 `v0.1.2`；`main` 分支 Rust workspace 已为 `0.1.3`。`latest/main` 中的内容不一定全部包含在 v0.1.2 二进制发布中。

## 一句话定位

**AgentENV（AENV）是面向 AI Agent 的自托管 Sandbox Runtime / 分布式沙箱平台。**

每个 Sandbox 运行在独立的 **Firecracker microVM** 中，底层利用 **OverlayBD + ublk + Snapshot** 实现 OCI 镜像按需加载、快速启动/恢复、增量快照与 Fork，并对外提供 **E2B-compatible API**。官方仓库同时说明该项目用于支撑 Kimi K3 的 agentic RL training 场景。

## 文件目录

1. `01_项目概览与核心能力.md`
2. `02_系统架构与核心组件.md`
3. `03_安装部署与硬件要求.md`
4. `04_Template_Sandbox_Snapshot生命周期.md`
5. `05_aenv_CLI使用手册.md`
6. `06_HTTP_API_E2B与Sandbox_Proxy.md`
7. `07_认证_网络策略与安全边界.md`
8. `08_存储_OverlayBD_ublk与按需加载.md`
9. `09_分布式控制面_调度_Redis与P2P.md`
10. `10_配置文件与环境变量.md`
11. `11_源码目录_模块职责与关键依赖.md`
12. `12_测试_持久化_可观测性与故障排查.md`
13. `13_Custom_Extension扩展机制.md`
14. `14_版本_性能_限制与生产风险.md`
15. `15_快速上手_学习路线与面试要点.md`
16. `16_官方资料来源.md`

## 核心技术关键词

```text
AI Agent Sandbox
Firecracker microVM
KVM / PVM
OverlayBD
ublk
OCI Image / On-demand Image Loading
Snapshot / Incremental Snapshot / Fork
envd
E2B Compatible API
Axum / Rust
Go Gateway / Scheduler
Redis Binding Store
Kubernetes DaemonSet
P2P Artifact Transport
iroh / iroh-blobs
Network Namespace
Sandbox Proxy
Custom Extension
```

## 官方入口

- Docs：https://kvcache-ai.github.io/AgentENV/latest/
- GitHub：https://github.com/kvcache-ai/AgentENV
- Releases：https://github.com/kvcache-ai/AgentENV/releases
- README：https://github.com/kvcache-ai/AgentENV/blob/main/README.md
- 默认配置：https://github.com/kvcache-ai/AgentENV/blob/main/config/default.toml
- Rust Workspace：https://github.com/kvcache-ai/AgentENV/blob/main/Cargo.toml
- Go Services：https://github.com/kvcache-ai/AgentENV/tree/main/services

## 建议阅读路线

- 了解项目：01 → 02
- 自己部署：03 → 05 → 10 → 12
- 接入 Agent/E2B：04 → 06 → 07
- 研究 Infra：08 → 09 → 11
- 秋招/面试：01 → 02 → 08 → 09 → 15
- 生产评估：03 → 07 → 10 → 12 → 14

“全量”在这里指对当前公开官方文档和主仓库中与使用、架构、部署、存储、网络、安全、API/CLI、扩展、测试和源码相关的信息进行结构化覆盖，而不是逐行复制整个源码。
