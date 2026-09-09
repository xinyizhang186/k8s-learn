# Kubernetes v1.35 / v1.36 关键特性汇报方案（基于 v1.34 基线，60 分钟）

## 汇报目标

本次汇报不是逐条朗读 Release Note，而是帮助听众在 1 小时内回答四个问题：

1. 基于 v1.34 的现有能力，v1.35 与 v1.36 分别新增、成熟、废弃或移除了什么？
2. 哪些变化会影响现网安全、资源调度、存储和运维？
3. 哪些 Feature Gate 会改变默认行为、带来兼容风险，或者已经废弃？
4. 升级前、升级中、升级后分别要做什么？

本报告将 **v1.34 视为变更基线**：工作簿中的 v1.35 和 v1.36 信息均应解读为“相对于 v1.34 的累计变化”，而不是只将 v1.36 与 v1.35 做差异比较。因此，汇报中需同时说明“v1.35 已引入但 v1.34 没有的能力”和“v1.36 新增或成熟的能力”，避免遗漏在 v1.35 已发生、但升级到 v1.36 时仍会影响现网的项目。

主讲材料为 `k8sv1.35-v1.36.xlsx`。建议将其全屏打开并使用筛选功能，不再额外制作逐项重复的 PPT；“版本全景”Sheet 已内置开场页和结论页，可直接投屏使用，无需额外制作简报。

## 讲解原则

- 以业务影响组织内容，不按 Excel 行号或特性名称首字母顺序讲。
- 每个重点特性只回答四件事：**解决什么问题、v1.36 有什么变化、谁会受影响、升级时怎么验证**。
- 对 Feature Gate 优先讲默认值变化、兼容性为“否”、建议开启/关闭的条目；其余项目归类说明，不逐个展开。
- 保留原始英文特性名，便于听众在 Kubernetes 文档、参数和日志中检索；中文名用于口头解释。
- 全程控制在 8 到 12 个重点特性内。当前“版本全景”Sheet 已按**业务影响、升级风险、成熟度/可行动性、主题覆盖**四项规则选出并高亮 11 个主讲特性；超出范围的内容通过 Excel 筛选留作答疑，不在主线中展开。

## 第一次汇报的最简路线

不需要先读懂工作簿中的每一行。请严格按以下顺序讲，避免在术语或细节上停留过久：

1. 打开“版本全景”：用开场页说明 v1.34 是基线，并先讲四大主题和升级结论。
2. 打开“重点讲稿”：按编号选择 8–10 项主讲；每项只讲“解决的问题、影响、验证动作”三句话。11 项完整清单用于备选，不要求全部讲完。
3. 需要展示依据时，切到“版本分析”的黄色高亮行；只展示对应行的功能介绍和价值分析，不朗读整段内容。
4. 被问到开关、默认值或兼容性时，切到“特性变更”的绿色高亮行；先读“是否兼容”“默认值变化”和“排查方法”。
5. 听众第一次听到术语时，切到“术语速查”用白话解释一次；不要现场展开底层实现。
6. 最后回到“版本全景”的结论页，确认灰度升级门槛、验证责任人和暂不随升级启用的能力。

对第一次汇报而言，宁可少讲，也不要为了覆盖全部特性而失去主线。遇到暂时答不上来的细节，可直接记录为“会后由平台/存储/安全团队确认”，并回到本次升级的验证行动。

## 会前准备

