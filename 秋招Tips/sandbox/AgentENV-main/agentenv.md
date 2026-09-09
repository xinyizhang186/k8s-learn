# AgentENV 测试快速入门

> 本文档基于仓库现有代码梳理而成，帮助你从零写出一个能跑起来的测试。
> 所有命令默认在仓库根目录 `AgentENV-main/` 下执行。

---

## 1. 项目一句话简介

AgentENV (AENV) 是一个 Rust 工作区，基于 Firecracker microVM 在大规模下运行 AI agent 沙箱环境，支持快照/分叉，并对外暴露 E2B 兼容的 HTTP API。

- 语言 / 工具链：Rust 2021 edition，stable 工具链（见 `rust-toolchain.toml`）
- 构建系统：`cargo` + `make`（Makefile 封装常用命令）
- 控制面另有 Go 模块 `services/`（gateway + scheduler），本指南聚焦 Rust 侧

---

## 2. 环境准备

### 2.1 基础（写单元测试就够了）

```bash
# 确认 rust 工具链（仓库自带 rust-toolchain.toml，会自动选择 stable）
rustc --version
cargo --version
```

### 2.2 编译期系统依赖（必装，否则单元测试也编不过）

仓库虽是纯 Rust，但若干 `-sys` crate 和 codegen 需要系统库/工具。在 openEuler/CentOS 系发行版上实测需要以下四个包（Ubuntu 对应 `libssl-dev libclang-dev clang protobuf-compiler libprotobuf-dev`）：

```bash
sudo dnf install -y openssl-devel clang-devel protobuf-compiler protobuf-devel
```

装完还需要两个环境变量（建议写进 `.envrc` 或 shell rc）：

```bash
# bindgen 找 libclang
export LIBCLANG_PATH=/usr/lib64
# clang builtin headers 位置（含 stdbool.h 等），libclang 默认不一定加载
export BINDGEN_EXTRA_CLANG_ARGS="-isystem /usr/lib64/clang/17/include -isystem /usr/include"
# protoc 默认从 /usr/include 找 google/protobuf/*.proto well-known types
```

> 坑点速查（按报错对应）：
> - `Could not find openssl via pkg-config` → 缺 `openssl-devel`
> - `Unable to find libclang` → 缺 `clang-devel`，或没设 `LIBCLANG_PATH`
> - `fatal error: 'stdbool.h' file not found`（librocksdb-sys） → 设 `BINDGEN_EXTRA_CLANG_ARGS` 指向 clang 的 `include/` 目录（如 `/usr/lib64/clang/17/include`）
> - `protoc failed: google/protobuf/timestamp.proto: File not found`（envd） → 缺 `protobuf-compiler` + `protobuf-devel`（well-known types `.proto` 在 `/usr/include/google/protobuf/`）

首次编译依赖众多（rocksdb / io-uring / ublk-sys / iroh 等），约需 **10 分钟**，后续增量编译很快。

### 2.3 跑集成测试才需要的条件

集成测试会真正起 Firecracker microVM，要求更重（**单元测试不需要这些**）：

- Linux 内核 6.8+
- `/dev/kvm` 可访问
- **root 权限**（需要 network namespace）
- 主机模块匹配 `AENV_VIRTUALIZATION_MODE`（默认 `kvm`）
- 需要先准备测试依赖状态目录：
  ```bash
  make prepare-agent-test-state   # 运行 server --setup-only 预置依赖
  ```

> 如果你的环境不满足，**先从单元测试入手**，单元测试不需要 KVM/root。

### 2.4 常用 Make 目标速查

| 命令 | 作用 |
|---|---|
| `make` | 构建整个 workspace |
| `make fmt` | rustfmt 检查 |
| `make clippy` | clippy（`-D warnings`） |
| `make test` | 完整测试套件（agent + envd + ublk） |
| `make test-unit` | 仅单元测试 |
| `make test-integration` | 集成测试（`tests/integration/*.rs`） |
| `make test-e2e` | E2E 测试（docker-compose/k8s） |

