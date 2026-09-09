# AgentENV 学习路线与内容清单

> 本文基于仓库 `AgentENV-main/` 实际代码与自带文档(`docs/`,mdBook,共 32 篇)梳理,所有命令/配置项/概念均来自项目真实文档。
> 目标:从零到能改代码、能贡献 PR。
> 配套阅读:同目录 `agentenv.md`(快速入门 + 测试入门)。

---

## 总览:AgentENV 是什么

一句话:**用 Rust 在大规模下运行 AI agent 沙箱的 platform**,底层是 Firecracker microVM,存储自研 overlaybd + ublk,控制面用 Go(gateway + scheduler),对外暴露 E2B 兼容 HTTP API。为 Kimi K3 的 agentic RL 训练提供环境。

核心卖点(来自 README):
- 跨机大规模 Firecracker 环境,overlaybd 按需加载,生产到 150 万镜像
- 沙箱 pause < 100ms / resume < 50ms,空闲释放 CPU/内存
- 原生增量快照 + fork,快照 < 100ms
- ublk 高性能 I/O,内存 ballooning 实现 9.6x 内存超卖

---

## 前置知识自检(阶段 0)

学 AgentENV 前,这些最好有底子;没有就先补,否则代码读不动。

| 领域 | 需要掌握到 | 补资料 |
|---|---|---|
| **Linux 内核/虚拟化** | KVM、`/dev/kvm`、network namespace、veth、iptables、`nsenter` | Firecracker 官方文档;Linux namespace `man 7` |
| **Rust** | async/await、tokio runtime、trait、Cargo workspace、`unsafe` 边界 | The Rust Book + Tokio Tutorial |
| **io_uring** | 基本概念(SQE/CQE/ring)、为何比 epoll 快 | `man io_uring`、liburing |
| **ublk** | 内核 ublk 驱动是什么、userspace 块设备原理 | Linux 6.x ublk 文档 |
| **容器/OCI** | OCI 镜像、layer、manifest、registry 协议、`regctl` | OCI Image Spec、overlaybd 文档 |
| **存储** | LSMT(log-structured)思想、COW、page cache、mmap、`FICLONE`/reflink | overlaybd README |
| **Go** | 基本能读 Go 代码(控制面用) | A Tour of Go |
| **网络** | gRPC、HTTP 反向代理、WebSocket、TPROXY | — |

> 最低门槛:Rust + tokio + 基本 Linux 内核知识。其余可边学边补。

---

## 阶段 1:概念建立(先懂"是什么")

**目标**:理解六大核心概念,能画出系统架构图,说清一次 `POST /sandboxes` 经过的层。

读 `docs/src/`(按顺序):

1. `getting-started/overview.md` — 项目定位
2. `concepts/overview.md` — ⭐ 系统总览 + mermaid 架构图 + 请求流,**最重要一篇**
3. `concepts/sandboxes.md` — 沙箱 = 一个 Firecracker microVM(含 8 态生命周期)
4. `concepts/templates.md` — 模板 = 从 OCI 镜像构建的提交快照
5. `concepts/snapshots.md` — 快照 = pause 时的内存+文件系统状态
6. `concepts/proxy.md` — 反向代理如何把流量送进 VM
7. `concepts/custom-extension.md` — 可选的外部 hook 服务

### 六大概念详解

| 概念 | 是什么 | 关键细节 |
|---|---|---|
| **Sandbox** | 一个隔离的 Firecracker microVM,有独立内核/文件系统/网络 | 8 态状态机(见下);TTL 过期默认 `pause`,可配 `kill`;fork 一对多变上限 **16** 个子沙箱 |
| **Template** | 由 OCI 镜像 + RUN/ENV/WORKDIR 步骤构建出的"基线快照" | UUID 标识,`--name` 加人类可读别名;`aenv pull`(OCI 直转)或 `aenv build`(Dockerfile,实验性) |
| **Snapshot** | 沙箱 pause 时的内存 + rootfs + 额外盘状态,可 resume / fork | 模板就是一类快照;三层存储模型(builder staging / committed 仓库 / node-local runtime cache) |
| **Orchestrator** | 沙箱生命周期状态机 | Creating→Running→{Pausing→Paused→Resuming} / {Snapshotting} / {Forking} →Killing;auto-eviction 后台任务 |
| **Proxy** | HTTP/WebSocket 反向代理,按 sandbox ID / host 路由到 VM 内服务 | `/proxy` + 路由 header + host-based `{port}-{sandboxID}.{domain}` |
| **Custom Extension** | 可选外部 HTTP 服务,在沙箱 start/stop 注入 hook | `[custom_extension].url` 未设则完全禁用;4 个 hook:start-fresh / start-resume / patch-params / stop |

### 沙箱 8 态生命周期(必须记牢)

```
Creating → Running → {Pausing→Paused→Resuming→Running}
                      {Snapshotting→Running}   # 不停机快照
                      {Forking→Running}          # 分叉,上限 16 子沙箱
                      {Killing→[*]}              # 销毁
```

| 状态 | 含义 |
|---|---|
| Creating | VM 启动中,块设备接入,网络配置 |
| Running | VM ready,可执行命令/代理流量/TTL 倒计时 |
| Pausing | 正在抓内存+盘快照 |
| Paused | VM 已停,快照产物已存,**不消耗资源** |
| Resuming | 从 paused 快照恢复 |
| Snapshotting | 抓持久化快照(不停机),完后回 Running |
| Forking | 克隆成子沙箱(不停机),完后回 Running |
| Killing | 拆除 VM,释放资源 |

### Warm Start vs Cold Start

| 方式 | 命令 | 说明 |
|---|---|---|
| **Warm Start**(从模板) | `aenv start <template-id>` | 从预构建模板恢复快照,毫秒级 |
| **Cold Start**(从 OCI 镜像) | `aenv start --cold ubuntu:24.04` | 直接拉 OCI 镜像运行时转块设备,慢;可选 `diskSizeMB`(≥1024 且整除 1024) |

### 检验(带答案)

- **Q: 一个沙箱从 `POST /sandboxes` 到能跑命令,经过了哪几层?**
  A: Client→CubeAPI 等价的 API 层(Axum)→ Orchestrator(状态机)→ Sandbox 模块(Firecracker VM + network namespace + ublk 块设备 + envd init)。具体:API 校验→orchestrator create→Firecracker 启动+网络槽+ublk 设备+rootfs→envd ready→Running。
- **Q: overlaybd 的 layered image 和 Docker 的 layered image 有什么区别?**
  A: overlaybd 是 LSMT 块设备层叠(immutable r/o lower + 单 r/w upper,16 字节 bit-packed `DiskSegmentMapping`),通过 ublk 暴露为 `/dev/ublkbN`;Docker 是 unionfs 文件级层叠。overlaybd 支持随机访问压缩(zstd 跳表)、registryfs_v2 远程按需读。
- **Q: pause/resume 为什么快(< 50ms)?**
  A: resume = Firecracker mmap 只读 ublk 内存设备 → COW 到匿名内存;多沙箱同快照共享同一 mem ublk(refcount)→ 复用 Linux page cache,避免重复 I/O。

---

## 阶段 2:跑起来(用起来)

**目标**:本机或 Docker 跑通一个沙箱,用 CLI 完整走一遍生命周期。

读 + 动手:

1. `getting-started/quickstart.md` — ⭐ 装机 + 起 server + 认证 + pull + start
2. `getting-started/on-demand-loading.md` — overlaybd 按需加载原理(POSIXFS / OSS 两种共享存储后端)
3. `getting-started/aenv-cli.md` — ⭐ CLI 全套命令

### 装机(两条路径,来自 quickstart.md)

**前置**:Linux kernel 6.8+ + `/dev/kvm` 访问。安装脚本会装缺失的下载/校验命令、配 `/dev/kvm` 权限、加载 `ublk_drv` 模块、下载运行时资产。**安装需 root,但服务不以 root 跑**——用 `aenv` 系统账号 + `CAP_NET_ADMIN` + `CAP_SYS_ADMIN` + kvm 组 + ublk 设备组。

