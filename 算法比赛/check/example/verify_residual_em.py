#!/usr/bin/env python3
"""verify_residual_em.py — 研究点六+七: IRLS 残差精化 + EM 交替

研究点六 (IRLS 残差重加权):
  Pass 1: 标准量化 (importance=λ_j) → params1, 残差 R
  Pass 2: λ_j' = λ_j * (1 + α * R_j²_norm) → 重新量化
  IRLS: 大残差通道获更高权重

研究点七 (单边 EM):
  迭代更新 w_diag (X importance) based on W_hat
  每轮: 量化 W → 更新 w_diag → 传给 X 在线量化

A@W 合规: 仅用 W, λ_j (from X^TX), w_diag (from W^TW)
"""
from __future__ import annotations
import os, sys, time
import torch

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

from solution import (
    _dequant_nvfp4, _apply_hadamard, _hif4_dequant, _quantize_hif4,
    _adaptive_n_candidates, _random_hadamard, HAD_SIZE,
    hif4_calibration_and_quantize_weight as _baseline_calib,
)
import simulate_scoring as ss


def _reconstruct_rotated(weight_quant, weight_scale, calib_list, state):
    W_fp = _dequant_nvfp4(weight_quant, weight_scale)
    H_mat = state.get("hadamard")
    D = state.get("smooth_scale")
    w_imp = state.get("importance")
    W_smooth = W_fp if D is None else W_fp * D.to(torch.float32)
    W_rot = W_smooth if H_mat is None else _apply_hadamard(W_smooth, H_mat.to(torch.float32))
    return W_rot, w_imp


def calib_irls(weight_quant, weight_scale, calib_list, alpha=1.0):
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    if not calib_list:
        return result
    params1 = result["weight_params"]
    state = result["activation_state"]
    W_rot, w_imp = _reconstruct_rotated(weight_quant, weight_scale, calib_list, state)
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


def calib_em(weight_quant, weight_scale, calib_list, n_iters=3):
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    if not calib_list:
        return result
    params = result["weight_params"]
    state = result["activation_state"]
    W_rot, w_imp = _reconstruct_rotated(weight_quant, weight_scale, calib_list, state)
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
    fn = lambda wq, ws, cl: calib_irls(wq, ws, cl, alpha=1.0)
    r_total, r_avg = run_linear(configs, fn, "irls_a1")
    t_r = time.time() - t0

    print(f"\n--- 研究点六: IRLS α=0.5 ---")
    fn2 = lambda wq, ws, cl: calib_irls(wq, ws, cl, alpha=0.5)
    r2_total, r2_avg = run_linear(configs, fn2, "irls_a0.5")

    print(f"\n--- 研究点六: IRLS α=2.0 ---")
    fn3 = lambda wq, ws, cl: calib_irls(wq, ws, cl, alpha=2.0)
    r3_total, r3_avg = run_linear(configs, fn3, "irls_a2")

    print(f"\n--- 研究点七: EM 交替 (3 iters) ---")
    t0 = time.time()
    em_fn = lambda wq, ws, cl: calib_em(wq, ws, cl, n_iters=3)
    em_total, em_avg = run_linear(configs, em_fn, "em_3")
    t_em = time.time() - t0

    print(f"\n{'=' * 70}")
    print(f"  Baseline:     {base_avg:+.4f}")
    print(f"  IRLS α=1.0:   {r_avg:+.4f}  Δ={r_avg - base_avg:+.4f} ({(r_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)  ({t_r:.1f}s)")
    print(f"  IRLS α=0.5:   {r2_avg:+.4f}  Δ={r2_avg - base_avg:+.4f} ({(r2_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)")
    print(f"  IRLS α=2.0:   {r3_avg:+.4f}  Δ={r3_avg - base_avg:+.4f} ({(r3_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)")
    print(f"  EM 交替 (3):  {em_avg:+.4f}  Δ={em_avg - base_avg:+.4f} ({(em_avg - base_avg)/max(abs(base_avg),1e-9)*100:+.2f}%)  ({t_em:.1f}s)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
