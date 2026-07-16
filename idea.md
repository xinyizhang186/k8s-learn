# K8s 学习项目 · 全面逻辑结构与代码讲解

> 本文件梳理 `k8s_learnProject` 的整体设计思路、运行流程，并对重要代码进行讲解。
> 配合 `README.md`（速览）与 `MeLearn.md`（知识点笔记）食用，形成"思路 + 代码"的完整理解。
>
> 阅读顺序建议：先看「一、项目设计思路」建立全局观 → 再看「二、整体架构」 → 最后按「三~五」逐层深入代码。

---

## 一、项目设计思路（为什么这样组织）

### 1.1 一句话定位

用一个**零依赖的访客计数器微服务**（Web + Redis），在本地 kind 集群里跑起来，**尽可能密集地覆盖 Kubernetes 的核心知识点**，让"学 K8s"从看文档变成可运行、有结果输出的实战。

### 1.2 三条核心设计原则

| 原则 | 体现 | 好处 |
| --- | --- | --- |
| **场景连贯** | 全部资源围绕"访客计数"一个故事：Web 计数、Redis 存储、Job 初始化、CronJob 巡检 | 知识点不散，互相之间有因果关系，便于理解 |
| **零依赖可运行** | 应用只用 Node 内置模块（`http`/`net`/`os`/`fs`），无需 `npm install`；镜像构建只需 `COPY server.js` | 门槛最低，构建快，镜像小，聚焦 K8s 而非业务代码 |
| **声明式 + 一键化** | 所有资源用 Kustomize 聚合，4 个脚本串成"建集群→造镜像→部署→验证"流水线 | 重复执行不报错（幂等），结果有输出可验证 |

### 1.3 "用最小代码覆盖最多知识点"的取舍

为了让一个 Deployment 文件就能讲清楚 15 个进阶概念，作者把所有能塞的东西都塞进了 `05-web-deployment.yaml`：
滚动更新、多容器 Pod（sidecar）、initContainer、ConfigMap 双注入、Secret 注入、Downward API、双探针、资源限制、securityContext、preStop 优雅关闭、podAntiAffinity、emptyDir、terminationGracePeriod。

这是"教学密度优先于生产合理性"的有意设计——真实项目不会把这么多特性堆在一个 Deployment 里，但学习时集中看更高效。

---

## 二、整体架构

### 2.1 运行时拓扑

```
                    ┌─────────────────────────────┐
                    │  Ingress (k8s-learn.local)   │  七层路由 (07-ingress)
                    │  ingress-nginx Controller    │
                    └──────────┬──────────────────┘
                               │ HTTP Host 路由
                    ┌──────────▼──────────┐
                    │  Service: web        │  ClusterIP 负载均衡 (06-service)
                    │  (2 副本, HPA 2~5)   │
                    └──────────┬──────────┘
               ┌───────────────┴───────────────┐
               ▼                               ▼
      ┌────────────────┐              ┌────────────────┐
      │  web-xxx (Pod) │◄─反亲和──────►│  web-yyy (Pod) │  (05-web-deployment)
      │ ┌────────────┐ │              │ ┌────────────┐ │
      │ │ initC:等redis│ │              │ │ initC:等redis│ │
      │ │ web 容器    │ │              │ │ web 容器    │ │
      │ │ +log-sidecar│ │              │ │ +log-sidecar│ │
      │ └─────┬──────┘ │              │ └─────┬──────┘ │
      └───────┼────────┘              └───────┼────────┘
              │ INCR visits (RESP over TCP)    │
              ▼                                ▼
      ┌──────────────────────────────────────────┐
      │  Service: redis (Headless, clusterIP:None)│  (06-service)
      │  ┌────────────────────────┐               │
      │  │ StatefulSet: redis-0    │  (04-redis)   │
      │  │ PVC data-redis-0 (256Mi)│  持久化计数    │
      │  └────────────────────────┘               │
      └──────────────────────────────────────────┘

  旁路资源（不直接参与计数，各演示一类知识点）:
   • DaemonSet node-info   — 每节点一个 Pod，采集负载 (09)
   • Job init-counter      — 一次性把 visits 设为 0 (10)
   • CronJob count-reporter— 每分钟打印 visits (11)
   • RBAC reader           — 只读 ServiceAccount 演示最小权限 (12)
   • NetworkPolicy         — 只允许 app=web 访问 redis (13)
```

### 2.2 分层视角

```
┌─────────────────────────────────────────────────────────┐
│  外部入口层    Ingress(07) → ingress-nginx              │
├─────────────────────────────────────────────────────────┤
│  服务发现层    Service(06): web(ClusterIP)/web-np/redis  │
├─────────────────────────────────────────────────────────┤
│  工作负载层    Deployment(05) / StatefulSet(04)          │
│              DaemonSet(09) / Job(10) / CronJob(11)      │
├─────────────────────────────────────────────────────────┤
│  配置/存储层   ConfigMap(01) / Secret(02) / PVC(03)      │
├─────────────────────────────────────────────────────────┤
│  治理层        HPA(08) / RBAC(12) / NetworkPolicy(13)    │
├─────────────────────────────────────────────────────────┤
│  命名空间      Namespace: learn-space (00)               │
└─────────────────────────────────────────────────────────┘
```

---

## 三、目录结构

```
k8s_learnProject/
├── README.md                # 项目速览 + 快速开始
├── MeLearn.md               # 知识点学习笔记（Docker/kind/Redis/NS/Ingress/setup-kind 讲解）
├── idea.md                  # ← 本文件：全面逻辑结构与代码讲解
├── result_verify.md         # verify.sh 的实测输出存档
├── kustomization.yaml       # 聚合 14 个 manifest，kubectl apply -k . 一键部署
├── app/                     # 应用代码（零依赖 Node 服务）
│   ├── server.js            # 访客计数器 HTTP 服务 + 自研 RESP Redis 客户端
│   ├── package.json         # 仅声明 name/type/engines，无依赖
│   └── Dockerfile           # 14 行极简镜像菜谱
├── manifests/               # 14 个 K8s 清单，按知识点编号 00~13
└── scripts/                 # 5 个自动化脚本
    ├── setup-kind.sh        # ① 建集群 + 装 metrics-server/ingress-nginx
    ├── build.sh             # ② docker build + kind load 镜像
    ├── deploy.sh            # ③ kubectl apply -k . + 等待就绪
    ├── verify.sh            # ④ 逐项验证并输出结果
    └── cleanup.sh           # 清理资源 / 删集群
```

---

## 四、完整运行流程（4 脚本串联的"流水线"）

这是理解整个项目的**主干线**。四个脚本严格按顺序执行，每一步的输出是下一步的前提：

