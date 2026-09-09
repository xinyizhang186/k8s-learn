#!/usr/bin/env bash
# =============================================================================
# verify.sh — 验证部署结果，逐项展示各 K8s 资源的运行状态与输出
# -----------------------------------------------------------------------------
# 这是项目的"结果输出"脚本，按知识点逐项验证。
# 用法: bash scripts/verify.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
sec()  { echo -e "\n${CYAN}══════════════════════════════════════════════════════════"; echo -e "  $1"; echo -e "══════════════════════════════════════════════════════════${NC}"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

sec "1. Namespace 与全局资源总览"
info "所有命名空间"
kubectl get ns
info "learn-space 命名空间下的所有资源"
kubectl -n learn-space get all

sec "2. ConfigMap / Secret / PVC（配置与存储）"
info "ConfigMap (非敏感配置)"
kubectl -n learn-space get cm
echo "--- web-config 内容 ---"
kubectl -n learn-space get cm web-config -o jsonpath='{.data}' | head -c 300; echo
info "Secret (敏感数据, 注意 base64 编码)"
kubectl -n learn-space get secret
echo "--- db-secret 解码后的 DB_USER ---"
kubectl -n learn-space get secret db-secret -o jsonpath='{.data.DB_USER}' | base64 -d; echo
info "PersistentVolumeClaim (持久存储)"
kubectl -n learn-space get pvc

sec "3. Pod 状态与标签（探针/资源/调度）"
kubectl -n learn-space get pods -o wide

sec "4. Service 与端点（网络发现）"
kubectl -n learn-space get svc
info "web Service 的 Endpoints (负载均衡到哪些 Pod)"
kubectl -n learn-space get endpoints web

sec "5. 应用输出 — 访问计数器主页"
info "通过 ClusterIP Service 内部访问 (展示 Pod 身份/计数/配置注入)"
kubectl -n learn-space run curl-test --rm -i --restart=Never --image=curlimages/curl:8.5.0 \
  -- curl -s http://web/ 2>/dev/null | grep -oE '你是第.*位访客|Pod: [^<]*|NS: [^<]*|Redis[^<]*|Secret[^<]*' | head -6 || warn "curl 失败，尝试端口转发"
echo ""
info "通过 NodePort 访问 (节点端口 30080)"
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
curl -s --max-time 5 --noproxy '*' "http://${NODE_IP}:30080/" | grep -oE '你是第.*位访客' | head -1 || warn "NodePort 访问失败"
echo ""
info "/healthz (liveness) 与 /readyz (readiness) 输出"
kubectl -n learn-space run curl-test2 --rm -i --restart=Never --image=curlimages/curl:8.5.0 \
  -- sh -c 'echo -n "healthz: "; curl -s http://web/healthz; echo; echo -n "readyz: "; curl -s http://web/readyz; echo' 2>/dev/null || warn "curl 失败"
echo ""
info "/metrics (Prometheus 指标)"
kubectl -n learn-space run curl-test3 --rm -i --restart=Never --image=curlimages/curl:8.5.0 \
  -- curl -s http://web/metrics 2>/dev/null | grep learn_ || warn "curl 失败"

sec "6. StatefulSet — Redis 有状态应用"
kubectl -n learn-space get sts redis
info "Redis 数据持久化验证 (PVC)"
kubectl -n learn-space get pvc -l app=redis

sec "7. Deployment 副本与滚动更新"
kubectl -n learn-space get deploy web
info "滚动更新历史 (用于回滚)"
kubectl -n learn-space rollout history deploy/web

sec "8. DaemonSet — 每节点一个 Pod"
kubectl -n learn-space get ds
info "DaemonSet Pod 日志 (节点信息采集)"
kubectl -n learn-space logs -l app=node-info --tail=3 2>/dev/null || warn "暂无日志"

sec "9. Job / CronJob — 批处理与定时任务"
info "Job 执行结果"
kubectl -n learn-space get jobs
kubectl -n learn-space logs job/init-counter --tail=5 2>/dev/null || warn "Job 日志已清理"
info "CronJob 调度状态"
kubectl -n learn-space get cronjob

sec "10. HPA — 自动扩缩容配置"
kubectl -n learn-space get hpa
info "当前指标 (需 metrics-server)"
kubectl -n learn-space top pods 2>/dev/null || warn "metrics-server 尚未就绪或无指标"

sec "11. Ingress — 七层路由"
kubectl -n learn-space get ingress
info "通过 Ingress 访问 (需配 /etc/hosts: k8s-learn.local -> 127.0.0.1)"
curl -s --max-time 5 --noproxy '*' --resolve k8s-learn.local:80:127.0.0.1 http://k8s-learn.local/ | grep -oE '你是第.*位访客' | head -1 || warn "Ingress 访问失败，确认 ingress-nginx 已安装"

sec "12. RBAC — 权限验证"
kubectl -n learn-space get sa,role,rolebinding
info "rbac-test Pod 的输出 (演示最小权限)"
kubectl -n learn-space logs rbac-test --tail=6 2>/dev/null || warn "rbac-test 未运行"

sec "13. NetworkPolicy — 网络隔离"
kubectl -n learn-space get networkpolicy

sec "验证完成！"
info "多容器 Pod (sidecar) 日志:"
kubectl -n learn-space logs deploy/web -c log-sidecar --tail=3 2>/dev/null || warn "sidecar 暂无日志"
echo ""
echo "常用调试命令:"
echo "  kubectl -n learn-space describe pod <pod-name>   # 排查 Pod 问题"
echo "  kubectl -n learn-space logs -f deploy/web         # 看实时日志"
echo "  kubectl -n learn-space exec -it deploy/web -- sh  # 进入容器"
echo "  kubectl -n learn-space rollout undo deploy/web    # 回滚上一版本"
