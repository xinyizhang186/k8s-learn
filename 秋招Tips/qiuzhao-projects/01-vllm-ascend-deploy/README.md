# vllm_ascend Deploy - 部署大模型推理服务

搭建个人开发环境，运行第一个 vllm_ascend 容器，部署大模型（Qwen3 系列）。

## 项目结构

```
01-vllm-ascend-deploy/
├── README.md                  # 本文件
├── Dockerfile                 # 自定义镜像（基于官方 quay.io/ascend/vllm-ascend）
├── docker-compose.yml         # 一键启动容器
├── scripts/
│   ├── start_service.sh       # 启动 vllm serve（单卡/多卡 TP）
│   ├── start_service_multi.sh # 多卡 TP=4 启动脚本（含 HCCL 环境变量）
│   ├── health_check.sh        # 健康检查
│   └── stop_service.sh        # 停止服务
├── client/
│   ├── client_test.py         # OpenAI 兼容 API 客户端测试
│   └── benchmark_client.py    # 简单压测客户端
├── configs/
│   └── qwen3-7b-args.json     # Qwen3-7B 推理参数配置
└── docs/
    ├── TROUBLESHOOTING.md     # 常见问题排查
    └── ENV_VARS.md            # 关键环境变量速查
```

## 快速开始

### 前置：宿主机安装昇腾驱动 + CANN（Docker 镜像已含 CANN，宿主只需 driver）

```bash
# 检查 NPU 可见
npu-smi info
# 输出应有 8 张卡（Atlas 800T A2）
```

### 步骤 1：拉取官方镜像

```bash
# v0.23.0（最新稳定版，2026-08 发布，对齐 vLLM v0.23.0）
docker pull quay.io/ascend/vllm-ascend:v0.23.0
# 或 openEuler 变体
docker pull quay.io/ascend/vllm-ascend:v0.23.0-openeuler
```

### 步骤 2：启动服务（单卡最小示例）

```bash
bash scripts/start_service.sh
# 输出日志：
#   Platform plugin ascend is activated
#   INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 步骤 3：测试

```bash
# 健康检查
curl http://localhost:8000/health

# OpenAI 兼容 API
python client/client_test.py

# 简单压测
python client/benchmark_client.py --num-requests 100 --rate 5
```

### 步骤 4：多卡部署（TP=4）

```bash
bash scripts/start_service_multi.sh
```

## 关键命令模板

### 单卡 Qwen3-0.6B
```bash
vllm serve Qwen/Qwen3-0.6B --port 8000
```

### 4 卡 TP=4 Qwen3-7B
```bash
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

## 注意事项

- **无需 `--device npu`**：vllm_ascend 插件自动激活（日志 `Platform plugin ascend is activated`）。
- **`/dev/shm` 太小**：默认 64MB 会让 HCCL 通信失败，必须 `--shm-size=16g`。
- **CANN 必须宿主装 driver + 容器内装 CANN/NNAL**：官方镜像已含，自建 Dockerfile 要 source `set_env.sh`。
- **停止服务**：用 `kill -2 $(pgrep -f "vllm serve")`（SIGINT 让 vLLM 优雅退出），不要 `kill -9`。

## 详细文档

- [环境变量速查](docs/ENV_VARS.md)
- [常见问题排查](docs/TROUBLESHOOTING.md)
