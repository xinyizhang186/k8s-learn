# 调优指南

## 1. 性能瓶颈定位流程

```
请求慢/OOM
    ↓
nvidia-smi / npu-smi info
    ├── GPU 利用率低 (<30%) → CPU/IO 瓶颈 → cudagraph / 减少 Python 开销
    ├── GPU 利用率高但慢 → 算力/带宽瓶颈 → 量化 / TP / 更大 batch
    └── 显存满 → OOM → 减 batch / 量化 / KV offload
```

## 2. 常见调优场景

### 场景 A：吞吐不够（批量处理）
```bash
vllm serve model \
    --max-num-seqs 256 \           # ↑ 并发
    --max-num-batched-tokens 8192 \ # ↑ token 预算
    --enable-chunked-prefill \     # 允许 prefill+decode 混批
    --enable-prefix-caching \      # 重复 prompt 命中
    --quantization fp8 \           # W8A8 加速
    --kv-cache-dtype fp8           # KV 减半
```

### 场景 B：延迟太高（实时对话）
```bash
vllm serve model \
    --max-num-seqs 32 \             # ↓ 减少排队
    --max-num-batched-tokens 1024 \ # ↓ 减少单步计算
    --enable-chunked-prefill \     # 防 TTFT 抖动
    --tensor-parallel-size 4       # 多卡分摊（减延迟 + 减显存）
```

### 场景 C：显存不够（OOM）
```bash
vllm serve model \
    --gpu-memory-utilization 0.85 \ # 留更多 buffer
    --max-model-len 4096 \          # ↓ 减 KV cache
    --max-num-seqs 64 \             # ↓ 减并发
    --quantization ascend \         # W8A8 减权重
    --kv-cache-dtype fp8 \          # KV 减半
    --tensor-parallel-size 4        # 多卡分摊
```

### 场景 D：代码补全（低延迟 + 投机解码）
```bash
vllm serve model \
    --max-num-seqs 32 \
    --enable-prefix-caching \       # 前缀命中（同文件补全）
    --speculative-config '{"method":"eagle","model":"/models/eagle-draft","num_speculative_tokens":3}'
```

## 3. NPU 特有调优

```bash
# 昇腾 NPU 关键环境变量
export TASK_QUEUE_ENABLE=1
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=200
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export VLLM_ASCEND_ENABLE_MLAPO=1          # DeepSeek W8A8 优化
export VLLM_ASCEND_ENABLE_FUSED_MC2=1      # MC2 通信融合

# 启动参数
vllm serve model \
    --block-size 128 \                       # NPU 推荐 128（非 GPU 的 16）
    --quantization ascend \                   # W8A8
    --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}' \  # ACLGraph
    --async-scheduling \                       # 异步调度
    --tensor-parallel-size 4 \                # TP=4
    --distributed-executor-backend mp         # 多进程后端
```

## 4. Profiling 流程

### NVIDIA GPU
```bash
# 1. 启动服务
vllm serve model --port 8000 &

# 2. 发请求触发 profiling
python client/benchmark.py --duration 30

# 3. 同时采集 nsys trace
nsys profile -t cuda,nvtx,osrt,cudnn,cublas \
    -o profile_trace --force-overwrite=true \
    -p "vllm" --duration=30

# 4. 分析
nsys stats profile_trace.nsys-rep
# 或用 Nsight Systems GUI 打开
```

### 昇腾 NPU
```bash
# 1. msprof 命令行采集
msprof --application="python benchmark.py --duration 30" \
    --output=./prof_data \
    --aic-metrics=ArithmeticUtilization \
    --sys-hardware-mem

# 2. 或用 torch_npu.profiler 在代码中采集
# from torch_npu.profiler import profile, ProfilerActivity
# with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.NPU]) as prof:
#     model.generate(...)
# prof.export_chrome_trace("trace.json")

# 3. 分析输出
# - op_summary_*.csv：算子级耗时
# - trace_view.json：时间线
# - op_statistic_*.csv：按算子类型聚合
```

## 5. 关键指标对照

| 指标 | 理想值 | 说明 |
|---|---|---|
| GPU 利用率 | >80%（prefill），30-50%（decode batched） | 低 → CPU/IO 瓶颈 |
| 显存利用率 | 85-95% | 太低浪费，太高易 OOM |
| MFU（模型算力利用率） | 训练 50-60%，prefill 30-50% | decode 单请求 <1% |
| 通信占比 | <20% | 高 → TP 过大或通信未隐藏 |
| P99/P50 延迟比 | <3× | 高 → 有长尾（排队/抢占） |
| 成功率 | >99% | 低 → 过载或 OOM |

## 6. 调优 Checklist

- [ ] 确认硬件状态（`nvidia-smi` / `npu-smi info`）
- [ ] 基线测试（默认参数，记录吞吐/延迟）
- [ ] 调整 `max-num-seqs` + `max-num-batched-tokens`
- [ ] 开启 `chunked-prefill` + `prefix-caching`
- [ ] 尝试量化（fp8 / ascend）
- [ ] 尝试 KV cache 量化
- [ ] 尝试 TP（从 2 开始，到 8 饱和）
- [ ] 尝试投机解码（eagle / mtp）
- [ ] 开启 cudagraph / ACLGraph
- [ ] Profiling 找瓶颈
- [ ] 多策略对比，输出调优报告
