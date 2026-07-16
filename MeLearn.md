# Docker 入门学习笔记

> 适合零基础小白快速理解 Docker 是什么、能干什么、怎么用。
> 本项目用 Docker 把「访客计数器」应用打包成镜像，再放进 K8s 运行，学完即可对照 `app/Dockerfile` 实战。

---

## 一、Docker 是什么

Docker 是一个**把应用及其依赖打包成「标准化集装箱」**的工具。

一句话理解：**它让「在我电脑上能跑」变成「在哪都能跑」**。

| 对比项 | 传统部署 | Docker 部署 |
| --- | --- | --- |
| 环境配置 | 每台机器手动装依赖 | 打包进镜像，一次构建处处运行 |
| 启动速度 | 虚拟机要分钟级 | 容器秒级启动 |
| 资源占用 | 虚拟机要整套 OS | 共享宿主机内核，轻量 |
| 隔离方式 | 进程级，易冲突 | 容器级，互不干扰 |
| 一致性 | 开发/测试/生产常不一致 | 同一镜像，环境完全一致 |

> 💡 核心记忆点：Docker 用**镜像**承载应用，用**容器**运行应用，解决了「环境不一致」这个老大难问题。

---

## 二、为什么用 Docker

1. **环境一致**：开发、测试、生产用同一个镜像，再也不会出现「我本地能跑」。
2. **快速启动**：容器共享内核，启动只需秒级，远快于虚拟机。
3. **资源高效**：一台机器能跑几十上百个容器，而虚拟机通常只能跑几个。
4. **隔离干净**：每个容器有独立文件系统/网络/进程空间，应用互不污染。
5. **便于交付**：镜像推到仓库，别人 `docker pull` 就能跑，无需关心怎么装。

> ⚠️ Docker 不是虚拟机。虚拟机虚拟整套硬件+OS，容器只隔离进程，共享宿主内核——所以**轻**但**隔离性弱于虚拟机**。

---

## 三、核心概念（3 个必记）

这三个概念是 Docker 的灵魂，先记住它们：

| 概念 | 类比 | 说明 |
| --- | --- | --- |
| **镜像 (Image)** | 模具/光盘 | 只读模板，包含应用 + 运行环境，用来创建容器 |
| **容器 (Container)** | 铸件/运行中的程序 | 镜像运行起来的实例，可启停删除 |
| **仓库 (Registry)** | 应用商店 | 存放镜像的地方，如 Docker Hub、私有仓库 |

它们的关系：
```
Dockerfile ──build──▶ 镜像 (Image) ──run──▶ 容器 (Container)
                          │
                        push/pull
                          ▼
                      仓库 (Registry)
```

> 💡 一句话：**写 Dockerfile → 构建成镜像 → 推到仓库 → 别人拉下来 → 跑成容器**。

---

## 四、常用命令速查

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `docker build` | 用 Dockerfile 构建镜像 | `docker build -t myapp:1.0 .` |
| `docker images` | 列出本地镜像 | `docker images` |
| `docker run` | 用镜像启动一个容器 | `docker run -d -p 8080:80 myapp` |
| `docker ps` | 查看运行中的容器 | `docker ps` / `docker ps -a` 看全部 |
| `docker stop` / `docker rm` | 停止 / 删除容器 | `docker stop <id>` |
| `docker rmi` | 删除镜像 | `docker rmi myapp:1.0` |
| `docker logs` | 查看容器日志 | `docker logs -f <id>` |
| `docker exec` | 进入容器执行命令 | `docker exec -it <id> sh` |
| `docker pull` / `docker push` | 拉/推镜像 | `docker pull nginx` |

> `-d` 后台运行，`-p 宿主端口:容器端口` 端口映射，`-it` 交互式终端，`-v` 挂载目录——这几个 flag 最常用。

---

## 五、Dockerfile 怎么写

Dockerfile 是一份**「怎么做镜像」的菜谱**，由一系列指令组成。本项目 `app/Dockerfile` 是个极简范例：

```dockerfile
FROM node:20-alpine              # 基础镜像：带 Node 20 的精简 Linux
ENV NODE_ENV=production          # 设置环境变量
WORKDIR /app                     # 容器内工作目录
COPY --chown=node:node server.js package.json ./   # 复制源码并改属主
USER node                        # 用非 root 用户运行（更安全）
EXPOSE 8080                      # 声明容器监听端口（文档性质）
HEALTHCHECK ... CMD wget ...     # 健康检查：定期 curl /healthz
CMD ["node", "server.js"]        # 容器启动时执行的命令
```

常用指令速记：

| 指令 | 作用 | 说明 |
| --- | --- | --- |
| `FROM` | 基础镜像 | 一切镜像都基于另一个镜像，如 `node:20-alpine` |
| `WORKDIR` | 工作目录 | 相当于 `cd`，后续指令都在此目录下 |
| `COPY` | 复制文件进镜像 | `COPY 本地路径 镜像内路径` |
| `RUN` | 构建时执行命令 | 如 `RUN npm install`，结果会写进镜像 |
| `ENV` | 设置环境变量 | 运行时也能读到 |
| `EXPOSE` | 声明端口 | 只是声明，真正映射靠 `docker run -p` |
| `CMD` | 默认启动命令 | 一个 Dockerfile 只有一个生效，可被 `run` 覆盖 |
| `USER` | 切换运行用户 | 安全最佳实践，避免用 root |
| `HEALTHCHECK` | 健康检查 | 告诉 Docker 怎么判断容器是否健康 |

> ⚠️ `RUN` 是**构建时**执行（结果固化进镜像），`CMD` 是**运行时**执行（容器启动才跑）——这是新手最常混的两个指令。

---

## 六、镜像分层与小技巧

Docker 镜像是**一层层堆叠**的，每条 Dockerfile 指令基本就是一层：

- **分层好处**：多镜像共享相同层，省空间、构建快。
- **缓存机制**：某层没变，下次构建直接用缓存；一旦某层变了，它及后续层全部重建。

所以写 Dockerfile 的顺序有讲究：
```dockerfile
# ✅ 好的顺序：先复制不常变的依赖文件，再复制常变的源码
COPY package.json package-lock.json ./
RUN npm ci            # 依赖装一次，缓存命中率高
COPY . .              # 源码变了只重建这一层
```

其他小技巧：
- 用 **alpine** 版基础镜像（如 `node:20-alpine`），体积比完整版小十倍。
- 用 **多阶段构建**，把「编译环境」和「运行环境」分开，最终镜像不含编译工具。
- 加 **`.dockerignore`**，避免把 `node_modules`、`.git` 等无关文件拷进镜像。

