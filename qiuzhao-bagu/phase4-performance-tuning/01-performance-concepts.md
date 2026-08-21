# 推理性能调优 - 性能概念八股速记

> 适用范围：秋招 AI Infra 岗位（推理框架方向）
> 涵盖：性能指标 / 屋顶线模型 / MFU / 显存预算 / 调优手段

---

## 一、核心性能指标

### Q1. TTFT / TPOT / Throughput / Latency 详解？
| 指标 | 全称 | 含义 | 主要由什么决定 |
|---|---|---|---|
| **TTFT** | Time To First Token | 从请求到收到第一个 token 的延迟 | Prefill 阶段（compute-bound） |
| **TPOT** | Time Per Output Token | Decode 阶段每 token 的平均时间 | Decode 阶段（memory-bound） |
| **e2e Latency** | End-to-End Latency | TTFT + (N-1) × TPOT | 整体响应时间 |
| **Throughput** | tokens/sec | 单位时间生成 token 数 | GPU 利用率 |
| **QPS** | Requests/sec | 单位时间完成请求数 | Throughput / avg_tokens_per_request |

### Q2. 三者之间的 tradeoff？
- **大 batch → 吞吐↑ 但 TPOT↑**（每请求变慢，因为 attention 计算量随 batch 增长）。
- **小 batch → 延迟↓ 但吞吐↓**（GPU 利用率低）。
- **TTFT vs Throughput**：长 prompt prefill 占算力大，prefill 时其他请求 decode 卡顿 → ITL 尖峰（chunked prefill 缓解）。
- 不能同时优化三个，要根据业务取舍：
  - 实时对话：TTFT < 500ms，TPOT < 50ms。
  - 批量任务：吞吐优先，可接受高延迟。
  - 代码补全：低 TTFT + 低 TPOT。

### Q3. 实测指标怎么算？
```bash
# vLLM 自带 benchmark
python benchmarks/benchmark_throughput.py \
  --model /models/qwen2-7b \
  --backend vllm \
  --dataset datasets/sharegpt.json \
  --num-prompts 1000

# 在线 serving benchmark
python benchmarks/benchmark_serving.py \
  --model /models/qwen2-7b \
  --dataset datasets/sharegpt.json \
  --num-prompts 1000 \
  --rate 10  # 请求速率 RPS
```

### Q4. 不同请求率（rate）下的指标含义？
- **rate=0**（无并发，串行）：测纯单请求 latency。
- **rate=低**：测 cold start TTFT，无排队。
- **rate=中**：测稳定吞吐，可能有轻排队。
- **rate=高（饱和）**：系统过载，吞吐封顶，延迟飙升——找拐点（knee point）。
- 报告时应给不同 rate 下的吞吐/延迟曲线，而非单点。

---

## 二、屋顶线模型（Roofline）

### Q5. 屋顶线模型是什么？
- 横轴：**算术强度**（Arithmetic Intensity, AI = FLOPs / Bytes）。
- 纵轴：**吞吐**（FLOP/s）。
- 两条线：
  - 内存带宽线：`Throughput = AI × Bandwidth`（斜线，AI 小时是瓶颈）。
  - 算力峰值线：`Throughput = Peak FLOP/s`（水平线，AI 大时是瓶颈）。
- 交点拐点（ridge point）：`AI_ridge = Peak FLOP/s / Bandwidth`。

### Q6. 主流 GPU/NPU 的拐点？
| 硬件 | Peak FP16 (TFLOPS) | HBM Bandwidth (TB/s) | Ridge AI (FLOP/Byte) |
|---|---|---|---|
| A100 80GB | 312 | 2.0 | 156 |
| H100 80GB | 990 | 3.35 | 296 |
| H200 141GB | 990 | 4.8 | 206 |
| B200 | 2250 | 8.0 | 281 |
| MI300X | 1307 | 5.3 | 247 |
| 910B | 400 | 1.6 | 250 |
| 910C | 800 | 3.2 | 250 |

