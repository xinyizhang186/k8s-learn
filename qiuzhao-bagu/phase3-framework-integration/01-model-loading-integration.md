# 推理框架集成与模型加载 - 八股速记

> 适用范围：秋招 AI Infra 岗位（推理框架方向）
> 涵盖：HF 集成 / 权重加载 / 分片 / safetensors / 分布式初始化

---

## 一、HuggingFace 集成

### Q1. vLLM 如何与 HuggingFace Transformers 集成？
- vLLM 复用 Transformers 的 `modeling_*.py` 文件作为模型实现参考，但**不直接调用 HF 的 forward**——它有自己的优化实现。
- 模型注册：`vllm/model_executor/models/registry.py`，把 HF 模型架构名（如 `LlamaForCausalLM`）映射到 vLLM 内部实现。
- 配置：读 `config.json` 的 `model_type` / `architectures` 字段决定加载哪个 vLLM 实现。

### Q2. vLLM 的模型加载流程？
```
1. 读 config.json → 确定模型架构（如 LlamaForCausalLM）
2. 在 registry 中查找对应 vLLM 实现（LlamaForCausalLM → vllm.model_executor.models.llama.LlamaForCausalLM）
3. 创建 model 实例（空权重）
4. ModelLoader.load_weights() 逐层加载权重（按 layer 顺序）
5. 权重名映射：HF 命名 → vLLM 命名（通过 `mapped_weights` 生成器）
6. 应用 quantization（如果有）
7. 分配到 device（GPU/NPU）
8. （可选）tensor parallel sharding
```

### Q3. weight name 映射怎么做？
- HF 与 vLLM 的权重命名约定不完全一致。
- vLLM 用 `weight_loader` 回调函数做映射：HF `model.layers.0.self_attn.q_proj.weight` → vLLM 内部 `model.layers.0.self_attn.q_proj.weight`（多数一致），但 TP 切分、fused QKV 等会改命名。
- 例：vLLM 把 Q/K/V 权重 fused 成 `qkv_proj`，加载时拆分。

### Q4. 如何注册新模型？
- 在 `vllm/model_executor/models/registry.py` 的 `_MODELS` dict 中加：
```python
@_MODELS.register("MyModel")
class MyModel(nn.Module):
    ...
```
- 或用 `@register("MyModel")` 装饰器。
- 需实现 `weight_loader` 方法处理权重名映射 + TP 切分。

---

## 二、权重格式与分片

### Q5. safetensors vs pickle (.bin)？
| 维度 | safetensors | pickle (.bin) |
|---|---|---|
| 加载速度 | 快（mmap，零拷贝） | 慢（unpickle 全量读） |
| 安全性 | 高（无任意代码执行） | **低**（pickle 反序列化可执行任意代码，CVE 风险） |
| 格式 | 开放 spec，header + tensor blobs | Python pickle |
| 跨语言 | 支持（Rust/Safetensors C++） | Python only |
| 检查 | 可读 header 不加载全部 | 必须全加载才知道有什么 |
| vLLM 支持 | 优先 | 兼容 |

- HuggingFace 已将 safetensors 设为默认上传格式。
- 大模型仓库（如 Qwen2.5-7B）通常同时有 `.safetensors` 和 `.bin`，vLLM 优先用前者。

### Q6. 为什么大模型权重分片（sharding）？
- 单文件上限：GitHub LFS 默认 5GB，GitLab 10GB；HF Hub 单文件理论上无硬限，但下载/续传/缓存效率在大文件上差。
- 大模型权重远超此：Llama-70B FP16 约 140GB → 切成 30+ 片。
- 命名约定：`model-00001-of-00004.safetensors` + `model.safetensors.index.json`（分片索引）。

### Q7. `model.safetensors.index.json` 结构？
```json
{
  "metadata": {"total_size": 14000000000},
  "weight_map": {
    "model.embed_tokens.weight": "model-00001-of-00004.safetensors",
    "model.layers.0.self_attn.q_proj.weight": "model-00001-of-00004.safetensors",
    ...
    "lm_head.weight": "model-00004-of-00004.safetensors"
  }
}
```
- 加载时先读 index，按需打开对应分片文件，用 mmap 加载 tensor。

