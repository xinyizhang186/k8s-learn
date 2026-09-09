# 大模型开发 & Agent 开发 秋招知识点速记手册

> 整理时间：2026-07-29 | 覆盖范围：LLM 基础理论、训练对齐、推理优化、RAG、Agent 设计模式、Agent 框架、MCP 协议、多智能体、评估
> 用途：秋招大模型算法/Agent 工程师岗位面试速记背诵

---

## 目录

1. [大模型基础理论](#1-大模型基础理论)
2. [主流大模型架构对比](#2-主流大模型架构对比)
3. [训练流程与对齐技术](#3-训练流程与对齐技术)
4. [参数高效微调（PEFT / LoRA / QLoRA）](#4-参数高效微调peft--lora--qlora)
5. [推理优化与部署](#5-推理优化与部署)
6. [分布式训练](#6-分布式训练)
7. [Prompt Engineering & CoT](#7-prompt-engineering--cot)
8. [RAG 检索增强生成全流程](#8-rag-检索增强生成全流程)
9. [Agent 设计模式](#9-agent-设计模式)
10. [Agent 框架对比](#10-agent-框架对比)
11. [MCP 协议与多智能体](#11-mcp-协议与多智能体)
12. [评估与幻觉](#12-评估与幻觉)
13. [高频面试题速记表](#13-高频面试题速记表)

---

## 1. 大模型基础理论

### 1.1 Transformer 架构

**核心组件**：Encoder + Decoder（原始论文），但现代 LLM 多为 **Decoder-Only**。

| 架构 | 代表模型 | 擅长任务 |
|------|---------|---------|
| Encoder-Only | BERT | 理解类（分类、NER、检索） |
| Decoder-Only | GPT 系列、LLaMA、Qwen | 生成类（对话、续写） |
| Encoder-Decoder | T5、BART | 翻译、摘要 |

**Decoder-Only 为何成为主流**：自回归生成能力强，Scaling Law 友好，in-context learning 能力涌现。

### 1.2 自注意力机制（Self-Attention）

**公式**：`Attention(Q, K, V) = softmax(QK^T / √d_k) · V`

- **Q/K/V**：通过三个线性投影矩阵把输入映射成 Query、Key、Value。
- **softmax 前除 √d_k**：防止点积过大导致 softmax 梯度消失（点积方差随 d_k 线性增长）。
- **为什么比 RNN 强**：并行计算（RNN 必须序列计算）、长程依赖直接建模（任意两 token 一步可达）。

### 1.3 多头注意力演进：MHA → MQA → GQA

| 方案 | KV 头数 | 推理 KV Cache 显存 | 质量 | 适用 |
|------|--------|-------------------|------|------|
| MHA（标准多头） | = Q 头数 | 最大 | 最好 | 训练 |
| MQA（Multi-Query） | 1 | 最小（1/N） | 略损 | 极致推理 |
| GQA（Grouped-Query） | 分组共享（如 8 组） | 中等 | 接近 MHA | **生产主流**（LLaMA-2/3） |

**核心动机**：推理时 KV Cache 是显存大头，减少 KV 头数 = 减少 KV Cache = 喂更长 context / 更大 batch。GQA 是 MHA 与 MQA 的折中。

### 1.4 位置编码（Position Encoding）

Transformer 无位置感知，需显式注入位置信息。

| 方案 | 原理 | 优缺点 |
|------|------|--------|
| 绝对正弦（sin/cos） | 固定三角函数 | 简单、不能外推 |
| 可学习绝对位置 | 学一个 embedding 表 | 长度上限固定 |
| **RoPE 旋转位置编码** | 在 Q/K 上施加旋转矩阵，相对位置信息隐式编码 | **主流**；外推有挑战（需 YaRN/NTK-aware 修复） |
| ALiBi | 在 attention score 上加线性偏置 | 外推好，但表达力弱于 RoPE |

**RoPE 要点**：把二维实数对当复数旋转，旋转角度与位置 m 成正比；两点相对位置决定内积，因此是相对位置编码的"绝对实现"。LLaMA / Qwen / DeepSeek 全用 RoPE。

### 1.5 分词器（Tokenizer）

| 算法 | 原理 | 代表 |
|------|------|------|
| BPE | 从字符出发，按频率合并最高频字节对，直到词表上限 | GPT 系列、LLaMA |
| WordPiece | 类 BPE，但用似然而非频率选合并对 | BERT |
| SentencePiece | 不依赖空格，直接对原始字节流做 BPE/Unigram | 多语言 LLM（LLaMA、T5） |

**关键概念**：
- **Token**：分词后的最小单元，1 token ≈ 4 个英文字符 ≈ 0.75 个中文字。
- **词表大小**：LLaMA-2 32k，LLaMA-3 128k，Qwen 152k（中文友好）。
- **特殊 token**：`<s>`、`</s>`、`<pad>`、`<eos>`，SFT 时 Chat Template 必须正确否则训练崩溃。

### 1.6 Scaling Law 与涌现能力

**Scaling Law**（Kaplan/Chinchilla）：Loss ≈ A·N^(-α) + B·D^(-β) + E，模型性能由参数量 N、数据量 D、计算量 C 共同决定。

- **Chinchilla 最优比**：每个参数训练约 **20 个 token**（旧 Kaplan 是 1.7 token/参数，过少）。
- **涌现能力（Emergent）**：模型规模到某一阈值（常 10B+ 参数）后突现 in-context learning、CoT 推理等能力，小模型完全没有。

### 1.7 解码策略

| 策略 | 原理 | 用途 |
|------|------|------|
| Greedy | 每步取概率最高 token | 确定性、易重复 |
| Beam Search | 保留 top-B 路径 | 翻译/摘要；不擅长开放生成 |
| Top-K Sampling | 在概率最高的 K 个里采样 | 多样性；K 固定可能不合理 |
| **Top-P（Nucleus）** | 累积概率 ≤ P 的最小集合内采样 | **主流**，自适应 K |
| Temperature | 除 T 控制分布尖锐度 | T↑ 多样性↑；T↓ 确定性↑ |

**生产经验**：对话一般 temperature=0.7、top_p=0.9、top_k=50；代码/抽取 temperature=0~0.2。

### 1.8 MoE 混合专家模型

**原理**：用 Router（门控网络）对每个 token 选 Top-K 个专家（FFN 层）激活，总参数量大但单 token 激活参数小，推理成本可控。

- **DeepSeek-V3**：总参数 671B，激活 37B；用 **MLA（Multi-head Latent Attention）** 进一步压缩 KV Cache。
- **Mixtral 8x7B**：8 个专家每次激活 2 个。
- **难点**：负载均衡（避免个别专家过载）、通信开销、serving 调度复杂。

### 1.9 激活函数与归一化

- **SwiGLU**：LLaMA / Qwen / DeepSeek 通用，`SwiGLU(x) = Swish(W1·x) ⊙ (W2·x)`，比 ReLU/GELU 表达力强。
- **RMSNorm**：LLaMA 系列用，去掉 LayerNorm 的均值减法，只做方差归一化，更快、效果相当。
- **Pre-Norm**：现代 LLM 全用 Pre-Norm（残差连接前归一化），训练更稳定，比 Post-Norm（原始 Transformer）不易梯度爆炸。

### 1.10 FlashAttention

- **不减少计算量**，但通过 **分块（tiling）+ 在 SRAM 内做 softmax 增量计算**，避免 HBM 反复读写，**显存降低 + 速度提升 2-4 倍**。
- **FlashAttention-2**：优化并行度（沿序列维度切分），A100 上接近 50% MFU。
- **FlashAttention-3**：针对 H100 的异步 TMA / WGMMA 进一步加速。

---

## 2. 主流大模型架构对比

| 模型 | 架构 | 注意力 | 位置编码 | 归一化 | 激活 | 特点 |
|------|------|--------|---------|--------|------|------|
| LLaMA-2/3 | Decoder-Only | GQA | RoPE | RMSNorm | SwiGLU | 开源标杆，3 代 128k 词表，3.1 支持 128k 上下文 |
| Qwen2/2.5/3 | Decoder-Only | GQA | RoPE | RMSNorm | SwiGLU | 中文最强开源；Qwen3 引入"混合思考"（thinking mode 开关） |
| DeepSeek-V3 | MoE Decoder | **MLA** | RoPE | RMSNorm | SwiGLU | 671B/激活 37B，MLA 极致压缩 KV Cache，性价比 SOTA |
| DeepSeek-R1 | 推理模型（V3 后训练） | MLA | RoPE | - | - | RL（GRPO）训练出强 CoT 推理能力，对标 o1 |
| GLM-4 | Decoder-Only Prefix-LM 变体 | - | RoPE | - | - | 智谱出品，双语友好 |
| MiniMax | Decoder-Only | **Lightning Attention**（线性） | - | - | - | 线性注意力，超长上下文友好 |

**MLA（Multi-head Latent Attention，DeepSeek 创新）**：把 KV 联合低秩压缩到一个 latent 向量，推理时只缓存 latent，KV Cache 大小可降到 MHA 的 1/10 量级，是 DeepSeek 长上下文 + 低成本的关键。

---

## 3. 训练流程与对齐技术

### 3.1 三阶段范式

| 阶段 | 目标 | 数据 | Loss | 一句话 |
|------|------|------|------|--------|
| **Pretrain** | 学语言能力 + 世界知识 | 海量无标注文本（T 级 token） | 全序列交叉熵 | "会说话" |
| **SFT** | 学指令遵循 + 任务格式 | 高质量（指令，回答）对（10w~百万） | 只算 response 部分交叉熵 | "听指令" |
| **RLHF/DPO** | 对齐人类偏好（有用、无害、诚实） | 偏好对（chosen, rejected） | PPO / DPO 损失 | "说得好" |

### 3.2 SFT 关键细节

- **Loss 屏蔽**：labels 中 prompt 部分**设为 -100**（PyTorch `ignore_index`），只对 response 部分反向传播。否则模型浪费容量学 prompt 分布。
- **Shift right**：logits 去掉最后一个，labels 去掉第一个，对齐做下一个 token 预测。
- **Chat Template**：必须用模型官方模板（如 LLaMA-3 的 `<|begin_of_text|><|start_header_id|>user<|end_header_id|>`），错用会导致训练崩坏。
- **数据配比**：简单:中等:困难 ≈ 3:5:2；长度短中长混合；质量 > 数量（LIMA：1k 高质量数据即可显著对齐）。
- **超参经验**：lr 1e-5 ~ 5e-5，1-3 epoch，warmup_ratio 0.03，cosine scheduler。

### 3.3 RLHF 三阶段（经典 PPO 流程）

1. **SFT**：先有监督微调一个初始策略模型。
2. **奖励模型 RM 训练**：用成对偏好数据（A 比 B 好），损失为 Bradley-Terry：`L = -log σ(r(A) - r(B))`；RM 通常从 SFT 模型初始化。
3. **PPO 强化学习**：4 个模型同台
   - **Actor（策略）**：要训练的 LLM
   - **Critic（价值）**：估 baseline，降低方差
   - **Reference（参考）**：冻结的 SFT 模型，**KL 惩罚**防止偏离过远
   - **Reward（奖励）**：RM 打分

   目标：`max E[r(x,y)] - β·KL(π || π_ref)`，β 是 KL 系数。

**PPO 关键技巧**：优势归一化、值函数 clipping、熵正则化（防过早收敛）、reward scaling。

### 3.4 DPO（Direct Preference Optimization）

**核心思想**：把"训练 RM + PPO"绕过，**直接用偏好对优化策略**，无需 RM。

- **损失**：`L_DPO = -log σ(β·(log π(y_w)/π_ref(y_w) - log π(y_l)/π_ref(y_l)))`
- **β**：控制偏离参考模型的程度，β 大 → 更激进对齐，β 小 → 更保守。增大风险：reward hacking、风格谄媚。

**PPO vs DPO 对比**：

| 维度 | PPO | DPO |
|------|-----|-----|
| 需要 RM | ✅ | ❌ |
| 在线采样 | ✅（生成新回答） | ❌（只用离线偏好对） |
| 训练稳定性 | 差（4 模型同时动） | 好 |
| 实现复杂度 | 高 | 低 |
| 上限 | 高（可探索超示范回答） | 受限（受偏好数据质量约束） |
| 计算成本 | 高 | 低 |

**选型**：偏好数据少且高质量 → DPO；要超越示范、多目标权衡 → PPO。

### 3.5 GRPO（DeepSeek 提出，R1 训练用）

- **Group Relative Policy Optimization**：去掉 Critic 模型，对一个 prompt 采样一组回答，用组内 reward 的均值/方差做 baseline（**组内相对优势**）。
- **优势**：省一个 Critic 模型，显存省一半；训练更稳。
- **RLVR**（Reinforcement Learning with Verifiable Reward）：reward 用**可验证规则**（如数学答案对错、代码测试通过），二元 0/1，无需 RM，是 R1 推理能力训练的核心。

### 3.6 其他对齐技术速记

- **RLAIF**：用 AI（而非人）打偏好分，降低标注成本（Constitutional AI）。
- **DAPO / Dr.GRPO**：2025 前沿改进，去 bias、稳训练。
- **拒绝采样微调（RFT）**：对 SFT 模型采样多个回答，挑 reward 高的再 SFT，简单有效。
- **Knowledge Distillation**：大模型当 teacher，小模型学其 logits/输出分布。

---

## 4. 参数高效微调（PEFT / LoRA / QLoRA）

### 4.1 LoRA（Low-Rank Adaptation）

**核心**：冻结原权重 W₀，加一个低秩增量 ΔW = B·A，其中 A∈ℝ^(r×k)、B∈ℝ^(d×r)，r << min(d,k)。
LoRA 用两个小矩阵近似完整权重更新，大幅减少需要训练的参数量。
LoRA 几乎不会增加推理延迟（合并权重后）。
补充：如果选择不合并（merge），推理时会额外计算 BAx，会有轻微开销。因此生产部署通常会先 Merge Adapter。

- **前向**：`h = W₀x + BAx`
- **可训练参数**：仅 A、B，约占总参数 0.1%~1%。
- **推理时合并**：`W = W₀ + BA`，**不增加推理延迟**。
- **目标模块**：通常加在 `q_proj`、`v_proj`，也可扩展到 `k_proj`、`o_proj`、FFN 的 `gate/up/down_proj`（全 Linear LoRA 效果更好）。

**关键超参**：
- `r`（秩）：8~64，越大表达力越强但易过拟合，7B 一般 r=16~32。
- `lora_alpha`：缩放因子，实际缩放为 α/r，通常 α=2r。
- `lora_dropout`：0.05~0.1 防过拟合。
- `target_modules`：先 q/v，效果不够再加 k/o 和 FFN。

### 4.2 QLoRA = 4bit 量化 + LoRA

**三大创新**：
1. **NF4（NormalFloat4）**：4-bit 量化，假设权重服从正态分布，量化分位点等概率，精度损失最小。
2. **双重量化（Double Quantization）**：把量化的常量再量化一次，省额外显存。
3. **分页优化器（Paged Optimizer）**：用 NVIDIA 统一内存，GPU 显存不够时溢出到 CPU。

**显存对比（7B 模型）**：

| 方案 | 显存 | 备注 |
|------|------|------|
| 全参 FP16 | ~60 GB | 多卡 |
| LoRA FP16 | ~12 GB | |
| **QLoRA 4-bit** | **~6 GB** | 单 4090 可训 7B；A100 单卡可训 65B |

**典型代码骨架**：
```python
from transformers import BitsAndBytesConfig, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.bfloat16,  # 反量化后用 bf16 计算
)
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Meta-Llama-3-8B",
    quantization_config=bnb_config, device_map="auto"
)
model = prepare_model_for_kbit_training(model)  # 把 LN/embedding/output 保 FP32，稳训练

lora_config = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    bias="none", task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
```

### 4.3 为什么 SFT 后还要 RL（高频考点）

- SFT 只能**模仿**示范回答，无法学习"A 比 B 好"的**相对偏好**。
- 偏好是**相对关系**，SFT 需要绝对正确答案，无法直接利用偏好对（直接对 chosen 做 SFT 会丢失"比 rejected 好"的信息）。
- RL 能让模型探索超示范的回答，SFT 不能。
- 多目标权衡（有用 vs 无害）RL 更灵活。

SFT 主要学习人类示范数据的分布，使模型具备指令跟随能力，但它无法表示不同回答之间的质量偏好。
RL 通过奖励函数优化模型输出概率，使模型更倾向生成符合人类偏好、更有帮助、更安全的回答。因此 SFT 解决“模型会不会回答”，RL 解决“模型回答得好不好”。
---

## 5. 推理优化与部署

### 5.1 KV Cache（自回归推理核心）

**原理**：自回归生成时，每生成一个新 token，前面所有 token 的 K、V 中间结果可复用，缓存下来避免重算。

- **只有 K、V 有 Cache**，Q 是当前 token 单步，无需缓存。
- **显存大头**：KV Cache 大小 ≈ `2 × num_layers × seq_len × hidden_dim × batch × dtype_bytes`，长上下文下可达数十 GB。
- **MHA/MQA/GQA 影响**：减少 KV 头数直接减 KV Cache。

Q1：KV Cache 为什么缓存 K 和 V，不缓存 Q？
回答：因为自回归生成时，历史 token 的 Key 和 Value 不会变化，可以重复利用；而 Query 只与当前生成 token 相关，每一步都会变化，因此只计算当前 Query。

### 5.2 推理框架对比
大模型推理框架的核心目标：不是让模型“更聪明”，而是让同一模型在有限 GPU 资源下生成得更快、更省显存、更高吞吐。

| 框架 | 特点 | 适用 |
|------|------|------|
| **vLLM** | **PagedAttention + Continuous Batching**；吞吐比 HF 高 14-24x | GPU 服务首选 |
| TGI（HF） | 生产稳定，OpenAI 兼容 API | 商用 |
| llama.cpp | C++/GGUF，CPU/边缘 | 个人/低资源 |
| TensorRT-LLM | NVIDIA 官方，极致延迟 | 生产低延迟 |
| SGLang | RadixAttention（前缀复用），结构化输出强 | 高并发 |

### 5.3 vLLM 三大核心技术

1. **PagedAttention**：把 KV Cache 按固定大小分**物理块**管理（类似 OS 虚拟内存分页），逻辑块连续、物理块可不连续；解决碎片化，KV Cache 利用率从 ~50% 提到 ~96%。
2. **Continuous Batching（动态批处理）**：传统 static batching 等最长序列结束才返回，短序列浪费算力；continuous batching 一旦某序列生成完立即让位给队列下一个，**GPU 利用率最大化**。
3. **Prefix Caching**：相同前缀（如 system prompt）的 KV Cache 跨请求复用，TTFT 显著降低。

### 5.4 量化（Quantization）

| 方案 | 位宽 | 特点 |
|------|------|------|
| INT8 | 8-bit | 损失极小，bitsandbytes |
| GPTQ | 4-bit | 一阶量化，需校准数据，精度高 |
| AWQ | 4-bit | 基于激活分布保护重要权重，速度比 GPTQ 快 |
| **GGUF** | 2-8-bit | llama.cpp 用，CPU/混合推理 |
| NF4 | 4-bit | QLoRA 用，正态分布假设 |

**经验**：4-bit 量化模型大小约为 FP16 的 1/4，精度损失通常 <2%；GPTQ 精度更优，AWQ 速度更快，GGUF 适合 CPU 部署。

### 5.5 推理性能指标

- **TTFT（Time To First Token）**：首字延迟，受 prefill 阶段影响。
- **TPOT（Time Per Output Token）**：每 token 生成时间，受 decode 阶段影响。
- **吞吐量**：tokens/s，受 batch size、KV Cache 占用影响。

**Prefill vs Decode 不对称**：prefill 是 compute-bound（一次算所有 prompt token 的 KV），decode 是 memory-bound（每步只算 1 个 token，但要读全部 KV Cache）。这是 **Prefill-Decode 分离（Disaggregated P/D）** 架构的动机。

### 5.6 其他推理优化

- **推测解码（Speculative Decoding）**：小模型/草稿模型先猜几个 token，大模型并行验证，命中则跳步，**不改变输出分布**，TTFT 不变但吞吐提升。
- **FlashAttention**：见 1.10。
- **Prefix Caching / Prompt Caching**：见 5.3。
- **张量并行（TP）**：把权重矩阵切到多卡，减少单卡显存。
- **流水线并行（PP）**：按层切到多卡。

---

## 6. 分布式训练

### 6.1 并行策略

| 并行 | 切分维度 | 通信量 |
|------|---------|--------|
| **数据并行 DP** | 每卡完整模型，切 batch | AllReduce 梯度 |
| **张量并行 TP** | 切单层权重矩阵 | 每层 AllReduce |
| **流水线并行 PP** | 切层到不同卡 | 相邻层间点对点 |
| **序列并行 SP** | 切序列长度 | 减少 attention 通信 |
| **ZeRO** | 切优化器状态/梯度/参数 | 通信换显存 |

### 6.2 ZeRO 三阶段（DeepSpeed）

| Stage | 切分对象 | 显存节省 | 通信 |
|-------|---------|---------|------|
| ZeRO-1 | 优化器状态 | 4x | 与 DP 同 |
| ZeRO-2 | + 梯度 | 8x | 与 DP 同 |
| ZeRO-3 | + 参数 | ~Nx | 增加通信（需 AllGather 参数） |

**经验**：显存够用优先 ZeRO-2（通信少）；显存紧张用 ZeRO-3 + offload 到 CPU。

### 6.3 显存优化技巧

- **混合精度训练（BF16/FP16）**：前向反向用 16-bit，主权重保 FP32，省一半显存。
- **梯度累积（Gradient Accumulation）**：小 batch 多次前向累加梯度再更新，等价大 batch。
- **梯度检查点（Gradient Checkpointing）**：只存部分层激活，反向时重算，省 30%+ 显存，时间换空间。
- **CPU Offload**：把优化器状态/参数放到 CPU 内存（ZeRO-Offload）。

### 6.4 训练框架

- **DeepSpeed**：微软，ZeRO 系列，易用。
- **Megatron-LM**：NVIDIA，TP+PP 工业级组合。
- **FSDP**：PyTorch 原生，类 ZeRO-3。
- **veRL / OpenRLHF**：2025 RL 后训练专用框架。

---

## 7. Prompt Engineering & CoT

### 7.1 提示工程技巧

- **Zero-shot**：直接给指令。
- **Few-shot**：给几个示例（输入→输出），范式对齐。
- **CoT（Chain-of-Thought）**："Let's think step by step"，让模型先写推理过程再给答案。对数学、逻辑推理提升显著。
- **Self-Consistency**：采样多条 CoT，投票多数答案，提升鲁棒性。
- **ToT（Tree of Thoughts）**：搜索式推理，分支探索+回溯，适合复杂规划。
- **ReAct**：见 9.1。

**CoT 局限**：靠"let's think step by step"触发的 CoT 是**被动模仿**，上限受基模推理能力约束；推理型模型（o1/R1）通过 RL 训练 CoT 是**主动探索**，上限更高。

### 7.2 Prompt 注入防御

- 把用户输入用分隔符（如 ```）隔离，避免覆盖系统指令。
- 明确告诉模型"仅基于下方上下文回答"。
- 高风险动作（转账、删数据）必须人工确认（Human-in-the-Loop）。

---

## 8. RAG 检索增强生成全流程

### 8.1 RAG 是什么 & 为什么

**RAG（Retrieval-Augmented Generation）**：生成前先从外部知识库检索相关文档片段，拼进 prompt，把"封闭考试"变"开卷考试"。

**优势**：相比微调，**成本低、数据可实时更新、可溯源、幻觉更少**。

**架构演进**：
- **Naive RAG**（2023）：检索→拼接。
- **Advanced RAG**（2024-25）：加 Query 重写、HyDE、重排序、Self-RAG、CRAG。
- **Modular RAG**（2025-26 当前主流）：每组件可插拔。
- **Agentic RAG**（2026）：Agent 自主决定何时检索、检索几次、是否要二次检索。

### 8.2 标准 6 步流水线

```
离线：原始文档 → 解析 → Chunking → Embedding → 写入向量库
在线：用户问题 → Query 改写 → Embedding → 向量召回 Top-K → Re-rank Top-N → 拼 Prompt → LLM 生成 → 带"引用"输出
```

### 8.3 Chunking 分块策略（灵魂参数）

| 策略 | 大小推荐 | 优点 | 缺点 |
|------|---------|------|------|
| 固定长度 | 512 token | 简单 | 易割裂语义 |
| 按句子/段落 | 一段 | 保语义 | 长度不均 |
| **递归字符**（LangChain 默认） | 400-600 + 10% overlap | 兜底稳 | 仍可能切错 |
| 语义分块 | 阈值 0.5-0.8 | 质量最高 | 慢/贵 |
| **父子分块** | 小块检索、大块返回 | 精度+上下文双赢 | 双索引 |
| Agentic 分块 | LLM 决边界 | 最智能 | 成本高 |

**关键经验**：
- **甜区 512 token + 10% overlap**。
- **上下文悬崖（Context Cliff）**：chunk > 2500 token 后质量显著下降，即使上下文窗口够。
- **Lost in the Middle**：LLM 对长上下文中间部分注意力弱，重要信息放首尾。

### 8.4 Embedding 模型

| 模型 | 维度 | 多语言 | 场景 |
|------|------|--------|------|
| OpenAI text-embedding-3-large | 3072 | ✓ | 通用 |
| **BGE-M3（智源）** | 1024 | 中英 | **中文首选** |
| Cohere Embed v3/v4 | 1024 | ✓ | 配合 rerank |
| Jina v3 | 1024 | ✓ | 长上下文 |
| GTE-Qwen2（阿里） | 1024 | 中英 | 开源中文强 |

**铁律**：
1. **query 和 doc 必须用同一版本 embedding 模型**，版本漂移 = 召回崩溃（OpenAI 静默更新过 embedding，无数项目踩坑）。
2. 换 embedding 模型 = **全量重建索引 + 双写灰度**。
3. MTEB 排行榜看 **Retrieval 子榜**，别看总分。
4. 1024 维是甜区，超大规模（>10亿）可考虑 Matryoshka 截断到 256。

### 8.5 向量数据库选型

| 数据库 | 语言 | 索引 | 适用规模 | 特色 |
|--------|------|------|---------|------|
| Milvus | Go+C++ | HNSW/IVF/DiskANN | 10亿+ | 分布式，云原生 |
| Qdrant | Rust | HNSW | 千万 | 单机性能强，Hybrid 原生 |
| pgvector | C(PG扩展) | HNSW/IVFFlat | <1000万 | 复用 PG，SQL 联表 |
| Chroma | Python | HNSW | 原型 | 开箱即用 |
| Pinecone | 闭源 SaaS | - | 任意 | 零运维 |
| Weaviate | Go | HNSW | 中大 | GraphQL + BM25 内置 |

**选型口诀**：<100万会话缓存→Redis Vector；<1000万要 SQL 联表→pgvector；>1000万 UGC 高 QPS→Milvus/Qdrant；零运维→Pinecone；知识图谱+向量→Weaviate。

### 8.6 ANN 算法

| 算法 | 原理 | 召回 | 延迟 | 内存 | 规模 |
|------|------|------|------|------|------|
| **HNSW** | 分层小世界图 | 0.95+ | 1-5ms | 高 | <1亿（主流默认） |
| IVF-PQ | 倒排+乘积量化 | 0.85-0.92 | 5-20ms | 低（压缩 1/10） | >1亿 |
| DiskANN | 图+SSD | 高 | 中 | 极低 | >10亿 |

**HNSW 关键参数**：`M`=16（每节点边数）、`efConstruction`=200（建图）、`efSearch`=64-128（查询）。

### 8.7 混合检索（Hybrid Search）

**为什么**：纯向量检索对**精确词匹配**（产品编号、人名、错误码）失效（失败率高达 30%），BM25 对语义转述不敏感。两者互补。

**架构**：BM25（关键词）+ 向量（语义）双路召回 → **RRF（Reciprocal Rank Fusion）融合** → Top-N。

**RRF 公式**：`score = Σ 1/(k + rank_i)`，k 通常取 60，不看分数绝对值只看排名，避免两路分数量纲不同。

**结论**：Hybrid 几乎在所有场景都比单路好，提升 5-15%，专业领域（法律/医疗/金融）更明显。**应作为默认方案**。

### 8.8 Re-ranking 重排序

**为什么**：Bi-encoder（向量检索）query/doc 各自编码，**无细粒度交互**，能保证 Top-50 含正确答案但难保证 Top-1。

**做法**：Cross-encoder 把 query+doc 拼起来过 BERT 类模型，捕捉细粒度匹配，精度高但慢（20-50ms/对）。

**生产模式**：Bi-encoder 召回 Top-100 → Cross-encoder 重排 Top-10 → LLM 生成。**ROI 最高的单一优化**，加 rerank 通常 +5-15 NDCG。

**模型**：Cohere Rerank、BGE-reranker-v2-m3、Jina Reranker。注意许可证（部分非商业）。

### 8.9 Query 重写（Advanced RAG）

- **查询扩展**：同义词替换提升召回。
- **查询分解**：复杂问题拆多个子查询分别检索。
- **HyDE（Hypothetical Document Embedding）**：先让 LLM 生成"假想答案"，用假想答案的向量去检索（假想答案与真实文档语言风格更接近，比原问题检索更准）。
- **多轮对话 Query 重写**：把"它怎么样"这类指代消解为完整问题再检索。

### 8.10 RAG 评估（RAGAS 五大指标）

| 指标 | 含义 |
|------|------|
| **Faithfulness（忠实度）** | 答案是否完全来自检索内容（无幻觉） |
| **Answer Relevancy（答案相关）** | 答案是否回答了问题 |
| **Context Precision（上下文精度）** | 检索内容中有用比例 |
| **Context Recall（上下文召回）** | 是否检索到所有需要的信息 |
| **Context Relevance** | 检索内容与问题的相关度 |

**生产铁律**：从第一天就建评估集（哪怕 50 条），没量化指标 = 盲飞。

### 8.11 生产 RAG 红线

1. **Pin embedding 版本**（防静默更新翻车）。
2. **引用来源**（每个答案可追溯到文档）。
3. **Metadata filter**（按权限/时间/类型过滤检索范围）。
4. **双索引灰度升级**（换 embedding 时新旧并存）。
5. **语义缓存**（相似 query 复用结果，省成本）。

---

## 9. Agent 设计模式

### 9.1 ReAct（Reasoning + Acting）

**核心**：LLM 交替输出 **Thought（推理）→ Action（调工具）→ Observation（观察结果）**，循环直到出最终答案。

- **优点**：每步基于真实观测，不易幻觉前进；可解释。
- **缺点**：每步一次完整 LLM 调用，**token 成本随步数线性增长**；无回溯，错一步可能一路错到底。
- **适用**：3-5 步短探索性任务，下一步依赖上一步结果（如调试、网页搜索）。
- **论文**：Yao et al. 2022（arXiv 2210.03629）。

### 9.2 Plan-and-Execute

**核心**：两阶段分离。
1. **Planner**：一次性生成完整多步计划。
2. **Executor**：按计划逐步执行，必要时 **re-plan**。

| 对比 | ReAct | Plan-and-Execute |
|------|-------|-----------------|
| 计划时机 | 每步临时 | 一次性前置 |
| 成本 | N 次推理 | 1 次大计划 + N 次小执行 |
| 自适应 | 强（每步看到结果） | 弱（计划可能基于过时假设） |
| 适用 | 探索/调试 | 结构化、可并行、可预测成本的任务（如报告生成） |

**生产实践**：通常 **Plan-and-Execute 做外层 + ReAct 做内层**，外层分解子目标，内层自适应执行。

### 9.3 Reflexion（反思）

**核心**：完成一轮 trajectory 后，**自我批评**生成"经验教训"，存入 episodic memory，下次重试时参考。

- 论文：Shinn et al. 2023（arXiv 2303.11366），HumanEval pass@1 从 GPT-4 的 80% 提到 91%。
- **适用**：可重试任务（代码生成、数学、多步检索——结果可验证）。
- **不适用**：不可逆动作（发邮件、转账）——重试会重复执行。

### 9.4 Tree of Thoughts（ToT）

**核心**：分支探索多个推理路径，评估每条路径，剪枝+回溯，类似搜索算法。

- 适用：组合优化、数学竞赛、策略类问题。
- 缺点：token 消耗指数级增长。

### 9.5 Agent Loop 与停止条件

**最小循环**：`perceive → reason → act → observe → repeat`，直到 emit "final answer"。

**生产必备的三道停止闸**（缺一不可，否则就是 4 万美元事故）：
1. **max_iterations**（硬步数上限）。
2. **max_tokens / max_cost**（token/金钱预算闸）。
3. **重复检测**（同一工具+同一参数连续调用 ≥2 次则停）。
4. **max_seconds**（墙钟时间）。

### 9.6 Agent 的记忆

| 类型 | 存储 | 作用 |
|------|------|------|
| **短期记忆** | 当前 context window | 当前对话+工具结果+推理轨迹 |
| **长期记忆** | 向量库（Pinecone/Qdrant） | 用户偏好、历史事实，语义检索 |
| **Episodic 记忆** | 结构化日志 | 历史 trajectory，Reflexion 用它做自我批评 |

**context 漂移问题**：随 history 增长，模型对 system prompt 的"权重"下降，可能重做已完成的步骤。解法：维护"已完成工具调用"的显式可见记录。

### 9.7 Tool Use / Function Calling

**Function Calling 是 API 机制**：模型输出结构化 JSON（函数名+参数），代码执行后把结果回喂。
**Tool Use 是更广义模式**：包含 ReAct 这类自由文本解析的工具调用。

**好工具的三原则**：
1. **描述性参数名** + 描述里给示例。
2. **严格类型**（string/number 选一，别 union；用 enum 限定已知值）。
3. **Schema 小**（参数越少越可靠，15 参数的怪物的调用失败率极高）。

**错误反馈格式**：失败时返回 `{"error": "...", "type": "...", "hint": "..."}`，**不要**贴堆栈、**不要**吞错假装成功。

**并行工具调用**：模型一轮 emit 多个 tool_use 块且工具间无依赖 → 并行执行（asyncio.gather / Promise.all）→ 一起返回结果再进下一轮。**不要跨轮并行**（那是并发不是并行）。

### 9.8 生产 Agent 四大加固

1. **三道预算闸**（见 9.5）。
2. **工具错误结构化反馈**（见 9.7）。
3. **沙箱隔离**（代码执行用 Firecracker microVM / E2B / Modal，禁止访问 host 凭据）。
4. **持久化 checkpoint**（长任务用 Temporal/Inngest/Vercel Workflow，断点续传免超时）。

### 9.9 Agentic AI 定义

> Agent = LLM 在循环里**动态决定下一步做什么**；Workflow = 代码编排 LLM 调用顺序。

关键区分：**谁控制执行顺序**——代码控制是 workflow，LLM 控制是 agent。

---

## 10. Agent 框架对比

### 10.1 主流框架速览

| 框架 | 定位 | 强项 | 上手 | 适用 |
|------|------|------|------|------|
| **LangChain** | 全能通用 | 生态最大、工具最多、Agent 全 | 中等偏难 | 通用 Agent 开发 |
| **LlamaIndex** | 数据连接 | RAG 最强、文档接入方便 | 简单 | 知识库问答为主 |
| **LangGraph** | 图编排（LangChain 官方） | 状态机、循环/分支/持久化、可控 | 中等 | **生产级复杂多 Agent 工作流** |
| **AutoGen**（微软） | 对话式多 Agent | Actor 模型、异步消息、可分布式 | 中等 | 代码评审、辩论、头脑风暴 |
| **CrewAI** | 多 Agent 协作 | 角色+任务模式直观 | 简单 | 多角色团队任务（写报告、调研） |
| **MetaGPT** | 软件公司模拟 | SOP 流程、PM/架构师/工程师角色 | 中等 | 端到端软件开发自动化 |
| **AutoGPT** | 自主 Agent 先驱 | 长任务全自动 | 极简（免代码） | 探索/玩具，**生产慎用**（易跑偏、烧 token） |
| **Qwen-Agent** | 阿里国产 | 中文文档、低代码、国产模型适配 | 极简 | 国内私有化、企业知识库 |

### 10.2 选型决策树

- **知识库问答（RAG 为主）** → LlamaIndex 或 Qwen-Agent
- **通用 Agent（多工具对话）** → LangChain
- **多角色团队协作（简单）** → CrewAI
- **复杂生产级多 Agent 工作流** → **LangGraph**（状态机，可控可恢复，**生产首选**）
- **开放式对话式协作** → AutoGen
- **端到端软件开发** → MetaGPT
- **国内私有化 + 国产模型** → Qwen-Agent

### 10.3 LangChain 核心抽象

- **Chain**：组件串联（如 `prompt | llm | parser`，LCEL 管道）。
- **Agent**：ReAct 等模式的智能体。
- **Tool**：工具封装。
- **Retriever**：检索器（接 RAG）。
- **Memory**：记忆模块（短期对话、长期向量库）。
- **LangSmith**：官方可观测性平台，trace 每个 LLM 调用和工具调用。

### 10.4 LangGraph 核心思想

- 把 Agent 流程建模为 **StateGraph 状态机**。
- **节点（Node）**：一个 Agent 或操作。
- **边（Edge）**：流转条件，支持循环、条件分支、并行。
- **State**：节点间共享的状态对象，支持细粒度更新。
- **Checkpointing**：内置持久化（SQLite/Postgres/Redis），支持**时间旅行**和断点续传。
- **Human-in-the-loop**：中断节点 + 人工审核边。

### 10.5 三个框架在协作模式上的差异

| 框架 | 协作范式 | 通信 | 适用 |
|------|---------|------|------|
| AutoGen v0.4 | 异步 Actor 模型 | BaseMessage 类型层次，跨进程/语言 | 开放式对话协作 |
| MetaGPT | SOP + 共享内存池 | 结构化 JSON 文档传递 | 确定性生产线（软件工程） |
| LangGraph | 状态机图 | LCEL 隐式数据流 | 企业级合规工作流 |

**融合趋势**：三者正在趋同——AutoGen 引入显式编排、MetaGPT 支持自定义 SOP、LangGraph 简化快速原型。**生产建议分层**：LangChain 处理工具/RAG，LangGraph 编排主流程，AutoGen/MetaGPT 处理特定多 Agent 子任务。

### 10.6 框架只是工具，效果看五件事

1. Prompt 设计（系统提示词质量）。
2. 工具设计（描述清不清楚、参数合不合理）。
3. RAG 质量（检索准不准）。
4. 模型选择（什么级别）。
5. 业务流程设计（工作流合理性）。

**简单 Agent 完全可手写**，核心 ReAct 循环就几十行 Python。好处：可控、轻量；坏处：边缘情况要自己处理。

---

## 11. MCP 协议与多智能体

### 11.1 MCP（Model Context Protocol）

**是什么**：Anthropic 2024-11 推出的开放标准，**标准化 LLM 与外部工具/数据源的连接**。被誉为"AI 应用的 USB-C"。

**为什么需要**：解决 **N×M 集成地狱**——M 个模型 × N 个工具 = M×N 套定制集成；MCP 把它降到 M+N（模型接 MCP 客户端，工具做成 MCP 服务器）。

**架构**：
- **MCP Host**：AI 应用（如 Claude Desktop、Cursor）。
- **MCP Client**：Host 内嵌，跟 Server 通信。
- **MCP Server**：暴露工具/资源/prompt 模板，可本地（stdio）或远程（SSE/HTTP）。

**vs Function Calling**：Function Calling 是 API 机制（模型输出 JSON）；MCP 是更广义的**标准化框架**——居中协调、统一接口、强制访问控制和日志。MCP 把临时性 function calling 升级成**结构化企业级流程**。

**vs RAG**：RAG 检索信息用于生成文本；MCP 涵盖**交互+执行**，能让 LLM 不仅取数据还能改 CRM、发邮件、执行代码。

**现状**：2026 中已超 10,000 个公共 MCP Server，SDK 月下载 9700 万次，OpenAI/Google/Microsoft/AWS 全部接入。

### 11.2 MCP 2026-07-28 重大修订（必考前沿）

这是 MCP 史上最大修订，**核心走向无状态化**：

1. **取消 initialize/initialized 握手**：版本/能力通过每请求 `_meta` 字段传递。
2. **移除 Mcp-Session-Id**：任意请求可命中任意服务器实例，**水平扩展无需粘性会话**，负载均衡友好。
3. **传输统一为 Streamable HTTP**：取消独立 GET 流端点，变更通知走 `subscriptions/listen` POST。
4. **MRTR（多轮往返）**：服务器禁止主动发 JSON-RPC 请求，sampling/roots 嵌入 `InputRequiredResult` 由客户端重试触发。
5. **Tasks 移出核心**：改为独立扩展，用 Task Handle 句柄驱动异步任务，删了 `tasks/list`。
6. **OAuth 2.1 资源服务器化**：强制 RFC 9728（Protected Resource Metadata）、RFC 8707（Resource Indicators）、RFC 9207（Issuer Verification），防混淆代理攻击。
7. **MCP Apps 扩展**：服务器可输出沙箱 iframe 渲染的 HTML 交互组件（`$prefab` 格式，MIME `text/html;profile=mcp-app`）。
8. **强制请求头** `Mcp-Method` + `Mcp-Name`：中间件不解析 body 即可路由/限流。

**废弃项（12 个月移除）**：Roots、Sampling、协议级 Logging。

**迁移要点**：把会话状态改造成工具参数显式传递；客户端每个请求带头；服务端配 `.well-known` 元数据。

### 11.3 多智能体协议生态

| 协议 | 提出方 | 用途 | 发现机制 | 身份 |
|------|--------|------|---------|------|
| **MCP** | Anthropic | LLM 调工具 | 静态 URL | Token + TLS |
| **A2A**（Agent2Agent） | Google → Linux Foundation | 企业内多 Agent 协作 | Agent Card（HTTP） | DID 握手/OAuth 2.1 |
| **ACP** | IBM | 已合并入 A2A（2025-08） | - | - |
| **ANP**（Agent Network Protocol） | 开源社区 | 去中心化 Agent 网络 | DID + 搜索引擎爬取 | did:wba + 密钥 |

**分层组合**：**MCP 负责 Agent↔工具，A2A 负责 Agent↔Agent**。

**A2A 核心**：基于 Task 模型（`submitted → working → input-required → completed/failed/cancelled`），通过 Artifact 返回结果，能力协商在消息 Part 的 MIME 类型里。

### 11.4 单 Agent + MCP vs 多 Agent 系统（MAS）

| 维度 | 单 Agent + MCP | 多 Agent（MAS） |
|------|---------------|----------------|
| 架构 | 集中式，一个 Agent 调多 MCP 工具 | 专家团队，分工协作 |
| 集成 | 简单 | 复杂 |
| 编排 | 内部决定何时用何工具 | 显式协作协议 |
| 推理 | 单模型多任务，难都最优 | 每 Agent 专精 |
| 资源 | 低 | 高（多模型并行） |
| 容错 | 中心节点挂全挂 | 单点失败可接管 |
| 适用 | 工具集成为主、原型、资源受限 | 高复杂、需并行、高可靠 |

**实用建议**：新项目从**单 Agent + MCP 起步**，复杂度增长再演进到 MAS；或用"主 Agent + 辅助 Agent"轻量混合架构。

### 11.5 多 Agent 协调模式

- **集中式（Supervisor）**：一个协调 Agent 分发任务给子 Agent。
- **对等（P2P）**：Agent 间直接通信。
- **分层（Hierarchical，2026 趋势）**：父子树结构，能力声明从底向上汇聚。

### 11.6 安全攻防前沿

- **OWASP Agentic Top 10**：覆盖 10 类 Agent 风险。
- **Microsoft AGT**（2026-04 开源）：首个覆盖 OWASP 全十项的开源运行时安全框架，支持 Python/TS/Rust/Go/.NET。
- **跨 Agent 提示注入**：即使单 Agent 防御好，针对编排层攻击成功率可达 10×。
- **协议层漏洞**：Agent Card 伪造、Task ID 重放、SSE 流中断注入、ANP 元协议降级。
- **动态信任评分**：从二元信任（信/不信）升级到 0-1000 持续行为验证。

---

## 12. 评估与幻觉

### 12.1 主流评测基准

| 基准 | 评测能力 |
|------|---------|
| **MMLU** | 多学科知识（57 个学科） |
| **HumanEval / MBPP** | 代码生成 |
| **GSM8K / MATH** | 数学推理 |
| **BBH** | 综合推理（Big-Bench Hard） |
| **Chatbot Arena** | 人类盲测对战 ELO 排名 |
| **MTEB** | Embedding 模型综合榜 |
| **RAGAS** | RAG 系统评估 |
| **SWE-bench** | 真实软件工程任务 |

### 12.2 LLM-as-Judge

用强模型（GPT-4/Claude）当裁判打分。**注意偏差**：位置偏差（偏好第一个）、长度偏差（偏好长答案）、自我偏好（偏好同家族模型）。

### 12.3 幻觉（Hallucination）

**成因**：
- 训练数据噪声/过时。
- 自回归生成本质是概率采样，可能生成看似合理但错误的内容。
- 知识在 FFN 层存储，可能错位关联。

**缓解手段**：
1. **RAG**（开卷考试，基于检索内容生成）。
2. **RLHF**（用事实性奖励微调）。
3. **对比解码**（Contrastive Decoding，对比微调前后模型）。
4. **明确 Prompt**："仅基于上下文回答"、"不知道就说不知道"。
5. **事实核查后处理**（生成后调外部工具验证）。
6. **解码策略**：降 temperature、用 Top-P 限制。

### 12.4 Agent 评估：Trajectory vs Outcome

- **Outcome eval**：只看最终答案对不对。
- **Trajectory eval**：评估整条轨迹（调了哪些工具、顺序对不对、中间步对不对）。能抓"蒙对但走错路"的 Agent——下次必然失败。
- **生产实践**：必须两者结合。

---

## 13. 高频面试题速记表

### 一句话答案速记

| 问题 | 一句话答案 |
|------|----------|
| Pretrain/SFT/RLHF 区别 | 学知识 → 指令跟随 → 对齐价值观 |
| SFT Loss 怎么算 | Shift right，只算 answer，prompt 设 -100 |
| 为什么 SFT 后要 RL | SFT 只能模仿，RL 能比较偏好（相对关系） |
| 为什么偏好不直接 SFT | 偏好是相对的，直接 SFT 会平均好坏崩溃 |
| DPO vs PPO | DPO 省 RM 和 PPO，直接用偏好对优化，更稳但上限受限 |
| LoRA 核心思想 | 冻结 W，加低秩 BA 增量，参数 <1% |
| QLoRA = ? | 4-bit 量化（NF4）+ LoRA，单 A100 可训 65B |
| KV Cache 为什么只有 KV 没 Q | 推理时 Q 是单 token，K/V 是历史序列可复用 |
| MHA/MQA/GQA 区别 | KV 头数依次减少，GQA 是折中生产主流 |
| RoPE 优点 | 相对位置编码隐式实现，外推有挑战需 YaRN 修复 |
| FlashAttention 为何快 | 不减计算量，分块+SRAM 内增量 softmax，省 HBM 读写 |
| PagedAttention 做什么 | 把 KV Cache 分物理块管理，解决碎片化 |
| Continuous Batching | 序列完成即让位给队列下一个，GPU 利用率最大化 |
| 混合检索为什么 | 纯向量对精确词匹配失败，BM25+向量+RRF 互补 |
| Rerank 为什么有效 | Bi-encoder 无 query-doc 交互，Cross-encoder 精度高 |
| Chunk 多大合适 | 512 token + 10% overlap 是甜区，>2500 触发"上下文悬崖" |
| Embedding 换版本要做什么 | 全量重建索引 + 双写灰度 |
| ReAct 是什么 | Thought→Action→Observation 循环，每步基于真实观测 |
| ReAct vs Plan-and-Execute | 前者自适应但贵，后者可预测成本但僵硬 |
| 生产 Agent 必备三闸 | max_iterations + max_cost + 重复检测 |
| MCP 是什么 | 标准化 LLM 与工具连接的开放协议，"AI 的 USB-C" |
| MCP 2026-07-28 大改 | 无状态化：去握手、去 session-id、OAuth 2.1 |
| A2A vs MCP | A2A 是 Agent 间协作，MCP 是 Agent 调工具 |
| 反射 Reflexion | 完成轨迹后自我批评，存 episodic memory，下次重试参考 |
| Agent vs Workflow | 谁控制执行顺序：LLM 控制是 Agent，代码控制是 Workflow |

### 必背口诀

**三阶段范式**：Pretrain 会说话，SFT 听指令，RLHF 说得好。

**PEFT 显存**：7B 全参 28G，LoRA 12G，QLoRA 6G。

**量化**：4-bit 模型大小 = FP16 × 1/4，精度损失 <2%。

**RAG 流水线**：离线 chunking+embedding+入库，在线 query→embed→召回→rerank→生成。

**Hybrid Search**：BM25 + 向量 + RRF 融合，几乎必选，提升 5-15%。

**ReAct 失败模式**：长任务漂移、误差累积、token 烧得快 → 用 Plan-and-Execute 或加 Reflexion。

**Agent Loop 停止**：步数闸 + 成本闸 + 重复检测 + 时间闸（缺一不可）。

**工具设计三原则**：描述性参数名 + 严格类型 + Schema 小。

**MCP 三大价值**：标准化（解 N×M）、安全治理、互操作。

**生产 Agent 加固四件套**：预算闸 + 结构化错误反馈 + 沙箱隔离 + 持久化 checkpoint。

### 必读论文/资料清单

| 类别 | 资源 |
|------|------|
| 基础架构 | Transformer（Attention Is All You Need）、RoPE、FlashAttention |
| 训练对齐 | InstructGPT、RLHF（PPO）、DPO、DeepSeek-R1（GRPO）、LIMA |
| 微调 | LoRA、QLoRA |
| RAG | RAG（Lewis 2020）、Self-RAG、CRAG、HyDE、RAGAS |
| Agent | ReAct（Yao 2022, arXiv 2210.03629）、Reflexion（Shinn 2023, arXiv 2303.11366）、Tree of Thoughts、Toolformer、Anthropic《Building Effective Agents》 |
| 协议 | MCP 规范 2026-07-28、A2A 协议 |
| 推理 | vLLM/PagedAttention、DeepSeek MLA |

### 项目经验高频追问（提前准备）

1. **数据获取**：训练/测试集怎么来的？格式是什么？
2. **指令微调数据格式**：在 TRL/Llama-Factory 下是什么 JSON 结构？
3. **RL 数据格式**：GRPO/PPO 偏好对怎么组织？
4. **过拟合如何判断**：验证集 loss 不是越低越好（SFT 后期 loss 降但回答变差），看 MT-Bench/人工评估。
5. **泛化性**：加 dropout、减 epoch、数据增强。
6. **Loss 函数**：是否自定义？为什么？
7. **奖励函数设计**：RL 任务里基于规则的奖励怎么设计？
8. **遇到的最大坑**：embedding 版本漂移、chunk 边界割裂、Chat Template 错用、KV Cache 爆显存、Agent 无限循环烧钱——每个都要有具体排查和解决过程。

### 系统设计题模板

遇到"设计一个 XX Agent / RAG 系统"题，按此骨架答：

1. **需求澄清**：用户量级？QPS？延迟 SLA？预算？数据规模？更新频率？
2. **架构选型**：单 Agent 还是多 Agent？哪个框架？哪个 LLM？
3. **数据流**：离线索引怎么做？在线检索怎么做？
4. **关键决策**：
   - Chunking 策略（默认递归 512 + 10% overlap）
   - Embedding（中文 BGE-M3，pin 版本）
   - 向量库（按规模选 Milvus/Qdrant/pgvector）
   - Hybrid Search + Rerank（必选）
   - Agent 模式（ReAct 内层 + Plan-and-Execute 外层）
   - 工具设计（描述清楚、严格类型、参数少）
5. **生产加固**：预算闸、结构化错误、沙箱、checkpoint、监控（LangSmith/Arize）
6. **评估**：RAGAS / Trajectory eval / 离线测试集 + 在线 A/B
7. **成本与延迟**：模型路由（简单 query 用小模型）、语义缓存、Prefix Caching、Prefill-Decode 分离
8. **演进路径**：从 80 分方案起步，运行中持续优化

---

## 附：技术栈速查

| 环节 | 主流工具 |
|------|---------|
| 微调 | PEFT、TRL、Llama-Factory、SWIFT、Unsloth |
| RL 后训练 | OpenRLHF、veRL、TRL |
| 分布式训练 | DeepSpeed、Megatron-LM、FSDP |
| 推理服务 | **vLLM**、TGI、SGLang、TensorRT-LLM、llama.cpp |
| 量化 | bitsandbytes、GPTQ、AWQ、GGUF（llama.cpp） |
| RAG 框架 | LangChain、LlamaIndex、Haystack |
| 向量库 | Milvus、Qdrant、pgvector、Chroma、Pinecone、Weaviate |
| Embedding | BGE-M3、OpenAI text-embedding-3、Cohere、Jina |
| Rerank | Cohere Rerank、BGE-reranker、Jina Reranker |
| Agent 框架 | LangChain、LangGraph、CrewAI、AutoGen、LlamaIndex、Qwen-Agent |
| 可观测 | LangSmith、Arize Phoenix、OpenTelemetry |
| 评估 | RAGAS、lm-eval-harness、Chatbot Arena、SWE-bench |

---

> **背诵建议**：先背"一句话答案速记表"和"必背口诀"，再深入各章节细节。面试官追问时按"系统设计题模板"展开。重点理解**为什么**而非死记——能讲清权衡（trade-off）的候选人远胜过背定义的。