> 本项目是「零依赖应用」，所以 Dockerfile 特别简单——不装依赖、不需要多阶段，直接复制源码即可运行。

---

## 七、在本项目中的实战

本项目的访客计数器应用通过 `app/Dockerfile` 打包成镜像，再由 K8s 拉取运行：

| 项目要素 | Docker 角度解释 |
| --- | --- |
| `app/Dockerfile` | 镜像菜谱，定义怎么把 `server.js` 打包 |
| `FROM node:20-alpine` | 基于 Node 20 精简镜像，体积小 |
| `COPY server.js package.json` | 把应用源码放进镜像 |
| `USER node` | 非 root 运行，与 K8s `securityContext` 对齐 |
| `HEALTHCHECK` | 镜像自带健康检查，K8s 探针可参考 |
| `EXPOSE 8080` | 声明端口，与 K8s Service 的 targetPort 一致 |
| 镜像构建命令 | `docker build -t k8s-learn/web:latest -f app/Dockerfile app/` |

> 🎯 对应 `app/Dockerfile:4` 的 `FROM node:20-alpine`——整个应用就靠这一份 14 行的菜谱，从源码变成可随处运行的标准化镜像，这正是 K8s 能调度它的前提（K8s 不直接跑代码，只跑容器）。

---

## 八、动手试一试（5 分钟）

```bash
# 1. 进入项目目录
cd /root/Agent项目/k8s_learnProject

# 2. 用本项目的 Dockerfile 构建镜像
docker build -t k8s-learn/web:latest -f app/Dockerfile app/

# 3. 看看镜像建好了没
docker images | grep k8s-learn/web

# 4. 跑一个容器，把 8080 映射到本机 8080
docker run -d --name web-test -p 8080:8080 k8s-learn/web:latest

# 5. 访问试试
curl http://localhost:8080
# -> 你是第 N 位访客 🎉

# 6. 看日志
docker logs -f web-test  # Ctrl + C 可以退出日志查看

# 7. 玩完清理
docker stop web-test && docker rm web-test
```

---

## 九、小结

- Docker = **把应用打包成标准化集装箱**的工具，解决环境不一致问题。
- 三个核心概念：**镜像（模具）/ 容器（实例）/ 仓库（商店）**。
- Dockerfile 是菜谱，关键指令：`FROM` / `COPY` / `RUN` / `CMD`。
- 镜像是**分层+缓存**的，写 Dockerfile 要把不常变的放前面以利用缓存。
- 本项目用 `app/Dockerfile` 把访客计数器打包成镜像，是 K8s 运行它的前提。
- 想深入：官方文档 https://docs.docker.com/ ，或 `docker --help` 查看所有命令。

---
---

# Kind (Kubernetes IN Docker) 入门学习笔记

> 适合零基础小白理解 kind 是什么、为什么用它学 K8s、怎么用。
> 本项目用 kind 在本地一键拉起一个「真·K8s 集群」，学完即可对照 `scripts/setup-kind.sh` 实战。

---

## 一、Kind 是什么

kind = **K**ubernetes **IN** **D**ocker，即「跑在 Docker 里的 Kubernetes」。

一句话理解：**它用一个 Docker 容器模拟一个 K8s 节点，让你不用装虚拟机、不用云账号，本地就能开一个真集群**。

| 对比项 | 云上托管集群 (EKS/GKE) | Minikube | kind |
| --- | --- | --- | --- |
| 启动方式 | 申请云资源，分钟~小时级 | 起虚拟机或容器 | 起一个 Docker 容器 |
| 启动速度 | 慢 | 较快 | 极快（秒级） |
| 资源占用 | 大 | 中 | 小 |
| 多集群 | 贵且麻烦 | 麻烦 | 随建随删，可开多个 |
| 适合场景 | 生产 | 本地学习/演示 | 本地学习、CI 测试 |

> 💡 核心记忆点：kind 把「K8s 节点」塞进一个 Docker 容器里——**容器里跑容器**，轻量到可以随建随删，是本地学 K8s 的首选。

---

## 二、为什么用 Kind

1. **零成本**：只要装了 Docker，一条命令就能开集群，不用花钱买云资源。
2. **真集群体验**：跑的是货真价实的 K8s（用 kubeadm 初始化），`kubectl` 命令和生产行为一致。
3. **启动快、占资源少**：一个单节点集群几秒就绪，笔记本也能轻松跑。
4. **多集群友好**：想开 dev/test 两个集群？建两个不同名字的 kind 集群即可。
5. **随建随删**：学完一条 `kind delete cluster` 清得干干净净，不污染系统。
6. **CI 友好**：很多开源项目用 kind 做自动化测试，稳定可靠。

> ⚠️ kind 适合**学习/测试/CI**，不适合跑生产负载——它本质是单机模拟，没有真正的多节点高可用。

---

## 三、核心概念（3 个必记）

| 概念 | 类比 | 说明 |
| --- | --- | --- |
| **Node 容器** | 一台「假机器」 | kind 起的 Docker 容器，里面装着 K8s 组件，对外表现得像个节点 |
| **Control-plane** | 集群大脑 | 管调度、存状态的控制节点；学习用单节点时，它既是 master 也是 worker |
| **kind 镜像加载** | 给机器装软件 | 宿主机构建的镜像 kind 节点看不到，必须 `kind load` 推进去 |

它们的关系：
```
你的电脑 (宿主机)
   │  Docker
   ▼
kind 节点容器 (control-plane)   ← 这就是一个「K8s 节点」
   │  里面有: kubelet / apiserver / etcd / containerd ...
   ▼
Pod (跑在节点容器里的容器)        ← 容器里跑容器
```

> 💡 一句话：**宿主机 Docker → kind 节点容器 → Pod 容器**，三层嵌套，但用起来和一个真集群没区别。

---

## 四、常用命令速查

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `kind create cluster` | 创建集群 | `kind create cluster --name k8s-learn` |
| `kind get clusters` | 列出所有 kind 集群 | `kind get clusters` |
| `kind delete cluster` | 删除集群 | `kind delete cluster --name k8s-learn` |
| `kind load docker-image` | 把宿主机镜像塞进节点 | `kind load docker-image myapp:latest --name k8s-learn` |
| `kind export kubeconfig` | 生成 kubectl 用的连接配置 | `kind export kubeconfig --name k8s-learn` |
| `kind create cluster --config` | 用配置文件建集群 | `kind create cluster --config=kind.yaml` |

> 创建后 `kubectl` 就能直接用了——kind 会自动写好 kubeconfig 并切到对应 context。

---

## 五、镜像加载：新手最容易踩的坑

