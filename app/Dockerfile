# syntax=docker/dockerfile:1
# 访客计数器镜像 — 多阶段构建，最终镜像无 node_modules（零依赖应用）
# 构建: docker build -t k8s-learn/web:latest -f app/Dockerfile app/
FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
# 零依赖应用，仅需复制源码
COPY --chown=node:node server.js package.json ./
# 非 root 运行（与 k8s securityContext 对齐）
USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=2s --start-period=3s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz >/dev/null 2>&1 || exit 1
CMD ["node", "server.js"]
