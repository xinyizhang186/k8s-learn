# CubeSandbox 学习路线与内容清单

> 本文基于仓库 `CubeSandbox-0.6.0/CubeSandbox-0.6.0/` 实际代码与自带文档(VitePress,中英双语)梳理。
> 目标:从零到能改代码、能贡献 PR。
> 项目是腾讯云开源的 AI agent 沙箱服务(Apache 2.0),基于 RustVMM + KVM,E2B 兼容,亚 60ms 冷启,< 5MB 内存开销。

---

## 总览:CubeSandbox 是什么

一句话:**用 KVM MicroVM 给 AI agent 提供硬件级隔离的毫秒级沙箱**,控制面 Go + 数据面 Rust + eBPF,对外 E2B SDK 兼容(换一个 URL 环境变量就能从 E2B Cloud 迁移)。

核心卖点(来自 README):
- 冷启 < 60ms(单并发;50 并发 P99 < 137ms)
- 单沙箱内存开销 < 5MB,单机可跑数千沙箱
- 每沙箱独立 Guest 内核(KVM),不是 Docker 共享内核
- CubeCoW 用 `FICLONE`/xfs-reflink 实现 O(1) 快照/克隆/回滚(百毫秒粒度)
- CubeVS 用 eBPF 内核态网络隔离(无 iptables/网桥)
- CubeEgress L7 出口代理:域名白名单 + 凭证注入 + 审计
- K8s 原生部署 + Terraform 一键 + ARM64 全栈

---

## 前置知识自检(阶段 0)

CubeSandbox 是混合栈,**前置知识面比 AgentENV 宽**。按子系统分组:

| 子系统 | 需要的语言/技术 | 补资料 |
|---|---|---|
| **控制面**(CubeAPI/Master/let/Proxy/Egress) | **Go** + gRPC + Redis | Tour of Go、gRPC 官方教程、Redis 文档 |
| **数据面 Rust**(CubeShim/hypervisor/agent/cubecow) | **Rust** + async + tokio + RustVMM crates | The Rust Book、RustVMM 文档 |
| **网络**(CubeVS) | **eBPF/XDP** + TC(traffic control)+ BPF maps + LPM trie | bpftrace 教程、Cilium eBPF 文档、`man tc` |
| **虚拟化**(hypervisor) | **KVM API** + virtio(block/net/vsock/fs)+ seccomp | KVM API 文档、RustVMM vm-* crates |
| **容器运行时**(CubeShim) | **containerd Shim v2** + ttrpc + OCI | containerd 设计文档、Shim v2 spec |
| **存储**(cubecow) | **XFS reflink** + `FICLONE`/`ioctl` + 块设备 | XFS reflink 文档 |
| **前端**(web) | **Vue** + VitePress(文档站) | Vue 3 文档、VitePress 文档 |
| **通用** | Linux、Docker、Make、protoc | — |

> 最低门槛:能读 Go + Rust;理解 KVM、containerd、eBPF 是什么。其他可在学中补。

---

## 阶段 1:概念建立(先懂"是什么")

**目标**:画出架构图,说清"一次 `POST /sandboxes` 经过了哪些组件"。

读 `docs/`(VitePress,中英双语,英文优先):

1. `docs/index.md` — 文档首页(9 个特性卡片)
2. `docs/guide/introduction.md` — 简介
3. `docs/architecture/overview.md` — ⭐⭐⭐ **最重要一篇**,含 mermaid 架构图 + 请求时序图 + 设计原则
4. `docs/architecture/network.md` — ⭐⭐ CubeVS eBPF 网络深度(340 行,含 11 节)

### 六大核心组件(必须记牢)

| 组件 | 语言 | 职责 |
|---|---|---|
| **CubeAPI** | Rust(Axum) | E2B 兼容 REST 网关,翻译 SDK 调用为内部 gRPC |
| **CubeMaster** | Go | 集群调度器,选节点、派活给 Cubelet、发生命周期事件到 Redis |
| **CubeProxy** | Go(OpenResty+Lua) | 反向代理,按 host/path 路由到沙箱,配合 cube-lifecycle-manager 做 auto-pause/resume |
| **Cubelet** | Go | 节点本地 agent,管本机所有沙箱全生命周期 |
| **CubeShim** | Rust | containerd Shim v2 实现,桥接容器运行时与 KVM MicroVM |
| **CubeHypervisor** | Rust(RustVMM) | VMM,管 vCPU/内存/virtio 设备/启动/快照/恢复,seccomp 加固 |