这是 kind 和 Docker 之间最大的「认知差」，必须搞懂：

**宿主机 `docker build` 出来的镜像，kind 节点里默认看不到！**

原因：kind 节点是一个独立的 Docker 容器，有自己的 containerd，和宿主机的 Docker 镜像列表不共享。

```
❌ 错误流程：
docker build -t myapp:latest .   # 镜像在宿主机
kubectl apply -f deployment.yaml # Pod 报 ErrImagePull / ImagePullBackOff

✅ 正确流程：
docker build -t myapp:latest .            # 1. 先构建
kind load docker-image myapp:latest \     # 2. 再「塞进」kind 节点
     --name k8s-learn
kubectl apply -f deployment.yaml          # 3. 现在 Pod 能找到镜像了
```

> 🎯 本项目 `scripts/build.sh` 就是这个流程：`docker build` → `kind load docker-image`，对应 `build.sh:17` 和 `build.sh:20`。

---

## 六、集群配置文件（端口映射）

本项目的 `setup-kind.sh` 没用默认配置，而是用一段配置文件建集群，关键在 `extraPortMappings`：

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |-
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            rotate-server-certificates: "true"
    extraPortMappings:
      - containerPort: 80        # 节点容器内的 80 端口
        hostPort: 80              # 映射到宿主机的 80 端口
        protocol: TCP
```

为什么要端口映射？因为 kind 节点是个容器，外部（你的浏览器/curl）要访问集群里的服务（如 ingress-nginx 监听的 80），必须把宿主机端口透传进节点容器。

```
浏览器 :80 (宿主机)
   │  extraPortMappings 透传
   ▼
kind 节点容器 :80
   │  ingress-nginx 监听
   ▼
集群内 Service / Pod
```

> 🎯 对应 `setup-kind.sh:36-39` 的 `extraPortMappings`——有了它，访问 `http://localhost` 或 `http://k8s-learn.local`（配好 hosts 后）就能直达 ingress-nginx。

---

## 七、在本项目中的实战

本项目用 kind 把「本地学习 K8s」门槛降到最低，三个脚本各司其职：

| 脚本 | kind 相关操作 | 作用 |
| --- | --- | --- |
| `scripts/setup-kind.sh` | `kind create cluster` + 安装 metrics-server / ingress-nginx | 建集群、装好附加组件 |
| `scripts/build.sh` | `docker build` + `kind load docker-image` | 构建镜像并塞进 kind 节点 |
| `scripts/cleanup.sh --all` | `kind delete cluster` | 一键删除整个集群 |

`setup-kind.sh` 还做了两件「kind 专属」的事：

1. **给 metrics-server 打 `--kubelet-insecure-tls` 补丁**：因为 kind 用自签证书，metrics-server 默认会校验失败，必须关掉校验才能取到 CPU 指标（HPA 依赖）。对应 `setup-kind.sh:54-55`。
2. **装 kind 专版 ingress-nginx**：用的是 `provider/kind/deploy.yaml`，已适配 kind 的端口映射。对应 `setup-kind.sh:65-66`。

> 🎯 整个学习流程：`setup-kind.sh`（建集群）→ `build.sh`（造镜像塞进去）→ `deploy.sh`（部署资源）→ `verify.sh`（看结果），kind 是这一切能「开箱即跑」的底层支撑。

---

## 八、动手试一试（5 分钟）

```bash
# 1. 看看有没有 kind 命令
kind version

# 2. 建一个自己的集群
kind create cluster --name my-kind

# 3. 看集群列表
kind get clusters
# -> my-kind

# 4. kubectl 直接能用（kind 已自动配好 context）
kubectl get nodes
# NAME                     STATUS   ROLES           CONTROL-PLANE ...
# my-kind-control-plane    Ready    control-plane   ...

# 5. 跑个 nginx 试试
kubectl run ng --image=nginx
kubectl get pods

# 6. 玩完删掉，干干净净
kind delete cluster --name my-kind
```

> 想跑本项目完整流程？直接 `bash scripts/setup-kind.sh` 即可，它会建好 `k8s-learn` 集群并装好学习所需组件。

---

## 九、小结

- kind = **Kubernetes IN Docker**，用 Docker 容器模拟 K8s 节点，本地零成本开真集群。
- 适合**学习/测试/CI**，不适合生产。
- 三个核心概念：**节点容器 / control-plane / 镜像加载**。
- 最大的坑：宿主机镜像要 `kind load docker-image` 才能被 Pod 看到。
- 想让外部访问集群服务，建集群时要用 `extraPortMappings` 做端口映射。
- 本项目 `setup-kind.sh` / `build.sh` / `cleanup.sh` 覆盖了 kind 的建、载、删全流程，是学习的最佳对照。
- 想深入：官方文档 https://kind.sigs.k8s.io/ ，或 `kind --help` 查看所有命令。

---
---

# Redis 入门学习笔记

> 适合零基础小白快速理解 Redis 是什么、能干什么、怎么用。
> 本项目用 Redis 作为「访客计数器」的后端存储，学完即可对照 `app/server.js` 实战。

---

## 一、Redis 是什么

Redis = **Re**mote **Di**ctionary **S**erver（远程字典服务）。

一句话理解：**它是一个把数据存在内存里的「键值数据库」**。

| 对比项 | 传统数据库 (MySQL) | Redis |
| --- | --- | --- |
| 存储位置 | 磁盘 | 内存（也可落盘） |
| 读写速度 | 较慢（毫秒级） | 极快（微秒级，10万+ QPS） |
| 数据结构 | 表 + 行 | 字符串、列表、哈希、集合等 |
| 典型用途 | 持久保存核心业务数据 | 缓存、计数、排行榜、消息队列 |

> 💡 核心记忆点：Redis 因为在内存里，所以**快**；但内存贵且断电易失，所以一般用作「辅助存储」而非主力数据库。

---

## 二、为什么用 Redis

1. **快**：数据在内存，单线程无锁竞争，性能极高。
2. **数据结构丰富**：不只是字符串，还有列表、哈希、集合等，省去应用层处理。
3. **操作原子**：像 `INCR`（自增）这种命令天然原子，多请求并发也安全。
4. **可持久化**：虽然快，但也能把数据写到磁盘，重启不丢。
5. **简单**：命令直白，`SET key value` / `GET key` 即可上手。

---

## 三、核心数据结构（5 种常用）

Redis 的「值」可以是不同类型，每种类型对应一类使用场景：

### 1. String 字符串
最基础的类型，能存字符串、数字、甚至二进制（图片）。
```
SET name "redis"
GET name              # -> "redis"
INCR visits           # 访问量 +1（原子操作）
```

