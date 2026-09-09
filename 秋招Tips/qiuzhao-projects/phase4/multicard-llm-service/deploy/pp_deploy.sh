#!/bin/bash
# deploy/pp_deploy.sh — Pipeline Parallel 部署 vLLM 服务
# 用法：bash deploy/pp_deploy.sh <model_path> <pp_size> <tp_size>
#
# 注意：PP 通常用于跨机多节点（单机内 TP 更优）

set -euo pipefail

MODEL_PATH="${1:?Usage: $0 <model_path> <pp_size> <tp_size>}"
PP_SIZE="${2:?Usage: $0 <model_path> <pp_size> <tp_size>}"
TP_SIZE="${3:-1}"
PORT="${PORT:-8000}"

echo "================================"
echo "Deploying vLLM (PP=${PP_SIZE}, TP=${TP_SIZE})"
echo "  Model: ${MODEL_PATH}"
echo "================================"

export VLLM_NO_USAGE_STATS=1

# PP 部署通常跨机，需要 Ray 集群
# 单机测试用 mp 后端
exec vllm serve "${MODEL_PATH}" \
    --served-model-name llm \
    --trust-remote-code \
    --distributed-executor-backend mp \
    --pipeline-parallel-size "${PP_SIZE}" \
    --tensor-parallel-size "${TP_SIZE}" \
    --port "${PORT}" \
    --max-model-len 8192 \
    --max-num-seqs 128 \
    --gpu-memory-utilization 0.9
