# LLM 基础 - 八股速记

> 适用范围：秋招 AI Infra 岗位（大模型推理部署方向）
> 涵盖：Transformer 架构 / GPT 系列演进 / 预训练-SFT-RLHF 范式 / Tokenizer 原理 / Prefill-Decode 推理流程

---

## 一、Transformer 架构详解

### Q1. 为什么需要 Self-Attention？相比 RNN/LSTM 的优势？
- **并行计算**：RNN 必须按时间步串行，无法跨 token 并行；Self-Attention 一次矩阵乘即可计算所有 token 之间关系，训练吞吐高几个数量级。
- **长程依赖**：RNN 依赖隐状态传递，距离远的 token 梯度衰减；Self-Attention 任意两 token 直接 Q·K 交互，路径长度 O(1)。
- **可解释性**：attention 权重矩阵可直接可视化，看到每个 token 关注哪些 token。
- 缺点：序列长度 N 时复杂度 O(N²)（标准 Attention），RNN 是 O(N)。长上下文必须靠稀疏 / 滑窗 / 线性 attention 等优化。

### Q2. Scaled Dot-Product Attention 公式与缩放因子为什么？
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{Q K^T}{\sqrt{d_k}}\right) V$$

- **为什么除以 √d_k**：当 d_k 较大时，Q·K 的内积方差增大，进入 softmax 饱和区（梯度极小），训练不动。除以 √d_k 把方差缩回 1 附近，softmax 梯度健康。
- 推导：若 Q、K 各分量独立同分布、均值 0、方差 1，则 $q·k = \sum_{i=1}^{d_k} q_i k_i$ 方差为 $d_k$，标准差为 $\sqrt{d_k}$。

### Q3. Multi-Head Attention（MHA）的动机与实现？
- 单头 attention 只能学到一种"关注模式"，多头让模型在不同子空间学不同模式（如短距离语法依赖、长距离指代、同义替换）。
- 实现：把 d_model 切成 h 份，每份 d_k = d_model / h，每头独立做 attention，输出 concat 后线性投影回 d_model。
- 参数量：4 个权重矩阵（W_Q / W_K / W_V / W_O），每个 d_model × d_model，总参数量 = 4 × d_model²，**与头数无关**。
- 计算量与头数也无关（矩阵分块而已），但显存布局有差异。

### Q4. Position Encoding 三种主要方案？
| 方案 | 思想 | 优点 | 代表模型 |
|---|---|---|---|
| **绝对位置编码（Sinusoidal）** | 给每个位置一个固定向量 $\sin(pos/10000^{2i/d})$ | 可外推到训练时未见的长度 | 原始 Transformer |
| **学习式位置编码** | 把位置当作可学习 embedding | 简单、效果好 | BERT / GPT-2 |
| **相对位置编码 / RoPE** | 把"位置"信息融入 Q/K 的旋转，无需额外参数、对外推友好 | 长上下文泛化好、精度高 | Llama / Qwen / DeepSeek |

### Q5. RoPE（Rotary Position Embedding）原理？
- 核心：把 Q、K 向量视为复数，乘以 $e^{i m \theta}$（位置 m 的旋转），等价于在 2D 子平面内做旋转。
- 效果：Q_m · K_n 的内积只依赖**相对位置 m−n**，符合相对位置编码思想，但**无需额外参数**。
- 公式：对 d 维向量两两分组 $(x_{2i}, x_{2i+1})$，第 i 组旋转角度 $\theta_i = 10000^{-2i/d}$。
- 优势：对长上下文友好，可用 NTK-aware / YaRN / Dynamic NTK 等方法外推。

### Q6. Feed-Forward Network（FFN）的作用？为什么有 2 个/3 个线性层？
- FFN 是 **逐位置（position-wise）** 的非线性变换，弥补 Self-Attention 没有的"逐 token 独立计算"能力。
- 经典结构：`Linear(d_model, 4*d_model) → GELU/ReLU → Linear(4*d_model, d_model)`。
- 中间维度 4×d_model 是经验值（论文原版）；现代模型常扩到 8×甚至更大（如 Llama 的中间维 11008，d_model=4096，约 2.68×）。
- **门控 FFN / GLU 变体**：Llama 用 SwiGLU = `silu(Lineargate(x) * Linearup(x)) @ Down`，3 个权重矩阵，性能更好但参数多。

