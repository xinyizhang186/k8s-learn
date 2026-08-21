# Docker 容器化开发环境 - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / 大模型推理部署方向）
> 使用方式：每节先记加粗结论，再展开。面试按"是什么 → 原理 → 命令 → 坑"四段答。

---

## 一、容器本质

### Q1. 容器 vs 虚拟机？
| 维度 | 容器 | 虚拟机 (VM) |
|---|---|---|
| 隔离方式 | Linux Namespace + Cgroup | Hypervisor + 独立内核 |
| 启动时间 | 秒级 | 分钟级 |
| 资源开销 | MB 级 | GB 级 |
| 共享内核 | 是（同主机） | 否 |
| 安全性 | 弱于 VM（内核漏洞可逃逸） | 强 |
| 镜像大小 | 通常 10-500MB | 通常 GB |

**关键**：容器不是"轻量 VM"，而是"带 Namespaces 隔离的进程"。

### Q2. Docker 用了哪些 Linux 内核能力？
1. **Namespace**：PID、NET、MNT、UTS、IPC、USER、Cgroup（共 7 种），隔离视图。
2. **Cgroup**：CPU、memory、blkio、devices、pids 等，限制资源。
3. **UnionFS**（overlay2）：镜像分层叠加。
4. **netfilter/iptables**：NAT、端口映射。
5. **veth pair**：容器与宿主机网桥的虚拟网线。
6. **capability**：root 拆成 40+ 项能力，按需授予。

### Q3. 为什么容器中 `ps aux` 能看到宿主机进程？
- 没有 PID namespace 隔离，或特权模式 `--privileged`。
- 普通 Docker 容器默认启用 PID ns，**只看本容器进程**。
- k8s pod 内若设 `hostPID: true` 或 `hostNetwork: true`，会突破相应 ns。

---

## 二、镜像与 Dockerfile

### Q4. 镜像分层原理？
- 每条 Dockerfile 指令生成一层（除 `ENV/LABEL/EXPOSE` 等元数据指令）。
- 只读层叠加，**最上层是可写容器层**（Copy-on-Write）。
- 修改文件时，从下层复制到上层再修改，原层不变 → 同一镜像可被多容器共享。
- `docker image inspect <img>` 看 `RootFS.Layers` 列出所有层 sha256。

### Q5. 多阶段构建（multi-stage build）的好处？
```dockerfile
# 构建阶段
FROM golang:1.22 AS builder
WORKDIR /app
COPY . .
RUN go build -o myapp .

# 运行阶段（仅复制产物，丢弃 Go 工具链）
FROM alpine:3.19
COPY --from=builder /app/myapp /usr/local/bin/
CMD ["myapp"]
```
- **好处**：最终镜像只含 alpine + 二进制，不含 Go SDK、源码、构建缓存。镜像从 1GB+ 降到 20MB。
- 适用：编译型语言（Go/Rust/C++）、PyTorch 编译 wheel 等。

### Q6. Dockerfile 优化 8 条军规？
1. **选 slim/alpine 基础镜像**：`python:3.11-slim` 比 `python:3.11` 小 10 倍。
2. **多阶段构建**：构建产物复制到运行镜像。
3. **合并 RUN**：`RUN apt update && apt install -y xxx && rm -rf /var/lib/apt/lists/*`，减少层数 + 清缓存。
4. **COPY 顺序**：先 `COPY requirements.txt` 再 `RUN pip install`，最后 `COPY .`，让代码改动不 invalidate 依赖层。
5. **.dockerignore**：排除 `.git`、`node_modules`、`__pycache__`、`venv`。
6. **非 root 用户**：`USER appuser` + `USER 1000`，避免提权。
7. **指定版本而非 latest**：`FROM python:3.11.7-slim` 而非 `python:latest`，保证可复现。
8. **HEALTHCHECK**：让编排系统能感知健康。

### Q7. ENTRYPOINT 与 CMD 的关系？
| 写法 | 行为 |
|---|---|
| 仅 CMD | docker run 后追加参数会**替换** CMD |
| 仅 ENTRYPOINT | docker run 后追加参数会**作为 ENTRYPOINT 的参数** |
| ENTRYPOINT + CMD | CMD 作为 ENTRYPOINT 默认参数，可被 docker run 后追加覆盖 |

```dockerfile
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
# docker run myimage        → python main.py --help
# docker run myimage --port 8080  → python main.py --port 8080
```
- **exec 形式**（JSON 数组）走 PID 1，可接收信号；**shell 形式**（`CMD python x.py`）会被 `/bin/sh -c` 包裹，**SIGTERM 收不到**。

