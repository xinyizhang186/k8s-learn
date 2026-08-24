# 03 · 推理优化与部署

> 推理部署是大模型工程岗必考。掌握 vLLM、KV Cache、量化、并行,基本每场都问。

---

## 题 1:大模型推理服务怎么扛高并发? ⭐⭐⭐⭐⭐

### 【场景】
要部署 Llama-3-8B 服务,目标 QPS 50、P99 延迟 < 2s。怎么设计?

### 【考察点】
vLLM、PagedAttention、连续 batching、吞吐 vs 延迟权衡

### 【答案要点】

**1. 单卡瓶颈分析**
- LLM 推理是 memory-bound(显存带宽瓶颈),不是 compute-bound
- 单请求延迟 = prefill 时间(处理 prompt)+ decode 时间(逐 token 生成)
- 8B 模型 FP16 约 16GB 权重,单卡 A100 80G 可服务,但单请求吞吐低
- 提吞吐关键:**batching + KV Cache 复用**

**2. 三大核心优化**

**① PagedAttention(vLLM 核心创新)**
- 把 KV Cache 按"页"(block,如 16 token)分配,而非连续内存
- 解决显存碎片 + 浪费,显存利用率从 ~60% 提升到 ~96%
- 类比 OS 虚拟内存分页:逻辑连续、物理离散

**② Continuous Batching(连续 batching)**
- 传统 batching:等批次内所有请求生成完才接新请求 → 短请求被长请求拖累
- 连续 batching:每一步(每个 token)动态调整 batch,有请求完成立刻让新请求加入
- 吞吐提升 2-8x vs 静态 batching

**③ Prefix Caching(前缀缓存)**
- 多请求共享相同前缀(如 system prompt)→ 前缀 KV Cache 算一次,后续请求复用
- vLLM/SGLang 都支持,对 Agent/RAG(同 system prompt)提升明显

**3. 框架选型**

| 框架 | 特点 | 适用 |
|---|---|---|
| **vLLM** | PagedAttention + continuous batching,开源主流 | 通用首选 |
| **SGLang** | RadixAttention(前缀树缓存)+ 结构化输出强 | Agent/复杂控制流 |
| **TGI**(HuggingFace) | 部署简单 | HF 生态 |
| **TensorRT-LLM** | NVIDIA 官方,极致性能 | NVIDIA 生产环境 |
| **LMDeploy** | 量化 + 部署一体 | 国产模型 |
| **llama.cpp** | CPU/边缘部署 | 本地/低资源 |

**4. 推理优化手段叠加**
- **量化**:INT8/INT4 降显存提吞吐(见题 3)
- **Tensor Parallelism**:多卡切模型(见题 6)
- **Speculative Decoding**:小模型先猜大模型验证,降延迟(见题 4)
- **Chunked Prefill**:长输入 prefill 切块,与 decode 交错避免阻塞

**5. 容量规划**
- 显存 = 模型权重 + KV Cache + 激活
- 8B FP16 = 16GB 权重;KV Cache(32k 上下文,batch=32)约 几十 GB
- 单 A100 80G:8B 模型 + 32 并发 8K 上下文可行
- QPS 50:看平均输出长度,连续 batching 下 1-2 张 A100 可达

**6. 服务层**
- 前置网关:限流(令牌桶)+ 路由 + 灰度
- 负载均衡:多卡 round-robin 或按队列长度
- 降级:超载时降配(短输出/换小模型/拒服务)
- 监控:QPS / P50/P99 延迟 / 显存利用率 / KV Cache 命中率 / 队列长度

### 【加分追问】
- **Q: PagedAttention 为什么不默认用?** A: 现在 vLLM 默认开;早期其他框架没集成。它需要修改 attention 实现,有些自定义模型不支持。
- **Q: 50 QPS 怎么算够不够?** A: 单卡吞吐 = batch / (decode_time × output_len);实测 A100 8B FP16 ~2000-4000 token/s;假设平均输出 200 token,QPS 上限约 10-20/卡。50 QPS 需 3-5 张 A100,或量化+优化后更少。
- **Q: prefill vs decode 哪个更耗?** A: prefill 并行处理 prompt,compute 密集;decode 逐 token,memory-bound。长 prompt 的 prefill 一次可能几百 ms;decode 每步几十 ms。

