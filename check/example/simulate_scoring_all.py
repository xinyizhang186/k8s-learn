#!/usr/bin/env python3
"""
simulate_scoring_all.py — 模拟平台打分（合成数据 + 真实 GPT-2 数据 合并版）

本文件合并了原 `simulate_scoring.py`（合成 NVFP4 数据，含 outlier）与
`simulate_scoring_real.py`（从 HuggingFace 下载 GPT-2 提取真实权重/激活）
两套模拟平台打分逻辑。两者共享相同的 GQA 注意力计算与打分函数，
仅在「数据来源」上不同。

打分公式（每个用例）：
    Score = (MSE_STD - MSE_PLAYER) / MSE_STD
其中 STD 为标准 HiF4 基线，PLAYER 为选手 solution。

用法:
    cd /root/A_zxy/ALG/check/example

    # 同时跑合成 + 真实 GPT-2（默认）
    python3 simulate_scoring_all.py

    # 只跑合成数据
    python3 simulate_scoring_all.py --mode synthetic

    # 只跑真实 GPT-2 数据
    python3 simulate_scoring_all.py --mode real
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections import defaultdict
from typing import Optional

import torch

# --- import solution from /root/A_zxy/ALG/solution ---
SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))

from solution import (  # noqa: E402
    dequantize_nvfp4,
    quantize_nvfp4,
    quantize_to_e6m2,
    standard_hif4_quantize,
    _dequantize_hif4,
    hif4_calibration_and_quantize_weight,
    hif4_dynamic_quantize_activation,
    hif4_calibration_attention,
    hif4_dynamic_quantize_q,
    hif4_dynamic_quantize_k,
    hif4_dynamic_quantize_v,
)


# ================================================================================
# Attention computation (GQA) — 共享
# ================================================================================

def gqa_attention(
    Q: torch.Tensor,
    K: torch.Tensor,
    V: torch.Tensor,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> torch.Tensor:
    """Standard Grouped-Query Attention. Q/K/V are [S, hidden]."""
    S = Q.shape[0]
    group = q_num_heads // kv_num_heads

    Q_h = Q.reshape(S, q_num_heads, head_dim).transpose(0, 1)    # [H_q, S, D]
    K_h = K.reshape(S, kv_num_heads, head_dim).transpose(0, 1)   # [H_kv, S, D]
    V_h = V.reshape(S, kv_num_heads, head_dim).transpose(0, 1)   # [H_kv, S, D]

    # Expand for GQA
    K_h = K_h.repeat_interleave(group, dim=0)                   # [H_q, S, D]
    V_h = V_h.repeat_interleave(group, dim=0)                   # [H_q, S, D]

    scores = torch.bmm(Q_h, K_h.transpose(1, 2)) / math.sqrt(head_dim)
    attn = torch.softmax(scores.float(), dim=-1)
    output = torch.bmm(attn, V_h)                                # [H_q, S, D]

    return output.transpose(0, 1).reshape(S, q_num_heads * head_dim)


# ================================================================================
# Scoring: Linear / Attention — 共享（合成与真实数据通用）
# ================================================================================

def score_linear_group(group: dict, idx: int) -> float:
    """Score one Linear group. Returns average score over test cases."""
    W_quant, W_scale = group["weight"]

    # Reference: NVFP4 dequant
    W_ref = dequantize_nvfp4(W_quant, W_scale)

    # Player: calibration + weight quant
    t0 = time.time()
    result = hif4_calibration_and_quantize_weight(
        W_quant, W_scale, group["calib_activation_list"]
    )
    weight_params = result["weight_params"]
    activation_state = result["activation_state"]
    t_calib = time.time() - t0

    W_player = _dequantize_hif4(weight_params, W_ref.shape)

    # Standard baseline
    std_w_params = standard_hif4_quantize(W_ref)
    W_std = _dequantize_hif4(std_w_params, W_ref.shape)

    scores = []
    t_dyn_total = 0.0
    mse_std = 0.0
    mse_player = 0.0
    for act_q, act_s in group["test_activation_list"]:
        X_ref = dequantize_nvfp4(act_q, act_s)

        # Player activation
        t0 = time.time()
        act_params = hif4_dynamic_quantize_activation(act_q, act_s, activation_state)
        t_dyn_total += time.time() - t0
        X_player = _dequantize_hif4(act_params, X_ref.shape)

        # Standard activation
        std_act_params = standard_hif4_quantize(X_ref)
        X_std = _dequantize_hif4(std_act_params, X_ref.shape)

        # Outputs (this is the platform's computation, not the player's)
        ref_out = X_ref @ W_ref.T
        std_out = X_std @ W_std.T
        player_out = X_player @ W_player.T

        mse_std = ((ref_out - std_out) ** 2).mean().item()
        mse_player = ((ref_out - player_out) ** 2).mean().item()

        score = (mse_std - mse_player) / max(mse_std, 1e-30)
        scores.append(score)

    avg = sum(scores) / len(scores)
    print(
        f"  Linear[{idx:2d}]  calib={t_calib:.2f}s  dyn={t_dyn_total:.2f}s  "
        f"MSE_std={mse_std:.6e}  MSE_player={mse_player:.6e}  "
        f"Score={avg:+.4f}  W={tuple(W_ref.shape)}"
    )
    return avg


def score_attention_group(group: dict, idx: int) -> float:
    """Score one Attention group. Returns average score over test cases."""
    q_heads = group["q_num_heads"]
    kv_heads = group["kv_num_heads"]
    head_dim = group["head_dim"]

    # Player calibration
    t0 = time.time()
    calib_result = hif4_calibration_attention(
        group["calib"], q_heads, kv_heads, head_dim
    )
    q_state = calib_result["q_state"]
    k_state = calib_result["k_state"]
    v_state = calib_result["v_state"]
    t_calib = time.time() - t0

    scores = []
    t_dyn_total = 0.0
    mse_std = 0.0
    mse_player = 0.0
    for sample in group["test"]:
        Q_ref = dequantize_nvfp4(*sample["q"])
        K_ref = dequantize_nvfp4(*sample["k"])
        V_ref = dequantize_nvfp4(*sample["v"])

        # Player
        t0 = time.time()
        Q_params = hif4_dynamic_quantize_q(
            sample["q"][0], sample["q"][1], q_heads, head_dim, q_state
        )
        K_params = hif4_dynamic_quantize_k(
            sample["k"][0], sample["k"][1], kv_heads, head_dim, k_state
        )
        V_params = hif4_dynamic_quantize_v(
            sample["v"][0], sample["v"][1], kv_heads, head_dim, v_state
        )
        t_dyn_total += time.time() - t0

        Q_player = _dequantize_hif4(Q_params, Q_ref.shape)
        K_player = _dequantize_hif4(K_params, K_ref.shape)
        V_player = _dequantize_hif4(V_params, V_ref.shape)

        # Standard baseline
        Q_std = _dequantize_hif4(standard_hif4_quantize(Q_ref), Q_ref.shape)
        K_std = _dequantize_hif4(standard_hif4_quantize(K_ref), K_ref.shape)
        V_std = _dequantize_hif4(standard_hif4_quantize(V_ref), V_ref.shape)

        # Outputs
        ref_out = gqa_attention(Q_ref, K_ref, V_ref, q_heads, kv_heads, head_dim)
        std_out = gqa_attention(Q_std, K_std, V_std, q_heads, kv_heads, head_dim)
        player_out = gqa_attention(
            Q_player, K_player, V_player, q_heads, kv_heads, head_dim
        )

        mse_std = ((ref_out - std_out) ** 2).mean().item()
        mse_player = ((ref_out - player_out) ** 2).mean().item()

        score = (mse_std - mse_player) / max(mse_std, 1e-30)
        scores.append(score)

    avg = sum(scores) / len(scores)
    print(
        f"  Attn  [{idx:2d}]  calib={t_calib:.2f}s  dyn={t_dyn_total:.2f}s  "
        f"MSE_std={mse_std:.6e}  MSE_player={mse_player:.6e}  "
        f"Score={avg:+.4f}  hd={head_dim}"
    )
    return avg


# ================================================================================
# Data generation — 合成数据（原 simulate_scoring.py）
# ================================================================================

def gen_linear_group(
    M: int = 512,
    K: int = 512,
    T: int = 128,
    n_calib: int = 5,
    n_test: int = 5,
    seed: int = 42,
) -> dict:
    """Generate a synthetic Linear group with NVFP4 data + outliers."""
    g = torch.Generator().manual_seed(seed)

    # Weight: small-variance normal
    W = torch.randn(M, K, generator=g) * 0.02
    W_quant, W_scale = quantize_nvfp4(W)

    calib, tests = [], []
    for i in range(n_calib + n_test):
        X = torch.randn(T, K, generator=g) * 0.5
        # Add outliers: ~1% of elements are 8x larger
        mask = torch.rand(T, K, generator=g) < 0.01
        X[mask] *= 8.0
        q, s = quantize_nvfp4(X)
        if i < n_calib:
            calib.append((q, s))
        else:
            tests.append((q, s))

    return {
        "weight": (W_quant, W_scale),
        "calib_activation_list": calib,
        "test_activation_list": tests,
    }


def gen_attention_group(
    q_heads: int = 32,
    kv_heads: int = 8,
    head_dim: int = 128,
    seq_len: int = 128,
    n_calib: int = 5,
    n_test: int = 5,
    seed: int = 42,
) -> dict:
    """Generate a synthetic Attention group with NVFP4 data."""
    g = torch.Generator().manual_seed(seed)
    q_hidden = q_heads * head_dim
    kv_hidden = kv_heads * head_dim

    def gen_qkv():
        Q = torch.randn(seq_len, q_hidden, generator=g) * 0.5
        K = torch.randn(seq_len, kv_hidden, generator=g) * 0.5
        V = torch.randn(seq_len, kv_hidden, generator=g) * 0.5
        for x in (Q, K, V):
            mask = torch.rand(x.shape, generator=g) < 0.01
            x[mask] *= 5.0
        return {
            "q": quantize_nvfp4(Q),
            "k": quantize_nvfp4(K),
            "v": quantize_nvfp4(V),
        }

    calib = [gen_qkv() for _ in range(n_calib)]
    tests = [gen_qkv() for _ in range(n_test)]

    return {
        "q_num_heads": q_heads,
        "kv_num_heads": kv_heads,
        "head_dim": head_dim,
        "calib": calib,
        "test": tests,
    }


# ================================================================================
# Data generation — 真实 GPT-2 数据（原 simulate_scoring_real.py）
# ================================================================================

_GPT2_TEXTS = [
    "The quick brown fox jumps over the lazy dog.",
    "Machine learning is a subset of artificial intelligence.",
    "The weather today is sunny with a chance of rain.",
    "Python is a popular programming language for data science.",
    "The stock market experienced significant volatility today.",
    "Climate change poses significant challenges to global ecosystems.",
    "The invention of the printing press revolutionized communication.",
    "Quantum computing leverages superposition and entanglement.",
    "The Renaissance was a period of cultural rebirth in Europe.",
    "Photosynthesis converts solar energy into chemical energy.",
    "The Earth revolves around the Sun once every 365 days.",
    "Water boils at 100 degrees Celsius at sea level pressure.",
    "The Great Wall of China is one of the world's largest structures.",
    "Deoxyribonucleic acid contains the genetic instructions for life.",
    "The Industrial Revolution transformed agrarian societies into industrial ones.",
    "Albert Einstein developed the theory of relativity in the early 20th century.",
    "The human brain contains approximately 86 billion neurons.",
    "Shakespeare wrote 37 plays and 154 sonnets during his lifetime.",
    "The Pacific Ocean is the largest and deepest ocean on Earth.",
    "Antibiotics revolutionized medicine by treating bacterial infections.",
    "The French Revolution began in 1789 and transformed European politics.",
    "DNA was discovered by Friedrich Miescher in the late 19th century.",
    "The internet originated from ARPANET research in the 1960s.",
    "Mount Everest is the highest peak above sea level at 8848 meters.",
    "The Roman Empire fell in 476 AD with the deposition of Romulus Augustulus.",
    "Penicillin was discovered by Alexander Fleming in 1928.",
    "The speed of light in vacuum is approximately 300 million meters per second.",
    "World War II ended in 1945 with the surrender of Japan.",
    "The periodic table organizes elements by their atomic number.",
    "The Pyramids of Giza are among the Seven Wonders of the Ancient World.",
    "The human genome contains approximately 3 billion base pairs.",
    "The Mona Lisa was painted by Leonardo da Vinci in the early 16th century.",
    "Gravity is one of the four fundamental forces of nature.",
    "The Amazon rainforest produces about 20 percent of the world's oxygen.",
    "The Wright brothers made their first powered flight in 1903.",
    "The Berlin Wall fell in 1989 marking the end of the Cold War.",
    "The human heart beats approximately 100000 times per day.",
    "The Statue of Liberty was a gift from France to the United States.",
    "The Great Barrier Reef is the world's largest coral reef system.",
    "The Declaration of Independence was signed on July 4 1776.",
    "The first computer was built during World War II for code breaking.",
    "The Black Death killed an estimated 75 to 200 million people in the 14th century.",
    "The Moon orbits the Earth at an average distance of 384400 kilometers.",
    "The first Olympic Games were held in ancient Greece in 776 BC.",
    "The solar system consists of eight planets orbiting the Sun.",
    "The Mariana Trench is the deepest point in any ocean on Earth.",
    "The printing press was invented by Johannes Gutenberg around 1440.",
    "The theory of evolution by natural selection was proposed by Charles Darwin.",
    "The United Nations was founded in 1945 after World War II.",
    "The International Space Station has been continuously occupied since 2000.",
]


def extract_real_data(n_texts: int = 50):
    """从真实 GPT-2 模型提取权重和激活数据。"""
    # transformers 仅在 real 模式下才需要，这里延迟导入
    from transformers import GPT2LMHeadModel, GPT2Tokenizer

    print("Loading GPT-2...")
    model = GPT2LMHeadModel.from_pretrained('gpt2')
    model.eval()
    tokenizer = GPT2Tokenizer.from_pretrained('gpt2')

    all_hidden_states = []
    all_qkv = []

    for text in _GPT2_TEXTS[:n_texts]:
        inputs = tokenizer(text, return_tensors='pt', max_length=128, truncation=True)
        input_ids = inputs['input_ids']

        with torch.no_grad():
            outputs = model(input_ids, output_hidden_states=True, use_cache=False)

        for layer_idx in range(12):
            hs = outputs.hidden_states[layer_idx].squeeze(0)
            all_hidden_states.append((layer_idx, hs))

        with torch.no_grad():
            for layer_idx in range(0, 12, 3):
                hidden = outputs.hidden_states[layer_idx]
                c_attn_w = model.transformer.h[layer_idx].attn.c_attn.weight.detach()
                qkv = hidden.squeeze(0) @ c_attn_w
                q, k, v = qkv.split(768, dim=-1)
                all_qkv.append((layer_idx, q, k, v))

    linear_weights = {}
    for name, param in model.named_parameters():
        if 'weight' in name and param.ndim == 2:
            w = param.detach().T
            if w.shape[0] >= 64 and w.shape[1] >= 64 and w.shape[0] % 64 == 0 and w.shape[1] % 64 == 0:
                linear_weights[name] = w

    return model, linear_weights, all_hidden_states, all_qkv


def gen_real_linear_group(model, linear_weights, all_hidden_states, seed: int = 0) -> Optional[dict]:
    """从真实 GPT-2 数据生成一个 Linear 测试组。"""
    keys = list(linear_weights.keys())
    key = keys[seed % len(keys)]
    W = linear_weights[key]

    hidden = [hs for _, hs in all_hidden_states
              if hs.shape[-1] == W.shape[1] and hs.shape[0] >= 1]

    if not hidden:
        return None

    torch.manual_seed(seed)
    perm = torch.randperm(len(hidden))
    hidden = [hidden[i] for i in perm]

    n_calib = min(5, len(hidden) // 2)
    n_test = min(5, len(hidden) - n_calib)

    if n_calib < 1 or n_test < 1:
        return None

    calib, tests = [], []
    for i in range(n_calib + n_test):
        T = min(hidden[i].shape[0], 128)
        X = hidden[i][:T]
        if X.shape[-1] != W.shape[1]:
            continue
        q, s = quantize_nvfp4(X)
        if i < n_calib:
            calib.append((q, s))
        else:
            tests.append((q, s))

    if len(calib) < 1 or len(tests) < 1:
        return None

    W_quant, W_scale = quantize_nvfp4(W)

    return {
        "weight": (W_quant, W_scale),
        "calib_activation_list": calib,
        "test_activation_list": tests,
    }


def gen_real_attention_group(model, all_qkv, seed: int = 0) -> Optional[dict]:
    """从真实 GPT-2 数据生成一个 Attention 测试组。"""
    q_heads = model.config.n_head
    head_dim = model.config.n_embd // model.config.n_head
    kv_heads = q_heads

    # Group QKV samples by layer to avoid mixing scales
    by_layer = defaultdict(list)
    for item in all_qkv:
        if item[1].shape[-1] == q_heads * head_dim:
            by_layer[item[0]].append(item)

    available_layers = [l for l, samples in by_layer.items() if len(samples) >= 10]
    if not available_layers:
        return None

    layer_idx = available_layers[seed % len(available_layers)]
    samples = by_layer[layer_idx]

    torch.manual_seed(seed)
    perm = torch.randperm(len(samples))
    samples = [samples[i] for i in perm]

    n_calib = min(5, len(samples) // 2)
    n_test = min(5, len(samples) - n_calib)

    if n_calib < 1 or n_test < 1:
        return None

    calib, tests = [], []
    for i in range(n_calib + n_test):
        _, q, k, v = samples[i]
        T = min(q.shape[0], 128)
        q_t, k_t, v_t = q[:T], k[:T], v[:T]

        sample = {
            "q": quantize_nvfp4(q_t),
            "k": quantize_nvfp4(k_t),
            "v": quantize_nvfp4(v_t),
        }

        if i < n_calib:
            calib.append(sample)
        else:
            tests.append(sample)

    if len(calib) < 1 or len(tests) < 1:
        return None

    return {
        "q_num_heads": q_heads,
        "kv_num_heads": kv_heads,
        "head_dim": head_dim,
        "calib": calib,
        "test": tests,
    }


# ================================================================================
# Runners
# ================================================================================

def run_synthetic() -> None:
    """运行合成数据模拟平台打分（原 simulate_scoring.py 的 main）。"""
    print("\n" + "=" * 70)
    print("  [合成数据] NVFP4 -> HiF4  模拟平台打分")
    print("=" * 70)

    # --- Linear ---
    print("\n--- Linear 场景 (10 组) ---")
    linear_configs = [
        dict(M=512,  K=512,  T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256,  K=512,  T=64,  seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512,  K=1024, T=256, seed=46),
        dict(M=1024, K=512,  T=64,  seed=47),
        dict(M=768,  K=768,  T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384,  K=768,  T=96,  seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]
    linear_total = 0.0
    t_start = time.time()
    for i, cfg in enumerate(linear_configs):
        group = gen_linear_group(**cfg)
        linear_total += score_linear_group(group, i)
    t_linear = time.time() - t_start

    # --- Attention ---
    print("\n--- Attention 场景 (10 组) ---")
    attn_configs = [
        dict(q_heads=32, kv_heads=8, head_dim=128, seq_len=128, seed=52),
        dict(q_heads=16, kv_heads=4, head_dim=64,  seq_len=128, seed=53),
        dict(q_heads=8,  kv_heads=2, head_dim=128, seq_len=64,  seed=54),
        dict(q_heads=24, kv_heads=6, head_dim=128, seq_len=256, seed=55),
        dict(q_heads=16, kv_heads=4, head_dim=128, seq_len=192, seed=56),
        dict(q_heads=32, kv_heads=8, head_dim=64,  seq_len=256, seed=57),
        dict(q_heads=8,  kv_heads=2, head_dim=64,  seq_len=128, seed=58),
        dict(q_heads=24, kv_heads=8, head_dim=128, seq_len=96,  seed=59),
        dict(q_heads=16, kv_heads=8, head_dim=128, seq_len=160, seed=60),
        dict(q_heads=8,  kv_heads=4, head_dim=64,  seq_len=192, seed=61),
    ]
    attn_total = 0.0
    t_start = time.time()
    for i, cfg in enumerate(attn_configs):
        group = gen_attention_group(**cfg)
        attn_total += score_attention_group(group, i)
    t_attn = time.time() - t_start

    # --- Summary ---
    n_linear = len(linear_configs)
    n_attn = len(attn_configs)
    print(f"\n{'=' * 70}")
    print(f"  [合成] Linear     总分: {linear_total:+.4f}  平均分: {linear_total / n_linear:+.4f}  (用时 {t_linear:.1f}s)")
    print(f"  [合成] Attention  总分: {attn_total:+.4f}  平均分: {attn_total / n_attn:+.4f}  (用时 {t_attn:.1f}s)")
    print(f"  [合成] 综合总分:       {linear_total + attn_total:+.4f}")
    print(f"  [合成] 综合平均分:     {(linear_total + attn_total) / (n_linear + n_attn):+.4f}")
    print(f"  [合成] 总用时:          {t_linear + t_attn:.1f}s")
    print(f"{'=' * 70}")


def run_real() -> None:
    """运行真实 GPT-2 数据模拟平台打分（原 simulate_scoring_real.py 的 main）。"""
    print("\n" + "=" * 70)
    print("  [真实 GPT-2] NVFP4 -> HiF4  模拟平台打分")
    print("=" * 70)

    model, linear_weights, all_hidden_states, all_qkv = extract_real_data(n_texts=50)

    print(f"\nExtracted: {len(linear_weights)} weight matrices, "
          f"{len(all_hidden_states)} activation samples, "
          f"{len(all_qkv)} QKV samples")

    print("\n--- Linear 场景 ---")
    linear_total = 0.0
    linear_count = 0
    t_start = time.time()
    for i in range(10):
        group = gen_real_linear_group(model, linear_weights, all_hidden_states, seed=i)
        if group is None:
            continue
        score = score_linear_group(group, i)
        linear_total += score
        linear_count += 1
    t_linear = time.time() - t_start

    print("\n--- Attention 场景 ---")
    attn_total = 0.0
    attn_count = 0
    t_start = time.time()
    for i in range(10):
        group = gen_real_attention_group(model, all_qkv, seed=i)
        if group is None:
            continue
        score = score_attention_group(group, i)
        attn_total += score
        attn_count += 1
    t_attn = time.time() - t_start

    print(f"\n{'=' * 70}")
    print(f"  [真实] Linear     总分: {linear_total:+.4f}  平均分: {linear_total/max(linear_count,1):+.4f}  "
          f"({linear_count}组, 用时 {t_linear:.1f}s)")
    print(f"  [真实] Attention  总分: {attn_total:+.4f}  平均分: {attn_total/max(attn_count,1):+.4f}  "
          f"({attn_count}组, 用时 {t_attn:.1f}s)")
    print(f"  [真实] 综合总分:       {linear_total + attn_total:+.4f}")
    print(f"  [真实] 综合平均分:     {(linear_total + attn_total) / max(linear_count + attn_count, 1):+.4f}")
    print(f"  [真实] 总用时:          {t_linear + t_attn:.1f}s")
    print(f"{'=' * 70}")


# ================================================================================
# Main
# ================================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="模拟平台打分（合并版：合成数据 + 真实 GPT-2 数据）"
    )
    parser.add_argument(
        "--mode",
        choices=["synthetic", "real", "both"],
        default="both",
        help="打分数据来源：synthetic=合成数据，real=真实 GPT-2，both=两者都跑（默认）",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  NVFP4 -> HiF4  模拟平台打分（合并版）")
    print("=" * 70)

    if args.mode in ("synthetic", "both"):
        run_synthetic()

    if args.mode in ("real", "both"):
        run_real()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