### Q7. LayerNorm vs RMSNorm？
- LayerNorm：减均值 + 除标准差 + 仿射变换。
- RMSNorm：**不减均值**，只除 RMS（均方根），再仿射缩放。
- 优势：少一次求和（减均值）+ 除标准差，计算量小约 10–20%；精度相当或略好。
- 主流模型：GPT-2/BERT 用 LayerNorm；Llama/Qwen/DeepSeek 全用 RMSNorm。

### Q8. Pre-LN vs Post-LN？为什么现代模型都用 Pre-LN？
- Post-LN（原版）：`x + Sublayer(LayerNorm(x))` → 训练不稳定，需要 warmup。
- Pre-LN：`x + Sublayer(LayerNorm(x))` 改成 `x = x + Sublayer(LayerNorm(x))`（残差后再归一化进下层）→ 梯度更平稳，可省 warmup，可堆更深。
- 实测 Pre-LN 在百层以上稳定，Post-LN 12 层就开始抖。现代 LLM 全用 Pre-LN 或变体（Sandwich-LN 等）。

### Q9. Decoder-only vs Encoder-only vs Encoder-Decoder？
| 架构 | 注意力 | 典型模型 | 适合任务 |
|---|---|---|---|
| **Encoder-only** | 双向 Self-Attn | BERT / RoBERTa / DeBERTa | 理解类（分类、抽取、embedding） |
| **Decoder-only** | 单向（causal mask）Self-Attn | GPT / Llama / Qwen | 生成类 |
| **Encoder-Decoder** | Encoder 双向 + Decoder causal + Cross-Attn | T5 / BART / 早期 Transformer | 翻译、摘要、seq2seq |

- 现代趋势：**Decoder-only 一统天下**（GPT/Llama/Qwen/DeepSeek 全是 Decoder-only），原因：
  - 训练目标统一（next-token prediction）→ 简单、可 scale。
  - 任务统一（一切皆 prompt + 生成）→ instruction tuning 易迁移。
  - 单向 mask 让训练 batch 内可同时预测多个位置（teacher forcing + parallel loss）。

### Q10. KV Cache 是什么？为什么需要？
- **生成第 t 个 token 时，前面 t−1 个 token 的 K、V 已经算过，且不再变**——存起来不重算，每步只算新 token 的 K/V。
- 没 KV cache：每步重算所有历史 attention，复杂度 O(N²) 累计 O(N³)。
- 有 KV cache：每步 O(N)，累计 O(N²)，加速几十倍。
- 内存代价：每层每头每 token 存 K、V 各一份，总占用 ≈ `2 × layers × heads × head_dim × seq_len × dtype_size`。Llama-7B、seq=4096、fp16 约 2GB；Llama-70B 约 20GB。
- 这正是 vLLM PagedAttention 解决的核心：高效管理 KV cache 的内存碎片。

### Q11. Attention 计算量 vs 访存量？
- Prefill 阶段：batch=1、seq=N，**计算量主导** (2 × N² × d_model)，访存量 (N × d_model)，**compute-bound**。
- Decode 阶段：batch=1、step=t，**计算量** 2 × N × d_model，**访存量** N × d_model（要读完整 KV cache + 权重），**memory-bound**。
- 关键洞察：Decode 时算术强度（FLOP/Byte）只有 1–2，远低于 GPU 的"屋顶线"（H100 ~250 FLOP/Byte）。→ 这就是 continuous batching / chunked prefill / 投机解码存在的理由。

### Q12. 因果掩码（causal mask）实现？
- 给 attention score 矩阵加上三角为 −∞ 的掩码后再 softmax：
```
[[0,   -∞, -∞, -∞],
 [0,    0, -∞, -∞],
 [0,    0,  0, -∞],
 [0,    0,  0,  0]]
```
- 效果：第 i 个 token 只能 attend 到 0..i，保证自回归。
- 实现：PyTorch `torch.triu(torch.ones(N,N), diagonal=1).bool()` 生成 mask，masked_fill(-inf)。