**Option A — Install Script(systemd 服务)**:
```bash
curl -fsSL https://raw.githubusercontent.com/kvcache-ai/AgentENV/main/scripts/install.sh | sudo AENV_HOME_PATH=/path/to/aenv/data bash
sudo systemctl start aenv
# 改配置:sudo vim /var/lib/aenv/config/config.toml && sudo systemctl restart aenv
# 改端口:编辑 /etc/default/aenv 的 API_ADDR
```

**Option B — Docker**:
```bash
curl -fsSL https://raw.githubusercontent.com/kvcache-ai/AgentENV/main/scripts/docker-setup.sh | sudo bash
docker pull ghcr.io/kvcache-ai/aenv-server:latest
docker run --rm -it --name aenv-server --device /dev/kvm --privileged -v /dev:/dev -p 8000:8000 ghcr.io/kvcache-ai/aenv-server:latest
# 挂自定义配置:-v "$PWD/config.toml:/workspace/config/default.toml:ro"
```

验证:`curl http://127.0.0.1:8000/health`

### 认证(三步)

```bash
# 1. 拿 API key(server 首启生成)
sudo cat /var/lib/aenv/secrets/api-key            # Native
docker exec aenv-server cat /workspace/env/secrets/api-key  # Docker

# 2. CLI 配置(存 ~/.config/aenv/credentials,0600)
aenv auth
# AENV server URL [http://localhost:8000]: http://127.0.0.1:8000
# API key: <paste>

# 3. 装 CLI(Option A 已含,Option B 单装)
curl -fsSL https://raw.githubusercontent.com/kvcache-ai/AgentENV/main/scripts/install-cli.sh | bash
```

### CLI 全套(来自 aenv-cli.md)

```bash
# ── 模板 ──
aenv pull ubuntu:22.04 --name ubuntu      # OCI 镜像 → 模板(默认等待完成)
aenv pull ubuntu:22.04 --name my-ubuntu --start-cmd "nginx" --ready-cmd "curl localhost" --probe 80 -d
aenv build ./Dockerfile --name my-app --image ghcr.io/myorg/base:latest  # 实验性
aenv template list [--output json]         # alias: ls
aenv template watch <name-or-id>           # 跟踪构建直到成功/失败
aenv template delete <name-or-id>          # alias: rm

# ── 沙箱 ──
aenv start ubuntu                          # warm start + attach 交互 shell
aenv start ubuntu -d                      # detach,只打印 sandbox ID
aenv start --cold ubuntu:24.04 --cpu 2 --mem 1024  # cold start,资源仅 cold 时有效
aenv start --secure ubuntu                # 要求 envd token 认证
aenv start ubuntu --timeout 600           # TTL 600s
aenv connect <id>                         # alias: cn;paused 会先 resume 再 attach
aenv exec <id> ls -la /                   # 一次性命令,流式输出
aenv upload <id> ./config.json /workspace/config.json [--user app]   # 上传文件/目录
aenv download <id> /workspace/result.txt ./result.txt [--user app] [--force]  # 下载
aenv list                                 # alias: ls;TTY 表格,管道 JSON
aenv pause <id>
aenv resume <id> [--timeout 600]
aenv timeout <id> 600                     # 从现在起 TTL=600s
aenv delete <id>                          # alias: rm

# ── 快照 ──
aenv snapshot create <id>                 # 从运行中沙箱抓持久快照
aenv snapshot create <id> --name my-base
aenv snapshot list [--sandbox-id <id>] [--output json]   # alias: ls / snap ls
# 删快照用:aenv template delete <snapshot-id>  # 快照和模板共享存储
```

### E2B 兼容(来自 integration/e2b.md,阶段 7 详述)

`aenv` CLI 之外,直接用 E2B 官方 Python/TS SDK,只改环境变量:
```bash
export E2B_API_URL=http://127.0.0.1:8000
export E2B_SANDBOX_URL=${E2B_API_URL}
export E2B_API_KEY=${AENV_API_KEY}
```

### 按需加载(来自 on-demand-loading.md)

本地磁盘是有界缓存,热数据保留/冷数据淘汰,无需每台机预热所有镜像。两种共享存储后端:

```toml
# POSIXFS
[snapshot]
repository_backend = "posix_fs"
[backend.posix_fs]
snapshot_store = "/mnt/aenv-snapshots"
[image.cache.remote_blocks]
max_size_gb = 100

# OSS(S3 兼容;Tigris/R2 需 addressing_style = "virtual")
[snapshot]
repository_backend = "oss"
[backend.oss]
endpoint = "YOUR_ENDPOINT"
bucket = "YOUR_BUCKET"
region = "YOUR_REGION"
prefix = "YOUR_PREFIX"
access_key_id = "..."
access_key_secret = "..."
cache_max_size_gb = 100
```

### 检验(带答案)

- **Q: `aenv pull` 把镜像转成了什么?**
  A: overlaybd commit(本地 `.commit` 文件 + `image.json`),存到 `[image.cache.root_dir]/commits/<sha256>/`。
- **Q: `--detach` 和直接 attach 的区别?**
  A: `-d` 只打印 sandbox ID 立即返回,不占 tty;默认会 attach 进交互 shell。
- **Q: pause 后 resume,VM 里的进程还在吗?**
  A: 在。pause 抓的是内存+盘快照,resume 从快照恢复,运行中的进程/打开的连接都原样保留。
- **Q: fork 最多分几个?**
  A: 16 个子沙箱(同节点),源沙箱短暂 pause 抓克隆后 resume,子继承 fs/memory/资源配置,各派生独立 envd/traffic 凭证。

---

## 阶段 3:部署(多机)

**目标**:理解单机 → 多机 → k8s 的演进,能部署多节点。

读 `docs/src/deployment/`(按复杂度递增):

1. `docker.md` — 单节点 Docker
2. `docker-compose.md` — ⭐ 多节点模拟(2 node + gateway + scheduler)
3. `static-multi-node.md` — 不用 k8s 的多机
4. `kubernetes.md` — ⭐ k8s(DaemonSet + Deployment)
5. `manual-compile.md` — 从源码编译单机
6. `pvm.md` — KVM 不可用时用 PVM(x86_64 + kvm_pvm 模块)

### 关键架构

多机时前置 gateway + scheduler:
```
Client → Gateway(:8080,HTTP) → Scheduler(:9090,gRPC) → Node A/B/...(:8000)
```

- **Gateway**:HTTP 反向代理,按 sandbox ID 路由;新沙箱调 `Schedule`,已有沙箱调 `LookupNode`
- **Scheduler**:gRPC,节点发现(static / k8s EndpointSlice)、沙箱-节点 binding、心跳

### docker-compose(来自 docker-compose.md)

```bash
git clone https://github.com/kvcache-ai/AgentENV.git && cd AgentENV
sudo bash scripts/docker-setup.sh      # 主机前置
make deploy-up                          # 构建 + 起 gateway/scheduler/2 node
# host-based sandbox 域名:
SANDBOX_PROXY_DOMAINS=sandbox.example.com make deploy-up

# 验证
curl http://127.0.0.1:8000/health
export AENV_API_KEY="$(docker compose -f deploy/docker-compose.yml exec -T agentenv-a cat /workspace/env/secrets/api-key)"
curl -H "X-API-Key: ${AENV_API_KEY}" http://127.0.0.1:8000/nodes

# 管理
make deploy-ps / deploy-logs / deploy-down
```

首启时 runtime 节点在共享 `agentenv-auth` volume 原子生成一个 API key + sandbox access-token seed;gateway 只读挂载该 volume。`make deploy-down` 保留两个 secret,`docker compose down -v` 会清掉(下次启重新生成,旧客户端失效)。要复用已有 key:`export AENV_API_KEY="e2b_..."` 后 `make deploy-up`。