### Q8. 镜像与容器数据存储位置？
- 镜像层：`/var/lib/docker/overlay2/`（默认 storage driver overlay2）。
- 容器可写层：同目录下 `<id>-init` 和 `<id>`。
- Volume：`/var/lib/docker/volumes/<name>/_data`。
- bind mount：直接挂载宿主路径，无 Docker 管理。
- 元数据：`/var/lib/docker/image/overlay2/`。

### Q9. `docker save` vs `docker export`？
- `save` 保存**镜像**（带分层、可 push 到 registry），生成 tar。
- `export` 导出**容器文件系统**（扁平化为一层，丢失元数据如 CMD/ENV）。
- 内网离线迁移用 `save | gzip | ssh ... `。

---

## 三、网络

### Q10. Docker 网络模式四种？
| 模式 | 隔离 | 与宿主通信 | 典型用途 |
|---|---|---|---|
| **bridge**（默认） | 是 | 通过 docker0 网桥 + NAT | 单机多容器 |
| **host** | 否 | 直接用宿主网络栈 | 网络性能敏感、调试 |
| **none** | 是 | 无网卡（仅 lo） | 离线计算、自定义网络栈 |
| **container:<id>** | 否（共享另一容器 ns） | 共享另一容器 | sidecar、k8s pod 内共享 |

- 自定义 bridge：`docker network create mynet`，**自动 DNS 解析容器名**（默认 bridge 无此功能）。
- 端口映射 `-p 8080:80` 通过 iptables DNAT 实现。

### Q11. macvlan 是什么？
- 容器直接拿到与宿主同一物理网络的 IP/MAC，**绕过 docker0 与 NAT**。
- 适用：要求容器作为独立 IP 设备的场景（如内网服务、IoT 网关）。
- 坑：宿主无法直接 ping 通 macvlan 容器（内核防环），需额外配 `macvlan bridge` 给宿主。

### Q12. overlay 网络用途？
- 跨多台主机 Docker 集群（Swarm / k8s 类似方案）的容器 L2 互通。
- 基于 VXLAN 封装，需要在 2377/4789 等端口开放。
- Docker Swarm 默认用 overlay；k8s 用 CNI（如 Calico 的 IPIP/VXLAN、Flannel）。

---

## 四、存储

### Q13. Volume vs bind mount vs tmpfs？
| 类型 | 谁管理 | 持久 | 跨主机 | 共享 |
|---|---|---|---|---|
| Volume | Docker | 是（独立于容器生命周期） | 可（NFS/SSHFS 后端） | 可 |
| bind mount | 用户（直接挂路径） | 取决宿主 | 否 | 可 |
| tmpfs | 内存 | 否（容器停即失） | 否 | 否 |

- bind mount 坑：宿主路径不存在时 Docker **自动创建一个空目录**，若期望文件被覆盖可能踩坑。
- Volume 推荐：数据库、模型 ckpt、训练日志。

### Q14. 命名 volume 与匿名 volume？
```bash
docker run -v /data              # 匿名（一长串 sha256 名）
docker run -v myvol:/data        # 命名（可复用、可备份）
docker volume create myvol       # 显式创建
```
- 匿名 volume 容易变成"孤儿"，定期 `docker volume ls -qf dangling=true | xargs -r docker volume rm` 清理。

### Q15. 容器如何使用宿主 GPU / NPU？
- NVIDIA：`--gpus all` 或 `--gpus '"device=0,1"'`，依赖 `nvidia-container-toolkit`，原理是把宿主 `/dev/nvidia*` + CUDA 库挂进去 + 设 env。
- 昇腾 NPU：挂载 `/dev/davinci*`、`/dev/davinci_manager`、`/dev/devmm_svm`、`/dev/hisi_hdc`，并设 `LD_LIBRARY_PATH` 指向 CANN lib。
- k8s：NVIDIA 用 `nvidia.com/gpu` 资源请求；昇腾用 `huawei.com/ascend-910` 等扩展资源 + device plugin。

---

## 五、运行与编排

### Q16. `docker run` 常用参数？
```bash
docker run \
  --name myapp \
  -d \                           # 后台
  --restart unless-stopped \     # 重启策略：no/on-failure[:N]/always/unless-stopped
  -p 8080:80 \                   # 端口
  -v /host/data:/data \          # 卷
  -e ENV=val \                   # 环境变量
  --shm-size 16g \               # 共享内存（NCCL 必备）
  --network mynet \              # 加入自定义网络
  --gpus all \                   # GPU
  --memory 8g --cpus 4 \         # 资源限制
  --user 1000:1000 \             # 非 root
  myimage:tag
```