### Q13. Transformer 训练用什么 Loss？
- 自回归 LM：每个位置预测下一个 token，**CrossEntropy(input=logits, target=next_token_id)**。
- 通常忽略前几个 token 或 pad token 的 loss（label smoothing 在 LLM 中已少用，怕影响 long-tail 知识）。
- BERT 类：MLM（随机 mask 15% 预测）+ NSP（次句预测，已弃用）。

---

## 二、GPT 系列架构演进

### Q14. GPT-1 → GPT-4 关键变化？
| 版本 | 参数量 | 关键创新 |
|---|---|---|
| GPT-1 (2018) | 117M | Decoder-only + 预训练 + 微调范式 |
| GPT-2 (2019) | 1.5B | 规模扩大 + Zero-shot（无需微调，纯 prompt） |
| GPT-3 (2020) | 175B | In-context learning + few-shot，scale 是一切 |
| InstructGPT / GPT-3.5 (2022) | 175B | RLHF，对齐人类偏好 |
| GPT-4 (2023) | 未公开（疑似 MoE） | 多模态 + 涌现能力 + MMLU 大幅提升 |

### Q15. GPT-3 的 in-context learning 是什么？
- 模型不动参数，仅靠 prompt 中的示例完成任务（few-shot）。
- 区别：zero-shot（无示例）、one-shot（一个示例）、few-shot（几个示例）。
- 机制：注意力机制把示例信息"压缩"进 KV cache，生成时 retrieval。
- 局限：示例数量受 context 限制；不同 prompt 顺序结果差异大（label sensitivity）。

### Q16. GPT-3 之后 LLaMA 系列的关键贡献？
- **开源高质**：Llama 1/2/3 用 RoPE、RMSNorm、SwiGLU、Pre-Norm，参数效率高（7B/13B/70B 三档）。
- **Pretrain + SFT + RLHF/DPO 三段训练**成业界标准。
- **数据扩张**：Llama-2 用 2T tokens，Llama-3 用 15T tokens。
- **长上下文**：Llama-3.1 把上下文扩到 128k，用 RoPE 外推 + 训练时混合长上下文样本。

### Q17. Qwen / DeepSeek / GLM 与 Llama 的差异？
| 模型 | 与 Llama 区别 |
|---|---|
| Qwen | 中文优化 + 多模态（Qwen-VL）+ 代码 + 早期用 tie embedding |
| DeepSeek-V3 | **MoE 671B / 37B 激活** + FP8 训练 + MLA（multi-head latent attention，KV cache 压缩）+ Multi-Token Prediction 投机 |
| DeepSeek-R1 | RL（GRPO）训练推理能力，无 SFT cold start 也能涌现 CoT |
| GLM 系列 | 早期 GLM 用 autoregressive blank infilling（非纯 decoder-only），现代 GLM-4/4.5 已对齐 decoder-only |
| MiniMax-M2 | MoE + eagle3 投机解码 + W8A8 量化 |

### Q18. MoE（Mixture of Experts）原理？
- 每个 FFN 替换为 N 个并行 FFN（专家）+ 一个 router（gating network）。
- 每个 token，router 输出 N 个 logit，取 top-k（通常 k=1 或 2）激活对应专家。
- 优势：**参数解耦计算**——总参数大（容量大）但每次只激活一小部分，FLOPs 不增。
- 代表：Mixtral 8×7B（每 token 激活 2 专家 = 13B FLOPs）、DeepSeek-V3 671B（激活 37B）。
- 挑战：负载均衡（避免少数专家过载，用辅助 loss 或 expert-choice routing）、通信开销（专家分布在多卡时 all-to-all）、推理部署（需要全部专家常驻显存）。

### Q19. MLA（Multi-head Latent Attention）原理？
- DeepSeek-V2 提出，解决 KV cache 显存爆炸。
- 思路：把 K、V 压缩到低秩"潜在向量"，KV cache 只存压缩向量，需要时再 up-project 还原 K/V。
- 优势：KV cache 大幅减小（约 1/4），长上下文场景显存友好。
- 代价：每次 attention 多一次矩阵乘（还原 K/V），但 decode 阶段 memory-bound，多算可摊销。

