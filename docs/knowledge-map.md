# K8s 知识点地图

> 本项目通过一个"访客计数器"微服务，覆盖 Kubernetes 核心知识点。
> 每个知识点对应一个 manifest 文件，可独立学习、逐步部署。

## 知识点 → 文件对照表

| # | 知识点 | 资源类型 | 文件 | 一句话理解 |
| --- | --- | --- | --- | --- |
| 0 | 命名空间 | Namespace | `00-namespace.yaml` | 集群内的逻辑隔离边界 |
| 1 | 配置管理 | ConfigMap | `01-configmap.yaml` | 非敏感配置，env / volume 两种注入 |
| 2 | 敏感信息 | Secret | `02-secret.yaml` | 密码/证书，base64 编码存储 |
| 3 | 持久存储声明 | PVC | `03-pvc.yaml` | 用户对存储的"申请单" |
| 4 | 有状态应用 | StatefulSet | `04-redis-statefulset.yaml` | 稳定网络标识 + 独立存储 (Redis) |
| 5 | 无状态应用 | Deployment | `05-web-deployment.yaml` | 副本管理 + 滚动更新 (★最密集) |
| 6 | 服务发现 | Service | `06-service.yaml` | 固定 IP/DNS + 负载均衡 |
| 7 | 七层路由 | Ingress | `07-ingress.yaml` | HTTP 域名/路径路由 |
| 8 | 自动扩缩容 | HPA | `08-hpa.yaml` | 按 CPU/内存自动增减副本 |
| 9 | 节点级守护 | DaemonSet | `09-daemonset.yaml` | 每个节点跑一个 Pod |
| 10 | 一次性任务 | Job | `10-job.yaml` | 运行到完成即退出 |
| 11 | 定时任务 | CronJob | `11-cronjob.yaml` | Cron 表达式定时跑 Job |
| 12 | 权限控制 | RBAC | `12-rbac.yaml` | ServiceAccount + Role + Binding |
| 13 | 网络隔离 | NetworkPolicy | `13-networkpolicy.yaml` | 限制 Pod 间网络访问 |

## Deployment 中的进阶知识点（集中在 05-web-deployment.yaml）

| 知识点 | 位置 | 说明 |
| --- | --- | --- |
| 滚动更新策略 | `strategy.rollingUpdate` | maxSurge/maxUnavailable 控制更新节奏 |
| 多容器 Pod | `containers[]` | 业务容器 + sidecar 共享网络/卷 |
| initContainer | `initContainers[]` | 主容器启动前执行，完成即退出 |
| ConfigMap 注入 | `envFrom.configMapRef` | 整体注入为环境变量 |
| ConfigMap 挂载 | `volumes.configMap` | 每个 key 变成一个文件 |
| Secret 注入 | `envFrom.secretRef` | 敏感变量注入 |
| Downward API | `env.valueFrom.fieldRef` | Pod 元信息/资源注入为环境变量 |
| 存活探针 | `livenessProbe` | httpGet，失败则重启容器 |
| 就绪探针 | `readinessProbe` | httpGet，失败则从 Service 摘除 |
| 资源限制 | `resources` | requests 调度依据 / limits 上限 |
| 安全上下文 | `securityContext` | 非 root + 禁止提权 |
| 优雅关闭 | `lifecycle.preStop` | 关闭前等待流量切走 |
| Pod 反亲和 | `affinity.podAntiAffinity` | 副本尽量分散到不同节点 |
| emptyDir | `volumes.emptyDir` | Pod 级临时共享存储 |
| terminationGracePeriod | `terminationGracePeriodSeconds` | 强制kill 前的宽限期 |

## 学习路线（推荐顺序）

```
第一阶段：核心三件套（跑起来）
  Namespace → ConfigMap/Secret → Deployment → Service
  目标：理解"声明式"思想，让一个应用跑起来并访问到

第二阶段：状态与存储
  PVC → StatefulSet (Redis)
  目标：理解有状态 vs 无状态、持久化

第三阶段：进阶调度
  initContainer/sidecar/probes/resources (重看 Deployment)
  DaemonSet / Job / CronJob
  目标：理解 Pod 生命周期与多种工作负载

第四阶段：网络与运维
  Ingress → HPA → RBAC → NetworkPolicy
  目标：理解流量入口、弹性、安全
```

## 核心概念速记

### 声明式 vs 命令式
- K8s 是**声明式**：你描述"期望状态"（要 3 个副本），K8s 持续调和使实际状态趋近期望。
- `kubectl apply` 是声明式（可重复执行），`kubectl create` 是命令式（重复会报错）。

### Pod 是什么
- Pod 是 K8s 最小调度单元，内含 1~N 个容器，共享网络和存储。
- 一个 Pod 内多容器 = sidecar 模式，常用于日志/监控代理。

### Service 如何找到 Pod
- Service 通过 `selector` 匹配 Pod 的 `labels`，自动维护 Endpoints 列表。
- Pod 增减/故障时 Endpoints 自动更新，客户端无感知。

### StatefulSet vs Deployment
| | Deployment | StatefulSet |
| --- | --- | --- |
| Pod 名 | 随机哈希 (web-7b9f-xxx) | 有序固定 (redis-0, redis-1) |
| 存储 | 共享或无 | 每个 Pod 独立 PVC |
| 启停顺序 | 并行 | 有序（启 0→1→2，停 2→1→0） |
| 适用 | Web/API/无状态 | 数据库/队列/有状态 |

### 三种探针
| 探针 | 作用 | 失败后果 |
| --- | --- | --- |
| liveness | 进程是否存活 | **重启**容器 |
| readiness | 是否准备好接流量 | 从 Service **摘除**（不重启） |
| startup | 启动是否完成（慢启动应用） | 在完成前禁用上面两个 |

### Service 四种类型
| 类型 | 访问范围 |
| --- | --- |
| ClusterIP（默认） | 集群内部 |
| NodePort | 节点端口（30000-32767） |
| LoadBalancer | 云厂商负载均衡器 |
| ExternalName | DNS CNAME 到外部服务 |
| Headless (clusterIP: None) | 直接返回 Pod IP（StatefulSet 用） |
