# Batching Strategy Benchmark

对比不同 Batching 策略（batch size / max-num-batched-tokens / max-num-seqs）下的吞吐量，输出调优报告。

## 项目结构

```
batching-strategy-benchmark/
├── README.md                # 本文件
├── requirements.txt
├── configs/
│   ├── baseline.json        # 基线配置
│   ├── large_batch.json     # 大 batch 策略
│   ├── small_batch.json     # 小 batch 策略
│   └── chunked_prefill.json # chunked prefill 优化策略
├── benchmark_strategies.py # 主脚本：对比不同策略
├── analyze_results.py       # 分析结果，输出 markdown 报告
├── report_template.md       # 调优报告模板
└── reports/                 # 生成的报告（运行后产生）
```

## 快速开始

### 1. 启动基线服务
```bash
vllm serve /models/Qwen3-7B --served-model-name qwen3 \
    --max-num-seqs 128 --max-num-batched-tokens 2048
```

### 2. 跑对比实验
```bash
python benchmark_strategies.py --host localhost --port 8000 \
    --model qwen3 --num-requests 200 --concurrent 20
```

### 3. 生成报告
```bash
python analyze_results.py --input reports/results.json --output reports/tuning_report.md
```

## 测试的策略矩阵

| 策略 | max-num-seqs | max-num-batched-tokens | enable-chunked-prefill | 适合场景 |
|---|---|---|---|---|
| baseline | 128 | 2048 | True | 通用基线 |
| large_batch | 256 | 8192 | True | 高吞吐 |
| small_batch | 32 | 1024 | True | 低延迟 |
| no_chunked | 128 | 2048 | False | 对照组 |
| eager_mode | 128 | 2048 | True + enforce-eager | 调试/对照 |

## 输出报告示例

```markdown
# 调优报告：Qwen3-7B / Atlas 800T A2

## 1. 实验环境
- 模型：Qwen3-7B
- 硬件：Atlas 800T A2（8×910B）
- 数据集：ShareGPT (avg input 350, output 200 tokens)

## 2. 结果对比
| 策略 | 吞吐(tok/s) | P50延迟 | P99延迟 | 成功率 |
|---|---|---|---|---|
| baseline | 1500 | 1.2s | 3.5s | 98% |
| large_batch | 2100 | 2.1s | 6.8s | 96% |
| small_batch | 800 | 0.4s | 1.0s | 100% |

## 3. 结论
- 吞吐优先：large_batch（+40%）
- 延迟优先：small_batch（-66% P50）
- 综合最优：baseline
```
