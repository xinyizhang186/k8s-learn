#!/usr/bin/env python3
"""
verify_awq.py — 验证 AWQ 逐通道显著保护 / mean统计 / 更多alpha 对 HiF4 Linear 的增益

对比 SmoothQuant 变体:
  V0 baseline:  max 统计, {None, 0.5},  D = max_X^a / max_W^(1-a)
  V1 more_alpha: max 统计, {None, 0.25, 0.5, 0.75}
  V2 mean_sq:    mean 统计, {None, 0.25, 0.5, 0.75}, D = mean_X^a / mean_W^(1-a)
  V3 awq:        mean 统计, {None, 0.25, 0.5, 0.75}, D = mean_X^a * mean_W^(1-a)

所有变体共用: 64-Hadamard + exact 微指数 + 对角重要性 + proxy MSE 选择.
"""
from __future__ import annotations

import os
import sys
import time

import torch

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

from solution import (
    _dequant_nvfp4,
    _apply_hadamard,
    _hif4_dequant,
    _quantize_hif4,
    _adaptive_n_candidates,
    _random_hadamard,
    HAD_SIZE,
    hif4_calibration_and_quantize_weight as _baseline_calib,
)
import simulate_scoring as ss


def _compute_stats(calib_acts, weight_fp, mode):
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


def _compute_D(stat_X, stat_W, alpha, formula):
    if alpha is None:
        return torch.ones_like(stat_X)
    if formula == "smoothquant":
        D = (stat_X.clamp(min=1e-8) ** alpha) / (stat_W ** (1 - alpha))
    else:
        D = (stat_X ** alpha) * (stat_W ** (1 - alpha))
    return D.clamp(min=1e-4, max=1e4)


def calib_variant(weight_quant, weight_scale, calib_list, mode="baseline"):
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
    stat_X, stat_W = _compute_stats(calib_acts, weight_fp, mode)

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
        D = _compute_D(stat_X, stat_W, alpha, formula)
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


def run_linear(configs, calib_fn, label):
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
    print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    return total, avg


def main():
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
        ("V0 max {None,0.5} (reimpl)", lambda wq, ws, cl: calib_variant(wq, ws, cl, "baseline")),
        ("V1 max {None,.25,.5,.75}", lambda wq, ws, cl: calib_variant(wq, ws, cl, "more_alpha")),
        ("V2 mean {None,.25,.5,.75} sq", lambda wq, ws, cl: calib_variant(wq, ws, cl, "mean_sq")),
        ("V3 mean {None,.25,.5,.75} awq", lambda wq, ws, cl: calib_variant(wq, ws, cl, "awq")),
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


if __name__ == "__main__":
    main()
