#!/usr/bin/env python3
"""
verify_optrot.py — 验证研究点五：旋转种子选择 / OptRot 对 HiF4 Linear 的增益

分两阶段:
  阶段1 多种子扫描: 扫描多个固定 seed, 确认"种子选择"是否有增益
    - 若多种子间分数差异显著 → 种子选择有效, 进入阶段2
    - 若无差异 → OptRot 不可行
  阶段2 四阶矩代理: 对每个 64-block, 用 min_R Σ(RW)⁴ 选旋转 (Cayley SGD)
    - 理论 (OptRot arXiv:2512.24124): 四阶矩是 µ_W 的平滑上界代理
    - 数据无关, 仅用 W

A@W 合规: 仅用 W 的统计量 (四阶矩 / max), 不计算 X@W
"""
from __future__ import annotations

import math
import os
import sys
import time

import torch

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

import solution
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


def _make_calib_with_seed(seed):
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


def _weight_fourth_power(W_rot):
    """Compute Σ (W_rot)⁴ — OptRot's smooth proxy for µ_W."""
    return (W_rot ** 4).sum().item()


def _make_calib_optrot(n_steps=30, lr=0.01):
    """OptRot: per-64-block Cayley SGD minimizing Σ(RW)⁴.

    Uses random Hadamard as init, then refines via Cayley parametrization
    on the 64×64 Stiefel manifold. Data-free (only uses W).
    """
    def _calib(weight_quant, weight_scale, calib_list):
        W_fp = _dequant_nvfp4(weight_quant, weight_scale)
        K = W_fp.shape[-1]
        M = W_fp.shape[0]
        n_blocks = K // HAD_SIZE

        # Init with random Hadamard (seed=42 baseline)
        H_init = _random_hadamard(HAD_SIZE, seed=42).to(torch.float64)
        H_best = H_init.clone()
        obj_best = sum(_weight_fourth_power(W_fp[:, b*HAD_SIZE:(b+1)*HAD_SIZE] @ H_init) for b in range(n_blocks))

        # Cayley SGD: R = (I - A)(I + A)^{-1}, A skew-symmetric
        # Gradient of Σ(RW)⁴ w.r.t. R: 4 * (RW)³ @ W^T
        A = torch.zeros(HAD_SIZE, HAD_SIZE, dtype=torch.float64, requires_grad=False)
        I = torch.eye(HAD_SIZE, dtype=torch.float64)

        for step in range(n_steps):
            # R = (I - A)(I + A)^{-1} via Cayley
            # Avoid matrix inverse: solve (I + A) X = (I - A)
            R = torch.linalg.solve(I + A, I - A)

            # Compute objective and gradient (sum over all blocks)
            total_obj = 0.0
            grad_R = torch.zeros_like(R)
            for b in range(n_blocks):
                Wb = W_fp[:, b*HAD_SIZE:(b+1)*HAD_SIZE].to(torch.float64)
                RW = Wb @ R
                RW4 = RW ** 4
                total_obj += RW4.sum().item()
                grad_r = 4.0 * (RW ** 3) @ Wb  # d Σ(RW)⁴ / dR = 4 (RW)³ W^T

                # Project gradient onto tangent space of Stiefel manifold at R
                # Tangent: Z = R @ skew(R^T @ grad_r)  (for orthogonal R)
                grad_r_proj = grad_r - R @ (grad_r.T @ R + R.T @ grad_r) / 2.0
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0  # skew-symmetrize? No, keep as is for Cayley
                grad_r_proj = R.T @ grad_r  # project to A-space
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0
                grad_r_proj_expanded = R @ grad_r_proj  # back to R-space
                grad_r_proj = grad_r_proj_expanded  # use as gradient

                grad_r_proj = (grad_r_proj - R @ (R.T @ grad_r_proj))  # project to tangent
                grad_r_proj = grad_r_proj - R @ ((R.T @ grad_r_proj) + (R.T @ grad_r_proj).T) / 2.0

                grad_r_proj_simple = grad_r - R @ (R.T @ grad_r)  # simple tangent projection
                grad_r_proj_simple = R.T @ grad_r_proj_simple
                grad_r_proj_simple = (grad_r_proj_simple - grad_r_proj_simple.T) / 2.0

                # Accumulate gradient in A-space
                grad_r_full = 4.0 * (RW ** 3) @ Wb  # full gradient in R-space
                grad_r_full_proj = R.T @ grad_r_full  # to A-space
                grad_r_full_proj = (grad_r_full_proj - grad_r_full_proj.T) / 2.0  # skew-symmetrize for A
                grad_r_proj = grad_r_full_proj

                # Jacobian of Cayley: dR/dA ≈ -2(I + A)^{-1} (for small A)
                # Approximate: grad_A ≈ grad_R_proj (ignoring Jacobian for simplicity)
                grad_A = grad_r_proj

            grad_A = grad_r_proj  # use last block's gradient (simplified: use block-averaged)

            # Recompute grad_A as average over blocks
            grad_A_avg = torch.zeros_like(A)
            R = torch.linalg.solve(I + A, I - A)
            for b in range(n_blocks):
                Wb = W_fp[:, b*HAD_SIZE:(b+1)*HAD_SIZE].to(torch.float64)
                RW = Wb @ R
                grad_r = 4.0 * (RW ** 3) @ Wb
                grad_r_proj = R.T @ grad_r
                grad_r_proj = (grad_r_proj - grad_r_proj.T) / 2.0
                grad_A_avg += grad_r_proj / n_blocks

            # Update A
            A_new = A - lr * grad_A_avg
            # Ensure skew-symmetry
            A_new = (A_new - A_new.T) / 2.0

            # Check if objective improved
            R_new = torch.linalg.solve(I + A_new, I - A_new)
            obj_new = sum(_weight_fourth_power(W_fp[:, b*HAD_SIZE:(b+1)*HAD_SIZE] @ R_new) for b in range(n_blocks))

            if obj_new < obj_best:
                H_best = R_new.to(torch.float32)
                obj_best = obj_new
                A = A_new
            else:
                lr *= 0.5
                if lr < 1e-6:
                    break

        # Use H_best for quantization
        H_final = H_best.to(torch.float32)

        # Replicate baseline calibration but with optimized H
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

        # Use baseline's SmoothQuant selection but with optimized H
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


def run_linear(configs, calib_fn, label, verbose=True):
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
    return total, avg


def main():
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
        fn = _make_calib_with_seed(seed)
        label = f"seed={seed}"
        total, avg = run_linear(configs, fn, label)
        seed_results[seed] = (total, avg)

    # 统计
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
        # === 阶段2: OptRot ===
        print(f"\n--- 阶段2: OptRot 四阶矩最小化 (Cayley SGD) ---")
        t0 = time.time()
        fn = _make_calib_optrot(n_steps=30, lr=0.01)
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


if __name__ == "__main__":
    main()
