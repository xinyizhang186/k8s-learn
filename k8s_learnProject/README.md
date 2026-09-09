# K8s 入门学习项目 · 访客计数器

> 一个通过"访客计数器"微服务覆盖 Kubernetes 大部分核心知识点的入门级实践项目。
> 声明式、可运行、有结果输出，配套 kind 本地集群，开箱即跑。

请把/root/Agent项目/k8s_learnProject/scripts/setup-kind.sh讲解放在/root/Agent项目/k8s_learnProject/MeLearn.md里，作为学习笔记，结构清晰，适合小白入门学习，可以不用太多。不要覆盖原有内容。
不要修改当前服务器的原有内容，请运行当前的项目文件，并展示结果。

## 这个项目能学到什么

通过一个连贯的微服务场景（Web 访客计数器 + Redis 后端），覆盖 **14 类 K8s 资源 + 15 个进阶知识点**：

| 类别 | 资源/知识点 |
| --- | --- |
| 工作负载 | Pod、Deployment、StatefulSet、DaemonSet、Job、CronJob |
| 网络 | Service（ClusterIP/NodePort/Headless）、Ingress、NetworkPolicy |
| 配置 | ConfigMap、Secret、Downward API |
| 存储 | PVC、emptyDir、volumeClaimTemplates |
| 弹性 | HPA（自动扩缩容） |
| 安全 | RBAC（ServiceAccount/Role/Binding）、securityContext |
| 运维 | 探针（liveness/readiness）、资源限制、优雅关闭、滚动更新、Pod 反亲和 |
| 进阶 | initContainer、多容器 Pod（sidecar）、Kustomize |

## 项目结构

```
k8s_learnProject/
├── README.md                      # 本文件
├── kustomization.yaml             # 聚合所有 manifest，一键部署
├── app/                           # 应用代码（零依赖 Node.js 服务）
│   ├── server.js                  # 访客计数器 HTTP 服务
│   ├── package.json
│   └── Dockerfile                 # 多阶段构建，非 root 运行
├── manifests/                     # K8s 清单（按知识点编号）
│   ├── 00-namespace.yaml          # Namespace
│   ├── 01-configmap.yaml          # ConfigMap (env + volume 两种注入)
│   ├── 02-secret.yaml             # Secret

│   ├── 03-pvc.yaml                # PersistentVolumeClaim
│   ├── 04-redis-statefulset.yaml  # StatefulSet (有状态 Redis + PVC)
│   ├── 05-web-deployment.yaml     # Deployment (★ 最密集: initContainer/sidecar/probes/资源/反亲和/Downward API)
│   ├── 06-service.yaml            # Service (ClusterIP/NodePort/Headless)
│   ├── 07-ingress.yaml            # Ingress
│   ├── 08-hpa.yaml                # HorizontalPodAutoscaler
│   ├── 09-daemonset.yaml          # DaemonSet (每节点一个)
│   ├── 10-job.yaml                # Job (一次性初始化)
│   ├── 11-cronjob.yaml            # CronJob (定时巡检)
│   ├── 12-rbac.yaml               # RBAC (ServiceAccount/Role/Binding)
│   └── 13-networkpolicy.yaml      # NetworkPolicy (网络隔离)
├── scripts/                       # 自动化脚本
│   ├── setup-kind.sh              # 创建 kind 集群 + 安装 metrics-server/ingress
│   ├── build.sh                   # 构建镜像并加载到 kind
│   ├── deploy.sh                  # 部署所有资源
│   ├── verify.sh                  # 验证并展示运行结果（结果输出）
│   └── cleanup.sh                 # 清理资源/集群
└── docs/
    └── knowledge-map.md           # 知识点地图 + 学习路线
```

## 架构

```
                   ┌─────────────────────────────┐
                   │      Ingress (k8s-learn.local) │  七层路由
                   └──────────┬──────────────────┘
                              │
                   ┌──────────▼──────────┐
                   │   Service: web       │  ClusterIP 负载均衡
                   │   (2 副本, HPA 2~5)  │
                   └──────────┬──────────┘
              ┌───────────────┴───────────────┐
              ▼                               ▼
     ┌────────────────┐              ┌────────────────┐
     │  web-xxx (Pod) │              │  web-yyy (Pod) │
     │  ┌──────────┐  │              │  ┌──────────┐  │
     │  │ web 容器  │◄─┼──反亲和──────┤  │ web 容器  │  │
     │  │+sidecar  │  │              │  │+sidecar  │  │
     │  └────┬─────┘  │              │  └────┬─────┘  │
     └───────┼────────┘              └───────┼────────┘
             │ initContainer 等待 redis 就绪  │
             │ ConfigMap/Secret 注入          │
             ▼                               ▼
     ┌──────────────────────────────────────────┐
     │     Service: redis (Headless)             │
     │     ┌────────────────────────┐            │
     │     │  StatefulSet: redis-0  │            │
     │     │  (PVC 持久化, 256Mi)    │            │
     │     └────────────────────────┘            │
     └──────────────────────────────────────────┘

  另有: DaemonSet(每节点) / Job(初始化) / CronJob(定时) / RBAC Pod / NetworkPolicy(隔离)
```

