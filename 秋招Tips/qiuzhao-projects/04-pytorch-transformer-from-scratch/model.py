"""
model.py — 从零实现的 Transformer（Attention is All You Need, 2017）

模块组成：
  - scaled_dot_product_attention  : 缩放点积注意力（核心公式）
  - MultiHeadAttention            : 多头注意力（MHA）
  - PositionalEncoding            : 正弦位置编码
  - PositionwiseFeedForward       : FFN（两层 Linear + ReLU）
  - LayerNorm / RMSNorm           : 归一化层
  - EncoderLayer / DecoderLayer  : 编码/解码层
  - Encoder / Decoder             : 堆叠 N 层
  - Transformer                   : 完整模型
  - LabelSmoothingLoss            : 标签平滑交叉熵

设计要点：
  - 用 Pre-LN（现代实践，比原论文 Post-LN 训练更稳）
  - 因果掩码 + pad 掩码统一处理
  - 支持任意 device（CPU/CUDA/NPU）
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
@dataclass
class TransformerConfig:
    """Transformer 超参配置。"""
    src_vocab_size: int = 1000       # 源语言词表大小
    tgt_vocab_size: int = 1000       # 目标语言词表大小
    d_model: int = 256               # 模型维度
    n_heads: int = 8                 # 多头注意力头数
    d_ff: int = 1024                 # FFN 中间维度
    num_encoder_layers: int = 4      # 编码器层数
    num_decoder_layers: int = 4      # 解码器层数
    max_seq_len: int = 512           # 最大序列长度
    dropout: float = 0.1             # dropout 概率
    pad_token_id: int = 0            # pad token id（用于 mask）
    use_rmsnorm: bool = False        # 是否用 RMSNorm 替代 LayerNorm
    label_smoothing: float = 0.1     # 标签平滑系数

    @property
    def head_dim(self) -> int:
        """每个头的维度 = d_model // n_heads。"""
        assert self.d_model % self.n_heads == 0, \
            f"d_model({self.d_model}) 必须能被 n_heads({self.n_heads}) 整除"
        return self.d_model // self.n_heads


# ---------------------------------------------------------------------------
# 核心组件
# ---------------------------------------------------------------------------
def scaled_dot_product_attention(
    q: Tensor,  # (batch, n_heads, seq_q, head_dim)
    k: Tensor,  # (batch, n_heads, seq_k, head_dim)
    v: Tensor,  # (batch, n_heads, seq_v, head_dim)
    mask: Tensor | None = None,  # (batch, 1, seq_q, seq_k) 或 broadcastable
    dropout: nn.Dropout | None = None,
) -> Tensor:
    """
    缩放点积注意力：softmax(Q @ K^T / sqrt(d_k)) @ V

    为什么除以 √d_k？
      当 d_k 较大时，Q·K 内积方差与 d_k 成正比，进入 softmax 饱和区，
      梯度极小训练不动。除以 √d_k 把方差缩回 1 附近。
    """
    d_k = q.size(-1)
    # (batch, n_heads, seq_q, seq_k)
    scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(d_k)

    if mask is not None:
        # mask 中 0 的位置置 -inf，softmax 后变 0
        scores = scores.masked_fill(mask == 0, float("-inf"))

    # 数值稳定：减最大值
    attn_weights = F.softmax(scores, dim=-1)

    if dropout is not None:
        attn_weights = dropout(attn_weights)

    # (batch, n_heads, seq_q, head_dim)
    output = torch.matmul(attn_weights, v)
    return output, attn_weights