---

## 3. 三种测试类型概览

仓库里测试分三层，难度/依赖递增：

| 类型 | 位置 | 运行命令 | 依赖 | 适合测什么 |
|---|---|---|---|---|
| **单元测试** | `src/**/*.rs` 内 `#[cfg(test)] mod tests` | `cargo test -p agentenv --lib <name>` | 无特殊依赖 | 纯逻辑、解析、校验、数据结构 |
| **集成测试** | `tests/integration/*.rs` | `make test-integration` | root + KVM + 网络 | 真实起 VM、沙箱生命周期、快照 |
| **E2E 测试** | `crates/e2e-tests/tests/*.rs` | `make test-e2e` | docker/k8s + 测试夹具 | OSS 后端、端到端发布 |

**最快入门路径：从单元测试开始。** 下面给出可直接复制运行的例子。

---

## 4. 快速入门：写一个单元测试（推荐起点）

单元测试就内嵌在源文件里，用 `#[cfg(test)] mod tests` 包裹。参考实例如 `src/api_key.rs`、`src/identity.rs`、`src/digest.rs`。

### 4.1 在现有模块里加一个测试

假设你给 `src/digest.rs` 加一个测试。先看该文件结构，然后在文件末尾加：

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_is_hex_sha256() {
        // 用一个已知输入，断言输出符合预期
        let input = b"hello world";
        let got = super::sha256_hex(input); // 调用该模块里真实的函数
        // sha256("hello world") 的标准结果：
        assert_eq!(got, "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9");
    }
}
```

> 注意：上面是示意，请用 `read src/digest.rs` 确认函数真实签名后再写断言。

### 4.2 完整可运行示例（自包含，无需 KVM）

如果你想立刻看到一条 `ok`，新建一个 crate 内的测试模块最简单。以 `src/types/` 下的纯数据逻辑为例，你可以这样写一个不依赖任何外部资源的单元测试：

```rust
// 在某个 src/**/*.rs 文件末尾加：
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn smoke_test_addition() {
        // 最简单的冒烟测试，确认测试机制本身能跑
        assert_eq!(2 + 2, 4);
    }
}
```

### 4.3 运行

> 下面所有 `cargo test` 命令前都要带上 2.2 节的两个环境变量（`LIBCLANG_PATH`、`BINDGEN_EXTRA_CLANG_ARGS`）。本机实测可直接跑通的最小命令是：

```bash
# 实测可跑通的单个单元测试（首次编译约 10 分钟，之后秒级）
LIBCLANG_PATH=/usr/lib64 \
BINDGEN_EXTRA_CLANG_ARGS="-isystem /usr/lib64/clang/17/include -isystem /usr/include" \
cargo test -p agentenv --lib api_key::tests::validation_enforces_length_and_url_safe_characters
# 预期输出：test api_key::tests::validation_enforces_length_and_url_safe_characters ... ok
#           test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 771 filtered out
```

其余常用写法：

```bash
# 跑全部单元测试（带环境变量前缀，下同）
make test-unit
# 等价于（部分）：
cargo test -p agentenv --lib

# 只跑某个测试（按名匹配）
cargo test -p agentenv --lib digest
cargo test -p agentenv --lib tests::smoke_test_addition

# 显示 println! 输出
cargo test -p agentenv --lib -- --nocapture
```

> 部分单元测试需要网络/能力，仓库用 `#[ignore]` 标记，需 `--ignored` 显式触发，普通 `cargo test` 会跳过它们。被忽略的能力测试由 Makefile 用 `scripts/run-with-capabilities.sh` 包装执行。

---

## 5. 进阶：写一个集成测试（需要 KVM/root）

集成测试位于 `tests/integration/*.rs`，通过 `tests/integration.rs` 用 `#[path]` 引入各子模块。共享夹具在 `tests/common/mod.rs`。