---

## 题 2:KV Cache 是什么?大小怎么估? ⭐⭐⭐⭐⭐

### 【场景】
面试官问:KV Cache 占多少显存?给个估算方法。

### 【答案要点】

**1. KV Cache 是什么**
- Transformer 自回归生成时,每生成一个 token 要 attend 之前所有 token 的 K/V
- 把每层每头的 K/V 缓存,避免重复计算 → 就是 KV Cache
- 显存随序列长度线性增长,是 LLM 推理显存大头

**2. 大小估算公式**

```
KV Cache 显存 = 2 (K和V) × num_layers × num_heads × head_dim × seq_len × batch × dtype_bytes
```

或等价:
```
KV Cache = 2 × num_layers × hidden_dim × seq_len × batch × dtype_bytes
```

**3. 实例:Llama-3-8B**
- 32 层,32 头,head_dim=128 → hidden_dim=4096
- FP16(2 字节),seq_len=8192,batch=1
- = 2 × 32 × 4096 × 8192 × 1 × 2 = 4 GB / 请求
- batch=32 → 128 GB(超单卡!)→ 需要 PagedAttention + 量化

**4. 大模型显存组成**
```
总显存 = 模型权重 + KV Cache + 激活 + 框架开销
```
- 权重:8B FP16 = 16GB
- KV Cache:按上面估,常是大头
- 激活:小,可忽略
- 框架:vLLM 约 1-2GB

**5. 优化 KV Cache**
- **PagedAttention**:分页减少碎片
- **量化**:KV Cache INT8/FP8 减半
- **Prefix Caching**:复用共享前缀
- **Sliding Window Attention**:只缓存最近 N 个 token(Mistral)
- **GQA/MQA**:减少 KV 头数(Llama-3 用 GQA,KV 头数 < query 头数 → KV Cache 砍几倍)

**6. 为什么 GQA 省显存**
- MHA:每个 query 头都有独立 K/V 头 → KV 头数 = query 头数
- MQA:所有 query 头共享 1 个 K/V 头 → KV 头数 = 1(激进)
- GQA:折中,query 头分组共享 K/V → KV 头数 = query 头数 / 组数
- Llama-3-8B:32 query 头,8 KV 头(GQA)→ KV Cache = MHA 的 1/4

### 【加分追问】
- **Q: KV Cache 量化精度损失?** A: INT8 几乎无损;FP8 几乎无损;INT4 有损但近年技术(CacheGen 等)改善。KV Cache 对精度比权重更敏感些。
- **Q: 长 context 时 KV Cache 多大?** A: Llama-3-8B 128K 上下文,batch=1,FP16 ≈ 64GB → 单卡放不下,需多卡或量化或 Sliding Window。
- **Q: 为什么 decode 是 memory-bound?** A: 每生成 1 token,要把整个 KV Cache 读一遍算 attention;算力只需 1 个 token 的矩阵乘,但读 KV 的字节数 >> 算力。Arithmetic Intensity 低。

---

## 题 3:量化方案怎么选? ⭐⭐⭐⭐⭐

### 【场景】
要把 8B 模型塞进单张消费级显卡(如 4090 24GB),怎么量化?选哪个方案?

### 【答案要点】

**1. 量化基础**

| 精度 | 权重大小(8B) | 精度损失 | 备注 |
|---|---|---|---|
| FP16/BF16 | 16GB | baseline | 训练精度 |
| INT8(W8A8) | 8GB | <1% | 几乎无损 |
| INT4(W4A16) | 4GB | 1-3% | 主流量化 |
| INT4(W4A8) | 4GB | 略大于 W4A16 | 兼顾 |

**2. 主流量化方案对比**

