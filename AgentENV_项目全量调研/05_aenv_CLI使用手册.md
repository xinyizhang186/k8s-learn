# AgentENV：`aenv` CLI 使用手册

> 调研日期：2026-08-31  
> 范围：AgentENV 官方 `latest` 文档、GitHub 主仓库与 Releases。  
> 版本提示：tagged release 与 `main/latest` 请分开理解。

> CLI 仍在演进，本文用于建立命令地图；具体 flags 以所安装版本的 `aenv --help` 和子命令 `--help` 为准。

## 1. CLI 覆盖范围

`aenv` 主要用于：

- 认证/连接 Runtime；
- Pull/Build Template；
- Start/List/Connect/Exec Sandbox；
- Pause/Resume/Timeout/Delete；
- Upload/Download；
- Snapshot 管理。

## 2. 帮助

```bash
aenv --help
aenv <command> --help
```

固定 release 时，应优先相信当前二进制帮助，而不是 main 文档。

## 3. Pull Template

```bash
aenv pull ubuntu:24.04
```

用于把 OCI Image 转成/注册为可复用环境。可围绕 name、CPU、memory、start command、ready command/probe、timeout 等设置。

## 4. Build Template

```bash
aenv build ...
```

适合把 apt/pip/npm 依赖、编译工具、测试 Harness、Agent 工具提前构建进环境，降低每次 Sandbox 启动后的 setup 成本。

## 5. Start

Warm：

```bash
aenv start <template-or-snapshot>
```

常见方向：

```text
--secure
--timeout
--detach
```

Cold：

```bash
aenv start --cold ubuntu:24.04
```

Cold start 可指定更明确的 CPU/memory/disk。

## 6. List

```bash
aenv ls
```

用于查看 Sandbox 状态。自动化场景优先使用结构化/JSON 输出（若当前版本子命令支持）。

## 7. Connect

```bash
aenv connect <sandbox-id>
aenv cn <sandbox-id>
```

适合交互式调试。目标 Paused 时可自动触发 resume。

## 8. Exec

```bash
aenv exec <sandbox-id> -- bash -lc 'uname -a'
aenv exec <sandbox-id> -- python -V
```

Agent Tool/CI 更适合 one-shot exec，而不是人工 Shell。

## 9. Pause / Resume

```bash
aenv pause <sandbox-id>
aenv resume <sandbox-id>
```

适合保留会话状态但停止执行。

## 10. Timeout

```bash
aenv timeout <sandbox-id> ...
```

需要联合理解：

```text
timeout + autoPause
```

决定到期后是 Pause 还是 Delete。

## 11. Delete

```bash
aenv delete <sandbox-id>
```

删除 Sandbox 是永久操作，但独立创建的 Snapshot 不会因为源 Sandbox 删除而自动消失。

## 12. Upload / Download

典型概念：

```bash
aenv upload <sandbox-id> <local> <remote>
aenv download ...
```

目录 upload 不完整保留 POSIX metadata，详见生命周期文档。

## 13. Snapshot

```bash
aenv snapshot create <sandbox-id>
```

当前 CLI 还围绕 Snapshot list/delete 等提供管理能力，精确命令名以对应版本帮助为准。

## 14. 一条完整操作链

```bash
aenv pull ubuntu:24.04
aenv start <template>
aenv ls
aenv exec <sandbox-id> -- bash -lc 'uname -a'
aenv cn <sandbox-id>
aenv snapshot create <sandbox-id>
aenv pause <sandbox-id>
aenv resume <sandbox-id>
aenv delete <sandbox-id>
```

## 15. CLI 与 API 的分工

- 人工开发/Debug：CLI
- Agent/平台生产接入：E2B SDK 或 AgentENV HTTP API

生产 API Client 更适合处理 timeout、retry、concurrency、structured errors 和 tracing。

## 官方来源

- https://kvcache-ai.github.io/AgentENV/latest/
- https://github.com/kvcache-ai/AgentENV/tree/main/crates/aenv
