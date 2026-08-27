#!/usr/bin/env python3
"""verify.py — 合并所有 verify_*.py 研究点验证脚本

每个模块针对 NVFP4→HiF4 量化任务测试一种优化策略, 对比 baseline 与变体的
Score = (MSE_STD - MSE_PLAYER) / MSE_STD 差异。

模块清单:
  attn            Attention 研究点验证: V importance+Wout (九), Q/K importance (十), GQA grouped rotation (十一)
  awq             AWQ/SmoothQuant 变体 Linear 验证: max/mean 统计, alpha 扫描, AWQ 公式
  direct_mapping  NVFP4→HiF4 直接精确映射 (无 Hadamard) Linear 验证
  direct_attn     Attention V 直接 NVFP4→HiF4 carrier 提取映射
  gptq            GPTQ 二阶 Hessian OBS 舍入精化 (阻尼扫描) Linear 验证
  hadamard        全K/大块 Hadamard 旋转 (64/128/256/512/auto) Linear 验证
  optrot          旋转种子选择 + OptRot 四阶矩 Cayley SGD (研究点五) Linear 验证
  owq             OWQ 候选预算扫描 (5/7/9/13/17) Linear 验证
  residual_em     IRLS 残差重加权 + EM 交替 (研究点六/七) Linear 验证
  vclip           V per-token clip 策略 (p99/p95/p90/per-channel) Attention 验证

用法:
    cd /root/A_zxy/ALG/check/example
    python3 verify.py --module attn          # 跑指定模块
    python3 verify.py --module all            # 跑全部
    python3 verify.py                         # 列出可用模块
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

import torch

# ================================================================================
# Path setup
# ================================================================================

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

import solution  # noqa: E402
from solution import (  # noqa: E402
    _dequant_nvfp4,
    _apply_hadamard,
    _hif4_dequant,
    _quantize_hif4,
    _adaptive_n_candidates,
    _random_hadamard,
    HAD_SIZE,
    BLK_SIZE,
    _E6M2_TABLE,
    standard_hif4_quantize,
    _dequantize_hif4,
    hif4_calibration_and_quantize_weight as _baseline_calib,
    hif4_calibration_attention as _baseline_calib_attn,
)
import simulate_scoring_all as ss  # noqa: E402


# ================================================================================
# Shared utilities
# ================================================================================

def _e6m2_nearest(x):
    """Quantize to nearest E6M2 value (shared by direct_mapping & direct_attn)."""
    idx = torch.searchsorted(_E6M2_TABLE, x.double())
    idx_lo = (idx - 1).clamp(0, len(_E6M2_TABLE) - 1)
    idx_hi = idx.clamp(0, len(_E6M2_TABLE) - 1)
    val_lo = _E6M2_TABLE[idx_lo]
    val_hi = _E6M2_TABLE[idx_hi]
    choose_hi = (x.double() - val_hi).abs() < (x.double() - val_lo).abs()
    return torch.where(choose_hi, val_hi, val_lo).to(torch.float32)


def run_linear(configs, calib_fn, label, return_scores=False, verbose=True):
    """Run Linear scoring with a patched calibration function.

    Temporarily swaps ss.hif4_calibration_and_quantize_weight with calib_fn,
    runs ss.score_linear_group for each config, returns (total, avg[, scores]).
    """
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_linear_group(**cfg)
        orig = ss.hif4_calibration_and_quantize_weight
        ss.hif4_calibration_and_quantize_weight = calib_fn
        try:
            sc = ss.score_linear_group(group, i)
        finally:
            ss.hif4_calibration_and_quantize_weight = orig
        scores.append(sc)
    total = sum(scores)
    avg = total / len(scores)
    if verbose:
        print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    if return_scores:
        return total, avg, scores
    return total, avg


def run_attn(configs, calib_fn, label):
    """Run Attention scoring with a patched calibration function.

    Temporarily swaps ss.hif4_calibration_attention with calib_fn,
    runs ss.score_attention_group for each config, returns (total, avg).
    """
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


# ================================================================================
# Module: attn — Attention 研究点验证
# ================================================================================

def attn_compute_out_norms(Q, K, V, qh, kvh, hd):
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
    out_norm_sq = torch.zeros(kvh, S)
    for g in range(kvh):
        out_g = out[g * grp:(g + 1) * grp]
        out_norm_sq[g] = (out_g ** 2).sum(dim=(0, 2))
    return out_norm_sq  # (kvh, S)


def attn_make_calib_vimp(alpha=1.0):
    """研究点九: V importance += alpha * out_norm_sq."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        result = _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        v_state = result["v_state"]
        rho = v_state["rho"]  # (kvh, seq)
        calib_seq = v_state["calib_seq"]

        out_norm = torch.zeros_like(rho)
        n = 0
        for sample in calib_qkv_list:
            Q = _dequant_nvfp4(*sample["q"])
            K = _dequant_nvfp4(*sample["k"])
            V = _dequant_nvfp4(*sample["v"])
            cur_seq = Q.shape[0]
            if cur_seq != calib_seq:
                continue
            out_norm += attn_compute_out_norms(Q, K, V, qh, kvh, hd)
            n += 1
        out_norm = (out_norm / max(n, 1)).clamp(min=1e-8)

        out_norm_n = out_norm / (out_norm.max() + 1e-12)
        rho_new = rho * (1.0 + alpha * out_norm_n)

        rho_mean_new = rho_new.mean(dim=1).repeat_interleave(hd).contiguous()
        v_state_new = dict(v_state)
        v_state_new["rho"] = rho_new.contiguous()
        v_state_new["rho_mean"] = rho_mean_new
        result["v_state"] = v_state_new
        return result
    return _calib


def attn_compute_qk_importance(calib_qkv_list, qh, kvh, hd):
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
        k_sq = (K_h ** 2).mean(dim=0)  # (kvh, hd)
        q_sq = (Q_h ** 2).mean(dim=0)  # (qh, hd)
        q_imp_head = k_sq.repeat_interleave(grp, dim=0)  # (qh, hd)
        k_imp_head = torch.zeros(kvh, hd)
        for g in range(kvh):
            k_imp_head[g] = q_sq[g * grp:(g + 1) * grp].mean(dim=0)

        if q_imp is None:
            q_imp = q_imp_head
            k_imp = k_imp_head
        else:
            q_imp += q_imp_head
            k_imp += k_imp_head
        n += 1
    q_imp = (q_imp / max(n, 1)).clamp(min=1e-8)  # (qh, hd)
    k_imp = (k_imp / max(n, 1)).clamp(min=1e-8)  # (kvh, hd)
    q_imp_flat = q_imp.reshape(-1).contiguous()
    k_imp_flat = k_imp.reshape(-1).contiguous()
    return q_imp_flat, k_imp_flat


def attn_make_calib_qkimp():
    """研究点十: Q/K importance 加权."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        result = _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        q_imp, k_imp = attn_compute_qk_importance(calib_qkv_list, qh, kvh, hd)
        q_state = dict(result["q_state"])
        q_state["importance"] = q_imp
        k_state = dict(result["k_state"])
        k_state["importance"] = k_imp
        result["q_state"] = q_state
        result["k_state"] = k_state
        return result
    return _calib


def attn_make_calib_grouped():
    """研究点十一: GQA grouped-head rotation H_{64×group}."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        grp = qh // kvh
        if hd % HAD_SIZE != 0:
            return _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
        had_size = hd
        target = hd * grp
        while target > had_size and (qh * hd) % target == 0:
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