```
setup-kind.sh ──▶ build.sh ──▶ deploy.sh ──▶ verify.sh
   建集群+插件     构建塞镜像    部署+等就绪    验证+输出
```

### 4.1 setup-kind.sh —— 搭舞台（scripts/setup-kind.sh）

**目标**：在本地用 kind 拉起一个真·K8s 集群，并装好两个学习必备插件。

| 步骤 | 关键命令 | 为什么 |
| --- | --- | --- |
| 幂等检查 | `kind get clusters \| grep k8s-learn` | 已存在则跳过，脚本可重复跑 |
| 建集群 | `kind create cluster --config=-`（内联 YAML） | 用 `extraPortMappings: 80→80` 把宿主机 80 透传进节点，供 ingress 用 |
| 切 context | `kind export kubeconfig` | 让 `kubectl` 默认连这个集群 |
| 装 metrics-server | `kubectl apply -f ...` + patch | HPA 依赖它取 CPU 指标；kind 自签证书要加 `--kubelet-insecure-tls` |
| 装 ingress-nginx | `kubectl apply -f provider/kind/deploy.yaml` | Ingress 规则要靠 Controller 才生效；用 kind 专版已适配端口映射 |
| 等就绪 | `kubectl rollout status --timeout` | 确保装好再继续，避免时序错乱 |

> ⚠️ 实测踩坑（见 `MeLearn.md` 第八节）：`rotate-server-certificates: "true"` 会产生未批准的 `kubelet-serving` CSR，需 `kubectl certificate approve` 手动批准，否则 metrics-server 不 Ready。kind 单节点学习环境可去掉该选项。

### 4.2 build.sh —— 造道具（scripts/build.sh）

**目标**：把 `app/server.js` 打包成镜像并"塞进"kind 节点。

```
docker build -t k8s-learn/web:latest -f app/Dockerfile app/   # 宿主机建镜像
kind load docker-image k8s-learn/web:latest --name k8s-learn  # 塞进 kind 节点
```

**为什么需要 `kind load`**：kind 节点是一个独立 Docker 容器，有自己的 containerd，和宿主机 Docker 镜像列表不共享。不 load 的话 Pod 会 `ErrImagePull`。

### 4.3 deploy.sh —— 上部署（scripts/deploy.sh）

**目标**：用 Kustomize 一键 apply 所有 manifest，并阻塞等待关键资源就绪。

```
kubectl apply -k .                                          # 部署全部 14 个资源
kubectl rollout status statefulset/redis  --timeout=120s    # 等 Redis 起来
kubectl rollout status deployment/web     --timeout=120s    # 等 Web 起来
kubectl wait --for=condition=complete job/init-counter      # 等 Job 跑完
```

`apply -k .` 读取根目录 `kustomization.yaml`，它把 14 个 manifest 按顺序聚合，并统一打上 `app.kubernetes.io/part-of: k8s-learn` 标签、统一指定 `namespace: learn-space`。

### 4.4 verify.sh —— 看结果（scripts/verify.sh）

**目标**：按 13 个知识点逐项验证并打印输出，是项目的"结果展示"脚本。它把 `kubectl get`、临时 Pod `curl`、节点 IP 访问、Ingress 域名访问等方式组合起来，证明每个资源真的在按预期工作。完整输出存档见 `result_verify.md`。

---

## 五、重要代码讲解

### 5.1 app/server.js —— 应用的核心（220 行，零依赖）

整个应用只用 Node 内置模块（`http`/`net`/`os`/`fs`），不装任何 npm 包。它的职责是把 K8s 注入的环境变量、Pod 身份信息"翻译"成可见的页面输出，从而验证 ConfigMap/Secret/Downward API/探针等知识点是否生效。

#### 5.1.1 配置入口：环境变量即 K8s 注入的"证据"（server.js:21-32）

```js
const PORT = Number(process.env.PORT ?? 8080);
const TITLE = process.env.TITLE ?? 'K8s 访客计数器';
const THEME = process.env.THEME ?? 'dark';
const HAS_DB_PASSWORD = Boolean(process.env.DB_PASSWORD);
const POD_NAME = process.env.POD_NAMESPACE ?? os.hostname();
const NODE_NAME = process.env.NODE_NAME ?? 'unknown';
const CPU_REQUEST = process.env.CPU_REQUEST ?? 'n/a';
const MEM_REQUEST = process.env.MEM_REQUEST ?? 'n/a';
```

| 变量 | 来源 | 对应 K8s 知识点 |
| --- | --- | --- |
| `PORT/TITLE/THEME/REDIS_URL` | ConfigMap `envFrom` | `01-configmap.yaml` |
| `DB_PASSWORD` | Secret `envFrom` | `02-secret.yaml`（只判断是否配置，**绝不回显明文**） |
| `POD_NAME/POD_NAMESPACE/NODE_NAME` | Downward API `fieldRef` | `05-web-deployment.yaml:80-91` |
| `CPU_REQUEST/MEM_REQUEST` | Downward API `resourceFieldRef` | `05-web-deployment.yaml:93-100` |

这段代码是"应用如何感知 K8s"的典型范式：应用不需要调 K8s API，只要读环境变量就能拿到自己的身份和资源配额。

#### 5.1.2 TinyRedis —— 自研 RESP 客户端（server.js:36-90）

这是整个应用里最"硬核"的一段：**用纯 `net` 模块手写 Redis 协议**，省掉 `ioredis` 依赖。

**RESP 协议极简回顾**：Redis 通信是基于 TCP 的文本协议，每条命令编码为：
```
*参数个数\r\n$参数1长度\r\n参数1\r\n$参数2长度\r\n参数2\r\n...
```
回复也以类型字符开头：`:` 整数、`$` 批量字符串、`+` 简单字符串。

**编码命令**（server.js:78-88）：
```js
cmd(...args) {
  let payload = `*${args.length}\r\n`;
  for (const a of args) { payload += `$${Buffer.byteLength(a)}\r\n${a}\r\n`; }
  this.queue.push({ resolve, reject });   // 响应排队，匹配请求
  this.sock.write(payload);
}
```
把 `INCR visits` 编码成 `*2\r\n$4\r\nINCR\r\n$6\r\nvisits\r\n` 发出去。

**解码回复**（server.js:53-72）：在 `sock.on('data')` 里按 `\r\n` 切行解析：
- 首字符 `:` → 整数回复（`INCR` 的返回值），`Number(line.slice(1))`
- 首字符 `$` → 批量字符串，读下一行作为数据（`GET` 的返回值）