数据面三件套(节点本地):

| 组件 | 技术 | 职责 |
|---|---|---|
| **CubeVS** | eBPF(Go 控制面) | 内核态网络:SNAT/DNAT + 连接跟踪 + LPM 策略 + ARP 代理 |
| **CubeCoW** | Rust(`FICLONE`) | O(1) 快照/克隆存储引擎,只持久化脏内存页 |
| **CubeEgress** | OpenResty+Lua | L7 出口代理:域名过滤 + 凭证注入 + 审计 |

### 控制面 vs 数据面(关键区分)

- **控制面(无状态)**:CubeAPI + CubeMaster + WebUI + Redis(Redis 是唯一真相源)→ 任意实例可服务任意请求,水平扩容简单
- **数据面(节点本地)**:Cubelet + CubeShim + CubeHypervisor + CubeVS + CubeEgress + CubeCoW → 管本机驻留沙箱

### 检验

- `Sandbox.create()` 的请求时序图能默画出来吗?(见 overview.md 的 sequenceDiagram)
- 为什么控制面无状态?(Redis 存元数据 + 生命周期事件流)
- CubeCoW 快照为什么是 O(1)?(FICLONE 共享 extent,不拷字节)

---

## 阶段 2:跑起来(用起来)

**目标**:本机或云上跑通一个沙箱,用 WebUI 走一遍生命周期。

读 + 动手(`docs/guide/`):

1. `docs/guide/quickstart.md` — ⭐ 四步:装机→装 Cube→建模板→跑第一个 agent
2. 部署路径三选一(README 推荐顺序):
   - `docs/guide/pvm-deploy.md` — ⭐ PVM 云 VM(无需裸金属/嵌套虚拟化,**推荐**)
   - `docs/guide/bare-metal-deploy.md` — 裸金属
   - `docs/guide/dev-environment.md` — QEMU VM 开发环境(性能差,不推荐生产)
3. `docs/guide/webui.md` — ⭐ 装完打开 `http://<IP>:12088`,三步:Overview 看节点→Template Store 装预设→建沙箱看日志

### 动手清单

```bash
# 一键部署后
xdg-open http://<control-node-IP>:12088   # 或浏览器打开

# WebUI 三步
# 1. Overview:确认节点 Ready + 容量健康
# 2. Template Store:装一个官方预设(或已有 READY 模板则跳过)
# 3. Sandboxes → + New Sandbox:挑 READY 模板,秒级出沙箱 + 实时日志

# E2B SDK 兼容:换一个环境变量即可迁移
# 把 E2B_API_URL 指向 CubeAPI,Python/Node/Go SDK 零代码改动
```

### 检验

- 能说出 template 三步生命周期(OCI 镜像→Buildkit→rootfs+冷启内存快照→注册为模板)
- 沙箱 boot 为什么快?(CubeCoW clone template 的 rootfs+内存卷 O(1),CubeShim 从内存快照 restore)

---

## 阶段 3:部署(多形态)

**目标**:理解单机→多机→K8s→Terraform 的部署矩阵。

读 `docs/guide/`:

1. `self-build-deploy.md` — 从源码单机部署
2. `multi-node-deploy.md` — ⭐ 多节点集群
3. `kubernetes/` — ⭐⭐ v0.6 K8s 原生部署(CRD/operator/DaemonSet)
4. `tencentcloud-terraform-deploy.md` — ⭐ Terraform 一键腾讯云生产集群
5. `connect-existing-cluster.md` — 接入已有集群
6. `pvm-deploy.md` — PVM(非裸金属云 VM)

部署形态对照:

| 形态 | 适用 | 关键组件 |
|---|---|---|
| 单机 PVM | 试玩/开发 | CubeAPI+Master+let+全数据面 同机 |
| 多节点 | 小规模生产 | 控制面集中 + 数据面分布式 |
| K8s | 生产可扩 | CRD+operator,数据面 DaemonSet |
| Terraform | 云上一键 | 腾讯云资源编排 |

### 检验

- K8s 里数据面为什么是 DaemonSet?(每台主机一个,要 `/dev/kvm` + 网络 + 存储)
- Terraform 和 K8s 部署的关系?(Terraform 编排云资源,可在其上跑 K8s 部署)