### 2. List 列表
有序、可重复，类似队列。
```
LPUSH queue "task1"   # 左侧插入
RPUSH queue "task2"   # 右侧插入
LPOP queue            # 取出最左
LRANGE queue 0 -1     # 查看全部
```
👉 用途：消息队列、最新动态列表。

### 3. Hash 哈希
键值对集合，适合存「对象」。
```
HSET user:1 name "Tom" age 20
HGET user:1 name      # -> "Tom"
HGETALL user:1        # 所有字段
```
👉 用途：用户信息、商品详情。

### 4. Set 集合
无序、不重复。
```
SADD tags "redis" "db"
SMEMBERS tags         # 所有成员
SISMEMBER tags "db"   # 是否存在
```
👉 用途：标签、去重、共同好友。

### 5. ZSet 有序集合
带「分数」的集合，按分数排序。
```
ZADD rank 100 "Alice" 90 "Bob"
ZRANGE rank 0 -1 WITHSCORES
ZREVRANGE rank 0 2    # 取前 3 名
```
👉 用途：排行榜、延时队列。

---

## 四、常用命令速查

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `SET` / `GET` | 设置/读取字符串 | `SET k v` / `GET k` |
| `INCR` / `DECR` | 原子自增/自减 | `INCR visits` |
| `EXPIRE` | 设置过期时间（秒） | `EXPIRE k 60` |
| `TTL` | 查看剩余存活时间 | `TTL k` |
| `DEL` | 删除键 | `DEL k` |
| `KEYS` | 查找键（生产慎用） | `KEYS *` |
| `EXISTS` | 判断键是否存在 | `EXISTS k` |
| `TYPE` | 查看值类型 | `TYPE k` |

> ⚠️ `KEYS *` 会扫描所有键，数据量大时会卡住服务，生产环境请用 `SCAN`。

---

## 五、持久化：内存数据怎么不丢

Redis 提供两种持久化方式，可单独或组合使用：

### 1. RDB（快照）
- 定时把内存数据「整体拍照」存到磁盘 `.rdb` 文件。
- 优点：文件小、恢复快。
- 缺点：两次快照之间的数据可能丢失。

### 2. AOF（追加日志）
- 把每条写命令追加到日志文件。
- 优点：丢数据少（最坏丢 1 秒）。
- 缺点：文件大、恢复慢。

> 本项目（K8s StatefulSet）用 PVC 挂载磁盘存放 Redis 数据，重启 Pod 后计数依然存在，靠的就是持久化机制。

---

## 六、典型应用场景

| 场景 | 用到的数据结构 | 说明 |
| --- | --- | --- |
| 缓存热点数据 | String | 把 DB 查询结果存 Redis，减轻数据库压力 |
| 计数器 | String (`INCR`) | 访客数、点赞数、库存 |
| 排行榜 | ZSet | 按分数排序，实时更新 |
| 分布式锁 | String (`SET NX EX`) | 多服务互斥访问共享资源 |
| 消息队列 | List / Stream | 任务排队、异步处理 |
| 会话 Session | String / Hash | 分布式登录态共享 |

---

## 七、在本项目中的实战

本项目的访客计数器（`app/server.js`）就是一个 Redis 最经典用法：**计数器**。

```js
// 自增访问计数（原子，并发安全）
const count = await redis.cmd('INCR', 'visits');
// 读取当前计数
const cur = await redis.cmd('GET', 'visits');
```

对应关系：

| 项目要素 | Redis 角度解释 |
| --- | --- |
| 键 `visits` | 一个 String 类型的计数器 |
| `INCR visits` | 每次访问原子 +1，多 Pod 并发也不会错乱 |
| StatefulSet + PVC | 保证 Redis 有稳定网络标识 + 数据持久化 |
| Redis 不可用时降级内存 | 体现「服务可用性优先」的容错设计 |
| `/readyz` 检查 Redis 连通 | K8s 就绪探针依赖 Redis 健康状态 |

> 🎯 学完上面的概念，再回看 `app/server.js:33-89` 的 `TinyRedis` 类，你会看到它用纯 TCP 实现了 RESP 协议与 Redis 通信——这恰好印证了「Redis 协议很简单」这一点。

---

## 八、动手试一试（5 分钟）

如果你已装 Docker，可一键启动一个 Redis 边玩边学：

```bash
# 1. 启动 Redis
docker run -d --name myredis -p 6379:6379 redis

# 2. 进入交互命令行
docker exec -it myredis redis-cli

# 3. 在 redis-cli 里试试
127.0.0.1:6379> SET hello world
OK
127.0.0.1:6379> GET hello
"world"
127.0.0.1:6379> INCR visits
(integer) 1
127.0.0.1:6379> INCR visits
(integer) 2
127.0.0.1:6379> KEYS *
1) "visits"
2) "hello"
127.0.0.1:6379> exit
```

---

## 九、小结

- Redis = **内存型键值数据库**，特点是**快**。
- 5 种核心数据结构：**String / List / Hash / Set / ZSet**，各有适用场景。
- 持久化靠 **RDB + AOF**，本项目通过 K8s PVC 落盘。
- 最经典的入门用法就是 **计数器**（`INCR`），本项目正是如此。
- 想深入：官方文档 https://redis.io/docs/ ，或 `redis-cli` 里输入 `HELP @<类型>` 查看命令。

---
---

# Kubernetes Namespace 入门学习笔记

> 适合零基础小白理解 K8s Namespace 是什么、为什么用、怎么用。
> 本项目所有资源都部署在 `learn-space` 命名空间里，学完即可对照 `manifests/00-namespace.yaml` 实战。

---

## 一、Namespace 是什么

Namespace（命名空间）是 K8s 中用于**在同一物理集群里划分「逻辑隔离区」**的机制。

一句话理解：**它像把一个大办公室隔成多个小房间，各房间里的桌椅（资源）互不混淆**。

| 对比项 | 不用 Namespace | 用 Namespace |
| --- | --- | --- |
| 资源组织 | 所有 Pod/Service 堆在一起 | 按团队/环境分组管理 |
| 命名冲突 | 同名资源会报错 | 不同 Namespace 内可同名 |
| 权限控制 | 难以细粒度授权 | 可按 Namespace 限定 RBAC 权限 |
| 资源限额 | 无法分团队限制 CPU/内存 | 可用 ResourceQuota 给每个 NS 配额 |

> 💡 核心记忆点：Namespace 提供**逻辑隔离**，不是物理隔离——不同 NS 的 Pod 仍可互通，只是便于管理。

---

## 二、为什么用 Namespace

