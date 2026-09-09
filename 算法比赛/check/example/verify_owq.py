#!/usr/bin/env python3
"""
verify_owq.py — 验证 OWQ 弱列识别 / 候选预算对 HiF4 Linear 的增益

测试全局 n_candidates 扫描: 5/7/9(当前自适应)/13/17
(候选集是超集关系, 更多候选不劣, 仅增时间)

如果更高候选帮忙 → per-block OWQ 值得实现 (重要块给13, 其余给5)
如果更高候选不帮忙 → 当前候选已饱和, OWQ 不可行
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


def _make_calib_with_ncand(ncand):
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
        fn = _make_calib_with_ncand(nc)
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


if __name__ == "__main__":
    main()
