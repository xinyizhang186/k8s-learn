# k8s 与 Pod 开发环境 - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / 大模型推理部署方向）
> 使用方式：每节先记加粗结论。面试按"对象是什么 → 控制器如何协调 → 调度 → 网络 → 运维"五段答。

---

## 一、整体架构

### Q1. k8s 控制面（Control Plane）组件？
| 组件 | 作用 |
|---|---|
| **kube-apiserver** | 唯一入口，所有组件通过它读写 etcd；RESTful + watch 机制 |
| **etcd** | 强一致性 KV 存储集群所有状态（Raft 协议） |
| **kube-scheduler** | 决定 Pod 调度到哪个 Node（预选 Predicate + 优选 Priority） |
| **kube-controller-manager** | 运行控制器循环：Deployment/ReplicaSet/Node/Endpoint 等 |
| **kube-cloud-controller-manager** | 云厂商特定逻辑（LB、PV、节点管理） |

### Q2. Node 节点组件？
- **kubelet**：节点上的"管家"，向 API Server 汇报状态，按 PodSpec 启停容器（通过 CRI）。
- **kube-proxy**：维护 iptables/IPVS 规则，实现 Service 转发。
- **容器运行时**：containerd（默认）、CRI-O、Docker（已 1.24 弃用）。
- **CNI 插件**：Calico/Flannel/Cilium，负责 Pod 网络。
- **CSI 插件**：负责 PV 挂载。

### Q3. k8s API 对象的"层次"关系？
```
Pod                  # 最小调度单元，封装一个或多个容器
 ├─ ReplicaSet       # 保证副本数
 ├─ Deployment       # 声明式滚动更新 + 回滚
 ├─ StatefulSet      # 有状态，Pod 名稳定 + 顺序启停 + 持久卷绑定
 ├─ DaemonSet        # 每节点一个（监控、网络插件、device plugin）
 └─ Job/CronJob      # 跑完即退 / 定时
Service              # 稳定 IP + DNS + 负载均衡
Ingress/Gateway       # 七层入口
ConfigMap/Secret      # 配置/敏感数据
PersistentVolume/PVC  # 持久存储
```

### Q4. 声明式 vs 命令式？
- 命令式：告诉系统"做什么动作"（`docker run`、`kubectl run`）。
- 声明式：告诉系统"期望状态是什么"（YAML），系统不断 reconcile 使实际状态趋近期望。
- k8s 全部声明式：`kubectl apply -f deploy.yaml`，删除 Pod 后控制器自动重建。
- 优势：幂等、可重入、易 GitOps（ArgoCD/Flux）。

---

## 二、Pod 深度

### Q5. Pod 为何不是容器？
- Pod 是一组**共享 Linux namespace 的容器**：相同 netns、utsns、ipcns，但 mount/userns 可隔离。
- Pod 内多容器共享 localhost + 共享 volume，便于 sidecar 模式（service mesh、日志采集、配置 reload）。
- Pod 是最小调度单元，不能跨 Node。
- k8s 不直接管容器，而是管 Pod，容器由 Pod 内 kubelet 通过 CRI 调度。

### Q6. Pod 内容器为什么共享 netns？
- 同 Pod 容器间通过 `localhost` 互通，无需暴露端口。
- Pod 有唯一 IP，每个容器端口不能冲突。
- 这也意味着 Pod 内通信无加密，敏感 sidecar 也需注意。
- 设计哲学：把紧耦合的多进程"打包"成一个调度原子。

### Q7. initContainer vs sidecar（1.28+）？
- **initContainer**：在主容器前**串行**执行，全部成功才启动主容器。常用于：等依赖就绪、下载配置、改文件权限。
- **sidecar（1.28 native sidecar，1.29 GA）**：与主容器并行，但有独立 lifecycle，可作为日志/网络代理。
- 老版 sidecar = 普通 container，重启策略与主容器一致，主容器退出 sidecar 还在跑导致 Pod 拖延 → native sidecar 解决此问题。

### Q8. Pod 生命周期与状态？
| Phase | 含义 |
|---|---|
| Pending | 已创建，未运行（等调度、拉镜像、PV 绑定） |
| Running | 所有容器已启动，至少一个还在运行 |
| Succeeded | 所有容器成功退出且不再重启（Job） |
| Failed | 所有容器退出，至少一个失败 |
| Unknown | 通常是与 Node 失联 |

