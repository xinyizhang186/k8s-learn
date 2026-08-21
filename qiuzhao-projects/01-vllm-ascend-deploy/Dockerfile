# vllm_ascend 部署镜像
# 基于 quay.io/ascend/vllm-ascend 官方镜像，添加自定义模型 + 配置
# 宿主机需要安装昇腾 driver + firmware，镜像内已含 CANN + NNAL + torch_npu + vllm-ascend

FROM quay.io/ascend/vllm-ascend:v0.23.0

LABEL maintainer="秋招实战项目"
LABEL description="vllm_ascend deploy with Qwen3 model + custom configs"

# 切换 apt 源加速（仅国内网络必要）
RUN sed -i 's@archive.ubuntu.com@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list 2>/dev/null || true \
 && sed -i 's@ports.ubuntu.com@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list 2>/dev/null || true

# 安装额外依赖（curl 用于健康检查，vim 便于调试）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    vim \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /workspace

# 复制启动脚本
COPY scripts/ /workspace/scripts/
RUN chmod +x /workspace/scripts/*.sh

# 复制客户端测试代码
COPY client/ /workspace/client/
COPY configs/ /workspace/configs/

# 环境变量（vllm-ascend 运行时）
ENV ASCEND_RT_VISIBLE_DEVICES=0 \
    TASK_QUEUE_ENABLE=1 \
    PYTORCH_NPU_ALLOC_CONF=expandable_segments:True \
    HCCL_OP_EXPANSION_MODE=AIV \
    VLLM_USE_MODELSCOPE=True \
    VLLM_NO_USAGE_STATS=1 \
    LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/lib64:$LD_LIBRARY_PATH

# 暴露服务端口
EXPOSE 8000

# 共享内存（HCCL 通信必需）
# docker run 时还需 --shm-size=16g
VOLUME ["/dev/shm"]

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动：单卡 Qwen3-0.6B（最小可跑示例）
# 实际使用时覆盖 CMD 或用 scripts/ 下脚本
ENTRYPOINT ["vllm", "serve"]
CMD ["Qwen/Qwen3-0.6B", "--port", "8000"]