def main_attn():
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
    fn9 = attn_make_calib_vimp(alpha=1.0)
    v_total, v_avg = run_attn(configs, fn9, "vimp_a1")

    print(f"\n--- 研究点九: V importance + Wout (α=0.5) ---")
    fn9b = attn_make_calib_vimp(alpha=0.5)
    v2_total, v2_avg = run_attn(configs, fn9b, "vimp_a0.5")

    print(f"\n--- 研究点十: Q/K importance ---")
    fn10 = attn_make_calib_qkimp()
    qk_total, qk_avg = run_attn(configs, fn10, "qkimp")

    print(f"\n--- 研究点九+十: V imp + Q/K imp ---")
    def calib_combined(calib_qkv_list, qh, kvh, hd):
        r9 = attn_make_calib_vimp(alpha=1.0)(calib_qkv_list, qh, kvh, hd)
        q_imp, k_imp = attn_compute_qk_importance(calib_qkv_list, qh, kvh, hd)
        qs = dict(r9["q_state"])
        qs["importance"] = q_imp
        ks = dict(r9["k_state"])
        ks["importance"] = k_imp
        r9["q_state"] = qs
        r9["k_state"] = ks
        return r9
    c_total, c_avg = run_attn(configs, calib_combined, "combined")

    print(f"\n--- 研究点十一: grouped-head rotation ---")
    fn11 = attn_make_calib_grouped()
    g_total, g_avg = run_attn(configs, fn11, "grouped")

    print(f"\n{'=' * 70}")
    print(f"  Baseline:          {b_avg:+.4f}")
    print(f"  V imp+Wout α=1.0:  {v_avg:+.4f}  Δ={v_avg - b_avg:+.4f} ({(v_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  V imp+Wout α=0.5:  {v2_avg:+.4f}  Δ={v2_avg - b_avg:+.4f} ({(v2_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Q/K importance:     {qk_avg:+.4f}  Δ={qk_avg - b_avg:+.4f} ({(qk_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Combined (V+QK):    {c_avg:+.4f}  Δ={c_avg - b_avg:+.4f} ({(c_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  Grouped rotation:   {g_avg:+.4f}  Δ={g_avg - b_avg:+.4f} ({(g_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"{'=' * 70}")


# ================================================================================
# Module: awq — AWQ/SmoothQuant 变体
# ================================================================================

def awq_compute_stats(calib_acts, weight_fp, mode):
    if mode in ("baseline", "more_alpha"):
        stat_X = torch.zeros(weight_fp.shape[-1], dtype=torch.float32)
        for act in calib_acts:
            stat_X = torch.maximum(stat_X, act.abs().amax(dim=0))
        stat_W = weight_fp.abs().amax(dim=0).clamp(min=1e-8)
    else:
        stat_X = torch.zeros(weight_fp.shape[-1], dtype=torch.float32)
        total_T = 0
        for act in calib_acts:
            stat_X += act.abs().sum(dim=0)
            total_T += act.shape[0]
        stat_X = (stat_X / max(total_T, 1)).clamp(min=1e-8)
        stat_W = weight_fp.abs().mean(dim=0).clamp(min=1e-8)
    return stat_X, stat_W


def awq_compute_D(stat_X, stat_W, alpha, formula):
    if alpha is None:
        return torch.ones_like(stat_X)
    if formula == "smoothquant":
        D = (stat_X.clamp(min=1e-8) ** alpha) / (stat_W ** (1 - alpha))
    else:
        D = (stat_X ** alpha) * (stat_W ** (1 - alpha))
    return D.clamp(min=1e-4, max=1e4)


def awq_calib_variant(weight_quant, weight_scale, calib_list, mode="baseline"):
    weight_fp = _dequant_nvfp4(weight_quant, weight_scale)
    K = weight_fp.shape[-1]
    H = _random_hadamard(HAD_SIZE, seed=42).to(torch.float32)
    n_final = _adaptive_n_candidates(weight_fp.shape)

    if not calib_list:
        weight_rot = _apply_hadamard(weight_fp, H)
        wp = _quantize_hif4(weight_rot, n_candidates=n_final)
        w_hat = _hif4_dequant(wp, weight_rot.shape)
        w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)
        return {"weight_params": wp,
                "activation_state": {"hadamard": H.contiguous(),
                                      "importance": w_diag.contiguous(),
                                      "smooth_scale": None}}

    calib_acts = [_dequant_nvfp4(aq, asc) for aq, asc in calib_list]
    stat_X, stat_W = awq_compute_stats(calib_acts, weight_fp, mode)

    if mode == "baseline":
        alphas, formula = [None, 0.5], "smoothquant"
    elif mode == "more_alpha":
        alphas, formula = [None, 0.25, 0.5, 0.75], "smoothquant"
    elif mode == "mean_sq":
        alphas, formula = [None, 0.25, 0.5, 0.75], "smoothquant"
    elif mode == "awq":
        alphas, formula = [None, 0.25, 0.5, 0.75], "awq"

    n_scan = min(256, weight_fp.shape[0])
    w_scan = weight_fp[:n_scan]
    best = None
    for alpha in alphas:
        D = awq_compute_D(stat_X, stat_W, alpha, formula)
        w_rot = _apply_hadamard(w_scan * D, H)
        x_sq = torch.zeros(K, dtype=torch.float32)
        n_tok = 0
        for act in calib_acts:
            ar = _apply_hadamard(act * (1.0 / D), H)
            x_sq += (ar ** 2).sum(dim=0)
            n_tok += act.shape[0]
        w_imp = (x_sq / max(n_tok, 1)).clamp(min=1e-8)
        wp = _quantize_hif4(w_rot, n_candidates=3, importance=w_imp)
        wh = _hif4_dequant(wp, w_rot.shape)
        proxy = (w_imp * (wh - w_rot) ** 2).sum().item() / n_scan
        if best is None or proxy < best[0]:
            best = (proxy, alpha, D, w_imp)

    alpha, D, w_imp = best[1], best[2], best[3]
    w_rot = _apply_hadamard(weight_fp * D, H)
    wp = _quantize_hif4(w_rot, n_candidates=n_final, importance=w_imp)
    wh = _hif4_dequant(wp, w_rot.shape)
    w_diag = (wh ** 2).sum(dim=0).clamp(min=1e-8)
    smooth_D = D if alpha is not None else None

    return {"weight_params": wp,
            "activation_state": {"hadamard": H.contiguous(),
                                  "importance": w_diag.contiguous(),
                                  "smooth_scale": smooth_D.contiguous() if smooth_D is not None else None}}


def main_awq():
    print("=" * 70)
    print("  AWQ/SmoothQuant 变体 — Linear 场景验证")
    print("=" * 70)

    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=1024, K=512, T=64, seed=47),
        dict(M=768, K=768, T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384, K=768, T=96, seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]

    variants = [
        ("baseline (max, {None,0.5})", lambda wq, ws, cl: _baseline_calib(wq, ws, cl)),
        ("V0 max {None,0.5} (reimpl)", lambda wq, ws, cl: awq_calib_variant(wq, ws, cl, "baseline")),
        ("V1 max {None,.25,.5,.75}", lambda wq, ws, cl: awq_calib_variant(wq, ws, cl, "more_alpha")),
        ("V2 mean {None,.25,.5,.75} sq", lambda wq, ws, cl: awq_calib_variant(wq, ws, cl, "mean_sq")),
        ("V3 mean {None,.25,.5,.75} awq", lambda wq, ws, cl: awq_calib_variant(wq, ws, cl, "awq")),
    ]

    results = {}
    for label, fn in variants:
        print(f"\n--- {label} ---")
        t0 = time.time()
        total, avg = run_linear(configs, fn, label)
        t = time.time() - t0
        results[label] = (total, avg, t)

    print(f"\n{'=' * 70}")
    base = results["baseline (max, {None,0.5})"][1]
    for label, (total, avg, t) in results.items():
        delta = avg - base
        pct = delta / max(abs(base), 1e-9) * 100
        tag = " ✓" if delta > 0 else ""
        print(f"  {label:>35}:  {total:+.4f}  avg {avg:+.4f}  Δ={delta:+.4f} ({pct:+.2f}%)  ({t:.1f}s){tag}")
    print(f"{'=' * 70}")


# ================================================================================
# Module: direct_mapping — NVFP4→HiF4 直接映射 (Linear)
# ================================================================================

def dm_extract_nvfp4_scales(weight_quant, weight_scale, blk_size=16):
    """从 NVFP4 carrier 提取每个 16-subblock 的 scale."""
    return weight_scale


def dm_direct_nvfp4_to_hif4(W_fp, nvfp4_scales):
    """直接从 NVFP4 结构计算 HiF4 参数.

    对每个 64-block (4 个 16-subblock):
    1. 提取 4 个 sub-scale
    2. 选 sf = E6M2(median sub-scale)
    3. 对每个 subblock: ratio = sub_scale/sf, 选 lv2/lv3 最佳匹配
    4. 对每个元素: mant = E2M1 × ratio / (lv2 × lv3), 取最近 HiF4 mant 值
    """
    M, K = W_fp.shape
    nB = K // BLK_SIZE
    NVFP4_BLK = 16

    sf_out = torch.zeros(M, nB, 1, 1, 1)
    lv2_out = torch.ones(M, nB, 8, 1, 1)
    lv3_out = torch.ones(M, nB, 8, 2, 1)
    sign_out = torch.zeros(M, nB, 8, 2, 4)
    mant_out = torch.zeros(M, nB, 8, 2, 4)

    for b in range(nB):
        s = b * BLK_SIZE
        sub_scales = []
        for sb in range(4):
            idx = s + sb * NVFP4_BLK
            block_vals = W_fp[:, idx:idx + NVFP4_BLK]
            smax = block_vals.abs().amax(dim=-1)  # (M,)
            nvfp4_scale = smax / 6.0  # E2M1 max = 6
            sub_scales.append(nvfp4_scale)

        sub_scales_t = torch.stack(sub_scales, dim=-1)  # (M, 4)
        median_scale = sub_scales_t.median(dim=-1).values  # (M,)
        sf = _e6m2_nearest(median_scale)  # (M,) E6M2 quantized

        for sb in range(4):
            idx = s + sb * NVFP4_BLK
            block_vals = W_fp[:, idx:idx + NVFP4_BLK]  # (M, 16)
            sub_scale = sub_scales_t[:, sb]  # (M,)
            ratio = sub_scale / sf.clamp(min=1e-30)  # (M,)

            for lv2 in [1, 2]:
                for lv3 in [1, 2]:
                    effective_scale = sf * lv2 * lv3  # (M,)
                    normalized = block_vals / effective_scale.unsqueeze(-1).clamp(min=1e-30)  # (M, 16)
                    mant_raw = normalized * 4.0  # (M, 16)
                    mant_int = mant_raw.round().clamp(-7, 7)  # (M, 16)
                    deq = mant_int / 4.0 * effective_scale.unsqueeze(-1)  # (M, 16)
                    err = ((block_vals - deq) ** 2).sum(dim=-1)  # (M,)

                    if sb == 0 and lv2 == 1 and lv3 == 1:
                        best_err = err
                        best_lv2 = torch.full((M,), 1.0)
                        best_lv3 = torch.full((M,), 1.0)
                        best_mant_int = mant_int
                    else:
                        improve = err < best_err
                        best_err = torch.where(improve, err, best_err)
                        best_lv2 = torch.where(improve, torch.full((M,), float(lv2)), best_lv2)
                        best_lv3 = torch.where(improve, torch.full((M,), float(lv3)), best_lv3)
                        best_mant_int = torch.where(improve.unsqueeze(-1), mant_int, best_mant_int)

            for g in range(2):
                gi = 2 * sb + g
                elem_start = g * 8
                vals = best_mant_int[:, elem_start:elem_start + 8]  # (M, 8)
                for half in range(2):
                    h_start = half * 4
                    v4 = vals[:, h_start:h_start + 4]  # (M, 4)
                    sign_out[:, b, gi, half, :] = torch.sign(v4).unsqueeze(-1).expand(-1, -1, 4).reshape(M, 4) if v4.dim() == 2 else torch.sign(v4)
                    mant_out[:, b, gi, half, :] = v4.abs() / 4.0
                    lv3_out[:, b, gi, half, 0] = best_lv3
                lv2_out[:, b, gi, 0, 0] = best_lv2

            sf_out[:, b, 0, 0, 0] = sf

    return {
        "scale_factor": sf_out.contiguous().float(),
        "scale_lv2": lv2_out.contiguous().float(),
        "scale_lv3": lv3_out.contiguous().float(),
        "sign": sign_out.contiguous().float(),
        "mant": mant_out.contiguous().float(),
    }