### 5.1 关键基础设施（`tests/common/mod.rs` 提供）

| 函数 | 作用 |
|---|---|
| `common::setup().await` | 初始化日志、配置、全局 ublk 管理器，并解析默认 rootfs 镜像。**每个集成测试开头都要调一次** |
| `common::setup_runtime_only().await` | 同上但不解析镜像 |
| `common::default_sandbox_config()` | 返回默认 FirecrackerSandboxConfig |
| `common::default_rootfs_template_build_spec()` | 返回默认模板构建 spec |
| `common::snapshot_test_parts(root)` | 返回 (TemplateBuilder, SnapshotManager, repository) |

### 5.2 现成模板（抄 `tests/integration/process.rs` 的写法）

```rust
use crate::common;
use std::collections::HashMap;
use agentenv::sandbox::{FirecrackerSandbox, ProcessOpts, SandboxExecutor, Signal};
use anyhow::Result;
use tokio::time::Duration;

const TEST_TIMEOUT: Duration = Duration::from_secs(60);

async fn start_sandbox() -> Result<FirecrackerSandbox> {
    let sandbox_config = common::default_sandbox_config()?;
    let mut sandbox = FirecrackerSandbox::new(sandbox_config)?;
    sandbox.start().await?;
    Ok(sandbox)
}

#[tokio::test]
async fn my_first_integration_test() -> Result<()> {
    common::setup().await;                         // 1. 必须先 setup
    tokio::time::timeout(TEST_TIMEOUT, async {    // 2. 套超时
        let mut sandbox = start_sandbox().await?;  // 3. 起沙箱

        let output = sandbox.run_command("echo", &["hello"]).await?;
        assert_eq!(output.exit_code, 0);
        assert!(output.stdout.contains("hello"));

        sandbox.stop().await?;                     // 4. 记得清理
        Ok(())
    })
    .await
    .map_err(|_| anyhow::anyhow!("test timed out"))?
}
```

### 5.3 把新测试文件挂进测试入口

集成测试通过 `#[path]` 引入。在 `tests/integration.rs` 里加一行：

```rust
#[path = "integration/my_test.rs"]
mod my_test;
```

新建文件 `tests/integration/my_test.rs` 写上面的代码即可。

### 5.4 运行

```bash
# 完整集成测试（会自动 prepare-agent-test-state + 编译 ublk daemon + 用能力包装器跑）
make test-agent-integration

# 只跑一个用例（注意 sudo -E 保留环境变量）
sudo -E cargo test -p agentenv --test integration -- my_first_integration_test
```

`sudo -E` 很关键：`CAPABILITY_TEST_ENV` 注入的 `AENV_HOME_PATH` 等环境变量必须保留，否则测试找不到运行时状态目录。

### 5.5 orchestrator 集成测试单独入口

`tests/orchestrator_integration.rs` 是独立测试目标，因为它会永久停止进程级运行时管理器，不能和别的沙箱测试共享进程。新写 orchestrator 相关测试挂到它里面的 `tests/integration/orchestrator.rs`。

---

## 6. E2E 测试（最高层，端到端）

- 位置：`crates/e2e-tests/tests/`（如 `snapshot_oss_e2e_test.rs`）
- 依赖：`crates/test-support` 提供 Minio 夹具（基于 testcontainers）
- 运行：`make test-e2e`（背后是 `scripts/tests/e2e/run_e2e.sh`）
- 可选 compose/k8s 模式：`make test-e2e-compose` / `make test-e2e-k8s`
- 注意：snapshot OSS e2e 用 `#[ignore]` 标记，Makefile 用 `--ignored` 触发

E2E 通常由维护者写，新手不需要从这里入门。

---

## 7. 运行单个测试的通用速记

