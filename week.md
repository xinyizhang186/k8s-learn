# 周报：学习 AgentENV

> 参考文档：https://kvcache-ai.github.io/AgentENV/latest/
> 仓库：https://github.com/kvcache-ai/AgentENV

AgentENV（AENV）是基于 Firecracker microVM、对外暴露 E2B 兼容 API 的自托管 AI Agent 沙箱运行时。本周在上周架构与部署基础上，深入模板构建、E2B 集成、安全沙箱三个专题，整理如下。

---

## 1. 模板（Template）概念与构建流程

### 1.1 任务描述

学习模板机制：理解模板与快照的关系，掌握 `aenv pull` / `aenv build` 两种构建方式及运行时配置继承。

### 1.2 详细内容

1）**模板的本质与生命周期**。模板是「已提交快照」的用户层封装——构建一次即可在毫秒级反复创建沙箱，无需每次重启 VM 装软件。流程为：定义（overlaybd 基础 rootfs + 有序步骤）→ 构建（启动临时沙箱执行步骤）→ 定稿（可选启动命令并就绪检查）→ 发布（提交为快照入库）→ 启动（从该快照恢复）。模板是 API/UX 层，快照是持久运行层：一个模板构建发布一个提交快照，模板 ID/别名解析到该快照，据此创建的沙箱从快照恢复。别名叫 `--name`，可用在任何接受模板 ID 的位置（`aenv start my-base`、`aenv template delete my-service`）。

2）**两种构建方式**。`aenv pull <image>` 直接导入 OCI 镜像为模板，`Env`/`WorkingDir`/`User` 自动从镜像 config 继承，可选 `--start-cmd`（打快照前运行）、`--ready-cmd`（每 2s 轮询直到 exit 0 才捕获快照）、`--probe <PORT>`（等 TCP 端口可连即就绪）、`-d`（提交即返回不阻塞）、`--timeout`。`aenv build <dockerfile> --name <name>`（实验性，不建议生产）在临时沙箱内跑 Dockerfile 指令：`FROM`（可被 `--image` 覆盖）、`RUN`/`ENV`/`ARG`/`WORKDIR`/`USER` 真实执行，`ENTRYPOINT` 映射为 `startCmd`（无则用 `CMD`），`EXPOSE`/`VOLUME`/`LABEL` 仅作元数据存储。两者读同一组 OCI image-spec config 字段（Env/WorkingDir/User/Entrypoint/Cmd/ExposedPorts/Volumes/Labels）决定运行时行为。

3）**模板管理与复用闭环**。`aenv template list`（别名 `ls`）显示 ID/名称/构建状态/CPU/内存/磁盘/更新时间；`aenv template watch <id|name>` 跟踪 `build` 异步构建直到成功或失败；`aenv template delete <id|name>`（别名 `rm`）删除。从模板启沙箱：`aenv start <id|name>` 附交互 shell，`aenv start -d <id|name>` 仅打印 sandbox ID 退出。模板把「构建一次 → 快照固化 → 多次毫秒级复用」串成闭环，是 AgentENV 高效复用的核心抽象。

---

## 2. E2B 兼容集成（SDK 与 CLI）

### 2.1 任务描述

掌握通过 E2B 官方 SDK/CLI 接入 AgentENV：环境变量配置、TS/Python SDK 用法、令牌边界。

### 2.2 详细内容

1）**兼容性与环境变量配置**。AgentENV 暴露 E2B 兼容 API，官方 E2B SDK 开箱即用无需改代码。单节点示例：`E2B_API_URL=http://127.0.0.1:8000`、`E2B_SANDBOX_URL=${E2B_API_URL}`、`E2B_API_KEY=${AENV_API_KEY}`（多节点/各部署模式的值见环境变量文档）。两种访问令牌边界不同：`network.allowPublicTraffic` 为 false 时返回 `trafficAccessToken`，用 `e2b-traffic-access-token` 头访问私有应用路由；安全沙箱额外返回 `envdAccessToken`，用 `X-Access-Token` 头仅用于 envd 控制面；公开应用路由无需任何令牌。