- **Conditions**：`PodScheduled`、`Initialized`、`ContainersReady`、`Ready`。
- **Container states**：`Waiting`、`Running`、`Terminated`。

### Q9. Probe（探针）三件套？
| Probe | 用途 | 失败后果 |
|---|---|---|
| **liveness** | 是否要重启容器 | 失败 N 次 → 重启 |
| **readiness** | 是否进 Service endpoints | 失败 → 从 endpoints 摘除，不重启 |
| **startup** | 是否启动完成 | 启动前不跑 liveness/readiness |

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8080 }
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3
```
- **关键**：readiness 失败时 Pod 仍 Running，仅切流，配合滚动升级避免把流量打到未就绪容器。

### Q10. 资源 requests 与 limits？
- `requests`：调度依据，节点资源必须满足 sum(requests) 才能调度。
- `limits`：硬上限，CPU 用 cfs quota 限制，memory 触发 OOMKill。
- **关键坑**：CPU limit 是 throttle 不是 OOM；只设 limit 不设 request → 调度器视 request=limit，可能与其它 Pod 抢资源。
- QoS 等级（决定 OOM 顺序）：
  - **Guaranteed**：requests == limits（CPU & mem 都设且相等）。
  - **Burstable**：有 request，但未满足 Guaranteed。
  - **BestEffort**：都没设，最先被 OOM。

### Q11. Pod 亲和与反亲和？
- **nodeSelector**：简单 key=value 硬约束（已过时）。
- **nodeAffinity**：required（硬）/ preferred（软），支持 In/NotIn/Exists/Gt/Lt。
- **podAffinity**：把 Pod 调到与某 Pod 同 topology（同 zone）。
- **podAntiAffinity**：分散 Pod（如副本不要全在一个节点上）。
- **topologySpreadConstraints**：更均匀的跨 zone 分布。

### Q12. Taint 与 Toleration？
- Taint：给 Node 加"污点"，默认不容纳 Pod。
  - `NoSchedule`：禁止调度。
  - `PreferNoSchedule`：尽量不调度。
  - `NoExecute`：已有 Pod 也驱逐。
- Toleration：Pod 声明能"容忍"该 taint。
- 典型：GPU/NPU 节点加 taint，只让需要 GPU 的 Pod 容忍。
```bash
kubectl taint node node1 nvidia.com/gpu=true:NoSchedule
```

---

## 三、控制器（Controller）

### Q13. Deployment 滚动更新原理？
- 修改 `spec.template` → 创建新 ReplicaSet → 逐步扩新 RS、缩旧 RS。
- 控制参数：
  - `maxSurge`：可超过期望副本数的最大值（默认 25%）。
  - `maxUnavailable`：滚动期间允许的不可用副本数（默认 25%）。
- `kubectl rollout status/undo/history` 看进度、回滚、看历史。
- 版本号在 `revisionHistoryLimit` 限定的 RS 中。

### Q14. StatefulSet 关键特性？
- Pod 名稳定：`<sts-name>-0`、`<sts-name>-1` ... 顺序创建、逆序销毁。
- 每个有稳定 DNS：`<pod-name>.<service-name>.<ns>.svc.cluster.local`。
- 每个 Pod 绑定独立 PVC（基于 `volumeClaimTemplates`）。
- 适合：数据库（MySQL/Postgres/ZooKeeper）、分布式 KV、Kafka。
- 部署模式：
  - **OrderedReady**（默认）：0->1->2，前一个 Ready 才下一个。
  - **Parallel**：并行创建，无序号依赖。

### Q15. DaemonSet 用例？
- 每节点跑一个 Pod：
  - 日志采集（Filebeat、Fluentd）。
  - 网络插件（Calico、Cilium、kube-proxy）。
  - 存储 daemon（Ceph CSI、本地盘）。
  - 监控 Exporter（node-exporter、DCGM-Exporter、NPU-Exporter）。
  - 设备 plugin（NVIDIA device plugin、昇腾 device plugin）。

### Q16. Job 与 CronJob？
- Job：跑完即退。`completions=N` 跑 N 个成功；`parallelism=M` 并发 M 个；`backoffLimit=6` 失败重试上限。
- CronJob：定时调度，spec 与 Job 类似。
  - `concurrencyPolicy`：`Allow`/`Forbid`/`Replace`，控制重叠运行。
  - 注意时区：默认用 controller manager 所在时区。

---

## 四、Service 与网络

### Q17. Service 四种类型？
| 类型 | 含义 | 典型 |
|---|---|---|
| **ClusterIP**（默认） | 集群内 VIP，仅集群内可达 | 内部服务互调 |
| **NodePort** | 在每节点开 30000-32767 端口 | 简单外暴 |
| **LoadBalancer** | 云厂商自动创建 LB | 公网入口 |
| **ExternalName** | CNAME 到外部域名 | 集群内调用外部 |

### Q18. Service 与 Endpoints 关系？
- Service 有一组 Endpoints（Pod IP:port 列表），由 Endpoints/EndpointSlice 控制器根据 `readiness` probe 自动维护。
- kube-proxy watch Endpoints → 在每个节点写 iptables/IPVS 规则，把 ClusterIP DNAT 到 Pod IP。
- readiness 失败的 Pod 从 Endpoints 摘除 → 不收流量。

### Q19. kube-proxy 的 iptables vs IPVS 模式？
- **iptables**：每 Service 一条链，规则 O(n) 查找，万级 Service 性能下降。
- **IPVS**：内核 L4 LB，基于哈希表 O(1)，支持更多 LB 算法（rr/wrr/lc/sh 等），适合大规模集群。
- 默认 iptables，`--mode=ipvs` 切换，需内核加载 ipvs 模块。

### Q20. Ingress 与 Gateway API？
- **Ingress**：七层 HTTP/HTTPS 入口，需要 Ingress Controller（nginx-ingress、traefik、istio-ingress）。
- **IngressClass**：选择哪个 controller 处理。
- **Gateway API**（GA in 1.27）：更通用的七层抽象，`GatewayClass`/`Gateway`/`HTTPRoute` 三层模型，支持多协议、跨命名空间路由。
- 大模型推理服务：Service + Ingress 暴露 OpenAI 兼容 API，加 TLS 终止 + 路径前缀路由。

### Q21. DNS 在 k8s 怎么工作？
- CoreDNS（Deployment 形式）+ `kube-dns` Service（ClusterIP 固定）。
- 每个 Pod 默认 resolv.conf 指向 kube-dns，search domain 加 `ns.svc.cluster.local` 等。
- Pod 名解析：<pod-ip-with-dash>.ns.pod.cluster.local（IP 用 `-` 替 `.`）。
- Headless Service（ClusterIP=None）解析到 Pod IP 列表（StatefulSet 必备）。

---

## 五、存储

### Q22. PV / PVC / StorageClass？
- **PV**（PersistentVolume）：集群级资源，代表一块存储。
- **PVC**：用户对存储的"申请"（容量、access mode）。
- **StorageClass**：动态创建 PV 的模板（provisioner + 参数）。
- 静态：管理员手动建 PV；动态：PVC 创建时 StorageClass 调 CSI 自动创建。

### Q23. accessModes？
- `ReadWriteOnce`（RWO）：单节点读写（最常见）。
- `ReadOnlyMany`（ROX）：多节点只读。
- `ReadWriteMany`（RWX）：多节点读写（NFS/CephFS/Filestore 才支持）。
- `ReadWriteOncePod`（1.27+）：单 Pod 读写，避免同节点多 Pod 抢挂。

### Q24. CSI（Container Storage Interface）？
- 标准接口，k8s 与存储驱动解耦。
- 三组件：`identity` / `controller`（创建卷、快照） / `node`（挂载到 Pod）。
- 典型 CSI：CSI-HostPath（dev）、AWS EBS CSI、Ceph CSI、阿里云 NAS/ESSD CSI。
- 大模型推理：模型权重放 NFS/NAS RWX，多 Pod 共享读取，节省 NPU 节点本地盘。

### Q25. 本地盘 vs 网络盘选型？
| 场景 | 选 |
|---|---|
| 模型权重多 Pod 只读共享 | NAS（RWX） |
| 训练 ckpt 高吞吐 | 本地 NVMe / ephemeral 盘 |
| 数据库、StatefulSet | 块存储（RWO） |
| 容器镜像层 | overlay2 on local ssd |
| 临时缓存 | emptyDir + Memory/SSD |

---

## 六、调度与扩展

### Q26. 调度器如何工作？
1. **过滤（Predicate / Filter）**：去掉不满足硬条件的 Node（资源不足、taint 不容忍、nodeSelector 不匹配、亲和违反）。
2. **打分（Priority / Score）**：剩余 Node 按策略打分（`LeastRequested`、`BalancedAllocation`、`NodeAffinity`、`PodTopologySpread`、`InterPodAffinity`）。
3. **绑定（Bind）**：选最高分 Node，写 Pod 的 `nodeName`。
- 调度器是单点瓶颈 → 1.19+ 默认开启 `EvenPods` 与 cache 优化；大规模可启 `DefaultPodTopologySpread` + 多调度器。

### Q27. 扩展资源（Extended Resource）？
- 自定义资源类型，例如 `nvidia.com/gpu`、`huawei.com/ascend-910`、`example.com/fpga`。
- Device Plugin 上报节点可用资源 → kubelet 上报 → API Server 可见 → Pod 请求 → kubelet 把 device 文件挂进容器。
- 大模型推理 Pod 请求 GPU/NPU 资源，由调度器分到有资源的节点。

### Q28. Pod 重启策略与回退？
- `Always`（默认）：退出就重启（除非 Job）。
- `OnFailure`：仅非 0 退出码重启。
- `Never`：不重启。
- CrashLoopBackOff：kubelet 重启失败指数退避（10s → 20s → 40s ... → 5min），表面看 Pod 在反复 crash。

### Q29. 节点驱逐（Eviction）？
- 节点压力（memory/diskpressure/pidpressure）触发 kubelet 驱逐 Pod。
- 按 QoS 等级 + Pod 优先级排序，先驱逐 BestEffort。
- `kubectl drain <node>` 主动驱逐 + cordon，`--ignore-daemonsets` 忽略 DaemonSet。

---

## 七、配置与密钥

### Q30. ConfigMap 与 Secret？
- ConfigMap：明文配置，支持 `data`（字符串）和 `binaryData`（base64）。
- Secret：同样 base64 存储，但分类型（docker-registry/tls/opaque/bootstrap），集群级 RBAC 控制。
- 用法：env 注入、volume 挂载（key→文件名）、imagePullSecret。
- **安全**：base64 不是加密，要安全用 etcd encryption-at-rest 或外部密钥（Vault、Sealed Secrets、External Secrets）。

### Q31. ConfigMap 更新后 Pod 自动生效吗？
- env 方式：**不会**，必须重启 Pod。
- volume 挂载方式：kubelet 周期刷新（默认 ~1 分钟），不重启也能看到新内容，但应用代码要 watch 或 reload。
- 最佳实践：把配置作为 volume + 应用 reload（如 nginx -s reload、Prometheus /-/reload API）。

### Q32. DownwardAPI 是什么？
- 让 Pod 把自身元数据（pod 名、IP、namespace、labels、resource limits）暴露为 env 或文件。
- 用途：Pod 内进程自识别身份，例如日志带上 pod 名、应用按 limit 动态配置缓存大小。

---

## 八、安全

### Q33. ServiceAccount / RBAC？
- ServiceAccount：Pod 的"身份"，挂载 token（1.24+ 改成 projected token，可旋转）。
- Role/ClusterRole：定义权限（资源+动词）。
- RoleBinding/ClusterRoleBinding：把 Role 绑定到 SA/User/Group。
- `kubectl auth can-i list pods -n prod` 测试权限。

### Q34. Pod Security Admission（PSA，1.25+）？
- 取代 PodSecurityPolicy。
- 三种级别：`privileged` / `baseline` / `restricted`，按 namespace label 启用。
- restricted 强制非 root、不挂 hostPath、不加全部 capability 等。

### Q35. NetworkPolicy？
- 默认命名空间内 Pod 全互通。NetworkPolicy 显式声明允许哪些 Pod/namespace 通信。
- 需要 CNI 支持（Calico、Cilium 默认支持；Flannel 需配合）。
- 典型：数据库 Pod 只让特定 namespace 的 Pod 访问 5432。

---

## 九、AI Infra 实战

### Q36. 部署大模型推理服务典型 Pod spec？
```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: vllm-qwen2 }
spec:
  replicas: 2
  selector: { matchLabels: { app: vllm-qwen2 } }
  template:
    metadata: { labels: { app: vllm-qwen2 } }
    spec:
      containers:
      - name: vllm
        image: registry.example.com/vllm:v0.6.3
        args:
        - --model=/models/qwen2-7b
        - --tensor-parallel-size=2
        - --gpu-memory-utilization=0.9
        - --max-model-len=8192
        ports: [{ containerPort: 8000 }]
        resources:
          limits:
            nvidia.com/gpu: 2
            memory: "32Gi"
        readinessProbe:
          httpGet: { path: /health, port: 8000 }
          initialDelaySeconds: 60
        volumeMounts:
        - { name: models, mountPath: /models }
      volumes:
      - name: models
        persistentVolumeClaim: { claimName: models-nfs }
      tolerations:
      - { key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }
