# PyTorch Transformer From Scratch

从零实现 "Attention is All You Need" 论文的 Transformer 架构（Encoder-Decoder），用于秋招面试手撕代码练习与理解。

## 项目结构

```
04-pytorch-transformer-from-scratch/
├── README.md              # 本文件
├── requirements.txt        # 依赖
├── model.py                # Transformer 完整模型（attention/PE/encoder/decoder）
├── tokenizer.py            # 简单字符级 tokenizer（教学用）
├── dataset.py              # 简单翻译数据集（en -> zh 风格 toy 数据）
├── train.py                # 训练入口
├── generate.py             # 推理 / 翻译生成
└── tests/
    └── test_model.py       # 模型单元测试
```

## 特性

- **完整 Encoder-Decoder 架构**（非 Decoder-only，贴合原论文）
- **Scaled Dot-Product Attention + Multi-Head Attention**
- **Sinusoidal Positional Encoding**（可选 RoPE）
- **Pre-LayerNorm**（现代实践，比原论文 Post-LN 训练更稳）
- **Label Smoothing + Pad Masking**
- **Beam Search 推理**
- 纯 PyTorch，无依赖第三方 NLP 库
- 单文件可跑（CPU 即可，NPU/GPU 自动加速）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 训练（toy 数据，CPU 上几分钟收敛）
python train.py --epochs 30 --batch-size 32

# 推理
python generate.py --input "i love machine learning"
# 输出：我 喜欢 机器 学习

# 跑测试
python -m pytest tests/ -v
```

## 在 NPU / GPU 上运行

```bash
# GPU
python train.py --device cuda --epochs 30

# 昇腾 NPU（需先安装 torch_npu）
python train.py --device npu --epochs 30
```

## 学习要点

1. **为什么除以 √d_k**：稳定 softmax 梯度（见 `model.py: scaled_dot_product_attention`）
2. **Multi-Head 的本质**：把 d_model 切成 h 份并行 attention，参数量/计算量与单头相同
3. **Positional Encoding 为什么有效**：sin/cos 不同频率让模型学到相对位置
4. **Pre-LN vs Post-LN**：Pre-LN 残差路径不经过归一化，深网梯度更稳
5. **KV Cache（本实现未做）**：推理时缓存历史 K/V，避免重算。生产框架（vLLM）的核心优化
6. **Causal Mask**：保证自回归，第 i 个 token 只 attend 到 0..i
7. **Cross-Attention**：decoder 的 K/V 来自 encoder 输出，Q 来自 decoder
