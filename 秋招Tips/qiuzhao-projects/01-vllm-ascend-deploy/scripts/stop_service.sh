#!/bin/bash
# scripts/stop_service.sh — 优雅停止 vllm 服务
# 用法：bash scripts/stop_service.sh
# 注意：用 SIGINT（kill -2）让 vLLM 优雅退出，不要用 kill -9

set -euo pipefail

# 找到 vllm serve 主进程
PIDS=$(pgrep -f "vllm serve" || true)

if [ -z "${PIDS}" ]; then
    echo "No vllm serve process found"
    exit 0
fi

echo "Found vllm serve processes: ${PIDS}"
echo "Sending SIGINT (Ctrl+C) for graceful shutdown..."

# 发 SIGINT 让 vLLM 优雅退出
for PID in ${PIDS}; do
    kill -2 "${PID}" 2>/dev/null || true
done

# 等待最多 30 秒
WAIT=30
for i in $(seq 1 ${WAIT}); do
    REMAINING=$(pgrep -f "vllm serve" || true)
    if [ -z "${REMAINING}" ]; then
        echo "✓ All vllm processes stopped (after ${i}s)"
        exit 0
    fi
    sleep 1
done

# 超时后强制 kill
echo "Graceful shutdown timed out after ${WAIT}s, sending SIGKILL..."
for PID in ${PIDS}; do
    kill -9 "${PID}" 2>/dev/null || true
done
echo "Done"