1. 优先使用 [k8sv1.35-v1.36-translated.xlsx](C:\Users\23363\Desktop\autok8s\k8s_report\k8sv1.35-v1.36-translated.xlsx)，该副本已增加“中文名称”列；原始文件也可作为备用。
2. 打开“版本分析”工作表，将表头固定在第 3 行，并确保能看到“分类、特性名称、特性功能介绍、特性价值领域、特性功能价值分析”。
3. 打开“特性变更”工作表，将表头固定在第 1 行，并准备按“变更类型、默认值变化、是否兼容、建议开启？”筛选。
4. **不会自行确认集群现状时，按下面最小清单收集信息即可。**在有只读 `kubectl` 权限的终端执行命令，将输出保存为文本；没有权限时把本清单交给平台/运维同事，不要猜测。\
   - 集群与运行时版本：`kubectl get nodes -o wide`；`kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\\t"}{.status.nodeInfo.kubeletVersion}{"\\t"}{.status.nodeInfo.containerRuntimeVersion}{"\\n"}{end}'`。\
   - CSI 驱动：`kubectl get csidrivers` 和 `kubectl get pods -A | grep -i csi`（Windows PowerShell 可将 `grep` 替换为 `Select-String csi`）。\
   - cgroup v2：请节点管理员在任一节点执行 `test -f /sys/fs/cgroup/cgroup.controllers && echo cgroup-v2 || echo cgroup-v1`；没有节点权限时，在汇报中明确标记为“待确认”。\
   - GPU/AI/DRA 场景：向业务或平台负责人确认是否有 GPU、RDMA、FPGA、分布式训练或 `ResourceClaim` 使用场景；没有即记录“当前无 DRA 试点需求”。\
   - kubelet API / RBAC 场景：让安全或平台同事提供访问 kubelet 的监控、日志、巡检组件清单；对已知 ServiceAccount 可执行 `kubectl auth can-i get nodes/proxy --as=system:serviceaccount:<命名空间>:<服务账号>` 作初步核查。
5. **不会准备 Feature Gate 配置和关键工作负载清单时，采用“导出 + 标记”的轻量做法。**这些操作均为只读，不会修改集群。\
   - 导出工作负载清单：`kubectl get deploy,statefulset,daemonset,job,cronjob -A -o wide > workloads-before-upgrade.txt`。从输出中标记有状态应用（StatefulSet）、核心入口/网关、监控日志组件、GPU/批处理作业和高优先级业务。\
   - 收集控制面 Feature Gate：优先查看集群部署配置，例如 `kubectl -n kube-system get configmap kubeadm-config -o yaml > kubeadm-config.txt`；若控制面采用静态 Pod 或托管服务，请向集群管理员索取 kube-apiserver、kube-controller-manager、kube-scheduler、kubelet 的启动参数或产品控制台截图。\
   - 只需把实际启用的 Feature Gate 与“特性变更”Sheet 中“是否兼容=否”“默认值变化”“Deprecated”三类行逐项比对；取不到配置时，在汇报行动项中注明“配置待平台团队确认”，不要自行开启或关闭开关。

## 60 分钟议程

| 时间 | 主题 | 主用 Sheet | 讲解产出 |
| --- | --- | --- | --- |
| 0-5 分钟 | 背景、范围与结论预览 | 两张表 | 让听众知道本次是升级影响评审，而非功能罗列 |
| 5-12 分钟 | 版本全景与优先级 | 版本全景（新增 Sheet）+ 版本分析 | 形成安全、存储/DRA、调度、运维四个主题，并明确 v1.34 基线 |
| 12-25 分钟 | 安全与身份能力 | 版本分析 | 明确最小权限、身份集成、准入控制的收益和检查项 |
| 25-37 分钟 | 存储与动态资源分配 | 版本分析 | 明确状态型业务与 GPU/设备调度收益和前置条件 |
| 37-45 分钟 | 调度、资源与可观测性 | 版本分析 | 明确弹性、性能和运维可见性的变化 |
| 45-54 分钟 | Feature Gate 与兼容性核查 | 特性变更 | 形成必须验证、建议评估、仅需知悉三类清单 |
| 54-60 分钟 | 升级行动、风险与决策 | 两张表 | 确认负责人、验证项和是否进入灰度升级 |

## 0-5 分钟：开场话术

可直接使用以下表述：

> 本次以 v1.34 为基线，评审 v1.35 与 v1.36 的累计能力和行为变化，而不是只比较两个相邻版本。我们会先看哪些能力进入稳定阶段并能带来收益，再看哪些 Feature Gate 改变了默认行为或存在兼容影响，最后输出升级前必须完成的验证清单。今天的结论不是“是否立即启用所有新特性”，而是“哪些能力可纳入平台路线，哪些风险必须在灰度环境先验证”。