**为什么要 `this.queue`**：TCP 是流式协议，多个命令的响应可能粘在一个 chunk 里，或一个响应跨多个 chunk。用一个 FIFO 队列把"等待响应的 Promise"排队，来一个回复就 `shift()` 一个，保证请求与响应正确配对。

> 这段代码只实现了 `INCR`/`GET` 用到的整数和批量回复两种，刚好满足计数器需求。它印证了"Redis 协议很简单"——简单到几十行 JS 就能实现一个能用的客户端。

#### 5.1.3 降级策略：Redis 不可用就回退内存（server.js:92-115）

```js
const ready = await redis.connect();
redisReady = ready;
if (redisReady) console.log('[app] 已连接 Redis');
else console.log('[app] Redis 不可用，降级为内存计数');

async function incrCounter() {
  if (redisReady) {
    try { return await redis.cmd('INCR', 'visits'); }
    catch { /* 跌回内存 */ }
  }
  return ++memCounter;
}
```

**设计思想**：服务可用性优先。Redis 挂了不致命，计数器降级为内存计数（虽不持久、不跨 Pod 共享），但页面仍能访问。这与 K8s 的就绪探针配合：
- Redis 通 → `/readyz` 返回 200 → Service 把 Pod 加入 Endpoints → 接流量，计数走 Redis
- Redis 断 → `/readyz` 返回 503 → Pod 被摘出 Endpoints → 不接新流量（避免计数到内存造成不一致）

#### 5.1.4 四条 HTTP 路由（server.js:170-205）

| 路由 | 作用 | 演示的 K8s 知识点 |
| --- | --- | --- |
| `/` | 自增计数 + 渲染 HTML（含 Pod 信息/配置/资源） | StatefulSet 计数、ConfigMap 标题、Secret 密码标记、Downward API |
| `/healthz` | 返回 `{"status":"alive","uptime":N}` | **livenessProbe**：进程活着就 200 |
| `/readyz` | Redis 通则 200 否则 503 | **readinessProbe**：依赖就绪才接流量 |
| `/metrics` | Prometheus 文本格式指标 | HPA / 监控（`learn_visits_total`、`learn_http_requests_total`） |

**双探针分离是重点**：liveness 只看"进程是否响应"（不管 Redis），readiness 才看 Redis。这样 Redis 抖动时 Pod 不会被重启（只是暂时摘流），重启会丢内存计数且增加恢复成本。见 `05-web-deployment.yaml:104-119`。

#### 5.1.5 优雅关闭（server.js:213-220）

```js
function shutdown(sig) {
  server.close(() => { redis.close(); process.exit(0); });  // 停止接收新连接，处理完在途请求再退
  setTimeout(() => process.exit(0), 3000).unref();          // 兜底：3 秒后强制退
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```

K8s 删 Pod 时会先发 `SIGTERM`，等 `terminationGracePeriodSeconds`（deployment 里设 30s）后才发 `SIGKILL`。应用捕获 `SIGTERM` 后先 `server.close()` 拒绝新连接、处理完在途请求再退出，避免丢请求。

> 与 Deployment 的 `lifecycle.preStop: sleep 5` 配合（`05-web-deployment.yaml:121-124`）：preStop 先 sleep 5 秒让 Service 把 Pod 从 Endpoints 摘除，**然后** kubelet 才发 SIGTERM——这 5 秒是为了消除"已摘除但仍有流量打过来"的时间窗。

### 5.2 app/Dockerfile —— 14 行极简镜像菜谱

```dockerfile
FROM node:20-alpine              # 精简基础镜像，体积小
ENV NODE_ENV=production
WORKDIR /app
COPY --chown=node:node server.js package.json ./   # 零依赖，只复制源码
USER node                        # 非 root 运行，与 K8s securityContext 对齐
EXPOSE 8080
HEALTHCHECK --interval=10s ... CMD wget -qO- http://localhost:8080/healthz || exit 1
CMD ["node", "server.js"]
```

要点：
- **零依赖应用**所以不需要 `RUN npm install`，也就不需要多阶段构建，镜像极小。
- `USER node` + `--chown=node:node`：镜像层面就用非 root，和 `05-web-deployment.yaml:51-54` 的 `securityContext.runAsNonRoot/runAsUser:1000` 双重保险。
- `HEALTHCHECK` 让 Docker 自身能判断容器健康，K8s 探针是另一套机制（两者互补）。

### 5.3 kustomization.yaml —— 聚合器

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: learn-space
resources:
  - manifests/00-namespace.yaml
  - manifests/01-configmap.yaml
  ... (14 个文件按编号顺序)
commonLabels:
  app.kubernetes.io/part-of: k8s-learn
```

它做三件事：
1. **聚合**：`kubectl apply -k .` 一条命令部署全部 14 个资源，无需逐个 apply。
2. **统一命名空间**：所有资源默认落到 `learn-space`。
3. **统一打标**：给所有资源加 `app.kubernetes.io/part-of: k8s-learn`，便于统一查询和清理（`kubectl delete -k .`）。

> 注意 `resources` 的顺序：Namespace 必须最先，ConfigMap/Secret 要在 Deployment 之前（Deployment 引用它们），PVC 要在 StatefulSet 之前。Kustomize 不强校验依赖顺序，但按编号排最稳妥。

### 5.4 manifests/ —— 14 个清单逐个讲解

#### 00-namespace.yaml — 逻辑隔离边界
```yaml
kind: Namespace
metadata:
  name: learn-space
```
所有资源的"房间"。先建它，后续资源才能放进来；删除它则里面所有资源一并清除。

#### 01-configmap.yaml — 非敏感配置（两种注入方式）
- `web-config`：键值对，通过 Deployment 的 `envFrom.configMapRef` 整体注入为环境变量（`TITLE/THEME/PORT/REDIS_URL`）。
- `web-config-files`：通过 `volumes.configMap` 挂载为文件（`greeting.txt` → `/etc/config/greeting.txt`），每个 key 变成一个文件。

> 两种方式的区别：env 适合少量简单配置；volume 适合配置文件、且运行时改 ConfigMap 会自动同步（约 60s）。

#### 02-secret.yaml — 敏感信息
```yaml
type: Opaque
stringData:          # 写明文，k8s 自动 base64 编码存储
  DB_PASSWORD: "p@ssw0rd-12345"
  DB_USER: "learnadmin"
```
**关键认知**：Secret 默认只是 base64 编码（`echo -n 'xxx' | base64` 可解码），**不是加密**！生产应配合 RBAC 限制访问或启用 etcd 加密。`stringData` 比手写 `data`+base64 方便。

#### 03-pvc.yaml — 手动声明持久存储
```yaml
accessModes: [ReadWriteOnce]   # 单节点读写
resources:
  requests:
    storage: 256Mi