### Q7. LLM 推理的算术强度？
- **Prefill**：算术强度 = `2 × N² × d / (N × d × dtype_size) ≈ 2N / dtype_size`。N=4096、FP16 → AI ≈ 4096，远超 ridge point → **compute-bound**，跑满算力。
- **Decode**：算术强度 = `2 × d_model / (2 × d_model × dtype_size) ≈ 1/dtype_size`。FP16 → AI ≈ 0.5，远低于 ridge → **memory-bound**，算力利用率 < 1%。

### Q8. 为什么 decode 时 GPU 利用率低？
- decode 是 memory-bound，算力跑不满。
- 单请求 decode，权重读取一遍只算 1 token → 算力浪费 99%+。
- 解决方案：
  - **Continuous Batching**：多请求 decode 拼批，权重读取摊薄到多 token。
  - **Speculative Decoding**：一次 verify 多个 token，prefill 量↑。
  - **Chunked Prefill**：decode 间隙塞 prefill chunk，提高算力利用率。

### Q9. MFU（Model FLOPs Utilization）是什么？
- `MFU = 实测 FLOP/s / 理论 Peak FLOP/s`
- 训练时 MFU 50-60% 算优秀（含 optimizer 状态、通信开销）。
- 推理 prefill MFU 30-50%（受 attention/通信限制）。
- 推理 decode 单请求 MFU < 1%（memory-bound）；continuous batching 后 10-30%。

### Q10. 如何测 FLOPs？
- 工具：`torch profiler` / Nsight Systems / `nvidia-smi dmon` / `msprof` / `npu-smi info`。
- 公式估算（Transformer）：
  - Prefill FLOPs ≈ `2 × batch × seq² × d_model × 2 × n_layers`（attention）+ `2 × batch × seq × d_model × hidden_ff × 2 × n_layers`（FFN）。
  - Decode FLOPs ≈ `2 × batch × seq × d_model × 2 × n_layers` + `2 × batch × d_model × hidden_ff × 2 × n_layers`。

---

## 三、显存预算

### Q11. LLM 推理显存占用组成？
```
Total GPU Memory
├── Weights（权重）        ≈ params × dtype_size（FP16: 2B params = 4GB）
├── KV cache               ≈ 2 × n_layers × n_heads × head_dim × seq_len × batch × dtype_size
├── Activations（中间层）   prefill 时大，decode 时小
├── Workspace（kernel）    100MB-1GB
└── Framework overhead    PyTorch caching allocator 等
```

### Q12. KV cache 大小估算示例？
- Llama-7B：n_layers=32、n_heads=32、head_dim=128、seq=2048、FP16、batch=1。
- KV cache = 2 × 32 × 32 × 128 × 2048 × 1 × 2 = 1GB（单请求）。
- Llama-70B：n_layers=80、n_heads=64、head_dim=128、seq=4096、batch=8。
- KV cache = 2 × 80 × 64 × 128 × 4096 × 8 × 2 = **170GB**（远超 80GB 单卡）。
- 这就是 PagedAttention / TP / KV 量化的动机。

### Q13. `gpu-memory-utilization` 参数？
- vLLM `--gpu-memory-utilization 0.9`：使用 90% 显存，10% 留给 PyTorch allocator 缓存。
- 值越大 KV cache 越大、能并发更多请求；但接近 100% 时易 OOM。
- 推理框架预留 buffer 应付 attention workspace 等 spike。
- 推荐值：0.85-0.95。

### Q14. 显存不足怎么办？
1. **减小 batch / seq**：最直接。
2. **量化权重**：FP16→INT4 减 4 倍。
3. **量化 KV cache**：`--kv-cache-dtype fp8` 减半。
4. **TP**：权重切到多卡。
5. **PP**：layer 切到多卡（少用，有 bubble）。
6. **KV cache offload**：换出到 CPU/SSD（vLLM sleep mode / LMCache）。
7. **减少 n_layers/head**：换小模型。
8. **GQA / MLA**：减少 KV cache 头数（Llama-3 用 GQA 8 KV head vs 32 Q head）。

---

## 四、调优手段