| 方案 | 思路 | 优点 | 缺点 |
|---|---|---|---|
| **GPTQ** | 逐层用二阶信息(Hessian)量化 | 精度好,流行 | 量化慢(需校准集) |
| **AWQ** | 找"重要"权重保护(基于激活幅度) | 精度好,推理快 | 需校准集 |
| **SmoothQuant** | 把难量化的激活迁移到权重 | INT8 全量化(W8A8) | 精度好 |
| **GGUF(llama.cpp)** | k-quants,本地部署 | CPU/GPU 混合,易用 | 推理慢于 vLLM |
| **FP8** | 硬件原生(H100+) | 几乎无损,硬件加速 | 需新硬件 |
| **BitNet** | 1.58bit 训练时量化 | 极致小 | 需训练,生态早 |

**3. 选型决策**
- **NVIDIA H100/H200** → FP8(原生硬件加速,无损)
- **NVIDIA A100/4090** → AWQ INT4(精度好,vLLM 支持)
- **CPU/边缘** → GGUF Q4_K_M(llama.cpp)
- **极致性能** → TensorRT-LLM + INT4/INT8
- **国产卡(昇腾等)** → 框架自带量化工具

**4. 关键概念**
- **PTQ(后训练量化)**:训练完直接量化,主流(GPTQ/AWQ)
- **QAT(量化感知训练)**:训练时模拟量化,精度最好但成本高
- **W4A16**:权重 INT4 + 激活 FP16,主流量化(vLLM 默认),精度好
- **W8A8**:权重激活都 INT8,SmoothQuant,吞吐高
- **Group Size**:量化粒度,group=128 是常见值,越小精度越好但开销大

**5. 实战流程(vLLM + AWQ INT4)**
```bash
# 1. 量化(用 AutoAWQ)
# 2. 部署
vllm serve <model> --quantization awq --dtype half
```
- 8B AWQ INT4 ≈ 4-5GB 权重,单 4090 24GB 可跑 8B 还能留 KV Cache 空间

**6. 量化注意点**
- 量化对模型有损,先在评测集跑一遍确认精度
- 不同模型对量化敏感度不同(小模型更敏感)
- KV Cache 也可量化(KV INT8),额外省显存

### 【加分追问】
- **Q: GPTQ 和 AWQ 哪个好?** A: 2024 前后 AWQ 略优(精度+速度),GPTQ 历史更久生态广;实际差距小,看框架支持。W4A16 主流。
- **Q: 为什么不直接 INT4 全量化?** A: 激活有离群值(outlier),INT4 量化激活精度损失大;所以 W4A16(权重 INT4 + 激活 FP16)是主流,SmoothQuant 是解决激活难量化的方案。
- **Q: 量化后推理更快吗?** A: 主要是显存带宽减少→decode 加速(decode 是 memory-bound);prefill(compute-bound)加速有限。INT4 比 FP16 吞吐提升 1.5-2x。

---

## 题 4:投机解码(Speculative Decoding)是什么? ⭐⭐⭐⭐

### 【场景】
听说投机解码能加速推理,原理是什么?什么时候用?

### 【答案要点】

**1. 核心思想**
- 大模型 decode 一次只生成 1 token,慢(memory-bound)
- 用一个小模型先"猜"几个 token,大模型一次验证多个 → 比逐 token 快
- 类比:实习生起草,Senior 审稿,比 Senior 一字字写快

**2. 工作流程**
```
① 小模型(草稿模型)自回归生成 γ 个候选 token
② 大模型(目标模型)一次前向验证这 γ 个 token
③ 接受最长匹配前缀(从第一个不匹配处截断)
④ 拒绝的 token 用大模型分布采样重接
⑤ 重复
```
- 每轮大模型 1 次前向,生成 1-γ 个 token(平均 > 1)
- 加速比 = 平均接受 token 数 / 1

**3. 加速条件**
- 小模型与大模型分布相近(接受率高)
- 小模型快得多(否则验证成本 > 收益)
- 典型:Llama-3-70B + Llama-3-8B 草稿;或同模型量化版当草稿