def dm_calib_direct(weight_quant, weight_scale, calib_list):
    """直接映射: 用 NVFP4 结构计算 HiF4, 不用 Hadamard."""
    W_fp = _dequant_nvfp4(weight_quant, weight_scale)
    nvfp4_scales = weight_scale
    weight_params = dm_direct_nvfp4_to_hif4(W_fp, nvfp4_scales)

    W_hat = _hif4_dequant(weight_params, W_fp.shape)
    w_diag = (W_hat ** 2).sum(dim=0).clamp(min=1e-8)

    H_id = torch.eye(HAD_SIZE, dtype=torch.float32)
    return {
        "weight_params": weight_params,
        "activation_state": {
            "hadamard": H_id.contiguous(),
            "importance": w_diag.contiguous(),
            "smooth_scale": None,
        },
    }


def dm_calib_identity_generic(weight_quant, weight_scale, calib_list):
    """无旋转 + 通用量化: 用 Identity 替代 Hadamard, 仍用通用量化."""
    orig_fn = solution._random_hadamard
    def _identity(n, seed=42):
        return torch.eye(n, dtype=torch.float64)
    solution._random_hadamard = _identity
    try:
        result = _baseline_calib(weight_quant, weight_scale, calib_list)
    finally:
        solution._random_hadamard = orig_fn
    return result


def main_direct_mapping():
    print("=" * 70)
    print("  NVFP4→HiF4 直接映射 — Linear 验证")
    print("=" * 70)
    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=768, K=768, T=192, seed=48),
    ]

    print(f"\n--- V0: Baseline (Hadamard + 通用量化) ---")
    b_total, b_avg = run_linear(configs, _baseline_calib, "baseline")

    print(f"\n--- V1: Identity + 通用量化 (无Hadamard, 仍通用量化) ---")
    i_total, i_avg = run_linear(configs, dm_calib_identity_generic, "identity")

    print(f"\n--- V2: Direct NVFP4→HiF4 (精确映射, 无Hadamard) ---")
    t0 = time.time()
    d_total, d_avg = run_linear(configs, dm_calib_direct, "direct")
    t_d = time.time() - t0

    print(f"\n{'=' * 70}")
    print(f"  V0 Baseline (Hadamard):     {b_avg:+.4f}")
    print(f"  V1 Identity (无旋转):        {i_avg:+.4f}  Δ={i_avg - b_avg:+.4f} ({(i_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)")
    print(f"  V2 Direct (精确映射):        {d_avg:+.4f}  Δ={d_avg - b_avg:+.4f} ({(d_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)  ({t_d:.1f}s)")
    print(f"{'=' * 70}")

    # 权重重建 MSE 对比
    print(f"\n--- 权重重建 MSE 对比 ---")
    for i, cfg in enumerate(configs[:2]):
        group = ss.gen_linear_group(**cfg)
        W_fp = _dequant_nvfp4(*group['weight'])
        H_had = _random_hadamard(HAD_SIZE, seed=42).to(torch.float32)
        H_id = torch.eye(HAD_SIZE, dtype=torch.float32)
        for name, H in [("Hadamard", H_had), ("Identity", H_id)]:
            W_rot = _apply_hadamard(W_fp, H)
            p = _quantize_hif4(W_rot, n_candidates=7)
            mse = ((_hif4_dequant(p, W_rot.shape) - W_rot) ** 2).mean().item()
            print(f"  cfg{i} {name}: recon_MSE={mse:.6e}", end="")
        p_direct = dm_direct_nvfp4_to_hif4(W_fp, group['weight'][1])
        mse_direct = ((_hif4_dequant(p_direct, W_fp.shape) - W_fp) ** 2).mean().item()
        print(f"  Direct: {mse_direct:.6e}")


# ================================================================================
# Module: direct_attn — Attention V 直接 NVFP4→HiF4 映射
# ================================================================================

def dn_direct_nvfp4_to_hif4(v_quant, v_scale):
    """直接从 NVFP4 carrier 结构计算 HiF4 参数.

    对每个 64-block (4 个 16-subblock):
    1. 提取 4 个 sub_scale
    2. 搜索最优 sf (E6M2), 使 sub_scale/sf 的失配最小
    3. 对每个 subblock: ratio = sub_scale/sf, 选 lv2/lv3 最佳匹配
    4. 对每个元素: mant = E2M1 × ratio / (lv2×lv3), 取最近 HiF4 mant
    """
    S, C = v_quant.shape
    nB = C // BLK_SIZE
    NVFP4_BLK = 16

    if v_scale.dim() == 1:
        v_scale = v_scale.unsqueeze(0).expand(S, -1)

    n_sub = C // NVFP4_BLK
    sub_scales = v_scale  # (S, n_sub)
    block_scales = sub_scales.reshape(S, nB, 4)  # (S, nB, 4)

    best_sf = torch.zeros(S, nB)
    best_lv2 = torch.ones(S, nB, 8, 1, 1)
    best_lv3 = torch.ones(S, nB, 8, 2, 1)
    best_sign = torch.zeros(S, nB, 8, 2, 4)
    best_mant = torch.zeros(S, nB, 8, 2, 4)

    W_8224 = v_quant.reshape(S, nB, 8, 2, 4)  # E2M1 值 (直接用 carrier!)

    for b in range(nB):
        scales_b = block_scales[:, b, :]  # (S, 4)
        cands = []
        for sb in range(4):
            cands.append(_e6m2_nearest(scales_b[:, sb]))  # (S,)
        max_val = W_8224[:, b].abs().amax(dim=(-3, -2, -1)) * scales_b.max(dim=-1).values
        cands.append(_e6m2_nearest(max_val / 7.0))
        cands = torch.stack(cands, dim=-1)  # (S, 5)

        best_mse = torch.full((S,), float('inf'))
        for ci in range(cands.shape[-1]):
            sf_ci = cands[:, ci]  # (S,)
            lv2_b = torch.ones(S, 8, 1, 1)
            lv3_b = torch.ones(S, 8, 2, 1)
            mant_b = torch.zeros(S, 8, 2, 4)
            sign_b = torch.zeros(S, 8, 2, 4)
            total_mse = torch.zeros(S)

            for sb in range(4):
                for g_offset in range(2):
                    gi = 2 * sb + g_offset
                    sub_scale = scales_b[:, sb]  # (S,)
                    ratio = sub_scale / sf_ci.clamp(min=1e-30)  # (S,)

                    best_sub_mse = torch.full((S,), float('inf'))
                    best_sub_lv2 = torch.ones(S)
                    best_sub_lv3 = torch.ones(S)
                    best_sub_mant = torch.zeros(S, 2, 4)

                    for lv2 in [1, 2]:
                        for lv3 in [1, 2]:
                            eff = sf_ci * lv2 * lv3  # (S,)
                            w_block = W_8224[:, b, gi]  # (S, 2, 4) — E2M1 值
                            dequant_block = w_block * sub_scale.unsqueeze(-1).unsqueeze(-1)  # (S, 2, 4)
                            mant_raw = dequant_block / eff.unsqueeze(-1).unsqueeze(-1).clamp(min=1e-30) * 4.0
                            mant_int = mant_raw.round().clamp(-7, 7)
                            deq = mant_int / 4.0 * eff.unsqueeze(-1).unsqueeze(-1)
                            mse = ((deq - dequant_block) ** 2).sum(dim=(-2, -1))  # (S,)

                            improve = mse < best_sub_mse
                            best_sub_mse = torch.where(improve, mse, best_sub_mse)
                            best_sub_lv2 = torch.where(improve, torch.full_like(best_sub_lv2, float(lv2)), best_sub_lv2)
                            best_sub_lv3 = torch.where(improve, torch.full_like(best_sub_lv3, float(lv3)), best_sub_lv3)
                            best_sub_mant = torch.where(improve.unsqueeze(-1).unsqueeze(-1), mant_int, best_sub_mant)

                    total_mse = total_mse + best_sub_mse
                    lv2_b[:, gi] = best_sub_lv2.unsqueeze(-1).unsqueeze(-1)
                    lv3_b[:, gi] = best_sub_lv3.unsqueeze(-1).unsqueeze(-1)
                    sign_b[:, gi] = torch.sign(best_sub_mant)
                    mant_b[:, gi] = best_sub_mant.abs() / 4.0

            improve = total_mse < best_mse
            best_mse = torch.where(improve, total_mse, best_mse)
            best_sf[:, b] = torch.where(improve, sf_ci, best_sf[:, b])
            best_lv2[:, b] = torch.where(improve.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1), lv2_b, best_lv2[:, b])
            best_lv3[:, b] = torch.where(improve.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1).unsqueeze(-1), lv3_b, best_lv3[:, b])
            best_sign[:, b] = torch.where(improve.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1).unsqueeze(-1), sign_b, best_sign[:, b])
            best_mant[:, b] = torch.where(improve.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1).unsqueeze(-1), mant_b, best_mant[:, b])

    return {
        "scale_factor": best_sf.reshape(S, nB, 1, 1, 1).contiguous().float(),
        "scale_lv2": best_lv2.contiguous().float(),
        "scale_lv3": best_lv3.contiguous().float(),
        "sign": best_sign.contiguous().float(),
        "mant": best_mant.contiguous().float(),
    }