class MultiHeadAttention(nn.Module):
    """
    多头注意力：把 d_model 切成 h 份并行 attention，输出 concat 后线性投影回 d_model。

    参数量与计算量都与单头相同（仅是矩阵分块），但能学不同子空间的关注模式。
    """

    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.n_heads = config.n_heads
        self.head_dim = config.head_dim
        self.d_model = config.d_model

        # Q/K/V/O 共享一个大权重矩阵，切成 4 份更高效
        # 也可分开写：self.q_proj = nn.Linear(d_model, d_model) 等
        self.qkv_proj = nn.Linear(config.d_model, 3 * config.d_model, bias=False)
        self.o_proj = nn.Linear(config.d_model, config.d_model, bias=False)

        self.dropout = nn.Dropout(config.dropout)

    def forward(
        self,
        x: Tensor,                # (batch, seq, d_model) - query 输入
        kv: Tensor | None = None,  # cross-attention 时 K/V 来自这里
        mask: Tensor | None = None,
    ) -> Tensor:
        """
        Args:
            x: query 输入，shape (batch, seq_q, d_model)
            kv: key/value 输入；None 时为 self-attention，否则为 cross-attention
            mask: (batch, 1, seq_q, seq_k) 或 broadcastable
        """
        batch_size, seq_q, _ = x.shape
        kv_input = x if kv is None else kv
        seq_k = kv_input.size(1)

        # 一次算出 Q/K/V，再切分
        # (batch, seq, 3 * d_model) -> 3 个 (batch, seq, d_model)
        qkv = self.qkv_proj(x if kv is None else x)  # query 总是用 x
        # 注意：cross-attention 时 K/V 来自 kv，Q 来自 x
        if kv is None:
            q, k, v = qkv.split(self.d_model, dim=-1)
        else:
            q = self.qkv_proj(x)  # 仅用前 1/3？这里简化：cross-attn 单独做
            # 为了教学清晰，这里用两个独立 Linear 更好，但本项目统一用 qkv_proj
            # 实际 cross-attention 应分开：q_proj + kv_proj
            q = qkv.split(self.d_model, dim=-1)[0]
            kv_out = self.qkv_proj(kv_input).split(self.d_model, dim=-1)
            k, v = kv_out[1], kv_out[2]

        # (batch, seq, d_model) -> (batch, n_heads, seq, head_dim)
        q = q.view(batch_size, seq_q, self.n_heads, self.head_dim).transpose(1, 2)
        k = k.view(batch_size, seq_k, self.n_heads, self.head_dim).transpose(1, 2)
        v = v.view(batch_size, seq_k, self.n_heads, self.head_dim).transpose(1, 2)

        # attention
        out, _ = scaled_dot_product_attention(q, k, v, mask, self.dropout)

        # (batch, n_heads, seq_q, head_dim) -> (batch, seq_q, d_model)
        out = out.transpose(1, 2).contiguous().view(batch_size, seq_q, self.d_model)

        # 输出投影
        return self.o_proj(out)


