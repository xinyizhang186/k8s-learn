#!/bin/bash
# scripts/start_service.sh — 单卡启动 vllm serve（最小可跑示例）
# 用法：bash scripts/start_service.sh [model_path]

set -euo pipefail

MODEL_PATH="${1:-Qwen/Qwen3-0.6B}"
PORT="${PORT:-8000}"

echo "================================"
echo "Starting vLLM on Ascend NPU"
echo "  Model: ${MODEL_PATH}"
echo "  Port:  ${PORT}"
echo "================================"

# vllm_ascend 关键环境变量（单卡精简版）
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export VLLM_USE_MODELSCOPE=True  # 用 ModelScope 镜像加速下载

# 启动（无需 --device npu，vllm_ascend 插件自动激活）
exec vllm serve "${MODEL_PATH}" \
    --port "${PORT}" \
    --trust-remote-code \
    --block-size 128 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 4096
