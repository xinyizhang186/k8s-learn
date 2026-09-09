#!/usr/bin/env python3
"""
verify_gptq.py — 验证 GPTQ 二阶 Hessian 舍入对 HiF4 Linear 场景的增益

对比:
  1. baseline: 当前 solution.py 的 Linear 评分
  2. gptq:     在 _quantize_hif4 确定 scale_factor/lv2/lv3 后,
               用 H = X_rot^T X_rot (block-diagonal 64x64) 做 GPTQ
               mantissa 二阶 OBS 舍入精化.

理论 (idea.md 8.3):
  - 当前对角近似: proxy = sum_j lambda_j * E_W[:,j]^2  (lambda_j = diag(H))
  - GPTQ 精确:    proxy = tr(E_W H E_W^T), 用 H^{-1} 做 OBS 补偿
  - GPTQ 解不劣于对角解 (对角是 GPTQ 在 H 对角时的退化)

A@W 合规: H = X^T X 是单边输入 Gram, 不计算 X@W.
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

from solution import (  # noqa: E402
    _dequant_nvfp4,
    _apply_hadamard,
    _hif4_dequant,
    hif4_calibration_and_quantize_weight as _baseline_calib,
)
import simulate_scoring as ss  # noqa: E402


BLK = 64


def _reconstruct_rotated_space(weight_quant, weight_scale, calib_list, state):
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


def _gptq_refine(W_rot, params, H_rot, damping=1e-6):
    """GPTQ mantissa 二阶舍入精化.

    保持 scale_factor / scale_lv2 / scale_lv3 不变 (来自 _quantize_hif4),
    仅用 H_rot 的 block-diagonal 64x64 子块对 mantissa 做 OBS 补偿舍入.
    damping 控制 H+λI 的 λ: 大 → 接近 RTN (更稳健), 小 → 激进补偿 (过拟合风险).
    """
    M, K = W_rot.shape
    n_blocks = K // BLK

    sf = params["scale_factor"]
    lv2 = params["scale_lv2"]
    lv3 = params["scale_lv3"]

    d = (sf * lv2 * lv3).expand(M, n_blocks, 8, 2, 4).contiguous()
    d_flat = d.reshape(M, K)

    q_deq = torch.zeros_like(W_rot)
    W_work = W_rot.clone()

    for b in range(n_blocks):
        s = b * BLK
        e = s + BLK
        H_b = H_rot[s:e, s:e].clone()
        H_b = H_b + damping * torch.eye(BLK, dtype=H_b.dtype, device=H_b.device)

        try:
            L = torch.linalg.cholesky(H_b)
            H_b_inv = torch.cholesky_inverse(L)
        except Exception:
            q_deq[:, s:e] = _hif4_dequant(params, W_rot.shape)[:, s:e]
            continue

        W_b = W_work[:, s:e]
        d_b = d_flat[:, s:e]

        for j in range(BLK):
            mant_int = (W_b[:, j] / d_b[:, j] * 4.0).round().clamp(-7, 7)
            q_j = mant_int / 4.0 * d_b[:, j]
            q_deq[:, s + j] = q_j
            err = W_b[:, j] - q_j
            if j < BLK - 1:
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


def calib_gptq(weight_quant, weight_scale, calib_list, damping=1e-6):
    """GPTQ 增强版校准: 在 baseline 基础上精化 mantissa."""
    result = _baseline_calib(weight_quant, weight_scale, calib_list)
    params = result["weight_params"]
    state = result["activation_state"]

    if not calib_list:
        return result

    W_rot, H_rot = _reconstruct_rotated_space(weight_quant, weight_scale, calib_list, state)
    refined = _gptq_refine(W_rot, params, H_rot, damping=damping)
    return {"weight_params": refined, "activation_state": state}


def run_linear(configs, calib_fn, label):
    """运行 Linear 场景, 返回 (总分, 平均分, 详情列表)."""
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
    return total, avg, scores


def main():
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

    # 阻尼扫描: 大 λ → 接近 RTN, 小 λ → 激进补偿
    dampings = [1e-6, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0]

    print(f"\n--- Baseline (当前 solution.py, 无 GPTQ) ---")
    base_total, base_avg, _ = run_linear(configs, _baseline_calib, "base")

    print(f"\n--- GPTQ 阻尼扫描 ---")
    results = {}
    for lam in dampings:
        fn = lambda wq, ws, cl, _l=lam: calib_gptq(wq, ws, cl, damping=_l)
        label = f"λ={lam:.0e}"
        total, avg, _ = run_linear(configs, fn, label)
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

    # 找最优
    best_lam = max(results, key=lambda l: results[l][1])
    best_avg = results[best_lam][1]
    if best_avg > base_avg:
        print(f"\n  ✓ 最优阻尼 λ={best_lam:.0e}, 平均分 {best_avg:+.4f} vs baseline {base_avg:+.4f} (Δ={best_avg-base_avg:+.4f})")
    else:
        print(f"\n  ✗ 所有阻尼下 GPTQ 均不优于 baseline (最优 λ={best_lam:.0e}, {results[best_lam][1]:+.4f} vs {base_avg:+.4f})")


if __name__ == "__main__":
    main()