```
这是"手动 PVC"方式：先建 PVC，再在 Deployment volume 里按名引用。本文件**仅为演示声明流程，实际未被挂载**——真正的 Redis 存储用的是 04 里的 `volumeClaimTemplates`（StatefulSet 专属自动方式）。两种方式对比见文件头注释。

#### 04-redis-statefulset.yaml — 有状态应用（Redis）
**StatefulSet vs Deployment 的核心区别**：
| | Deployment | StatefulSet |
| --- | --- | --- |
| Pod 名 | 随机哈希 | 有序固定 `redis-0` |
| 存储 | 共享或无 | 每个 Pod 独立 PVC（`volumeClaimTemplates`） |
| 启停 | 并行 | 有序（0→1→2 启，2→1→0 停） |

关键字段：
- `serviceName: redis`：**必须**有同名 Headless Service（见 06），StatefulSet 靠它给每个 Pod 分配稳定 DNS（`redis-0.redis.learn-space.svc.cluster.local`）。
- `volumeClaimTemplates`：自动为每个 Pod 生成独立 PVC（`data-redis-0`），Pod 重建后数据仍在。
- `command: redis-server --save 60 1 --appendonly yes`：开启 RDB（60s 1 次快照）+ AOF（每条命令追加日志）双持久化。
- `livenessProbe/readinessProbe: redis-cli ping`：用 Redis 自带的 ping 命令探活。

#### 05-web-deployment.yaml — ★ 知识点最密集的文件（149 行）
这个 Deployment 集中了 15 个进阶知识点，逐一定位：

```yaml
spec:
  replicas: 2
  strategy:                              # ① 滚动更新策略
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }   # 零停机：更新期间不允许不可用
  template:
    spec:
      affinity:
        podAntiAffinity:                 # ② Pod 反亲和：副本尽量打散到不同节点
          preferredDuringSchedulingIgnoredDuringExecution: ...
      securityContext:                   # ③ 安全上下文：非 root + fsGroup
        runAsNonRoot: true
        runAsUser: 1000
      initContainers:                    # ④ initContainer：主容器前等待 Redis DNS 可解析
        - name: wait-for-redis
          command: ["sh","-c","until nslookup redis.learn-space.svc.cluster.local; do sleep 2; done"]
      containers:
        - name: web
          envFrom:                       # ⑤ ConfigMap + ⑥ Secret 整体注入
            - configMapRef: { name: web-config }
            - secretRef:    { name: db-secret }
          env:                           # ⑦ Downward API：Pod 元信息 + 资源请求
            - name: POD_NAME
              valueFrom: { fieldRef: { fieldPath: metadata.name } }
            - name: CPU_REQUEST
              valueFrom: { resourceFieldRef: { resource: requests.cpu } }
          resources:                     # ⑧ 资源限制：requests 调度 / limits 上限
            requests: { cpu: 100m, memory: 128Mi }
            limits:    { cpu: 500m, memory: 256Mi }
          livenessProbe:                 # ⑨ 存活探针：/healthz
            httpGet: { path: /healthz, port: 8080 }
          readinessProbe:                # ⑩ 就绪探针：/readyz（查 Redis）
            httpGet: { path: /readyz, port: 8080 }
          lifecycle:                     # ⑪ 优雅关闭：preStop sleep 5 等流量切走
            preStop: { exec: { command: ["sh","-c","sleep 5"] } }
          volumeMounts:                  # ⑫ 挂载 ConfigMap 文件 + emptyDir 共享日志
            - { name: config-files, mountPath: /etc/config }
            - { name: shared-logs,  mountPath: /var/log/app }
        - name: log-sidecar              # ⑬ sidecar：共享 emptyDir 读业务日志转发到 stdout
          command: ["sh","-c","tail -n+1 -f /var/log/app/access.log"]
      volumes:
        - { name: config-files, configMap: { name: web-config-files } }
        - { name: shared-logs,  emptyDir: {} }   # ⑭ emptyDir：Pod 级临时共享存储
      terminationGracePeriodSeconds: 30  # ⑮ 强制 kill 前宽限期
```

**sidecar 模式详解**：业务容器把访问日志写到 `emptyDir` 共享卷 `/var/log/app/access.log`，sidecar 容器 `tail -f` 同一个文件。这样：
- 业务容器不用关心日志收集，只管写文件；
- sidecar 把日志转发到自己的 stdout，`kubectl logs deploy/web -c log-sidecar` 就能看到；
- 这是 Fluentd/Filebeat 等日志代理的典型 sidecar 模式雏形。

#### 06-service.yaml — 服务发现（三种类型 + Headless）
- `redis`（Headless，`clusterIP: None`）：DNS 查询返回 Pod IP 列表，StatefulSet 必需，让客户端能直连具体 Pod。
- `web`（ClusterIP）：集群内部访问，固定 IP + DNS `web.learn-space.svc`，在 Pod 间负载均衡。
- `web-nodeport`（NodePort `30080`）：每个节点开 30080，集群外部可访问。

**Service 如何找到 Pod**：通过 `selector: app=web` 匹配 Pod 的 `labels`，自动维护 Endpoints 列表。Pod 增减/故障时 Endpoints 自动更新，客户端无感知。

#### 07-ingress.yaml — 七层路由
```yaml
spec:
  ingressClassName: nginx
  rules:
    - host: k8s-learn.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: web, port: { number: 80 } }
```
把 `Host: k8s-learn.local` 的 HTTP 请求路由到 `web:80`。`rewrite-target: /` 注解把路径重写为 `/`。**光写 Ingress 没用，必须先装 Ingress Controller**（`setup-kind.sh` 装的 ingress-nginx）。访问假域名需配 `/etc/hosts` 或 `curl --resolve k8s-learn.local:80:127.0.0.1`。

#### 08-hpa.yaml — 自动扩缩容
```yaml
minReplicas: 2
maxReplicas: 5
metrics:
  - type: Resource
    resource:
      name: cpu
      target: { type: Utilization, averageUtilization: 70 }
behavior:
  scaleDown:
    stabilizationWindowSeconds: 60   # 缩容冷却 60s 防抖
```
CPU 平均利用率超 70% 自动扩到最多 5 副本，降下来后冷却 60s 才缩容。**前提是 metrics-server 已装**，否则指标显示 `<unknown>`。压测触发：`while true; do curl http://<nodeip>:30080; done`。

#### 09-daemonset.yaml — 每节点一个 Pod
```yaml
tolerations:                          # 容忍 control-plane 污点，kind 单节点也能调度
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
```
DaemonSet 保证每个节点跑一个 Pod，典型用于日志/监控代理。这里每 10s 打印节点名和 loadavg。kind 单节点是 control-plane，默认有 `NoSchedule` 污点，必须加 `tolerations` 才能调度上去。

