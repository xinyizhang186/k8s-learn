# 07 · 多模态

> 多模态大模型(VLM)是 2024-2026 增长方向。秋招高频:架构、图文 RAG、推理优化。

---

## 题 1:多模态大模型架构有哪些? ⭐⭐⭐⭐

### 【场景】
图文理解大模型怎么设计的?LLaVA / Qwen-VL 原理是什么?

### 【答案要点】

**1. 主流架构**

| 架构 | 思路 | 代表 |
|---|---|---|
| **Encoder-LLM** | 视觉编码器 + 投影层 + LLM | LLaVA、Qwen-VL |
| **Cross-Attention** | LLM 中加 cross-attn 融合视觉 token | Flamingo |
| **统一 Transformer** | 原生多模态(视觉 token 与文本 token 同处理) | Gemini、GPT-4o |
| **Diffusion** | 文生图(Diffusion + text encoder) | Stable Diffusion、DALL-E |

**2. Encoder-LLM(LLaVA 类,主流)**
- **视觉编码器**:CLIP ViT 抽图像特征(token 序列)
- **投影层**:MLP / Q-Former 把视觉特征对齐到 LLM 嵌入空间
- **LLM**:LLaMA/Qwen 处理视觉 token + 文本 token 生成
- 训练:① 对齐预训练(图文对,训投影层)② 指令微调(多模态对话)
- 优点:复用现有 LLM,工程简单

**3. Cross-Attention(Flamingo)**
- LLM 不变,在层间加 cross-attn 接收视觉特征
- 视觉 token 不进 LLM 主序列,通过 cross-attn 影响
- 适合少样本多模态

**4. 统一 Transformer(Gemini/GPT-4o)**
- 视觉/文本/音频 token 进同一 Transformer
- 端到端训练,模态融合最深
- 优点:模态间交互强;缺点:训练贵

**5. 文生图(Diffusion)**
- 文本编码器(CLIP/T5)→ 文本嵌入
- Diffusion 模型(UNet/DiT)以文本嵌入为条件去噪
- 代表:Stable Diffusion 3、DALL-E 3、Midjourney

**6. 选型**
- 图文理解(看图说话/文档理解)→ LLaVA / Qwen-VL / InternVL
- 文生图 → Stable Diffusion / DALL-E
- 视频理解 → Video-LLaVA / Qwen-VL(支持视频)
- 全模态交互 → Gemini / GPT-4o

### 【加分追问】
- **Q: LLaVA 训练分几阶段?** A: ① 预训练:图文对,冻 LLM 和 ViT,只训投影层 ② SFT:多模态指令数据,训投影层(+ LoRA LLM)。
- **Q: Q-Former 是什么?** A: BLIP-2 的设计,一组可学习 query 通过 cross-attn 从视觉编码器抽信息,生成固定数量 token;比 MLP 投影更灵活但复杂。

---

## 题 2:图文 RAG 怎么设计? ⭐⭐⭐⭐

### 【场景】
知识库有图片(PDF 截图/图表/扫描件),要做问答。怎么 RAG?

### 【答案要点】

**1. 挑战**
- 传统 RAG 只处理文本,图片信息丢失
- PDF 截图/扫描件含表格/图表/印章,文本提取不全

**2. 方案**

| 方案 | 做法 | 优劣 |
|---|---|---|
| **OCR + 文本 RAG** | OCR 抽文本 → 传统 RAG | 简单,但表格/图丢失 |
| **多模态 Embedding** | 用 CLIP 等图文模型 Embedding 检索 | 支持图查询 |
| **文档页向量(ColPali)** | 整页向量化,不切分 | 保留版式信息 |
| **VLM 转结构化** | VLM 把图/表格转 JSON/Markdown → 文本 RAG | 信息全,成本高 |

**3. ColPali(2024 新方向)**
- 基于 ColBERT 的 late-interaction:文档页切成 patch,每 patch 向量
- 查询与文档 patch 向量做 MaxSim,检索整页
- 优势:不改 PDF,版式/表格/图全保留
- 模型:ColPali / ColQwen2

**4. VLM 转结构化**
- 用 Qwen-VL / GPT-4o 把图表转 Markdown 表格
- 把图片内容描述成文本
- 转换后入库走传统 RAG
- 适合图表/扫描件

**5. 多模态 Embedding**
- CLIP / BGE-M3(支持图文)/ Jina-CLIP
- 图文统一向量空间,支持"以图搜图"或"以文搜图"
- 适合图像检索场景

**6. 实战组合**
- PDF 处理:MarkItDown / Unstructured 抽文本 + 表格 + 图片
- 表格:VLM 转 Markdown
- 图片:VLM 描述 + 多模态 Embedding
- 检索:文本 RAG + 多模态检索融合
- 生成:VLM(若查询含图)

