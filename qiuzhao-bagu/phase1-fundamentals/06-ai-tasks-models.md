# 场景 AI 任务与模型 - 八股速记

> 适用范围：秋招 AI Infra 岗位（昇腾 NPU / 大模型推理方向）
> 涵盖：NLP 任务 / CV 任务 / 多模态任务 + 代表模型

---

## 一、NLP 任务与模型

### Q1. NLP 主要任务分类？
| 任务 | 输入 | 输出 | 代表模型 |
|---|---|---|---|
| **文本分类** | 句子/文档 | 类别标签 | BERT、RoBERTa |
| **命名实体识别（NER）** | 句子 | 每个 token 的实体类型 | BERT-CRF |
| **情感分析** | 文本 | 积极/消极/中性 | BERT、TextCNN |
| **文本匹配** | 句子对 | 相似度 | Sentence-BERT |
| **机器翻译** | 源语言文本 | 目标语言文本 | T5、NLLB、Marian |
| **文本摘要** | 长文 | 短摘要 | BART、PEGASUS、GPT |
| **问答（QA）** | 问题 + 上下文 | 答案片段 | BERT、T5 |
| **对话生成** | 上下文 | 回复 | GPT、DialoGPT |
| **代码生成** | 自然语言 | 代码 | CodeLlama、DeepSeek-Coder |

### Q2. BERT vs GPT 区别？
| 维度 | BERT | GPT |
|---|---|---|
| 架构 | Encoder-only | Decoder-only |
| 注意力 | 双向 Self-Attn | 单向（causal mask） |
| 预训练目标 | MLM + NSP | Next-token prediction |
| 适合任务 | 理解类（分类、NER、QA） | 生成类 |
| 微调方式 | 全参微调 / 领域适配 | Prompt + in-context |
| 上下文 | 通常 ≤512 | 数千-数万 |

### Q3. 主流 LLM 代表系列？
| 系列 | 公司 | 特点 |
|---|---|---|
| GPT-4/4o/5 | OpenAI | 闭源、多模态、推理强 |
| Claude 3.5/4 | Anthropic | 长文本、代码、artifacts |
| Gemini 1.5/2.0 | Google | 多模态原生、长上下文 2M |
| Llama 3/3.1 | Meta | 开源、广泛社区支持 |
| Qwen 2.5/3 | 阿里 | 中文优化、多模态 |
| DeepSeek-V3/R1 | DeepSeek | MoE、FP8 训练、推理强 |
| GLM-4/4.5 | 智谱 | 中英双语、agent |
| Mistral / Mixtral | Mistral AI | 欧洲开源、MoE |

### Q4. Embedding 模型原理？
- 把文本编码为固定维度向量，用于检索、聚类、相似度。
- 主流：BGE（智源）、M3E、E5（微软）、Sentence-BERT、OpenAI text-embedding。
- 对比学习目标：正样本对（query, related_doc）距离小，负样本距离大。
- 评估：MTEB leaderboard（50+ 任务综合）。
- 应用：RAG（检索增强生成）——先 embedding 检索 top-k 文档，再拼入 LLM prompt。

### Q5. RAG（Retrieval-Augmented Generation）流程？
```
1. 文档分块（chunking，通常 200-500 tokens）
2. 每个 chunk 用 embedding 模型编码
3. 存入向量数据库（FAISS/Milvus/Qdrant）
4. 查询时：query → embedding → top-k 检索 → 拼入 prompt → LLM 生成
```
- 优势：无需重训、知识可更新、可引用来源。
- 挑战：chunk 大小、检索精度、长上下文压缩、rerank。

### Q6. Agent / Tool Use 是什么？
- LLM 作为"大脑"，调用外部工具（搜索、计算器、API、代码解释器）。
- ReAct 范式：Thought → Action → Observation 循环。
- Function Calling：OpenAI 格式（function schema → JSON arguments）。
- 代表框架：LangChain、AutoGen、CrewAI、OpenAI Assistants API。

### Q7. 长上下文模型挑战？
- **计算量 O(N²)**：标准 attention，N 翻倍算力 4 倍。
- **KV cache 爆炸**：128k 上下文 Llama-70B 约 40GB KV cache。
- **外推问题**：训练时见过的位置有限，超出后性能骤降。
- 解决方案：
  - 稀疏 attention（Longformer、BigBird）。
  - 滑窗 + 全局 token。
  - RoPE 外推（NTK-aware、YaRN、Dynamic NTK）。
  - KV cache 量化（FP8/INT8）。
  - KV cache offload 到 CPU / SSD（vLLM、LMCache）。

