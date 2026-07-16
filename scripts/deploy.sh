#!/usr/bin/env bash
# =============================================================================
# deploy.sh — 部署所有 K8s 资源并等待就绪
# -----------------------------------------------------------------------------
# 用法: bash scripts/deploy.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

info "应用所有 manifest (kustomize) ..."
kubectl apply -k .

echo ""
info "等待 Redis StatefulSet 就绪 ..."
kubectl -n learn-space rollout status statefulset/redis --timeout=120s

info "等待 Web Deployment 就绪 ..."
kubectl -n learn-space rollout status deployment/web --timeout=120s

info "等待 Job 完成 ..."
kubectl -n learn-space wait --for=condition=complete job/init-counter --timeout=60s || warn "Job 未完成（可能还在跑）"

echo ""
info "部署完成！查看运行结果："
echo "    bash scripts/verify.sh"