compose 还自动配心跳:`AENV_NODE_ID=node-a|node-b`、`AENV_OBSERVABILITY_SCHEDULER_REPORT_ENABLED=true`、`AENV_OBSERVABILITY_SCHEDULER_ENDPOINT=http://scheduler:9090`。

### kubernetes(来自 kubernetes.md)

| Workload | Kind | 说明 |
|---|---|---|
| `agentenv-gateway` | Deployment + ClusterIP | HTTP 反向代理 |
| `agentenv-scheduler` | Deployment(单副本) + ClusterIP | gRPC 节点选择 + binding |
| `agentenv-node` | DaemonSet(privileged) | 每节点一个 runtime Pod |
| `agentenv-nodes` | Headless Service | scheduler EndpointSlice 发现用 |

**为什么 DaemonSet**:每 Pod 要 host-local `/dev/kvm`;沙箱网络用 host iptables + network namespace;runtime 资产 + 快照状态按 host 缓存在 `/var/lib/aenv`。

```bash
make k8s-build                      # 构建 runtime/gateway/scheduler 三镜像
sudo bash scripts/docker-setup.sh   # 每个 worker 跑一次
make k8s-render                      # 预览 manifests
make k8s-apply                       # 部署(首部署生成 256-bit key 存 Secret/agentenv-auth)
SANDBOX_PROXY_DOMAINS=sandbox.example.com make k8s-apply   # host-based 域名

# 读 API key
kubectl -n agentenv-system get secret agentenv-auth -o go-template='{{index .data "AENV_API_KEY" | base64decode}}{{"\n"}}'

make k8s-redeploy / k8s-delete
```

DaemonSet 自动注入:`AENV_UBLK_DAEMON_BINARY_PATH=/usr/local/bin/uvm-ublk-daemon`、`AENV_NODE_ID=metadata.name`、`AENV_OBSERVABILITY_SCHEDULER_REPORT_ENABLED=true`、`AENV_OBSERVABILITY_SCHEDULER_ENDPOINT=http://agentenv-scheduler:9090`。

scheduler 看 EndpointSlice + Pod 标签发现:`no_schedule_pod_selector` 匹配的 Pod 留作 lingering(不调度),`ignore_pod_selector` 匹配的排除。IPv4/IPv6 都支持。**binding 在内存,scheduler 必须单副本,重启丢 binding**(要 HA 用 Redis,见阶段 6 进阶)。

k3s 本地开发:`make k8s-build && make k8s-load-dev && make k8s-render-dev && make k8s-apply-dev`(或一键 `make k8s-refresh-dev`)。`local-dev` overlay 直接挂 `env/` 到 DaemonSet `/workspace/env`,免拷贝资产。

### 检验(带答案)

- **Q: gateway 怎么知道一个已有沙箱在哪个 node?**
  A: scheduler binding——sandbox 创建后 gateway 调 `RecordAssignment` 种 binding,runtime 心跳带 sandbox 全量 roster,scheduler 以 roster 为准删失效 binding,`binding_ttl` 控制新鲜度。
- **Q: scheduler 重启后 binding 丢吗?**
  A: 内存版丢;设 `scheduler.redis_addr` 切 Redis 后,主 scheduler 写、query-only 副本读,数据面 LookupNode 在主重启期间不中断(但控制面操作仍依赖主)。
- **Q: k8s 里 runtime 为什么是 DaemonSet?**
  A: 每台主机一个,要 `/dev/kvm` + iptables/netns + hostPath 缓存;同 host 的 Pod 必须用同一 KVM/PVM 模式。

---

## 阶段 4:配置与安全

**目标**:会改配置、懂认证模型、懂网络策略优先级。

1. `configuration/reference.md` — ⭐⭐ 全配置项参考(560 行,覆盖每个 section)
2. `configuration/env-vars.md` — 环境变量覆盖
3. `security/authentication.md` — 三凭证模型
4. `security/secure-sandboxes.md` — ⭐ secure sandbox + access-token seed

### 全局/路径配置

| Key | 默认 | 说明 |
|---|---|---|
| `home_path` | `/var/lib/aenv` | 本地状态/缓存/日志根(`AENV_HOME_PATH` 覆盖) |
| `runtime_path` | `/run/aenv` | 瞬时 namespace + daemon socket(`AENV_RUNTIME_PATH`) |
| `deps_path` | `$AENV_HOME/deps` | 自动下载的 runtime 资产根(`AENV_DEPS_PATH`) |
| `virtualization_mode` | `kvm` | `kvm` / `pvm`(`AENV_VIRTUALIZATION_MODE`;快照只能在创建模式恢复) |

> `$AENV_HOME` / `$AENV_RUNTIME` 是配置文件里的**字面占位符**(不是 shell 变量),server 解析 `home_path` 后替换。相对路径相对配置文件目录解析。

### 核心 section 速查

| Section | 关键 key | 默认 |
|---|---|---|
| `[firecracker]` | `boot_args`(含 DAMON reclaim 参数)、`socket_timeout_secs=3`、`work_dir`、`serial_dir`、`log_level` | — |
| `[kernel]` | `image_path`(本地 vmlinux) | 自动下载 |
| `[tools]` | `version`、`drive_path`、`control_plane_port=49983` | envd 端口 49983 |
| `[image.resolver]` | `default_image=ubuntu:24.04`、`search_registries=[docker.io,ghcr.io]`、`allowed_registries`(省略=不限制,`[]`=全拒)、`try_referrers_overlaybd_prefixes` | — |
| `[image.cache]` | `root_dir`、`capacity_gb=100`、`[gc].enabled=true`/`interval_secs=1800`/`high/low_watermark_ratio=0.95/0.70` | — |
| `[image.cache.remote_blocks]` | `max_size_gb=100` | overlaybd registryfs_v2 远程块缓存 |
| `[sandbox_proxy]` | `domains`(`[]` 时不按 Host 分类;`domains[0]` 是 advertised 域名) | `AENV_SANDBOX_PROXY_DOMAINS` |
| `[network.egress]` | `always_denied_cidrs`(默认拒 RFC1918 + 链路本地) | 用户策略前装,不可被 allowOut 覆盖 |
| `[network.internal]` | `host_interaction_cidr=10.11.0.0/16`、`veth_cidr=10.12.0.0/16` | 不可重叠或与固定 `169.254.0.20/30` 重叠 |
| `[machine]` | `mem_size_mib=1024`、`vcpu_count=2` | 默认 VM 资源 |
| `[envd]` | `version=0.5.15`、`init_timeout_secs=60`、`poll_ms=3` | — |
| `[sandbox]` | `access_token_hash_seed`(省略则管理 `$AENV_HOME/secrets/...`) | `AENV_SANDBOX_ACCESS_TOKEN_HASH_SEED` |
| `[orchestrator]` | `auto_evict_interval_ms=1000`、`default_sandbox_timeout_secs=15`、`auto_resume_min_sandbox_timeout_secs=300`、`persisted_sandbox_store_path` | — |
| `[pool]` | `low_watermark=2`、`high_watermark=64`;`[pool.network/block/firecracker]` 各自子项 | 预热资源池 |
| `[observability]` / `[observability.scheduler_report]` | `enabled=true` / `enabled=false`、`interval_secs=5` | `AENV_OBSERVABILITY_SCHEDULER_REPORT_ENABLED/ENDPOINT/INTERVAL_SECS` |
| `[cluster]` | `scheduler_endpoint`(gRPC,如 `http://127.0.0.1:9090`) | — |
| `[p2p]` | `enabled=false`(默认禁用)、`transport=iroh`、`store_dir`、`listen_addr=0.0.0.0:0`、`lookup/fetch_timeout_ms=5000/30000` | **实验性,生产慎用** |
| `[snapshot]` | `local_cache_path`、`repository_backend=posix_fs|oss`、`p2p_enabled=true` | `AENV_SNAPSHOT_LOCAL_CACHE_PATH` |
| `[snapshot.image_publish]` | `enabled=false`(仅 oss 后端生效) | 把 rootfs 推回原 registry 作 overlaybd-native 镜像 |
| `[backend.posix_fs]` | `snapshot_store=$AENV_HOME/snapshot-store` | `AENV_SNAPSHOT_STORE` |
| `[backend.oss]` | `endpoint/bucket/region/prefix`、`credential_process`(argv 式,无 shell)、`access_key_id/secret`、`addressing_style`(auto/`virtual`/`path`,Tigris/R2 用 virtual)、`cache_max_size_gb=10` | — |
| `[ublk]` | `daemon_binary_path`、`daemon_socket_path=$AENV_RUNTIME/ublk-daemon.sock`、`daemon_metrics_listen_addr=0.0.0.0:9103` | `AENV_UBLK_DAEMON_BINARY_PATH/METRICS_LISTEN_ADDR` |
| `[ublk.overlaybd]` | `global_config_path`(启动自动生成)、`read_only`、`runtime_upper_mode=hybridLogStructured`、`allow_shrink=false`、`p2p_lookup/fetch_range_timeout_ms=300/2000` | — |
| `[memory_snapshot]` | `track_dirty_pages=true`(PVM 自动关)、`compression_enabled=false`、`compression_algorithm=lz4|zstd` | `AGENTENV_MEMORY_SNAPSHOT_TRACK_DIRTY_PAGES=false` |
| `[memory_snapshot.background_download]` | `enable=true`、`block_size=16777216`(16MiB)、`concurrency=4`、`max_inflight_blocks=16` | 远程内存层后台下载 |