1. **隔离环境**：dev / test / prod 各放一个 NS，互不干扰。
2. **避免命名冲突**：两个团队都想叫 `redis` 服务，分开放就不打架。
3. **权限边界**：RBAC 可限定「A 团队只能操作 dev 这个 NS」。
4. **资源配额**：用 ResourceQuota 限制某 NS 最多用多少 CPU/内存，防止单团队吃光集群。
5. **便于清理**：删一个 NS，里面所有资源一并清除，不用一个个删。

> ⚠️ Namespace 主要隔离**对象管理**，**不隔离网络**。要隔离网络得用 NetworkPolicy（见 `manifests/13-networkpolicy.yaml`）。

---

## 三、集群自带的 Namespace

一个全新 K8s 集群默认就有几个 Namespace：

| Namespace | 作用 |
| --- | --- |
| `default` | 不指定 NS 时，资源默认放这里 |
| `kube-system` | K8s 系统组件（调度器、DNS、ingress 等） |
| `kube-public` | 公开资源，所有用户可读 |
| `kube-node-lease` | 节点心跳信息 |

> 小白起步时，**不要往 `kube-system` 里放自己的应用**，以免搞乱系统组件。

---

## 四、常用命令速查

| 命令 | 作用 |
| --- | --- |
| `kubectl get ns` | 列出所有 Namespace |
| `kubectl create ns learn-space` | 创建一个 Namespace |
| `kubectl delete ns learn-space` | 删除 NS 及其内所有资源 |
| `kubectl -n learn-space get pods` | 查看指定 NS 里的 Pod |
| `kubectl get pods -A` | 查看所有 NS 的 Pod（`-A` = all namespaces） |
| `kubectl config set-context --current --namespace=learn-space` | 设置默认 NS，省去每次 `-n` |

> 💡 小技巧：把默认 NS 设成 `learn-space` 后，后续命令就不用每次加 `-n` 了。

---

## 五、怎么定义（YAML 示例）

创建一个 Namespace 非常简单，`manifests/00-namespace.yaml` 全部内容如下：

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: learn-space
  labels:
    app.kubernetes.io/name: k8s-learn
```

- `kind: Namespace` —— 声明这是一个 Namespace 资源
- `metadata.name` —— Namespace 的名字（项目里叫 `learn-space`）
- `labels` —— 打标签，便于后续选择/过滤（本项目用于标识归属）

部署方式：
```bash
kubectl apply -f manifests/00-namespace.yaml
# 或直接用命令
kubectl create namespace learn-space
```

---

## 六、其他资源怎么放进 Namespace

大多数资源（Pod/Deployment/Service…）通过 `metadata.namespace` 字段指定归属：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: learn-space    # ← 指定放进哪个 NS
spec:
  # ...
```

> 如果不写 `namespace`，会落到 `kubectl` 当前上下文的默认 NS（通常是 `default`）。

---

## 七、在本项目中的实战

本项目所有 14 个 manifest 都部署在 `learn-space` 这一个 Namespace 里：

| 项目要素 | Namespace 角度解释 |
| --- | --- |
| `00-namespace.yaml` | 第一个部署的资源，先把「房间」建好 |
| `learn-space` | 房间名字，后续所有资源都放这里 |
| `kubectl -n learn-space get pods` | 只看这个房间里的 Pod |
| `verify.sh` 脚本 | 所有命令都带 `-n learn-space` 定向查询 |
| `cleanup.sh` | 删 NS 即可一键清空所有学习资源 |

> 🎯 对应 `manifests/00-namespace.yaml:11` 的 `name: learn-space`——这是本项目所有资源的「逻辑边界」，部署时必须先建 NS，再建其他资源。

---

## 八、动手试一试（3 分钟）

```bash
# 1. 查看集群现有的 Namespace
kubectl get ns

# 2. 新建一个自己的 NS
kubectl create ns my-playground

# 3. 把默认上下文切到它
kubectl config set-context --current --namespace=my-playground

# 4. 在里面跑个临时 Pod 试试
kubectl run tmp --image=redis --rm -it -- redis-cli ping
# -> PONG

# 5. 玩完一键清空（NS 里所有资源一起删）
kubectl delete ns my-playground
```

---

## 九、小结

- Namespace = K8s 集群里的**逻辑隔离区**，像办公室的小房间。
- 主要用途：**分环境 / 避免重名 / 权限边界 / 资源配额**。
- **不隔离网络**，要网络隔离需配合 NetworkPolicy。
- 默认 NS 是 `default`，系统组件在 `kube-system`，别乱动。
- 本项目统一用 `learn-space`，部署第一步就是建它，清理时删它即可。

---
---

# Kubernetes Ingress 入门学习笔记

> 适合零基础小白理解 K8s Ingress 是什么、和 Service 有啥区别、怎么用。
> 本项目通过 Ingress 把 `k8s-learn.local` 域名的流量路由到 web 服务，学完即可对照 `manifests/07-ingress.yaml` 实战。

---

## 一、Ingress 是什么

Ingress 是 K8s 中**把外部 HTTP/HTTPS 流量按域名和路径路由到集群内 Service** 的资源。

一句话理解：**它像集群门口的「前台接待」，根据来访的域名/路径，把你领到对应的房间（Service）**。

| 对比项 | Service (NodePort/LoadBalancer) | Ingress |
| --- | --- | --- |
| 工作层级 | 4 层（TCP/UDP 端口） | 7 层（HTTP 域名/路径） |
| 对外暴露方式 | 每个服务一个端口/IP | 一个入口，按域名/路径分流 |
| TLS/HTTPS | 需自行处理 | 原生支持证书终结 |
| 典型场景 | 简单暴露、四层流量 | 多网站、API 路由、虚拟主机 |

> 💡 核心记忆点：Ingress 是**七层（HTTP）路由器**，一个入口能管多个服务，省端口、支持域名。

---

## 二、为什么用 Ingress

1. **统一入口**：一个公网 IP/域名后面挂多个服务，不用每个服务都开端口。
2. **按域名/路径路由**：`api.example.com` → 服务 A，`example.com/blog` → 服务 B。
3. **支持 HTTPS**：集中管理 TLS 证书，自动终结 HTTPS，后端服务不用关心。
4. **虚拟主机**：同一 IP 通过不同 `Host` 头分发到不同服务。
5. **功能丰富**：通过注解支持重写、限流、重定向、鉴权等高级能力。

> ⚠️ Ingress 只是「路由规则」，真正干活的是 **Ingress Controller**（如 ingress-nginx）。没有 Controller，规则写了也不生效。

---

## 三、Ingress vs Service vs Ingress Controller