## 快速开始（4 步跑起来）

### 前置要求
- Docker、kind、kubectl（Linux/Mac/WSL）
- Node.js 18+（仅本地测试应用时需要，K8s 部署用镜像）

### 步骤

```bash
cd k8s_learnProject

# 1. 创建本地 K8s 集群（含 metrics-server + ingress-nginx）
bash scripts/setup-kind.sh

# 2. 构建应用镜像并加载到 kind
bash scripts/build.sh

# 3. 部署所有 K8s 资源
bash scripts/deploy.sh

# 4. 验证运行结果（逐项展示各资源状态与输出）
bash scripts/verify.sh
```

### 预期输出（verify.sh 节选）

```
  5. 应用输出 — 访问计数器主页
[✓] 通过 Service 内部访问
你是第 <span class="count">1</span> 位访客
Pod: web-7b9f-xxx
NS: learn-space
当前计数后端：Redis (StatefulSet)
数据库密码：已配置 (Secret)

[✓] /healthz 与 /readyz
healthz: {"status":"alive","uptime":12}
readyz: {"status":"ready","redis":true}

[✓] /metrics
learn_visits_total 1
learn_http_requests_total 5
```

## 应用说明

访客计数器（`app/server.js`）是一个**零第三方依赖**的 Node.js 服务：

| 路由 | 作用 | 演示的知识点 |
| --- | --- | --- |
| `/` | 访问计数 + 展示 Pod 信息 | StatefulSet(Redis计数)、ConfigMap(标题)、Secret(密码标记)、Downward API(Pod名/IP/资源) |
| `/healthz` | 存活探针 | livenessProbe |
| `/readyz` | 就绪探针 | readinessProbe（检查 Redis 连通） |
| `/metrics` | Prometheus 指标 | HPA / 监控 |

- 无 Redis 时自动降级为内存计数，保证服务可用。
- 用纯 `net` 模块实现 RESP 协议与 Redis 通信，无需 `npm install`。

## 渐进式学习

不必一次部署全部，可按学习路线逐步 apply：

```bash
# 第一阶段：让应用跑起来
kubectl apply -f manifests/00-namespace.yaml
kubectl apply -f manifests/01-configmap.yaml -f manifests/02-secret.yaml
kubectl apply -f manifests/05-web-deployment.yaml -f manifests/06-service.yaml
kubectl -n learn-space get pods   # 观察 Pod 启动

# 第二阶段：加状态存储
kubectl apply -f manifests/03-pvc.yaml -f manifests/04-redis-statefulset.yaml
kubectl apply -f manifests/06-service.yaml  # redis headless service

# 第三阶段：批量任务
kubectl apply -f manifests/09-daemonset.yaml -f manifests/10-job.yaml -f manifests/11-cronjob.yaml

# 第四阶段：网络与运维
kubectl apply -f manifests/07-ingress.yaml -f manifests/08-hpa.yaml
kubectl apply -f manifests/12-rbac.yaml -f manifests/13-networkpolicy.yaml
```

## 常用调试命令

```bash
kubectl -n learn-space get pods -o wide        # Pod 状态与调度节点
kubectl -n learn-space describe pod <name>      # 事件/探针/调度详情（排错首选）
kubectl -n learn-space logs -f deploy/web        # 实时日志
kubectl -n learn-space logs deploy/web -c log-sidecar  # sidecar 日志
kubectl -n learn-space exec -it deploy/web -- sh # 进入容器
kubectl -n learn-space scale deploy/web --replicas=4  # 手动扩缩
kubectl -n learn-space rollout undo deploy/web   # 回滚上一版本
kubectl -n learn-space rollout history deploy/web # 查看更新历史
kubectl -n learn-space top pods                  # 资源使用（需 metrics-server）
kubectl kustomize .                              # 渲染所有 manifest 预览
```

## 清理

```bash
bash scripts/cleanup.sh         # 仅删除 K8s 资源（保留集群）
bash scripts/cleanup.sh --all   # 连 kind 集群一起删除
```

## 知识点详解

详见 [docs/knowledge-map.md](docs/knowledge-map.md)，包含：
- 每个知识点的文件对照表
- Deployment 中 15 个进阶知识点定位
- 推荐学习路线（四阶段）
- 核心概念速记（声明式、Pod、Service、StatefulSet、探针、Service 类型）