#### 10-job.yaml — 一次性任务
```yaml
completions: 1            # 成功完成 1 次
parallelism: 1            # 并发 1
backoffLimit: 3           # 失败重试上限 3
activeDeadlineSeconds: 60 # 最长运行 60s
ttlSecondsAfterFinished: 600  # 完成后保留 10 分钟便于看日志
restartPolicy: OnFailure      # Job 只支持 OnFailure/Never
```
用 `redis-cli -h redis set visits 0` 初始化计数器。Job 保证"至少成功完成 N 次"，适合批处理/初始化。

#### 11-cronjob.yaml — 定时任务
```yaml
schedule: "*/1 * * * *"           # 每分钟
concurrencyPolicy: Forbid         # 上次没跑完则跳过本次
successfulJobsHistoryLimit: 3
```
每分钟创建一个 Job 打印当前 visits，模拟定时巡检。CronJob = 定时器 + Job 模板。

#### 12-rbac.yaml — 权限控制（四要素）
```
ServiceAccount(reader) ──绑定──▶ Role(pod-reader) ──允许──▶ get/list/watch pods
```
- **ServiceAccount**：Pod 的身份。
- **Role**：命名空间内权限（只能 get/list/watch pods 和 get configmaps）。
- **RoleBinding**：把 Role 绑给 SA。
- **演示 Pod `rbac-test`**：用 `reader` 身份跑，验证能 `get pods` 但 `delete pod` 被拒绝（见 `result_verify.md:212-214` 的 Forbidden 输出）。

> ClusterRole/ClusterRoleBinding 是集群范围版本，本文件用命名空间级的 Role 演示最小权限原则。

#### 13-networkpolicy.yaml — 网络隔离
```yaml
podSelector: { matchLabels: { app: redis } }   # 作用于 redis Pod
policyTypes: [Ingress]                          # 限制入站
ingress:
  - from:
      - podSelector: { matchLabels: { app: web } }   # 只允许 app=web
    ports:
      - { protocol: TCP, port: 6379 }                # 访问 6379
```
默认 K8s 允许所有 Pod 互通，NetworkPolicy 显式限制：redis 只接受 app=web 的 6379 访问，其他一律拒绝。需 CNI 插件支持（kind 的 kindnetd 支持基本策略）。验证：`rbac-test` Pod 访问 redis 会被拒。

---

## 六、一次请求的完整流转（端到端）

以"浏览器访问 `http://k8s-learn.local/`"为例，串联所有组件：

```
1. 浏览器请求 k8s-learn.local:80
   │ （/etc/hosts 或 curl --resolve 把域名指向 127.0.0.1）
   ▼
2. 宿主机:80 ──extraPortMappings──▶ kind 节点容器:80
   │
   ▼
3. ingress-nginx Controller (Pod) 收到请求
   │ 查 Ingress 规则: host=k8s-learn.local → service web:80
   ▼
4. Service: web (ClusterIP, 10.96.x.x)
   │ selector app=web → Endpoints [10.244.0.41:8080, 10.244.0.44:8080]
   │ 负载均衡选一个 Pod（比如 web-xxx）
   ▼
5. Pod web-xxx 内：
   │ initContainer 早已确认 redis 可解析（启动时）
   │ web 容器收到请求 → / 路由 → incrCounter()
   ▼
6. incrCounter() → TinyRedis.cmd('INCR','visits')
   │ 编码为 RESP: *2\r\n$4\r\nINCR\r\n$6\r\nvisits\r\n
   │ TCP 发往 redis://redis:6379
   ▼
7. Service: redis (Headless) → 解析到 redis-0 Pod IP
   │ NetworkPolicy 校验: 来源 app=web ✓ 允许
   ▼
8. StatefulSet redis-0 处理 INCR，返回 :18\r\n（整数回复）
   │ 数据写入 /data（PVC data-redis-0 持久化）
   ▼
9. web 容器拿到 18 → renderHtml(18)
   │ 读取环境变量: TITLE(ConfigMap)、POD_NAME(Downward API)、HAS_DB_PASSWORD(Secret)
   │ 渲染 HTML: "你是第 18 位访客" + Pod 信息标签
   ▼
10. 同时 writeAccessLog() 把请求写入 /var/log/app/access.log (emptyDir)
    │ sidecar 容器 tail -f 同一文件 → 转发到 stdout
    ▼
11. 响应回流: web → Service → ingress-nginx → 宿主机:80 → 浏览器
```

这一条链路穿过了：Ingress → Service(ClusterIP) → Pod(web) → Service(Headless) → Pod(redis)，并触发 NetworkPolicy、ConfigMap、Secret、Downward API、emptyDir+sidecar、PVC 持久化等几乎所有知识点。

---

## 七、计数链路与数据持久化

计数是这个项目的"业务主线"，它的可靠性设计值得单独看：

```
写入路径:  / 请求 → INCR visits ──TCP──▶ redis-0 ──▶ /data/appendonly.aof + dump.rdb
                                                          │
存储层:    PVC data-redis-0 (256Mi, ReadWriteOnce) ◀──────┘
                                                          │
读取路径:  /metrics → GET visits ──TCP──▶ redis-0 ──▶ 返回当前值
```

**为什么用 Redis 而不是内存计数**：
- 内存计数每个 Pod 独立，2 副本会各数各的，计数不准。
- Redis 作为共享后端，`INCR` 是原子操作，多 Pod 并发也安全。
- StatefulSet + PVC 保证 Redis 重启后数据不丢（`result_verify.md` 显示重启后计数延续）。

**降级保底**：Redis 不可用时回退内存计数，虽不精确但服务可用（见 5.1.3）。

**Job 初始化**：`10-job.yaml` 在部署时把 visits 设为 0，保证每次全新部署计数从 0 开始（而非继承上次 PVC 里的值——注意：如果 PVC 没删，Job 的 `set visits 0` 会覆盖旧值）。

---

## 八、关键设计思想小结

