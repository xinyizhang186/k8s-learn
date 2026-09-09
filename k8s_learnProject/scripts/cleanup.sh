#!/usr/bin/env bash
# =============================================================================
# cleanup.sh — 清理项目资源（保留或删除集群）
# -----------------------------------------------------------------------------
# 用法:
#   bash scripts/cleanup.sh         # 仅删除 K8s 资源（保留集群）
#   bash scripts/cleanup.sh --all   # 连 kind 集群一起删除
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

info "删除所有 K8s 资源 (kustomize) ..."
kubectl delete -k . --ignore-not-found=true

if [[ "${1:-}" == "--all" ]]; then
  warn "删除 kind 集群 k8s-learn ..."
  kind delete cluster --name k8s-learn
  info "集群已删除"
else
  info "保留了 kind 集群 k8s-learn (如需删除: bash scripts/cleanup.sh --all)"
fi
info "清理完成"
