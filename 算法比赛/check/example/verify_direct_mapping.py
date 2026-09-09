#!/usr/bin/env python3
"""verify_direct_mapping.py — 验证 NVFP4→HiF4 直接映射

核心发现: HiF4 可精确表示 NVFP4 的全部 8 个 E2M1 值 (当 sf=NVFP4 scale).
当前管线 Hadamard 破坏了离散结构. 直接映射可零权重误差.

对比:
  V0 baseline: NVFP4→FP32→Hadamard→generic quantize→HiF4 (当前)
  V1 identity: NVFP4→FP32→Identity→generic quantize→HiF4 (无旋转, 仍用通用量化)
  V2 direct:   NVFP4→直接从 carrier 提取 scale/E2M1→精确 HiF4 映射

A@W 合规: 仅用 NVFP4 carrier 结构 (W 数据格式), 不计算 X@W
"""
from __future__ import annotations
import os, sys, time, math
import torch

SOLUTION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "solution")
sys.path.insert(0, os.path.abspath(SOLUTION_DIR))
EXAMPLE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(EXAMPLE_DIR))

from solution import (
    _dequant_nvfp4, _apply_hadamard, _hif4_dequant, _quantize_hif4,
    _adaptive_n_candidates, _random_hadamard, HAD_SIZE, BLK_SIZE,
    _E6M2_TABLE, hif4_calibration_and_quantize_weight as _baseline_calib,
)
import simulate_scoring as ss


def _e6m2_nearest(x):
    idx = torch.searchsorted(_E6M2_TABLE, x.double())
    idx_lo = (idx - 1).clamp(0, len(_E6M2_TABLE) - 1)
    idx_hi = idx.clamp(0, len(_E6M2_TABLE) - 1)
    val_lo = _E6M2_TABLE[idx_lo]
    val_hi = _E6M2_TABLE[idx_hi]
    choose_hi = (x.double() - val_hi).abs() < (x.double() - val_lo).abs()
    return torch.where(choose_hi, val_hi, val_lo).to(torch.float32)


def _extract_nvfp4_scales(weight_quant, weight_scale, blk_size=16):
    """从 NVFP4 carrier 提取每个 16-subblock 的 scale."""
    # weight_scale shape: (..., K//16)
    return weight_scale


def _direct_nvfp4_to_hif4(W_fp, nvfp4_scales):
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

    W_reshaped = W_fp.reshape(M, nB, BLK_SIZE)
    scales_reshaped = nvfp4_scales.reshape(M if nvfp4_scales.dim() > 1 else 1, -1)

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
            block_vals = W_fp[:, idx:idx+NVFP4_BLK]
            smax = block_vals.abs().amax(dim=-1)  # (M,)
            nvfp4_scale = smax / 6.0  # E2M1 max = 6
            sub_scales.append(nvfp4_scale)

        sub_scales_t = torch.stack(sub_scales, dim=-1)  # (M, 4)
        median_scale = sub_scales_t.median(dim=-1).values  # (M,)
        sf = _e6m2_nearest(median_scale)  # (M,) E6M2 quantized

        for sb in range(4):
            idx = s + sb * NVFP4_BLK
            block_vals = W_fp[:, idx:idx+NVFP4_BLK]  # (M, 16)
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

            # 写入对应 8×2×4 位置
            # subblock sb 对应 8-group indices: 2*sb, 2*sb+1
            # 每个 8-group 对应 8 个连续元素
            for g in range(2):
                gi = 2 * sb + g
                elem_start = g * 8
                vals = best_mant_int[:, elem_start:elem_start+8]  # (M, 8)
                # 拆成 2×4
                for half in range(2):
                    h_start = half * 4
                    v4 = vals[:, h_start:h_start+4]  # (M, 4)
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


def calib_direct(weight_quant, weight_scale, calib_list):
    """直接映射: 用 NVFP4 结构计算 HiF4, 不用 Hadamard."""
    W_fp = _dequant_nvfp4(weight_quant, weight_scale)
    nvfp4_scales = weight_scale
    weight_params = _direct_nvfp4_to_hif4(W_fp, nvfp4_scales)

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


def calib_identity_generic(weight_quant, weight_scale, calib_list):
    """无旋转 + 通用量化: 用 Identity 替代 Hadamard, 仍用通用量化."""
    import solution
    orig_fn = solution._random_hadamard
    def _identity(n, seed=42):
        return torch.eye(n, dtype=torch.float64)
    solution._random_hadamard = _identity
    try:
        result = _baseline_calib(weight_quant, weight_scale, calib_list)
    finally:
        solution._random_hadamard = orig_fn
    return result


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
    i_total, i_avg = run_linear(configs, calib_identity_generic, "identity")

    print(f"\n--- V2: Direct NVFP4→HiF4 (精确映射, 无Hadamard) ---")
    t0 = time.time()
    d_total, d_avg = run_linear(configs, calib_direct, "direct")
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
        # Direct
        p_direct = _direct_nvfp4_to_hif4(W_fp, group['weight'][1])
        mse_direct = ((_hif4_dequant(p_direct, W_fp.shape) - W_fp) ** 2).mean().item()
        print(f"  Direct: {mse_direct:.6e}")


if __name__ == "__main__":
    main()
