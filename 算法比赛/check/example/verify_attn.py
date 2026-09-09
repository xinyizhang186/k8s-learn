#!/usr/bin/env python3
"""verify_attn.py — Attention 三个研究点验证

研究点九: V importance 加 Wout^T·Wout 因子 (BoA)
  rho_t *= ||attn_out[:,t]||^2 (attention output per-token 范数近似 Wout 影响)

研究点十: Q/K importance 加权 (BoA relaxed Hessian)
  Q importance = K^T·K (per KV head), K importance = Q^T·Q

研究点十一: GQA grouped-head rotation
  H_64 → H_{64×group} (跨 GQA group 联合旋转)

A@W 合规: 仅用 P (from calib Q,K), V, K^TK, Q^TQ 单边统计
"""
from __future__ import annotations
import os, sys, time, math
import torch

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

import solution
from solution import (
    _dequant_nvfp4, _apply_hadamard, _hif4_dequant, _quantize_hif4,
    _random_hadamard, HAD_SIZE, BLK_SIZE,
    hif4_calibration_attention as _baseline_calib_attn,
)
import simulate_scoring as ss


def _compute_attn_out_norms(Q, K, V, qh, kvh, hd):
    """Compute per-token attention output norm (approx Wout^T Wout diagonal)."""
    scale = 1.0 / math.sqrt(hd)
    S = Q.shape[0]
    Q_h = Q.reshape(S, qh, hd).transpose(0, 1)
    K_h = K.reshape(S, kvh, hd).transpose(0, 1)
    V_h = V.reshape(S, kvh, hd).transpose(0, 1)
    grp = qh // kvh
    K_exp = K_h.unsqueeze(1).expand(-1, grp, -1, -1).reshape(qh, S, hd)
    V_exp = V_h.unsqueeze(1).expand(-1, grp, -1, -1).reshape(qh, S, hd)
    scores = torch.matmul(Q_h, K_exp.transpose(-1, -2)) * scale
    P = torch.softmax(scores, dim=-1)
    out = torch.matmul(P, V_exp)  # (qh, S, hd)
    # per-KV-head, per-token norm
    out_norm_sq = torch.zeros(kvh, S)
    for g in range(kvh):
        out_g = out[g*grp:(g+1)*grp]
        out_norm_sq[g] = (out_g ** 2).sum(dim=(0, 2))
    return out_norm_sq  # (kvh, S)


def _make_calib_vimp(alpha=1.0):
    """研究点九: V importance += alpha * out_norm_sq."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        result = _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        v_state = result["v_state"]
        rho = v_state["rho"]  # (kvh, seq)
        calib_seq = v_state["calib_seq"]

        # 从校准数据计算 attention output per-token 范数
        out_norm = torch.zeros_like(rho)
        n = 0
        for sample in calib_qkv_list:
            Q = _dequant_nvfp4(*sample["q"])
            K = _dequant_nvfp4(*sample["k"])
            V = _dequant_nvfp4(*sample["v"])
            cur_seq = Q.shape[0]
            if cur_seq != calib_seq:
                continue
            out_norm += _compute_attn_out_norms(Q, K, V, qh, kvh, hd)
            n += 1
        out_norm = (out_norm / max(n, 1)).clamp(min=1e-8)

        # 组合 importance: rho * (1 + alpha * out_norm_normalized)
        out_norm_n = out_norm / (out_norm.max() + 1e-12)
        rho_new = rho * (1.0 + alpha * out_norm_n)

        rho_mean_new = rho_new.mean(dim=1).repeat_interleave(hd).contiguous()
        v_state_new = dict(v_state)
        v_state_new["rho"] = rho_new.contiguous()
        v_state_new["rho_mean"] = rho_mean_new
        result["v_state"] = v_state_new
        return result
    return _calib


def _compute_qk_importance(calib_qkv_list, qh, kvh, hd):
    """研究点十: Q importance = K^T·K, K importance = Q^T·Q (per KV head)."""
    grp = qh // kvh
    q_imp = None
    k_imp = None
    n = 0
    for sample in calib_qkv_list:
        Q = _dequant_nvfp4(*sample["q"])
        K = _dequant_nvfp4(*sample["k"])
        S = Q.shape[0]
        Q_h = Q.reshape(S, qh, hd)  # (S, qh, hd)
        K_h = K.reshape(S, kvh, hd)  # (S, kvh, hd)
        # K^T·K per KV head → Q importance (per channel within head)
        KtK = (K_h.transpose(0, 1) @ K_h.transpose(0, 1).transpose(-1, -2)).diagonal(dim1=-2, dim2=-1)  # 不对
        # 简化: per-head channel 范数 = mean over tokens of K[:,head,channel]^2
        k_sq = (K_h ** 2).mean(dim=0)  # (kvh, hd)
        q_sq = (Q_h ** 2).mean(dim=0)  # (qh, hd)
        # Q importance: per KV head, 取该 group 的 K channel 范数
        q_imp_head = k_sq.repeat_interleave(grp, dim=0)  # (qh, hd)
        # K importance: per KV head, 取该 group 的 Q channel 范数 (mean over Q heads in group)
        k_imp_head = torch.zeros(kvh, hd)
        for g in range(kvh):
            k_imp_head[g] = q_sq[g*grp:(g+1)*grp].mean(dim=0)

        if q_imp is None:
            q_imp = q_imp_head
            k_imp = k_imp_head
        else:
            q_imp += q_imp_head
            k_imp += k_imp_head
        n += 1
    q_imp = (q_imp / max(n, 1)).clamp(min=1e-8)  # (qh, hd)
    k_imp = (k_imp / max(n, 1)).clamp(min=1e-8)  # (kvh, hd)
    # 展平到 (qh*hd,) 和 (kvh*hd,)
    q_imp_flat = q_imp.reshape(-1).contiguous()
    k_imp_flat = k_imp.reshape(-1).contiguous()
    return q_imp_flat, k_imp_flat


def _make_calib_qkimp():
    """研究点十: Q/K importance 加权."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        result = _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        q_imp, k_imp = _compute_qk_importance(calib_qkv_list, qh, kvh, hd)
        q_state = dict(result["q_state"])
        q_state["importance"] = q_imp
        k_state = dict(result["k_state"])
        k_state["importance"] = k_imp
        result["q_state"] = q_state
        result["k_state"] = k_state
        return result
    return _calib