---

## 阶段 4:配置与安全

**目标**:会改配置、懂六层安全模型。

读 `docs/guide/`:

1. `authentication.md` — 认证(CubeAPI 可插拔 auth 回调)
2. `security-proxy.md` — ⭐⭐ CubeEgress 域名过滤 + 凭证注入 + 审计
3. `network-policy.md` — ⭐ 每沙箱 CIDR/domain 策略
4. `route-aware-egress.md` — v0.5 策略路由出口
5. `network-hardening.md` — 网络加固
6. `node-isolation.md` — 节点隔离
7. `restrict-public-access.md` — 限制公网访问
8. `https-and-domain.md` — HTTPS + 域名(含 path-based 路由场景)
9. `persistent-storage.md` + `volume-plugin.md` — ⭐ v0.6 Volume 框架(E2B 兼容,可插后端)

### 六层安全模型(overview.md §Security)

1. **硬件隔离** — KVM MicroVM + 独立内核
2. **网络隔离** — CubeVS 默认拒私网/链路本地段
3. **出口控制** — CubeEgress L7 域名白名单
4. **凭证保险库** — header 重写注入,密钥不进沙箱/model context
5. **Seccomp** — CubeHypervisor 最小 syscall 白名单
6. **认证** — CubeAPI 可插拔 auth 回调

### 检验

- 凭证怎么不进沙箱?(CubeEgress 透明 MITM,append `Authorization`,沙箱模板预置 CubeEgress 根 CA)
- domain 策略怎么处理 CDN 动态 IP?(DNS 拦截学习:query 记录→response 提 A 记录→插 `allow_out_v2` 带 TTL 过期)

---

## 阶段 5:架构深入(原理层)

**目标**:读懂内部设计。这是从"会用"到"能改"的关键。

### 必读(overview + network 已在阶段 1 读过,这里深挖)

1. `docs/architecture/overview.md` — ⭐⭐⭐ 总览 + 设计原则 + 时序图
2. `docs/architecture/network.md` — ⭐⭐⭐ CubeVS 11 节深度(架构/流量/会话/NAT/策略/端口映射/TAP 生命周期/ARP)

### 深度博客(`docs/blog/posts/`,14 篇,按主题读)

| 主题 | 博客 |
|---|---|
| **性能基准** | `2026-06-01-cubesandbox-perf-benchmark`(裸金属)、`2026-06-03-cubesandbox-perf-benchmark-pvm`(PVM) |
| **网络深度** | `2026-06-23-cubesandbox-network-deep-dive` |
| **快照/克隆/回滚** | `2026-06-25-cubesandbox-snapshot-clone-rollback-deep-dive`、`2026-06-03-cubesandbox-v0.3.0-snapshot` |
| **agent 友好服务** | `2026-06-17-cubesandbox-agent-friendly-service` |
| **PVM** | `2026-05-22-cube-pvm-on-opencloudos9`、`2026-05-17-aws-nested-virt-cube-deploy` |
| **ARM64** | `2026-07-08-cubesandbox-arm-support` |
| **理念** | `2026-05-22-from-serverless-to-agent`、`2026-05-15-welcome` |
| **版本发布** | `v0.2.2` / `v0.4.0` / `v0.5.0` release |

### 核心数据流(必须能画出来)

**控制面请求时序**(overview.md 的 sequenceDiagram):
```
Client → POST /sandboxes → CubeAPI → gRPC CreateSandbox → CubeMaster
  → 选节点 → gRPC RunCubeSandbox → Cubelet
  → CubeCoW clone template rootfs → containerd Shim v2 Create+Start
  → CubeShim → launch_vmm/create_vm/restore_vm → CubeHypervisor → VM ready(vsock)
  → Cubelet AddTAPDevice + AttachFilter(CubeVS)
  → CubeMaster 发生命周期事件到 Redis → CubeAPI → 201 {sandbox_id}
```

**存储层**(overview.md §Storage):
```
Template(只读基线)
  └── FICLONE ──→ 沙箱 rootfs 卷(CoW)
                    ├── FICLONE ──→ Snapshot A
                    └── FICLONE ──→ Clone 1, 2, ...
```

