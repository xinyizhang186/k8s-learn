# pprof-export

面向生产环境的 Go runtime pprof 自动导出库。集成到业务进程后，当出现 **内存压力** 或收到 **SIGUSR2 信号** 时，自动把 `runtime/pprof` 数据落盘，便于事后离线分析内存泄漏、goroutine 泄漏与 CPU 热点。

- **零侵入**：启动时调用一次 `pprof.ActivePProf(ctx, prefix)` 即可
- **双触发**：内存压力自动触发 + SIGUSR2 信号主动触发
- **cgroup v1/v2 自适应**：按进程所属 cgroup 内存用量判定压力，无需手动配置
- **自动清理**：按时间戳分批，仅保留最近 2 批
- 仅依赖标准库与 `golang.org/x/sys`

---

## 1. 快速入手

进程启动时调用一次，`ctx` 取消即停止所有 trigger：

```go
import (
    "context"
    "pprof-export/pprof"
)

func main() {
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()
    pprof.ActivePProf(ctx, "openfuyao")
    // ... 业务逻辑 ...
}
```

---

## 2. 触发与导出

两种触发器启动后同时运行。对应 5 种 profile：**CPU / Heap / Block / Mutex / Goroutine**。

| 触发器 | 导出范围 | 触发条件 |
|--------|----------|----------|
| **内存压力** | Heap + Goroutine | cgroup 实际用量超阈值（usage 剔除可回收的 `inactive_file`） |
| **SIGUSR2** | 全部 5 种 | 收到信号即导出（`kill -USR2 <pid>`），CPU 采样 15s |

> 内存触发只取 Heap + Goroutine：告警要求立即取证，高压下采样 CPU 会加剧压力；信号触发导出全套，便于人工介入时拿完整快照。

**输出**：文件写入 `${HW_PROFILING_PATH}`（默认 `/opt/dump/coredump`），命名 `{prefix}-{YYYYMMDD-HHMMSS}-{type}.profile`，按时间戳分批仅保留最近 2 批。

> Block / Mutex 需在进程启动时调用 `runtime.SetBlockProfileRate(n)` / `runtime.SetMutexProfileFraction(n)`（n>0）开启采样，否则这两个文件为空。

---

## 3. 配置

全部通过环境变量，未设置时用默认值。对应 §2 中的阈值与增量：

| 变量名 | 默认值 | 含义 |
|--------|--------|------|
| `HW_PROFILING_PATH` | `/opt/dump/coredump` | profile 输出目录 |
| `HW_PROFILING_CHECK_INTERVAL` | `1` (秒) | 内存压力检查周期 |
| `HW_PROFILING_ALERT_MEM` | `0` | 剩余内存低于该值（MiB）即触发，**优先级高于百分比** |
| `HW_PROFILING_ALERT_PERCENT` | `0.8` | 使用率超该值即触发（`ALERT_MEM` 未设置时生效） |
| `HW_PROFILING_MEMERY_INCREMENT` | `0.08` | 持续告警时再次导出所需的最小内存增量（相对 limit） |

> `ALERT_MEM` 与 `ALERT_PERCENT` 同时为 0 时自动回退到 `0.8`。`MEMERY_INCREMENT` 拼写沿用代码原始命名，保持向后兼容。

---

## 4. cgroup 兼容性

通过 `statfs(/sys/fs/cgroup)` 判断是否为 `CGROUP2_SUPER_MAGIC` 自动识别版本，无需配置：

| 模式 | usage | limit | stat |
|------|-------|-------|------|
| **v2** | `/sys/fs/cgroup/memory.current` | `/sys/fs/cgroup/memory.max` | `/sys/fs/cgroup/memory.stat` |
| **v1** | `/sys/fs/cgroup/memory/memory.usage_in_bytes` | `/sys/fs/cgroup/memory/memory.limit_in_bytes` | `/sys/fs/cgroup/memory/memory.stat` |

非 Linux 平台为空实现桩，可编译但不读取内存。

---

## 5. 分析 profile

导出的 `.profile` 文件用标准工具直接分析：

```bash
go tool pprof -top /opt/dump/coredump/openfuyao-20260728-090358-heap.profile   # 文本摘要（路径为示例）
go tool pprof    /opt/dump/coredump/openfuyao-20260728-090358-heap.profile      # 交互式
```

---

## 6. 仓库结构

```
pprof-export-master/
├── pprof/
│   ├── facade.go        # ActivePProf()：组装 exporter + triggers
│   ├── exporter/        # 并发写文件 + 按批清理
│   ├── names/           # Profile 名称枚举
│   └── trigger/         # 内存压力 / SIGUSR2 触发器
├── util/
│   ├── cgroups/         # cgroup v1/v2 路径自动识别
│   └── env/             # 环境变量读取
├── log/                 # 日志
├── main.go              # 演示程序（见下，非库本体）
└── go.mod / go.sum
```

`go test ./...` 共 29 个测试函数全部 PASS。

---

## 7. 演示程序

`main.go` 是冒烟测试，非库的一部分：创建 100MB 限制的测试 cgroup、分配内存制造压力，验证触发链路。集成到 openfuyao 时无需关心。

```bash
timeout 40 go run main.go   # 通过 util/cgroups 的 IsCgroup2UnifiedMode() 自动探测 cgroup 版本
```