---

## 三、预训练 / SFT / RLHF 训练范式

### Q20. 三段式训练流程？
```
Pretraining (海量无监督文本，next-token 预测)
    ↓
SFT (有监督微调，Instruction-Response 数据)
    ↓
RLHF / DPO / GRPO (基于人类偏好对齐)
```

### Q21. 预训练（Pretraining）的关键点？
- **目标**：next-token prediction，最小化 cross-entropy。
- **数据**：T 级 tokens，互联网 + 代码 + 多语言，去重是关键（MinHash、LSH）。
- **优化器**：AdamW，cosine schedule，warmup（前 2k-5k 步线性），最后 10% decay 到 10% 峰值。
- **batch size**：通常 4M tokens（大模型），用梯度累积 + 多卡数据并行。
- **序列长度**：2k-4k 起步，后期可扩到 8k-32k（context extension 阶段）。
- **混合精度**：BF16 主流（不像 FP16 易溢出），高端训练用 FP8（DeepSeek-V3）。
- **关键指标**：loss 曲线、PPL（perplexity）、benchmark（MMLU/HumanEval）。

### Q22. SFT（Supervised Fine-Tuning）的目的与做法？
- **目的**：让模型学会"听指令"——从"续写文本"变成"回答问题"。
- **数据**：Instruction（输入）-Response（输出）对，几万到几十万条。
- **方法**：
  - Full SFT：全参数微调（成本高）。
  - LoRA/QLoRA：只训低秩适配器（参数量 0.1-1%），效果接近，部署友好。
- **loss mask**：通常只对 Response 计算 loss，Instruction 部分不参与（mask 掉）。
- **数据质量 >> 数据数量**：LIMA 论证"1000 条高质量数据 > 50000 条垃圾"。

### Q23. RLHF 三阶段？
1. **SFT 模型作为初始策略**。
2. **训练 Reward Model（RM）**：用人类偏好对（preferred vs rejected）训练，loss = `−log(σ(r(x,y_c) − r(x,y_r)))`（Bradley-Terry 模型）。
3. **PPO 训练**：
   - Actor：当前策略 π_θ（要训）。
   - Reference：冻结的 SFT 模型 π_ref，用 KL 散度约束 π_θ 不偏离太远（防 reward hacking）。
   - 目标：`max E[r(x,y)] − β · KL(π_θ || π_ref)`。
4. **挑战**：RM 训练数据贵、PPO 训练不稳定（4 个模型同时 forward）、reward hacking。

### Q24. DPO（Direct Preference Optimization）vs PPO？
- DPO 跳过显式 RM 训练，直接从偏好数据学策略，loss：
$$\mathcal{L}_{DPO} = -\log \sigma\left(\beta \log \frac{\pi_\theta(y_w|x)}{\pi_{ref}(y_w|x)} - \beta \log \frac{\pi_\theta(y_l|x)}{\pi_{ref}(y_l|x)}\right)$$
- 优势：无需 RM、无 PPO 的 4 模型，**简、稳、省**。
- 劣势：仍假设 Bradley-Terry 偏好模型；对 in-distribution 数据敏感。
- 现代趋势：DPO 成主流，RLHF/PPO 用于追求极致性能（GPT-4/Claude 仍用 PPO）。

### Q25. GRPO（Group Relative Policy Optimization）是什么？
- DeepSeek-R1 提出，**省去 critic 网络**（PPO 中价值网络）。
- 对每个 prompt 采样 G 个 response，用组内平均 reward 作为 baseline， Advantage = `r_i − mean(r)`，再 PPO-style 更新。
- 优势：训练显存降一半（无 critic），适合大规模 RL。
- DeepSeek-R1 完全用 GRPO + 规则 reward（正确性、格式），无需 RM，涌现出长 CoT 推理能力。