**网络层**(network.md,三个 BPF 程序):
```
from_cube  (TAP ingress)    : 沙箱→主机,策略+DNS+SNAT+会话+ARP 代理
from_world (host NIC ingress): 外部→主机,反向 NAT + 端口映射
from_envoy (cube-dev egress) : 主机→沙箱,DNAT(CubeEgress 回包保源 IP / 主机探测改源为网关)
```

### 检验

- eBPF 三程序分别挂在哪?为什么不用网桥?(每沙箱独立 TAP,无广播域,内核态策略)
- 会话跟踪为什么用双 map?(`egress_sessions` 主表存全 NAT 态,`ingress_sessions` 反查表只存重建 key,O(1) 双向查)
- SNAT IP 怎么选?(`jhash(sandbox_ip) % 4`,同沙箱恒定 IP,简化外部防火墙)

---

## 阶段 6:代码精读(Component by Component)

**目标**:按 17 个顶层目录读懂实现。结合 `CONTRIBUTING.md` 的项目结构表。

### 6.1 数据面 Rust(5 个 Cargo workspace)

来自 Makefile 的 `RUST_PROJECT_DIRS`:

| 目录 | 是什么 | 读什么 |
|---|---|---|
| `CubeAPI/` | E2B 兼容 REST 网关(Axum) | `Cargo.toml`、`src/`(API 路由 + auth 回调)、`Makefile` |
| `CubeShim/` | containerd Shim v2 实现 | `src/`(rootfs/memory/kernel 准备 + vsock + 原地快照) |
| `agent/` | 沙箱内 daemon | `src/`(命令执行/文件操作/健康上报,`libs/safe-path/`) |
| `cubecow/` | ⭐⭐ CoW 存储引擎 | `README.md`(非常详细:架构图+on-disk 布局+FFI+Rust SDK)、`src/engine/reflink.rs`、`include/cubecow.h`、`ffi.rs` |
| `hypervisor/` | KVM VMM(Cloud Hypervisor fork) | `README.md`、`hypervisor/src/`(vCPU/内存/virtio/seccomp)、`virtiofsd/`(子模块) |

### 6.2 数据面 + 控制面 Go

| 目录 | 是什么 | 读什么 |
|---|---|---|
| `Cubelet/` | ⭐ 节点本地 agent | `pkg/`(lifecycle/sandbox/store/snapshots/cubecow/cmd)、`Makefile`、`pkg/hotswap/`、`pkg/store/membolt/` |
| `CubeMaster/` | ⭐ 集群调度器 | `cmd/`、`Makefile`、proto |
| `CubeOps/` | 运维 CLI | `cmd/cubeops` |
| `CubeProxy/` | 反向代理(OpenResty+Lua + Go sidecar) | `sidecar/`、`README.md` |
| `CubeNet/` | ⭐ eBPF 网络数据面 | `CubeNet/cubevs/`(`mvmtap.bpf.c`/`nodenic.bpf.c`/`localgw.bpf.c` 三个 BPF + Go 控制面)、`cmd/cubevsmapdump` |
| `network-agent/` | 网络管理服务 | `README.md`、proto |
| `cube-lifecycle-manager/` | auto-pause/resume 看护 | `README.md`(watch Redis 事件 + 透明 pause + 收到请求 resume) |
| `CubeDB/` | 数据库迁移层 | `README.md`、`migrate/migrations/{postgres,mysql}/` |
| `CubeEgress/` | L7 出口代理 | OpenResty+Lua 配置 |
| `cubelog/` | 日志收集 | `Makefile` |

### 6.3 部署 / 前端 / SDK / 示例

| 目录 | 是什么 |
|---|---|
| `deploy/` | 部署脚本 + guest 镜像工具(`one-click/`、`kubernetes/chart/`、`pvm/`) |
| `web/` | ⭐ Vue WebUI(`:12088`,版本矩阵/模板健康检查) |
| `sdk/python/` + `sdk/node/` + `sdk/go/` | ⭐ 三语言 SDK(E2B 兼容) |
| `examples/` | ⭐ 16 个端到端示例(见阶段 7) |
| `docs/` | VitePress 文档站(中英双语) |
| `docker/` | builder image + 运行时镜像 |
| `dev-env/` | 开发用 QEMU VM |
| `configs/` | guest 内核配置(`kernel-oc9.<arch>.config`) |
| `tests/` | e2e 测试(`e2e/sdk_compat/`) |

### 6.4 生成代码 / proto