```

### Q37. 多副本大模型推理如何让流量均分？
- Service + IPVS kube-proxy：每请求按 rr 转发。
- vLLM 自带连续批处理，单 Pod 内吞吐足够高时副本数 = ceil(目标QPS / 单Pod QPS)。
- 想要亲和 / 路由：用 Gateway API + 路径前缀路由到不同 model deployment。
- 会话亲和（sessionAffinity=ClientIP）避免多 Pod KV cache 重复（适用于启用 prefix cache 时）。

### Q38. GPU 资源限制的坑？
- `nvidia.com/gpu: 2` 把 2 张 GPU 整卡分给 Pod，**不能多 Pod 共享一张 GPU**（需 MIG 或 MPS）。
- 想分时复用：NVIDIA MIG（A100/H100 切片）→ 资源声明 `nvidia.com/mig-1g.10gb`。
- 显存不够通常导致 Pod OOMKilled（cuda OOM → 进程退出）。
- 监控：DCGM-Exporter + Prometheus + Grafana。

### Q39. 昇腾 NPU 在 k8s 怎么用？
- 装 Ascend device plugin（DaemonSet 形式）上报 `ascend-910-xxx` 资源。
- Pod 请求 `huawei.com/ascend-910: 8`，调度器分到含 8 卡的节点。
- 挂载 `/dev/davinci*`、`/dev/davinci_manager`、`/dev/devmm_svm`、`/dev/hisi_hdc`。
- CANN 环境通过 initContainer 拷贝 / ConfigMap 注入 env。
- HCCL 多卡通信通过 hostNetwork + RDMA/RoCE，确保 Pod 拿到整机的 8 张卡（亲和性约束）。

### Q40. k8s 大规模推理集群常见瓶颈？
- **etcd**：3-5 节点，避免大对象写入，`--max-request-bytes` 调大。
- **API Server**：list 全量 watch 太多 → 改用 informer cache、字段过滤。
- **kube-proxy**：万级 Service 用 IPVS。
- **节点资源碎片**：daemon 占了 GPU 节点的 CPU/mem，导致 GPU Pod 调度不上，用 `gpu-plugin` 等专用调度器或 descheduler 重平衡。

---

## 十、一页速记卡

| 类别 | 必背 |
|---|---|
| 控制面 | apiserver/etcd/scheduler/controller-manager；节点 kubelet/kube-proxy/containerd/CNI/CSI |
| 声明式 | apply 改 spec → 控制器 reconcile → 实际趋近期望 |
| Pod | 同 netns 共享 localhost；init/sidecar；liveness/readiness/startup；requests vs limits |
| QoS | Guaranteed/BestEffort 三档；OOMKilled 顺序 BestEffort 优先 |
| 控制器 | Deployment 滚动 maxSurge/maxUnavailable；StatefulSet 稳定名+PVC；DaemonSet 每节点一个 |
| Service | ClusterIP/NodePort/LB/ExternalName；ClusterIP 经 kube-proxy DNAT 到 Pod |
| 存储 | PV/PVC/StorageClass；accessModes RWO/ROX/RWX；CSI 解耦 |
| 调度 | Filter→Score→Bind；Taint/Toleration；Affinity/Anti；topologySpread |
| 安全 | SA+RBAC；PSA restricted；NetworkPolicy；最小权限 |
| AI infra | device plugin 上报 nvidia/ascend 资源；GPU Pod 请求资源；NPU 挂 /dev/davinci* |