### 三凭证模型(来自 authentication.md,核心)

| Credential | Scope | Header |
|---|---|---|
| **API key** | AgentENV 生命周期 + 管理 API | `X-API-Key` |
| **`trafficAccessToken`** | `allowPublicTraffic:false` 时的私有应用入口 | `e2b-traffic-access-token` |
| **`envdAccessToken`** | secure sandbox 的 envd 直连(命令/文件) | `X-Access-Token` |

**三凭证不可互换**。公开应用入口 + insecure envd 不需任何 AgentENV 凭证。`Authorization` 是应用层 header,不认证 AgentENV。沙箱路由上,`X-API-Key` 当应用数据处理,**仅当正好等于平台 key 时被剥除**(避免平台凭证转发到沙箱)。

API key 解析顺序(运行时节点):`AENV_API_KEY` → `/run/secrets/api-key` → `$AENV_HOME/secrets/api-key`;都没有则首启自动生成(gateway 只查前两个,不生成)。自定义 key 需 32–256 个 URL-safe 字符,生成 key 用 `e2b_` 前缀:`export AENV_API_KEY="e2b_$(openssl rand -hex 32)"`。

> API-key 认证**不加密流量**,用 HTTPS 终止/VPN/loopback/可信私网。换 `AENV_API_KEY` 不影响沙箱凭证;换 `AENV_SANDBOX_ACCESS_TOKEN_HASH_SEED` 轮换两类沙箱 token。多节点必须共享同一 seed。

### 网络策略优先级(来自 concepts/sandboxes.md + internals/networking.md)

每沙箱独立 network namespace。创建时传 `allow_internet_access`(默认 true)和 `network: {allowOut, denyOut}`。**用户策略链优先级**:`allowOut` > `denyOut` > base policy(`allow_internet_access`)。

```
目的包 → 匹配 allowOut? → Yes:Allow
                  ↓ No
        匹配 denyOut? → Yes:Reject
                  ↓ No
        allow_internet_access? → Yes:Allow / No:Reject
```

