#!/usr/bin/env python3
"""
simulate_scoring.py — 模拟平台打分

生成合成 NVFP4 数据（含 outlier），运行标准 HiF4 基线与选手 solution，
计算每个用例的 Score = (MSE_STD - MSE_PLAYER) / MSE_STD 并汇总。

用法:
    cd /root/A_zxy/ALG/check/example
    python3 simulate_scoring.py
"""

from __future__ import annotations

import math
import os
import sys
import time

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
# Data generation
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
# Attention computation (GQA)
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
# Scoring: Linear
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
        f"  Linear[{idx}]  calib={t_calib:.2f}s  dyn={t_dyn_total:.2f}s  "
        f"MSE_std={mse_std:.6e}  MSE_player={mse_player:.6e}  "
        f"Score={avg:+.4f}"
    )
    return avg


# ================================================================================
# Scoring: Attention
# ================================================================================

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
        f"  Attn  [{idx}]  calib={t_calib:.2f}s  dyn={t_dyn_total:.2f}s  "
        f"MSE_std={mse_std:.6e}  MSE_player={mse_player:.6e}  "
        f"Score={avg:+.4f}"
    )
    return avg


# ================================================================================
# Main
# ================================================================================

def main():
    print("=" * 70)
    print("  NVFP4 -> HiF4  模拟平台打分")
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
    print(f"  Linear     总分: {linear_total:+.4f}  平均分: {linear_total / n_linear:+.4f}  (用时 {t_linear:.1f}s)")
    print(f"  Attention  总分: {attn_total:+.4f}  平均分: {attn_total / n_attn:+.4f}  (用时 {t_attn:.1f}s)")
    print(f"  综合总分:       {linear_total + attn_total:+.4f}")
    print(f"  综合平均分:     {(linear_total + attn_total) / (n_linear + n_attn):+.4f}")
    print(f"  总用时:          {t_linear + t_attn:.1f}s")
    print(f"{'=' * 70}")

    # --- Detail breakdown ---
    print("\n--- 详细分析 ---")
    print(f"  Linear  组数: {n_linear}  正分: {sum(1 for _ in linear_configs)} 组  平均: {linear_total / n_linear:+.4f}")
    print(f"  Attn    组数: {n_attn}  正分: {sum(1 for _ in attn_configs)} 组  平均: {attn_total / n_attn:+.4f}")
    print(f"  综合平均分: {(linear_total + attn_total) / (n_linear + n_attn):+.4f}")


if __name__ == "__main__":
    main()