### 【加分追问】
- **Q: ColPali 比传统 RAG 好在哪?** A: 不切分,保留文档版式和图文关系;对复杂版式 PDF(扫描件/多栏)效果显著好于传统切分。但模型较大,工程复杂度高。
- **Q: 表格在 RAG 里怎么处理?** A: ① VLM 转 Markdown 表格入库 ② 整行/整列为一个 chunk ③ 用 SQL 执行结构化查询(若可转结构化)。

---

## 题 3:VLM 推理优化有哪些特殊点? ⭐⭐⃞

### 【场景】
多模态模型比纯文本慢,怎么加速?

### 【答案要点】

**1. 瓶颈**
- 视觉编码器(ViT)处理高分辨率图慢
- 视觉 token 数多(一张图几百 token)→ prefill 长
- 多模态 batch 不均(图文混合,长度差异大)

**2. 优化**
- **视觉 token 压缩**:动态分辨率(只取关键区域)/ token pruning(丢低注意力 token)
- **视觉编码器加速**:ViT 量化、TensorRT 加速
- **batch 优化**:图文混合 batch 调度
- **图像预处理缓存**:同一图多次查询,ViT 特征缓存
- **分辨率自适应**:简单图低分辨率,复杂图高分辨率

**3. 框架**
- vLLM 支持多模态(v0.6+),支持 LLaVA/Qwen-VL
- TensorRT-LLM 多模态优化
- 自部署可针对 ViT 单独优化

**4. 实战**
- 限制图片分辨率 + 数量(防滥用)
- 视觉编码与文本推理并行
- 简单场景(纯文字图)先用 OCR + 文本模型,便宜快

### 【加分追问】
- **Q: 一张图多少 token?** A: LLaVA 默认 256-576 token/图;Qwen-VL 动态,高分辨率可达上千 token;影响 prefill 成本。
- **Q: VLM 量化注意什么?** A: 视觉编码器和 LLM 可分开量化;视觉编码器量化对精度敏感(尤其细粒度任务),建议保守。

---

## 题 4:多模态怎么评估? ⭐⭐⃞

### 【场景】
怎么知道一个 VLM 好不好?

### 【答案要点】

**1. 主流 benchmark**
- **MMBench / MME**:多模态理解综合
- **MMMU**:大学级多学科图文推理
- **MathVista**:图文数学
- **DocVQA / ChartQA**:文档/图表问答
- **GQA / VQAv2**:视觉问答
- **MMBench-CN**:中文多模态

**2. 维度**
- 感知(物体识别/计数/空间关系)
- 推理(图文逻辑/数学/常识)
- 文档(OCR/表格/图表)
- 视频(时序理解)

**3. 自动评估**
- 标准答案匹配(选择/填空)
- LLM-as-judge(开放问答)
- 人工抽检(主观质量)

**4. 实战**
- 自建领域测试集(实际业务图)
- 与开源 / GPT-4o 对比
- 关注错误模式(幻觉物体/计数错/空间错)

### 【加分追问】
- **Q: VLM 幻觉怎么测?** A: POPE(物体存在性)、HallusionBench;测模型是否描述图中不存在的物体。
- **Q: 视频 VLM 怎么评估?** A: MVBench/Video-MME;关注时序理解、长视频因果推理。

---

## 题 5:视频理解怎么实现? ⭐⭐⃞

### 【场景】
做视频问答(监控/教程/直播),怎么实现?

### 【答案要点】

**1. 挑战**
- 视频帧数多,token 爆炸
- 时序信息(动作/因果)
- 长视频(几分钟到几小时)

**2. 方案**

| 方案 | 做法 |
|---|---|
| **关键帧抽帧 + VLM** | 抽 N 帧 → 每帧 VLM 描述 → 文本 + RAG |
| **Video-LLaVA** | 视频原生编码,直接吃帧 |
| **视频帧 Embedding** | 帧向量库 + 检索 |
| **流式处理** | 分段处理 + 时序摘要 |

**3. 关键帧抽取**
- 均匀抽帧(1 帧/秒)简单
- 镜头切换检测(I 帧)抽关键帧
- 重要时刻(动作/物体变化)抽帧
- 平衡帧数 vs 信息量

**4. 时序建模**
- 视频编码器(VideoMAE/TimeSFormer)
- LLM 加时序位置编码
- 长视频:分段摘要 + 时序 RAG

**5. 实战**
- 短视频(< 1 分钟):抽 8-16 帧 → Video-LLaVA
- 中视频(几分钟):关键帧抽帧 → VLM 多帧理解
- 长视频(小时):分段摘要 + RAG + 时序索引

### 【加分追问】
- **Q: 视频抽帧密度怎么定?** A: 看任务:静态场景低密度(1 帧/秒够);动作识别高密度;关键事件检测用镜头切换。综合信息量 vs token 成本。
- **Q: Gemini 视频怎么处理?** A: Gemini 1.5 Pro 原生支持视频(每秒 1 帧),1M 上下文可吃长视频;闭源黑盒但效果最好。