- `allowOut`:CIDR/IP/**domain**(domain 仅对 80/443 新 TCP 连接,需配 `denyOut:["0.0.0.0/0"]`;支持精确 / `*.example.com`(不匹配 apex)/ `*`)
- `denyOut`:CIDR/IP
- **静态内部拒**(始终先于用户链):RFC1918 + 链路本地段(`10/8`、`100.64/10`、`127/8`、`169.254/16`、`172.16/12`、`192.168/16`)+ AgentENV 内部地址池,**不可被 allowOut 覆盖**
- 域名规则:proxy 检查 Host/SNI,用 host 侧可信 resolver 重新解析(guest DNS 答案不权威)

构建 allowlist:`denyOut:["0.0.0.0/0"]` + `allowOut:[白名单]`,或 `allow_internet_access:false` + `allowOut:[白名单]`。

### 检验(带答案)

- **Q: API key 从哪来?**
  A: 三选一——`AENV_API_KEY` env / `/run/secrets/api-key` 外部 secret / `$AENV_HOME/secrets/api-key` 首启自动生成(`e2b_` 前缀 + 32 字节随机)。
- **Q: 沙箱数据面和控制面认证有什么不同?**
  A: 控制面用 API key(`X-API-Key`);数据面公开入口无凭证,私有入口用 `trafficAccessToken`(`e2b-traffic-access-token`),secure envd 用 `envdAccessToken`(`X-Access-Token`)。三者不可互换。
- **Q: 静态拒段能不能被 allowOut 覆盖?**
  A: 不能。`always_denied_cidrs` + 内部地址池在用户链之前评估,`allowOut` 只能覆盖用户自己配的 `denyOut`。

---

## 阶段 5:架构深入(原理层)

**目标**:读懂内部设计。这是从"会用"到"能改"的关键。

读 `docs/src/internals/`(8 篇):

1. `architecture.md` — ⭐⭐⭐ 最重要,含目录结构 + 数据流图,**必读**
2. `networking.md` — ⭐⭐ network namespace 拓扑 / 防火墙链 / egress proxy / warm pool
3. `sandbox-testing.md` — 沙箱测试 + Firecracker 升级清单
4. `template-builder-testing.md` — 模板构建测试
5. `persistence-artifact-inventory.md` — 持久化产物清单
6. `proxy-design.md` — ⭐⭐ 反向代理设计(路由契约/HTTP/WS/错误码/auto-resume)
7. `services.md` — ⭐ 分布式控制面(gateway + scheduler,gRPC API)
8. `p2p-design.md` — ⭐ P2P artifact 传输(iroh-blobs)

### 核心数据流(必须能画出来)

**Block device 链路**(读):
```
VM /dev/vda → ublk /dev/ublkbN → OverlaybdTarget → ImageFile → 层栈 top-down 解析
                                                          ├── upper(r/w,LogStructured/HybridLogStructured/sparse)
                                                          └── layer 0,1,2...(r/o,可 zstd 压缩 + 跳表)
```

**Memory snapshot 链路**(resume):
```
Firecracker → mmap ublk /dev/ublkbM(只读) → overlaybd mem layers → snap 0,1,...N
                 └ 多沙箱同快照共享同一 mem ublk(refcount)→ 复用 page cache
```

**Pause 链路**:
```
Firecracker state-only diff snapshot → 查 dirty/present 内存范围(track_dirty_pages=true)
  → process_vm_readv 读内存 → 直接写 overlaybd mem layer(compression 可选 lz4/zstd)→ 父层堆叠
```

### 网络拓扑(internals/networking.md,关键)

每沙箱独立 netns,Firecracker VM 经 TAP 接 namespace,namespace 经 veth 对接 host:

```
[netns]  VM eth0(169.254.0.21) ↔ tap0(169.254.0.22) ↔ vpeer(veth pool 10.12/16,/31 per slot) ↔ [host] veth-{slot} ↔ host-interaction IP(10.11/16,/31 per slot) ↔ Internet
                  ↓ TCP 80/443 REDIRECT
            EgressProxy listener 0.0.0.0:15000(每 namespace 独立 listener)
```

- 全局 `NetworkManager`(`src/sandbox/network/manager.rs`):进程级 slot bitmap + warm pool + 全局 host iptables + proxy registry
- 每 `Slot`(`slot.rs`):一个 namespace + veth/TAP + 地址 plan + namespace iptables + 策略 + 清理
- namespace 三链:`AGENTENV-EGRESS`(静态 FORWARD)、`AGENTENV-USER-EGRESS`(可替换用户策略)、`AGENTENV-EGRESS-PROXY`(可替换 NAT PREROUTING 重定向到 15000)

### 包路径(必读)

- **沙箱→外网**:VM eth0→tap0→nat/PREROUTING(80/443 REDIRECT 到 proxy)→filter/FORWARD(AGENTENV-EGRESS)→POSTROUTING SNAT 到 host_interaction_ip→host FORWARD+MASQUERADE→外网
- **返回**:ESTABLISHED,RELATED 先于用户链接受
- **host→VM**:proxy/envd 流量到 host_interaction_ip,namespace PREROUTING DNAT 到 vm_ip(169.254.0.21)

### Egress Proxy(namespace-local,透明)

- `ensure_listener()` 用 `setns` 进 namespace 绑 15000,nonblocking accept
- 接连接 → `SO_ORIGINAL_DST` 拿原目的 → 缓冲 ≤64KiB 提取 HTTP Host / TLS ClientHello SNI(跨 record 边界累加)
- domain match 交给进程级 host-netns DNS worker 重新解析,候选 IP 经 `SandboxNetworkPolicy::is_domain_allowed` 检查(含平台/内部段拒)后拨号
- 策略替换是原子操作:`iptables-restore` 一批提交,失败保留旧策略;活跃策略在 pending 成功后才激活
- **不终止 TLS、不重写 HTTP**,纯透传 relay(半关闭处理);空/未识别 hostname 在有 domain allowlist 时 fail-closed

### 反向代理设计(internals/proxy-design.md)

路由契约:每请求必须带 sandbox ID + target port。
- header:`x-agentenv-sandbox-id` + `x-agentenv-target-port`(或 E2B 兼容 `e2b-sandbox-id` + `e2b-sandbox-port`)
- host-based:`{port}-{sandboxID}.{domain}`(domain 必须精确匹配,小写归一化,可选去尾点)
- 校验:sandbox ID 必须合法 UUID,target port 解析为 `u16` 且 >0

运行时路由表(in-memory,key=`SandboxId`):只有 `Running` 沙箱发路由。lookup:`Ready(target)` / 元数据 `NotFound`/`Paused{auto_resume}`/`RouteMissing`/`Unavailable(state)`。

**Paused auto-resume**:`/proxy` 可自动 resume paused 沙箱(每请求最多一次);resume 成功后 timeout 用 `EnsureMinimum(5 min)`(=max(existing, 5min));proxy 等待测试构建短超时 / 运行时 60s;`auto_resume=false`→410 Gone,失败→502,超时→504。

HTTP 转发:`/proxy`→`/`,`/proxy/{path}`→原样后缀,header-routed 保留原 path,query 不变;百分号编码/重复前导斜杠保留;剥路由 header + hop-by-hop header;注入 `x-forwarded-host/proto/method/uri`。WebSocket 走同一 endpoint,upstream 拒绝按状态码透传,连接失败 502,握手超时 504。

错误码:`400`(缺/非法路由 header)、`404`(沙箱不存在)、`410`(paused 且 auto-resume 禁)、`502`(Running 但路由缺失 / resume 失败 / 上游传输失败)、`504`(resume 超时 / 上游 header 超时 / WS 握手超时)。

### P2P artifact 传输(internals/p2p-design.md)

`src/p2p/` 项目级节点间 artifact 传输抽象,`Arc<dyn P2pTransport>`。默认 `DisabledP2pTransport`(lookup miss / publish no-op / fetch 报 TransportDisabled)。iroh 后端 = iroh endpoint + `iroh-blobs` FsStore + RocksDB catalog。

- 一个 `P2pArtifactKey`(稳定字符串)代表一个逻辑 artifact;descriptor 含 `key`/`providers`/`backend_locator`(iroh 用 blob hash)/`metadata`(JSON)
- lookup 顺序:本地 catalog → scheduler `LookupP2pArtifact` → 已发现 peer 按 ALPN 询问
- fetch:iroh content-addressed blob 下载到本地 FsStore 再导出;**远程 fetch 成功后 best-effort 把本地副本广告**,让 artifact 在集群扩散
- scheduler 只存 key→node 映射,**不存 locator/metadata,不代理字节**
- snapshot 消费:`src/snapshot/p2p.rs` 在仓库 commit 成功后 best-effort 发布(`vm_state.bin` + `firecracker-manifest.json` 走 snapshot-scoped key,overlaybd 层走 `overlaybd-layer/v1/sha256:<digest>` 共享 key);OSS 解析 P2P 优先 + OSS 回退,POSIX 解析**不用** P2P(本地仓库即真相)
- GC 门控:有 pending 才跑 mark/sweep,避免周期性全库扫描

### 检验(带答案)

- **Q: overlaybd 的 LSMT 层是怎么映射虚拟块到物理位置的?**
  A: 16 字节 bit-packed `DiskSegmentMapping`:50-bit virtual offset + 14-bit length + 55-bit physical offset + zeroed flag + layer tag。`HeaderTrailer`(magic `LSMT\0\1\2`,UUID)标边界。
- **Q: 为什么 resume 快?**
  A: Firecracker mmap 只读 ublk 内存设备 → 首次写 COW 到匿名内存;同快照多沙箱共享 mem ublk(refcount)→ page cache 复用 → 大幅降低并发启动 I/O。
- **Q: `close_seal + restack` 做了什么?**
  A: `ImageFile::create_snapshot_and_restack()` 把 live upper 经 `LSMTFile::close_seal_and_reopen()` 封存成最新 lower,原地开新 writable upper;`export_upper_as_snapshot_layer()` 是打包/导出流程用的显式 upper 导出路径。
- **Q: namespace 三链怎么排?**
  A: `AGENTENV-EGRESS`(静态 FORWARD):1. ESTABLISHED,RELATED accept → 2. DNS 53 → 3. 拒内部池+always_denied_cidrs → 4. jump `AGENTENV-USER-EGRESS`(allowOut ACCEPT → denyOut REJECT → base Deny 时 0.0.0.0/0 REJECT);`AGENTENV-EGRESS-PROXY`(NAT PREROUTING)把 80/443 REDIRECT 到 15000。
- **Q: P2P 为什么 POSIX 后端不用?**
  A: POSIX 仓库本身就是可直接访问的 committed artifact 源,缺文件直接返 `ArtifactNotFound` 而不从 peer 修复;overlaybd 层加速归 overlaybd P2P HTTP facade,不归 snapshot 解析器。

---

## 阶段 6:代码精读(Crate by Crate)

**目标**:按 crate 读懂实现。结合 `CLAUDE.md`(它本身就是一个高质量的 crate 概览)。

### 6.1 存储子系统(`storage/`,核心)

| Crate | 路径 | 读什么 |
|---|---|---|
| **overlaybd** | `storage/overlaybd/` | ⭐⭐ LSMT 层叠格式。`image/image_file.rs`(高层)、`lsmt/file/{readonly,readwrite,stack}.rs`、`lsmt/format.rs`(二进制格式)、`compression/zfile.rs`(zstd 跳表)、`backend/{local,registryfs_v2,tar}.rs` |
| **ublk** | `storage/ublk/` | ⭐ userspace 块设备。`lib.rs`(API)、`ctrl.rs`(`/dev/ublk-control`)、`dev.rs`/`queue.rs`、`io_buffer.rs`(零拷贝 `AutoRegBuffer` kernel 6.8+ / `UserBuffer`)、`impls/overlaybd_target.rs` |
| **ublk-daemon** | `storage/ublk-daemon/` | 单进程管理所有 ublk 设备,Unix socket RPC(`CreateOverlaybd`/`AcquireOverlaybd`/`RestackSnapshot`/`Shutdown` 等)。`client.rs`/`server.rs`/`protocol.rs` |
| **storage-util** | `storage/util/` | 共享 io_uring:`AsyncIoRing<S>`(slab Future)+ `IoRingWorker`(线程本地 ring)+ `ReloadableIDAllocator`(bitmap 复用) |
| uffd-core | `storage/uffd-core/` | userfaultfd 内存恢复(参考用,**不参与编译**) |

### 6.2 节点主体(`src/`,Rust)

| 模块 | 职责 | 关键文件 |
|---|---|---|
| `api/` | Axum HTTP + OpenAPI + 反向代理 | `src/api/openapi.yml`、`impls/`(sandbox/snapshot/template/auth/pagination)、`proxy.rs` |
| `orchestrator/` | ⭐ 生命周期状态机 + 自动驱逐 + 持久化 + 计数器 | `service.rs`(核心)、`store/{in_memory,metadata}`、`persistence/{mod,file_backed}`、`metrics.rs`、`proxy.rs` |
| `sandbox/` | ⭐ Firecracker VM + 网络 + envd + ublk | `firecracker/sandbox.rs`(主,带 stable `SandboxId`)、`firecracker/{connector,instance,manifest,factory,config,mmds,socket,overlaybd_snapshot,process_vm_reader}.rs`、`network/{manager,slot,address_plan,policy,egress_proxy,resolver,iptables_util}.rs`、`ublk/{device,overlaybd}.rs`、`extra_drive.rs`、`envd.rs`、`access.rs` |
| `snapshot/` | 提交快照模型 + 仓库后端 + 运行时解析 | `manager.rs`(`publish_captured`)、`repository/backends/{posixfs,oss}/`、`p2p.rs`、`runtime_support.rs`、`artifact_cache.rs`、`image_export/{service,regctl}.rs`、`types/{snapshot,drive,value,version}.rs` |
| `template/` | 模板构建器(声明式 RUN/ENV/WORKDIR) | `builder.rs`(build/rebuild)、`build_spec.rs`、`runner.rs`、`step_executor.rs` |
| `observability/` | 节点身份 + 主机指标 + 心跳上报 | `service.rs`、`reporter.rs`、`machine.rs`、`host.rs`、`identity.rs`、`prometheus.rs` |
| `p2p/` | P2P artifact 传输抽象 | `mod.rs`、`config.rs`、`types.rs`、`transport.rs`、`discovery/{mod,scheduler}.rs`、`iroh/{transport,catalog,endpoint}.rs` |
| `image/` | 镜像解析 + OCI 转换 | `resolver.rs`(`ImageResolver`)、`oci_image.rs`(`regctl manifest get`)、`reference.rs`、`cache/{mod,store,service,graph,source_config}.rs`、`commit_index.rs` |
| `overlaybd/` | overlaybd p2p facade + artifact | `p2p/{cache,facade,artifact}.rs`(`overlaybd-layer/v1/sha256:<digest>`) |
| `cfg.rs` + `cfg/` | TOML 配置 | `default.toml`、`network.rs`、`image.rs` |
| `setup/` | 主机依赖配置 | `mod.rs`、`kvm.rs`、`overlaybd.rs`、`deps.rs`、`packages.rs` |
| 其他 | `api_key.rs`、`digest.rs`、`identity.rs`、`local_store.rs`(RocksDB `LocalKvStore`)、`logging.rs`、`managed_secret.rs`、`privileges.rs`、`proto.rs`、`virtualization.rs`、`types/{image_configs,resources}.rs` |

入口:`src/bin/server.rs`(另有 `src/bin/aenv-snapshot-image.rs`,独立工具,不进 server 二进制)。

### 6.3 工具 crate(`crates/`)

| Crate | 用途 |
|---|---|
| `aenv` | ⭐ 原生 Rust CLI,包 HTTP API + envd Connect-RPC |
| `test-support` | 测试夹具(Minio via testcontainers) |
| `warm-pool` | 水位资源池(网络槽 + ublk 设备池共享) |
| `linux-cap` | Linux capability 检查 + 子进程授权(`scripts/run-with-capabilities.sh` 用) |
| `object-store-operator` | S3 兼容对象存储客户端 + 刷新凭证 |
| `shell-util` | `shell_quote` 参数转义(aenv + agentenv 用) |
| `observability` | 节点可观测性(被 src/ 用) |
| `benchmarks` | 性能基准(snapshot / ublk_overlaybd / orchestrator_store / oci_conversion_pipeline) |
| `e2e-tests` | E2E 测试(`snapshot_oss_e2e_test`) |

### 6.4 控制面(`services/`,Go)

| 服务 | 路径 | 读什么 |
|---|---|---|
| **gateway** | `services/gateway/` | HTTP 反向代理,header/host 路由,聚合 `GET /sandboxes`/`/v2/sandboxes`/`/nodes`,host-based `{port}-{sandboxID}.{domain}`(RFC 952/1123 DNS-label,≤63 字符) |
| **scheduler** | `services/scheduler/` | gRPC,节点发现(static/k8s EndpointSlice)、binding(in-memory 或 `redis_addr` 切 Redis)、心跳、P2P 索引、资源限额(`node_resource_limit`)、策略(round_robin 默认 / random) |
| — | `services/api/proto/scheduler.proto` | gRPC 契约:`Schedule`/`ListNodes`/`LookupNode`/`RecordAssignment`/`Heartbeat`/`ListObservedNodes`/`ReportSandboxEvent`/`GetNode`/`UnregisterNode` + P2P:`ListP2pPeers`/`RecordP2pArtifact`/`ForgetP2pArtifact`/`LookupP2pArtifact` |
| — | `services/shared/` | 配置 + 日志(console/json/auto) |

binding 生命周期:`RecordAssignment` 种 → 心跳 roster 刷新 → `binding_ttl` 过期清 → `UnregisterNode` 清该节点所有 binding。

### 6.5 生成代码(只读,别手改)

`thirdparty/firecracker-client`、`src/api/generated/`、`src/custom_extension_api/generated/` —— 改 schema 后用 `make firecracker-client` / `make agentenv-server` / `make custom-extension-client` 重新生成。`custom_extension` 生成器不自动删孤儿模型文件,schema 删字段后手动清。

---

## 阶段 7:API 与集成

**目标**:会用 API + E2B SDK 写程序。

1. `api/index.md` — Swagger UI 页面(实际 schema 在 `src/api/openapi.yml`)
2. `integration/e2b.md` — ⭐ E2B SDK 兼容(改环境变量即可)

### 核心节点 API(E2B 兼容)

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/sandboxes` | 创建沙箱(从 template) |
| POST | `/sandboxes-cold` | cold start(从 OCI image) |
| GET | `/sandboxes` | 列沙箱 |
| GET | `/sandboxes/{id}` | 沙箱元数据 |
| DELETE | `/sandboxes/{id}` | 删沙箱 |
| POST | `/sandboxes/{id}/pause` | 暂停(快照) |
| POST | `/sandboxes/{id}/resume` | 从快照恢复 |
| POST | `/sandboxes/{id}/fork` | 分叉(上限 16,带 `count`) |
| PUT | `/sandboxes/{id}/network` | 更新运行中沙箱 egress 规则 |
| GET/PUT/PATCH | `/sandboxes/{id}/custom-extension-params` | 自定义扩展参数 |
| GET | `/nodes` / `/nodes/{id}` | 节点可观测性 |
| ANY | `/proxy` `/proxy/{path}` | 反向代理到沙箱内服务 |

### E2B SDK 集成(来自 integration/e2b.md)

```bash
export E2B_API_URL=http://127.0.0.1:8000
export E2B_SANDBOX_URL=${E2B_API_URL}
export E2B_API_KEY=${AENV_API_KEY}
```

**Python**:
```bash
pip install e2b
```
```python
from e2b import Sandbox, SandboxQuery, SandboxState
sandbox = Sandbox.create("<template-id>")
running = Sandbox.list(limit=20, query=SandboxQuery(state=[SandboxState.RUNNING]))
print(running.next_items())
result = sandbox.commands.run("echo hello world")
print(result.stdout, end="")
sandbox.beta_pause()
sandbox.kill()
```

**TypeScript**:
```bash
npm install e2b
```
```typescript
import { Sandbox } from "e2b";
const sandbox = await Sandbox.create("<template-id>", { apiKey: process.env.E2B_API_KEY });
const running = Sandbox.list({ apiKey: process.env.E2B_API_KEY, limit: 20, query: { state: ["running"] } });
console.log(await running.nextItems());
sandbox.commands.run("echo hello world");
await Sandbox.Pause(sandbox.sandboxId, { apiKey: process.env.E2B_API_KEY });
await sandbox.kill();
```

**E2B CLI** 兼容,但官方推荐用 `aenv` CLI 走 AgentENV 工作流。

返回的 `trafficAccessToken`(私有入口,`e2b-traffic-access-token`)和 `envdAccessToken`(secure envd,`X-Access-Token`)header 不同、信任边界不同;公开入口无需 token。

---

## 阶段 8:测试与贡献

**目标**:会跑测试、能排错、能提 PR。

1. `troubleshooting/common-issues.md` — ⭐ 常见 6 大问题
2. `CONTRIBUTING.md` — 贡献规范
3. `SECURITY.md` — 漏洞私密披露
4. `CLAUDE.md` — ⭐ 架构 + 命令速览(开发向,必读)
5. 同目录 `agentenv.md` — 测试快速入门(已写)

### 常见排错(来自 common-issues.md)

| 症状 | 解决 |
|---|---|
| `/dev/kvm` missing | `ls -l /dev/kvm` 确认存在;`sudo usermod -aG kvm $USER`(重登);云 VM 无 KVM 走 `deployment/pvm.md` |
| 虚拟化模式不匹配 | 默认 KVM;PVM 主机需 `AENV_VIRTUALIZATION_MODE=pvm` |
| network 操作 permission denied | 需 `CAP_NET_ADMIN`+`CAP_SYS_ADMIN`(effective/permitted/inheritable);systemd unit 自动配;源码用 `make start-server` 或 `scripts/run-with-capabilities.sh`;**别整 root 跑 server** |
| `ip netns list` 看不到沙箱 ns | ns 挂在 `$AENV_RUNTIME_PATH/netns`(systemd 用 `/run/aenv/netns`),不在 `/var/run/netns`;用 `sudo nsenter --net=/run/aenv/netns/agentenv-ns-<slot> ip addr` |
| Config file not found | 默认找 `config/default.toml`,或 `export AENV_CONFIG_PATH=/path/to/config.toml` |
| Port already in use | `API_ADDR=0.0.0.0:8001 make start-server` |
| Sandbox creation timeout | 检查 runtime 资产(Firecracker/kernel/rootfs)已下载,`cargo run --bin server -- --setup-only` 手动预置看详细错误;大 rootfs 调大 `[envd].init_timeout_secs`(默认 60s) |

### 测试三层

| 类型 | 位置 | 跑法 | 依赖 |
|---|---|---|---|
| 单元 | `src/**/*.rs` `#[cfg(test)]` | `cargo test -p agentenv --lib <name>` | 编译期系统库(见下) |
| 集成 | `tests/integration/*.rs` | `make test-integration`(需 sudo + KVM) | root + `/dev/kvm` + 网络 ns + `AENV_CONFIG_PATH` |
| E2E | `crates/e2e-tests/` | `make test-e2e` | docker/k8s |