### Q17. 重启策略区别？
| 策略 | 总是重启 | 退出码非 0 时 | 手动 stop 后 |
|---|---|---|---|
| `no`（默认） | 否 | 否 | 否 |
| `on-failure[:N]` | 否 | 是，最多 N 次 | 否 |
| `always` | 是 | 是 | 是（除非 `docker rm`） |
| `unless-stopped` | 是 | 是 | 否（如果之前手动 stop 过） |

### Q18. Docker Compose 关键概念？
- `docker-compose.yml` 描述多容器应用（v2 / v3）。
- v3 为 swarm 兼容设计，但单机用也行；现代推荐 v2 + `docker compose`（不再是 `docker-compose`，已集成进 docker CLI）。
- 关键字段：`services`、`networks`、`volumes`、`build`、`depends_on`、`healthcheck`、`deploy`（仅 swarm）。
- 依赖启动顺序靠 `depends_on` + `condition: service_healthy`，纯 `depends_on` 仅等容器启动不等就绪。

### Q19. 健康检查（HEALTHCHECK）作用？
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```
- 让外部编排系统（k8s readiness/liveness）有统一信号。
- 状态：`starting` → `healthy` / `unhealthy`。
- 坑：检查脚本失败不要写 `exit 0`，否则永远 healthy。

---

## 六、Registry 与镜像分发

### Q20. 镜像 pull 流程？
1. `docker pull registry/repo:tag` → 解析 registry 地址（默认 docker.io）。
2. HTTPS GET `/v2/<repo>/manifests/<tag>` 拉 manifest（多 arch 列表）。
3. 按 manifest 拉 config + 各层 blob（gzip tar）。
4. 解压到 `overlay2` 目录，按 layer sha 去重缓存。
5. 跨主机同镜像不重复下载（layer 内容寻址）。

### Q21. 私有 registry 怎么搭？
- 官方 `registry:2` 镜像 + 持久化 volume + TLS（HTTPS）或 insecure registry 配置。
- Harbor：企业级，带 UI、权限、镜像扫描、镜像签名。
- 拉/推需 `docker login`，token 存 `/root/.docker/config.json`。
- 大模型镜像（如 torch + vllm 几个 G）建议拆 base + 应用层，并行 push/pull 加速。

### Q22. 镜像为什么不能超过 100 层？
- Docker 老版本限制最多 127 层。
- 实际工程约束：层数多 → 启动慢、存储碎、缓存命中率低。
- 建议：合并 RUN、用多阶段、用 `--squash` 实验 feature。

---

## 七、安全

### Q23. `--privileged` 的危险？
- 几乎等于 root 宿主权限：所有 capability、所有 device、AppArmor 关闭。
- 容器逃逸（如 CVE-2019-5736 runc）后直接拿宿主 root。
- 替代方案：
  - 给特定 device：`--device /dev/nvidia0`
  - 给特定 capability：`--cap-add SYS_ADMIN`（仍要谨慎）
  - 用 `--security-opt=no-new-privileges` 防止 setuid 提权

### Q24. 容器逃逸常见路径？
1. **privileged + 挂载宿主磁盘**：`mount /dev/sda1 /mnt; chroot /mnt`。
2. **挂载 docker socket**：`-v /var/run/docker.sock:/var/run/docker.sock` 后能在容器内启新容器（已宿主 root）。
3. **内核漏洞**：CVE-2019-5736（runc）、dirty cow 等。
4. **capability 过大**：`CAP_SYS_ADMIN` + `CAP_SYS_PTRACE` 组合。
- 防御：非 root、最小 cap、seccomp 默认 profile、read-only rootfs。

### Q25. 为何要 non-root？
- 容器内 root uid=0，若挂载宿主目录且宿主目录归属 root，容器可改宿主文件。
- 即使容器逃逸，uid 仍非 0 减小爆破面。
- 写法：`RUN groupadd -r app && useradd -r -g app app && USER app`。

---

## 八、AI Infra 实战场景

### Q26. 一个标准的大模型推理 Dockerfile 模板？
```dockerfile
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# 国内 apt 源加速
RUN sed -i 's@archive.ubuntu.com@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list \
 && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3-pip git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 模型与代码分层：代码层在上，模型层在下（更稳定）
COPY . /workspace

ENV HF_HOME=/models \
    TRANSFORMERS_CACHE=/models \
    VLLM_NO_USAGE_STATS=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# tini 作为 PID 1，正确转发信号
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "vllm.entrypoints.openai.api_server", \
     "--model", "/models/qwen2-7b", "--port", "8000"]
