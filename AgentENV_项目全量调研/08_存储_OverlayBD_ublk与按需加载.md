# AgentENV：存储、OverlayBD、ublk 与按需加载

> 调研日期：2026-08-31  
> 范围：AgentENV 官方 `latest` 文档、GitHub 主仓库与 Releases。  
> 版本提示：tagged release 与 `main/latest` 请分开理解。

## 1. 为什么存储是核心

传统：

```text
pull full image
→ unpack
→ create rootfs
→ start
```

AgentENV：

```text
OCI Image
→ block-addressable layers
→ on-demand fetch
→ bounded local cache
→ Firecracker block device
```

这非常适合巨大的环境镜像 catalog。

## 2. ublk

ublk 是 Linux 用户态块设备机制。

```text
Firecracker /dev/vda
      ↓
Linux ublk
      ↓
AgentENV userspace block server
      ↓
OverlayBD / snapshot / remote backend
```

Firecracker 因而无需理解 OCI Registry、对象存储等具体后端。

## 3. OverlayBD Layer

读：

```text
read(offset)
→ newest layer
→ older layer
→ ...
→ base image
```

写：

```text
write → current writable upper
```

Snapshot：

```text
writable upper
→ seal
→ readonly snapshot layer
→ new writable upper
```

## 4. VirtualFile Backend

源码设计包含不同数据来源，例如：

- LocalFile；
- OCI registry；
- tar；
- remote blocks；
- compressed blocks。

Local I/O 可结合 io_uring；底层还有随机访问压缩/校验相关实现。

## 5. On-Demand Loading

```text
Guest block read
      ↓
OverlayBD lookup
      ↓
local cache?
  ├─ hit → return
  └─ miss
       ↓
 registry / object store
       ↓
      cache
       ↓
     return
```

优点：

- 不需完整预拉镜像；
- 大 image catalog；
- 本地磁盘可有界；
- 热块可复用。

代价：

- cold miss 受网络影响；
- remote backend latency 很关键；
- cache sizing 决定 tail latency。

## 6. Cache

当前 main 默认配置可见的量级：

- image cache：约 100GiB；
- remote block cache：约 100GiB。

GC 参数包括：

```text
enabled
interval
min_age
high_watermark
low_watermark
```

当前默认可见约为：

```text
interval 1800s
min age 600s
high 0.95
low 0.70
```

这些只是默认，不是容量规划答案。

## 7. Snapshot Backend

### POSIXFS

简单直观，但 NFS/共享 FS metadata/throughput 可能成为瓶颈。

### OSS/S3-compatible

扩展性更自然，但受 request latency、对象存储吞吐、网络和 credential 管理影响。

## 8. Memory Snapshot

AgentENV 也把 VM memory 做成可分层 Artifact：

```text
base memory
→ dirty/present ranges
→ incremental memory layer
```

关键点：

- dirty-page tracking；
- 只保存变化；
- parent layer reuse；
- readonly ublk memory device；
- Host Page Cache sharing。

## 9. Background Download

当前 main config 包含 memory snapshot background download，配置维度包括：

- enabled；
- block size；
- concurrency；
- max inflight。

目标是让启动不一定等待整个远端 memory artifact 完整下载。

## 10. Memory Compression

Release/config 中出现 ZFile/LZ4 等 memory snapshot compression 能力。当前 main 默认 compression 是关闭状态，不能只看到算法参数就认为默认启用。

## 11. 性能瓶颈

```text
registry latency
object store throughput
network
local NVMe IOPS
ublk queue
OverlayBD lookup
snapshot compression CPU
page faults
dirty rate
cache eviction
```

AgentENV 并没有消灭 I/O，而是通过延迟读取与共享降低重复工作。

## 12. 调优

- 高频 Template 预热；
- Registry/Snapshot backend 与 Node 同 Region/AZ；
- 10GbE+ 大规模网络；
- NVMe cache；
- 监控 cache hit ratio；
- 管理 snapshot layer depth；
- 监控 remote read amplification；
- 调整 GC 与 watermark。

## 官方来源

- https://kvcache-ai.github.io/AgentENV/latest/
- https://github.com/kvcache-ai/AgentENV/tree/main/storage
- https://github.com/kvcache-ai/AgentENV/blob/main/config/default.toml