### Q26. RLHF 的常见替代方案？
- **DPO**：直接偏好优化，跳过 RM。
- **IPO / KTO / SimPO**：DPO 变体，改 loss 形式。
- **RRHF / RLAIF**：用 AI 反馈代替人类反馈（constitutional AI）。
- **GRPO**：无 critic 的 PPO 变体。
- **Constitutional AI（CAI）**：让 AI 给自己写偏好数据（Claude 用）。

---

## 四、Tokenizer 原理（BPE / SentencePiece）

### Q27. 为什么需要 Tokenizer？
- 文本 → 整数 ID，模型只能算数字。
- 词汇表大小 V（通常 3-15 万）tradeoff：太小 → 序列长（每 token 含义少）；太大 → embedding 矩阵 + 输出 softmax 庞大。

### Q28. BPE（Byte-Pair Encoding）算法步骤？
1. 把每个词拆成字符序列（开始时词 = 字符）。
2. 统计所有相邻字符对出现频次，合并频次最高的对为一个新 token。
3. 重复 2 直到达到目标 V 大小或频次阈值。
- 优势：未知词可拆为子词/字符，**永远不出现 `<unk>`**（除 OOV 字符）。
- 代表：GPT-2、GPT-3、Llama、Qwen。

### Q29. BBPE（Byte-level BPE）？
- 普通 BPE 在字符级，遇到非英文（中文 emoji）会 `<unk>`。
- BBPE 在 **字节级**——把文本先 UTF-8 编码成字节，BPE 在字节流上跑。
- 优势：覆盖所有 Unicode，永远不 unk；缺点：中文一字常占 3 字节 → token 数变长。
- GPT-2/4、Llama 都用 BBPE。

### Q30. WordPiece 与 BPE 区别？
- WordPiece（BERT 用）：合并依据是 `freq(xy) / (freq(x) * freq(y))`（似然增益），而非纯频次。
- BPE：纯频次。
- 实际效果相近，BBPE 几乎一统现代 LLM。

### Q31. SentencePiece 是什么？
- Google 的分词工具，**语言无关**（不依赖空格，适合中日韩）。
- 内部可选 BPE 或 Unigram 算法。
- Llama/Qwen/DeepSeek 都用 SentencePiece（部分用 BBPE + SentencePiece）。
- Unigram LM 算法：随机初始化一堆子词，用 EM 算每个子词概率，迭代剪枝低频子词。

### Q32. Tokenizer 评估指标？
- **Fertility**：每词平均 token 数（越低越好）。
- **Compression**：每字符平均 token 数。
- **Parity**：跨语言公平性（中英文 token 数比例应接近 1:1）。
- **Reversibility**：可逆 decode 回原文。

### Q33. 特殊 token？
- `<bos>` / `<eos>` / `<pad>` / `<unk>`：基础四件套。
- Chat 模板：`<|im_start|>` `<|im_end|>`（Qwen）/ `<|user|>` `<|assistant|>`（Llama-3）。
- 代码补全：`<fim_prefix>` `<fim_middle>` `<fim_suffix>`（fill-in-middle）。
- 多模态：`<image>` `<video>` 占位符。
- 大模型推理框架（vLLM）依赖 chat template 渲染对话。

---

## 五、推理过程：Prefill 与 Decode

### Q34. Prefill 阶段做什么？
- 输入完整 prompt（N tokens），一次性计算所有 token 的 K、V、Q、attention、FFN。
- 输出：第一个生成 token 的 logits + 完整 KV cache。
- **计算特性**：N × N 的 attention 矩阵 → compute-bound。
- **显存峰值**：N × d_model × layers × dtype 的 activations + N² × heads × layers 的 attention 矩阵（若不 flash）。
- FlashAttention 通过 tiling + online softmax 把显存降到 O(N)，但计算量不变。

### Q35. Decode 阶段做什么？
- 输入上一步生成的 token，计算其 K/V 追加到 cache，与历史 K/V 算 attention，过 FFN，得下一个 token。
- **计算特性**：每步只 1 个 token 的算，但要把所有历史 KV 读一遍 → memory-bound。
- **算术强度**：≈ `2 × d_model / (2 × d_model × dtype_size)` ≈ `1 / dtype_size`，FP16 下 ≈ 0.5 FLOP/Byte，远低于 GPU 屋顶线。