小白最容易混这三个，一次理清：

| 概念 | 角色 | 类比 |
| --- | --- | --- |
| **Service** | 给 Pod 一个稳定访问地址（ClusterIP/NodePort…） | 房间门牌号 |
| **Ingress** | 一份「域名/路径 → Service」的路由规则表 | 前台登记册 |
| **Ingress Controller** | 真正执行规则的程序（nginx/traefik…） | 前台接待员 |

数据流：
```
外部用户
   │  HTTP 请求 (Host: k8s-learn.local)
   ▼
Ingress Controller (nginx Pod)     ← 实际监听 80/443 端口
   │  查 Ingress 规则
   ▼
Service: web (ClusterIP)           ← 集群内部地址
   │  负载均衡
   ▼
Pod: web-xxx
```

> 本项目的 `setup-kind.sh` 会自动安装 ingress-nginx，这就是 Controller。

---

## 四、常用命令速查

| 命令 | 作用 |
| --- | --- |
| `kubectl -n learn-space get ingress` | 查看所有 Ingress 规则 |
| `kubectl -n learn-space describe ingress web-ingress` | 查看规则详情与后端 |
| `kubectl get pods -n ingress-nginx` | 查看 Ingress Controller 是否运行 |
| `kubectl get ingressclass` | 查看集群可用的 Ingress 类 |
| `kubectl -n learn-space get svc -n ingress-nginx` | 找 Controller 对外暴露地址 |

---

## 五、怎么定义（YAML 示例）

本项目的 `manifests/07-ingress.yaml` 是最典型的单域名路由：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
  namespace: learn-space
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /   # 把请求路径重写为 /
spec:
  ingressClassName: nginx                            # 指定用哪个 Controller
  rules:
    - host: k8s-learn.local                          # 匹配的域名
      http:
        paths:
          - path: /                                  # 匹配的路径
            pathType: Prefix                         # 前缀匹配（/ 开头都算）
            backend:
              service:
                name: web                            # 转发到哪个 Service
                port:
                  number: 80                         # Service 的端口
```

关键字段解读：

| 字段 | 作用 |
| --- | --- |
| `ingressClassName` | 指定由哪个 Ingress Controller 处理（这里是 `nginx`） |
| `rules[].host` | 匹配 HTTP 请求的 `Host` 头（域名） |
| `paths[].path` + `pathType` | 匹配 URL 路径；`Prefix` 表示前缀匹配 |
| `backend.service` | 命中后转发到哪个 Service 的哪个端口 |
| `annotations` | 给 Controller 的额外指令（如重写、限流） |

---

## 六、pathType 三种模式

| 取值 | 含义 | 示例 |
| --- | --- | --- |
| `Prefix` | 前缀匹配（最常用） | `/` 匹配所有；`/api` 匹配 `/api`、`/api/v1` |
| `Exact` | 精确匹配，路径必须完全相同 | `/health` 只匹配 `/health`，不匹配 `/health/x` |
| `ImplementationSpecific` | 交由 Controller 自行判断 | 少用 |

> 本项目用 `Prefix` + `/`，表示「`k8s-learn.local` 下所有路径都转给 web 服务」。

---

## 七、进阶：多服务按路径分流

Ingress 真正强大的地方是**一个入口分发多个服务**：

```yaml
rules:
  - host: app.example.com
    http:
      paths:
        - path: /api
          pathType: Prefix
          backend:
            service: { name: api-svc, port: { number: 80 } }
        - path: /static
          pathType: Prefix
          backend:
            service: { name: static-svc, port: { number: 80 } }
        - path: /
          pathType: Prefix
          backend:
            service: { name: web-svc, port: { number: 80 } }
```

也可以用**不同域名**分流（虚拟主机）：
```yaml
rules:
  - host: api.example.com      → api-svc
  - host: blog.example.com     → blog-svc
```

---

## 八、在本项目中的实战

| 项目要素 | Ingress 角度解释 |
| --- | --- |
| `07-ingress.yaml` | 定义 `k8s-learn.local` → `web:80` 的路由规则 |
| `ingressClassName: nginx` | 选用 ingress-nginx 作为 Controller |
| `rewrite-target: /` | 注解，把路径重写为 `/`，避免后端收到原始路径 |
| `setup-kind.sh` | 自动安装 ingress-nginx Controller，否则规则不生效 |
| 访问方式 | 配置 `/etc/hosts` 把 `k8s-learn.local` 指向节点 IP，或 `curl --resolve` |
| `verify.sh` | 通过 Ingress 域名访问主页，验证七层路由是否生效 |

> 🎯 对应 `manifests/07-ingress.yaml:20` 的 `host: k8s-learn.local`——访问这个域名时，ingress-nginx 会把请求转发给 `web` Service，再负载到具体 Pod。

### 怎么访问这个域名

因为 `k8s-learn.local` 是假域名，需要本地解析到集群入口：

```bash
# 方式一：改 /etc/hosts（需先拿到 ingress-nginx 的外部 IP）
echo "<INGRESS_IP> k8s-learn.local" | sudo tee -a /etc/hosts
curl http://k8s-learn.local

# 方式二：用 curl --resolve 临时指定（不改 hosts）
curl --resolve k8s-learn.local:80:<INGRESS_IP> http://k8s-learn.local
```

获取 ingress-nginx 对外 IP：
```bash
kubectl get svc -n ingress-nginx
# 找 TYPE=LoadBalancer 或 NodePort 的端口
```

---

## 九、动手试一试（5 分钟）

```bash
# 1. 确认 Ingress Controller 已就绪（本项目 setup-kind.sh 已装）
kubectl get pods -n ingress-nginx

# 2. 部署 Ingress 规则
kubectl apply -f manifests/07-ingress.yaml

# 3. 查看规则是否生效
kubectl -n learn-space get ingress
# NAME           CLASS   HOSTS             ADDRESS        PORTS   AGE
# web-ingress    nginx   k8s-learn.local   192.168.x.x    80      1m

# 4. 拿到 Controller 地址
kubectl get svc -n ingress-nginx ingress-nginx-controller
# 记下 EXTERNAL-IP 或 NodePort