1. **声明式优先**：所有东西都是 YAML（声明期望状态），K8s 负责调和。`kubectl apply -k .` 可重复执行不报错。
2. **零依赖最小化**：应用、镜像、脚本都追求最小化，把注意力集中在 K8s 而非业务复杂度。
3. **探针分离**：liveness 只看进程，readiness 看依赖。避免依赖抖动导致无谓重启。
4. **可用性优先 + 降级**：Redis 挂了回退内存，服务不中断；配合探针摘流避免不一致。
5. **最小权限**：RBAC 只给 get/list/watch，NetworkPolicy 只开必要端口，securityContext 非 root。
6. **优雅关闭双保险**：`preStop sleep 5`（等摘流）+ `SIGTERM → server.close()`（处理在途）+ `terminationGracePeriodSeconds: 30`（兜底）。
7. **幂等自动化**：每个脚本都"先查再建/装"，失败有兜底（`代理源 || 原地址`），`rollout status` 等待就绪，4 步流水线可重复跑。
8. **教学密度集中**：把 15 个进阶知识点塞进一个 Deployment，便于对照学习，而非分散在多个文件。

> 学完本文件，建议对照 `result_verify.md`（实测输出）和 `MeLearn.md`（单点深入笔记），并实际跑一遍 `setup-kind.sh → build.sh → deploy.sh → verify.sh`，形成"思路—代码—运行结果"的闭环理解。

---

## 九、setup-kind.sh 逐行深入讲解（补充）

> 第四节 4.1 给过这个脚本的速览表，这里再**逐行拆解**，重点讲"为什么这么写"，把容易卡住的点讲透。
> 脚本只有 77 行，但涉及 kind 配置、kubeadm 补丁、kubectl patch、镜像源兜底、rollout 等多个新手易混的概念。

### 9.0 这个脚本在整条流水线里的位置

```
setup-kind.sh          build.sh         deploy.sh         verify.sh
   ↓                      ↓                ↓                ↓
 建集群+装插件        构建塞镜像        部署 YAML         看结果
 ─────────────  这一步是"地基"，地基没打好后面全跑不动  ─────────────
```

它做三件事，对应脚本里三大块：
1. **建 kind 集群**（第 18–46 行）——造一个跑在 Docker 里的 K8s 节点
2. **装 metrics-server**（第 48–60 行）——让 HPA 能读到 CPU 指标
3. **装 ingress-nginx**（第 62–71 行）——让 Ingress 规则能真正生效

---

### 9.1 脚本头部：严格模式 + 彩色输出（第 1–16 行）

```bash
#!/usr/bin/env bash          # 第1行：用 bash 解释执行（不写 /bin/bash 是为兼容 Mac）
set -euo pipefail            # 第11行：三合一严格模式
```

`set -euo pipefail` 是写 shell 脚本的"安全带"，三个选项各管一件事：

| 选项 | 含义 | 不加会怎样 |
| --- | --- | --- |
| `-e` | 任何命令失败（返回非 0）立刻退出 | 前面命令失败了脚本还继续往下跑，越跑越错，最后输出一堆误导性的错误 |
| `-u` | 用了未定义的变量就报错退出 | 变量名拼错会变成空字符串，悄悄产出错误结果 |
| `-o pipefail` | 管道 `A \| B` 中任一环节失败，整条算失败 | 默认只看管道最后一个命令的返回值，中间环节失败会被漏掉 |

```bash
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'   # 第14行：ANSI 颜色码
info()  { echo -e "${GREEN}[✓]${NC} $1"; }               # 第15行：绿色 ✓ 成功提示
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }              # 第16行：黄色 ! 警告提示
```

- `\033[0;32m` 是终端的"绿色开始"指令，`\033[0m`（NC = No Color）是"恢复默认色"。
- `echo -e` 的 `-e` 让 `echo` 解释转义符（不加 `-e` 会原样输出 `\033`）。
- 封装成 `info()`/`warn()` 两个函数，后续调用统一，输出整齐好看。

> 💡 这是写 shell 脚本的好习惯：**严格模式保安全 + 彩色函数让输出好读**。你可以直接抄到自己的脚本里。

---

### 9.2 第①步：创建 kind 集群（第 18–46 行）

#### 9.2.1 幂等检查：先查再建（第 18–21 行）

```bash
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "kind 集群 ${CLUSTER_NAME} 已存在，跳过创建"
else
  info "创建 kind 集群: ${CLUSTER_NAME}"
  ...
fi
```

逐个拆解这行关键的 `if`：

| 片段 | 作用 |
| --- | --- |
| `kind get clusters` | 列出当前所有 kind 集群的名字（每行一个） |
| `2>/dev/null` | 把**错误输出**丢进黑洞（kind 没装时不报错污染屏幕） |
| `\| grep -q "..."` | 在输出里静默查找匹配行；`-q` = quiet，找到返回 0，没找到返回 1 |
| `"^${CLUSTER_NAME}$"` | 正则：`^` 开头 `$` 结尾，确保精确匹配 `k8s-learn`，不会误匹配 `k8s-learn-2` |

**为什么要这么做**：让脚本"可重复运行"（幂等）。第一次跑会建集群，第二次跑发现已存在就跳过，不会报错。这是运维脚本的基本素养——**绝不能因为资源已存在就让用户手动处理**。

#### 9.2.2 用 heredoc 把内联 YAML 喂给 kind（第 24–40 行）

这是全脚本最容易卡住的一段，先看长什么样：

```bash
cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --wait 120s --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |-
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            rotate-server-certificates: "true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
EOF
```

**先理解整体结构**——它是一个管道：
```
cat <<EOF ... EOF        ← 左边：用 heredoc 生成一段 YAML 文本
        |
        ▼
kind create cluster --config=-   ← 右边：kind 从 stdin（-）读配置
```

| 片段 | 含义 |
| --- | --- |
| `cat <<EOF ... EOF` | "Here Document"语法：把两个 `EOF` 之间的所有行当作文本，通过 `cat` 输出到 stdout |
| `\|` | 管道：把左边 cat 的输出喂给右边的 kind 命令 |
| `--config=-` | 告诉 kind 从**标准输入**（stdin，用 `-` 表示）读配置文件，而不是从磁盘读 |

**为什么不直接写个 `kind.yaml` 文件再 `--config=kind.yaml`**？因为这样脚本自成一体，不用额外维护一个配置文件，复制脚本到任何地方都能跑。这是"单文件脚本"的常见技巧。

#### 9.2.3 集群配置逐段解读

配置里就一个节点（`role: control-plane`），即"单节点集群"——这个节点既是 master（控制面）又是 worker（跑 Pod）。kind 默认就这种模式，适合学习。

**① `extraPortMappings`（第 36–39 行）——最重要的配置**

```yaml
extraPortMappings:
  - containerPort: 80      # kind 节点容器内部的 80 端口
    hostPort: 80            # 映射到宿主机（你的电脑）的 80 端口
    protocol: TCP
```

这是 kind 专属配置，本质就是 `docker run -p 80:80` 的等价物。**为什么需要它**？