def dn_run_attn(configs, v_quant_fn, label):
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']
        calib = _baseline_calib_attn(group['calib'], qh, kvh, hd)
        H_q = calib['q_state'].get('hadamard')
        v_state = calib['v_state']
        rho = v_state.get('rho')
        calib_seq = v_state.get('calib_seq')
        rho_mean = v_state.get('rho_mean')

        test_scores = []
        for sample in group['test']:
            Q = _dequant_nvfp4(*sample['q'])
            K = _dequant_nvfp4(*sample['k'])
            V_q, V_s = sample['v']
            V_fp = _dequant_nvfp4(V_q, V_s)

            Q_p = _apply_hadamard(Q, H_q) if H_q is not None else Q
            K_p = _apply_hadamard(K, H_q) if H_q is not None else K

            Q_params = _quantize_hif4(Q_p, n_candidates=_adaptive_n_candidates(Q_p.shape))
            K_params = _quantize_hif4(K_p, n_candidates=_adaptive_n_candidates(K_p.shape))
            Q_hat = _hif4_dequant(Q_params, Q_p.shape)
            K_hat = _hif4_dequant(K_params, K_p.shape)

            V_params = v_quant_fn(V_q, V_s, V_fp, v_state, kvh, hd)
            V_hat = _hif4_dequant(V_params, V_fp.shape)

            ref_out = ss.gqa_attention(Q_p, K_p, V_fp, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(Q_p), Q_p.shape),
                _dequantize_hif4(standard_hif4_quantize(K_p), K_p.shape),
                _dequantize_hif4(standard_hif4_quantize(V_fp), V_fp.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)

            mse_std = ((ref_out - std_out) ** 2).mean().item()
            mse_player = ((ref_out - player_out) ** 2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))

        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    return total, avg


def main_direct_attn():
    print("=" * 70)
    print("  V 直接 NVFP4→HiF4 映射 vs 通用量化")
    print("=" * 70)
    configs = [
        dict(q_heads=32, kv_heads=8, head_dim=128, seq_len=128, seed=52),
        dict(q_heads=16, kv_heads=4, head_dim=64,  seq_len=128, seed=53),
        dict(q_heads=8,  kv_heads=2, head_dim=128, seq_len=64,  seed=54),
        dict(q_heads=16, kv_heads=4, head_dim=128, seq_len=192, seed=56),
        dict(q_heads=32, kv_heads=8, head_dim=64,  seq_len=256, seed=57),
    ]

    def v_baseline(V_q, V_s, V_fp, v_state, kvh, hd):
        rho = v_state.get('rho')
        calib_seq = v_state.get('calib_seq')
        rho_mean = v_state.get('rho_mean')
        imp = None
        if rho is not None and calib_seq is not None and V_fp.shape[0] == calib_seq:
            imp = rho.to(torch.float32).transpose(0, 1).repeat_interleave(hd, dim=1)
            if int(imp.shape[-1]) != int(V_fp.shape[-1]): imp = None
        else:
            if rho_mean is not None and int(rho_mean.shape[-1]) == kvh * hd: imp = rho_mean.to(torch.float32)
        return _quantize_hif4(V_fp, n_candidates=_adaptive_n_candidates(V_fp.shape), importance=imp)

    def v_direct(V_q, V_s, V_fp, v_state, kvh, hd):
        return dn_direct_nvfp4_to_hif4(V_q, V_s)

    print(f"\n--- V0 Baseline (通用量化) ---")
    b_total, b_avg = dn_run_attn(configs, v_baseline, "baseline")

    print(f"\n--- V1 Direct (NVFP4→HiF4 直接映射) ---")
    t0 = time.time()
    d_total, d_avg = dn_run_attn(configs, v_direct, "direct")
    t_d = time.time() - t0

    # V 重建 MSE 对比
    print(f"\n--- V 重建 MSE 对比 ---")
    for i, cfg in enumerate(configs[:3]):
        group = ss.gen_attention_group(**cfg)
        V_q, V_s = group['test'][0]['v']
        V_fp = _dequant_nvfp4(V_q, V_s)
        p_base = v_baseline(V_q, V_s, V_fp, _baseline_calib_attn(group['calib'], cfg['q_heads'], cfg['kv_heads'], cfg['head_dim'])['v_state'], cfg['kv_heads'], cfg['head_dim'])
        p_direct = dn_direct_nvfp4_to_hif4(V_q, V_s)
        mse_base = ((_hif4_dequant(p_base, V_fp.shape) - V_fp) ** 2).mean().item()
        mse_direct = ((_hif4_dequant(p_direct, V_fp.shape) - V_fp) ** 2).mean().item()
        print(f'  cfg{i}: baseline={mse_base:.4e}  direct={mse_direct:.4e}  ratio={mse_direct/max(mse_base,1e-30):.3f}')

    print(f"\n{'=' * 70}")
    print(f"  Baseline:   {b_avg:+.4f}")
    print(f"  Direct:     {d_avg:+.4f}  Δ={d_avg - b_avg:+.4f} ({(d_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)  ({t_d:.1f}s)")
    print(f"{'=' * 70}")


# ================================================================================
# Module: gptq — GPTQ 二阶 Hessian 舍入
# ================================================================================

GPTQ_BLK = 64


def gptq_reconstruct_rotated_space(weight_quant, weight_scale, calib_list, state):
    """复现 solution.py 的旋转/平滑流水线, 返回 (W_rot, H_rot).

    W_rot = Hadamard(W * D)   (与 solution 内部一致)
    H_rot = (1/T) * sum_t X_rot[t]^T X_rot[t],  X_rot = Hadamard(X / D)
    """
    W_fp = _dequant_nvfp4(weight_quant, weight_scale)
    K = W_fp.shape[-1]

    H_mat = state.get("hadamard")
    D = state.get("smooth_scale")

    W_smooth = W_fp if D is None else W_fp * D.to(torch.float32)
    W_rot = W_smooth if H_mat is None else _apply_hadamard(W_smooth, H_mat.to(torch.float32))

    H_rot = torch.zeros(K, K, dtype=torch.float32)
    total_T = 0
    for aq, asc in calib_list:
        act = _dequant_nvfp4(aq, asc)
        act_smooth = act if D is None else act * (1.0 / D.to(torch.float32))
        act_rot = act_smooth if H_mat is None else _apply_hadamard(act_smooth, H_mat.to(torch.float32))
        H_rot += act_rot.t() @ act_rot
        total_T += act.shape[0]
    H_rot = H_rot / max(total_T, 1)
    return W_rot, H_rot