**4. 变体**
- **Vanilla Speculative**:小模型 + 大模型
- **Medusa**:大模型自己加多个"头"预测多 token,不需小模型
- **EAGLE**:用隐状态预测,接受率更高
- **Lookahead Decoding**:不需草稿模型,自推测
- **Self-Speculative**:同模型 INT4 当草稿,FP16 验证

**5. 适合场景**
- ✅ 长输出生成(草稿模型摊销成本低)
- ✅ 有合适小模型且分布接近
- ❌ 输出短(prefill 主导,优化 decode 没意义)
- ❌ 小模型与目标分布差异大(接受率低,反而慢)

**6. 框架支持**
- vLLM:vLLM V0+ 支持 speculative decoding,需配草稿模型
- SGLang:支持 EAGLE/Medusa
- TensorRT-LLM:支持

### 【加分追问】
- **Q: 接受率怎么估?** A: 实测;同家族模型接受率高(70B+8B Llama 接受率 ~70%);不同家族低。优化草稿模型大小/微调对齐分布可提升。
- **Q: 为什么大模型验证多个 token 不亏?** A: 大模型 attention 算 K/V 一次能并行算多个位置的 logits;1 次前向算 γ 个 token 的验证 ≈ 1 次 decode 的成本(因为 memory-bound,算 γ 个不比 1 个贵多少)。
- **Q: Medusa 不用小模型怎么加速?** A: 在大模型最后一层加多个预测头,每个头预测未来第 i 个 token;训练这些头;推理时并行出多个候选 + 树形 attention 验证。省了草稿模型,但需训练 Medusa 头。

---

## 题 5:长输入/长输出推理怎么优化? ⭐⭐⃞⭐

### 【场景】
用户输入 50K token 文档问问题,模型输出 5K,延迟很高。怎么优化?

### 【答案要点】

**1. 瓶颈分析**
- **Prefill 慢**:50K 输入要全部 attention,compute 密集,单次几百 ms 到秒级
- **KV Cache 大**:50K 的 KV Cache 占大显存,限制并发
- **Decode 长**:5K 输出 = 5000 步 decode,累加延迟

**2. 优化手段**

**① Prefix Caching**
- 多请求共享 system prompt / 固定文档前缀 → 前 KV Cache 算一次复用
- vLLM/SGLang 都支持,SGLang 用 RadixAttention 做前缀树管理

**② Chunked Prefill**
- 长 prefill 切成块(如 512 token),与 decode 交错调度
- 避免长 prefill 阻塞所有 decode 请求
- vLLM 默认开启

**③ KV Cache 量化**
- INT8/FP8 减半显存,提升并发
- 适合长 context 场景

**④ 长输出优化**
- Speculative Decoding(题 4):加速 decode
- 流式输出:边生成边返回,首 token 延迟低
- 投机解码 + 长 output 摊销大

**⑤ 模型层面**
- 用 GQA 模型(Llama-3)KV Cache 小
- 用 Sliding Window(Mistral)限制 KV 增长
- 长上下文模型(如 YaRN/RoPE 扩展)原生长

**3. 系统层面**
- 限制最大输入长度(防止滥用)
- 长输入分批处理 + Map-Reduce 摘要
- 用 RAG 替代长上下文(见 01-rag 题 5)—— 只送相关块

**4. 评估**
- 首 token 延迟(TTFT):prefill 主导
- 每生成 token 延迟(TPOT):decode 主导
- 总延迟 = TTFT + TPOT × 输出长度

### 【加分追问】
- **Q: SGLang RadixAttention 是什么?** A: 用 Radix Tree 管理所有请求的 KV Cache 前缀,自动识别共享前缀并复用;比 vLLM 的 LRU prefix cache 更精细。对 Agent 多轮(同 system prompt)提升明显。
- **Q: 为什么 prefill 慢但 decode 也慢?** A: prefill 是 compute-bound(并行算 prompt 所有位置),但 token 数多所以总时间长;decode 是 memory-bound(每步读全 KV),单步快但步数多。

---

## 题 6:显存不足怎么部署大模型? ⭐⭐⭐⭐