### Q36. 为什么 Decode 慢？
- **GPU 利用率极低**：单请求 decode 时单步只算几百 GFLOPS，H100 算力 1000 TFLOPS，利用率 <0.1%。
- **KV cache 读取代价**：Llama-70B、seq=4096、FP16 的 KV cache ≈ 2.5GB/请求，单步全读，H100 HBM 3TB/s → 0.8ms 起步，再加 attention/FFN 计算约 10-30ms。
- ** batching 是救星**：把多个 decode 请求拼一个 batch，分摊权重 + KV cache 读取 → 这就是 continuous batching。

### Q37. TTFT / TPOT / Throughput 三指标？
- **TTFT**（Time To First Token）：从请求到收到第一个 token 的延迟，主要由 prefill 决定。
- **TPOT**（Time Per Output Token）：decode 阶段每 token 的平均时间。
- **Throughput**：tokens/sec 或 requests/sec，由 GPU 利用率决定。
- 三者互斥：增大 batch → 吞吐↑ 但 TPOT↑（每请求变慢）；减小 batch → 延迟↓ 但吞吐↓。

### Q38. 为什么 prefill 和 decode 要分开调度？
- prefill compute-bound，吃算力；decode memory-bound，吃带宽。
- 同 batch 混跑会冲突：prefill 大块占用 SM，decode 排队等 → decode 延迟尖峰。
- 解决方案：
  - **Chunked prefill**：prefill 切小块与 decode 拼批，平滑延迟。
  - **Disaggregated prefill-decode**：prefill 与 decode 用不同 GPU 池，KV cache 经 NVLink/RDMA 传输。

### Q39. 投机解码（Speculative Decoding）原理？
- 用小模型（draft）一次生成 k 个候选 token，大模型（target）一次 forward verify（成本与单步相当）。
- 若 k 个全对，等于一步生成 k+1 token；若部分对，回滚到错的点。
- 适合：accept rate 高（如代码、规则文本）；不适合：随机性强的创作。
- 代表方法：EAGLE、MTP（multi-token prediction，DeepSeek-R1 用）、Lookahead Decoding、Medusa。

### Q40. Continuous Batching 在 decode 阶段如何提高吞吐？
- 静态 batching：一个 batch 内所有请求都生成完毕才换新请求，短请求等长请求 → GPU 空转。
- Continuous batching：每步 decode 都重新组 batch，已完成的请求移出、新请求加入（iteration-level scheduling）。
- 配合 PagedAttention：不同请求的 KV cache 用分页管理，新旧请求切换无需拷贝大块内存。
- vLLM 实测吞吐提升 2-4×。

---

## 六、一页速记卡

| 类别 | 必背 |
|---|---|
| Attention | $\text{softmax}(QK^T/\sqrt{d_k})V$；MHA 分 h 头并行 |
| 位置编码 | 绝对（sin/cos）/ 学习式 / 相对（RoPE 外推友好） |
| FFN | Linear→激活→Linear；Llama 用 SwiGLU（门控） |
| Norm | Pre-LN 训练稳；RMSNorm 省计算 |
| 架构 | Decoder-only 一统天下；Encoder-Decoder 仅用于 seq2seq |
| KV cache | 存历史 K/V，decode 每步 O(N) 不重算；显存约 2×layers×heads×head_dim×seq×dtype |
| 算术强度 | prefill compute-bound；decode memory-bound（强度≈1） |
| GPT 演进 | GPT-1 微调 → GPT-3 zero/few-shot → InstructGPT RLHF → GPT-4 多模态 |
| 训练范式 | Pretrain → SFT → RLHF/DPO/GRPO |
| Tokenizer | BBPE（字节级 BPE）主流；SentencePiece 处理中日韩 |
| Prefill | 一次算完 prompt，输出首 token + KV cache；compute-bound |
| Decode | 每 step 1 token；memory-bound；GPU 利用率 <0.1% |
| 三指标 | TTFT（首 token 延迟）/ TPOT（每 token 时间）/ Throughput |
| 加速 | Continuous batching、Chunked prefill、Speculative decoding、PD 分离 |