proto 契约在 `CubeNet/cubevs`、`CubeMaster`、`Cubelet`、`network-agent`、`CubeShim` 各自 `make proto` 生成;OpenAPI 在根 `openapi.yml`(CubeAPI)。

---

## 阶段 7:API + SDK + 集成示例

**目标**:会用 SDK 写一个 agent 程序,跑通一个 example。

### API

- 根 `openapi.yml` — CubeAPI 的 E2B 兼容 REST schema
- `sdk/files-api-streaming.md` — 文件 API 流式用法

### SDK(三语言,E2B 兼容)

- `sdk/python/README.md`(PyPI `cubesandbox`)— ⭐ 推荐入门
- `sdk/node/README.md`
- `sdk/go/README.md`

### 16 个示例(`examples/`,按场景分组)

| 示例 | 学什么 |
|---|---|
| `code-sandbox-quickstart/` | ⭐ 代码执行沙箱快速入门 |
| `browser-sandbox/` | 浏览器自动化沙箱 |
| `openai-agents-example/` + `openai-agents-code-interpreter/` | ⭐ OpenAI Agents SDK 集成 |
| `openclaw-integration/` | OpenClaw 助手集成 |
| `pi-agent-integration/` | Pi agent 集成 |
| `mini-rl-training/` | ⭐ RL 训练(SWE-Bench,含 `mini-swe-agent-patch/`) |
| `snapshot-rollback-clone/` | ⭐ 快照/回滚/克隆 |
| `route-aware-egress/` | 策略路由出口 |
| `network-policy/` | 网络策略 |
| `volume/cos/` | ⭐ v0.6 Volume 框架(腾讯云 COS 后端,含 rpc/binary 两种) |
| `cubesandbox-base-nginx/` | 自建 nginx 基础模板 |
| `e2b-dev-sidecar/` | E2B dev sidecar |
| `host-mount/` | host mount |
| `ivshmem/` | 共享内存(ivshmem 设备) |
| `cube-bench/` | 性能基准工具 |

### 检验

- 用 Python SDK 写一个起沙箱→跑代码→拿结果→删沙箱的最小程序
- 跑通 `mini-rl-training` 看 RL agent 怎么用沙箱做环境

---

## 阶段 8:测试与贡献

**目标**:会跑测试、能提 PR。**注意 DCO + AI 署名政策**(AGENTS.md)。

### 构建/测试命令速查(根 Makefile)

```bash
# ── 构建(builder image 是统一构建环境)──
make builder-image           # 先建 builder image(cube-sandbox-builder:ubuntu2004)
make builder-shell           # 进 builder 交互 shell
make all                     # 构建全部 Go 组件(cubemaster/cubelet/network-agent/cubevsmapdump)
make cubemaster / cubelet / agent / shim / cubeapi / cubeops / network-agent / cube-proxy-sidecar

# ── Rust 单独 ──
make cubecow-sdk             # 构建 cubecow 静态库给 Cubelet 用(cgo 链接)
make cubecow-smoke           # cubecow smoke CLI
make cubecow-test-native     # cubecow 原生测试

# ── 测试 ──
make cubeops-test            # CubeOps
make cubemaster-test         # CubeMaster
make cubelet-test            # Cubelet(依赖 cubecow-sdk)
make network-agent-test     # network-agent
make cube-proxy-test        # CubeProxy(本地)
make cube-api-test          # CubeAPI
make shim-test              # CubeShim
# cubecow 单元测试:cd cubecow && cargo test --lib(无需 root)

# ── guest 内核 ──
make guest-kernel KERNEL_SRC=/path/to/linux        # 原生
make guest-kernel KERNEL_SRC=... KERNEL_TARGET_ARCH=aarch64  # 交叉

# ── 发布 ──
make manual-release          # 打手动更新 tarball

# ── 前端 ──
make web-install / web-dev / web-build / web-preview / web-lint / web-fmt / web-api-sync

# ── 格式化(全部组件)──
make fmt
```

> 二进制产物写 `_output/bin/`,发布包写 `_output/release/`。builder 镜像统一了 Rust+Go+protoc+musl 环境,避免本机装一堆依赖。

### 贡献要点(CONTRIBUTING.md)

