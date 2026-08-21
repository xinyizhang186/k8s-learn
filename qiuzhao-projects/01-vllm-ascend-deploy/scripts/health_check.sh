#!/bin/bash
# scripts/health_check.sh — vllm 服务健康检查
# 用法：bash scripts/health_check.sh [host] [port]

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8000}"
URL="http://${HOST}:${PORT}/health"

echo "Checking vLLM health: ${URL}"

# 最多重试 30 次（首次启动慢，模型加载可能 1-2 分钟）
MAX_RETRIES=30
RETRY_INTERVAL=5

for i in $(seq 1 ${MAX_RETRIES}); do
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "${URL}" 2>/dev/null || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo "✓ Service is healthy (attempt ${i}/${MAX_RETRIES})"
        # 额外检查模型列表
        MODELS=$(curl -s "http://${HOST}:${PORT}/v1/models" 2>/dev/null || echo "{}")
        echo "  Models: ${MODELS}"
        exit 0
    fi
    echo "  Attempt ${i}/${MAX_RETRIES}: HTTP ${HTTP_CODE}, waiting ${RETRY_INTERVAL}s..."
    sleep "${RETRY_INTERVAL}"
done

echo "✗ Service not healthy after ${MAX_RETRIES} attempts"
exit 1