### Q15. vLLM 调优旋钮清单？
| 参数 | 作用 | 调优建议 |
|---|---|---|
| `--tensor-parallel-size` | TP 数 | 单机 8 卡可设 8；跨机建议 TP=8 + DP |
| `--gpu-memory-utilization` | 显存使用率 | 0.85-0.95，留 buffer |
| `--max-model-len` | 最大序列长度 | 按业务设，过大吃 KV cache |
| `--max-num-seqs` | 最大并发请求数 | 默认 128；高并发调大 |
| `--max-num-batched-tokens` | 每 step token 预算 | chunked prefill 关键旋钮 |
| `--block-size` | PagedAttention 块大小 | 默认 16；Ascend 推荐 128 |
| `--enable-prefix-caching` | 前缀缓存 | V1 默认开 |
| `--enable-chunked-prefill` | 分块 prefill | V1 默认开 |
| `--kv-cache-dtype` | KV cache 量化 | fp8 减半 |
| `--quantization` | 权重量化 | fp8/awq/gptq |
| `--speculative-config` | 投机解码 | eagle/mtp/n-gram |
| `--gpu-memory-utilization` | 显存使用率 | 0.9 常用 |
| `--enforce-eager` | 关 cudagraph | 调试时用 |
| `--compilation-config` | torch.compile 配置 | `{"cudagraph_mode":"FULL_DECODE_ONLY"}` |

### Q16. 吞吐 vs 延迟优先的配置差异？
| 维度 | 吞吐优先 | 延迟优先 |
|---|---|---|
| `max-num-seqs` | 大（256+） | 小（32-64） |
| `max-num-batched-tokens` | 大（8192+） | 中（2048） |
| Chunked Prefill | 开 | 开（防 TTFT 抖动） |
| Prefix Caching | 开 | 开 |
| Spec Decode | 视任务 | eagle 适合代码 |
| TP | 大（8） | 中（4，平衡通信） |
| Quantization | INT4/FP8 | FP8（精度好） |

### Q17. 性能瓶颈定位流程？
1. `nvidia-smi dmon` / `npu-smi info`：GPU 利用率、显存占用。
2. `torch profiler` / `msprof`：算子级耗时、CPU/GPU overlap。
3. `nsys profile` / `msprof`：timeline 看 CPU launch 与 GPU kernel 是否重叠。
4. 看 `op_summary.csv`：哪类算子占大头（attention/FFN/通信）。
5. 看 NCCL/HCCL 统计：通信占比（TP 大时通信可能成瓶颈）。
6. 看内存带宽：decode 时是否打满 HBM 带宽。
7. 看 kernel launch overhead：小算子多时 CPU launch 成瓶颈（cudagraph 解决）。

### Q18. CUDA Graph / ACLGraph 何时有用？
- 小 batch + 多小算子时 CPU launch overhead 大（每 kernel ~5μs）。
- Graph 把整段 kernel 调用录制成一个 graph，replay 时单次 launch。
- 节省 10-30% latency（小 batch 显著，大 batch 几乎无影响）。
- 限制：动态 shape 不友好（需多个 graph 分别 capture 不同 size）。
- vLLM：`--compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'`。
- vllm_ascend：ACLGraph，等价 CUDA Graph。

### Q19. 通信隐藏（compute-comm overlap）？
- TP 时每层 Linear 后跟 all-reduce，若不重叠通信与计算，通信占用 20-40%。
- 重叠技巧：
  - **NCCL/HCCL 异步**：`all_reduce(...async_op=True)`，下一段 Linear 同时计算。
  - **Fused MoE**：把 MoE 的 all-to-all 与 FFN 融合。
  - **stream 优先级**：把通信 stream 提优先级。
- vLLM V1 在 worker 端做 async scheduling，可隐藏通信。

### Q20. vllm_ascend 特有调优点？
- `--block-size 128`（不是 16，昇腾 Cube Unit 大）。
- `--quantization ascend`（W8A8 量化）。
- `--compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'`（ACLGraph）。
- `export TASK_QUEUE_ENABLE=1`（task queue 优化）。
- `export HCCL_OP_EXPANSION_MODE="AIV"`（HCCL 用 AIV 算子）。
- `export VLLM_ASCEND_ENABLE_FUSED_MC2=1`（MC2 通信融合）。
- `export VLLM_ASCEND_ENABLE_MLAPO=1`（DeepSeek MLAPO 优化）。
- `export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True`（显存策略）。
- `--async-scheduling`（异步调度）。
- `--enable-flashcomm1`（FlashComm，via additional_config）。