> 编译期坑(已踩,详见 `agentenv.md` 第 2.2 节):openEuler 上需 `dnf install -y openssl-devel clang-devel protobuf-compiler protobuf-devel`,并设 `LIBCLANG_PATH=/usr/lib64` + `BINDGEN_EXTRA_CLANG_ARGS="-isystem /usr/lib64/clang/17/include -isystem /usr/include"`。实测命令:
> ```bash
> LIBCLANG_PATH=/usr/lib64 \
> BINDGEN_EXTRA_CLANG_ARGS="-isystem /usr/lib64/clang/17/include -isystem /usr/include" \
> cargo test -p agentenv --lib api_key::tests::validation_enforces_length_and_url_safe_characters
> ```

### 常用命令

```bash
make            # 构建
make fmt        # rustfmt 检查
make clippy     # clippy -D warnings
make test       # 完整测试(agent + envd + ublk)
make test-unit  # 单元
make test-integration
make -C services test   # Go 控制面测试
make -C services build  # gateway + scheduler
make start-server       # 起节点 server(自动预置依赖)
make docs-serve         # 本地起 mdBook 文档站
# Go 单测:cd services && go test ./...
# Rust 单测按名:cargo test -p agentenv --lib <name>
# 集成单测:sudo -E cargo test -p agentenv --test integration <module>::<name>
```