- **环境前置**:Linux+KVM(x86_64)、Docker、Go 1.21+、Rust 1.75+(带 `x86_64-unknown-linux-musl` target)、protoc
- **提交组织**:一 commit 一组件(跨组件拆开);原子;refactor 与行为改动分开;逻辑排序
- **commit message**:`component: summary` 前缀(如 `cubeapi:` `cubelet:` `docs:` `shim:`),说清 *why*
- **DCO(强制)**:每个 commit 必须有 `Signed-off-by`,`git commit -s` 加;无此行**不接收**
- **代码风格**:Go 用 gofmt;Rust 用 rustfmt + clippy;中英文档保持同步
- **社区文档通道**:`docs/guide/{troubleshooting,usecases,integrations}/` 三类,双语 kebab-case 文件名,从 `_template.md` 起

### ⚠️ AI 生成代码政策(AGENTS.md,重点)

- AI **不得**加 `Signed-off-by`(只有人类能合法 certify DCO)
- 人类提交者负责:审查 AI 代码 + 加自己的 `Signed-off-by` + 承担全部责任
- commit/PR **必须**带署名 tag(让 AI 贡献在历史里可见可追溯):
  - 人辅 AI:`Assisted-by: AGENT_NAME:MODEL_VERSION`
  - AI 全自动:`Autonomously-by: AGENT_NAME:MODEL_VERSION`

### 安全漏洞

走 GitHub Security Advisories 私密披露,**不要开公开 issue**。

---

## 学习内容总清单(速查)

### A. 自带文档(VitePress,中英双语)

英文在 `docs/`,中文镜像在 `docs/zh/`。按目录:

