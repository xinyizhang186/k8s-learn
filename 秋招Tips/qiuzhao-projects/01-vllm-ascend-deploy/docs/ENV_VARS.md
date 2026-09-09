# vllm_ascend 关键环境变量速查

> 区分两类：① vllm-ascend **自有** env（`envs.py`，多为 `VLLM_ASCEND_*`）；② **CANN/HCCL 运行时** env（部署脚本设置）

## vllm-ascend 自有环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `VLLM_ASCEND_ENABLE_MLAPO` | 1 | DeepSeek W8A8 的 MLAPO 优化，提性能但增显存；省显存设 0 |
| `VLLM_ASCEND_ENABLE_FUSED_MC2` | 0 | MC2 通信融合（0=默认，1=dispatch_ffn_combine，2=decode） |
| `VLLM_ASCEND_ENABLE_MATMUL_ALLREDUCE` | 0 | TP 时 MatmulAllReduce 融合核（A2 eager 更优） |
| `VLLM_ASCEND_ENABLE_FLASHCOMM1` | 0 | FlashComm 优化（已废弃，改用 additional_config） |
| `VLLM_ASCEND_FLASHCOMM2_PARALLEL_SIZE` | 0 | >0 启用 FlashComm2 |
| `VLLM_ASCEND_ENABLE_NZ` | 1 | 权重转 FRACTAL_NZ 格式（0=关，1=仅量化，2=尽量开） |
| `VLLM_ASCEND_BALANCE_SCHEDULING` | 0 | 均衡调度（已废弃，用 additional_config） |
| `VLLM_ASCEND_ENABLE_BATCH_MEMCPY` | auto | KV cache offload 批量拷贝 |
| `DYNAMIC_EPLB` | false | 动态 EPLB |
| `SOC_VERSION` | - | 构建时芯片版本 |

## CANN/HCCL 运行时环境变量（部署脚本常见）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ASCEND_RT_VISIBLE_DEVICES` | - | **NPU 设备选择**（等价 `CUDA_VISIBLE_DEVICES`），如 `0,1,2,3` |
| `PYTORCH_NPU_ALLOC_CONF` | - | NPU 显存分配策略；vllm-ascend 默认追加 `expandable_segments:True` |
| `TASK_QUEUE_ENABLE` | - | 开启 Ascend task queue（多卡部署**几乎必备**） |
| `HCCL_OP_EXPANSION_MODE` | - | HCCL 算子展开模式（常用 `AIV`） |
| `HCCL_BUFFSIZE` | - | HCCL buffer 大小（如 `200`/`512`） |
| `HCCL_IF_IP` | - | 多节点通信 IP 配置 |
| `HCCL_SOCKET_IFNAME` | - | 主机网卡选择（`eth`/`^eth`/`=eth0`/`^=eth0`） |
| `HCCL_IF_BASE_PORT` | 60000 | 主机网卡起始端口，使用 32 个端口 |
| `HCCL_EXEC_TIMEOUT` | 1836 | 通信算子执行同步等待时间（秒）。**注意：不存在 `HCCL_TIMEOUT`** |
| `HCCL_CONNECT_TIMEOUT` | 120 | socket 建链超时（秒） |
| `HCCL_RDMA_TIMEOUT` | 20 | RDMA NIC 重传超时（`4.096μs × 2^timeout`） |
| `HCCL_INTRA_PCIE_ENABLE` | - | 节点内 PCIe 通信开关 |
| `HCCL_INTRA_ROCE_ENABLE` | - | 节点内 ROCE 通信开关 |
| `LD_LIBRARY_PATH` | - | 含 CANN 库路径 |
| `LD_PRELOAD` | - | 如 `libjemalloc.so.2` |
| `LCCL_DETERMINISTIC` | - | 确定性算法（batch invariance 场景） |
| `VLLM_USE_MODELSCOPE` | - | `True` 用 ModelScope 镜像下模型 |
| `VLLM_PLUGINS` | - | 控制加载哪些 vLLM 插件 |
| `ASCEND_LAUNCH_BLOCKING` | - | 同步执行（调试用，**不能与 ACLGraph 同时为 1**） |
| `TORCH_DEVICE_BACKEND_AUTOLOAD` | - | 设备自动加载，CPU-only 构建时设 0 |

## 未验证环境变量

以下变量在 v0.23.0 代码库中**未找到**，可能是旧版或其他项目命名：
- `ASCEND_RT_OPTIONS`
- `COMBINE_ENABLE`
- `ATB_LLM_ENABLE_MC2`（当前用 `VLLM_ASCEND_ENABLE_FUSED_MC2` 取代相关语义）