def gptq_refine(W_rot, params, H_rot, damping=1e-6):
    """GPTQ mantissa 二阶舍入精化.

    保持 scale_factor / scale_lv2 / scale_lv3 不变 (来自 _quantize_hif4),
    仅用 H_rot 的 block-diagonal 64x64 子块对 mantissa 做 OBS 补偿舍入.
    damping 控制 H+λI 的 λ: 大 → 接近 RTN (更稳健), 小 → 激进补偿 (过拟合风险).
    """
    M, K = W_rot.shape
    n_blocks = K // GPTQ_BLK

    sf = params["scale_factor"]
    lv2 = params["scale_lv2"]
    lv3 = params["scale_lv3"]

    d = (sf * lv2 * lv3).expand(M, n_blocks, 8, 2, 4).contiguous()
    d_flat = d.reshape(M, K)

    q_deq = torch.zeros_like(W_rot)
    W_work = W_rot.clone()

    for b in range(n_blocks):
        s = b * GPTQ_BLK
        e = s + GPTQ_BLK
        H_b = H_rot[s:e, s:e].clone()
        H_b = H_b + damping * torch.eye(GPTQ_BLK, dtype=H_b.dtype, device=H_b.device)

        try:
            L = torch.linalg.cholesky(H_b)
            H_b_inv = torch.cholesky_inverse(L)
        except Exception:
            q_deq[:, s:e] = _hif4_dequant(params, W_rot.shape)[:, s:e]
            continue

        W_b = W_work[:, s:e]
        d_b = d_flat[:, s:e]

        for j in range(GPTQ_BLK):
            mant_int = (W_b[:, j] / d_b[:, j] * 4.0).round().clamp(-7, 7)
            q_j = mant_int / 4.0 * d_b[:, j]
            q_deq[:, s + j] = q_j
            err = W_b[:, j] - q_j
            if j < GPTQ_BLK - 1:
                coef = H_b_inv[j, j + 1:] / H_b_inv[j, j].clamp(min=1e-12)
                W_b[:, j + 1:] -= err.unsqueeze(-1) * coef.unsqueeze(0)

    mant_int = (q_deq / d_flat * 4.0).round().clamp(-7, 7)
    mant = mant_int / 4.0
    sign = torch.sign(mant)
    mant_abs = mant.abs()

    sign_5d = sign.reshape(M, n_blocks, 8, 2, 4).contiguous().float()
    mant_5d = mant_abs.reshape(M, n_blocks, 8, 2, 4).contiguous().float()

    return {
        "scale_factor": params["scale_factor"],
        "scale_lv2": params["scale_lv2"],
        "scale_lv3": params["scale_lv3"],
        "sign": sign_5d,
        "mant": mant_5d,
    }


def gptq_calib(weight_quant, weight_scale, calib_list, damping=1e-6):
    """GPTQ 增强版校准: 在 baseline 基础上精化 mantissa."""
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    params = result["weight_params"]
    state = result["activation_state"]

    if not calib_list:
        return result

    W_rot, H_rot = gptq_reconstruct_rotated_space(weight_quant, weight_scale, calib_list, state)
    refined = gptq_refine(W_rot, params, H_rot, damping=damping)
    return {"weight_params": refined, "activation_state": state}


def main_gptq():
    print("=" * 70)
    print("  GPTQ 二阶 Hessian 舍入 — Linear 场景验证 (阻尼扫描)")
    print("=" * 70)

    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
    ]

    dampings = [1e-6, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0]

    print(f"\n--- Baseline (当前 solution.py, 无 GPTQ) ---")
    base_total, base_avg, _ = run_linear(configs, _baseline_calib, "base", return_scores=True)

    print(f"\n--- GPTQ 阻尼扫描 ---")
    results = {}
    for lam in dampings:
        fn = lambda wq, ws, cl, _l=lam: gptq_calib(wq, ws, cl, damping=_l)
        label = f"λ={lam:.0e}"
        total, avg, _ = run_linear(configs, fn, label, return_scores=True)
        results[lam] = (total, avg)

    print(f"\n{'=' * 70}")
    print(f"  Baseline (RTN):                  总分 {base_total:+.4f}  平均 {base_avg:+.4f}")
    for lam in dampings:
        t, a = results[lam]
        delta = a - base_avg
        pct = delta / max(abs(base_avg), 1e-9) * 100
        tag = " ✓" if delta > 0 else ""
        print(f"  GPTQ λ={lam:<7.0e}:  总分 {t:+.4f}  平均 {a:+.4f}  Δ={delta:+.4f} ({pct:+.2f}%){tag}")
    print(f"{'=' * 70}")

    best_lam = max(results, key=lambda l: results[l][1])
    best_avg = results[best_lam][1]
    if best_avg > base_avg:
        print(f"\n  ✓ 最优阻尼 λ={best_lam:.0e}, 平均分 {best_avg:+.4f} vs baseline {base_avg:+.4f} (Δ={best_avg-base_avg:+.4f})")
    else:
        print(f"\n  ✗ 所有阻尼下 GPTQ 均不优于 baseline (最优 λ={best_lam:.0e}, {results[best_lam][1]:+.4f} vs {base_avg:+.4f})")


# ================================================================================
# Module: hadamard — 全K/大块 Hadamard 旋转
# ================================================================================

def had_largest_pow2_divisor(K, cap=None):
    s = 1
    while s * 2 <= K and K % (s * 2) == 0:
        s *= 2
        if cap is not None and s > cap:
            s //= 2
            break
    return s


def had_make_calib_with_had_size(had_size):
    """Return a calib function that patches solution.HAD_SIZE."""
    def _calib(weight_quant, weight_scale, calib_activation_list):
        K = weight_quant.shape[-1]
        if callable(had_size):
            hs = had_size(K)
        else:
            hs = had_size
            if K % hs != 0:
                hs = had_largest_pow2_divisor(K, cap=hs)
        orig = solution.HAD_SIZE
        solution.HAD_SIZE = hs
        try:
            result = _baseline_calib(weight_quant, weight_scale, calib_activation_list)
        finally:
            solution.HAD_SIZE = orig
        return result
    return _calib


def main_hadamard():
    print("=" * 70)
    print("  全K/大块 Hadamard 旋转 — Linear 场景验证")
    print("=" * 70)

    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=1024, K=512, T=64, seed=47),
        dict(M=768, K=768, T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384, K=768, T=96, seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]

    had_configs = [
        (64, "64 (baseline)"),
        (128, "128"),
        (256, "256"),
        (512, "512"),
        (lambda K: had_largest_pow2_divisor(K), "auto (largest)"),
    ]

    results = {}
    for had_size, label in had_configs:
        fn = had_make_calib_with_had_size(had_size)
        print(f"\n--- Hadamard block = {label} ---")
        t0 = time.time()
        total, avg, _ = run_linear(configs, fn, label, return_scores=True)
        t = time.time() - t0
        results[label] = (total, avg, t)

    print(f"\n{'=' * 70}")
    base_avg = results["64 (baseline)"][1]
    for label, (total, avg, t) in results.items():
        delta = avg - base_avg
        pct = delta / max(abs(base_avg), 1e-9) * 100
        tag = " ✓" if delta > 0 else ""
        print(f"  {label:>20}:  总分 {total:+.4f}  平均 {avg:+.4f}  Δ={delta:+.4f} ({pct:+.2f}%)  ({t:.1f}s){tag}")
    print(f"{'=' * 70}")


# ================================================================================
# Module: optrot — 旋转种子选择 / OptRot
# ================================================================================

def optrot_make_calib_with_seed(seed):
    """Patch solution._random_hadamard to use a fixed seed for HAD_SIZE blocks."""
    def _calib(weight_quant, weight_scale, calib_list):
        orig_fn = solution._random_hadamard
        def _patched(n, seed=42):
            return orig_fn(n, seed=seed)
        solution._random_hadamard = _patched
        try:
            result = _baseline_calib(weight_quant, weight_scale, calib_list)
        finally:
            solution._random_hadamard = orig_fn
        return result
    return _calib


def optrot_weight_fourth_power(W_rot):
    """Compute Σ (W_rot)⁴ — OptRot's smooth proxy for µ_W."""
    return (W_rot ** 4).sum().item()