### Q8. Code Generation 模型？
- 训练数据：GitHub 代码（CODE、The Stack）。
- 代表：CodeLlama、DeepSeek-Coder、StarCoder、Qwen-Coder。
- Fill-in-Middle（FIM）：给定前缀和后缀，补全中间代码。
- 评估：HumanEval / MBPP / LiveCodeBench / SWE-Bench。

---

## 二、CV 任务与模型

### Q9. CV 主要任务？
| 任务 | 输入 | 输出 | 代表模型 |
|---|---|---|---|
| **图像分类** | 图像 | 类别标签 | ResNet、ViT、ConvNeXt |
| **目标检测** | 图像 | 边界框 + 类别 | YOLO、DETR、Faster R-CNN |
| **语义分割** | 图像 | 每像素类别 | U-Net、DeepLab、Mask2Former |
| **实例分割** | 图像 | 每实例 mask | Mask R-CNN |
| **全景分割** | 图像 | 像素 + 实例 | Panoptic FPN |
| **姿态估计** | 图像 | 关键点 | HRNet、ViTPose |
| **OCR** | 图像 | 文字 + 位置 | PaddleOCR、TrOCR |
| **超分** | 低分辨率图 | 高分辨率图 | ESRGAN、SwinIR |

### Q10. CNN 经典架构演进？
- **LeNet (1998)**：手写数字识别，2 卷积 + 3 全连接。
- **AlexNet (2012)**：ImageNet 破局，ReLU、Dropout、GPU 训练。
- **VGG (2014)**：堆叠 3×3 小卷积，16/19 层。
- **ResNet (2015)**：**残差连接** x + F(x)，解决深网梯度消失，可堆 152 层。
- **Inception (v1-v4)**：多尺度并行卷积。
- **MobileNet/EfficientNet**：深度可分离卷积，移动端高效。
- **ConvNeXt (2022)**：用现代设计（大 kernel、LayerNorm、GELU）让 CNN 重新匹敌 ViT。

### Q11. ViT（Vision Transformer）原理？
- 把图像切成 patch（通常 16×16），每个 patch 拉成向量 + 加位置编码 → 当 token 输入 Transformer Encoder。
- 加 `[CLS]` token 做分类。
- 优势：大数据预训练后超越 CNN，可迁移性强。
- 缺点：小数据上不如 CNN（缺归纳偏置）；计算量 O(N²) 对高分辨率不友好。
- 后续：Swin Transformer（滑窗、层级）、DeiT（数据增强 + 蒸馏）、MAE（masked autoencoder 预训练）。

### Q12. 目标检测：YOLO vs DETR？
| 维度 | YOLO 系列 | DETR |
|---|---|---|
| 架构 | CNN + anchor + NMS | Transformer + bipartite matching |
| 速度 | 快（实时） | 较慢 |
| 精度 | 高（YOLOv8/v11） | 高（大模型） |
| 后处理 | NMS 去重 | 无需 NMS（匈牙利匹配） |
| 训练 | 收敛快 | 需长训练、收敛慢 |
| 适合 | 工业部署、实时 | 学术、高精度 |

### Q13. 图像生成模型？
- **GAN**：StyleGAN、BigGAN。判别器 + 生成器对抗。模式坍缩难训。
- **Diffusion**：DDPM、Stable Diffusion、DALL-E 3、Imagen。去噪迭代，稳定且质量高。
- **Stable Diffusion**：在 latent 空间做 diffusion（VAE 压缩 → diffusion → VAE 解码），计算量大幅降低。
- **DiT（Diffusion Transformer）**：把 UNet 换成 Transformer，Sora 用此架构。
- **Flow Matching**：新一代生成框架，比 diffusion 采样更快、训练更稳。FLUX、Stable Diffusion 3 用此。

---

## 三、多模态任务与模型

