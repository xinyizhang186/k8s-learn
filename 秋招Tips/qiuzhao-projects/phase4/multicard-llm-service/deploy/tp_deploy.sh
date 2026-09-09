#!/bin/bash
# deploy/tp_deploy.sh — Tensor Parallel 部署 vLLM 服务
# 用法：bash deploy/tp_deploy.sh <model_path> <tp_size> [--device npu|cuda]
#
# 例：
#   bash deploy/tp_deploy.sh /models/Llama-3-8B 4              # GPU
#   bash deploy/tp_deploy.sh /models/Qwen3-7B 4 --device npu  # NPU

set -euo pipefail

MODEL_PATH="${1:?Usage: $0 <model_path> <tp_size> [--device npu|cuda]}"
TP_SIZE="${2:?Usage: $0 <model_path> <tp_size> [--device npu|cuda]}"
DEVICE="${3:-cuda}"
PORT="${PORT:-8000}"

echo "================================"
echo "Deploying vLLM (TP=${TP_SIZE}, device=${DEVICE})"
echo "  Model: ${MODEL_PATH}"
echo "  Port:  ${PORT}"
echo "================================"

# 通用环境变量
export VLLM_NO_USAGE_STATS=1

if [ "${DEVICE}" = "npu" ]; then
    # 昇腾 NPU 环境变量
    export ASCEND_RT_VISIBLE_DEVICES="${ASCEND_RT_VISIBLE_DEVICES:-0,1,2,3}"
    export TASK_QUEUE_ENABLE=1
    export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
    export HCCL_OP_EXPANSION_MODE="AIV"
    export HCCL_BUFFSIZE=200
    export LD_LIBRARY_PATH="/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}"
    export VLLM_USE_MODELSCOPE=True

    exec vllm serve "${MODEL_PATH}" \
        --served-model-name llm \
        --trust-remote-code \
        --distributed-executor-backend mp \
        --tensor-parallel-size "${TP_SIZE}" \
        --port "${PORT}" \
        --max-model-len 8192 \
        --max-num-batched-tokens 16384 \
        --max-num-seqs 256 \
        --block-size 128 \
        --gpu-memory-utilization 0.9 \
        --enable-chunked-prefill \
        --async-scheduling \
        --quantization ascend \
        --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'
else
    # NVIDIA GPU
    export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"

    exec vllm serve "${MODEL_PATH}" \
        --served-model-name llm \
        --trust-remote-code \
        --distributed-executor-backend mp \
        --tensor-parallel-size "${TP_SIZE}" \
        --port "${PORT}" \
        --max-model-len 8192 \
        --max-num-batched-tokens 16384 \
        --max-num-seqs 256 \
        --block-size 16 \
        --gpu-memory-utilization 0.9 \
        --enable-chunked-prefill \
        --enable-prefix-caching
fi