```
没有 extraPortMappings 时:
  浏览器 → 宿主机:80 → ❌ 没人监听，访问失败
                        （kind 节点是个 Docker 容器，端口没透传出来）

有 extraPortMappings 后:
  浏览器 → 宿主机:80 ─透传─▶ kind 节点:80 ─▶ ingress-nginx 在这里监听
                                              ─▶ 转发给 web Service ─▶ Pod
```

一句话：**kind 节点是个容器，外部要访问集群服务，必须把宿主机端口透传进节点容器**。后面 Ingress 监听 80 端口，靠的就是这个映射。

> 💡 如果想同时暴露 443（HTTPS），再加一条 `{ containerPort: 443, hostPort: 443 }` 即可。

**② `kubeadmConfigPatches` + `rotate-server-certificates`（第 29–35 行）**

```yaml
kubeadmConfigPatches:
  - |-
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        rotate-server-certificates: "true"
```

这段是给 kubeadm（K8s 的集群初始化工具）打补丁，让 kubelet（每个节点上的代理）开启**服务证书自动轮转**。

| 概念 | 作用 |
| --- | --- |
| `kubeadmConfigPatches` | kind 用来修改默认 kubeadm 配置的机制，可以叠加多段补丁 |
| `InitConfiguration` | 补丁针对"集群初始化"阶段 |
| `kubeletExtraArgs` | 给 kubelet 进程加启动参数 |
| `rotate-server-certificates: "true"` | 让 kubelet 自动向 apiserver 申请新的服务证书，到期前轮转 |

> ⚠️ **实测大坑**（见 `MeLearn.md` 第八节）：开启后 kubelet 会生成 `kubelet-serving` 类型的 CSR 请求，但这些 **CSR 默认不会被自动批准**！不批准会导致：
> - metrics-server 取不到指标（TLS 校验失败）
> - `kubectl logs` 报 TLS 错误
>
> 修复：`kubectl get csr` 看到 Pending 的，`kubectl certificate approve <名字>` 手动批准。
>
> **学习环境建议**：要么去掉这个选项，要么准备好手动批准 CSR。它对学习没增益，反而添乱。

**③ `--wait 120s`（第 24 行）**

```bash
kind create cluster --name "${CLUSTER_NAME}" --wait 120s --config=-
```

`--wait 120s` 让 kind 创建集群后**阻塞等待控制面就绪**（最多 120 秒），而不是创建完立刻返回。这样下一行 `kubectl` 命令执行时集群一定已经可用，不会因"集群还没起好"而报错。

#### 9.2.4 切换 kubectl 上下文（第 44–46 行）

```bash
kind export kubeconfig --name "${CLUSTER_NAME}"
info "当前 context: $(kubectl config current-context)"
```

- `kind export kubeconfig`：把集群的连接信息（API 地址、证书）写到 `~/.kube/config`，并切换当前 context 到 `kind-k8s-learn`。
- 之后 `kubectl` 默认就连这个集群了，不用每次指定 `--kubeconfig`。

```
~/.kube/config 里会多一个 context:
  name: kind-k8s-learn
  cluster: kind-k8s-learn        ← 连接信息（API server 地址 + 证书）
  user:   kind-k8s-learn         ← 认证信息
当前 context → kind-k8s-learn     ← kubectl 默认用这个
```

> 💡 `$(kubectl config current-context)` 用命令替换把当前 context 名嵌进提示信息，让你一眼看到现在连的是哪个集群。

---

### 9.3 第②步：安装 metrics-server（第 48–60 行）

#### 9.3.1 为什么必须装它

后面要学 **HPA（自动扩缩容）**，HPA 根据"CPU 使用率"决定加几个副本。但 K8s 默认**不知道**每个 Pod 用了多少 CPU——这个数据由 metrics-server 提供。

```
没有 metrics-server:
  HPA → 查 CPU 使用率 → apiserver 说"我不知道" → 指标显示 <unknown> → 不扩缩

有 metrics-server:
  metrics-server → 定期问每个节点的 kubelet → 收集 CPU/内存 → 存到 apiserver
  HPA → 查 CPU 使用率 → apiserver 返回数据 → 按规则扩缩
```

kind 默认不装它，必须自己装。

#### 9.3.2 幂等检查（第 49 行）

```bash
if ! kubectl get deployment metrics-server -n kube-system >/dev/null 2>&1; then
```

逐个拆：

| 片段 | 作用 |
| --- | --- |
| `kubectl get deployment metrics-server -n kube-system` | 查 kube-system 命名空间里有没有这个 Deployment |
| `>/dev/null 2>&1` | 把正常输出和错误输出都丢黑洞——我们只关心"有没有"，不看内容 |
| `!` | 取反：**不存在**才进入 then 块去安装 |

和建集群的幂等检查思路一致：已装就跳过，不重复装。

#### 9.3.3 双镜像源兜底（第 51–52 行）——网络友好设计

```bash
kubectl apply -f https://ghproxy.com/https://github.com/.../components.yaml 2>/dev/null \
  || kubectl apply -f https://github.com/.../components.yaml
```

| 片段 | 作用 |
| --- | --- |
| `ghproxy.com/https://github.com/...` | 用国内代理 `ghproxy.com` 加速访问 GitHub（国内直连 GitHub 常超时） |
| `2>/dev/null` | 第一次如果失败（超时），错误信息丢黑洞，屏幕干净 |
| `\|\|` | 短路或：左边失败才执行右边——回退到 GitHub 原地址再试一次 |

**思想**：先试快的代理，失败了再试原地址。这是国内环境拉 GitHub 资源的标准技巧，保证"网络不好也能装上"。

> 💡 `kubectl apply -f <URL>` 会直接从 URL 下载 YAML 并 apply，不用先 `wget` 到本地。

#### 9.3.4 打补丁：追加 `--kubelet-insecure-tls`（第 54–55 行）——全脚本最"吓人"的一行

```bash
kubectl patch deployment metrics-server -n kube-system \
  --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
```

看着复杂，其实就做一件事：**给 metrics-server 容器追加一个启动参数 `--kubelet-insecure-tls`**。逐段拆：

| 片段 | 含义 |
| --- | --- |
| `kubectl patch deployment metrics-server` | 给名为 metrics-server 的 Deployment 打补丁（不用重写整个 YAML） |
| `--type='json'` | 用 JSON Patch 格式（RFC 6902 规范） |
| `-p='[...]'` | 补丁内容，一段 JSON 数组 |
| `op: "add"` | 操作类型 = 添加 |
| `path: ".../containers/0/args/-"` | 目标路径：第 0 个容器的 args 数组末尾（`-` 表示"追加到末尾"） |
| `value: "--kubelet-insecure-tls"` | 要添加的值 |