def _make_calib_grouped():
    """研究点十一: GQA grouped-head rotation H_{64×group}."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        grp = qh // kvh
        if hd % HAD_SIZE != 0:
            return _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        # grouped 旋转大小: hd * min(grp, ...) 使得 qh*hd % had_size == 0
        had_size = hd
        # 尝试增大: hd * grp (跨 group 联合)
        target = hd * grp
        # 确保是 2 的幂 (Hadamard 需要)
        while target > had_size and (qh * hd) % target == 0:
            # 检查 target 是否是 2 的幂
            if target & (target - 1) == 0:
                had_size = target
            target //= 2
            if had_size >= hd * grp:
                break
        if had_size == hd:
            return _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)

        H = _random_hadamard(had_size, seed=123).to(torch.float32).contiguous()
        result = _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        result["q_state"] = {"hadamard": H}
        result["k_state"] = {"hadamard": H}
        return result
    return _calib


def run_attn(configs, calib_fn, label):
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        orig = ss.hif4_calibration_attention
        ss.hif4_calibration_attention = calib_fn
        try:
            sc = ss.score_attention_group(group, i)
        finally:
            ss.hif4_calibration_attention = orig
        scores.append(sc)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    return total, avg


def main():
    print("=" * 70)
    print("  Attention 研究点验证: V importance + Q/K importance + grouped rotation")
    print("=" * 70)
    configs = [
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

    print(f"\n--- Baseline ---")
    b_total, b_avg = run_attn(configs, _baseline_calib_attn, "baseline")

    print(f"\n--- 研究点九: V importance + Wout (α=1.0) ---")
    fn9 = _make_calib_vimp(alpha=1.0)
    v_total, v_avg = run_attn(configs, fn9, "vimp_a1")

    print(f"\n--- 研究点九: V importance + Wout (α=0.5) ---")
    fn9b = _make_calib_vimp(alpha=0.5)
    v2_total, v2_avg = run_attn(configs, fn9b, "vimp_a0.5")

    print(f"\n--- 研究点十: Q/K importance ---")
    fn10 = _make_calib_qkimp()
    qk_total, qk_avg = run_attn(configs, fn10, "qkimp")

    print(f"\n--- 研究点九+十: V imp + Q/K imp ---")
    def calib_combined(calib_qkv_list, qh, kvh, hd):
        r9 = _make_calib_vimp(alpha=1.0)(calib_qkv_list, qh, kvh, hd)
        q_imp, k_imp = _compute_qk_importance(calib_qkv_list, qh, kvh, hd)
        qs = dict(r9["q_state"])
        qs["importance"] = q_imp
        ks = dict(r9["k_state"])
        ks["importance"] = k_imp
        r9["q_state"] = qs
        r9["k_state"] = ks
        return r9
    c_total, c_avg = run_attn(configs, calib_combined, "combined")

    print(f"\n--- 研究点十一: grouped-head rotation ---")
    fn11 = _make_calib_grouped()
    g_total, g_avg = run_attn(configs, fn11, "grouped")

    print(f"\n{'=' * 70}")
    print(f"  Baseline:          {b_avg:+.4f}")
    print(f"  V imp+Wout α=1.0:  {v_avg:+.4f}  Δ={v_avg - b_avg:+.4f} ({(v_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  V imp+Wout α=0.5:  {v2_avg:+.4f}  Δ={v2_avg - b_avg:+.4f} ({(v2_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Q/K importance:     {qk_avg:+.4f}  Δ={qk_avg - b_avg:+.4f} ({(qk_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Combined (V+QK):    {c_avg:+.4f}  Δ={c_avg - b_avg:+.4f} ({(c_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Grouped rotation:   {g_avg:+.4f}  Δ={g_avg - b_avg:+.4f} ({(g_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
