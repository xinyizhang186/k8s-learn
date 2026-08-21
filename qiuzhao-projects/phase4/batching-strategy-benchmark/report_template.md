# 调优报告模板

> 用 `analyze_results.py --input results.json --output tuning_report.md` 自动生成

## 模板结构

```markdown
# vLLM Batching 策略调优报告

## 1. 实验环境
- 模型：Qwen3-7B
- 硬件：Atlas 800T A2（8×910B）/ NVIDIA H100 × 8
- 数据集：ShareGPT（avg input 350, output 200 tokens）
- 测试时间：2026-XX-XX

## 2. 策略对比

| 策略 | max_num_seqs | max_num_batched_tokens | chunked_prefill | 并发 | 吞吐(tok/s) | P50延迟 | P95延迟 | 成功率 |
|---|---|---|---|---|---|---|---|---|
| baseline | 128 | 2048 | True | 20 | 1500 | 1.2s | 3.5s | 98% |
| large_batch | 256 | 8192 | True | 50 | 2100 | 2.1s | 6.8s | 96% |
| small_batch | 32 | 1024 | True | 5 | 800 | 0.4s | 1.0s | 100% |
| chunked_prefill | 128 | 4096 | True | 20 | 1700 | 1.0s | 2.8s | 99% |

## 3. 详细分析

### baseline
- 总请求：200，成功：196，失败：4
- 延迟均值：1.3s，中位数 1.2s
- 吞吐：1500 tok/s

### large_batch
- ...
（每策略一段）

## 4. 结论与建议
- 吞吐最高：large_batch（+40%）
- 延迟最低：small_batch（-66% P50）
- 综合最优：baseline 或 chunked_prefill

## 5. 调优旋钮速查
（参数表）
```

## 完整流程示例

```bash
# 1. 用 baseline 配置启动 vllm
vllm serve /models/Qwen3-7B --max-num-seqs 128 --max-num-batched-tokens 2048 &

# 2. 等 health 就绪
curl http://localhost:8000/health

# 3. 跑 benchmark（baseline）
python benchmark_strategies.py --configs configs/baseline.json

# 4. kill 旧服务，启动 large_batch 配置
kill -2 $(pgrep -f "vllm serve")
vllm serve /models/Qwen3-7B --max-num-seqs 256 --max-num-batched-tokens 8192 &

# 5. 跑 benchmark（large_batch）
python benchmark_strategies.py --configs configs/large_batch.json

# 6. 合并多次运行结果
# （benchmark_strategies.py 支持多 config 一次跑，会输出到同一 results.json）

# 7. 生成报告
python analyze_results.py --input reports/results.json --output reports/tuning_report.md
```

## 注意事项

1. **每次只测一个策略**：同一服务实例不能动态改 `max_num_seqs` 等参数，必须重启。
2. **预热**：首请求冷启动慢，前 10 个请求不计入统计。
3. **多次取均值**：每策略至少跑 3 次，剔除异常。
4. **监控 GPU/NPU**：压测时同时记录 `nvidia-smi dmon` / `npu-smi info`，便于瓶颈分析。
5. **数据集代表性**：用真实业务分布的 prompt，长尾 prompt 对结果影响大。
