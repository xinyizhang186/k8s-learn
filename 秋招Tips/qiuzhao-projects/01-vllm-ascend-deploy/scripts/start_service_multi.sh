#!/bin/bash
# scripts/start_service_multi.sh — 多卡 TP 部署（Qwen3-7B, TP=4）
# 用法：bash scripts/start_service_multi.sh [model_path] [tp_size]
# 默认：Qwen3-7B, TP=4

set -euo pipefail

MODEL_PATH="${1:-/models/Qwen3-7B}"
TP_SIZE="${2:-4}"
PORT="${PORT:-8000}"

echo "================================"
echo "Starting vLLM on Ascend NPU (TP=${TP_SIZE})"
echo "  Model: ${MODEL_PATH}"
echo "  TP:    ${TP_SIZE}"
echo "  Port:  ${PORT}"
echo "================================"

# 多卡 NPU 设备选择
export ASCEND_RT_VISIBLE_DEVICES="${ASCEND_RT_VISIBLE_DEVICES:-0,1,2,3}"

# vllm_ascend + HCCL 关键环境变量
export TASK_QUEUE_ENABLE=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=200
export VLLM_USE_MODELSCOPE=True

# LD_LIBRARY_PATH（CANN 库）
export LD_LIBRARY_PATH="/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}"

# 启动（分布式用 mp 后端）
exec vllm serve "${MODEL_PATH}" \
    --served-model-name qwen3 \
    --trust-remote-code \
    --distributed-executor-backend mp \
    --tensor-parallel-size "${TP_SIZE}" \
    --port "${PORT}" \
    --max-model-len 5500 \
    --max-num-batched-tokens 40960 \
    --no-enable-prefix-caching \
    --async-scheduling \
    --quantization ascend \
    --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}' \
    --block-size 128 \
    --gpu-memory-utilization 0.9