用图理解 path 的定位：
```
spec
 └─ template
     └─ spec
         └─ containers
             └─ [0]  ← 第0个容器（metrics-server）
                 └─ args  ← 启动参数数组
                     ├─ "--kubelet-preferred-address-types=InternalIP"
                     ├─ "--cert-dir=/tmp"
                     └─ "-"  ← 在这里追加
```

**为什么需要这个参数**：

```
正常流程:  metrics-server → 连 kubelet:10250 → kubelet 出示 TLS 证书 → metrics-server 校验证书是否可信
                                                                          ↑
                                                                  kind 用自签证书，校验失败！

加了参数后: metrics-server → 连 kubelet:10250 → kubelet 出示证书 → metrics-server 说"我不校验了，直接信" → 拿到指标
```

kind 节点用自签名证书（不是权威 CA 签的），metrics-server 默认会校验失败。`--kubelet-insecure-tls` = "不校验证书"。**学习环境可接受，生产绝不能这么干**（会有中间人攻击风险）。

> 💡 `kubectl patch` 的两种常见 type：
> - `--type='json'`：JSON Patch，精确增删改某个字段（本例用）
> - `--type='strategic'`（默认）：K8s 战略合并，按字段名合并

#### 9.3.5 等待就绪（第 56 行）

```bash
kubectl rollout status deployment metrics-server -n kube-system --timeout=120s
```

`rollout status` 会**阻塞**直到 Deployment 滚动更新完成（所有副本 Ready），或超时。这是"确保装好再继续"的关键——不等待的话，下一步装 ingress 时可能资源紧张导致都起不来。

> ⚠️ 正是在这一步，如果 `rotate-server-certificates: "true"` 产生了未批准的 CSR，metrics-server 会卡在 NotReady，导致这里超时、脚本因 `set -e` 中止。见 9.2.3 的踩坑说明。

---

### 9.4 第③步：安装 ingress-nginx（第 62–71 行）

套路和 metrics-server **一模一样**：先查 → 装 → 等就绪。

```bash
if ! kubectl get namespace ingress-nginx >/dev/null 2>&1; then
  info "安装 ingress-nginx ..."
  kubectl apply -f https://ghproxy.com/.../provider/kind/deploy.yaml 2>/dev/null \
    || kubectl apply -f https://raw.githubusercontent.com/.../provider/kind/deploy.yaml
  kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=180s
  info "ingress-nginx 已就绪"
else
  warn "ingress-nginx 已存在，跳过"
fi
```

两个细节值得注意：

**① 用 kind 专版部署文件**：URL 里是 `provider/kind/deploy.yaml`，而不是通用的 `deploy.yaml`。kind 专版已经适配了 kind 的端口映射方式（配合 `extraPortMappings`），装完就能直接用 80 端口访问。

**② 检查的是 namespace 而非 deployment**：metrics-server 检查的是 `deployment`，这里检查的是 `namespace`。因为 ingress-nginx 的部署文件会创建 `ingress-nginx` 命名空间，检查命名空间是否存在就够了。

**为什么必须装它**：后面要学 **Ingress**（七层路由）。但 Ingress 只是一份"路由规则"，真正执行规则的程序是 **Ingress Controller**。没装 Controller，写再多 Ingress YAML 也不生效——请求打进来没人处理。

```
你写的 Ingress YAML: "k8s-learn.local → web:80"   ← 只是规则（登记册）
ingress-nginx Controller: 真正监听 80 端口、按规则转发的程序  ← 干活的（接待员）
```

---

### 9.5 脚本结尾：引导下一步（第 73–77 行）

```bash
echo ""
info "集群准备完成！下一步："
echo "    bash scripts/build.sh      # 构建 web 镜像并加载到 kind"
echo "    bash scripts/deploy.sh     # 部署所有 K8s 资源"
echo "    bash scripts/verify.sh     # 验证并查看运行结果"
```

脚本没默默结束，而是**告诉用户接下来该干嘛**。这是写工具脚本的好习惯——降低使用门槛，用户不用回去翻 README 找下一步。

---

### 9.6 三个"为什么"总结（最容易卡住的点）

| 疑问 | 答案 |
| --- | --- |
| **为什么宿主机 `docker build` 的镜像 kind 里看不到？** | kind 节点是独立 Docker 容器，有自己的 containerd，不共享宿主机镜像列表。必须 `kind load docker-image` 塞进去（这是 `build.sh` 的事，不是本脚本）。 |
| **为什么 `curl localhost` 能访问到集群里的 Ingress？** | 因为建集群时 `extraPortMappings: 80→80` 把宿主机 80 透传进了 kind 节点，而 ingress-nginx 在节点里监听 80。没有这个映射，外部访问不进来。 |
| **为什么 metrics-server 要加 `--kubelet-insecure-tls`？** | kind 用自签证书，metrics-server 默认校验 kubelet 的 TLS 证书会失败，拿不到指标。加这个参数 = 不校验证书。学习环境可接受，生产不行。 |

---

### 9.7 脚本里的 5 个设计模式（可偷师的技巧）

| 技巧 | 体现 | 好处 |
| --- | --- | --- |
| **严格模式** | `set -euo pipefail` | 出错即停，不让错误蔓延 |
| **幂等设计** | 每步都 `if 已存在 then 跳过` | 脚本可重复跑，不会因已装而报错 |
| **彩色输出** | `info()` / `warn()` 函数 | 输出好看，✓ / ! 一眼分清 |
| **兜底回退** | `代理源 \|\| 原地址` | 网络不好也能装上 |
| **等待就绪** | `rollout status --timeout` | 确保装好再继续，不会时序错乱 |

---

### 9.8 跑完之后集群里有什么

```
集群: k8s-learn (kind 单节点)
├─ kube-system 命名空间
│   ├─ metrics-server          ← 本脚本装的，HPA 依赖
│   └─ (kind 自带的: apiserver/scheduler/etcd/coredns/...)
├─ ingress-nginx 命名空间
│   └─ ingress-nginx-controller ← 本脚本装的，Ingress 规则靠它执行
├─ local-path-storage 命名空间
│   └─ (kind 自带的存储驱动，提供 standard StorageClass)
└─ learn-space 命名空间          ← 还没建！这是 deploy.sh 才会建的
    └─ (空，等 deploy.sh 来填充 14 个资源)
```

注意：本脚本**只装基础设施**，不碰业务资源。`learn-space` 命名空间和 14 个 manifest 是 `deploy.sh` 的事。两步分明，各司其职。

> 跑完本脚本，集群"舞台"搭好了，但"演员"还没上台。下一步执行 `build.sh`（造演员=镜像）和 `deploy.sh`（让演员上台=部署资源）。
