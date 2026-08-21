# 昇腾 NPU 架构 + vllm_ascend - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / vLLM 推理方向）
> 重要纠错：常见误解 `HCCL_TIMEOUT` 不存在，正确为 `HCCL_EXEC_TIMEOUT`；vLLM 没有 `--quantization deepseek_fp8` 方法
> 事实均附官方文档 / 源码链接；不能验证的标「未验证」

---

## 一、DaVinci 架构与 AICore

### Q1. DaVinci 架构核心理念？
- **三级计算单元**：1D Scalar + 2D Vector + 3D Matrix (Cube)，针对 DNN 算子（标量/向量/矩阵）的不同特性分别优化。
- 来源：HotChips 31 演讲 [DaVinci: A Scalable Architecture for Neural Network Computing](https://old.hotchips.org/hc31/HC31_1.11_Huawei.Davinci.HengLiao_v4.0.pdf)

### Q2. AICore 内部组成？
- 每个 AI Core = **Cube Unit（矩阵）+ Vector Unit（向量）+ Scalar Unit（标量）+ DMA/MTE 数据搬移单元**。
- Scalar 读指令序列并下发到其他单元的指令队列；Cube/Vector/DMA 异步并行执行。
- 来源：[CANN 9.0.X 同步控制介绍](https://www.hiascend.com/document/detail/en/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0179.html)

### Q3. Cube Unit 工作机制？
- 单条指令完成一次矩阵乘 `A(M×K) × B(K×N)`。
- 左矩阵 A 来自 **L0A Buffer**，右矩阵 B 来自 **L0B Buffer**，结果存 **L0C Buffer**。
- DaVinci Max：16³ = **4096 FP16 MACs/cycle**（+8192 INT8 MACs）。

### Q4. 存储层次（由近到远）？
- **L0A / L0B**（Cube 输入，512B 对齐）
- **L0C**（Cube 输出，64B 对齐）
- **L1 Buffer**（核内，32B 对齐；910A=256KB/core，910B=512KB/core，310P=128KB/core）
- **Unified Buffer (UB)**（Vector 用，32B 对齐）
- **L2 Cache**（片上共享，910B=192MB）
- **Global Memory (GM)** = HBM 或 DDR

### Q5. 矩阵乘数据流？
```
GM →(MTE2)→ L1 →(MTE1)→ L0A/L0B →(PIPE_M/Cube)→ L0C →(PIPE_V/VECIN)→ UB →(MTE3/VECOUT)→ GM
```

### Q6. 主要硬件流水线（PIPE）？
- `PIPE_S`(Scalar) / `PIPE_V`(Vector) / `PIPE_M`(Cube 矩阵)
- `PIPE_MTE1`(L1→L0A/L0B) / `PIPE_MTE2`(GM→L1/UB) / `PIPE_MTE3`(UB→GM) / `PIPE_FIX`(L0C→GM)

### Q7. Ascend 910（一代，2019）？
- TSMC 7nm；32 DaVinci Max AI Cores（4 cluster × 8）；1 Cube + 1 Vector/core
- FP16 = **256 TFLOPS**；INT8 = 512 TOPS；32GB HBM2 @ 1.228 TB/s；310W

### Q8. Ascend 910B（二代，2022）？
- SMIC 7nm N+2；20-25 AI Cores；**1 Cube + 2 Vector/core**（比 910A 多一个 Vector）
- 64GB HBM2e @ 1.6 TB/s；FP16 最高 400 TFLOPS；192MB L2；~400W
- 来源：[CSET 报告](https://cset.georgetown.edu/publication/pushing-the-limits-huawei-ai-chip-tests-u-s-export-controls/)

### Q9. 910B1/B2/B3/B4 细分？
- **B1**：~25/24 cores，64GB HBM2e，~400 TFLOPS（最高配）
- **B2**：64GB HBM2e，~376 TFLOPS
- **B3**：64GB HBM2e，~313 TFLOPS
- **B4**：**32GB HBM2e**（仅 2 stacks），~280 TFLOPS

### Q10. Ascend 910C（2024-2025）？
- **单封装 2 个 die**（每个 die 类似 910B），共 ~50 Vector Cores
- **128GB HBM3/HBM2e @ 3.2 TB/s**；FP16 ~800 TFLOPS；两 die 间通过 **SIO link** 互连
- Atlas 800I A3 服务器单卡 2 die、整机 16 devices

### Q11. Ascend 310（边缘）与 310P（推理增强）？
- **310**：12nm，2-8 DaVinci Mini AI Cores，FP16=8-16 TFLOPS，4GB LPDDR4X，<10W
- **310P**：8 AI Cores，24GB/48GB LPDDR4X @ 204.8 GB/s，FP16=70 TFLOPS，72W
- 310P 对 KV cache 有特殊 5D shape 对齐要求（head_size 对齐 16）

### Q12. HCCS（片间互联）？
- 华为专有，**P2P full-mesh 拓扑**（无 NVSwitch 类芯片）
- 910A 单 chip 3 个 HCCS port @ 30GB/s
- 910B 8 卡整机聚合 **392 GB/s**，但**单 pair 峰值仅 ~56 GB/s**
- 跨机用 2×100Gbps RoCEv2 RDMA

### Q13. 数据格式（Cube 友好）？
- 5D `NC1HWC0`（C0 = Cube Unit 大小）
- `FRACTAL_NZ`（列主序分形，Cube 输出）
- `FRACTAL_Z`（卷积权重）

---

## 二、CANN 软件栈

### Q14. CANN 是什么？
- **Compute Architecture for Neural Networks**，华为昇腾异构计算架构。
- 上接 MindSpore/PyTorch/TensorFlow，下接 AI 处理器。
- **当前版本：9.0.0**（社区版与商用版同步发布，新增 Ascend 950PR、FP8/MxFP8/MxFP4、CCU 通信加速、AscendC SIMD+SIMT 混合编程）。
- 来源：[CANN 9.0.0 版本说明](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/releasenote/release-notes.md)

### Q15. CANN 三个组合包？
- **Toolkit** + **ops（算子包）** + **NNAL（加速库，提供 `libatb.so`）**
- 9.0 起 ops 包下新增 `Ascend-cann-950-ops` 支持 Ascend 950PR

### Q16. ATC（Ascend Tensor Compiler）？
- 模型转换工具，把开源框架模型（Caffe=0/AIR=1/TF=3/ONNX=5）转成昇腾离线模型 `.om`。
- 流程：Parser → IR 图 → 图准备/分区/优化/build → .om
- 命令：`atc --model=resnet50.onnx --framework=5 --output=resnet50 --soc_version=<soc>`

### Q17. ACL / AscendCL？
- **Ascend Computing Language**：C/C++ + Python(pyACL) 双语言 API。
- 管理 Device/Stream/Event/Memory/Model。
- 调用流：`acl.init() → acl.rt.set_device(id) → acl.mdl.load_from_file → acl.mdl.execute → acl.finalize`

### Q18. AICPU 算子 vs AICore Kernel？
- **AICPU 算子**：不适合 Cube/Vector 的算子（控制流、复杂逻辑）下发给 AI CPU（片上 Arm 核）；profile 中 `Task Type = AI CPU`
- **AICore Kernel**：通过 **BiSheng Compiler** 编译为 Cube/Vector 二进制；核心宏：`__DAV_CUBE__`/`__DAV_VEC__`

### Q19. GraphEngine / AclGraph？
- **GraphEngine (GE)**：图编译与执行引擎
- **AclGraph**：CANN 9.0 强化的预编译静态图能力，**等价于 CUDA Graph**
- stream 规格扩充至 64k，Event 规格仅受 Device 内存限制

### Q20. 算子调用链（vllm-ascend 视角）？
- `vllm-ascend → PTA(torch_npu) → CANN(ATB/aclnn)`
- PTA 未集成或 CANN 版本不够会阻塞；vllm-ascend RFC #4298 提出直接调 aclnn 双段接口绕过 PTA

---

## 三、执行模式：AclGraph vs Eager

### Q21. Eager 模式（默认）？
- PyTorch 逐算子执行，torch_npu 通过 dispatch key `PrivateUse1` 把 aten op 路由到 ACL/aclnn
- 异步 task queue（容量 4096）+ ACL worker thread 实现非阻塞下发

### Q22. AclGraph 模式？
- 等价 CUDA Graph，**预编译静态图**，减少 host launch 开销
- 捕获期录制 task handle/event/workspace；replay 前用 `update_graph_params()` 在 update stream 上刷新 attention 运行时元数据
- 目标：减少小/中 batch 的 host launch 开销

### Q23. AclGraph 两种子模式？
- **Piecewise（分段图）**：保守路径，对非 attention 段做图捕获，按模型深度产生多个子图
- **Full Graph（全图）**：性能优先，依赖 attention backend 提供 `update_graph_params()` 钩子

### Q24. AclGraph 约束？
- 拒绝 `ASCEND_LAUNCH_BLOCKING=1`；禁用 `use_inductor`
- Encoder-decoder 模型强制 PIECEWISE

### Q25. torch_npu 集成？
- `import torch_npu` 后 `torch.device("npu:0")` 可用
- NPUGraph API：`torch_npu.npu.NPUGraph()` + `with torch_npu.npu.graph(self.graph, stream=...)` 捕获；`replay()` 重放
- Dynamo backend `npu` 通过 `torchair` 或 fallback `_eager_npu_backend`

### Q26. custom_op_register（vllm-ascend 实践）？
- `direct_register_custom_op(op_name, op_func, fake_impl, mutates_args, dispatch_key="PrivateUse1")` 注册自定义算子
- 提供 `fake_impl`（meta 实现）供 torch.compile 跟踪
- 来源：[vllm-ascend register_custom_ops.py](https://github.com/vllm-project/vllm-ascend/blob/1eb0cc0e/vllm_ascend/ops/register_custom_ops.py)

---

## 四、HCCL（Huawei Collective Communication Library）

### Q27. HCCL 定位？
- 基于 Ascend AI 处理器的高性能集合通信库，提供单机多卡/多机多卡的数据并行与模型并行方案
- 包含 **HCCL 集合通信库 + HCOMM 通信基础库**（控制面+数据面分层）

### Q28. 支持的通信原语与算法？
- 原语：AllReduce、Broadcast、AllGather、ReduceScatter、AlltoAll（及 Send/Recv）
- 算法：Ring、Mesh、Halving-Doubling (HD)
- 底层传输：HCCS（片内/片间）、RoCE（跨机 RDMA）、PCIe（兜底）
- CANN 9.0 新增 **UB** 与 **CCU**（Collective Communication Unit）

### Q29. HCCL vs NCCL 对比？
| 维度 | HCCL | NCCL |
|---|---|---|
| API 形态 | `HcclAllReduce` 等 | `ncclAllReduce` 等 |
| 拓扑 | HCCS P2P full-mesh（无 NVSwitch） | NVLink 全互联 + NVSwitch |
| 单 pair 带宽 | ~56 GB/s（910B） | 400-900 GB/s |
| 算子展开位置 | AICPU / AIV / Host CPU / CCU | 主要 GPU SM |
| 可编程性 | 9.0 开放 HCOMM 自定义开发接口 | 较黑盒 |

### Q30. ⚠️ `HCCL_TIMEOUT` 不存在！正确变量名是什么？
- **CANN 中没有名为 `HCCL_TIMEOUT` 的环境变量**
- **实际变量是 `HCCL_EXEC_TIMEOUT`**：通信算子执行同步等待时间
- A2/A3 范围 [0, 2147483647] 秒，**默认 1836**；`0` 表示永不超时
- 若 `HCCL_OP_EXPANSION_MODE=AIV` 则范围 [0, 1091]，默认 1091
- 来源：[CANN 8.5 HCCL_EXEC_TIMEOUT](https://www.hiascend.com/document/detail/en/CANNCommunityEdition/850/maintenref/envvar/envref_07_0078.html)

### Q31. 其他常见 HCCL 环境变量？
| 变量 | 作用 | 默认值 |
|---|---|---|
| `HCCL_WHITELIST_DISABLE` | 0=启用白名单（仅信任列表内 IP），1=禁用 | **1**（默认禁用） |
| `HCCL_IF_BASE_PORT` | 主机网卡起始端口，使用从该端口起的 **32 个端口** | 60000-60031 |
| `HCCL_CONNECT_TIMEOUT` | socket 建链超时，范围 [120, 7200] | 120 秒 |
| `HCCL_SOCKET_IFNAME` | 主机网卡选择（`eth`/`^eth`/`=eth0`/`^=eth0`） | 系统自动 |
| `HCCL_RDMA_TIMEOUT` | RDMA NIC 重传超时，公式 `4.096μs × 2^timeout` | 20 |
| `HCCL_OP_EXPANSION_MODE` | 算子展开模式（AIV 等） | - |
| `HCCL_BUFFSIZE` | HCCL buffer 大小 | - |

### Q32. 设备能力差异？
- 910A：仅 FP32 + ReduceOp=SUM
- 910B/B3/910C：FP32/FP16/INT8/INT16/INT32/BFP16 + SUM/MAX/MIN
- 310P3：FP32/INT16/FP16
- 910A 需 128B 对齐；310P 需 2B；910B/B3 inline reduce 无地址对齐限制

---

## 五、内存管理与 PagedAttention

### Q33. `aclrtMalloc` 关键细节？
- 在 Device（HBM）分配线性内存；**起始地址 64 字节对齐**
- 分配大小 = `ALIGN_UP[len, 32] + 32` 字节（向上取 32 倍数再加 32）
- 不初始化内容、不隐式同步
- 释放必须用 `aclrtFree`，且匹配分配 API

### Q34. 分配策略枚举？
- `ACL_MEM_MALLOC_HUGE_FIRST`（默认）：≤1MB 普通页，>1MB 优先 huge page
- `ACL_MEM_MALLOC_HUGE_ONLY`：仅 huge page
- `ACL_MEM_MALLOC_NORMAL_ONLY`：仅普通页
- `*_P2P` 变体用于跨设备拷贝

### Q35. 虚拟内存 API（CANN 8.5+）？
- `aclrtMallocPhysical`（分配物理内存返回 handle）
- `aclrtReserveMemAddress`（预留虚拟地址）
- `aclrtMapMem`（映射虚拟↔物理）
- 用于分配地址连续的虚拟内存，最大化物理内存利用率

### Q36. PagedAttention on Ascend（vllm-ascend 实现）？
- 核心算子：`torch_npu._npu_paged_attention(query, key_cache, value_cache, num_kv_heads, num_heads, scale_value, block_table, context_lens, out, workspace)`
- `block_table` 是物理块索引张量；`context_lens` 是每序列长度
- workspace 在 graph capture 时预计算并缓存（`graph_params.workspaces.get(num_tokens)`）

### Q37. 为什么 Ascend 需要 scatter/gather 自定义算子？
- Ascend **无 CUDA 风格 scatter/gather 原语**
- vllm-ascend 新增 `scatter_pa_kv_cache_vllm` 与 `gather_pa_kv_cache_vllm` 自定义算子（含 host tiling + kernel + torch binding）
- 专门处理 paged KV cache 的非连续内存布局

### Q38. 310P 特殊 KV cache shape？
- 5D `(2, num_blocks, (num_kv_heads*head_size)//16, block_size, 16)`
- head_size 必须对齐 16

### Q39. FIA（Fused Infer Attention）替代路径？
- decode 期也可用 `torch_npu.npu_fused_infer_attention_score.out(query, key, value, block_table, input_layout="TND", block_size, actual_seq_lengths, ...)`
- 原生支持 paged KV

---

## 六、Profiling（msprof / Ascend PyTorch Profiler）

### Q40. 三层工具？
- **msprof**：CANN 命令行采集工具
- **Ascend PyTorch Profiler** = `torch_npu.profiler`：在 PyTorch 脚本中插入 API 采集
- **MindStudio Insight**：可视化工具加载 `PROF_XXX` 目录

### Q41. 输出目录结构？
```
PROF_XXX/
├── host/data               # host 原始数据
├── device_{id}/data        # device 原始数据
├── msprof_{timestamp}.db   # DB 格式
└── mindstudio_profiler_output/
    ├── msprof_{timestamp}.json     # timeline JSON
    ├── op_summary_{timestamp}.csv # AI Core & AICPU 算子明细
    ├── op_statistic_{timestamp}.csv # 按 Op Type 聚合
    └── trace_view.json            # torch_npu 集成视图
```

### Q42. 关键文件含义？
- **`trace_view.json`**：torch_npu 集成 CANN 软件栈 + NPU 数据的统一 trace，含 PyTorch op 树、ACL↔NPU kernel flow event、GC 层
- **`op_summary_*.csv`**：含算子输入/输出 shape、PMU 性能监控、`Task Duration`、`Task Type`（AI Core / AICPU）
- **`op_statistic_*.csv`**：按 Op Type 聚合，给出每种算子类型的总调用时长和调用次数

### Q43. 采集的 activities？
- `ProfilerActivity.CPU` + `ProfilerActivity.NPU`（仅这两种，不似 PyTorch CUDA 的 CUDA activity）

### Q44. _ExperimentalConfig 关键字段？
- `export_type`(Text/Db)、`profiler_level`(Level0 默认 / Level1 更详细)
- `aic_metrics`、`l2_cache`、`op_attr`（仅 aclnn 算子）、`data_simplification`、`record_op_args`

---

## 七、vllm_ascend 关键事实

### Q45. vllm_ascend 是什么？
- **vllm-project/vllm-ascend**（GitHub），Apache 2.0，社区维护
- vLLM 的**社区维护硬件插件**，遵循 `[RFC]: Hardware pluggable`（vllm#11162）
- **版本对齐上游 vLLM**：v0.23.0 ↔ vLLM v0.23.0（最新稳定，2026-08-16 发布）

### Q46. 插件注册机制？
- 通过 Python `entry_points` 注册，组名 `vllm.platform_plugins`
- 条目：`ascend = vllm_ascend:register`
- `register()` 返回字符串 `"vllm_ascend.platform.NPUPlatform"`
- 来源：[setup.py L543-L551](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/setup.py#L543-L551)

### Q47. 平台类 NPUPlatform？
- 类名是 **`NPUPlatform`**（不是 `AscendPlatform`），继承 `vllm.platforms.Platform`
- `_enum = PlatformEnum.OOT`（out-of-tree 平台）
- `device_name="npu"`、`device_type="npu"`、`device_control_env_var="ASCEND_RT_VISIBLE_DEVICES"`

### Q48. 安装方式？
**pip**：
```bash
pip install vllm==0.23.0
pip install --extra-index-url https://mirrors.huaweicloud.com/ascend/repos/pypi/variant vllm-ascend==0.23.0
```

**Docker**：
```bash
docker pull quay.io/ascend/vllm-ascend:v0.23.0  # Atlas A2 Ubuntu
# 变体：-openeuler/-a3/-a3-openeuler/-310p/-310p-openeuler/-950dt/-950dt-openeuler
```

### Q49. 软件栈要求？
| 软件 | 版本 |
|---|---|
| CANN | 9.1.0 |
| TorchNPU | 2.10.0.post4 |
| torch | 2.10.0 |
| NNAL | 9.1.0（提供 `libatb.so`） |
| Python | 3.10-3.13 |
| triton-ascend | 3.2.2（300I DUO 不支持，会卸载） |

### Q50. 部署命令模板？
```bash
# 单卡最小示例（无需 --device npu，插件自动激活）
vllm serve Qwen/Qwen3-0.6B &

# 多 NPU 4 卡 TP 示例
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export TASK_QUEUE_ENABLE=1
export HCCL_OP_EXPANSION_MODE="AIV"
vllm serve your_model_path \
  --served-model-name qwen3 --trust-remote-code \
  --distributed-executor-backend mp --tensor-parallel-size 4 \
  --max-model-len 5500 --max-num-batched-tokens 40960 \
  --no-enable-prefix-caching --async-scheduling \
  --quantization ascend \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}' \
  --block-size 128 --gpu-memory-utilization 0.9
```

### Q51. Ascend 量化方法名？
- `--quantization ascend`（非 vLLM 原生选项，由 `NPUPlatform.pre_register_and_update` 动态注入到 argparse choices）
- `supported_quantization` = `[ascend, compressed-tensors, fp8, deepseek_v4_fp8]`

### Q52. ACLGraph 模式配置？
- `--compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'`
- Ascend 的 cudagraph 等价物叫 **ACLGraph**

### Q53. 关键代码路径（vllm_ascend/ 目录）？
| 子模块 | 作用 |
|---|---|
| `platform.py` | NPUPlatform，平台注册核心 |
| `attention/` | 多注意力后端：attention_v1/mla_v1/sfa_v1/dsa_v1/fa3_v1 |
| `quantization/` | AscendModelSlimConfig（W8A8）/ AscendCompressedTensorsConfig / AscendFp8Config |
| `compilation/` | AscendCompiler + GraphFusionPassManager + **ACLGraphWrapper** |
| `distributed/` | NPUCommunicator + kv_transfer（Mooncake） |
| `worker/` | NPUWorker / NPUWorker310 / XliteWorker |
| `device_allocator/` | CaMemAllocator（自定义显存分配，sleep mode 支撑） |
| `lora/` | PunicaWrapperNPU |
| `eplb/` | Expert Parallel Load Balancing |
| `spec_decode/` | eagle3、deepseek_mtp 投机 |
| `csrc/` | C++ 算子：attention/gmm/mc2/mla_preprocess/moe |

### Q54. 「torchatb」真相？
- **不存在叫 `torchatb` 的独立包**
- `atb` = Ascend Tensor Boost，由 **NNAL**（Ascend Neural Network Acceleration Library）提供 `libatb.so`，属于 **CANN** 一部分
- Python 侧通过 **`torch_npu.atb.*`** 命名空间访问（如 `torch_npu.atb.npu_paged_cache_load`）

### Q55. 「sparseLA / ditp」真相？
- v0.23.0 代码库中**未找到**这些术语
- 推测是旧版或他项目命名
- 当前等价物：`AscendSFABackend`（sfa_v1.py，Sparse Flash Attention）+ `AscendDSABackend`（dsa_v1.py）

### Q56. vllm_ascend 自有 vs 运行时环境变量分类？
**A. vllm-ascend 自有环境变量**（`envs.py`，多为 `VLLM_ASCEND_*`）：
- `VLLM_ASCEND_ENABLE_MLAPO`（默认 1）：DeepSeek W8A8 MLAPO 优化
- `VLLM_ASCEND_ENABLE_FUSED_MC2`（默认 0）：MC2 通信融合（0/1/2 三档）
- `VLLM_ASCEND_ENABLE_MATMUL_ALLREDUCE`（默认 0）：MatmulAllReduce 融合核
- `VLLM_ASCEND_ENABLE_FLASHCOMM1`（默认 0）：FlashComm 优化
- `VLLM_ASCEND_FLASHCOMM2_PARALLEL_SIZE`（默认 0）：>0 启用 FlashComm2
- `VLLM_ASCEND_ENABLE_NZ`（默认 1）：权重转 FRACTAL_NZ 格式
- `VLLM_ASCEND_BALANCE_SCHEDULING`（默认 0）：均衡调度
- `DYNAMIC_EPLB`（默认 false）：动态 EPLB
- `SOC_VERSION`：构建时芯片版本（A2=`ascend910b1`、A3=`ascend910_9391`、310P=`ascend310p1`、950DT=`ascend950dt_9582`）

**B. CANN/HCCL 运行时环境变量**（部署脚本常见，非 vllm-ascend 自有）：
- `ASCEND_RT_VISIBLE_DEVICES`：NPU 设备选择（等价 `CUDA_VISIBLE_DEVICES`）
- `PYTORCH_NPU_ALLOC_CONF`：NPU 显存分配策略；默认追加 `expandable_segments:True`
- `TASK_QUEUE_ENABLE=1`：开启 Ascend task queue（多卡必备）
- `HCCL_OP_EXPANSION_MODE="AIV"`：HCCL 算子展开模式
- `HCCL_BUFFSIZE`：HCCL buffer 大小
- `HCCL_IF_IP` / `HCCL_SOCKET_IFNAME` / `GLOO_SOCKET_IFNAME` / `TP_SOCKET_IFNAME`：多节点通信网卡/IP 配置
- `LD_LIBRARY_PATH`：含 CANN 库路径
- `LD_PRELOAD`：如 `libjemalloc.so.2`
- `LCCL_DETERMINISTIC=1`：确定性算法（batch invariance 场景，由 `batch_invariant.py` 设置）
- `VLLM_USE_MODELSCOPE=True`：用 ModelScope 镜像下模型
- `ASCEND_LAUNCH_BLOCKING`：不能与 ACLGraph 同时为 1

### Q57. 「未验证」环境变量（用户提到但代码中找不到）？
- `ASCEND_RT_OPTIONS`：v0.23.0 代码库中**未找到**
- `COMBINE_ENABLE`：v0.23.0 代码库中**未找到**
- `ATB_LLM_ENABLE_MC2`：v0.23.0 代码库中**未找到**（疑为旧版；当前用 `VLLM_ASCEND_ENABLE_FUSED_MC2` 取代相关语义）

### Q58. 已知限制 / 与 NVIDIA 上游 vLLM 差异？
- 🟡 **Enc-dec**：Planned（计划中），需 vLLM 先支持
- 🔵 **实验性**：LoRA、Pooling、Beam search
- 🟢 **已功能化**：Chunked Prefill、APC、Speculative decoding、Multi-Modality、TP、PP、EP、DP、PD 分离、Quantization、Graph Mode、Sleep Mode、Context Parallel
- **torch.compile 禁用**：`simple_compile_backend = "eager"`，`use_inductor = False`
- **Breakable cudagraph 强制关闭**：`VLLM_USE_BREAKABLE_CUDAGRAPH = False`
- **ACLGraph 与 ASCEND_LAUNCH_BLOCKING 互斥**
- **PCP 与 DP 不能同时开**
- **PP+MTP 限制**：仅 PD 分离 P 节点支持；D 节点必须 `pipeline_parallel_size=1`
- **量化支持矩阵**：W8A8 全面可用；W4A8/W4A4 部分场景可用
- **310P 不支持 MLA/SFA/FA3**

---

## 八、常见 Bug / Gotchas

### Q59. ACL_ERROR_RT_QUEUE_FULL = 207014 "queue is full"？
- torch_npu 异步 task queue（`Repository` 环形 buffer，容量 **4096**）已满
- `WriteQueue` 返回 false 触发 `Enqueue` 阻塞（生产者-消费者模型，eventfd 同步）
- 来源：[torch_npu NPUQueue.cpp](https://github.com/Ascend/pytorch/blob/15c68ef6/torch_npu/csrc/core/npu/NPUQueue.cpp)

### Q60. "aclnn op not registered"？
- 原因 1：operator name 冲突（如 DeepSeek-V3.2 + VERL 框架，ops 在 vllm_ascend 与 CANN built-in 同名 → segfault）
- 修复：rename with `_custom` suffix
- 原因 2：CANN 版本不含该算子
- 原因 3：PTA（torch_npu）尚未集成

### Q61. NPU not visible（npu-smi info 返回 -8005）？
- -8005 = device occupied by another container
- dcmi module initialize failed
- 修复：检查 `--device` 挂载 + `/usr/local/dcmi` + `/usr/local/Ascend/driver` volume
- 或用 `--privileged` + 完整宿主挂载（仅开发环境）
- `ASCEND_RT_VISIBLE_DEVICES` 也会过滤 NPU

### Q62. 容器内 OOM 杀进程？
- `dmesg | grep -i 'killed process'` 看宿主内核日志
- `docker inspect <id> --format '{{.State.OOMKilled}}'` 是否 OOMKilled
- cgroup memory limit 触发 OOM killer（按 `oom_score_adj` 选最该杀的进程）
- 防御：`--memory` 略大于峰值、JVM/PyTorch 显式设堆/缓存上限

### Q63. 训练脚本卡住不动排查？
1. `npu-smi info` 看 NPU 利用率是否为 0
2. `py-spy dump --pid <pid>` 看 Python 调用栈（不修改代码）
3. `top -H -p <pid>` 找最忙线程，`py-spy top --pid <pid>` 看实时函数热点
4. `cat /proc/<pid>/wchan` 看内核态等待点（如 `futex_wait` → 锁竞争）
5. 多卡训练卡死通常是 rank 0/1 通信 hang，检查 HCCL 日志

---

## 九、一页速记卡

| 类别 | 必背 |
|---|---|
| DaVinci | 三级单元（Scalar/Vector/Cube）；L0A→L0C→UB→GM 流水 |
| 硬件 | 910B（64GB/400T）/910C（128GB/800T/双 die）/310P（推理） |
| HCCS | P2P full-mesh，无 NVSwitch；910B 单 pair ~56 GB/s |
| CANN | 9.0.0；Toolkit+ops+NNAL；ATC→.om；ACL/AscendCL |
| AclGraph | = CUDA Graph 等价物；Piecewise vs Full |
| torch_npu | `import torch_npu`；dispatch key `PrivateUse1`；NPUGraph |
| HCCL | AllReduce/Broadcast/AllGather；Ring/Mesh/HD |
| ⚠️ 纠错 | `HCCL_TIMEOUT` 不存在；正确为 `HCCL_EXEC_TIMEOUT` 默认 1836 |
| vllm_ascend | NPUPlatform（不是 AscendPlatform）；entry_points 注册 |
| 安装 | `pip install vllm-ascend` + 镜像 `quay.io/ascend/vllm-ascend:v0.23.0` |
| 部署 | `vllm serve` 无需 `--device npu`；多卡 `ASCEND_RT_VISIBLE_DEVICES` + `--tensor-parallel-size` |
| 量化 | `--quantization ascend`（非 `deepseek_fp8`！） |
| ACLGraph | `--compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'` |
| atb | `libatb.so` 由 NNAL 提供，Python 走 `torch_npu.atb.*`（无独立 torchatb 包） |
| 排错 | queue full=207014；npu-smi info -8005=被占；`py-spy dump` 查栈 |
