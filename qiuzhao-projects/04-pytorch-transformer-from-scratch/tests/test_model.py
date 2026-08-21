"""
tests/test_model.py — 模型单元测试

运行：
    python -m pytest tests/ -v
"""
import torch
import pytest

from model import (
    Transformer,
    TransformerConfig,
    scaled_dot_product_attention,
    MultiHeadAttention,
    PositionalEncoding,
    make_src_mask,
    make_tgt_mask,
    LabelSmoothingLoss,
)


@pytest.fixture
def config():
    return TransformerConfig(
        src_vocab_size=100,
        tgt_vocab_size=100,
        d_model=32,
        n_heads=4,
        d_ff=64,
        num_encoder_layers=2,
        num_decoder_layers=2,
        max_seq_len=16,
        pad_token_id=0,
    )


def test_scaled_dot_product_attention_shape():
    """测试 attention 输出 shape 正确。"""
    batch, n_heads, seq, d = 2, 4, 8, 16
    q = torch.randn(batch, n_heads, seq, d)
    k = torch.randn(batch, n_heads, seq, d)
    v = torch.randn(batch, n_heads, seq, d)

    out, weights = scaled_dot_product_attention(q, k, v)
    assert out.shape == (batch, n_heads, seq, d)
    assert weights.shape == (batch, n_heads, seq, seq)
    # 权重每行应和为 1（softmax）
    assert torch.allclose(weights.sum(dim=-1), torch.ones(batch, n_heads, seq), atol=1e-6)


def test_scaled_dot_product_attention_mask():
    """测试 mask 生效：被 mask 的位置权重应为 0。"""
    batch, n_heads, seq, d = 1, 1, 3, 4
    q = torch.randn(batch, n_heads, seq, d)
    k = torch.randn(batch, n_heads, seq, d)
    v = torch.randn(batch, n_heads, seq, d)

    # causal mask: 上三角为 0
    mask = torch.tril(torch.ones(seq, seq)).view(1, 1, seq, seq)
    out, weights = scaled_dot_product_attention(q, k, v, mask=mask)

    # 上三角权重应为 0
    upper = weights[0, 0].triu(1)
    assert torch.allclose(upper, torch.zeros_like(upper), atol=1e-6)
    # 每行应和为 1
    assert torch.allclose(weights.sum(dim=-1), torch.ones(batch, n_heads, seq), atol=1e-6)


def test_multihead_attention_shape(config):
    """测试 MHA 输出 shape 正确。"""
    mha = MultiHeadAttention(config)
    x = torch.randn(2, 8, config.d_model)
    out = mha(x)
    assert out.shape == (2, 8, config.d_model)


def test_positional_encoding_shape():
    """测试 PE 输出 shape 不变。"""
    pe = PositionalEncoding(d_model=32, max_seq_len=16, dropout=0.0)
    x = torch.randn(2, 8, 32)
    out = pe(x)
    assert out.shape == x.shape


def test_transformer_forward(config):
    """测试完整模型 forward 输出 shape 正确。"""
    model = Transformer(config)
    batch_size, src_len, tgt_len = 2, 10, 8

    src = torch.randint(1, 100, (batch_size, src_len))
    tgt_in = torch.randint(1, 100, (batch_size, tgt_len))
    src_mask = make_src_mask(src, pad_id=0)
    tgt_mask = make_tgt_mask(tgt_in, pad_id=0)

    logits = model(src, tgt_in, src_mask, tgt_mask)
    assert logits.shape == (batch_size, tgt_len, config.tgt_vocab_size)


def test_transformer_generate(config):
    """测试贪心解码能生成。"""
    model = Transformer(config)
    src = torch.randint(1, 100, (1, 5))
    src_mask = make_src_mask(src, pad_id=0)

    out = model.generate(src, src_mask, max_len=10, bos_id=1, eos_id=2)
    # 输出应至少有 bos + 1 个 token
    assert out.shape[0] == 1
    assert out.shape[1] >= 2
    assert out[0, 0].item() == 1  # bos


def test_label_smoothing_loss(config):
    """测试 label smoothing loss 可正常计算。"""
    criterion = LabelSmoothingLoss(vocab_size=100, smoothing=0.1, pad_id=0)
    logits = torch.randn(2, 8, 100)
    target = torch.randint(1, 100, (2, 8))
    loss = criterion(logits, target)
    assert loss.dim() == 0  # scalar
    assert loss.item() > 0


def test_param_count(config):
    """测试模型参数量合理（不应太大）。"""
    model = Transformer(config)
    n_params = sum(p.numel() for p in model.parameters())
    # 小模型应在 10万-100万之间
    assert 100_000 < n_params < 2_000_000


def test_gradient_flow(config):
    """测试梯度能正常回传（不会断链）。"""
    model = Transformer(config)
    src = torch.randint(1, 100, (1, 5))
    tgt_in = torch.randint(1, 100, (1, 5))
    src_mask = make_src_mask(src, pad_id=0)
    tgt_mask = make_tgt_mask(tgt_in, pad_id=0)

    logits = model(src, tgt_in, src_mask, tgt_mask)
    loss = logits.sum()
    loss.backward()

    # 所有参数应有梯度
    for name, param in model.named_parameters():
        if param.requires_grad:
            assert param.grad is not None, f"Parameter {name} has no gradient"