在“版本全景”中先指向“版本基线与解读口径”，再说明 v1.35 与 v1.36 均基于 v1.34 的累计变化。随后切换到“版本分析”，说明它包含成熟、Beta、Alpha 和弃用/移除信息。强调优先级顺序：**GA 能力优先评估采用，默认值变化优先评估风险，Alpha/Beta 仅按场景试点，弃用/移除优先安排整改。**

## 5-12 分钟：版本全景与筛选方法

先展示新增的“版本全景”Sheet：用其顶部的“版本基线与解读口径”说明本次范围，再用“四大主题”表完成 2 分钟概览。随后切换到“版本分析”，按“特性价值领域”筛选并快速浏览。建议将条目归入下表，而不要逐行说明。

| 主题 | 代表特性 | 应传达的结论 |
| --- | --- | --- |
| 安全与身份 | Fine-grained API authorization、External ServiceAccount token signer、Constrained impersonation、Pod certificates | 控制面和节点 API 的最小权限能力增强，适合纳入安全基线 |
| 存储与 DRA | Volume group snapshots、Mutable volume attach limits、DRA GA/Beta 特性 | 有状态应用恢复与设备/GPU 资源治理更成熟，但依赖 CSI 驱动和设备插件协同 |
| 调度与弹性 | In-place Pod resource update、Workload Aware Scheduling、Node declared features、Gang scheduling | 为批处理、AI、弹性扩缩容提供更精细的资源与放置能力 |
| 运维与可观测性 | Node log query、Statusz、Flagz、CRI list streaming、Native histograms | 排障和指标能力增强，适合作为平台运维能力建设项 |
| 升级治理 | externalIPs、gitRepo、Ingress NGINX、cgroup v1、kube-proxy ipvs、containerd v1.x | 需确认当前依赖并在升级计划中给出替代或迁移时间表 |

过渡话术：

> 接下来不按所有特性逐条介绍，而是选择直接改变安全边界、数据恢复能力和调度方式的项目。其余项目在表中仍然可查，并将在 Feature Gate 环节用筛选规则统一处理。

## 12-25 分钟：安全与身份能力

在“版本分析”筛选 `DFX:安全`，按以下顺序讲解。

### 1. Fine-grained API authorization（细粒度 API 授权）

- **价值**：将 kubelet HTTPS API 的授权从宽泛的 `nodes/proxy` 收敛到更细的权限，降低监控、日志和诊断组件的过度授权风险。
- **v1.36 状态**：`KubeletFineGrainedAuthz` 已稳定。
- **关注对象**：使用 kubelet API 的监控、日志、探针、节点运维工具，以及相关 RBAC 规则。
- **汇报时的验证结论**：列出当前拥有 `nodes/proxy` 的 ServiceAccount；在灰度节点验证实际访问所需的最小 verbs/资源；确认监控和告警没有出现 403。

### 2. API for external signing of ServiceAccount tokens（ServiceAccount 令牌外部签名 API）

- **价值**：可将 ServiceAccount Token 签名对接外部 IAM、KMS 或企业密钥体系，减少控制面内置签名的耦合。
- **v1.36 状态**：外部签名者能力稳定。
- **关注对象**：已有企业身份平台、多集群统一身份体系或密钥托管合规要求的团队。
- **汇报时的边界**：这不是必须随升级立即切换的能力。应作为身份架构演进项目，先验证公钥发现、缓存、令牌过期策略和故障降级。

### 3. Constrained impersonation（受约束的模拟身份）与 Pod certificates（Pod 证书）

- **价值**：前者限制模拟身份的使用范围，后者为工作负载身份提供证书化能力，两者都服务于更可控的身份访问。
- **行动建议**：安全团队评估现有 impersonation 使用情况；平台团队将 Pod 证书能力纳入服务网格、mTLS 或工作负载身份方案的候选项。

### 4. Mutating admission policies（变更准入策略）

- **价值**：提供更声明式的准入变更能力，减少部分自定义 Webhook 的维护负担。
- **行动建议**：不在生产升级日直接替换现有 Webhook。选择低风险策略在测试集群比对准入结果、延迟和失败行为后再推广。

本段结束时应得到的结论：**安全基线优先验证 kubelet 细粒度授权；外部令牌签名、Pod 证书和声明式准入进入后续平台演进路线。**

## 25-37 分钟：存储与 DRA

### 1. Volume group snapshots（卷组快照）