### Q8. vLLM 加载权重如何并行化？
- `multiproc` 模式下，每个 worker 进程独立加载自己负责的 TP shard（避免主进程全加载再广播）。
- 用 ` SafetensorsZipLoader` 或 mmap 按需读取，不全量读入内存。
- 多文件并行读（`asyncio` + `aiofiles`）。

---

## 三、Tensor Parallel 权重切分

### Q9. Tensor Parallel（TP）原理？
- 把模型权重按某个维度切到 N 张卡，每卡算一部分，结果用 all-reduce 合并。
- Linear 层：输入 X，权重 W = [W_1; W_2; ...; W_N]（按行切）。
  - 每卡算 `Y_i = X @ W_i`，all-reduce 合并：`Y = sum(Y_i)`。
  - 不需要通信 X，只 reduce 输出。
- 通信开销：每个 Linear 后跟一次 all-reduce，与 FLOP 重叠可隐藏。

### Q10. Column Parallel vs Row Parallel？
| 维度 | Column Parallel | Row Parallel |
|---|---|---|
| 切分维度 | 输出维度（W 的行） | 输入维度（W 的列） |
| 权重形状 | 每卡 [out/N, in] | 每卡 [out, in/N] |
| 输入 | 全量（每卡都有） | 切分（每卡一份） |
| 输出 | 切分 | 全量 |
| 通信 | 输出需 all-gather | 输出需 all-reduce |
| 典型 | Q/K/V projection | FFN 的 down projection |

### Q11. vLLM 默认的 TP 策略？
- Attention 的 Q/K/V/O：Q/K/V 用 column parallel（每卡部分 head），O 用 row parallel（输入聚合）。
- FFN 的 up projection（gate/up）：column parallel。
- FFN 的 down projection：row parallel。
- Embedding：column parallel（每卡部分 vocab）。
- LayerNorm/RMSNorm：不切（每卡全量算）。

### Q12. fused QKV 权重加载怎么处理？
- HF 分别存 `q_proj`、`k_proj`、`v_proj`，vLLM 内部 fused 成 `qkv_proj`。
- 加载时按 head 维度重新排列：每张卡拿自己负责的 head 的 Q/K/V 拼接。
- 代码示例（vLLM `LlamaParallelLinear.weight_loader`）。

### Q13. Pipeline Parallel（PP）原理？
- 把模型按 layer 切到 N 张卡，每卡算一段 layer，结果传给下一张卡。
- 通信：每段后 send/recv activation（不是 all-reduce）。
- 优势：通信量小（只传 activation）；劣势：bubble（前一段没算完，后一段空等）。
- vLLM 用 `--pipeline-parallel-size N` 配置；用 1F1B（one forward one backward）调度减少 bubble。

### Q14. TP vs PP vs DP 选择？
| 维度 | TP | PP | DP |
|---|---|---|---|
| 切分 | 权重切 | 模型按 layer 切 | 数据切，模型复制 |
| 通信 | all-reduce（每层） | send/recv（每段） | 数据并行同步 |
| 通信量 | 大（每层） | 小（每段一次） | 大（梯度同步） |
| 显存 | 减权重 | 减 layer 缓存 | 不减（复制） |
| bubble | 无 | 有 | 无 |
| vLLM 默认 | TP | PP（兼容） | DP（数据并行，多副本） |
| 典型 | 单机内 | 跨机 | 跨机高吞吐 |

---

## 四、分布式初始化

### Q15. vLLM 的分布式后端？
- `--distributed-executor-backend`：
  - `mp`（multiprocessing）：单机多进程，用 `torch.distributed` + gloo/nccl backend。
  - `ray`：跨机多节点，用 Ray 集群管理 + RayWorker。
  - `external`：外部 launcher（如 k8s Job、Slurm）。
- NPU（昇腾）：`mp` + HCCL backend。

