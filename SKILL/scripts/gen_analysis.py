#!/usr/bin/env python3
"""Generate analysis.json: auto-generate feature_changes text (特性变更) and
multi-feature enhancement text (版本分析 multi-feature entries).

Single-feature and risk version_analysis entries are left for the LLM (phase 3b)
to write Chinese text from blog content.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


GATE_CN: dict[str, dict[str, str]] = {
    "AuthorizePodWebsocketUpgradeCreatePermission": {
        "cn_desc": "强制对 exec、attach、portforward 等 pod 子资源的 'create' 动词进行鉴权",
        "check_hint": "排查可检查 RBAC 规则是否授予了对 pod 子资源 create 的权限",
        "mechanism": "exec、attach、portforward 等 pod 子资源操作的鉴权此前未统一强制要求 create 动词权限。该特性强制对这些子资源执行 create 动词鉴权，确保所有此类访问均经 RBAC 校验，关闭后可能绕过部分鉴权检查",
    },
    "CRDObservedGenerationTracking": {
        "cn_desc": "检查 CRD 资源的 status.observedGeneration 字段及 conditions 中的 observedGeneration",
        "check_hint": "排查可将 observedGeneration 与 metadata.generation 对比，若 observedGeneration < generation 说明控制器尚未处理最新 spec 变更",
        "mechanism": "在 CRD 的 status 和 conditions 中跟踪 observed generation。observedGeneration 记录控制器已处理的 spec generation 值，客户端可据此判断 spec 变更是否已被 reconcile，避免基于过期状态做决策",
    },
    "CSIServiceAccountTokenSecrets": {
        "cn_desc": "允许 CSI 驱动通过 NodePublishVolumeRequest 的 secrets 字段从 kubelet 接收 ServiceAccount token",
        "check_hint": "排查需确认 CSI 驱动是否支持该字段",
        "mechanism": "CSI 驱动原通过 NodePublishVolumeRequest 的 volume_context 字段接收 ServiceAccount token。该特性改用专用 secrets 字段传递 token，使 token 传递更规范且可独立管理，CSI 驱动需 opt-in 支持新字段",
    },
    "ChangeContainerStatusOnKubeletRestart": {
        "cn_desc": "kubelet 重启时改变 pod 状态",
        "check_hint": "开启会恢复 kubelet 重启导致 pod 状态变化的旧行为",
        "mechanism": "kubelet 重启时此前会重置容器状态，导致健康 Pod 被标记为 NotReady 并从负载均衡器移除。该门控控制此行为，已弃用且默认关闭",
    },
    "ClearingNominatedNodeNameAfterBinding": {
        "cn_desc": "pod 绑定到节点后清除 pod.Status.NominatedNodeName",
        "check_hint": "排查可观察 pod 的 NominatedNodeName 字段在绑定后是否清空",
        "mechanism": "Pod 被调度器抢占时设置 NominatedNodeName 记录预期节点。Pod 绑定到实际节点后该字段不再需要，若不清空会误导 Cluster Autoscaler、Karpenter 等外部调度组件。该特性在 Pod 绑定后自动清除 NominatedNodeName",
    },
    "ComponentFlagz": {
        "cn_desc": "为各组件提供 /flagz 端点，展示当前启动参数",
        "check_hint": "排查可访问各组件的 /flagz 端点",
        "mechanism": "验证组件配置此前需要特权访问宿主机或进程参数。该特性为各组件提供 /flagz HTTP 端点，支持纯文本和结构化 JSON 输出，授权用户可查看启动时的命令行标志",
    },
    "ComponentStatusz": {
        "cn_desc": "为各组件提供 /statusz 端点，展示组件运行状态",
        "check_hint": "排查可访问各组件的 /statusz 端点",
        "mechanism": "排查组件问题此前需要解析非结构化日志。该特性为各组件提供 /statusz HTTP 端点，暴露构建和版本信息（如启动时间、运行时间、Go 版本），支持纯文本和结构化 JSON 输出",
    },
    "ConstrainedImpersonation": {
        "cn_desc": "审计 RBAC 中 impersonate 权限的授予范围，检查 apiserver 日志中 impersonation 相关鉴权决策",
        "check_hint": "需确认现有 impersonate 权限配置是否受影响",
        "mechanism": "Kubernetes 原 impersonation 机制为全有或全无模式——要么允许用户模拟任意身份，要么完全禁止。该特性将 impersonation 约束到特定请求，使模拟权限可按请求级别控制，而非全局开关",
    },
    "ContainerRestartRules": {
        "cn_desc": "支持容器重启策略及重启策略规则，可覆盖 pod 重启策略",
        "check_hint": "排查可检查容器 spec 的 restartPolicy 字段",
        "mechanism": "Pod 级 restartPolicy 此前对所有容器统一生效。该特性引入容器级重启策略规则，可覆盖 Pod restartPolicy，允许单个容器在 Pod restartPolicy 为 Never 时独立重启",
    },
    "CustomCPUCFSQuotaPeriod": {
        "cn_desc": "检查节点 KubeletConfiguration 的 cpuCFSQuotaPeriod 字段",
        "check_hint": "结合 cgroup 的 cpu.cfs_period_us 值验证实际 CFS 周期，默认周期为 100ms",
        "mechanism": "Linux CFS 通过 cpu.cfs_period_us 和 cpu.cfs_quota_us 控制容器 CPU 限额，默认周期 100ms。该特性允许节点通过 KubeletConfiguration 的 cpuCFSQuotaPeriod 自定义周期，适配低延迟或高精度调度需求",
    },
    "DRAConsumableCapacity": {
        "cn_desc": "确认 DRA 驱动是否实现容量计量接口",
        "check_hint": "检查 ResourceClaim 的容量请求与 ResourceSlice 中设备声明的可消费容量是否匹配",
        "mechanism": "DRA 原以整个设备为分配粒度。该特性引入可消耗容量概念，DRA 驱动可按容量单位（如 GPU 显存、FPGA 区域）计量设备资源，ResourceClaim 可按具体容量值请求而非独占整设备",
    },
    "DRADeviceBindingConditions": {
        "cn_desc": "启用设备绑定条件支持，延迟绑定依赖带绑定条件设备的 pod",
        "check_hint": "需同时启用 DRAResourceClaimDeviceStatus，排查可检查 ResourceClaim 的绑定条件状态",
        "mechanism": "DRA 设备可声明绑定条件，表示设备需满足特定状态后才可绑定。该特性延迟依赖此类设备的 Pod 绑定，直到条件满足后才完成绑定。需同时启用 DRAResourceClaimDeviceStatus",
    },
    "DRADeviceTaints": {
        "cn_desc": "允许将设备标记为 tainted，阻止新 pod 使用或导致使用该设备的 pod 停止",
        "check_hint": "排查可检查设备的 taint 状态与 pod 的容忍度配置",
        "mechanism": "类似节点 taint 机制，该特性允许将 DRA 管理的设备标记为 tainted。新 Pod 默认不调度到 tainted 设备，正在使用 tainted 设备的 Pod 可被停止。用户可通过 tolerations 配置容忍特定设备 taint",
    },
    "DRAExtendedResource": {
        "cn_desc": "启用由 DRA 支撑的扩展资源请求",
        "check_hint": "排查可检查 ResourceClaim 与扩展资源的映射关系",
        "mechanism": "扩展资源原通过 Device Plugin 机制提供。该特性允许通过 DRA 框架提供扩展资源请求，使扩展资源可利用 DRA 的结构化参数和驱动模型进行分配",
    },
    "DRAPartitionableDevices": {
        "cn_desc": "启用设备动态分区，按调度时分配的部分对设备分区",
        "check_hint": "排查需确认 DRA 驱动是否支持分区",
        "mechanism": "部分设备（如 GPU）可划分为多个分区供不同 Pod 使用。该特性支持 DRA 驱动按调度时分配的部分动态分区设备，使同一物理设备可被多个 Pod 共享，提高设备利用率",
    },
    "DRAResourceClaimGranularStatusAuthorization": {
        "cn_desc": "启用 ResourceClaim 状态更新的细粒度鉴权",
        "check_hint": "排查可检查 RBAC 是否授予 resourceclaims/binding 的权限",
        "mechanism": "ResourceClaim 的 status 更新原为粗粒度鉴权。该特性拆分为细粒度：更新 status.allocation 和 status.reservedFor 需 resourceclaims/binding 权限，更新 status.devices 需按驱动粒度的 resourceclaims/driver 权限",
    },
    "DeclarativeValidationBeta": {
        "cn_desc": "观察 apiserver 声明式校验相关 metrics（如 declarative_validation_mismatch_total）",
        "check_hint": "确认 Beta 阶段校验规则执行状态，关闭此门控后 Beta 规则退回影子模式（仅记录不拒绝）",
        "mechanism": "该门控是 Beta 阶段声明式校验规则的全局安全开关。开启时强制执行 Beta 规则；关闭时退回影子模式——声明式校验仍运行但仅记录与手写校验的差异 metrics，不拒绝请求。仅在主门控 DeclarativeValidation 开启时生效",
    },
    "DeploymentReplicaSetTerminatingReplicas": {
        "cn_desc": "Deployment 和 ReplicaSet 通过 .status.terminatingReplicas 跟踪终止中的 pod",
        "check_hint": "排查可检查 Deployment/RS 的 status.terminatingReplicas 字段",
        "mechanism": "Deployment 和 ReplicaSet 原仅通过 .status.replicas 等字段跟踪运行中和已完成的 Pod。该特性新增 .status.terminatingReplicas 字段，跟踪正在终止的 Pod 数量及列表，便于监控滚动更新和缩容进度",
    },
    "EnvFiles": {
        "cn_desc": "允许容器从文件读取环境变量",
        "check_hint": "环境变量文件须由 initContainer 生成并位于 emptyDir 卷内，排查可检查 initContainer 与 emptyDir 配置",
        "mechanism": "容器环境变量原通过 spec 或 ConfigMap/Secret 引用注入。该特性允许容器从 emptyDir 卷中的文件读取环境变量——文件须由 initContainer 生成，kubelet 解析文件内容填充容器环境变量",
    },
    "ExtendWebSocketsToKubelet": {
        "cn_desc": "允许 API 服务器向 kubelet 代理 websocket 用于 exec/attach",
        "check_hint": "需 kubelet 声明支持，排查可检查 kubelet 是否支持 websocket 及 API 服务器代理配置",
        "mechanism": "exec/attach 操作原通过 HTTP 升级或 SPDY 代理到 kubelet。该特性使 API 服务器可向支持 WebSocket 的 kubelet 代理 WebSocket 连接用于 exec/attach，需 kubelet 声明支持 WebSocket",
    },
    "HPAConfigurableTolerance": {
        "cn_desc": "启用可配置的 HPA 扩缩容容忍度",
        "check_hint": "排查可检查 HPA 的 tolerance 配置",
        "mechanism": "HPA 原使用硬编码的扩缩容容忍度（scale-up 0%，scale-down 默认 10%）。该特性允许通过 HPA 配置自定义 scale-up 和 scale-down 容忍度，使扩缩容触发行为更精细可控",
    },
    "HostnameOverride": {
        "cn_desc": "允许将任意 FQDN 设置为 pod 的 hostname",
        "check_hint": "排查可检查 pod spec 的 hostname 字段",
        "mechanism": "Pod hostname 原受 DNS 子域名限制（RFC 1123），不允许包含点号等特殊字符。该特性放宽限制，允许将任意 FQDN 设置为 Pod hostname",
    },
    "ImageVolume": {
        "cn_desc": "启用 image volume source",
        "check_hint": "排查可检查 pod spec 的 image volume source 配置",
        "mechanism": "该特性引入 image volume source，可将容器镜像作为卷源挂载到 Pod 中。适用于需要访问其他镜像内容而无需通过 initContainer 拷贝的场景",
    },
    "InPlacePodLevelResourcesVerticalScaling": {
        "cn_desc": "启用 pod 级别资源原地垂直扩缩容",
        "check_hint": "需 InPlacePodVerticalScaling 配合，排查可检查 pod-level resources 配置",
        "mechanism": "Pod 资源原仅在容器级别指定。该特性支持在 Pod 级别指定资源并允许原地垂直调整，需 InPlacePodVerticalScaling 特性配合",
    },
    "InPlacePodVerticalScalingInitContainers": {
        "cn_desc": "允许运行中的非 sidecar init 容器原地扩缩容",
        "check_hint": "排查可检查 init 容器的 resize 配置",
        "mechanism": "原地垂直扩缩容原不支持运行中的 init 容器。该特性扩展至运行中的非 sidecar init 容器，允许对其资源请求/限制进行原地调整",
    },
    "KubeletCrashLoopBackOffMax": {
        "cn_desc": "启用可配置的每节点容器重启退避上限",
        "check_hint": "排查可检查节点 KubeletConfiguration 的 crashLoopBackOff 配置",
        "mechanism": "容器崩溃重启的退避时间原使用集群统一的上限。该特性允许通过 KubeletConfiguration 为每个节点配置自定义退避上限，使退避策略可按节点差异化调整",
    },
    "KubeletEnsureSecretPulledImages": {
        "cn_desc": "启用镜像拉取凭据跟踪，为不同租户授权镜像访问",
        "check_hint": "排查可检查 imagePullSecrets 与租户隔离配置",
        "mechanism": "kubelet 原以节点为单位拉取镜像，不区分拉取凭据来源。该特性使 kubelet 跟踪镜像拉取凭据，按租户隔离镜像访问授权，防止单节点上不同租户的 Pod 交叉访问私有镜像",
    },
    "MutableCSINodeAllocatableCount": {
        "cn_desc": "使 CSINode.Spec.Drivers[*].Allocatable.Count 可变",
        "check_hint": "排查可检查 CSINode 的 Allocatable.Count 字段",
        "mechanism": "CSINode.Spec.Drivers[*].Allocatable.Count 原为不可变字段，节点可分配卷数在注册时固定。该特性使其可变，CSI 驱动可动态更新节点可分配卷数，适应存储容量变化",
    },
    "MutablePodResourcesForSuspendedJobs": {
        "cn_desc": "启用暂停 Job 的可变 pod 资源",
        "check_hint": "排查可检查 Job 的 suspend 与 resource 配置",
        "mechanism": "暂停的 Job 原 Pod 资源不可修改。该特性允许修改暂停 Job 的 Pod 资源，便于在暂停期间调整资源配额后恢复执行",
    },
    "MutableSchedulingDirectivesForSuspendedJobs": {
        "cn_desc": "启用暂停 Job 的可变调度指令",
        "check_hint": "排查可检查 Job 的 suspend 与 nodeSelector/affinity 配置",
        "mechanism": "暂停的 Job 原调度指令不可修改。该特性允许修改暂停 Job 的调度指令，便于在暂停期间调整调度策略后恢复执行",
    },
    "MutatingAdmissionPolicy": {
        "cn_desc": "提供基于 CEL 的变更型准入策略",
        "check_hint": "排查可检查 MutatingAdmissionPolicy 资源配置",
        "mechanism": "类似 ValidatingAdmissionPolicy，该特性引入基于 CEL 的变更型准入策略。管理员可定义 CEL 表达式在准入阶段修改请求对象，无需编写 Webhook 即可实现声明式的变更准入控制",
    },
    "NodeDeclaredFeatures": {
        "cn_desc": "检查 Node.status.declaredFeatures 字段确认节点声明的特性列表",
        "check_hint": "结合调度器配置确认是否启用基于 DeclaredFeatures 的过滤",
        "mechanism": "kubelet 在 Node.status 中填充 declaredFeatures 字段声明节点支持特性。调度器据此过滤，避免将需要特定节点特性的 Pod 调度到不支持的节点",
    },
    "NodeLogQuery": {
        "cn_desc": "启用通过 /logs 端点查询节点服务日志",
        "check_hint": "有安全影响建议按需启用调试，排查可访问节点的 /logs 端点",
        "mechanism": "该特性启用通过 /logs 端点查询节点服务日志。因可能暴露敏感信息，有安全影响，建议仅在调试时按需启用，平时保持禁用",
    },
    "NominatedNodeNameForExpectation": {
        "cn_desc": "扩展 NominatedNodeName 字段表达预期 pod 放置",
        "check_hint": "排查可检查 pod 的 NominatedNodeName 字段",
        "mechanism": "NominatedNodeName 原仅用于调度器抢占场景记录提名节点。该特性扩展其语义为预期 Pod 放置，使调度器与外部组件共享放置意图，改善组件协调",
    },
    "OpportunisticBatching": {
        "cn_desc": "启用调度器的机会性批处理",
        "check_hint": "排查可观察调度器吞吐与延迟",
        "mechanism": "调度器此前按 Pod 逐一处理，对兼容的 Pod 产生冗余计算。该特性通过 Pod 调度签名识别兼容的 Pod 并批量处理，共享过滤和评分结果",
    },
    "PLEGOnDemandRelist": {
        "cn_desc": "启用按需重新列举单个 pod",
        "check_hint": "排查可观察 kubelet PLEG 行为",
        "mechanism": "PLEG 此前按固定间隔全量列举所有 Pod 状态。该特性允许 PLEG 按需重新列举单个 Pod 而非全量，减少不必要的容器状态查询开销",
    },
    "PodTopologyLabelsAdmission": {
        "cn_desc": "启用 PodTopologyLabelsAdmission 准入插件，将节点的 topology.kubernetes.io/{zone,region} 标签复制到 pod/binding 请求",
        "check_hint": "排查可检查 pod 的 topology 标签与插件配置",
        "mechanism": "Pod 原无法在调度时获知节点拓扑信息。该特性启用 PodTopologyLabelsAdmission 准入插件，在 pod/binding 请求中将节点拓扑标签复制到 Binding，使 Pod 调度后可获知所在节点拓扑",
    },
    "RelaxedServiceNameValidation": {
        "cn_desc": "放宽 Service 名称校验",
        "check_hint": "排查可检查 Service 名称是否符合新校验规则",
        "mechanism": "Service 名称原受 DNS 子域名严格限制（RFC 1123）。该特性放宽 Service 名称校验规则，允许更宽松的格式",
    },
    "ReloadKubeletClientCAFile": {
        "cn_desc": "启用 kubelet 客户端 CA 文件热重载",
        "check_hint": "排查可检查 kubelet 的 clientCAFile 配置与重载日志",
        "mechanism": "kubelet 客户端 CA 文件更新后此前需要重启 kubelet 才能生效。该特性使 kubelet 检测到 CA 文件变化时自动热重载，无需重启",
    },
    "ResourceHealthStatus": {
        "cn_desc": "在容器状态中添加 AllocatedResourcesStatus",
        "check_hint": "排查可检查容器 status 的 AllocatedResourcesStatus 字段",
        "mechanism": "容器状态原不包含已分配资源的健康信息。该特性在容器 status 中新增 AllocatedResourcesStatus 字段，反映容器已分配资源的健康状态",
    },
    "ResourceHealthStatusMessage": {
        "cn_desc": "为 AllocatedResourcesStatus 条目添加 message",
        "check_hint": "排查可检查容器 status 的 AllocatedResourcesStatus.message 字段",
        "mechanism": "AllocatedResourcesStatus 此前仅报告设备健康状态（Healthy/Unhealthy/Unknown）而无文字说明。该特性为每个状态条目添加 message 字段，提供设备异常的具体描述信息",
    },
    "RestartAllContainersOnContainerExits": {
        "cn_desc": "容器退出时原地重启 pod（同一节点）",
        "check_hint": "排查可检查 pod 的重启行为与 restartPolicy 配置",
        "mechanism": "Pod 内单个容器退出时，原行为取决于 Pod restartPolicy。该特性在容器退出时原地重启整个 Pod 的所有容器，而非仅重启退出的容器",
    },
    "ServiceCIDRStatusFieldWiping": {
        "cn_desc": "开启后 apiserver 忽略对 ServiceCIDR 根资源 status 字段的写入",
        "check_hint": "该门控已弃用，排查可检查 ServiceCIDR 资源的 status 字段写入行为",
        "mechanism": "ServiceCIDR 根资源的 status 字段此前可被写入。该门控启用后 apiserver 忽略对 status 字段的写入操作，已弃用",
    },
    "StaleControllerConsistencyDaemonSet": {
        "cn_desc": "使 DaemonSet 控制器在 reconcile 前能读取自己的写入",
        "check_hint": "排查可观察 DaemonSet reconcile 一致性",
        "mechanism": "控制器此前在 reconcile 前可能读到缓存的过期数据而非自己的最新写入。该特性使 DaemonSet 控制器在 reconcile 前能读取自己的写入，避免基于过期状态做决策",
    },
    "StaleControllerConsistencyJob": {
        "cn_desc": "使 Job 控制器在 reconcile 前能读取自己的写入",
        "check_hint": "排查可观察 Job reconcile 一致性",
        "mechanism": "控制器此前在 reconcile 前可能读到缓存的过期数据而非自己的最新写入。该特性使 Job 控制器在 reconcile 前能读取自己的写入，避免基于过期状态做决策",
    },
    "StaleControllerConsistencyReplicaSet": {
        "cn_desc": "使 ReplicaSet 控制器在 reconcile 前能读取自己的写入",
        "check_hint": "排查可观察 ReplicaSet reconcile 一致性",
        "mechanism": "控制器此前在 reconcile 前可能读到缓存的过期数据而非自己的最新写入。该特性使 ReplicaSet 控制器在 reconcile 前能读取自己的写入，避免基于过期状态做决策",
    },
    "StaleControllerConsistencyStatefulSet": {
        "cn_desc": "使 StatefulSet 控制器在 reconcile 前能读取自己的写入",
        "check_hint": "排查可观察 StatefulSet reconcile 一致性",
        "mechanism": "控制器此前在 reconcile 前可能读到缓存的过期数据而非自己的最新写入。该特性使 StatefulSet 控制器在 reconcile 前能读取自己的写入，避免基于过期状态做决策",
    },
    "StrictIPCIDRValidation": {
        "cn_desc": "对 API 对象中的 IP 地址和 CIDR 值进行更严格的校验",
        "check_hint": "排查可检查 API 对象中的 IP/CIDR 字段是否符合新校验",
        "mechanism": "API 对象中的 IP 地址和 CIDR 字段原校验较宽松，部分非标准格式可被接受。该特性实施更严格的 IP/CIDR 校验，不符合 RFC 标准的值将被拒绝",
    },
    "StructuredAuthenticationConfigurationJWKSMetrics": {
        "cn_desc": "查看 apiserver 暴露的 JWKS 相关 metrics",
        "check_hint": "监控 JWT 签名密钥集的获取状态和密钥数量变化",
        "mechanism": "结构化认证配置使用外部 JWT 签名器时，apiserver 需要定期获取 JWKS（JSON Web Key Set）以验证 token。该特性暴露 JWKS 获取状态和密钥数量的 metrics，帮助监控外部签名器的密钥发现和轮换行为",
    },
    "UnknownVersionInteroperabilityProxy": {
        "cn_desc": "在多版本 apiserver 共存场景下检查 apiserver 的 UnknownVersionInteroperabilityProxy 配置",
        "check_hint": "审计跨版本代理请求日志",
        "mechanism": "集群升级期间多个 apiserver 实例可能运行不同版本。客户端请求的资源版本在当前 apiserver 不支持时，该特性将请求代理到能服务该版本的 apiserver，避免升级过程中 API 不可用",
    },
    "WatchCacheInitializationPostStartHook": {
        "cn_desc": "观察 apiserver 启动时 post-start hook 执行日志",
        "check_hint": "确认 watch cache 初始化在存储就绪后完成，关注 readiness probe 就绪时序",
        "mechanism": "apiserver 的 watch cache 初始化可能耗时较长。该特性将 watch cache 初始化纳入 post-start hook，确保 apiserver 在 cache 完全就绪后才标记 ready 接受流量，避免数据不一致",
    },
}




GATE_NAME_CN_FALLBACK: dict[str, dict[str, str]] = {
    "AggregatedDiscoveryRemoveBetaType": {"cn_desc": "移除聚合发现的 Beta 类型", "check_hint": "排查可检查聚合发现 API 响应格式", "mechanism": "聚合发现 API 此前包含 Beta 类型的响应字段，该门控控制移除这些字段，已弃用"},
    "AllowOverwriteTerminationGracePeriodSeconds": {"cn_desc": "允许软驱逐时覆盖 Pod 终止优雅期限", "check_hint": "排查可检查 Pod 的 terminationGracePeriodSeconds 和驱逐配置", "mechanism": "软驱逐时 MaxPodGracePeriodSeconds 此前无法覆盖 Pod 的 terminationGracePeriodSeconds。该特性允许覆盖，已弃用"},
    "AllowParsingUserUIDFromCertAuth": {"cn_desc": "允许从证书认证中解析用户 UID", "check_hint": "排查可检查 apiserver 认证日志中的 UID 字段", "mechanism": "证书认证此前不解析用户 UID。该特性允许从客户端证书中解析 UID 并加入认证上下文"},
    "AnonymousAuthConfigurableEndpoints": {"cn_desc": "配置匿名认证允许访问的端点", "check_hint": "排查可检查 apiserver 的匿名认证端点配置", "mechanism": "匿名认证此前只能全局启用或禁用。该特性允许管理员配置允许匿名访问的端点列表（如 /healthz、/readyz）"},
    "AuthorizeNodeWithSelectors": {"cn_desc": "使节点授权器使用细粒度选择器授权", "check_hint": "排查可检查节点授权器的选择器配置和 RBAC 规则", "mechanism": "节点授权器此前不使用字段和标签选择器。该特性使节点授权器基于选择器做细粒度授权决策，需同时启用 AuthorizeWithSelectors"},
    "AuthorizeWithSelectors": {"cn_desc": "基于字段和标签选择器的细粒度授权", "check_hint": "排查可检查授权策略中的选择器条件和 RBAC 规则", "mechanism": "授权层此前不考虑请求中的字段和标签选择器。该特性使授权器能基于请求中的选择器做决策，支持最小权限规则"},
    "BtreeWatchCache": {"cn_desc": "使用 B 树数据结构的 watch 缓存", "check_hint": "排查可观察 apiserver watch 缓存内存和性能指标", "mechanism": "watch 缓存此前使用 map 数据结构。该特性引入 B 树存储，优化大规模集群的缓存内存使用"},
    "DRAAdminAccess": {"cn_desc": "允许在 ResourceClaim 中请求管理员访问权限", "check_hint": "排查可检查 ResourceClaim 中的 adminAccess 字段和命名空间标签", "mechanism": "DRA 此前不允许管理员访问已分配给其他 Pod 的设备。该特性允许在 ResourceClaim 中请求管理员访问，用于监控和诊断，仅限授权命名空间"},
    "DRAPrioritizedList": {"cn_desc": "允许在设备请求中声明带优先级的备选列表", "check_hint": "排查可检查 ResourceClaim 中的 firstAvailable 字段", "mechanism": "DRA 设备请求此前只能指定单一需求。该特性引入 firstAvailable 有序列表，允许调度器按优先级尝试满足备选设备方案"},
    "DRAResourceClaimDeviceStatus": {"cn_desc": "启用 ResourceClaim.status.devices 字段", "check_hint": "排查可检查 ResourceClaim 的 status.devices 字段", "mechanism": "ResourceClaim 此前不报告分配的设备状态。该特性新增 status.devices 字段，由 DRA 驱动填充设备状态信息"},
    "DRASchedulerFilterTimeout": {"cn_desc": "启用 DRA 调度器过滤超时机制", "check_hint": "排查可检查调度器 DRA 过滤超时配置和日志", "mechanism": "DRA 调度器过滤操作此前可能阻塞调度。该特性引入可配置的过滤超时（默认 10 秒），超时后跳过该节点"},
    "DeclarativeValidation": {"cn_desc": "启用声明式 API 验证", "check_hint": "排查可检查 apiserver 的声明式验证 metrics", "mechanism": "Kubernetes API 验证此前完全手写。该特性启用基于 CEL 的声明式验证，通过 IDL 标记注释自动生成验证代码"},
    "DetectCacheInconsistency": {"cn_desc": "检测 watch 缓存不一致", "check_hint": "排查可观察 apiserver 缓存一致性告警日志", "mechanism": "watch 缓存此前不检测不一致。该特性在检测到缓存与 etcd 状态不一致时记录告警，帮助发现缓存 bug"},
    "DisableAllocatorDualWrite": {"cn_desc": "禁用 Service IP 分配器双写", "check_hint": "排查可检查 ServiceCIDR 和 IPAddress 资源状态", "mechanism": "多 CIDR Service 分配器在迁移期间同时写入新旧存储。该特性禁用旧存储写入，完成迁移"},
    "DisableCPUQuotaWithExclusiveCPUs": {"cn_desc": "为独占 CPU 的容器禁用 CPU 配额", "check_hint": "排查可检查节点 CPU Manager 配置和容器 CPU 分配", "mechanism": "独占 CPU 容器此前仍受 CPU CFS 配额限制。该特性为独占 CPU 容器禁用配额，避免不必要的限制"},
    "DisableNodeKubeProxyVersion": {"cn_desc": "禁用节点 kubeProxyVersion 字段", "check_hint": "排查可检查 Node status 中的 kubeProxyVersion 字段", "mechanism": "Node.status.nodeInfo.kubeProxyVersion 此前由 kubelet 设置但值不准确。该门控控制禁用该字段，已弃用"},
    "DynamicResourceAllocation": {"cn_desc": "动态资源分配（DRA）核心功能", "check_hint": "排查可检查 ResourceClaim、ResourceSlice 和 DeviceClass 资源配置", "mechanism": "Kubernetes 此前缺少对 GPU、FPGA 等专用设备的灵活分配机制。DRA 引入 ResourceClaim 和结构化参数模型，允许调度器直接模拟设备分配"},
    "ExternalServiceAccountTokenSigner": {"cn_desc": "外部 ServiceAccount token 签名器", "check_hint": "排查可检查 apiserver 的外部 JWT 签名器配置", "mechanism": "ServiceAccount token 签名此前仅使用集群内置密钥。该特性引入 ExternalJWTSigner gRPC 服务，支持与外部 KMS 集成"},
    "GitRepoVolumeDriver": {"cn_desc": "gitRepo 卷驱动", "check_hint": "排查可检查 Pod spec 中的 gitRepo 卷配置", "mechanism": "gitRepo 卷类型存在安全风险，可被利用在节点上执行代码。该门控控制启用/禁用该驱动，已弃用"},
    "InPlacePodVerticalScaling": {"cn_desc": "原地 Pod 垂直扩缩容", "check_hint": "排查可检查 Pod 的 resources 字段和 .status.containerStatuses.resources", "mechanism": "Pod 资源此前不可变，调整需重建 Pod。该特性允许在不重启容器的前提下动态修改 CPU 和内存资源"},
    "JobManagedBy": {"cn_desc": "Job managed-by 外部控制器机制", "check_hint": "排查可检查 Job spec 的 managedBy 字段", "mechanism": "Job 控制器此前只能由内置控制器管理。该特性引入 managedBy 字段，允许外部控制器（如 Kueue）声明接管 Job 状态同步"},
    "KubeletFineGrainedAuthz": {"cn_desc": "kubelet HTTPS API 细粒度授权", "check_hint": "排查可检查 kubelet 的授权配置和 RBAC 规则", "mechanism": "访问 kubelet API 此前需要 nodes/proxy 宽泛权限。该特性提供更精确的最小权限访问控制，替代 nodes/proxy"},
    "KubeletPSI": {"cn_desc": "kubelet PSI（压力失速信息）指标", "check_hint": "排查可检查 kubelet 暴露的 PSI metrics", "mechanism": "Kubernetes 此前缺少细粒度资源争用视图。该特性在 cgroup v2 节点上报告 CPU、内存和 I/O 的压力指标"},
    "KubeletPodResourcesDynamicResources": {"cn_desc": "kubelet PodResources API 报告 DRA 资源", "check_hint": "排查可检查 PodResources API 响应中的 DRA 设备信息", "mechanism": "PodResources API 此前不报告 DRA 分配的设备。该特性扩展 PodResources API 以包含 DRA 资源信息"},
    "KubeletPodResourcesGet": {"cn_desc": "PodResources API 的 Get 方法", "check_hint": "排查可检查 PodResources API 的 Get 端点响应", "mechanism": "PodResources API 此前只有 List 方法。该特性新增 Get 方法，允许按 Pod 查询资源分配"},
    "KubeletPodResourcesListUseActivePods": {"cn_desc": "PodResources API 仅列出活跃 Pod", "check_hint": "排查可检查 PodResources API 返回的 Pod 列表", "mechanism": "PodResources API 此前返回所有 Pod 包括已终止的。该特性使其仅返回活跃 Pod，已弃用"},
    "KubeletRegistrationGetOnExistsOnly": {"cn_desc": "kubelet 注册时仅 Get 已存在资源", "check_hint": "排查可检查 kubelet 启动日志中的 API 注册行为", "mechanism": "kubelet 启动时此前对所有资源执行 List。该特性改为仅 Get 已存在的资源，减少启动时 API 负载，已弃用"},
    "KubeletServiceAccountTokenForCredentialProviders": {"cn_desc": "kubelet 凭证提供者使用 ServiceAccount token", "check_hint": "排查可检查 kubelet 凭证提供者配置和 imagePullSecrets", "mechanism": "kubelet 镜像拉取凭证此前依赖长期 Secret。该特性允许 kubelet 使用短期 SA token 认证镜像拉取，基于 Pod 身份而非节点凭证"},
    "ListFromCacheSnapshot": {"cn_desc": "从 watch 缓存快照服务 List 请求", "check_hint": "排查可检查 apiserver List 请求性能和缓存快照 metrics", "mechanism": "指定 resourceVersion 的 List 请求此前直接访问 etcd。该特性从 watch 缓存快照服务 List 请求，减少 etcd 负载"},
    "MatchLabelKeysInPodTopologySpreadSelectorMerge": {"cn_desc": "PodTopologySpread 合并 matchLabelKeys", "check_hint": "排查可检查 PodTopologySpread 配置中的 matchLabelKeys", "mechanism": "PodTopologySpread 此前不合并 matchLabelKeys。该特性改进滚动更新时的 Pod 分布计算"},
    "MultiCIDRServiceAllocator": {"cn_desc": "多 CIDR Service IP 分配器", "check_hint": "排查可检查 ServiceCIDR 和 IPAddress 资源", "mechanism": "集群此前只能配置一个 Service CIDR。该特性引入 ServiceCIDR 和 IPAddress API，允许动态增加 Service IP 地址池"},
    "OrderedNamespaceDeletion": {"cn_desc": "有序 Namespace 删除", "check_hint": "排查可检查 Namespace 删除过程中资源的删除顺序", "mechanism": "Namespace 删除此前半随机顺序可能导致安全间隙。该特性强制按逻辑和安全依赖顺序删除资源"},
    "PodLevelResources": {"cn_desc": "Pod 级别资源请求和限制", "check_hint": "排查可检查 Pod spec 中的 pod-level resources 配置", "mechanism": "资源请求和限制此前只能在容器级别设置。该特性允许在 Pod 级别设置资源预算，由所有容器共享"},
    "PodLifecycleSleepActionAllowZero": {"cn_desc": "PreStop 钩子 Sleep 动作允许零值", "check_hint": "排查可检查 Pod 的 preStop 钩子配置中的 sleep 值", "mechanism": "PreStop 钩子的 Sleep 动作此前不支持零秒。该特性允许零秒作为有效值，定义无操作钩子"},
    "PodObservedGenerationTracking": {"cn_desc": "Pod 的 generation 和 observedGeneration 跟踪", "check_hint": "排查可检查 Pod 的 metadata.generation 和 status.observedGeneration", "mechanism": "Pod API 此前缺少 generation 字段。该特性引入 generation 和 observedGeneration，使控制器可判断 spec 变更是否已处理"},
    "PreferSameTrafficDistribution": {"cn_desc": "偏好同节点流量分发的 Service 选项", "check_hint": "排查可检查 Service spec 的 trafficDistribution 字段", "mechanism": "Service 流量分发此前只有 PreferClose 选项。该特性引入 PreferSameNode 和 PreferSameZone 选项"},
    "PreventStaticPodAPIReferences": {"cn_desc": "防止静态 Pod 在 API 中创建引用", "check_hint": "排查可检查 apiserver 中静态 Pod 的镜像 Pod 状态", "mechanism": "静态 Pod 此前会在 API Server 中创建引用。该特性防止创建这些引用"},
    "ProbeHostPodSecurityStandards": {"cn_desc": "Pod 安全标准禁止远程探测", "check_hint": "排查可检查 Pod 的探针配置中的 host 字段", "mechanism": "Restricted Pod 安全标准此前不禁止远程探测。该特性要求 Pod 不设置探针的 host 字段才满足 Restricted 标准"},
    "ProcMountType": {"cn_desc": "Pod 的 ProcMount 类型选项", "check_hint": "排查可检查 Pod securityContext 中的 procMount 字段", "mechanism": "Pod 的 /proc 挂载行为此前固定。该特性允许在 securityContext 中自定义 /proc 挂载行为"},
    "RecoverVolumeExpansionFailure": {"cn_desc": "卷扩容失败恢复", "check_hint": "排查可检查 PVC 的 status 和扩容状态", "mechanism": "卷扩容失败后此前无法回退。该特性允许取消不支持的扩容并重试更小值"},
    "RelaxedDNSSearchValidation": {"cn_desc": "放宽 DNS 搜索路径校验", "check_hint": "排查可检查 Pod dnsConfig 的 searches 字段", "mechanism": "Pod DNS 搜索路径此前严格验证。该特性放宽校验，支持复杂网络环境的 DNS 配置"},
    "RelaxedEnvironmentVariableValidation": {"cn_desc": "放宽环境变量名称校验", "check_hint": "排查可检查 Pod spec 中的环境变量名称", "mechanism": "环境变量名称此前受严格限制。该特性放宽校验，允许冒号等特殊字符（如 .NET Core 框架）"},
    "RemoteRequestHeaderUID": {"cn_desc": "远程请求头中的 UID", "check_hint": "排查可检查 apiserver 的请求头配置", "mechanism": "API Server 此前不从请求头解析 UID。该特性从远程请求头中解析 UID 并加入认证上下文"},
    "SELinuxChangePolicy": {"cn_desc": "SELinux 卷标签变更策略", "check_hint": "排查可检查 Pod securityContext 中的 seLinuxChangePolicy 字段", "mechanism": "SELinux 卷标签此前使用递归重新标记。该特性允许选择 mount-based 或 recursive 策略"},
    "SchedulerAsyncAPICalls": {"cn_desc": "调度器异步 API 调用", "check_hint": "排查可检查调度器性能指标和异步 API 队列状态", "mechanism": "调度器在调度周期中执行阻塞 API 调用。该特性引入异步 API 处理，通过优先队列和请求去重减少调度延迟"},
    "SchedulerAsyncPreemption": {"cn_desc": "调度器异步抢占", "check_hint": "排查可观察调度器抢占行为和吞吐指标", "mechanism": "抢占操作（如删除 Pod 的 API 调用）此前同步执行。该特性将抢占操作异步并行处理，提高调度吞吐量"},
    "SchedulerPopFromBackoffQ": {"cn_desc": "activeQ 为空时从 backoffQ 弹出 Pod", "check_hint": "排查可观察调度器队列状态和调度延迟", "mechanism": "调度器在 activeQ 为空时此前会闲置。该特性从 backoffQ 弹出不因错误退避的 Pod，提高调度效率"},
    "SchedulerQueueingHints": {"cn_desc": "调度器 QueueingHint 回调", "check_hint": "排查可检查调度器各插件的 QueueingHint 配置", "mechanism": "调度器此前使用固定退避策略重新排队。该特性允许每个调度插件注册回调判断集群事件是否可能使被拒绝 Pod 可调度"},
    "SeparateCacheWatchRPC": {"cn_desc": "分离缓存 Watch RPC", "check_hint": "排查可观察 apiserver watch 和 cache RPC 性能", "mechanism": "watch 和 cache 此前共享 RPC。该特性分离两者，已弃用"},
    "ServiceAccountNodeAudienceRestriction": {"cn_desc": "ServiceAccount 节点受众限制", "check_hint": "排查可检查 ServiceAccount token 的 audience 配置", "mechanism": "ServiceAccount token 此前不限制节点受众。该特性限制 token 仅在指定节点使用"},
    "SizeBasedListCostEstimate": {"cn_desc": "基于大小的 List 成本估算", "check_hint": "排查可检查调度器中 List 操作的成本估算", "mechanism": "调度器此前不估算 List 操作成本。该特性基于返回大小估算成本，优化调度决策"},
    "StreamingCollectionEncodingToJSON": {"cn_desc": "流式集合 JSON 编码", "check_hint": "排查可检查 apiserver List 请求的响应格式", "mechanism": "List 请求此前将整个集合序列化到内存。该特性引入 JSON 流式编码，减少内存峰值"},
    "StreamingCollectionEncodingToProtobuf": {"cn_desc": "流式集合 Protobuf 编码", "check_hint": "排查可检查 apiserver List 请求的 Protobuf 响应", "mechanism": "List 请求此前将整个集合序列化到内存。该特性引入 Protobuf 流式编码，减少内存峰值"},
    "StrictCostEnforcementForVAP": {"cn_desc": "ValidatingAdmissionPolicy 严格成本执行", "check_hint": "排查可检查 VAP 的成本限制配置", "mechanism": "VAP 此前不严格执行成本限制。该特性启用严格成本执行，防止 CEL 表达式消耗过多资源"},
    "StrictCostEnforcementForWebhooks": {"cn_desc": "Webhook 严格成本执行", "check_hint": "排查可检查 webhook 的超时和成本配置", "mechanism": "Webhook 此前不严格执行成本限制。该特性启用严格成本执行"},
    "StructuredAuthenticationConfigurationEgressSelector": {"cn_desc": "结构化认证配置 Egress Selector", "check_hint": "排查可检查 apiserver 认证配置中的 egress selector", "mechanism": "结构化认证配置此前不支持 egress selector。该特性支持通过 egress selector 连接外部认证服务"},
    "SupplementalGroupsPolicy": {"cn_desc": "Pod 补充组策略", "check_hint": "排查可检查 Pod securityContext 中的 supplementalGroupsPolicy", "mechanism": "容器此前隐式继承镜像的补充组。该特性引入 Merge 和 Strict 策略，控制补充组来源"},
    "SystemdWatchdog": {"cn_desc": "systemd watchdog 监控 kubelet", "check_hint": "排查可检查 systemd 配置和 kubelet 健康检查日志", "mechanism": "kubelet 健康检查失败时此前不自动重启。该特性使用 systemd watchdog 在 kubelet 不健康时自动重启"},
    "TokenRequestServiceAccountUIDValidation": {"cn_desc": "Token 请求 ServiceAccount UID 校验", "check_hint": "排查可检查 TokenRequest API 中的 UID 字段", "mechanism": "Token 请求此前不校验 ServiceAccount UID。该特性添加 UID 校验提高安全性"},
    "UserNamespacesSupport": {"cn_desc": "Pod 用户命名空间支持", "check_hint": "排查可检查 Pod spec 中的 hostUsers 字段", "mechanism": "Pod 此前与宿主机共享用户 ID。该特性允许 Pod 使用隔离的用户命名空间，将容器 root 映射为宿主机非特权用户"},
    "VolumeAttributesClass": {"cn_desc": "卷属性类（VolumeAttributesClass）", "check_hint": "排查可检查 VolumeAttributesClass 资源和 PVC 引用", "mechanism": "卷参数（如 IO）修改此前缺少通用 API。该特性引入 VolumeAttributesClass API，通过 CSI 修改卷属性"},
    "WatchList": {"cn_desc": "WatchList 机制", "check_hint": "排查可检查 apiserver 的 List/Watch 请求行为", "mechanism": "客户端此前先 List 再 Watch。该特性允许客户端通过单个 WatchList 请求获取初始状态和后续变更"},
    "WinDSR": {"cn_desc": "Windows kube-proxy DSR（直接服务器返回）", "check_hint": "排查可检查 Windows kube-proxy 的 DSR 配置", "mechanism": "Windows kube-proxy 返回流量此前通过负载均衡器。该特性允许返回流量直接响应客户端"},
    "WindowsGracefulNodeShutdown": {"cn_desc": "Windows 节点优雅关闭", "check_hint": "排查可检查 Windows 节点的关闭事件日志和 Pod 终止行为", "mechanism": "Windows 节点此前不检测系统关闭事件。该特性使 kubelet 检测关闭事件并优雅终止 Pod"},
}


# ===== Verification target mapping =====

VERIFY_MAP: list[tuple[list[str], str]] = [
    (["csi", "volume", "image", "snapshot"], "排查可检查 CSI 驱动配置或 Pod 卷挂载行为"),
    (["kubelet", "node", "pleg", "crash"], "排查可检查 kubelet 配置和节点行为"),
    (["schedul", "dra", "resource", "device", "gang", "workload"], "排查可检查调度器配置和 ResourceClaim 行为"),
    (["admission", "auth", "impersonat", "certificate", "token"], "排查可检查准入控制器配置和 RBAC 规则"),
    (["hpa", "autoscal"], "排查可检查 HPA 配置和自动伸缩行为"),
    (["job", "deployment", "statefulset", "replicaset", "controller", "stale"], "排查可检查控制器调和行为和相关资源状态"),
    (["flagz", "statusz"], "排查可访问各组件的 /flagz 或 /statusz 端点"),
    (["validation", "cidr", "ip", "service"], "排查可检查 API 对象中的相关字段验证行为"),
    (["websocket", "proxy", "watch", "cache"], "排查可检查 API Server 代理和连接行为"),
]


def get_verify_hint(gate_name: str) -> str:
    nl = gate_name.lower()
    for keywords, hint in VERIFY_MAP:
        if any(k in nl for k in keywords):
            return hint
    return "排查可检查相关组件配置和 API 行为"


# ===== Old/new behavior description =====

STAGE_LABELS = {"Alpha": "Alpha", "Beta": "Beta", "GA": "GA", "Deprecated": "Deprecated"}


def describe_old(fact: dict) -> str:
    before = fact.get("before")
    if before is None:
        return "该 FeatureGate 此前不存在"
    b_stage = before.get("stage", "")
    b_default = before.get("default", False)
    if b_stage == "Deprecated":
        return f"该特性此前已处于 Deprecated 状态，默认{'启用' if b_default else '关闭'}"
    return f"该特性此前处于 {STAGE_LABELS.get(b_stage, b_stage)}，默认{'启用' if b_default else '关闭'}"


def describe_new(fact: dict) -> str:
    after = fact.get("after")
    if after is None:
        return "已被移除"
    a_stage = after.get("stage", "")
    a_default = after.get("default", False)
    a_locked = after.get("locked", False)
    locked_text = "且已锁定" if a_locked else ""
    return f"提升为 {STAGE_LABELS.get(a_stage, a_stage)}，默认{'启用' if a_default else '关闭'}{locked_text}"


# ===== Check method and details generation =====

def gen_check_method(fact: dict) -> str:
    gate_name = fact["feature_name"]
    after = fact.get("after")
    before = fact.get("before")
    change_type = fact.get("change_type", "")

    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    cn_desc = gate_data.get("cn_desc", gate_name)
    check_hint = gate_data.get("check_hint", get_verify_hint(gate_name))

    a_stage = after.get("stage", "") if after else ""
    a_default = after.get("default", False) if after else False
    b_stage = before.get("stage", "") if before else None
    b_default = before.get("default", False) if before else None
    to_ver = fact.get("to_version", "")

    if change_type == "Deprecated":
        behavior = f"该门控已弃用，默认{'关闭' if not a_default else '启用'}"
    elif change_type == "Added":
        if a_default:
            behavior = f"v{to_ver} 新增并默认启用，升级后自动激活"
        else:
            behavior = f"v{to_ver} 新增，默认关闭，需手动启用"
    elif a_default and b_default is False:
        if a_stage == "GA":
            behavior = f"从 {b_stage} 提升为 GA 并默认启用，已锁定不可回退"
        else:
            behavior = f"从 {b_stage}（默认关闭）提升为 {a_stage} 并默认启用，升级后自动激活"
    elif a_default and b_default is True:
        behavior = f"保持默认启用，阶段从 {b_stage} 变更为 {a_stage}"
    elif a_stage == "GA" and b_stage != "GA":
        behavior = f"从 {b_stage} 提升为 GA，已锁定不可回退"
    else:
        behavior = f"阶段从 {b_stage} 变更为 {a_stage}，默认{'启用' if a_default else '关闭'}"

    return f"{cn_desc}。{behavior}，{check_hint}。"


def gen_details(fact: dict) -> str:
    gate_name = fact["feature_name"]
    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    mechanism = gate_data.get("mechanism", "")
    cn_desc = gate_data.get("cn_desc", gate_name)
    old = describe_old(fact)
    new = describe_new(fact)
    change_type = fact.get("change_type", "")
    to_ver = fact.get("to_version", "")
    after = fact.get("after", {})
    before = fact.get("before", {})
    a_default = after.get("default", False) if after else False
    b_default = before.get("default", False) if before else None

    body = mechanism if mechanism else cn_desc

    if change_type == "Added":
        transition = "v{0} 新增该特性（{1}）。".format(
            to_ver, "默认启用" if a_default else "默认关闭"
        )
    elif change_type == "Deprecated":
        transition = "v{0} 将该特性标记为弃用。".format(to_ver)
    else:
        transition = "{0}，{1}。".format(old, new)

    return f"{body}。{transition}"


def gen_conclusion(fact: dict) -> str:
    gate_name = fact["feature_name"]
    after = fact.get("after")
    before = fact.get("before")
    stage = after.get("stage", "") if after else ""
    default = after.get("default", False) if after else False
    to_ver = fact.get("to_version", "")
    change_type = fact.get("change_type", "")
    b_default = before.get("default", False) if before else None

    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    cn_desc = gate_data.get("cn_desc", gate_name)

    if stage == "Deprecated":
        return f"该门控已弃用（v{to_ver}），建议关闭并清理相关配置，避免升级后出现兼容性问题。"
    elif change_type == "Added" and default:
        return f"v{to_ver} 新增并默认启用{cn_desc}，升级后自动生效，无需额外操作。"
    elif change_type == "Added":
        return f"v{to_ver} 新增{cn_desc}但默认关闭，升级后无影响，按需启用。"
    elif default and stage == "GA":
        return f"v{to_ver} 将{cn_desc}提升为 GA 并锁定默认值，升级后自动生效，该特性不可回退。"
    elif default and b_default is False:
        return f"v{to_ver} 默认启用{cn_desc}，升级后自动生效，确认相关组件兼容性后直接升级。"
    elif default:
        return f"v{to_ver} 保持{cn_desc}默认启用，阶段变更为 {stage}，确认兼容性后直接升级。"
    else:
        return f"v{to_ver} 中{cn_desc}默认关闭，升级后无影响，按需启用。"


def gen_recommendation(fact: dict) -> str:
    after = fact.get("after")
    stage = after.get("stage", "") if after else ""
    default = after.get("default", False) if after else False
    if stage == "Deprecated":
        return "关闭"
    elif default:
        return "开启"
    return ""


def gen_notes(fact: dict) -> str:
    gate_name = fact["feature_name"]
    after = fact.get("after")
    before = fact.get("before")
    stage = after.get("stage", "") if after else ""
    default = after.get("default", False) if after else False
    to_ver = fact.get("to_version", "")
    change_type = fact.get("change_type", "")
    b_default = before.get("default", False) if before else None

    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    cn_desc = gate_data.get("cn_desc", gate_name)

    if stage == "Deprecated":
        return f"v{to_ver} 已弃用，建议关闭"
    elif fact.get("lock_change"):
        return f"v{to_ver} 已锁定默认值，不可回退"
    elif change_type == "Added" and default:
        return f"v{to_ver} 新增默认启用"
    elif default and stage == "GA":
        return f"v{to_ver} GA 锁定"
    elif default and b_default is False:
        return f"v{to_ver} 默认值变更为启用"
    elif default:
        return f"v{to_ver} 默认启用"
    elif change_type == "Added":
        return f"v{to_ver} 新增，默认关闭"
    else:
        return f"v{to_ver} 默认关闭，按需启用"


def gen_sources(fact: dict, fg_doc: str) -> list[str]:
    kep_url = fact.get("kep_url", "")
    sources = []
    if kep_url:
        sources.append(kep_url)
    sources.append(fg_doc)
    return sources


# ===== Multi-feature sub-feature handling =====

KEP_SUB_CN: dict[str, str] = {
    "5018": "为集群管理员提供永久、安全的框架以全局访问与管理硬件资源，支持管理员覆盖与 ResourceClaimTemplate 的集中治理",
    "4816": "允许在设备请求中声明带优先级的备选列表，确保资源选择逻辑在所有集群环境中一致、可预测",
    "5004": "将 DRA 与扩展资源集成，兼容传统设备插件使用方式，支持渐进式迁移",
    "4817": "在 ResourceClaim 状态中报告设备健康与分配状态，提供设备生命周期的可观测性，支持细粒度授权检查",
    "5055": "为设备引入污点与容忍机制，确保专用资源仅被合适工作负载使用，故障设备可自动驱逐",
    "5075": "允许设备以可消耗容量方式分配，使多个 Pod 共享同一设备的部分容量",
    "4815": "支持将物理硬件（如 GPU）动态分区为多个可独立分配的逻辑实例，提高硬件资源利用率",
    "5007": "在 Pod 调度前确保设备已附着，避免调度后因设备不可用导致 Pod 卡死",
    "5729": "为高层控制器提供原生 ResourceClaim 工作负载支持，实现 DRA 与 Job 等控制器的无缝集成",
    "5304": "通过 Downward API 向容器暴露复杂资源属性，使应用可直接感知已分配设备的元数据",
    "5517": "将 DRA 的灵活性引入 CPU 管理，使 CPU 资源也可通过 DRA 框架进行精细化分配",
    "5677": "改进资源可用性可见性，使调度更可预测",
    "5491": "设备属性支持列表类型，丰富设备元数据表达能力和调度匹配精度",
    "4671": "实现 all-or-nothing 编组调度策略，确保整个 Pod 组同时调度或都不调度",
    "5547": "引入解耦的 PodGroup API，将相关 Pod 作为单一逻辑实体管理",
    "5832": "将 Job 控制器与修订版 Workload API 原生集成",
    "5732": "新增 PodGroup 调度周期，对整组 Pod 原子化评估（全绑或全不绑）",
    "5710": "将 Job 控制器与 Workload API 集成，实现工作负载感知调度",
}

KEP_SUB_NAMES: dict[str, str] = {
    "5018": "AdminAccess for ResourceClaims and ResourceClaimTemplates",
    "4816": "Prioritized Alternatives in Device Requests",
    "5004": "Extended Resource Requests via DRA",
    "4817": "ResourceClaim Granular Status Authorization",
    "5055": "Device Taints and Tolerations",
    "5075": "Consumable Capacity",
    "4815": "Partitionable Devices",
    "5007": "Device Binding Conditions",
    "5729": "ResourceClaim Support for Workloads",
    "5304": "Device Attributes in Downward API",
    "5517": "Node Allocatable Resource Requests",
    "5677": "Resource Availability Visibility",
    "5491": "List Types for Attributes",
    "4671": "Gang Scheduling",
    "5547": "PodGroup API",
    "5832": "Workload API Integration",
    "5732": "PodGroup Scheduling Cycle",
    "5710": "Job Controller Integration",
}


def gen_multi_feature_enhancement(subs: list[dict], kep_to_fact: dict) -> str:
    lines = []
    for s in subs:
        kid = s["kep_id"]
        sig = s.get("sig", "")
        kname = KEP_SUB_NAMES.get(kid, f"KEP #{kid}")
        cn_desc = KEP_SUB_CN.get(kid, s.get("description", f"提供 {kname} 相关能力"))

        fact = kep_to_fact.get(kid)
        if fact:
            after = fact.get("after")
            if after:
                stage = after.get("stage", "")
                default = after.get("default", False)
                stage_label = STAGE_LABELS.get(stage, stage)
                default_label = "启用" if default else "关闭"
                lines.append(
                    f"{kname}（KEP #{kid}，{sig}）{cn_desc}，"
                    f"升级为 {stage_label} 并默认{default_label}。"
                )
            else:
                lines.append(f"{kname}（KEP #{kid}，{sig}）{cn_desc}。")
        else:
            lines.append(f"{kname}（KEP #{kid}，{sig}）{cn_desc}。")
    return "\n".join(lines)


STAGE_LABELS = {"Alpha": "Alpha", "Beta": "Beta", "GA": "GA", "Deprecated": "Deprecated"}


def describe_old(fact: dict) -> str:
    before = fact.get("before")
    if before is None:
        return "该 FeatureGate 此前不存在"
    b_stage = before.get("stage", "")
    b_default = before.get("default", False)
    if b_stage == "Deprecated":
        return f"该特性此前已处于 Deprecated 状态，默认{'启用' if b_default else '关闭'}"
    return f"该特性此前处于 {STAGE_LABELS.get(b_stage, b_stage)}，默认{'启用' if b_default else '关闭'}"


def describe_new(fact: dict) -> str:
    after = fact.get("after")
    if after is None:
        return "已被移除"
    a_stage = after.get("stage", "")
    a_default = after.get("default", False)
    a_locked = after.get("locked", False)
    locked_text = "且已锁定" if a_locked else ""
    return f"提升为 {STAGE_LABELS.get(a_stage, a_stage)}，默认{'启用' if a_default else '关闭'}{locked_text}"


def gen_check_method(fact: dict) -> str:
    gate_name = fact["feature_name"]
    after = fact.get("after") or {}
    before = fact.get("before")
    change_type = fact.get("change_type", "")

    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    cn_desc = gate_data.get("cn_desc", gate_name)
    check_hint = gate_data.get("check_hint", get_verify_hint(gate_name))

    a_stage = after.get("stage", "")
    a_default = after.get("default", False)
    b_stage = before.get("stage", "") if before else None
    b_default = before.get("default", False) if before else None
    to_ver = fact.get("to_version", "")

    if change_type == "Deprecated":
        behavior = f"该门控已弃用，默认{'关闭' if not a_default else '启用'}"
    elif change_type == "Added":
        behavior = f"v{to_ver} 新增并默认{'启用，升级后自动激活' if a_default else '关闭，需手动启用'}"
    elif a_default and b_default is False:
        behavior = f"从 {b_stage}（默认关闭）提升为 {a_stage} 并默认{'启用，已锁定不可回退' if after.get('locked') else '启用，升级后自动激活'}"
    elif a_default and b_default is True:
        behavior = f"保持默认启用，阶段从 {b_stage} 变更为 {a_stage}"
    elif a_stage == "GA" and b_stage and b_stage != "GA":
        behavior = f"从 {b_stage} 提升为 GA，已锁定不可回退"
    else:
        behavior = f"阶段从 {b_stage} 变更为 {a_stage}，默认{'启用' if a_default else '关闭'}"

    return f"{cn_desc}。{behavior}，{check_hint}。"


def gen_details(fact: dict) -> str:
    gate_name = fact["feature_name"]
    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    mechanism = gate_data.get("mechanism", "")
    cn_desc = gate_data.get("cn_desc", gate_name)
    old = describe_old(fact)
    new = describe_new(fact)
    change_type = fact.get("change_type", "")
    to_ver = fact.get("to_version", "")
    after = fact.get("after") or {}
    before = fact.get("before") or {}
    a_default = after.get("default", False)
    b_default = before.get("default", False) if before else None

    body = mechanism if mechanism else cn_desc

    if change_type == "Added":
        transition = "v{} 新增该特性（{}）。".format(to_ver, "默认启用" if a_default else "默认关闭")
    elif change_type == "Deprecated":
        transition = "v{} 将该特性标记为弃用。".format(to_ver)
    else:
        transition = "{},{}。".format(old, new)

    return f"{body}。{transition}"


def gen_conclusion(fact: dict) -> str:
    gate_name = fact["feature_name"]
    after = fact.get("after") or {}
    before = fact.get("before") or {}
    stage = after.get("stage", "")
    default = after.get("default", False)
    to_ver = fact.get("to_version", "")
    change_type = fact.get("change_type", "")
    b_default = before.get("default", False) if before else None

    gate_data = GATE_CN.get(gate_name) or GATE_NAME_CN_FALLBACK.get(gate_name, {})
    cn_desc = gate_data.get("cn_desc", gate_name)

    if stage == "Deprecated":
        return f"该门控已弃用（v{to_ver}），建议关闭并清理相关配置，避免升级后出现兼容性问题。"
    elif change_type == "Added" and default:
        return f"v{to_ver} 新增并默认启用{cn_desc}，升级后自动生效，无需额外操作。"
    elif change_type == "Added":
        return f"v{to_ver} 新增{cn_desc}但默认关闭，升级后无影响，按需启用。"
    elif default and stage == "GA":
        return f"v{to_ver} 将{cn_desc}提升为 GA 并锁定默认值，升级后自动生效，该特性不可回退。"
    elif default and b_default is False:
        return f"v{to_ver} 默认启用{cn_desc}，升级后自动生效，确认相关组件兼容性后直接升级。"
    elif default:
        return f"v{to_ver} 保持{cn_desc}默认启用，阶段变更为 {stage}，确认兼容性后直接升级。"
    else:
        return f"v{to_ver} 中{cn_desc}默认关闭，升级后无影响，按需启用。"


def gen_recommendation(fact: dict) -> str:
    after = fact.get("after") or {}
    stage = after.get("stage", "")
    default = after.get("default", False)
    if stage == "Deprecated":
        return "关闭"
    elif default:
        return "开启"
    return ""


def gen_notes(fact: dict) -> str:
    after = fact.get("after") or {}
    before = fact.get("before") or {}
    stage = after.get("stage", "")
    default = after.get("default", False)
    to_ver = fact.get("to_version", "")
    change_type = fact.get("change_type", "")
    b_default = before.get("default", False) if before else None

    gate_data = GATE_CN.get(fact["feature_name"]) or GATE_NAME_CN_FALLBACK.get(fact["feature_name"], {})
    cn_desc = gate_data.get("cn_desc", fact["feature_name"])

    if stage == "Deprecated":
        return f"v{to_ver} 已弃用，建议关闭"
    elif fact.get("lock_change"):
        return f"v{to_ver} 已锁定默认值，不可回退"
    elif change_type == "Added" and default:
        return f"v{to_ver} 新增默认启用"
    elif default and stage == "GA":
        return f"v{to_ver} GA 锁定"
    elif default and b_default is False:
        return f"v{to_ver} 默认值变更为启用"
    elif default:
        return f"v{to_ver} 默认启用"
    elif change_type == "Added":
        return f"v{to_ver} 新增，默认关闭"
    else:
        return f"v{to_ver} 默认关闭，按需启用"


def gen_sources(fact: dict, fg_doc: str) -> list[str]:
    kep_url = fact.get("kep_url", "")
    sources = []
    if kep_url:
        sources.append(kep_url)
    sources.append(fg_doc)
    return sources


KEP_SUB_CN: dict[str, str] = {
    "5018": "为集群管理员提供永久、安全的框架以全局访问与管理硬件资源，支持管理员覆盖与 ResourceClaimTemplate 的集中治理",
    "4816": "允许在设备请求中声明带优先级的备选列表，确保资源选择逻辑在所有集群环境中一致、可预测",
    "5004": "将 DRA 与扩展资源集成，兼容传统设备插件使用方式，支持渐进式迁移",
    "4817": "在 ResourceClaim 状态中报告设备健康与分配状态，提供设备生命周期的可观测性，支持细粒度授权检查",
    "5055": "为设备引入污点与容忍机制，确保专用资源仅被合适工作负载使用，故障设备可自动驱逐",
    "5075": "允许设备以可消耗容量方式分配，使多个 Pod 共享同一设备的部分容量",
    "4815": "支持将物理硬件（如 GPU）动态分区为多个可独立分配的逻辑实例，提高硬件资源利用率",
    "5007": "在 Pod 调度前确保设备已附着，避免调度后因设备不可用导致 Pod 卡死",
    "5729": "为高层控制器提供原生 ResourceClaim 工作负载支持，实现 DRA 与 Job 等控制器的无缝集成",
    "5304": "通过 Downward API 向容器暴露复杂资源属性，使应用可直接感知已分配设备的元数据",
    "5517": "将 DRA 的灵活性引入 CPU 管理，使 CPU 资源也可通过 DRA 框架进行精细化分配",
    "5677": "改进资源可用性可见性，使调度更可预测",
    "5491": "设备属性支持列表类型，丰富设备元数据表达能力和调度匹配精度",
    "4671": "实现 all-or-nothing 编组调度策略，确保整个 Pod 组同时调度或都不调度",
    "5547": "引入解耦的 PodGroup API，将相关 Pod 作为单一逻辑实体管理",
    "5832": "将 Job 控制器与修订版 Workload API 原生集成",
    "5732": "新增 PodGroup 调度周期，对整组 Pod 原子化评估（全绑或全不绑）",
    "5710": "将 Job 控制器与 Workload API 集成，实现工作负载感知调度",
}

KEP_SUB_NAMES: dict[str, str] = {
    "5018": "AdminAccess for ResourceClaims and ResourceClaimTemplates",
    "4816": "Prioritized Alternatives in Device Requests",
    "5004": "Extended Resource Requests via DRA",
    "4817": "ResourceClaim Granular Status Authorization",
    "5055": "Device Taints and Tolerations",
    "5075": "Consumable Capacity",
    "4815": "Partitionable Devices",
    "5007": "Device Binding Conditions",
    "5729": "ResourceClaim Support for Workloads",
    "5304": "Device Attributes in Downward API",
    "5517": "Node Allocatable Resource Requests",
    "5677": "Resource Availability Visibility",
    "5491": "List Types for Attributes",
    "4671": "Gang Scheduling",
    "5547": "PodGroup API",
    "5832": "Workload API Integration",
    "5732": "PodGroup Scheduling Cycle",
    "5710": "Job Controller Integration",
}


def gen_multi_feature_enhancement(subs: list[dict], kep_to_fact: dict) -> str:
    lines = []
    for s in subs:
        kid = s["kep_id"]
        sig = s.get("sig", "")
        kname = KEP_SUB_NAMES.get(kid, f"KEP #{kid}")
        cn_desc = KEP_SUB_CN.get(kid, s.get("description", f"提供 {kname} 相关能力"))
        fact = kep_to_fact.get(kid)
        if fact:
            after = fact.get("after")
            if after:
                stage = after.get("stage", "")
                default = after.get("default", False)
                stage_label = STAGE_LABELS.get(stage, stage)
                default_label = "启用" if default else "关闭"
                lines.append(f"{kname}（KEP #{kid}，{sig}）{cn_desc}，升级为 {stage_label} 并默认{default_label}。")
            else:
                lines.append(f"{kname}（KEP #{kid}，{sig}）{cn_desc}。")
        else:
            lines.append(f"{kname}（KEP #{kid}，{sig}）{cn_desc}。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate feature_changes and multi-feature VA text.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()

    analysis = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8-sig"))
    facts = json.loads((run_dir / "machine-facts.json").read_text(encoding="utf-8-sig"))
    catalog = json.loads((run_dir / "release-catalog.json").read_text(encoding="utf-8-sig"))

    FG_DOC = "https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/"

    cat_idx: dict[str, dict] = {}
    for v in catalog["versions"]:
        for item in v["features"] + v["risks"]:
            cat_idx[item["catalog_id"]] = item

    fact_by_id = {f["id"]: f for f in facts["feature_changes"]}
    kep_to_fact: dict[str, dict] = {}
    for f in facts["feature_changes"]:
        kep_url = f.get("kep_url", "")
        if kep_url:
            kep_id = kep_url.rstrip("/").rsplit("/", 1)[-1]
            kep_to_fact[kep_id] = f

    for row in analysis["feature_changes"]:
        fid = row["id"]
        fact = fact_by_id.get(fid, {})
        compat = fact.get("compatible", False)
        after = fact.get("after")
        sources = gen_sources(fact, FG_DOC)

        if compat:
            default_off = after is not None and not after.get("default", False)
            row["compatibility_analysis"] = "特性默认关闭，无影响" if default_off else "开关状态不变，无影响"
            row["conclusion"] = ""
            row["check_method"] = ""
            row["sources"] = sources
            row["details"] = ""
            row["notes"] = ""
            row["recommendation"] = ""
            row["status"] = "ready"
        else:
            row["compatibility_analysis"] = ""
            row["check_method"] = gen_check_method(fact)
            row["sources"] = sources
            row["details"] = gen_details(fact)
            row["conclusion"] = gen_conclusion(fact)
            row["recommendation"] = gen_recommendation(fact)
            row["notes"] = gen_notes(fact)
            row["status"] = "ready"

    for row in analysis["version_analysis"]:
        cat_id = row.get("catalog_id", "")
        cat_item = cat_idx.get(cat_id, {})
        subs = cat_item.get("sub_features", [])
        is_risk = row.get("category") in ("弃用与移除", "关键变更风险")

        if not is_risk and len(subs) > 1:
            row["enhancement"] = gen_multi_feature_enhancement(subs, kep_to_fact)
            row["feature_summary"] = row["enhancement"]
            row["status"] = "ready"

    (run_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    fc_total = len(analysis["feature_changes"])
    fc_ready = sum(1 for r in analysis["feature_changes"] if r.get("status") == "ready")
    va_total = len(analysis["version_analysis"])
    va_auto = sum(1 for r in analysis["version_analysis"] if r.get("status") == "ready")
    print(f"feature_changes: {fc_ready}/{fc_total} ready")
    print(f"version_analysis: {va_auto} auto-generated, {va_total} total ({va_total - va_auto} need LLM for Chinese text)")


if __name__ == "__main__":
    main()