- **价值**：可对多个 PVC 创建崩溃一致性快照并按同一恢复点恢复，改善数据库、分布式中间件等多卷工作负载的备份与恢复能力。
- **重点追问**：CSI 驱动是否支持 VolumeGroupSnapshot；快照控制器与 CRD 是否已部署；恢复流程、存储空间和保留策略是否已经演练。
- **汇报建议**：展示“特性功能介绍”中的现状与增强，用一个“数据库数据卷 + 日志卷”恢复场景说明收益即可。

### 2. Mutable volume attach limits（可变卷挂载限制）

- **价值**：kubelet 可动态更新节点卷挂载容量，调度器不会长期基于过时的 CSI 容量判断调度。
- **重点追问**：CSI 驱动对容量耗尽错误的行为、节点卷使用率、历史上是否出现 Pod 因卷挂载上限失败。
- **行动建议**：在压测或预发布环境验证节点卷数量逼近上限时，容量更新是否及时、调度失败是否减少。

### 3. DRA features graduating to Stable（升级为稳定版的 DRA 特性）

- **价值**：管理员访问 ResourceClaim、设备备选优先级等能力稳定，适合更大规模 GPU、加速卡和可共享设备治理。
- **重点追问**：是否存在 GPU/AI、RDMA、FPGA 等设备资源；设备插件、驱动与 ResourceClaim API 是否已验证兼容；租户隔离和管理员权限是否明确。
- **建议定位**：没有设备调度需求的集群仅需知悉；有 AI 平台需求的集群应建立专门试点，不与普通业务升级绑定。

### 4. 其他存储相关条目

快速点到即可：`CSIServiceAccountTokenSecrets` 便于 CSI 驱动获取 ServiceAccount Token；`ImageVolume`/OCI artifact 卷源为镜像化分发提供新选择；`StorageVersionMigrator` 关系到存储版本迁移治理。强调这些项目都应以驱动和组件兼容矩阵为前置条件。

本段结论：**卷组快照和可变挂载限制是有状态业务的直接收益；DRA 是设备资源平台化的中长期能力。**

## 37-45 分钟：调度、资源与可观测性

按“功能：调度”和相关资源项选择下列项目。

| 特性 | 推荐讲法 | 升级前检查 |
| --- | --- | --- |
| In-place update of Pod resources | 资源可在不重建 Pod 的情况下更新，减少变更扰动 | HPA/VPA、准入策略、控制器以及工作负载对资源变更的行为 |
| Workload Aware Scheduling / WorkloadAwarePreemption | 让调度与抢占更贴近工作负载特征 | 是否有批处理、AI、队列作业；先在专用节点池验证 |
| Node declared features | 节点可在调度前暴露能力，改善异构节点调度 | 节点标签、污点、特性发现链路的一致性 |
| Gang scheduling | 一组 Pod 同时获得资源才启动，适合分布式训练 | 当前是否使用 Volcano/Kueue 等方案，避免策略重叠 |
| HPA configurable tolerance / scale to zero | 弹性策略更可控，且可支持自定义指标缩容到零 | 指标可用性、冷启动 SLA、最小副本和告警策略 |
| Resource health status | 将资源健康信息暴露给控制器和运维侧 | 现有告警、控制器和设备健康信号能否消费该状态 |

随后用 2 分钟讲运维提升：`Node log query` 可减少登节点取日志的依赖，`Statusz`/`Flagz` 有助于观察组件状态与实际开关，`CRI list streaming` 和原生直方图有利于高规模场景排障与指标分析。这里不需要承诺立即启用所有能力，只需要将其纳入运维工具评估。

## 45-54 分钟：Feature Gate 与兼容性核查

切换到“特性变更”工作表。这一段的核心是把大量行压缩为可执行的筛选动作。

### 现场筛选顺序

1. 首先筛选“是否兼容”为 `否`：这是升级前必须逐项确认的最高优先级集合。
2. 在结果中查看“默认值变化”和“默认值锁定”：默认开启、由 false 变 true、或已锁定的项目优先于仅新增且默认关闭的项目。
3. 查看“建议开启？”为“开启”或“关闭”的行，结合“排查方法”和“补充说明”形成验证项。
4. 最后筛选“变更类型”为 `Deprecated`：记录移除/弃用项、替代方案和整改截止时间，不要把它们混进新功能演示。

