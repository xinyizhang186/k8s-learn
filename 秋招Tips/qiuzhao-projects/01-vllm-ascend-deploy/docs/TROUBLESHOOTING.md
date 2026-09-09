# 常见问题排查

## 1. 容器内 NPU 不可见

**现象**：`npu-smi info` 报错或返回 -8005（device occupied）

**排查**：
```bash
# 宿主机检查 NPU 状态
npu-smi info
# 若宿主也看不到，检查 driver 是否安装
ls /usr/local/Ascend/driver/
```

**修复**：Docker 启动时必须挂载所有 NPU 设备 + driver 目录：
```bash
docker run --device /dev/davinci0 --device /dev/davinci1 \
  --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
  -v /usr/local/dcmi:/usr/local/dcmi \
  quay.io/ascend/vllm-ascend:v0.23.0
```

---

## 2. HCCL 通信失败

**现象**：`EI0002` 通信算子超时，或 `HcclAllReduce` 卡死

**排查**：
```bash
# 1. 检查 ASCEND_RT_VISIBLE_DEVICES 是否设了多卡
echo $ASCEND_RT_VISIBLE_DEVICES  # 应为 0,1,2,3

# 2. 检查 /dev/shm 大小（HCCL 需要共享内存）
df -h /dev/shm  # 应 > 1GB

# 3. 检查端口是否被占用
ss -ltnp | grep 60000  # HCCL 默认用 60000-60031

# 4. 检查网络连通
hccn_tool -i 0 -link -j 1  # 测卡 0 到卡 1 的 HCCS 链路
```

**修复**：
- `docker run --shm-size=16g`（默认 64MB 不够）
- `export TASK_QUEUE_ENABLE=1`
- `export HCCL_OP_EXPANSION_MODE="AIV"`
- `export HCCL_BUFFSIZE=200`

---

## 3. ACL_ERROR_RT_QUEUE_FULL (207014)

**现象**：日志报 `queue is full`，推理卡住

**原因**：torch_npu 异步 task queue（容量 4096）已满，无法再入队

**修复**：
- 减小 `max_num_batched_tokens`（减少单步 token 数）
- 减小 `max_num_seqs`（减少并发请求数）
- 关闭 `ASCEND_LAUNCH_BLOCKING`（同步执行会更快填满队列）

---

## 4. "aclnn op not registered"

**现象**：报错某算子未注册或 segfault

**原因**：
1. CANN 版本不含该算子
2. torch_npu (PTA) 版本不匹配
3. 算子名冲突（如与 CANN built-in 重名）

**修复**：
```bash
# 1. 检查版本兼容性（vllm-ascend、vLLM、torch、torch_npu、CANN 必须配套）
pip show vllm-ascend vllm torch torch_npu

# 2. 检查 CANN 是否完整
cat /usr/local/Ascend/ascend-toolkit/latest/version.cfg

# 3. 设置 ASCEND_LAUNCH_BLOCKING=1 获取更准确的报错堆栈
export ASCEND_LAUNCH_BLOCKING=1
# 注意：调试完务必 unset，不能与 ACLGraph 同时开
```

---

## 5. OOM（显存不足）

**现象**：容器内 OOMKilled 或 `aclrtMalloc` 失败

**排查**：
```bash
# 检查 NPU 显存占用
npu-smi info

# 检查是否有其他进程占用
npu-smi info -t proc-mem -i 0
```

**修复**：
- 降低 `--gpu-memory-utilization 0.8`（从 0.9 降）
- 减小 `--max-model-len`
- 减小 `--max-num-seqs`
- 启用 `--kv-cache-dtype fp8`（KV cache 减半）
- 启用 `--quantization ascend`（W8A8 量化）
- 增加 `--tensor-parallel-size`（多卡分摊）

---

## 6. ACLGraph 报错

**现象**：`ASCEND_LAUNCH_BLOCKING=1` 时开 cudagraph 报错

**原因**：ACLGraph 不能与同步执行模式同时使用

**修复**：
```bash
# 二选一：
# 选项 A：关闭 ASCEND_LAUNCH_BLOCKING（生产推荐，开 ACLGraph）
unset ASCEND_LAUNCH_BLOCKING

# 选项 B：关闭 ACLGraph（调试用）
# 启动时加 --enforce-eager 或改 compilation_config
```

---

## 7. 模型下载慢

**现象**：从 HuggingFace 下载模型超时

**修复**：
```bash
# 用 ModelScope 镜像（国内更快）
export VLLM_USE_MODELSCOPE=True
pip install modelscope

# 或手动下载后挂载本地路径
modelscope download --model Qwen/Qwen3-7B --local_dir /models/Qwen3-7B
vllm serve /models/Qwen3-7B
```

---

## 8. 服务启动后无响应

**现象**：容器跑着但 `curl localhost:8000/health` 不通

**排查**：
```bash
# 1. 检查容器是否还在
docker ps | grep vllm

# 2. 查看容器日志
docker logs vllm-ascend --tail 50

# 3. 进容器检查
docker exec -it vllm-ascend bash
curl localhost:8000/health
ps aux | grep vllm
```

**常见原因**：
- 模型还在加载（大模型首启 1-2 分钟正常）
- 端口被占用（`ss -ltnp | grep 8000`）
- 网络模式不对（用 `--network host` 避免端口映射问题）