# 5. 用 curl 模拟域名访问（不改 hosts）
curl --resolve k8s-learn.local:80:<上一步的IP> http://k8s-learn.local
# 你是第 N 位访客 🎉
```

---

## 十、小结

- Ingress = K8s 的**七层（HTTP）路由规则**，像集群门口的前台接待。
- 三件套别混：**Service = 门牌号 / Ingress = 登记册 / Ingress Controller = 接待员**。
- 核心能力：**统一入口、按域名/路径分流、TLS 终结、虚拟主机**。
- 光写 Ingress 没用，必须先装 **Ingress Controller**（本项目用 ingress-nginx）。
- 本项目用 `k8s-learn.local` 域名路由到 web 服务，是 Ingress 最经典的单服务暴露用法。

---
---

# scripts/setup-kind.sh 脚本逐行讲解

> 适合零基础小白理解这个「一键建集群」脚本到底干了什么。
> 对照源码 `scripts/setup-kind.sh`（共 77 行）逐段拆解，学完即可看懂任意 kind 初始化脚本。

---

## 一、这个脚本干什么（一张大图）

`setup-kind.sh` 是本项目的**第 0 步**——在学习 K8s 之前，先把「练习用的集群」搭好。它做三件事：

```
┌─────────────────────────────────────────────────────────┐
│  setup-kind.sh                                           │
│                                                          │
│  ① kind create cluster  ──→  建一个名叫 k8s-learn 的集群  │
│  ② 装 metrics-server    ──→  让 HPA 能读到 CPU 指标       │
│  ③ 装 ingress-nginx     ──→  让 Ingress 规则能真正生效    │
│                                                          │
│  跑完之后，kubectl 就能直接用了                            │
└─────────────────────────────────────────────────────────┘
```

> 💡 一句话：**它把「装集群 + 装两个必备插件」自动化成一条命令**，省去手动敲十几条 kubectl。

---

## 二、脚本骨架（头部的约定）

```bash
#!/usr/bin/env bash          # 用 bash 解释执行
set -euo pipefail            # 严格模式：任何命令失败就立刻退出
```

| `set` 选项 | 含义 | 为什么要这样 |
| --- | --- | --- |
| `-e` | 命令出错立即退出 | 避免前面失败还继续往下跑，越跑越错 |
| `-u` | 用了未定义变量就报错 | 防止拼写错误导致空值 |
| `-o pipefail` | 管道中任一环节失败则整体失败 | 默认只看最后一条，可能漏掉错误 |

还有两个小工具函数（彩色输出）：

```bash
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }   # 绿色 ✓ 成功提示
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }   # 黄色 ! 警告提示
```

> 这是写 shell 脚本的好习惯：用 `set -euo pipefail` 保安全，用彩色函数让输出好看又好读。

---

## 三、第 ① 步：创建 kind 集群（第 18–46 行）

### 3.1 先查再建，避免重复

```bash
CLUSTER_NAME="k8s-learn"

# 如果集群已存在，跳过创建
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "kind 集群 ${CLUSTER_NAME} 已存在，跳过创建"
else
  info "创建 kind 集群: ${CLUSTER_NAME}"
  # ... 用配置文件创建 ...
fi
```

**思想**：脚本要「可重复运行」（幂等）——跑一次建集群，再跑一次不应该报错，而是跳过。`kind get clusters` 列出现有集群，`grep -q` 静默匹配，存在就跳过。

### 3.2 用内联 YAML 建集群（关键！）

不用默认配置，而是用 `cat <<EOF | kind create cluster --config=-` 把一段配置「管道」喂给 kind：

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane              # 单节点：既是 master 也是 worker
    kubeadmConfigPatches:
      - |-
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            rotate-server-certificates: "true"   # 开启证书轮转
    extraPortMappings:
      - containerPort: 80            # 节点容器内的 80 端口
        hostPort: 80                 # 映射到宿主机的 80 端口
        protocol: TCP
```

两个关键点：

| 配置 | 作用 | 为什么需要 |
| --- | --- | --- |
| `extraPortMappings: 80→80` | 把宿主机 80 端口透传进 kind 节点 | ingress-nginx 监听 80，外部（浏览器/curl）才能访问到集群 |
| `rotate-server-certificates: "true"` | 让 kubelet 自动轮转服务证书 | 生产安全实践（⚠️ kind 下需手动批准 CSR，见后文「踩坑」） |

> ⚠️ **重要踩坑**：开启 `rotate-server-certificates` 后，kubelet 会生成 `kubelet-serving` 类型的 CSR 请求，这些**默认不会被自动批准**！不批准会导致 metrics-server 取不到指标、`kubectl logs` 报 TLS 错误。需要手动执行：
> ```bash
> kubectl certificate approve <csr-name>   # 批准 pending 的 kubelet-serving CSR
> ```
> 这是本次实际运行时遇到的真实问题。

### 3.3 切换 kubectl 上下文

```bash
kind export kubeconfig --name "${CLUSTER_NAME}"
info "当前 context: $(kubectl config current-context)"
```

`kind export kubeconfig` 把连接信息写到 `~/.kube/config`，并切换到 `kind-k8s-learn` 这个 context。之后 `kubectl` 默认就连这个集群了。

---

## 四、第 ② 步：安装 metrics-server（第 48–60 行）

### 4.1 先查再装（幂等）

```bash
if ! kubectl get deployment metrics-server -n kube-system >/dev/null 2>&1; then
  info "安装 metrics-server ..."
```

`kubectl get deployment ... >/dev/null 2>&1` 把输出和报错都丢弃，只看「存不存在」这个返回值。`!` 取反：不存在才装。

### 4.2 双镜像源兜底（网络友好）

```bash
kubectl apply -f https://ghproxy.com/https://github.com/.../components.yaml 2>/dev/null \
  || kubectl apply -f https://github.com/.../components.yaml
```

**思想**：先用国内代理 `ghproxy.com` 加速，失败了（`||`）再回退到 GitHub 原地址。`2>/dev/null` 隐藏第一次的报错，让输出干净。这是国内环境拉 GitHub 资源的常见技巧。

### 4.3 打补丁：--kubelet-insecure-tls

```bash
kubectl patch deployment metrics-server -n kube-system \
  --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
```

这段看着吓人，其实就一件事：**给 metrics-server 容器追加一个启动参数** `--kubelet-insecure-tls`。

| 部分 | 含义 |
| --- | --- |
| `kubectl patch` | 给已有资源打补丁，不用重写整个 YAML |
| `--type='json'` | 用 JSON Patch 格式（RFC 6902） |
| `op: add` | 添加操作 |
| `path: .../containers/0/args/-` | 第 0 个容器的 args 数组末尾（`-` 表示追加） |
| `value: --kubelet-insecure-tls` | 新增的参数值 |

**为什么需要**：kind 用自签证书，metrics-server 默认会校验 kubelet 的 TLS 证书然后失败。加这个参数 = 「不校验证书」，学习环境里安全可接受，生产绝不能这么干。

### 4.4 等待就绪

```bash
kubectl rollout status deployment metrics-server -n kube-system --timeout=120s
```

