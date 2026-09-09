# vLLM 深度解析 - 八股速记

> 适用范围：秋招 AI Infra 岗位（推理框架方向）
> 当前年份：2026，核对日期：2026-08-21
> 事实均附论文 / GitHub 源码 / 官方文档链接；不能在当前 `main` 核实的标注「未验证」

---

## 一、PagedAttention（分页注意力）

### Q1. 核心论文与类比？
- 论文：Kwon et al., *Efficient Memory Management for LLM Serving with PagedAttention*, SOSP 2023（[arxiv 2309.06180](https://arxiv.org/abs/2309.06180)）。
- 类比 OS 虚拟内存分页：每个请求 KV cache 切成固定大小 **KV block**（类比 page），token 类比 byte，request 类比 process。逻辑块可映射到非连续物理块。

### Q2. 默认 block size = 16（已核实）？
- 论文 §7.2 明确「vLLM sets its default block size as 16」。
- 代码 `tests/conftest.py`、`tests/v1/core/utils.py`、benchmarks 中 `block_size: int = 16` 处处可见。
- **CPU 后端默认 128**（CPU 安装文档「multiples of 32, with 128 being the default」）。

### Q3. 逻辑块 vs 物理块映射？
- 每个请求维护一张 **block table**（逻辑块号 → 物理块号），逻辑上连续，物理上非连续。
- 例：7-token prompt 映射逻辑块 0,1 → 物理块 7,1。

### Q4. 消除碎片化的原理？
- 块按需分配，**外部碎片为 0**（所有块同尺寸）。
- 用相对小的块缓解**内部碎片**。
- 块粒度支持跨请求内存共享（parallel sampling / beam search / 共享 system prompt）。

### Q5. block size 权衡？
- 太小 → GPU 并行度不足；太大 → 内部碎片↑、共享命中率↓。
- 论文实测 16–128 在 ShareGPT 上最优，Alpaca 上 16/32 最好。

### Q6. KV block 存储布局？
- key/value 分别按 `[num_blocks, num_kv_heads, head_size/x, block_size, x]` / `[num_blocks, num_kv_heads, head_size, block_size]` 存储。
- x 是向量化因子（如 head_size=128 时 x=8）。
- 设计文档：[docs.vllm.cc/design/paged_attention](https://docs.vllm.cc/en/latest/design/paged_attention/)

### Q7. PagedAttention CUDA kernel 结构？
- vLLM 自实现 `paged_attention_kernel`（`csrc/attention/attention_kernels.cu`）。
- 模板参数含 `BLOCK_SIZE`、`HEAD_SIZE`、`NUM_THREADS`、`PARTITION_SIZE`（TP 数）。
- kernel 内逐 block 读取 block table、计算 attention score、与 value 相乘。

### Q8. kernel 开销对比？
- 相比 FasterTransformer 高度优化 attention，PagedAttention 单 kernel 延迟高 20–26%（因 block table 查表、分支、变长处理）。
- 但端到端仍 2–4× 领先（碎片消除 + 共享命中）。

### Q9. 跨请求块共享（copy-on-write）？
- 共享块通过引用计数管理，写时才复制新块。
- 支持 parallel sampling / beam search / 共享 system prompt。

### Q10. 关于「prefix_scan / swap 操作」？
- ⚠️ **未验证**：当前 `main` 分支源码与论文均**未发现**名为 `prefix_scan` 的 kernel 操作。
- 「swap」在论文语境下指 **KV cache 在 CPU↔GPU 之间换入换出**（preemption 恢复机制），而非 attention kernel 内部操作。

---

## 二、Continuous Batching（连续批处理）

### Q1. 静态批处理 vs 连续批处理？
- **静态**：请求级组批，batch 内所有序列必须同时完成，短序列等长序列 → GPU 空转。
- **连续**：每次 decode 迭代级别动态插入/移除请求，新请求随时进、完成请求随时出。

### Q2. 为何提升 GPU 利用率？
- decode 每步仅处理 1 token，单请求算力远不饱和。
- 把多个 decode 请求拼到同一 batch，且 prefill 与 decode 可共存，提升吞吐。

### Q3. V0 调度器三队列结构（V0 经典设计）？
- `waiting`（待调度的新请求）、`running`（正在生成）、`swapped`（被抢占、KV cache 已换出到 CPU）。
- ⚠️ 当前 `main` 分支**已移除 V0 代码**（`vllm/core/scheduler.py` 返回 404），此结构为历史 V0 设计，依据论文 §4.5–4.6 描述。

### Q4. V1 调度器队列结构（已核实）？
- `Scheduler` 类位于 `vllm/v1/core/sched/scheduler.py`。
- 含 `self.waiting`（`create_request_queue(policy)`）、`self.running: list[Request]`、`self.skipped_waiting`（因异步依赖被跳过的请求）。

### Q5. 抢占（Preemption）两种策略？
- **Recompute（重算）**：丢弃 KV，日后从 prompt 重算。
- **Swap（换出）**：把 KV cache 经 PCIe 换到 CPU，日后换回。
- 论文实测：小 block size 下 recompute 更优（恒定开销），大 block size 下 swap 更优；recompute 开销不超过 swap 的 20%。

### Q6. all-or-nothing swap-out 策略？
- vLLM 利用「处理一个请求需其全部 token 状态都在 GPU」的语义，整体换出一个请求而非部分块（OS 做不到的 LLM 特化优化）。

### Q7. V1 已移除 GPU↔CPU KV swap？
- V1 特性表「GPU <> CPU KV Cache Swapping 🔴 Removed」。
- V1 主要靠 recompute + 前缀缓存应对压力，不再依赖 swap。
- 来源：[v1_guide 特性表](https://docs.vllm.ai/en/latest/usage/v1_guide/)

### Q8. 调度输出？
- V0 为 `SchedulerOutput`（区分 prefill/decode）。
- V1 简化为字典 `{request_id: num_tokens}`，每步指定每个请求处理多少 token。

---

## 三、Chunked Prefill（分块预填充）

### Q1. 功能开关与默认值？
- `--enable-chunked-prefill`。
- **V1 默认开启**（`SchedulerConfig.enable_chunked_prefill: bool = True`）。
- 来源：[vllm/config/scheduler.py](https://github.com/vllm-project/vllm/blob/main/vllm/config/scheduler.py)

### Q2. 解决什么问题？
- 长 prompt 一次性 prefill 是 compute-bound，独占一个调度步（head-of-line blocking）。
- 期间所有 decode 请求流式输出「冻结」，造成 ITL（inter-token latency）尖峰。
- Chunked prefill 把长 prefill 切成 token 级小块，与 decode 拼到同一 batch。

### Q3. 为何降低 TTFT 抖动？
- decode 优先——先把所有 pending decode 排入 batch，剩余 token budget 再给 prefill chunk。
- 保证「每个 running 请求每步至少前进 1 token」，流不卡顿。

### Q4. Token 预算 = max_num_batched_tokens？
- 每步处理的总 token 上限。
- 预算小 → 步长短、ITL 平滑但长 prompt TTFT 升高。
- 预算大 → prefill 更快、吞吐高但 ITL 抖动。

### Q5. 默认值（已核实，分版本）？
- **V1 默认 2048**（`SchedulerConfig.DEFAULT_MAX_NUM_BATCHED_TOKENS = 2048`），优化 ITL 而非吞吐。
- **V0 启用 chunked prefill 时默认 512**（v0.4.2 文档：「512 is the default max_num_batched_tokens for chunked prefill」）。

### Q6. 配套旋钮？
- `long_prefill_token_threshold`（默认约 context 的 4%）。
- `max_long_partial_prefills`、`max_num_partial_prefills`——让短 prompt 插队，防止单个超长请求独占 prefill 预算。

### Q7. 为何常是吞吐正收益？
- decode 是 memory-bound（读完整套权重才出 1 token），算术强度~1。
- 把 prefill chunk 搭便车到同一次权重读取，算术强度提升到 ~(1+chunk/decode)，权重读取成本被摊薄。

### Q8. Encoder-decoder 不支持？
- `is_encoder_decoder` 时强制关闭 chunked prefill。

### Q9. 与 speculative decoding 的交互？
- spec decode 每序列每步贡献 `(1 + num_speculative_tokens)` 个 token，会吃掉 `max_num_batched_tokens` 预算。
- 开启 spec decode 时应按比例调大预算。

---

## 四、Decode + Prefill 调度

### Q1. V1 Scheduler 类位置？
- `vllm/v1/core/sched/scheduler.py`，`class Scheduler(SchedulerInterface)`。
- 构造时接收 `vllm_config`、`kv_cache_config`、`block_size`、`structured_output_manager`。

### Q2. 统一调度表示？
- V1 取消 prefill/decode 阶段区分，把 user prompt token 与 model 生成 token 统一处理。
- 每步调度决策是字典 `{request_id: num_tokens}`。
- chunked prefill、prefix caching、spec decode 都建立在此表示上。

### Q3. 调度策略（policy）？
- 通过 `--scheduling-policy` 配置，支持 **FCFS**（默认）与 **priority**（按请求 priority 排序，FCFS 作 tie-breaker）。
- V1 scheduler 内 `self.policy = SchedulingPolicy(self.scheduler_config.policy)`。

### Q4. Decode 优先规则？
- 开启 chunked prefill 后，调度器先把所有 pending decode 排入 batch。
- 剩余 token budget 调度 prefill chunk。
- 若最后一个 prefill 请求放不下，则切分。

### Q5. KV cache 约束？
- `max_num_running_reqs = scheduler_config.max_num_seqs`（默认 128）。
- `max_num_scheduled_tokens` 默认等于 `max_num_batched_tokens`。

### Q6. Prefix caching 集成？
- 调度新请求时先调 `kv_cache_manager.get_computed_blocks()` 命中已算块。
- 再 `allocate_slots()` 分配新块。
- 「touch」命中块增加引用计数防驱逐。

### Q7. KVCacheBlock 数据结构（V1）？
- `block_id`、`block_hash`、`ref_cnt`、双向链表指针 `prev_free_block`/`next_free_block`。
- 初始化时一次性分配所有 Block 对象，避免运行期 Python 对象创建开销——这是 V1 prefix caching「零开销」的关键。

### Q8. LRU 驱逐？
- free queue 头部为 LRU 块。
- 被驱逐时从 cache 移除 block_id 与 block_hash。
- 请求结束时其块按逆序加入 free queue 尾部（最后一块哈希的 token 最多，最不可能复用，应先驱逐）。

### Q9. Prefill-Decode 分离（disaggregation）之争？
- colocated（chunked prefill）小规模/单节点更简单、利用率高。
- disaggregated（DistServe/Splitwise/Mooncake）把 prefill 与 decode 放不同 GPU 池，KV cache 经 NVLink/RDMA 传输，TTFT 与 ITL 都更可控但需 KV 传输 fabric 与双份部署。
- vLLM 通过 `kv_transfer` connector（NIXL/LMCache/Mooncake 等）支持 disaggregated prefill。

### Q10. V0 的 prefill 优先策略？
- 默认 scheduler 优先 prefill、不与 decode 拼批——优化 TTFT 但 ITL 差、GPU 利用率低。
- 开启 chunked prefill 后切换为 decode 优先。

---

## 五、Worker / Executor / Engine 架构

### Q1. V1 架构链路（已核实）？
- `AsyncLLM`（API 层，异步）→ `EngineCore`（隔离执行循环，专注 scheduler + executor）→ `Executor`（`vllm/v1/executor/`）→ `Worker`（`vllm/v1/worker/`）→ `ModelRunner`（`vllm/v1/worker/gpu/`）→ model forward。
- 来源：[v1 blog §1](https://vllm.ai/blog/2025-01-27-v1-alpha-release) ｜ [v1/engine/llm_engine.py](https://github.com/vllm-project/vllm/blob/main/vllm/v1/engine/llm_engine.py)

### Q2. EngineCore 隔离循环？
- V0.6.0 引入用 ZeroMQ IPC 的多进程 API server。
- V1 把多进程架构下沉到 AsyncLLM 核心，`EngineCore` 只管 scheduler + model executor。
- 把 tokenize / 多模态预处理 / detokenize / 流式输出 overlap 掉，最大化模型吞吐。

### Q3. LLMEngine（V1 中的遗留兼容层）？
- `vllm/v1/engine/llm_engine.py` 注释明确「Legacy LLMEngine for backwards compatibility」。
- 内部组合 `InputProcessor` + `OutputProcessor` + `EngineCoreClient`。

### Q4. Executor 选择？
- `Executor.get_class(vllm_config)` 按 `distributed_executor_backend` 选具体类。
- V1 executor 在 `vllm/v1/executor/`。
- ⚠️ prompt 所列 `GPUExecutor / RayGPUExecutor / MultiprocGPUExecutor` 为 **V0 类名**，当前 main 已迁移到 V1 executor 体系。

### Q5. Tensor Parallel 对称架构（V1 改进）？
- V0 中 scheduler 与 Worker 0 同进程以减少广播开销（非对称）。
- V1 在 worker 端缓存请求状态、每步只传增量（diffs），使 scheduler 与所有 worker 分离运行，得到对称、简洁架构。

### Q6. AsyncLLMEngine（V0）vs AsyncLLM（V1）？
- V0 异步引擎为 `AsyncLLMEngine`。
- V1 改名 `AsyncLLM`（`vllm/v1/engine/async_llm.py`），配合 `EngineCore`。

### Q7. ModelRunner V2（MRV2）？
- `docs/design/model_runner_v2.md` 描述 V1 新 model runner。
- 分离持久 CPU 状态与 copied tensor，消除 async 执行下 CPU/GPU 同时触同一内存的竞态。

### Q8. Persistent Batch（高效输入准备）？
- V0 每步重建输入张量。
- V1 缓存输入张量、每步只 apply diffs，并用 Numpy 替代 Python 原生操作降低 CPU 开销（借鉴 LMDeploy）。

---

## 六、V1 引擎（核心重构）

### Q1. 启用方式？
- `export VLLM_USE_V1=1`，无需改 API；后续成为默认引擎。

### Q2. 设计目标？
- 简单/模块化/易改的代码库。
- 近零 CPU 开销的高性能。
- 把关键优化合并到统一架构。
- 零配置（特性默认开）。

### Q3. 重写范围？
- scheduler、KV cache manager、worker、sampler、API server 全部重构。
- 但复用 V0 的模型实现、GPU kernels、分布式控制面与工具函数。

### Q4. 统一调度算法？
- 取消 prefill/decode 区分，用 `{request_id: num_tokens}` 字典表示每步调度。
- chunked prefill / prefix caching / spec decode 都在此表示上自然实现。

### Q5. 零开销 Prefix Caching（默认开启）？
- V0 的 prefix caching 低命中率时 CPU 开销大故默认关。
- V1 优化数据结构为 O(1) 驱逐、最小化 Python 对象创建。
- 命中率 0% 时吞吐下降 <1%，故 V1 **默认开启** prefix caching。

### Q6. 多模态 prefix caching？
- 除 token ID 哈希外，用 image hash 标识图像输入的 KV cache。
- 利于多轮图文对话。

### Q7. torch.compile + Piecewise CUDA Graphs？
- V1 用 torch.compile 自动优化模型，减少手写 kernel。
- 引入 piecewise CUDA graphs 缓解 CUDA graphs 的动态性限制。

### Q8. FlashAttention 3 集成？
- V1 高动态性（prefill+decode 同 batch）需要灵活且高性能的 attention kernel。
- FA3 论文：[arxiv 2407.08608](https://arxiv.org/abs/2407.08608)。

### Q9. 性能？
- 相比 V0（不含 multi-step scheduling），V1 吞吐最高 **1.7×**。
- VLM（如 Qwen2-VL）提速更明显。

### Q10. V1 移除的特性（已核实）？
- `best_of` 🔴 Removed
- Per-Request Logits Processors 🔴 Removed
- **GPU↔CPU KV Cache Swapping 🔴 Removed**
- Request-level Structured Output Backend 🔴 Removed

### Q11. V1 已支持的特性？
- Prefix Caching 🟢、Chunked Prefill 🟢、LoRA 🟢、Logprobs 🟢、FP8 KV Cache 🟢、Spec Decode 🟢、Prompt Logprobs with Prefix Caching 🟢、Structured Output 多后端 🟢。

### Q12. 硬件支持？
- V1 初版仅支持 Ampere 及以后的 NVIDIA GPU。
- TPU 等后端在扩展中。

---

## 七、量化支持

### Q1. 完整量化方法枚举（已核实）？
- `awq, auto_awq, fp8, fbgemm_fp8(已弃用), fp_quant(已弃用), modelopt, modelopt_fp4, modelopt_mxfp8, modelopt_mixed, auto_gptq, gptq, gptq_marlin, awq_marlin, humming, compressed-tensors, experts_int8, quark, moe_wna16, torchao, inc, mxfp4, gpt_oss_mxfp4, deepseek_v4_fp8, online`。
- 在线简写：`fp8_per_tensor`/`fp8_per_block`/`fp8_per_channel`/`int8_per_channel_weight_only`/`nvfp4_per_token`/`mxfp8`。
- 来源：[quantization/__init__.py](https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/layers/quantization/__init__.py)

### Q2. AWQ？
- weight-only 4-bit，通过 AutoAWQ 量化。
- 硬件：Turing/Ampere/Ada/Hopper ✅，Volta ❌，AMD ❌。

### Q3. GPTQ？
- 4-bit post-training，用 GPTQModel。
- 硬件：Volta 起全支持（含 Intel GPU/x86 CPU ✅）。

### Q4. FP8（W8A8）？
- 动态量化无需校准数据。
- 硬件：**Ada (SM8.9) + Hopper (SM9.0)** ✅，AMD GPU ✅；Ampere 及更早 ❌。

### Q5. Marlin kernel（混合精度 GEMM）？
- 不是量化方法，是统一服务 GPTQ/AWQ/FP8/FP4 的低精度线性 kernel。
- 硬件：Turing*/Ampere/Ada/Hopper ✅（*Turing 不支持 Marlin MXFP4），AMD/Intel/CPU ❌。

### Q6. Machete kernel（Hopper 专用）？
- 基于 CUTLASS wgmma，**仅 Hopper (sm90a) + CUDA ≥12.0** 才编译。
- CMake 中 `cuda_archs_loose_intersection(MACHETE_ARCHS "9.0a" ...)`。
- 支持 uint4/uint8（带/不带 zero point）。

### Q7. bitsandbytes？
- NF4/4-bit。配置类 `BitsAndBytesConfig`。
- 硬件：**Volta 起所有 NVIDIA GPU 全支持**，AMD ❌。

### Q8. INT8 / SmoothQuant 路径？
- 通过 llm-compressor 的 INT8（W8A8 / W4A8）实现，非独立「SmoothQuant」方法名。
- W8A8 支持 Turing+；W4A8 仅 Arm CPU ✅。
- INC（Intel Neural Compressor）作为 `inc` 方法支持 INT4。

### Q9. DeepSeek FP8？
- ⚠️ **关键纠错**：vLLM **没有** `--quantization deepseek_fp8` 方法。
- DeepSeek-V3/R1 的 FP8 权重走 `--quantization fp8`（靠 checkpoint 里的 `weight_block_size: [128, 128]` 字段触发 block 量化路径）。
- vLLM 有 `deepseek_v4_fp8` 方法（`DeepseekV4FP8Config`），用于更新的 V4 模型。

### Q10. SM 代号对照？
- Volta=SM7.0、Turing=SM7.5、Ampere=SM8.0/8.6、Ada=SM8.9、Hopper=SM9.0。

### Q11. 插件机制？
- 用 `@register_quantization_config("my_quant")` 注册树外量化方法，无需改 vLLM 代码。

---

## 八、采样

### Q1. SamplingParams 核心字段？
- `temperature`、`top_p`、`top_k`、`min_p`、`repetition_penalty`、`length_penalty`（默认 1.0）、`stop_token_ids`、`max_tokens`、`n`、`use_beam_search`、`structured_outputs`。
- 来源：[completion/protocol.py](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/completion/protocol.py)

### Q2. Beam Search？
- `use_beam_search=True`；`request.to_beam_search_params(...)` 转换为 `BeamSearchParams`。
- 流式不支持 beam search（`stream + use_beam_search` 报错）。

### Q3. best_of？
- ⚠️ **V1 已移除**（`best_of 🔴 Removed`）。
- V0 支持；V1 改用 `n`（并行采样）等替代。

### Q4. 结构化输出后端（已核实）？
- `StructuredOutputsBackend` Literal：`"auto" | "xgrammar" | "guidance" | "outlines" | "lm-format-enforcer"`。
- 默认 `auto` 按请求细节选择。

### Q5. xgrammar？
- `XgrammarBackend`，默认后端之一。
- 支持 JSON schema、regex、grammar、choice、structural_tag。

### Q6. outlines？
- `OutlinesBackend`，基于 `outlines_core`。
- 有可选磁盘缓存（`VLLM_V1_USE_OUTLINES_CACHE`，默认关，多租户不安全）。

### Q7. guidance / lm-format-enforcer？
- `GuidanceBackend`（基于 llguidance/Lark）。
- `LMFormatEnforcerBackend`（用 Python `re`）。
- 非 tekken Mistral tokenizer 不支持 guidance。

### Q8. 结构化输出参数（StructuredOutputsParams）？
- `json`、`regex`、`choice`、`grammar`、`structural_tag`、`whitespace_pattern`。
- 旧 `guided_*` 字段在 v0.12.0 移除，改用 `structured_outputs`。

### Q9. 投机解码方法全集（已核实）？
- **EAGLE**、**MTP（Multi-Token Prediction）**、**Draft Model**、**PARD（Parallel Draft Model）**、**MLP**、**N-Gram**、**Suffix Decoding**、**Hidden State Extraction**、**Custom Proposer（实验）**、**Dynamic Speculative Decoding**。
- 来源：[docs spec_decode](https://docs.vllm.ai/en/stable/features/speculative_decoding/)

### Q10. EAGLE？
- `method: "eagle"`（含 EAGLE3），proposer 类 `EagleProposer`。
- 支持 `parallel_drafting`、动态 spec。

### Q11. MTP？
- `method: "mtp"`，`Step3p5MTPProposer` 继承 `EagleProposer`。
- 适合目标模型原生支持 MTP（如 MiMo-7B、Gemma4 assistant）。

### Q12. ⚠️ 关于 "lookahead"？
- vLLM 当前 spec decode 方法表中**没有名为 "lookahead" 的方法**。
- 早期版本曾有 "Lookahead Decoding"，现更名为 **"N-Gram"**（n-gram / prompt lookup）。
- 面试中若被问 lookahead，应澄清现在叫 N-Gram。

---

## 九、一页速记卡

| 类别 | 必背 |
|---|---|
| PagedAttention | 类比 OS 分页；block 默认 16（CPU=128）；block table 逻辑↔物理映射 |
| Continuous Batching | iteration-level 调度；V0 三队列 waiting/running/swapped；V1 简化为 waiting/running + skipped |
| Preemption | recompute vs swap；V1 已移除 GPU↔CPU swap |
| Chunked Prefill | V1 默认开；max_num_batched_tokens V1=2048/V0=512；decode 优先 |
| V1 引擎 | EngineCore 隔离循环；统一调度 {req_id: tokens}；prefix caching 默认开；torch.compile + piecewise CUDA graphs；FA3 |
| Worker/Executor | AsyncLLM → EngineCore → Executor → Worker → ModelRunner；TP 对称架构 |
| V1 移除 | best_of、Per-Request Logits、CPU KV swap、Request-level Structured Backend |
| 量化方法 | awq/gptq/fp8/bitsandbytes/compressed-tensors/quark/mxfp4 等 |
| Marlin/Machete | Marlin=Turing+ 通用混合精度 GEMM；Machete=Hopper sm90a 专用 |
| DeepSeek FP8 | ⚠️ 用 `--quantization fp8`（无 deepseek_fp8 方法！）；V4 才有 deepseek_v4_fp8 |
| 采样 | top-k/top-p/temperature/n/beam_search；V1 移除 best_of |
| 结构化输出 | auto/xgrammar/guidance/outlines/lm-format-enforcer |
| 投机解码 | EAGLE/MTP/Draft Model/PARD/N-Gram/Suffix/Dynamic；无 "lookahead"（已改名 N-Gram） |