### 贡献要点(来自 CONTRIBUTING.md)

- **环境前置**:Linux+KVM(x86_64)、Docker、Go 1.21+、Rust 1.75+(带 `x86_64-unknown-linux-musl` target)、protoc
- **PR 聚焦**:一 PR 一改动,别混 feature/refactor/依赖更新
- **新行为补测试**;改 schema 连同生成代码一起提交
- **改 `services/`** 额外跑 `make -C services test`
- **Conventional Commits**:`feat:` `fix:` `refactor:` `ci:` `chore:`(CLAUDE.md 还提 `docs:`)
- 推到 fork,PR 到 `kvcache-ai/AgentENV`,**别直推主仓**
- 安全漏洞走 `SECURITY.md`,**别开公开 issue**
- 代码风格:Rust rustfmt + clippy;Go gofmt;日志用 `info/debug/warn/error`,**只在 binary 入口初始化 tracing**

---

## 学习内容总清单(速查)

### A. 自带文档(32 篇,mdBook)

`docs/src/SUMMARY.md` 是目录。按主题分组:

- **Getting Started**(4):overview / quickstart / on-demand-loading / aenv-cli
- **Deployment**(6):docker / docker-compose / static-multi-node / kubernetes / manual-compile / pvm
- **Configuration**(2):reference / env-vars
- **Security**(2):authentication / secure-sandboxes
- **Core Concepts**(6):overview / templates / sandboxes / snapshots / custom-extension / proxy
- **API**(1):index(Swagger UI,实际 schema 在 `src/api/openapi.yml`)
- **Integration**(1):e2b
- **Troubleshooting**(1):common-issues
- **Developer Internals**(8):architecture / networking / sandbox-testing / template-builder-testing / persistence-artifact-inventory / proxy-design / services / p2p-design

本地起文档站:`make docs-serve`(mdBook)。

### B. Workspace Crate(14 个,Rust + Go)

Rust(`Cargo.toml`):agentenv(根)/ adev(工具)/ aenv(CLI)/ linux-cap / object-store-operator / test-support / shell-util / warm-pool / observability / benchmarks / e2e-tests + storage 四件套(overlaybd/ublk/ublk-daemon/util)+ 3 个生成包(firecracker-client/envd/agentenv_http_server/custom_extension_client)。

Go(`services/go.mod`):gateway / scheduler / shared。

### C. 关键配置文件

| 文件 | 作用 |
|---|---|
| `config/default.toml` | 默认配置(361 行,全配置都在这) |
| `config/deps_manifest.toml` | 依赖版本 + 下载 URL(Firecracker/kernel/工具盘) |
| `rust-toolchain.toml` | stable 工具链 |
| `Cargo.toml` | workspace 定义 |
| `Makefile` | 所有构建/测试/部署入口 |
| `src/api/openapi.yml` | HTTP API schema(生成 server) |
| `src/custom_extension_api/openapi.yml` | 扩展 hook schema |
| `services/api/proto/scheduler.proto` | gRPC 契约 |
| `thirdparty/firecracker-client/firecracker.yaml` | Firecracker API schema |
| `deploy/docker-compose.yml` | 多节点 compose |
| `deploy/k8s/overlays/default` | K8s Kustomize 默认 overlay |