`rollout status` 会阻塞直到 Deployment 滚动更新完成（或超时）。这是脚本里「确保装好了再继续」的关键。

> 💡 为什么需要 metrics-server？因为后面要学 **HPA（自动扩缩容）**，HPA 根据 CPU 使用率扩缩 Pod，而 CPU 数据就靠 metrics-server 提供。没有它，HPA 会一直 `unknown`。

---

## 五、第 ③ 步：安装 ingress-nginx（第 62–71 行）

套路和 metrics-server 一模一样：**先查 → 装 → 等就绪**。

```bash
if ! kubectl get namespace ingress-nginx >/dev/null 2>&1; then
  info "安装 ingress-nginx ..."
  # 同样用 ghproxy 兜底，但用的是 kind 专版部署文件
  kubectl apply -f https://ghproxy.com/https://raw.githubusercontent.com/.../provider/kind/deploy.yaml 2>/dev/null \
    || kubectl apply -f https://raw.githubusercontent.com/.../provider/kind/deploy.yaml
  kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=180s
fi
```

注意这里用的是 `provider/kind/deploy.yaml`（kind 专版），而不是通用版。kind 专版已经适配了 kind 的端口映射方式，装完就能直接用 80 端口访问。

> 💡 为什么需要 ingress-nginx？因为后面要学 **Ingress**（七层路由）。Ingress 只是「规则」，真正执行规则的是 Ingress Controller。没装它，写再多 Ingress YAML 也不生效。

---

## 六、脚本结尾：提示下一步（第 73–77 行）

```bash
echo ""
info "集群准备完成！下一步："
echo "    bash scripts/build.sh      # 构建 web 镜像并加载到 kind"
echo "    bash scripts/deploy.sh     # 部署所有 K8s 资源"
echo "    bash scripts/verify.sh     # 验证并查看运行结果"
```

脚本没有默默结束，而是告诉用户「接下来该干嘛」。这是写工具脚本的好习惯——**引导用户进入下一步**，降低使用门槛。

完整学习流程：
```
setup-kind.sh  ──→  build.sh  ──→  deploy.sh  ──→  verify.sh
  建集群+插件       构建并塞镜像     部署 YAML       看运行结果
```

---

## 七、脚本里的设计模式总结

小白可以从中偷师的 5 个 shell 脚本技巧：

| 技巧 | 脚本中的体现 | 好处 |
| --- | --- | --- |
| **严格模式** | `set -euo pipefail` | 出错即停，不让错误蔓延 |
| **幂等设计** | 每步都 `if 已存在 then 跳过` | 脚本可重复跑，不会因已装而报错 |
| **彩色输出** | `info()` / `warn()` 函数 | 输出好看，✓ / ! 一眼分清 |
| **兜底回退** | `代理源 \|\| 原地址` | 网络不好也能装上 |
| **等待就绪** | `rollout status --timeout` | 确保装好再继续，不会时序错乱 |

---

## 八、实际运行结果（本次实测）

在本机执行 `bash scripts/setup-kind.sh`，真实输出如下（节选）：

### 1. 建集群成功（约 19 秒）
```
[✓] 创建 kind 集群: k8s-learn
Creating cluster "k8s-learn" ...
 ✓ Preparing nodes 📦
 ✓ Starting control-plane 🕹️
 ✓ Installing CNI 🔌
 ✓ Installing StorageClass 💾
 • Ready after 19s 💚
[✓] kind 集群已就绪
[✓] 当前 context: kind-k8s-learn
```

### 2. metrics-server 初次超时（踩坑）
```
[✓] 安装 metrics-server ...
deployment.apps/metrics-server patched
Waiting for deployment "metrics-server" rollout to finish: 1 old replicas are pending termination...
error: timed out waiting for the condition     ← 脚本因 set -e 在此中止
```

**原因**：`rotate-server-certificates: "true"` 导致 kubelet 生成了 2 个 `kubelet-serving` CSR 处于 `Pending` 状态，metrics-server 无法校验 kubelet 证书 → 不 Ready → rollout 超时。

**修复**：
```bash
# 1. 查看未批准的 CSR
kubectl get csr
# csr-slmg7   kubelet-serving   Pending
# csr-zhqdv   kubelet-serving   Pending

# 2. 批准它们
kubectl certificate approve csr-slmg7 csr-zhqdv

# 3. 等待 ~40s 后 metrics-server 变 Ready
kubectl get deployment metrics-server -n kube-system
# NAME             READY   UP-TO-DATE   AVAILABLE
# metrics-server   1/1     1            1

kubectl top nodes    # 指标正常输出，说明 metrics-server 工作了
# NAME                      CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# k8s-learn-control-plane   206m         2%     763Mi           2%
```

### 3. ingress-nginx 安装成功（脚本中止后手动补装）
```
namespace/ingress-nginx created
...
deployment.apps/ingress-nginx-controller created
deployment "ingress-nginx-controller" successfully rolled out
```

### 4. 最终全量验证
```
① KIND CLUSTERS:      k8s-learn
② CONTEXT:            kind-k8s-learn
③ NODES:              k8s-learn-control-plane   Ready    v1.25.0
④ metrics-server:     1/1 Available  ✅
⑤ kubectl top nodes:  正常输出 CPU/内存  ✅
⑥ ingress-nginx Pod:  1/1 Running  ✅
⑦ IngressClass:       nginx 已注册  ✅
⑧ 端口映射:           0.0.0.0:80->80/tcp（宿主机 80 直达集群）✅
```

> 🎯 **结论**：脚本本身逻辑正确，三个组件最终全部就绪。唯一的「坑」是 `rotate-server-certificates: "true"` 在 kind 下需手动批准 kubelet-serving CSR——这也是本次实测最有价值的收获。如果不想踩这个坑，可以把该选项去掉或改成 `"false"`，kind 单节点学习环境不轮转证书也没问题。

---

## 九、小结

- `setup-kind.sh` = **建集群 + 装 metrics-server + 装 ingress-nginx** 三合一自动化脚本。
- 三大设计：**幂等（先查再建/装）**、**兜底（代理源回退）**、**等待（rollout status）**。
- 两个 kind 专属处理：`extraPortMappings` 做 80 端口透传；`--kubelet-insecure-tls` 绕过 kind 自签证书校验。
- ⚠️ 实测踩坑：`rotate-server-certificates: "true"` 会产生未批准的 CSR，需 `kubectl certificate approve` 手动批准，否则 metrics-server 不 Ready。
- 跑完它，集群就搭好了，接下来执行 `build.sh → deploy.sh → verify.sh` 即可完整体验 K8s 学习流程。

