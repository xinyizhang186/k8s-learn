# Multi-Card LLM Inference Service

部署一个多卡 LLM 推理服务（vLLM TP/PP），支持并发请求，并附带压测脚本。

## 项目结构

```
multicard-llm-service/
├── README.md              # 本文件
├── requirements.txt       # 依赖
├── deploy/
│   ├── tp_deploy.sh       # Tensor Parallel 部署脚本（推荐）
│   ├── pp_deploy.sh       # Pipeline Parallel 部署脚本
│   └── docker-compose.yml # Docker Compose 多卡部署
├── server/
│   ├── start_server.py    # vLLM 服务启动入口（Python API）
│   └── health_server.py   # 简易健康检查 + 状态服务
├── client/
│   ├── async_client.py    # 异步并发客户端（asyncio）
│   ├── benchmark.py        # 压测脚本（吞吐 + 延迟）
│   └── load_generator.py  # 多种负载模式（恒定/爆发/渐进）
└── docs/
    └── TUNING_GUIDE.md    # 调优指南
```

## 快速开始

### 1. 启动多卡服务（NVIDIA GPU，TP=4）

```bash
bash deploy/tp_deploy.sh /models/Llama-3-8B 4
```

### 2. 启动多卡服务（昇腾 NPU，TP=4）

```bash
bash deploy/tp_deploy.sh /models/Qwen3-7B 4 --device npu
```

### 3. 压测

```bash
# 并发 20 请求，持续 60 秒
python client/benchmark.py --host localhost --port 8000 \
  --concurrent 20 --duration 60 --rate 10

# 输出报告：
#   Throughput: 1520 tokens/s
#   P50 latency: 1.2s, P99 latency: 3.5s
#   Success rate: 98%
```

## TP vs PP 选择

| 场景 | 推荐 | 理由 |
|---|---|---|
| 单机多卡 | TP | 通信快（NVLink/HCCS），无 bubble |
| 跨机多节点 | PP（或 TP+PP 混合） | 跨机 TP 通信慢，PP 通信量小 |
| 模型层多（Llama-70B 80层） | PP | 切分灵活 |
| 极致吞吐 | TP + DP | 多副本数据并行 |
| 显存不够但卡少 | PP | 单卡装不下权重，PP 切 layer |

## 关键性能指标

- **TTFT**（首 token 延迟）：prefill 时间
- **TPOT**（每 token 时间）：decode 速度
- **Throughput**（tokens/sec）：整体吞吐
- **QPS**（requests/sec）：请求处理速率
- **P99 latency**：99 分位延迟
- **Success rate**：成功率