```bash
# 单元测试（无特殊依赖）
cargo test -p agentenv --lib <test_name>

# 集成测试（需要 root + KVM）
sudo -E cargo test -p agentenv --test integration <module>::<test_name>
sudo -E cargo test -p agentenv --test orchestrator_integration orchestrator::<test_name>

# 显示输出 / 跑被忽略的
cargo test ... -- --nocapture
cargo test ... -- --ignored
```

`-p agentenv` 指定主 crate；其他 crate（如 ublk、overlaybd）用 `-p uvm-ublk`、`-p overlaybd` 等。

---

## 8. 调试技巧

1. **看不到 println?** 加 `--nocapture`。
2. **集成测试超时/卡住?** 检查是否漏了 `common::setup().await`，或 `sudo -E` 没加导致环境变量丢失。
3. **找不到 /dev/kvm?** 说明你不适合在本机跑集成测试，先用单元测试；或用官方 Docker：`docker run -d --name aenv-server --privileged -v /dev:/dev -p 8000:8000 ghcr.io/kvcache-ai/aenv-server:latest`。
4. **改了 OpenAPI / proto?** 生成代码在 `thirdparty/`、`src/api/generated/`、`src/custom_extension_api/generated/`，**不要手改**，用：
   ```bash
   make firecracker-client        # 重新生成 Firecracker 客户端
   make envd-http-client          # 重新生成 envd 客户端
   make agentenv-server           # 重新生成 Axum server
   make custom-extension-client
   ```
5. **测试要写文件?** 用 `tempfile::TempDir` 隔离，参考 `src/api_key.rs` 里的 `tests` 模块。

---

## 9. 编码与提交约定

来自 `CLAUDE.md` / `CONTRIBUTING.md`：

- Rust 2021，改动的代码必须 **rustfmt-clean + clippy-clean**（`make fmt && make clippy`）
- 日志：`info` 生命周期 / `debug` 内部状态切换 / `warn` 可恢复 / `error` 不可恢复；**只在 binary 入口初始化 tracing**
- Conventional Commits：`feat:` `fix:` `refactor:` `ci:` `chore:`
- 新行为要补测试；改了 schema 要连同重新生成的输出一起提交
- PR 推到 fork，不直接推到 `kvcache-ai/AgentENV`
- 安全漏洞走 `SECURITY.md` 私密流程，**不要在公开 issue 披露**

---

## 10. 第一次写测试的推荐动作清单

1. `make` 确认能编译
2. `cargo test -p agentenv --lib` 跑通现有单元测试，确认环境 OK
3. 挑一个你想覆盖的 `src/**/*.rs` 模块，在文件末尾加 `#[cfg(test)] mod tests { ... }`
4. 用 `cargo test -p agentenv --lib <你的测试名> -- --nocapture` 跑
5. `make fmt && make clippy` 保证风格
6. （可选）如果是 VM 行为相关，按第 5 节写集成测试挂到 `tests/integration/`

---

## 附：关键文件索引

| 路径 | 说明 |
|---|---|
| `Cargo.toml` | workspace 根，列出所有成员 crate |
| `rust-toolchain.toml` | stable 工具链 |
| `Makefile` | 所有 build/test/deploy 入口 |
| `config/default.toml` | 默认配置（`AENV_CONFIG_PATH` 可覆盖） |
| `src/lib.rs` | 主 crate 顶层模块导出 |
| `tests/common/mod.rs` | 集成测试共享夹具 |
| `tests/integration.rs` | 集成测试入口（`#[path]` 聚合） |
| `tests/orchestrator_integration.rs` | orchestrator 独立集成入口 |
| `crates/test-support/` | 共享测试夹具（Minio 等） |
| `crates/e2e-tests/tests/` | E2E 测试 |
| `scripts/tests/` | 测试脚本（envd/e2e/能力校验） |
| `CLAUDE.md` | 架构与命令速览（必读） |
| `CONTRIBUTING.md` | 贡献规范 |
