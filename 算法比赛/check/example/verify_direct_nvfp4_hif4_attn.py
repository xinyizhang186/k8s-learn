#!/usr/bin/env python3
"""verify_direct_nvfp4_hif4_attn.py — Attention V 直接 NVFP4→HiF4 映射

核心发现:
1. NVFP4 E2M1 全部 8 值可被 HiF4 精确映射 (sf=sub_scale 时零误差)
2. 但 64-block 内 4 个 sub-scale 差异大 (max/min up to 10×)
3. 当前通用量化: NVFP4→FP32→通用量化 (忽略离散结构, 有量化损失)

直接映射思路:
- 从 NVFP4 carrier 提取 E2M1 值 + sub-scale
- 选 HiF4 sf = 最优 E6M2 值 (搜索使 4 个 sub-scale 的失配最小)
- 对每个 subblock: 根据比值 sub_scale/sf 选 lv2/lv3, 直接映射 E2M1→mant
- 量化误差仅来自 sub-scale 失配 (非 2 幂比值部分)

对比:
- V0 baseline: 当前通用量化 (NVFP4→FP32→通用量化)
- V1 direct: 直接从 carrier 结构映射
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
    _random_hadamard, HAD_SIZE, BLK_SIZE, _E6M2_TABLE,
    standard_hif4_quantize, _dequantize_hif4, _adaptive_n_candidates,
    hif4_calibration_attention,
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


def direct_nvfp4_to_hif4(v_quant, v_scale):
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

    # 展平 scale: (S, C//16)
    if v_scale.dim() == 1:
        v_scale = v_scale.unsqueeze(0).expand(S, -1)

    # 每个 64-block 的 4 个 sub_scale
    n_sub = C // NVFP4_BLK
    sub_scales = v_scale  # (S, n_sub)
    # 每 4 个 sub_scale 对应 1 个 64-block
    block_scales = sub_scales.reshape(S, nB, 4)  # (S, nB, 4)

    # 搜索最优 sf: 对每个 (S, nB), 从 4 个 sub_scale 中选一个作为 sf 候选
    # + E6M2 量化, 评估失配
    best_sf = torch.zeros(S, nB)
    best_lv2 = torch.ones(S, nB, 8, 1, 1)
    best_lv3 = torch.ones(S, nB, 8, 2, 1)
    best_sign = torch.zeros(S, nB, 8, 2, 4)
    best_mant = torch.zeros(S, nB, 8, 2, 4)

    W_8224 = v_quant.reshape(S, nB, 8, 2, 4)  # E2M1 值 (直接用 carrier!)

    for b in range(nB):
        scales_b = block_scales[:, b, :]  # (S, 4)
        # 候选 sf: 4 个 sub_scale 的 E6M2 量化
        cands = []
        for sb in range(4):
            cands.append(_e6m2_nearest(scales_b[:, sb]))  # (S,)
        # 也加 max/7 作为候选
        max_val = W_8224[:, b].abs().amax(dim=(-3, -2, -1)) * scales_b.max(dim=-1).values
        cands.append(_e6m2_nearest(max_val / 7.0))
        cands = torch.stack(cands, dim=-1)  # (S, 5)

        best_mse = torch.full((S,), float('inf'))
        for ci in range(cands.shape[-1]):
            sf_ci = cands[:, ci]  # (S,)
            # 对每个 subblock, 搜索最佳 lv2/lv3
            lv2_b = torch.ones(S, 8, 1, 1)
            lv3_b = torch.ones(S, 8, 2, 1)
            mant_b = torch.zeros(S, 8, 2, 4)
            sign_b = torch.zeros(S, 8, 2, 4)
            total_mse = torch.zeros(S)

            for sb in range(4):
                # subblock sb 对应 8-group indices 2*sb, 2*sb+1
                for g_offset in range(2):
                    gi = 2 * sb + g_offset
                    sub_scale = scales_b[:, sb]  # (S,)
                    ratio = sub_scale / sf_ci.clamp(min=1e-30)  # (S,)

                    # 搜索 4 种 (lv2, lv3)
                    best_sub_mse = torch.full((S,), float('inf'))
                    best_sub_lv2 = torch.ones(S)
                    best_sub_lv3 = torch.ones(S)
                    best_sub_mant = torch.zeros(S, 2, 4)

                    for lv2 in [1, 2]:
                        for lv3 in [1, 2]:
                            eff = sf_ci * lv2 * lv3  # (S,)
                            # mant = E2M1 × sub_scale / eff = E2M1 × ratio / (lv2*lv3)
                            # 但 E2M1 = v_quant (carrier 值)
                            # dequant_val = E2M1 × sub_scale
                            # HiF4_val = mant × eff = mant × sf × lv2 × lv3
                            # 要使 HiF4_val ≈ dequant_val: mant = E2M1 × sub_scale / eff
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


def run_attn(configs, v_quant_fn, label):
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']
        calib = hif4_calibration_attention(group['calib'], qh, kvh, hd)
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

            # V: 用指定函数量化
            V_params = v_quant_fn(V_q, V_s, V_fp, v_state, kvh, hd)
            V_hat = _hif4_dequant(V_params, V_fp.shape)

            ref_out = ss.gqa_attention(Q_p, K_p, V_fp, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(Q_p), Q_p.shape),
                _dequantize_hif4(standard_hif4_quantize(K_p), K_p.shape),
                _dequantize_hif4(standard_hif4_quantize(V_fp), V_fp.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)

            mse_std = ((ref_out - std_out)**2).mean().item()
            mse_player = ((ref_out - player_out)**2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))

        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [{label}] 总分: {total:+.4f}  平均: {avg:+.4f}")
    return total, avg


def main():
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
            if rho_mean is not None and int(rho_mean.shape[-1]) == kvh*hd: imp = rho_mean.to(torch.float32)
        return _quantize_hif4(V_fp, n_candidates=_adaptive_n_candidates(V_fp.shape), importance=imp)

    def v_direct(V_q, V_s, V_fp, v_state, kvh, hd):
        return direct_nvfp4_to_hif4(V_q, V_s)

    def v_direct_imp(V_q, V_s, V_fp, v_state, kvh, hd):
        """直接映射 + importance (用于候选选择)"""
        # 简化: 直接映射不用 importance
        return direct_nvfp4_to_hif4(V_q, V_s)

    print(f"\n--- V0 Baseline (通用量化) ---")
    b_total, b_avg = run_attn(configs, v_baseline, "baseline")

    print(f"\n--- V1 Direct (NVFP4→HiF4 直接映射) ---")
    t0 = time.time()
    d_total, d_avg = run_attn(configs, v_direct, "direct")
    t_d = time.time() - t0

    # V 重建 MSE 对比
    print(f"\n--- V 重建 MSE 对比 ---")
    for i, cfg in enumerate(configs[:3]):
        group = ss.gen_attention_group(**cfg)
        V_q, V_s = group['test'][0]['v']
        V_fp = _dequant_nvfp4(V_q, V_s)
        p_base = v_baseline(V_q, V_s, V_fp, hif4_calibration_attention(group['calib'], cfg['q_heads'], cfg['kv_heads'], cfg['head_dim'])['v_state'], cfg['kv_heads'], cfg['head_dim'])
        p_direct = direct_nvfp4_to_hif4(V_q, V_s)
        mse_base = ((_hif4_dequant(p_base, V_fp.shape) - V_fp)**2).mean().item()
        mse_direct = ((_hif4_dequant(p_direct, V_fp.shape) - V_fp)**2).mean().item()
        print(f'  cfg{i}: baseline={mse_base:.4e}  direct={mse_direct:.4e}  ratio={mse_direct/max(mse_base,1e-30):.3f}')

    print(f"\n{'=' * 70}")
    print(f"  Baseline:   {b_avg:+.4f}")
    print(f"  Direct:     {d_avg:+.4f}  Δ={d_avg - b_avg:+.4f} ({(d_avg - b_avg)/max(abs(b_avg),1e-9)*100:+.2f}%)  ({t_d:.1f}s)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