def optrot_make_calib_optrot(n_steps=30, lr=0.01):
    """OptRot: per-64-block Cayley SGD minimizing Σ(RW)⁴.

    Uses random Hadamard as init, then refines via Cayley parametrization
    on the 64×64 Stiefel manifold. Data-free (only uses W).
    """
    def _calib(weight_quant, weight_scale, calib_list):
        W_fp = _dequant_nvfp4(weight_quant, weight_scale)
        K = W_fp.shape[-1]
        M = W_fp.shape[0]
        n_blocks = K // HAD_SIZE

        H_init = _random_hadamard(HAD_SIZE, seed=42).to(torch.float64)
        H_best = H_init.clone()
        obj_best = sum(optrot_weight_fourth_power(W_fp[:, b * HAD_SIZE:(b + 1) * HAD_SIZE] @ H_init) for b in range(n_blocks))

        A = torch.zeros(HAD_SIZE, HAD_SIZE, dtype=torch.float64, requires_grad=False)
        I = torch.eye(HAD_SIZE, dtype=torch.float64)

        for step in range(n_steps):
            R = torch.linalg.solve(I + A, I - A)

            total_obj = 0.0
            grad_r = None
            for b in range(n_blocks):
                Wb = W_fp[:, b * HAD_SIZE:(b + 1) * HAD_SIZE].to(torch.float64)
                RW = Wb @ R
                RW4 = RW ** 4
                total_obj += RW4.sum().item()
                grad_r = 4.0 * (RW ** 3) @ Wb  # d Σ(RW)⁴ / dR = 4 (RW)³ W^T

                grad_r_proj = grad_r - R @ (grad_r.T @ R + R.T @ grad_r) / 2.0
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0
                grad_r_proj = R.T @ grad_r
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0
                grad_r_proj_expanded = R @ grad_r_proj
                grad_r_proj = grad_r_proj_expanded

                grad_r_proj = (grad_r_proj - R @ (R.T @ grad_r_proj))
                grad_r_proj = grad_r_proj - R @ ((R.T @ grad_r_proj) + (R.T @ grad_r_proj).T) / 2.0

                grad_r_proj_simple = grad_r - R @ (R.T @ grad_r)
                grad_r_proj_simple = R.T @ grad_r_proj_simple
                grad_r_proj_simple = (grad_r_proj_simple - grad_r_proj_simple.T) / 2.0

                grad_r_full = 4.0 * (RW ** 3) @ Wb
                grad_r_full_proj = R.T @ grad_r_full
                grad_r_full_proj = (grad_r_full_proj - grad_r_full_proj.T) / 2.0
                grad_r_proj = grad_r_full_proj

                grad_A = grad_r_proj

            grad_A = grad_r_proj

            grad_A_avg = torch.zeros_like(A)
            R = torch.linalg.solve(I + A, I - A)
            for b in range(n_blocks):
                Wb = W_fp[:, b * HAD_SIZE:(b + 1) * HAD_SIZE].to(torch.float64)
                RW = Wb @ R
                grad_r = 4.0 * (RW ** 3) @ Wb
                grad_r_proj = R.T @ grad_r
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0
                grad_A_avg += grad_r_proj / n_blocks

            A_new = A - lr * grad_A_avg
            A_new = (A_new - A_new.T) / 2.0

            R_new = torch.linalg.solve(I + A_new, I - A_new)
            obj_new = sum(optrot_weight_fourth_power(W_fp[:, b * HAD_SIZE:(b + 1) * HAD_SIZE] @ R_new) for b in range(n_blocks))

            if obj_new < obj_best:
                H_best = R_new.to(torch.float32)
                obj_best = obj_new
                A = A_new
            else:
                lr *= 0.5
                if lr < 1e-6:
                    break

        H_final = H_best.to(torch.float32)

        n_final = _adaptive_n_candidates(W_fp.shape)

        if not calib_list:
            weight_rot = _apply_hadamard(W_fp, H_final)
            weight_params = _quantize_hif4(weight_rot, n_candidates=n_final)
            w_hat = _hif4_dequant(weight_params, weight_rot.shape)
            w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)
            return {"weight_params": weight_params,
                    "activation_state": {"hadamard": H_final.contiguous(),
                                          "importance": w_diag.contiguous(),
                                          "smooth_scale": None}}

        calib_acts = [_dequant_nvfp4(aq, asc) for aq, asc in calib_list]
        max_act = torch.zeros(K, dtype=torch.float32)
        for act in calib_acts:
            max_act = torch.maximum(max_act, act.abs().amax(dim=0))
        max_w = W_fp.abs().amax(dim=0).clamp(min=1e-8)

        n_scan = min(256, W_fp.shape[0])
        w_scan = W_fp[:n_scan]
        best_proxy = None
        for alpha in (None, 0.5):
            if alpha is None:
                D = torch.ones(K, dtype=torch.float32)
            else:
                D = (max_act.clamp(min=1e-8) ** alpha) / (max_w ** (1 - alpha))
                D = D.clamp(min=1e-4, max=1e4)
            w_rot = _apply_hadamard(w_scan * D, H_final)
            x_sq_sum = torch.zeros(K, dtype=torch.float32)
            total_tokens = 0
            for act in calib_acts:
                act_rot = _apply_hadamard(act * (1.0 / D), H_final)
                x_sq_sum += (act_rot ** 2).sum(dim=0)
                total_tokens += act.shape[0]
            w_imp = (x_sq_sum / max(total_tokens, 1)).clamp(min=1e-8)
            wp = _quantize_hif4(w_rot, n_candidates=3, importance=w_imp)
            w_hat = _hif4_dequant(wp, w_rot.shape)
            proxy = (w_imp * (w_hat - w_rot) ** 2).sum().item() / n_scan
            if best_proxy is None or proxy < best_proxy[0]:
                best_proxy = (proxy, alpha, D, w_imp)

        alpha, D, w_imp = best_proxy[1], best_proxy[2], best_proxy[3]
        w_smooth = W_fp * D
        w_rot = _apply_hadamard(w_smooth, H_final)
        weight_params = _quantize_hif4(w_rot, n_candidates=n_final, importance=w_imp)
        w_hat = _hif4_dequant(weight_params, w_rot.shape)
        w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)
        smooth_D = D if alpha is not None else None

        return {"weight_params": weight_params,
                "activation_state": {"hadamard": H_final.contiguous(),
                                      "importance": w_diag.contiguous(),
                                      "smooth_scale": smooth_D.contiguous() if smooth_D is not None else None}}

    return _calib


def main_optrot():
    print("=" * 70)
    print("  研究点五：旋转种子选择 / OptRot — Linear 场景验证")
    print("=" * 70)

    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=1024, K=512, T=64, seed=47),
        dict(M=768, K=768, T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384, K=768, T=96, seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]

    # === 阶段1: 多种子扫描 ===
    print(f"\n--- 阶段1: 多种子扫描 (验证种子选择是否有增益) ---")
    seeds = [42, 1, 7, 13, 21, 100, 2024, 999]
    seed_results = {}
    for seed in seeds:
        fn = optrot_make_calib_with_seed(seed)
        label = f"seed={seed}"
        total, avg = run_linear(configs, fn, label)
        seed_results[seed] = (total, avg)

    avgs = [v[1] for v in seed_results.values()]
    avg_mean = sum(avgs) / len(avgs)
    avg_min = min(avgs)
    avg_max = max(avgs)
    avg_std = (sum((a - avg_mean) ** 2 for a in avgs) / len(avgs)) ** 0.5

    print(f"\n  种子扫描统计:")
    print(f"    mean={avg_mean:+.4f}  std={avg_std:.4f}  min={avg_min:+.4f}  max={avg_max:+.4f}")
    print(f"    max-min={avg_max - avg_min:+.4f}  (SpinQuant 报告 13pt 差异)")
    print(f"    baseline(seed=42)={seed_results[42][1]:+.4f}")

    best_seed = max(seed_results, key=lambda s: seed_results[s][1])
    delta_best = seed_results[best_seed][1] - seed_results[42][1]
    print(f"    best seed={best_seed}, Δ(42)={delta_best:+.4f} ({delta_best/max(abs(seed_results[42][1]),1e-9)*100:+.2f}%)")

    if delta_best > 0.001:
        print(f"\n  ✓ 种子选择有效! 进入阶段2: OptRot 四阶矩最小化")
        print(f"\n--- 阶段2: OptRot 四阶矩最小化 (Cayley SGD) ---")
        t0 = time.time()
        fn = optrot_make_calib_optrot(n_steps=30, lr=0.01)
        total, avg = run_linear(configs, fn, "optrot")
        t_opt = time.time() - t0

        print(f"\n{'=' * 70}")
        print(f"  Baseline (seed=42):  {seed_results[42][1]:+.4f}")
        print(f"  Best seed ({best_seed}):  {seed_results[best_seed][1]:+.4f}  Δ={delta_best:+.4f}")
        print(f"  OptRot:              {avg:+.4f}  Δ={avg - seed_results[42][1]:+.4f}  ({t_opt:.1f}s)")
        print(f"{'=' * 70}")
    else:
        print(f"\n  ✗ 种子选择无显著差异 (Δ={delta_best:+.4f}), OptRot 不可行")

    print(f"\n{'=' * 70}")
    print(f"  最终对比:")
    print(f"  Baseline (seed=42):  {seed_results[42][1]:+.4f}")
    print(f"  种子扫描 mean:       {avg_mean:+.4f}  std={avg_std:.4f}")
    print(f"  种子扫描 best:       {avg_max:+.4f}  (seed={best_seed})")
    if delta_best > 0.001:
        print(f"  OptRot:              {avg:+.4f}")
    print(f"{'=' * 70}")


# ================================================================================
# Module: owq — OWQ 候选预算扫描
# ================================================================================

def owq_make_calib_with_ncand(ncand):
    """Patch _adaptive_n_candidates to always return ncand."""
    def _calib(weight_quant, weight_scale, calib_list):
        orig = solution._adaptive_n_candidates
        solution._adaptive_n_candidates = lambda shape: ncand
        try:
            result = _baseline_calib(weight_quant, weight_scale, calib_list)
        finally:
            solution._adaptive_n_candidates = orig
        return result
    return _calib


