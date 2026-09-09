#!/usr/bin/env python3
"""
verify_hadamard.py — 验证全K/大块 Hadamard 旋转对 HiF4 Linear 场景的增益

对比 Hadamard 块大小: 64 (当前) / 128 / 256 / 512 / auto (K 的最大 2 幂因子)

理论 (idea.md 8.4):
  - 当前 block-diagonal 64×64: outlier 仅在 64 元素内分散
  - 全K/大块: outlier 跨 K 分散, block max 降至 ||x||·√(2·log K / K)
  - outlier block 的 scale_factor 降 ~√(64/K) → MSE 降 ~(64/K) (σ²∝步长²)

数据无关 (随机 Hadamard), 无校准→测试泛化 gap (对比 GPTQ 的失败).
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

import solution
from solution import hif4_calibration_and_quantize_weight as _baseline_calib
import simulate_scoring as ss


def _largest_pow2_divisor(K, cap=None):
    s = 1
    while s * 2 <= K and K % (s * 2) == 0:
        s *= 2
        if cap is not None and s > cap:
            s //= 2
            break
    return s


def _make_calib_with_had_size(had_size):
    """Return a calib function that patches solution.HAD_SIZE."""
    def _calib(weight_quant, weight_scale, calib_activation_list):
        K = weight_quant.shape[-1]
        if callable(had_size):
            hs = had_size(K)
        else:
            hs = had_size
            if K % hs != 0:
                hs = _largest_pow2_divisor(K, cap=hs)
        orig = solution.HAD_SIZE
        solution.HAD_SIZE = hs
        try:
            result = _baseline_calib(weight_quant, weight_scale, calib_activation_list)
        finally:
            solution.HAD_SIZE = orig
        return result
    return _calib


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
    return total, avg, scores


def main():
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
        (lambda K: _largest_pow2_divisor(K), "auto (largest)"),
    ]

    results = {}
    for had_size, label in had_configs:
        fn = _make_calib_with_had_size(had_size)
        print(f"\n--- Hadamard block = {label} ---")
        t0 = time.time()
        total, avg, _ = run_linear(configs, fn, label)
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


if __name__ == "__main__":
    main()