### 推荐重点展示的条目

| Feature Gate | 为什么要讲 | 应如何检查 |
| --- | --- | --- |
| `AuthorizePodWebsocketUpgradeCreatePermission` | 影响 exec、attach、portforward 等 Pod 子资源的 RBAC 授权 | 检查相关角色是否拥有 `create`；在灰度集群实际执行命令验证 |
| `CRDObservedGenerationTracking` | CRD 控制器可通过 `status.observedGeneration` 判断是否处理最新 spec | 检查自研/三方控制器对该字段的使用与兼容性 |
| `CSIServiceAccountTokenSecrets` | CSI 驱动可选择接收 ServiceAccount Token | 确认驱动版本和是否使用该字段 |
| `KubeletFineGrainedAuthz` | 与安全基线直接相关 | 核查 kubelet API 调用方的 RBAC 并观察 403 |
| `ImageVolume` / `ImageVolumeWithDigest` | 新卷源能力可能影响镜像、CRI 与安全策略 | 只在预发布验证，确认摘要、拉取策略和准入策略 |
| `InPlacePodVerticalScaling` 系列 | 影响 Pod 资源更新行为 | 与 HPA/VPA、PDB、业务运行时联调 |
| `UserNamespacesSupport` 系列 | 容器隔离增强但涉及运行时与网络限制 | 验证 CRI、CNI、hostNetwork 限制和工作负载兼容性 |
| `GitRepoVolumeDriver`、`ChangeContainerStatusOnKubeletRestart` | 已弃用或默认行为有变化 | 清查遗留 YAML/脚本，避免依赖旧行为 |

说明口径：对于表中“是否兼容”为“是”、默认值不变且当前未使用的项目，直接归为“已评估，无需专项行动”；不要因条目多而消耗主讲时间。

## 54-60 分钟：升级行动与结论

最后用下表作为汇报结尾。实际汇报时可直接在 Excel 新建一个筛选视图或增加批注，将责任人和日期补齐。

| 优先级 | 行动 | 责任角色 | 完成标准 |
| --- | --- | --- | --- |
| P0 | 清查所有 kubelet API 调用方及其 RBAC | 平台 + 安全 | 灰度环境无非预期 403，最小权限规则已确认 |
| P0 | 筛选“是否兼容=否”的 Feature Gate 并逐项验证 | 平台 + 应用负责人 | 每项有测试证据、风险结论和回退方式 |
| P0 | 清查 cgroup v1、gitRepo、externalIPs、Ingress NGINX、ipvs、containerd v1.x 依赖 | 平台 + 基础设施 | 有替代方案或明确不受影响的证据 |
| P1 | 验证卷组快照与可变卷挂载限制 | 存储平台 | CSI 兼容、备份恢复演练通过 |
| P1 | 验证原地资源更新和 HPA 容差 | 应用平台 | 核心工作负载在灰度环境表现符合预期 |
| P2 | 评估 DRA、外部令牌签名、Pod 证书 | 架构 + 安全 + AI 平台 | 完成需求判断和试点设计，不阻塞本次基础升级 |

建议以如下结论结束：

> 建议进入灰度升级准备，但以 Feature Gate 兼容性核查和弃用依赖清理作为前置门槛。安全方面优先完成 kubelet 细粒度授权验证；存储方面优先完成 CSI 与卷组快照验证；DRA、外部身份签名和高级调度能力采用“场景驱动、独立试点”的方式推进，不在本次升级中强制全面启用。

## Q&A 备用路径

当听众询问未展开项目时，按以下路径回答并在 Excel 中定位：

1. 先在“版本分析”按特性名称或价值领域定位，说明功能价值与成熟度。
2. 再到“特性变更”搜索同名 Feature Gate，检查阶段、默认值、兼容性、排查方法和参考资料。
3. 若条目没有兼容风险或默认值变化，说明其纳入“已评估，无专项行动”；若有风险，则加入 P0/P1 验证清单。

这样既能保持主线紧凑，也能让 Excel 成为现场可追溯的事实依据。