def main_owq():
    print("=" * 70)
    print("  OWQ 候选预算扫描 — Linear 场景验证")
    print("=" * 70)

    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=1024, K=512, T=64, seed=47),
        dict(M=768, K=768, T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384, K=768, T=96, seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]

    ncand_list = [5, 7, 9, 13, 17]

    results = {}
    for nc in ncand_list:
        label = f"n_cand={nc}"
        fn = owq_make_calib_with_ncand(nc)
        print(f"\n--- {label} ---")
        t0 = time.time()
        total, avg = run_linear(configs, fn, label)
        t = time.time() - t0
        results[label] = (total, avg, t)

    print(f"\n{'=' * 70}")
    base_avg = results["n_cand=9"][1]
    for label, (total, avg, t) in results.items():
        delta = avg - base_avg
        pct = delta / max(abs(base_avg), 1e-9) * 100
        tag = " ✓" if delta > 0 else ""
        print(f"  {label:>12}:  总分 {total:+.4f}  平均 {avg:+.4f}  Δ(9)={delta:+.4f} ({pct:+.2f}%)  ({t:.1f}s){tag}")
    print(f"{'=' * 70}")


# ================================================================================
# Module: residual_em — IRLS 残差精化 + EM 交替
# ================================================================================

def em_reconstruct_rotated(weight_quant, weight_scale, calib_list, state):
    W_fp = _dequant_nvfp4(weight_quant, weight_scale)
    H_mat = state.get("hadamard")
    D = state.get("smooth_scale")
    w_imp = state.get("importance")
    W_smooth = W_fp if D is None else W_fp * D.to(torch.float32)
    W_rot = W_smooth if H_mat is None else _apply_hadamard(W_smooth, H_mat.to(torch.float32))
    return W_rot, w_imp


def em_calib_irls(weight_quant, weight_scale, calib_list, alpha=1.0):
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    if not calib_list:
        return result
    params1 = result["weight_params"]
    state = result["activation_state"]
    W_rot, w_imp = em_reconstruct_rotated(weight_quant, weight_scale, calib_list, state)
    if w_imp is None:
        return result
    W_hat1 = _hif4_dequant(params1, W_rot.shape)
    R = W_rot - W_hat1
    R_sq_per_chan = (R ** 2).mean(dim=0)
    R_sq_norm = R_sq_per_chan / (R_sq_per_chan.max() + 1e-12)
    w_imp_new = w_imp * (1.0 + alpha * R_sq_norm)
    n_final = _adaptive_n_candidates(W_rot.shape)
    params2 = _quantize_hif4(W_rot, n_candidates=n_final, importance=w_imp_new)
    W_hat2 = _hif4_dequant(params2, W_rot.shape)
    mse1 = (w_imp * (W_hat1 - W_rot) ** 2).sum().item()
    mse2 = (w_imp * (W_hat2 - W_rot) ** 2).sum().item()
    if mse2 < mse1:
        return {"weight_params": params2, "activation_state": state}
    return result


def em_calib_em(weight_quant, weight_scale, calib_list, n_iters=3):
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    if not calib_list:
        return result
    params = result["weight_params"]
    state = result["activation_state"]
    W_rot, w_imp = em_reconstruct_rotated(weight_quant, weight_scale, calib_list, state)
    if w_imp is None:
        return result
    best_mse = (w_imp * (_hif4_dequant(params, W_rot.shape) - W_rot) ** 2).sum().item()
    for it in range(n_iters):
        W_hat = _hif4_dequant(params, W_rot.shape)
        w_diag_new = (W_hat ** 2).sum(dim=0).clamp(min=1e-8)
        n_final = _adaptive_n_candidates(W_rot.shape)
        params_new = _quantize_hif4(W_rot, n_candidates=n_final, importance=w_diag_new)
        W_hat_new = _hif4_dequant(params_new, W_rot.shape)
        mse_new = (w_imp * (W_hat_new - W_rot) ** 2).sum().item()
        if mse_new < best_mse:
            params = params_new
            best_mse = mse_new
            state = dict(state)
            state["importance"] = w_diag_new.contiguous()
        else:
            break
    return {"weight_params": params, "activation_state": state}


def main_residual_em():
    print("=" * 70)
    print("  研究点六+七: IRLS 残差精化 + EM 交替 — Linear 验证")
    print("=" * 70)
    configs = [
        dict(M=512, K=512, T=128, seed=42),
        dict(M=1024, K=1024, T=256, seed=43),
        dict(M=256, K=512, T=64, seed=44),
        dict(M=2048, K=2048, T=128, seed=45),
        dict(M=512, K=1024, T=256, seed=46),
        dict(M=1024, K=512, T=64, seed=47),
        dict(M=768, K=768, T=192, seed=48),
        dict(M=1280, K=1280, T=128, seed=49),
        dict(M=384, K=768, T=96, seed=50),
        dict(M=1536, K=1024, T=160, seed=51),
    ]

    print(f"\n--- Baseline ---")
    base_total, base_avg = run_linear(configs, _baseline_calib, "baseline")

    print(f"\n--- 研究点六: IRLS α=1.0 ---")
    t0 = time.time()
    fn = lambda wq, ws, cl: em_calib_irls(wq, ws, cl, alpha=1.0)
    r_total, r_avg = run_linear(configs, fn, "irls_a1")
    t_r = time.time() - t0

    print(f"\n--- 研究点六: IRLS α=0.5 ---")
    fn2 = lambda wq, ws, cl: em_calib_irls(wq, ws, cl, alpha=0.5)
    r2_total, r2_avg = run_linear(configs, fn2, "irls_a0.5")

    print(f"\n--- 研究点六: IRLS α=2.0 ---")
    fn3 = lambda wq, ws, cl: em_calib_irls(wq, ws, cl, alpha=2.0)
    r3_total, r3_avg = run_linear(configs, fn3, "irls_a2")

    print(f"\n--- 研究点七: EM 交替 (3 iters) ---")
    t0 = time.time()
    em_fn = lambda wq, ws, cl: em_calib_em(wq, ws, cl, n_iters=3)
    em_total, em_avg = run_linear(configs, em_fn, "em_3")
    t_em = time.time() - t0

    print(f"\n{'=' * 70}")
    print(f"  Baseline:     {base_avg:+.4f}")
    print(f"  IRLS α=1.0:   {r_avg:+.4f}  Δ={r_avg - base_avg:+.4f} ({(r_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)  ({t_r:.1f}s)")
    print(f"  IRLS α=0.5:   {r2_avg:+.4f}  Δ={r2_avg - base_avg:+.4f} ({(r2_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)")
    print(f"  IRLS α=2.0:   {r3_avg:+.4f}  Δ={r3_avg - base_avg:+.4f} ({(r3_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)")
    print(f"  EM 交替 (3):  {em_avg:+.4f}  Δ={em_avg - base_avg:+.4f} ({(em_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)  ({t_em:.1f}s)")
    print(f"{'=' * 70}")


# ================================================================================
# Module: vclip — V per-token clip 策略
# ================================================================================

def vclip_percentile(x, percentile=99):
    """Clip tensor to percentile of absolute values."""
    if percentile >= 100:
        return x
    abs_x = x.abs()
    thresh = torch.quantile(abs_x.flatten(), percentile / 100.0)
    thresh = max(thresh.item(), 1e-8)
    return x.clamp(-thresh, thresh)


def vclip_per_channel(x, percentile=99):
    """Clip per-channel (last dim) to percentile."""
    if percentile >= 100:
        return x
    abs_x = x.abs()
    thresh = torch.quantile(abs_x, percentile / 100.0, dim=0, keepdim=True)
    thresh = thresh.clamp(min=1e-8)
    return torch.where(x.abs() > thresh, torch.sign(x) * thresh, x)


