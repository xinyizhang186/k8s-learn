# AgentENV：HTTP API、E2B 与 Sandbox Proxy

> 调研日期：2026-08-31  
> 范围：AgentENV 官方 `latest` 文档、GitHub 主仓库与 Releases。  
> 版本提示：tagged release 与 `main/latest` 请分开理解。

## 1. API 入口

单 Node 常见地址：

```text
http://<node>:8000
```

分布式模式通常访问 Gateway：

```text
http://<gateway>:8080
```

完整 API Schema 以官方 Swagger/OpenAPI 和对应 release 的 generated API 为准。

## 2. 核心 API 能力

Developer Architecture 中可见的典型 Node 级资源包括：

```text
POST   /sandboxes
GET    /sandboxes
GET    /sandboxes/{id}
DELETE /sandboxes/{id}

POST /sandboxes/{id}/pause
POST /sandboxes/{id}/resume

GET /nodes
GET /nodes/{id}

ANY /proxy
ANY /proxy/{path...}
```

另有 Template/Snapshot 等接口。精确 path/body/status code 以当前 OpenAPI 为准。

## 3. E2B SDK

关键做法是把 E2B endpoint 指向 AgentENV：

```bash
export E2B_API_URL=http://127.0.0.1:8000
export E2B_SANDBOX_URL=$E2B_API_URL
export E2B_API_KEY=$AENV_API_KEY
```

这样已有 E2B SDK 调用可以复用，而 Sandbox 基础设施变成自托管 AgentENV。

## 4. Management API 认证

典型 Header：

```http
X-API-Key: <AENV_API_KEY>
```

它用于 Sandbox lifecycle、Template、Snapshot 和管理查询。

## 5. Sandbox Proxy

Proxy 将 Host/Gateway 请求转发到某个 Sandbox 的目标端口。

支持：

- HTTP；
- SSE；
- WebSocket。

### Header Routing

```http
x-agentenv-sandbox-id: <sandbox-id>
x-agentenv-target-port: <port>
```

同时提供 E2B 兼容 header。

### Host Routing

配置 domain 后可形成：

```text
<port>-<sandbox-id>.<sandbox-domain>
```

适合 Web preview、Jupyter、dev server、临时 API。

## 6. Public 与 Private Ingress

允许 public traffic 时，不需要 private traffic token。

Private Sandbox Service 使用：

```http
e2b-traffic-access-token: <trafficAccessToken>
```

这个 token 与 `X-API-Key` 完全不同。

## 7. Secure envd

Sandbox `secure=true` 时，envd 操作用：

```http
X-Access-Token: <envdAccessToken>
```

三种凭据：

| Credential | 作用面 |
|---|---|
| API Key | Host management/control plane |
| Traffic Access Token | Private Sandbox ingress |
| envd Access Token | Guest envd operations |

## 8. Gateway 路由

分布式场景：

```text
request(sandbox-id)
→ Gateway
→ binding lookup
→ target Node
→ forward HTTP/WebSocket
```

新 Sandbox 创建：

```text
Gateway
→ Scheduler
→ choose Node
→ forward create
→ persist binding
```

应用无需知道 Sandbox 实际位于哪个 Node。

## 9. Binding Store

```text
sandbox-id → node-id
```

可使用：

- in-memory；
- Redis。

Redis 适合多个 Gateway/control-plane 进程共享 binding。

## 10. 推荐接入层

建议业务内部再包一层 Runtime Adapter：

```python
class SandboxRuntime:
    def create(self, ...): ...
    def exec(self, ...): ...
    def upload(self, ...): ...
    def snapshot(self, ...): ...
    def pause(self, ...): ...
    def resume(self, ...): ...
    def delete(self, ...): ...
```

这样上层 Agent 不被某个 Sandbox Provider API 完全绑定。

## 11. Timeout 要分层

至少区分：

```text
HTTP request timeout
sandbox TTL
boot/restore timeout
envd readiness timeout
scheduler timeout
proxy timeout
```

不要用一个 timeout 覆盖全部含义。

## 官方来源

- https://kvcache-ai.github.io/AgentENV/latest/
- https://github.com/kvcache-ai/AgentENV/tree/main/src/api
- https://github.com/kvcache-ai/AgentENV/blob/main/src/api/proxy.rs