```

### Q27. `/dev/shm` 太小问题与解决？
- NCCL/HCCL/PyTorch DataLoader 的多进程共享内存通信默认走 `/dev/shm`，64MB 必炸。
- 解决：
  - `docker run --shm-size=16g`
  - 或 `docker run -v /tmp/shm:/dev/shm`（注意宿主 `/tmp/shm` 权限）
  - PyTorch DataLoader：`DataLoader(..., persistent_workers=True, num_workers>0)` + 避免 `pin_memory=True` 走 shm
- k8s：emptyDir `medium: Memory` + `sizeLimit`。

### Q28. 容器内 OOM 杀进程怎么排查？
- `dmesg | grep -i 'killed process'` 看宿主内核日志。
- `docker inspect <id> --format '{{.State.OOMKilled}}'` 是否 OOMKilled。
- 原因：cgroup memory limit 触发 OOM killer（按 `oom_score_adj` 选最该杀的进程）。
- 防御：`--memory` 略大于峰值、JVM/PyTorch 显式设堆/缓存上限。

### Q29. 训练镜像怎么减小重复下载？
- HF / HuggingFace cache 挂到 volume，多容器共享。
- `pip install` 时配合 `--mount=type=cache,target=/root/.cache/pip` BuildKit 缓存。
- 模型权重不进镜像，挂载宿主目录或从 OSS 拉。
- 镜像层只放依赖与代码，runtime 数据进 volume。

### Q30. `docker exec` vs `docker attach`？
- `exec`：在运行容器中**新开**一个进程（典型 `bash`），不影响主进程。
- `attach`：连接到 PID 1 的 stdin/stdout/stderr；Ctrl+C 会发 SIGINT 给 PID 1。
- 调试用 `exec -it <id> bash`；查看主进程 stdout 用 `docker logs -f <id>`，不要 `attach`。

### Q31. `docker logs` 日志输出哪来？
- Docker 默认 logging driver = `json-file`，写到 `/var/lib/docker/containers/<id>/<id>-json.log`。
- 大日志容易撑爆磁盘：设 `log-opts` 限大小：
```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "100m", "max-file": "3" }
}
```
- 或改 driver 为 `journald` / `fluentd` / `syslog`。

### Q32. 容器内程序收到 SIGTERM 后立刻被 kill 怎么办？
- 看 `stop_grace_period`（默认 10s），应用没在 10s 内退出就发 SIGKILL。
- 看是否 PID 1 是 bash（shell form CMD），bash 不转发信号给子进程。
- 解决：用 exec form、用 `tini`/`dumb-init` 做 PID 1，应用代码注册 SIGTERM handler。

---

## 九、Docker 与 k8s 的边界

### Q33. Docker 三件套：dockerd、containerd、runc？
- `dockerd`：Docker daemon，对外 API、镜像构建、卷管理。
- `containerd`：高级行容器运行时，负责镜像 pull、容器 lifecycle。
- `runc`：OCI 低级运行时，真正调用 namespace/cgroup 启动容器。
- 链路：`docker CLI → dockerd → containerd → containerd-shim → runc → 进程`。
- k8s 已弃用 Docker 作为容器运行时（1.24+），改用 containerd 或 CRI-O 直连。**容器仍能用 docker 命令构建**，但 k8s 节点不再装 docker。

### Q34. OCI 镜像与 OCI 运行时规范？
- OCI Image Spec：镜像 manifest/config/layer 格式标准。
- OCI Runtime Spec：容器运行时配置（config.json）标准。
- runc 是参考实现，kata、gVisor 也兼容。
- 现代镜像可同时被 Docker / containerd / podman / k8s 拉取运行。

### Q35. podman / buildah / skopeo 区别？
- `podman`：Docker CLI 兼容（无 daemon、rootless）。
- `buildah`：构建镜像（无 daemon）。
- `skopeo`：跨 registry copy/inspect，不需拉到本地（节省带宽）。
- RedHat 系默认用 podman 而非 docker。

---

## 十、一页速记卡

| 类别 | 必背 |
|---|---|
| 本质 | 容器 = namespace 隔离的进程 + cgroup 限制 + overlay2 镜像层 |
| 镜像层 | 每条 Dockerfile 指令 = 一层；COW；`overlay2` |
| 网络 | bridge/host/none/container；自定义 bridge 自带 DNS |
| 存储 | volume（Docker 管）/ bind（用户管）/ tmpfs（内存） |
| Dockerfile | 多阶段、合并 RUN、COPY 顺序、`.dockerignore`、非 root |
| 命令 | `docker run/exec/logs/inspect/stats`；`docker system prune` |
| PID 1 | exec form + tini；否则 SIGTERM 收不到 |
| 资源 | `--memory`/`--cpus`/`--shm-size`/`--gpus`/`--cap-add` |
| 安全 | 非 root、最小 capability、`no-new-privileges`、勿 `--privileged` |
| k8s | 已弃 Docker，用 containerd；`/dev/shm` 用 emptyDir Memory |
| AI infra | 模型权重挂载不入镜像；HF cache 共享；`shm-size` 必设 |
