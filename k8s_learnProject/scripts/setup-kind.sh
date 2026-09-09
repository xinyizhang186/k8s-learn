#!/usr/bin/env bash
# =============================================================================
# setup-kind.sh — 创建专用的 kind 集群并安装 metrics-server + ingress-nginx
# -----------------------------------------------------------------------------
# kind (Kubernetes IN Docker) 用 Docker 容器模拟一个 K8s 节点，本地学习首选。
# 本脚本创建名为 k8s-learn 的集群，并安装学习所需的两个附加组件：
#   - metrics-server：HPA 自动扩缩容所必需（提供 CPU/内存指标）
#   - ingress-nginx：Ingress 资源所必需（七层路由）
# 用法: bash scripts/setup-kind.sh
# =============================================================================
set -euo pipefail

CLUSTER_NAME="k8s-learn"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }

# 1. 若集群已存在则跳过创建
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "kind 集群 ${CLUSTER_NAME} 已存在，跳过创建"
else
  info "创建 kind 集群: ${CLUSTER_NAME}"
  # extraPortMappings: 把宿主机 80 映射到节点，供 ingress-nginx 使用
  cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --wait 120s --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |-
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            # 允许 metrics-server 不验证证书（kind 单节点学习用）
            rotate-server-certificates: "true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
EOF
  info "kind 集群已就绪"
fi

# 切换 context
kind export kubeconfig --name "${CLUSTER_NAME}"
info "当前 context: $(kubectl config current-context)"

# 2. 安装 metrics-server（HPA 依赖）
if ! kubectl get deployment metrics-server -n kube-system >/dev/null 2>&1; then
  info "安装 metrics-server ..."
  kubectl apply -f https://ghproxy.com/https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null \
    || kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
  # kind 自签证书，需加 --kubelet-insecure-tls
  kubectl patch deployment metrics-server -n kube-system \
    --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
  kubectl rollout status deployment metrics-server -n kube-system --timeout=120s
  info "metrics-server 已就绪"
else
  warn "metrics-server 已存在，跳过"
fi

# 3. 安装 ingress-nginx（Ingress 依赖）
if ! kubectl get namespace ingress-nginx >/dev/null 2>&1; then
  info "安装 ingress-nginx ..."
  kubectl apply -f https://ghproxy.com/https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml 2>/dev/null \
    || kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
  kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=180s
  info "ingress-nginx 已就绪"
else
  warn "ingress-nginx 已存在，跳过"
fi

echo ""
info "集群准备完成！下一步："
echo "    bash scripts/build.sh      # 构建 web 镜像并加载到 kind"
echo "    bash scripts/deploy.sh     # 部署所有 K8s 资源"
echo "    bash scripts/verify.sh     # 验证并查看运行结果"