---

## 五、压测方法论

### Q21. 压测如何设计？
1. **数据集**：用真实业务分布（如 ShareGPT 对话）而非随机 prompt。
2. **请求率（rate）**：从低到高扫，找拐点。
3. **prompt/output 长度分布**：要 representative，长尾影响大。
4. **预热**：先发少量请求 warmup，避免冷启动影响。
5. **持续时长**：至少 5-10 分钟稳态才测得准。
6. **多次取均值**：跑 3 次取平均，剔除异常。
7. **监控**：GPU 利用率、显存、温度、功率一并记录。

### Q22. 输出调优报告模板？
```
# 调优报告：<模型>/<硬件>

## 1. 基线
- 模型：Qwen2.5-7B-Instruct
- 硬件：Atlas 800T A2（8×910B）
- 配置：TP=4, max-num-seqs=128, block-size=128
- 数据集：ShareGPT (avg input 350, output 200 tokens)
- 结果：吞吐 1500 tok/s, TPOT 80ms, TTFT 1.2s

## 2. 瓶颈分析
- GPU 利用率 65%（瓶颈在 attention + 通信）
- 通信占比 22%（TP=4 时 all-reduce）
- KV cache 显存 25GB，未占满

## 3. 调优实验
| 实验 | 改动 | 吞吐 | TPOT | TTFT |
|---|---|---|---|---|
| 基线 | - | 1500 | 80 | 1.2 |
| +chunked prefill | max_num_batched_tokens=4096 | 1650 | 75 | 0.9 |
| +FP8 KV cache | --kv-cache-dtype fp8 | 1720 | 73 | 0.85 |
| +ACLGraph | cudagraph_mode=FULL_DECODE_ONLY | 1800 | 65 | 0.85 |
| +W8A8 量化 | --quantization ascend | 2100 | 55 | 0.7 |

## 4. 最优配置
TP=4, max-num-seqs=128, block-size=128, FP8 KV, W8A8, ACLGraph
吞吐 2100 tok/s（提升 40%）, TPOT 55ms, TTFT 0.7s

## 5. 残留瓶颈
- decode 仍 memory-bound，可考虑 PD 分离 + KV transfer
- 通信 18%（HCCL Ring 可换 HD 算法）
```

---

## 六、一页速记卡

| 类别 | 必背 |
|---|---|
| 核心指标 | TTFT（首 token 延迟）/ TPOT（每 token 时间）/ 吞吐 / QPS |
| Tradeoff | 大 batch → 吞吐↑ TPOT↑；不能同时优化所有指标 |
| 屋顶线 | AI=FLOP/Byte；prefill compute-bound；decode memory-bound |
| H100 ridge | ~296 FLOP/Byte；decode AI≈0.5，远低于 ridge → 算力浪费 |
| MFU | 实测/理论；训练 50-60%、prefill 30-50%、decode 单请求 <1% |
| 显存预算 | 权重 + KV cache + activations + workspace + overhead |
| KV cache 公式 | 2 × layers × heads × head_dim × seq × batch × dtype |
| gpu-memory-utilization | 0.85-0.95 留 buffer |
| 调优旋钮 | TP/max-num-seqs/max-num-batched-tokens/quantization/spec-decode |
| 瓶颈定位 | nvidia-smi → profiler → op_summary → NCCL stats → bandwidth |
| CUDA Graph | 小 batch CPU launch overhead 大时有用；动态 shape 限制 |
| 通信隐藏 | async all-reduce + stream 优先级 + fused MoE |
| Ascend 调优 | block-size=128/quantization ascend/ACLGraph/TASK_QUEUE_ENABLE |
| 压测 | 真实数据 + 扫 rate + 预热 + 稳态 + 多次取均值 |