class PositionalEncoding(nn.Module):
    """
    正弦位置编码（Sinusoidal）：
        PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
        PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))

    性质：
        - PE(pos+k, 2i) 可表示为 PE(pos, 2i) 和 PE(pos, 2i+1) 的线性组合
          => 模型能学到相对位置
        - 不同频率让不同维度编码不同尺度的位置
        - 不需要学习，直接计算
    """

    def __init__(self, d_model: int, max_seq_len: int = 5000, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        # (max_seq_len, d_model)
        pe = torch.zeros(max_seq_len, d_model)
        # (max_seq_len, 1): 0, 1, 2, ..., max_seq_len-1
        position = torch.arange(0, max_seq_len, dtype=torch.float).unsqueeze(1)
        # (d_model // 2,): 10000^(2i/d_model) 的指数
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float) * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        # (1, max_seq_len, d_model) 便于 broadcast
        pe = pe.unsqueeze(0)
        self.register_buffer("pe", pe, persistent=False)

    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: (batch, seq, d_model)
        Returns:
            (batch, seq, d_model)
        """
        x = x + self.pe[:, : x.size(1), :]
        return self.dropout(x)


class PositionwiseFeedForward(nn.Module):
    """FFN: Linear(d_model, d_ff) -> ReLU -> Linear(d_ff, d_model)"""

    def __init__(self, d_model: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.w1 = nn.Linear(d_model, d_ff)
        self.w2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor) -> Tensor:
        return self.w2(self.dropout(F.relu(self.w1(x))))


class RMSNorm(nn.Module):
    """
    RMSNorm：去掉 LayerNorm 的减均值操作，只除 RMS（均方根）。
    优势：少一次求和，计算量小约 10-20%，精度相当或略好。
    主流模型（Llama/Qwen/DeepSeek）都用 RMSNorm。
    """

    def __init__(self, d_model: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(d_model))

    def forward(self, x: Tensor) -> Tensor:
        rms = torch.rsqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return self.weight * x * rms


def make_norm(config: TransformerConfig) -> nn.Module:
    """根据配置选择 LayerNorm 或 RMSNorm。"""
    if config.use_rmsnorm:
        return RMSNorm(config.d_model)
    return nn.LayerNorm(config.d_model)


# ---------------------------------------------------------------------------
# Encoder / Decoder
# ---------------------------------------------------------------------------
class EncoderLayer(nn.Module):
    """
    Pre-LN Encoder Layer:
        x = x + SelfAttn(LN(x))
        x = x + FFN(LN(x))
    """

    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.norm1 = make_norm(config)
        self.self_attn = MultiHeadAttention(config)
        self.norm2 = make_norm(config)
        self.ffn = PositionwiseFeedForward(config.d_model, config.d_ff, config.dropout)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x: Tensor, src_mask: Tensor | None = None) -> Tensor:
        # Pre-LN: 先归一化再进子层，残差直接加
        normed = self.norm1(x)
        x = x + self.dropout(self.self_attn(normed, kv=None, mask=src_mask))
        normed = self.norm2(x)
        x = x + self.dropout(self.ffn(normed))
        return x


class DecoderLayer(nn.Module):
    """
    Pre-LN Decoder Layer（三层子模块）:
        x = x + SelfAttn(LN(x), mask=causal_mask)         # masked self-attention
        x = x + CrossAttn(LN(x), kv=enc_out, mask=src_mask)  # cross-attention
        x = x + FFN(LN(x))
    """

    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.norm1 = make_norm(config)
        self.self_attn = MultiHeadAttention(config)
        self.norm2 = make_norm(config)
        self.cross_attn = MultiHeadAttention(config)
        self.norm3 = make_norm(config)
        self.ffn = PositionwiseFeedForward(config.d_model, config.d_ff, config.dropout)
        self.dropout = nn.Dropout(config.dropout)

    def forward(
        self,
        x: Tensor,
        enc_out: Tensor,
        tgt_mask: Tensor | None = None,  # causal + pad
        src_mask: Tensor | None = None,  # src pad
    ) -> Tensor:
        # Masked self-attention
        normed = self.norm1(x)
        x = x + self.dropout(self.self_attn(normed, kv=None, mask=tgt_mask))
        # Cross-attention：Q 来自 x，K/V 来自 enc_out
        normed = self.norm2(x)
        x = x + self.dropout(self.cross_attn(normed, kv=enc_out, mask=src_mask))
        # FFN
        normed = self.norm3(x)
        x = x + self.dropout(self.ffn(normed))
        return x


class Encoder(nn.Module):
    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.token_emb = nn.Embedding(config.src_vocab_size, config.d_model, padding_idx=config.pad_token_id)
        self.pos_enc = PositionalEncoding(config.d_model, config.max_seq_len, config.dropout)
        self.layers = nn.ModuleList([EncoderLayer(config) for _ in range(config.num_encoder_layers)])
        self.norm = make_norm(config)  # 最后一层后归一化（Pre-LN 必备）

    def forward(self, src: Tensor, src_mask: Tensor | None = None) -> Tensor:
        x = self.token_emb(src) * math.sqrt(self.token_emb.embedding_dim)
        x = self.pos_enc(x)
        for layer in self.layers:
            x = layer(x, src_mask)
        return self.norm(x)


class Decoder(nn.Module):
    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.token_emb = nn.Embedding(config.tgt_vocab_size, config.d_model, padding_idx=config.pad_token_id)
        self.pos_enc = PositionalEncoding(config.d_model, config.max_seq_len, config.dropout)
        self.layers = nn.ModuleList([DecoderLayer(config) for _ in range(config.num_decoder_layers)])
        self.norm = make_norm(config)

    def forward(
        self,
        tgt: Tensor,
        enc_out: Tensor,
        tgt_mask: Tensor | None = None,
        src_mask: Tensor | None = None,
    ) -> Tensor:
        x = self.token_emb(tgt) * math.sqrt(self.token_emb.embedding_dim)
        x = self.pos_enc(x)
        for layer in self.layers:
            x = layer(x, enc_out, tgt_mask, src_mask)
        return self.norm(x)


# ---------------------------------------------------------------------------
# 完整 Transformer
# ---------------------------------------------------------------------------
class Transformer(nn.Module):
    """
    Encoder-Decoder Transformer（原论文）。

    用法：
        model = Transformer(config)
        logits = model(src, tgt_in, src_mask, tgt_mask)
        # logits: (batch, seq_tgt, tgt_vocab_size) - 预测下一个 token
    """

    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.config = config
        self.encoder = Encoder(config)
        self.decoder = Decoder(config)
        # 输出投影：共享 embedding（weight tying，省参数 + 提精度）
        self.output_proj = nn.Linear(config.d_model, config.tgt_vocab_size, bias=False)
        self.output_proj.weight = self.decoder.token_emb.weight

    def forward(
        self,
        src: Tensor,           # (batch, seq_src) - 源 token ids
        tgt_in: Tensor,        # (batch, seq_tgt) - 目标 input（shifted right，即去掉最后一个 token）
        src_mask: Tensor | None = None,
        tgt_mask: Tensor | None = None,
    ) -> Tensor:
        """
        Returns:
            logits: (batch, seq_tgt, tgt_vocab_size)
        """
        enc_out = self.encoder(src, src_mask)            # (batch, seq_src, d_model)
        dec_out = self.decoder(tgt_in, enc_out, tgt_mask, src_mask)  # (batch, seq_tgt, d_model)
        logits = self.output_proj(dec_out)               # (batch, seq_tgt, tgt_vocab)
        return logits

    @torch.no_grad()
    def generate(
        self,
        src: Tensor,
        src_mask: Tensor,
        max_len: int = 50,
        bos_id: int = 1,
        eos_id: int = 2,
        temperature: float = 1.0,
    ) -> Tensor:
        """
        贪心解码生成。

        实际生产中用 beam search 或 sampling，且会缓存 KV cache（本教学版未实现）。
        """
        batch_size = src.size(0)
        device = src.device

        # encoder 一次算
        enc_out = self.encoder(src, src_mask)

        # decoder 自回归生成
        tgt = torch.full((batch_size, 1), bos_id, dtype=torch.long, device=device)

        for _ in range(max_len):
            # 构建 causal mask（随 tgt 增长）
            seq_len = tgt.size(1)
            causal_mask = torch.tril(torch.ones(seq_len, seq_len, device=device))
            causal_mask = causal_mask.unsqueeze(0).unsqueeze(0)  # (1, 1, seq, seq)

            dec_out = self.decoder(tgt, enc_out, causal_mask, src_mask)
            logits = self.output_proj(dec_out[:, -1, :] / temperature)  # 取最后一位
            next_token = logits.argmax(dim=-1, keepdim=True)  # (batch, 1)
            tgt = torch.cat([tgt, next_token], dim=1)

            # 全部到 eos 提前结束
            if (next_token == eos_id).all():
                break

        return tgt


# ---------------------------------------------------------------------------
# Mask 工具
# ---------------------------------------------------------------------------
def make_src_mask(src: Tensor, pad_id: int = 0) -> Tensor:
    """
    src pad mask：pad 位置不能被 attend。
    Returns: (batch, 1, 1, seq_src) - 1=有效, 0=pad
    """
    # (batch, seq) -> (batch, 1, 1, seq)
    return (src != pad_id).unsqueeze(1).unsqueeze(1).float()


def make_tgt_mask(tgt: Tensor, pad_id: int = 0) -> Tensor:
    """
    tgt mask = causal mask + pad mask。
    Returns: (batch, 1, seq_tgt, seq_tgt)
    """
    batch_size, seq_len = tgt.shape
    # causal mask: 上三角为 0
    causal = torch.tril(torch.ones(seq_len, seq_len, device=tgt.device))
    causal = causal.unsqueeze(0).unsqueeze(0)  # (1, 1, seq, seq)

    # pad mask: (batch, 1, 1, seq)
    pad = (tgt != pad_id).unsqueeze(1).unsqueeze(1).float()

    # 合并：两者都满足才有效
    return causal * pad


# ---------------------------------------------------------------------------
# Loss
# ---------------------------------------------------------------------------
class LabelSmoothingLoss(nn.Module):
    """
    标签平滑：把 hard label [0, 0, 1, 0] 变成 [eps/V, eps/V, 1-eps+eps/V, eps/V]。
    效果：减少 overconfidence，提升泛化；标准 Transformer trick。
    """

    def __init__(self, vocab_size: int, smoothing: float = 0.1, pad_id: int = 0):
        super().__init__()
        self.vocab_size = vocab_size
        self.smoothing = smoothing
        self.pad_id = pad_id

    def forward(self, logits: Tensor, target: Tensor) -> Tensor:
        """
        Args:
            logits: (batch, seq, vocab)
            target: (batch, seq)
        """
        # 把 pad 位置 ignore（设为 -100 让 CrossEntropy 自动跳过）
        target = target.clone()
        target[target == self.pad_id] = -100

        # 展平
        logits = logits.reshape(-1, self.vocab_size)
        target = target.reshape(-1)

        # 标签平滑 KL
        nll = F.cross_entropy(logits, target, ignore_index=-100, reduction="mean")
        smooth_loss = -F.log_softmax(logits, dim=-1).mean(dim=-1)
        # 对 ignore_index 位置不贡献（已经 mask）
        mask = (target != -100).float()
        smooth_loss = (smooth_loss * mask).sum() / mask.sum().clamp(min=1)

        return (1 - self.smoothing) * nll + self.smoothing * smooth_loss