### D. 核心术语表

| 术语 | 含义 |
|---|---|
| overlaybd | LSMT 层叠镜像格式,自研 |
| ublk | Linux 内核 userspace 块设备驱动 |
| LSMT | Log Structured Merge Tree,overlaybd 的层叠机制 |
| `DiskSegmentMapping` | 16 字节 bit-packed:50-bit voffset + 14-bit len + 55-bit poffset + flag + tag |
| Firecracker | AWS 的 microVM 监控器 |
| envd | 沙箱内 init 系统,负责命令执行/进程管理/文件操作 |
| MMDS | Firecracker 的元数据服务(169.254.169.254),给 envd 传沙箱/快照身份 |
| Template | 从镜像构建的基线快照(UUID + 可选别名) |
| Snapshot | pause 时的内存+盘状态;三层存储(builder staging / committed 仓库 / node-local runtime cache) |
| Fork | 一个运行中沙箱分叉成多个(上限 16),各派生独立凭证 |
| Warm/Cold Start | warm=从模板恢复快照;cold=从 OCI 镜像运行时转 |
| warm-pool | 预热资源池(网络槽/Firecracker 进程/ublk 设备),水位 low→high 几何增长 |
| restack | 快照时把 upper 转为 lower 并开新 upper(`close_seal + restack`) |
| PVM | KVM 不可用时的替代虚拟化模式(x86_64 + kvm_pvm 模块) |
| trafficAccessToken | 数据面私有入口令牌(`e2b-traffic-access-token` header) |
| envdAccessToken | secure envd 访问令牌(`X-Access-Token` header) |
| `AENV_SANDBOX_ACCESS_TOKEN_HASH_SEED` | 派生两类沙箱 token 的 seed,多节点必须共享 |
| Custom Extension | 可选外部 HTTP hook 服务(start-fresh/start-resume/patch-params/stop) |
| EgressProxy | namespace-local 透明代理(0.0.0.0:15000),不终止 TLS/不重写 HTTP |
| iroh-blobs | P2P backend 的 content-addressed blob 存储 |

---

## 推荐学习顺序(4 周计划)

| 周 | 重点 | 产出 |
|---|---|---|
| **W1** | 阶段 0+1+2:补基础 + 概念 + 跑通单机 | 能用 `aenv` CLI 起停沙箱,能画架构图 + 8 态生命周期 |
| **W2** | 阶段 3+4:部署 + 配置/安全 | 能用 docker-compose 部署多节点,会改配置,懂三凭证 + 网络策略优先级 |
| **W3** | 阶段 5:架构深入 | 读完 architecture.md + networking.md + proxy-design.md + p2p-design.md,能默画 block/memory 数据流 + 网络拓扑 + 包路径 |
| **W4** | 阶段 6+7+8:代码精读 + API + 测试 | 跑通单元测试,用 E2B Python SDK 写一个起停沙箱程序,能改一个小功能提 PR |

### 每周自检(带答案)

- **W1**:sandbox 和 template 的关系?为什么需要 snapshot?
  A:template 是快照的 UX 包装(一个 template build commit 一个快照);sandbox 从 template resume;snapshot 是持久化原语(pause 状态),让暂停/恢复/fork 成为可能。
- **W2**:gateway 怎么路由一个已有沙箱的请求?scheduler 挂了会怎样?
  A:gateway 调 `LookupNode`(binding 表)找到 owning node 转发;scheduler 挂——内存版 binding 丢(新 sandbox 创建失败,已有 sandbox 数据面 LookupNode 失败);Redis 版 + query-only 副本则数据面不中断(控制面仍依赖主)。
- **W3**:overlaybd 读一个块时怎么找到数据?memory snapshot resume 为什么快?
  A:层栈 top-down 搜 `DiskSegmentMapping`,首个含该块范围的层服务数据,未映射则穿透下层;resume 快=Firecracker mmap 只读 ublk 内存设备 + COW + 多沙箱共享 mem ublk 复用 page cache。
- **W4**:写一个单元测试(参考 `src/api_key.rs` 的 `#[cfg(test)] mod tests`)并跑通;用 E2B Python SDK 写一个 create→run→pause→kill 程序。

---

## 进阶方向(学完基础后)

- **性能**:读 `crates/benchmarks/`,跑 `make bench` / `bench-snapshot` / `bench-ublk` / `bench-orchestrator-store` / `bench-oci-conversion`(OCI_IMAGE=...),理解快照/ublk/oci 转换性能基线
- **P2P**:读 `docs/src/internals/p2p-design.md` + `src/p2p/iroh/`,理解 iroh-blobs content-addressed fetch + GC 门控 + catalog ALPN
- **自定义扩展**:读 `concepts/custom-extension.md` + `src/custom_extension_api/`,写一个 start/stop hook(参考文档里的 FastAPI 最小示例)
- **控制面 HA**:读 `services/README.md` 的 Redis + query-only scheduler 部分(`--query-only` + `gateway.query_only_scheduler_addr`);注意 HA 是数据面 only,控制面仍依赖主
- **镜像生态**:理解 `regctl` + `umoci` + overlaybd-native OCI 镜像发布(`src/bin/aenv-snapshot-image.rs`,`make build-snapshot-image`);OCI Referrers API(`try_referrers_overlaybd_prefixes`)发现 overlaybd-native artifact
- **Firecracker 升级**:读 `internals/sandbox-testing.md` 的升级清单——改 `thirdparty/firecracker-client/firecracker.yaml`→`make firecracker-client`→打包 `firecracker-{version}-{arch}.tgz`→改 `config/deps_manifest.toml`
- **OSS 镜像发布**:`[snapshot.image_publish].enabled=true`(仅 oss 后端),把 rootfs 推回原 registry 作 `agentenv-snapshot-{id}` tag,增量(已有层按 digest 引用,只推新 delta)
- **内存快照压缩 + 后台下载**:`[memory_snapshot].compression_algorithm=lz4|zstd` + `[memory_snapshot.background_download]` 的 block_size/concurrency/max_inflight_blocks,理解 16MiB chunk 对齐 + 并发上限的内存占用(`max_inflight_blocks × block_size`)
- **warm pool 调优**:`[pool]` 水位 + `[pool.firecracker].fill_concurrency` + `[pool.block].startup_prewarm`(kernel 不支持 `UBLK_F_UPDATE_SIZE` 时禁用)

---

## 附:关键文件索引(读代码时对照)

| 路径 | 是什么 |
|---|---|
| `README.md` | 项目门面,Quick Start |
| `CLAUDE.md` | ⭐ 架构 + 命令速览(开发向,最实用) |
| `CONTRIBUTING.md` | 贡献规范 |
| `Cargo.toml` | workspace 根 |
| `Makefile` | 构建测试部署入口 |
| `config/default.toml` | 默认配置(361 行) |
| `config/deps_manifest.toml` | 依赖版本 + 下载 URL |
| `src/lib.rs` | 主 crate 21 个顶层模块导出 |
| `src/bin/server.rs` | 节点二进制入口 |
| `src/bin/aenv-snapshot-image.rs` | 独立快照镜像发布工具(不进 server) |
| `src/api/openapi.yml` | HTTP API schema |
| `docs/src/SUMMARY.md` | 文档目录 |
| `services/README.md` | Go 控制面文档(最详) |
| `services/api/proto/scheduler.proto` | gRPC 契约 |
| `tests/common/mod.rs` | 集成测试共享夹具 |
| `tests/integration.rs` | 集成测试入口 |
| `agentenv.md`(同目录) | 快速入门 + 测试入门 |