### 【场景】
要部署 70B 模型,单卡 A100 80G 装不下(权重就 140GB FP16)。怎么办?

### 【答案要点】

**1. 三种并行**

| 并行 | 切法 | 适用 | 通信 |
|---|---|---|---|
| **Tensor Parallel(TP)** | 把每层权重按维度切到多卡,每卡算一部分 | 单机多卡 | 高(每层 all-reduce) |
| **Pipeline Parallel(PP)** | 把层分到多卡,数据像流水线过 | 跨机 | 低(只传激活) |
| **Data Parallel(DP)** | 多卡各跑完整模型不同 batch | 有多份模型 | 中(梯度同步,推理少用) |
| **Expert Parallel(EP)** | MoE 专家分到多卡 | MoE 模型 | — |

**2. 选型**
- 单机多卡(GPU 间 NVLink)→ **TP**(通信快)
- 跨机多卡(网络慢)→ **TP + PP**(TP 在机内,PP 跨机)
- 多副本 → **DP**

**3. 70B FP16 部署**
- 权重 140GB,需 2 张 A100 80G(TP=2)或 4 张 A100 40G(TP=4)
- 加 KV Cache,实际要预留更多
- vLLM 启动:`--tensor-parallel-size 2`

**4. 进阶方案**
- **量化**:70B INT4 ≈ 35GB,单 A100 80G 可跑(留 KV Cache)
- **CPU Offload**:权重放 CPU 内存,GPU 算时按层加载;慢但能跑(llama.cpp)
- **ZeRO/Megatron**:训练用,推理少用
- **MoE 模型**:DeepSeek-V3 671B 总参数大但激活小,EP 部署

**5. vLLM 多卡部署**
```bash
vllm serve <model> --tensor-parallel-size 2 --pipeline-parallel-size 1
```

**6. 注意**
- TP 通信开销大,超过 8 卡收益递减
- 跨机部署网络带宽是瓶颈(NVLink > InfiniBand > Ethernet)
- Pipeline Parallel 有气泡(bubble),吞吐有损

### 【加分追问】
- **Q: 推理用 DP 还是 TP?** A: 推理 batch 小时 TP 优(通信摊销);batch 大 DP 也行;实际看模型大小和卡数。常见 TP=2/4/8。
- **Q: 为什么推理不用 ZeRO?** A: ZeRO 是训练优化(切优化器状态/梯度);推理无优化器状态,主要切权重,TP/PP 更直接。
- **Q: 70B 量化后单卡可行吗?** A: AWQ INT4 ≈ 35GB,单 A100 80G 可跑 + 留充足 KV Cache;4090 24G 紧但短 context 可行。

---

## 题 7:推理框架选型:vLLM vs SGLang vs TRT-LLM ⭐⭐⭐⭐

### 【场景】
公司要选推理框架,三选一怎么选?

### 【答案要点】

**1. 主流框架对比**

| 框架 | 优势 | 劣势 | 适用 |
|---|---|---|---|
| **vLLM** | PagedAttention,生态最广,文档好 | 结构化输出/复杂控制流弱于 SGLang | 通用首选 |
| **SGLang** | RadixAttention(前缀树)+ 结构化输出强 | 生态较新 | Agent/结构化输出/共享前缀场景 |
| **TensorRT-LLM** | NVIDIA 官方,极致性能,支持 FP8 | 编译流程重,部署复杂 | NVIDIA 生产环境极致性能 |
| **TGI** | HF 出品,部署简单 | 性能中等 | HF 生态 |
| **LMDeploy** | 量化+部署一体 | 主要适配国产模型 | 国产模型 |
| **llama.cpp** | CPU/边缘/混合 | 吞吐低 | 本地/低资源 |

**2. 决策树**
- 通用服务、模型杂、团队熟 Python → **vLLM**
- Agent / 多轮 / 同 system prompt 多 → **SGLang**(前缀缓存强)
- NVIDIA 卡 + 极致性能预算 → **TensorRT-LLM**
- 边缘/本地/CPU → **llama.cpp**
- 国产模型/国产卡 → **LMDeploy**