### Q16. ProcessGroup 初始化流程？
1. 主进程拉起 N 个 worker 子进程（mp 模式）。
2. 每个 worker 设置 `RANK`、`WORLD_SIZE`、`MASTER_ADDR`、`MASTER_PORT`。
3. 调 `torch.distributed.init_process_group(backend='nccl'/'hccl')`。
4. 主进程与 worker 间用 local socket 或 ZMQ 通信（控制面）。
5. worker 间用 NCCL/HCCL 通信（数据面）。

### Q17. NCCL/HCCL 的 all-reduce 实现原理？
- **Ring All-Reduce**：N 个 rank 组成环，每步每 rank 把一块 send 给下一 rank + receive 上一 rank 的块 + accumulate。
- 总通信量：`(N-1)/N × data_size`，每个 link 上是 `2(N-1)/N × data_size / N`（带宽利用率高）。
- 对比：树形 all-reduce 通信量相同但延迟更低（log N）。
- 大数据用 Ring（吞吐高），小数据用 Tree（延迟低）。

### Q18.昇腾上的分布式通信？
- `vllm_ascend.distributed.device_communicators.npu_communicator.NPUCommunicator`。
- 底层调 HCCL，算法可选 Ring/Mesh/Halving-Doubling。
- 跨节点用 RoCEv2 RDMA；节点内用 HCCS（P2P full-mesh，无 NVSwitch）。

---

## 五、模型加载优化

### Q19. weight preloading / async loading？
- vLLM V1 支持 async loading：在主进程调度其他工作时，worker 进程后台加载权重。
- 加快冷启动（首请求延迟降低）。

### Q20. bnb（bitsandbytes）4-bit 在线量化加载？
- 不需提前量化：模型仍是 FP16 权重，运行时按 NF4 量化。
- 加载时用 `BitsAndBytesConfig`：`load_in_4bit=True`，`quant_type="nf4"`。
- 优势：不用预量化步骤；劣势：量化无校准数据，精度略差。

### Q21. sleep mode / KV cache offload？
- vLLM 1.0+ 支持 sleep mode：服务空闲时把权重/KV cache 卸载到 CPU 内存或磁盘，释放 GPU 给其他 Pod。
- 唤醒时再 load 回来，比冷启动快（权重在 CPU 内存，PCIe 拷贝 < 1s vs 重新下载 > 分钟级）。
- 昇腾用 `CaMemAllocator` 支撑（`is_cumem_allocator_available=True`）。

### Q22. Mooncake / LMCache / NIXL（KV transfer）？
- PD 分离部署时，P 节点 prefill 算完 KV cache 后，要把 KV cache 传到 D 节点 decode。
- Connector 抽象：`kv_transfer_config = {"kv_connector": "MooncakeConnectorV1", ...}`。
- 传输方式：RDMA、NVLink、共享内存。
- Mooncake：清华 mooncake 项目，P2P KV cache transfer。
- LMCache：UC Berkeley，KV cache 多级缓存。
- NIXL：NVIDIA Inference Transfer，基于 RDMA。

---

## 六、一页速记卡

| 类别 | 必背 |
|---|---|
| 模型加载 | 读 config.json → registry 找 vLLM 实现 → 创建实例 → load_weights → TP shard |
| safetensors | mmap 零拷贝 + 防 pickle 反序列化攻击；HF 默认 |
| 分片 | 单文件 5GB 限；index.json 映射 weight→file |
| TP 原理 | 权重切到 N 卡，all-reduce 合并输出 |
| Column/Row Parallel | Column 切输出（Q/K/V）；Row 切输入（FFN down） |
| fused QKV | HF 分别存 q/k/v_proj；vLLM 内部 fuse 为 qkv_proj，加载时按 head 重排 |
| PP | 按 layer 切，send/recv，有 bubble |
| DP | 数据切，模型复制，跨机高吞吐 |
| 分布式后端 | mp（单机）/ ray（跨机）/ external（k8s/Slurm） |
| All-Reduce | Ring（吞吐高）/ Tree（延迟低）；通信量 (N-1)/N × data |
| 加载优化 | async loading / sleep mode / KV offload |
| KV transfer | Mooncake / LMCache / NIXL；PD 分离必备 |