- **docs/index.md** — 首页
- **docs/architecture/**(2):`overview.md` ⭐⭐⭐ / `network.md` ⭐⭐⭐
- **docs/guide/**(36 文件 + 6 子目录):部署/配置/安全/lifecycle/templates/snapshot/volume/webui/perf/roadmap + `troubleshooting/` `usecases/` `integrations/` `tutorials/` `kubernetes/` `maintainer/`
- **docs/blog/posts/**(14):性能基准×2、网络深度、快照深度、agent 友好、PVM×2、ARM、理念×2、welcome、release×4
- **docs/changelog/**(13):`index` + v0.1.0→v0.6.0 全版本演进
- **docs/dev/**(2):`index` + `redis-key-spec.md`(Redis key 规范,看 CubeProxy/Master 怎么用 Redis)

本地起文档站:`cd docs && npm i && npm run dev`(VitePress)。

### B. 顶层目录(17 个组件 + 配套)

| 目录 | 语言 | 阶段 6 已列职责 |
|---|---|---|
| CubeAPI / CubeShim / agent / cubecow / hypervisor | Rust | 数据面 5 个 Cargo workspace |
| Cubelet / CubeMaster / CubeOps / CubeProxy / CubeNet / network-agent / cube-lifecycle-manager / CubeDB / CubeEgress / cubelog | Go | 控制面 + 数据面 Go |
| web | Vue | WebUI |
| sdk | Python/Node/Go | E2B 兼容 SDK |
| examples | Python | 16 个端到端示例 |
| deploy / docker / dev-env / configs / tests / scripts / docs | 配套 | 部署/构建/测试 |

### C. 关键配置/契约文件

| 文件 | 作用 |
|---|---|
| `Makefile` | 所有构建/测试/部署入口(415 行,help target 列全) |
| `openapi.yml` | CubeAPI E2B 兼容 REST schema |
| `configs/kernel-oc9.<arch>.config` | guest 内核配置(x86_64/aarch64) |
| `docker/Dockerfile.builder` | 统一构建环境镜像 |
| `deploy/one-click/` | 一键部署脚本 + 资产 |
| `deploy/kubernetes/chart/` | Helm chart |
| `docs/dev/redis-key-spec.md` | Redis key 规范 |
| `docs/dev/index.md` | 开发者文档入口 |

### D. 核心术语表

| 术语 | 含义 |
|---|---|
| MicroVM | KVM 轻量虚拟机,每沙箱一个,独立内核 |
| CubeShim | containerd Shim v2 实现,把沙箱接入容器运行时 |
| CubeVS | eBPF 网络虚拟化(三个 BPF 程序 + Go 控制面) |
| CubeCoW | xfs-reflink(FICLONE)O(1) 快照/克隆存储引擎 |
| CubeEgress | OpenResty L7 出口代理(域名过滤+凭证注入+审计) |
| template | OCI 镜像→Buildkit→rootfs+内存快照,作为基线 |
| FICLONE | Linux `ioctl` reflink,XFS/Btrfs 共享 extent 不拷字节 |
| TPROXY | 透明代理,CubeEgress 用它截获出口流量 |
| vsock | virtio socket,host↔guest 通信通道 |
| virtiofsd | virtio-fs 守护进程,文件系统直通 |
| reflink | XFS 写时复制,extent 共享 |
| auto-pause/resume | 空闲沙箱自动挂起,下次请求自动唤醒(cube-lifecycle-manager) |
| traffic token | 每沙箱数据面访问令牌(v0.5 网络策略加固) |
| Volume | E2B 兼容卷框架,独立生命周期,可跨沙箱共享(v0.6) |

---

## 推荐学习顺序(4 周计划)

| 周 | 重点 | 产出 |
|---|---|---|
| **W1** | 阶段 0+1+2:补基础 + 概念 + 跑通 PVM 单机 | WebUI 起停沙箱,能画架构图 |
| **W2** | 阶段 3+4:部署 + 配置/安全 | 多节点或 K8s 部署,改配置,懂六层安全 |
| **W3** | 阶段 5:架构深入 | 读完 overview+network+网络/快照/性能博客,默画请求时序+存储层+三 BPF 流量图 |
| **W4** | 阶段 6+7+8:代码精读 + SDK + 测试 | 跑通一个 example,跑通一个组件单测,懂 DCO+AI 署名 |

### 每周自检

- W1:CubeSandbox 和 Docker 沙箱的本质区别?(独立内核 vs 共享内核)
- W2:控制面为什么无状态?Redis 存了哪些东西?(沙箱元数据+生命周期事件流+CubeProxy 路由表+auto-pause/resume 分布式锁)
- W3:eBPF 三程序挂在哪?会话跟踪双 map 怎么设计?快照为什么 O(1)?
- W4:`make cubelet-test` 怎么跑?提 PR 要带什么署名?(`Signed-off-by` + `Assisted-by:`/`Autonomously-by:`)

---

## 进阶方向(学完基础后)

- **eBPF 深挖**:读 `CubeNet/cubevs/` 三个 `.bpf.c` 源码,理解 11 状态 TCP 跟踪、LPM trie、DNS 学习
- **RustVMM**:读 `hypervisor/`,理解 vCPU/内存区域/virtio 设备/seccomp,对比 Cloud Hypervisor 上游差异
- **containerd Shim v2**:读 `CubeShim/`,理解 ttrpc + 任务模型 + 与 containerd daemon 的交互
- **CubeCoW 后端扩展**:`cubecow/` 的 `Engine` trait 是 backend-agnostic,可加新后端(如对象存储)
- **Volume 插件**:v0.6 Volume 框架,读 `examples/volume/cos/` 写自定义后端
- **auto-pause/resume**:读 `cube-lifecycle-manager/`,理解 Redis 事件 watch + 透明 pause + 唤醒路径
- **跨节点 pause/resume**(roadmap):内存+文件系统状态跨节点保留

---

## 附:关键文件索引

| 路径 | 是什么 |
|---|---|
| `README.md` / `README_zh.md` | 项目门面,中英双语 |
| `CONTRIBUTING.md` / `CONTRIBUTING_zh.md` | 贡献规范(含 DCO) |
| `AGENTS.md` | ⚠️ AI 生成代码署名政策(Assisted-by/Autonomously-by) |
| `Makefile` | 构建/测试/部署总入口 |
| `openapi.yml` | CubeAPI REST schema |
| `docs/index.md` | 文档首页 |
| `docs/architecture/overview.md` | ⭐⭐⭐ 架构总览(最该读的一篇) |
| `docs/architecture/network.md` | ⭐⭐⭐ CubeVS eBPF 网络深度 |
| `docs/dev/redis-key-spec.md` | Redis key 规范 |
| `docs/blog/posts/` | 14 篇深度技术博客 |
| `docs/changelog/` | 13 个版本演进 |
| `cubecow/README.md` | ⭐ CoW 引擎详解(架构图+on-disk+FFI+SDK) |
| `examples/` | 16 个端到端示例 |
| `sdk/{python,node,go}/` | 三语言 E2B 兼容 SDK |
| `deploy/one-click/` + `deploy/kubernetes/chart/` | 一键 + K8s 部署 |
