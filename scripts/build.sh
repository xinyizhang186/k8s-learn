#!/usr/bin/env bash
# =============================================================================
# build.sh — 构建 Web 镜像并加载到 kind 集群
# -----------------------------------------------------------------------------
# kind 节点是 Docker 容器，宿主机构建的镜像不会自动可见。
# 需用 `kind load docker-image` 把镜像"塞进" kind 节点。
# 用法: bash scripts/build.sh
# =============================================================================
set -euo pipefail

CLUSTER_NAME="k8s-learn"
IMAGE="k8s-learn/web:latest"
GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }

info "构建镜像: ${IMAGE}"
docker build -t "${IMAGE}" -f app/Dockerfile app/

info "加载镜像到 kind 集群: ${CLUSTER_NAME}"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"

info "镜像就绪: ${IMAGE}"
echo "    下一步: bash scripts/deploy.sh"