2）**TypeScript SDK 用法**。`npm install e2b` 后：`Sandbox.create("<template-id>", { apiKey })` 从模板创沙箱；`Sandbox.list({ limit, query:{ state:["running"] } })` 列运行中沙箱并 `nextItems()` 取分页；`sandbox.commands.run("echo hello world")` 跑命令；`Sandbox.Pause(sandboxId, { apiKey })` 暂停；`sandbox.kill()` 销毁。`<template-id>` 需为本地模板库中存在的模板，可用 `e2b template list` 或 `GET /v2/templates` 查看。

3）**Python SDK 与 CLI 取舍**。Python：`pip install e2b` 后同样 `Sandbox.create("<template-id>")`、`Sandbox.list(limit=20, query=SandboxQuery(state=[SandboxState.RUNNING]))` + `next_items()`、`sandbox.commands.run("...")`、`sandbox.beta_pause()`、`sandbox.kill()`，依赖 shell 中已设的环境变量。E2B CLI 虽兼容，但官方推荐 AgentENV 工作流优先用 `aenv` CLI——它原生封装了 HTTP API 与 envd gRPC，模板/沙箱/快照管理更顺手。

---

## 3. 安全沙箱与访问令牌

### 3.1 任务描述

学习安全沙箱机制：secure 模式的令牌保护范围、令牌种子配置、多节点与 K8s 下的共享种子实践。

### 3.2 详细内容

1）**secure 模式与令牌边界**。安全沙箱用 envd 访问令牌保护控制面通信（命令执行、文件访问）。启用方式：API/SDK 设 `secure: true`，或 CLI `aenv start --secure <template-id>`，API/SDK 自动返回并附加 `envdAccessToken` 到 envd 请求。它与 `trafficAccessToken` 独立——后者用 `e2b-traffic-access-token` 头保护私有应用入口，公开入口无需凭证。fork 出的沙箱各自独立凭证；secure 模式跨 pause/restart/resume 保持；旧沙箱除非以 `secure: true` 创建否则仍非安全。

2）**访问令牌种子（seed）**。seed 是派生每个沙箱 envd/traffic 令牌的随机值。单机可选——不设时运行时自动在 `$AENV_HOME/secrets` 生成并持久化。集群则必须在每个运行时节点配同一显式 seed：`openssl rand -hex 32` 生成一次存入密钥管理器，作为 `AENV_SANDBOX_ACCESS_TOKEN_HASH_SEED` 环境变量或 TOML `[sandbox].access_token_hash_seed` 设到每节点。升级须保留 seed，改 seed 会轮换所有沙箱访问令牌。

3）**Kubernetes 下的种子管理**。运行时 DaemonSet 保留可选 `agentenv-runtime-secrets` 契约：先 `kubectl apply -f deploy/k8s/base/namespace.yaml`，再用 `openssl rand -hex 32` 经 `kubectl -n agentenv-system create secret generic agentenv-runtime-secrets --from-literal="sandbox-access-token-hash-seed=..."` 创建，升级务必保留。也可由外部密钥管理器提供同名同 key 的 Secret；若 Secret 不存在，Pod 退回节点本地 seed，集群下会致跨节点 fork/resume 校验失败，故多节点必须统一 seed。

---

## 心得体会

AgentENV 用「模板→快照→fork」三层抽象把隔离环境的构建与复用压到毫秒级，再以 E2B 兼容 API 与 secure 令牌机制兼顾迁移成本与安全，是 AI Agent 工程化落地的关键基础设施。

## 下周学习计划

基于本周掌握的模板与安全模型，下周动手实战：构建一个预装 Python 环境的自定义模板，用 E2B Python SDK 跑通「创建沙箱—执行代码—暂停/恢复—fork 并行」完整链路，并验证 secure 模式下的令牌边界。