### Q14. 多模态模型分类？
| 类型 | 任务 | 代表 |
|---|---|---|
| **VLM（Vision-Language Model）** | 图像理解 + 文本对话 | GPT-4V/4o、Claude 3.5、Qwen-VL、LLaVA、InternVL |
| **TTS（Text-To-Speech）** | 文本 → 语音 | Whisper-TTS、CosyVoice、ChatTTS |
| **STT（Speech-To-Text）** | 语音 → 文本 | Whisper、Paraformer、SenseVoice |
| **图像生成** | 文本 → 图像 | Stable Diffusion、DALL-E 3、Midjourney |
| **视频生成** | 文本 → 视频 | Sora、Kling、CogVideoX |
| **音频生成** | 文本/图像 → 音频 | AudioLDM、Suno |

### Q15. VLM（Vision-Language Model）主流架构？
**三类架构**：
1. **Embedding-based**：图像经 vision encoder（CLIP ViT）→ projection（MLP/Q-Former）→ 拼入 LLM token 序列。代表：LLaVA、Qwen-VL。简单高效，主流。
2. **Cross-Attention**：LLM 内加 cross-attn 层接收图像特征。代表：Flamingo、IDEFICS。
3. **原生多模态**：图像 patch 直接作为 token，与文本统一进 Transformer。代表：Gemini、GPT-4o。

### Q16. LLaVA 架构详解？
```
图像 → CLIP ViT（vision encoder）→ patch embeddings
    → MLP projection（投影到 LLM 维度）
    → 与文本 token 拼接
    → LLM（如 Llama/Qwen）→ 文本输出
```
- 训练：
  1. Stage 1：冻 vision encoder + LLM，只训 projection（对齐特征）。
  2. Stage 2：冻 vision encoder，训 projection + LLM（指令微调）。
- 数据：LLaVA-1.5 用 558K 图像描述 + 158K 多模态对话。
- 简单但有效，是开源 VLM 基线。

### Q17. Qwen-VL 系列？
- Qwen-VL：基于 Qwen LM + ViT-bigG + Cross-Attn。
- Qwen2-VL：改用 **dynamic resolution**（图像任意分辨率，不 resize）+ M-RoPE（多模态 RoPE，对位置 1D/2D 编码）。
- 支持图像、视频、多图对话、OCR、grounding（输出 bbox 坐标）。

### Q18. Whisper（STT）原理？
- Encoder-Decoder Transformer。
- 输入：mel-spectrogram（80 维 × 时间帧）。
- 训练数据：68 万小时多语言弱标注 → 多任务（转录 + 翻译 + 语言识别 + 时间戳）。
- 优势：零样本泛化强；缺点：流式支持差、长音频需分段。

### Q19. CosyVoice / ChatTTS（TTS）？
- CosyVoice（阿里）：可控语音生成，支持音色克隆（3 秒样本）、情感控制、多语言。
- ChatTTS：对话式 TTS，支持细粒度韵律控制（laugh、pause）。
- 现代 TTS 趋势：LLM-based——把语音 token 化，用 LM 自回归生成，再 vocoder 还原。

### Q20. 多模态推理部署挑战？
- **vision encoder 与 LLM 资源争抢**：encoder 通常占 0.3-1B 参数，LLM 7-70B，两者都要 GPU。
- **图像 token 数量爆炸**：1024×1024 图 → ViT 4096 patch → 4096 token，KV cache 显存 4-8 倍文本。
- **变长输入**：图像分辨率、视频帧数变化，batch 处理复杂。
- vLLM 对 VLM 支持：通过 `--multimodal` 或模型 config 声明 image token，自动处理 prefill。

---

## 四、一页速记卡

| 类别 | 必背 |
|---|---|
| NLP 任务 | 分类/NER/QA/翻译/摘要/对话/代码 |
| NLP 模型 | BERT（理解）/ GPT（生成）/ T5（seq2seq）/ RAG / Agent |
| LLM 系列 | GPT-4 / Claude / Gemini / Llama / Qwen / DeepSeek |
| RAG | chunk → embedding → 向量库 → 检索 → prompt → LLM |
| Agent | ReAct（Thought-Action-Obs）/ Function Calling |
| CV 任务 | 分类/检测/分割/OCR/超分/生成 |
| CV 模型 | ResNet / ViT / YOLO / DETR / Stable Diffusion |
| 多模态 | VLM（图文）/ TTS / STT / 图像生成 / 视频生成 |
| VLM 架构 | Embedding-based（LLaVA）/ Cross-Attn（Flamingo）/ 原生（GPT-4o） |
| Whisper | mel-spec → Encoder-Decoder → 多任务（转录+翻译） |
| 部署挑战 | vision encoder 资源、图像 token 爆炸、变长输入 |