def vclip_make_calib(percentile, per_channel=False):
    """V per-token clip: 在动态量化时 clip V 到百分位."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        return _baseline_calib_attn(calib_qkv_list, qh, kvh, hd)
    return _calib


def vclip_run_attn(configs, percentile, per_channel=False, label=""):
    """Run attention scoring with V clip applied at dynamic quantization."""
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']

        calib = _baseline_calib_attn(group['calib'], qh, kvh, hd)
        q_state = calib['q_state']
        k_state = calib['k_state']
        v_state = calib['v_state']
        H_q = q_state.get('hadamard')

        test_scores = []
        for sample in group['test']:
            Q_ref = _dequant_nvfp4(*sample['q'])
            K_ref = _dequant_nvfp4(*sample['k'])
            V_ref = _dequant_nvfp4(*sample['v'])

            Q_p = _apply_hadamard(Q_ref, H_q) if H_q is not None else Q_ref
            K_p = _apply_hadamard(K_ref, H_q) if H_q is not None else K_ref

            Q_params = _quantize_hif4(Q_p, n_candidates=_adaptive_n_candidates(Q_p.shape))
            K_params = _quantize_hif4(K_p, n_candidates=_adaptive_n_candidates(K_p.shape))
            Q_hat = _hif4_dequant(Q_params, Q_p.shape)
            K_hat = _hif4_dequant(K_params, K_p.shape)

            V_clipped = V_ref
            if percentile < 100:
                if per_channel:
                    V_clipped = vclip_per_channel(V_ref, percentile)
                else:
                    V_clipped = vclip_percentile(V_ref, percentile)

            rho = v_state.get('rho')
            calib_seq = v_state.get('calib_seq')
            rho_mean = v_state.get('rho_mean')
            kv_hidden = kvh * hd
            test_seq = V_ref.shape[0]
            imp = None
            if rho is not None and calib_seq is not None and test_seq == calib_seq:
                imp = rho.to(torch.float32).transpose(0, 1).repeat_interleave(hd, dim=1)
                if int(imp.shape[-1]) != int(V_clipped.shape[-1]):
                    imp = None
            else:
                if rho_mean is not None and int(rho_mean.shape[-1]) == kv_hidden:
                    imp = rho_mean.to(torch.float32)

            V_params = _quantize_hif4(V_clipped, n_candidates=_adaptive_n_candidates(V_clipped.shape), importance=imp)
            V_hat = _hif4_dequant(V_params, V_clipped.shape)

            ref_out = ss.gqa_attention(Q_p, K_p, V_ref, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(Q_p), Q_p.shape),
                _dequantize_hif4(standard_hif4_quantize(K_p), K_p.shape),
                _dequantize_hif4(standard_hif4_quantize(V_ref), V_ref.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)

            mse_std = ((ref_out - std_out) ** 2).mean().item()
            mse_player = ((ref_out - player_out) ** 2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))

        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    return total, avg


def main_vclip():
    print("=" * 70)
    print("  V per-token clip 策略验证")
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

    print(f"\n--- Baseline (无 clip) ---")
    b_total, b_avg = vclip_run_attn(configs, 100, label="baseline")

    print(f"\n--- V 全局 clip ---")
    for p in [99.9, 99, 98, 95, 90]:
        vclip_run_attn(configs, p, per_channel=False, label=f"clip_p{p}")

    print(f"\n--- V per-channel clip ---")
    for p in [99, 95, 90]:
        vclip_run_attn(configs, p, per_channel=True, label=f"chan_p{p}")

    print(f"\n--- Q/K clip (Q@K^T 误差被 softmax 吸收?) ---")
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']
        calib = _baseline_calib_attn(group['calib'], qh, kvh, hd)
        H_q = calib['q_state'].get('hadamard')
        v_state = calib['v_state']
        test_scores = []
        for sample in group['test']:
            Q_ref = _dequant_nvfp4(*sample['q'])
            K_ref = _dequant_nvfp4(*sample['k'])
            V_ref = _dequant_nvfp4(*sample['v'])
            Q_p = _apply_hadamard(Q_ref, H_q) if H_q is not None else Q_ref
            K_p = _apply_hadamard(K_ref, H_q) if H_q is not None else K_ref
            Q_p_c = vclip_percentile(Q_p, 99)
            K_p_c = vclip_percentile(K_p, 99)
            Q_params = _quantize_hif4(Q_p_c, n_candidates=_adaptive_n_candidates(Q_p_c.shape))
            K_params = _quantize_hif4(K_p_c, n_candidates=_adaptive_n_candidates(K_p_c.shape))
            Q_hat = _hif4_dequant(Q_params, Q_p_c.shape)
            K_hat = _hif4_dequant(K_params, K_p_c.shape)
            rho = v_state.get('rho')
            calib_seq = v_state.get('calib_seq')
            rho_mean = v_state.get('rho_mean')
            test_seq = V_ref.shape[0]
            imp = None
            if rho is not None and calib_seq is not None and test_seq == calib_seq:
                imp = rho.to(torch.float32).transpose(0, 1).repeat_interleave(hd, dim=1)
                if int(imp.shape[-1]) != int(V_ref.shape[-1]): imp = None
            else:
                if rho_mean is not None and int(rho_mean.shape[-1]) == kvh * hd: imp = rho_mean.to(torch.float32)
            V_params = _quantize_hif4(V_ref, n_candidates=_adaptive_n_candidates(V_ref.shape), importance=imp)
            V_hat = _hif4_dequant(V_params, V_ref.shape)
            ref_out = ss.gqa_attention(Q_p, K_p, V_ref, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(Q_p), Q_p.shape),
                _dequantize_hif4(standard_hif4_quantize(K_p), K_p.shape),
                _dequantize_hif4(standard_hif4_quantize(V_ref), V_ref.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)
            mse_std = ((ref_out - std_out) ** 2).mean().item()
            mse_player = ((ref_out - player_out) ** 2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))
        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [qk_clip_p99] 总分: {total:+.4f}  平均: {avg:+.4f}")

    print(f"\n--- Q/K + V 全部 clip p99 ---")
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']
        calib = _baseline_calib_attn(group['calib'], qh, kvh, hd)
        H_q = calib['q_state'].get('hadamard')
        v_state = calib['v_state']
        test_scores = []
        for sample in group['test']:
            Q_ref = _dequant_nvfp4(*sample['q'])
            K_ref = _dequant_nvfp4(*sample['k'])
            V_ref = _dequant_nvfp4(*sample['v'])
            Q_p = _apply_hadamard(vclip_percentile(Q_ref, 99), H_q) if H_q is not None else vclip_percentile(Q_ref, 99)
            K_p = _apply_hadamard(vclip_percentile(K_ref, 99), H_q) if H_q is not None else vclip_percentile(K_ref, 99)
            V_c = vclip_percentile(V_ref, 99)
            Q_params = _quantize_hif4(Q_p, n_candidates=_adaptive_n_candidates(Q_p.shape))
            K_params = _quantize_hif4(K_p, n_candidates=_adaptive_n_candidates(K_p.shape))
            V_params = _quantize_hif4(V_c, n_candidates=_adaptive_n_candidates(V_c.shape),
                                       importance=v_state.get('rho').to(torch.float32).transpose(0, 1).repeat_interleave(hd, dim=1) if v_state.get('rho') is not None and V_c.shape[0] == v_state.get('calib_seq') else None)
            Q_hat = _hif4_dequant(Q_params, Q_p.shape)
            K_hat = _hif4_dequant(K_params, K_p.shape)
            V_hat = _hif4_dequant(V_params, V_c.shape)
            ref_out = ss.gqa_attention(_apply_hadamard(Q_ref, H_q) if H_q is not None else Q_ref,
                                        _apply_hadamard(K_ref, H_q) if H_q is not None else K_ref, V_ref, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(_apply_hadamard(Q_ref, H_q) if H_q is not None else Q_ref), Q_ref.shape),
                _dequantize_hif4(standard_hif4_quantize(_apply_hadamard(K_ref, H_q) if H_q is not None else K_ref), K_ref.shape),
                _dequantize_hif4(standard_hif4_quantize(V_ref), V_ref.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)
            mse_std = ((ref_out - std_out) ** 2).mean().item()
            mse_player = ((ref_out - player_out) ** 2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))
        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [all_clip_p99] 总分: {total:+.4f}  平均: {avg:+.4f}")


# ================================================================================
# Module registry & CLI
# ================================================================================

MODULES = {
    "attn":            ("Attention 研究点验证 (V imp + Q/K imp + grouped rotation)", main_attn),
    "awq":             ("AWQ/SmoothQuant 变体 Linear 验证",                         main_awq),
    "direct_mapping":  ("NVFP4→HiF4 直接精确映射 Linear 验证",                     main_direct_mapping),
    "direct_attn":     ("Attention V 直接 NVFP4→HiF4 carrier 提取映射",            main_direct_attn),
    "gptq":            ("GPTQ 二阶 Hessian OBS 舍入精化 Linear 验证",               main_gptq),
    "hadamard":        ("全K/大块 Hadamard 旋转 Linear 验证",                       main_hadamard),
    "optrot":          ("旋转种子选择 + OptRot 四阶矩 Cayley SGD Linear 验证",      main_optrot),
    "owq":             ("OWQ 候选预算扫描 Linear 验证",                             main_owq),
    "residual_em":     ("IRLS 残差重加权 + EM 交替 Linear 验证",                    main_residual_em),
    "vclip":           ("V per-token clip 策略 Attention 验证",                     main_vclip),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="研究点验证合并脚本 (原 verify_*.py × 10)"
    )
    parser.add_argument(
        "--module",
        choices=list(MODULES.keys()) + ["all"],
        default=None,
        help="要运行的验证模块 (不指定则列出可用模块)",
    )
    args = parser.parse_args()

    if args.module is None:
        print("可用验证模块:\n")
        for name, (desc, _) in MODULES.items():
            print(f"  {name:<16} {desc}")
        print(f"\n  {'all':<16} 运行全部模块")
        print(f"\n用法: python3 verify.py --module <name>")
        return 0

    if args.module == "all":
        for name, (desc, fn) in MODULES.items():
            print(f"\n{'#' * 70}")
            print(f"# Module: {name} — {desc}")
            print(f"{'#' * 70}")
            fn()
        return 0

    desc, fn = MODULES[args.module]
    fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