**3. 评测维度**
- **吞吐**(tokens/s):QPS / 总 token
- **延迟**:P50/P99/TTFT/TPOT
- **显存利用**:同卡能开多大 batch
- **功能**:结构化输出(前缀/正则约束)、lora 适配、多模态
- **部署便利**:启动复杂度、模型支持广度
- **运维**:监控、日志、稳定性

**4. 工程经验**
- 先 vLLM 起步(最稳生态最广)
- SGLang 在 Agent/RAG(共享前缀多)场景有显著优势,值得 A/B 测
- TRT-LLM 性能最优但工程成本高,大流量才值得
- 生产部署务必加监控 + 多副本 + 负载均衡

### 【加分追问】
- **Q: vLLM 和 SGLang 谁更快?** A: 看场景。vLLM 在通用场景吞吐好;SGLang 在共享前缀(Agent 多轮、相同 system prompt)场景因为 RadixAttention 优势明显。基准见 SGLang 官方 benchmark。
- **Q: 如何 A/B 测推理框架?** A: ① 同硬件同模型 ② 同负载(录线 Query 重放)③ 比 P50/P99/TTFT/TPOT/吞吐/显存 ④ 看功能契合(如结构化输出)。
- **Q: 自研推理引擎值得吗?** A: 一般不值得,除非有特殊硬件或极致优化需求;vLLM/TRT-LLM 已高度优化,自研投入产出比低。

---

## 题 8:推理延迟 vs 吞吐怎么权衡? ⭐⭐⭐

### 【场景】
线上服务,QPS 要求高,但用户体感延迟要低。怎么权衡?

### 【答案要点】

**1. 延迟与吞吐的关系**
- **吞吐优先**(batch 大):每秒处理 token 多,但单请求延迟高(排队等 batch 满)
- **延迟优先**(batch 小/1):单请求快,但吞吐低(算力未充分利用)
- LLM 推理 memory-bound,batch 大摊销更优 → 但单请求延迟受 batch 内最长请求拖累

**2. 关键指标**

| 指标 | 含义 | 影响 |
|---|---|---|
| TTFT(Time To First Token) | 首 token 延迟 | prefill 主导,用户体验 |
| TPOT(Time Per Output Token) | 每生成 token 延迟 | decode 主导 |
| E2E Latency | 总延迟 = TTFT + TPOT × 输出长度 | 端到端体验 |
| Throughput | 单位时间处理 token | 资源利用 |
| QPS | 每秒请求数 | 业务并发能力 |

**3. 权衡策略**
- **流式输出**:首 token 即返回,降低 TTFT 体感(用户等感好)
- **Continuous Batching**:动态 batch,新请求即时加入,兼顾吞吐和延迟
- **优先级队列**:VIP 用户低延迟,普通用户高 batch
- **批大小调节**:低负载 batch 小(低延迟),高负载 batch 大(高吞吐)
- **模型分级**:小模型处理简单请求(快),大模型复杂请求
- **缓存**:相同 Query 答案缓存,命中即返

**4. 实战经验**
- 实时对话:延迟优先,TPOT < 50ms,TTFT < 500ms
- 批处理(夜间总结):吞吐优先,batch 大
- 混合:白天低 batch 高延迟敏感,夜间高 batch 批处理

**5. 监控**
- 实时 P50/P99/TTFT/TPOT + 队列长度 + 显存利用率
- P99 飙升 → 排队多 → 加机器或限流
- TTFT 高 → prefill 慢 → chunked prefill / prefix cache
- TPOT 高 → decode 慢 → 量化 / 投机解码 / 减 batch

### 【加分追问】
- **Q: 流式输出真的降低延迟吗?** A: 不降低总延迟,降低"首字延迟"体感;用户看到第一个字就开始读,体验好。技术上仍是同样总生成时间。
- **Q: 为什么 continuous batching 兼顾延迟和吞吐?** A: 不等 batch 满,有请求就启 batch;新请求随时加入,完成即退出;既不浪费算力(吞吐),又不让请求干等(延迟)。
