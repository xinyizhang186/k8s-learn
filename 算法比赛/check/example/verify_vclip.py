#!/usr/bin/env python3
"""verify_vclip.py — V per-token clip 策略验证

核心思路: V 的 outlier 集中在个别 token, 直接 clip 到百分位降低 block max
- p99/p95/p90 clip 后, scale_factor 降低 → 量化步长更细 → V 重建 MSE 降
- clip 引入的误差 = 被截断值, 但 P@V 中该 token 权重低时影响小
- 对比: 不clip / p99 / p95 / p90 / per-channel clip

也测试 Q/K 的 per-token clip (Q@K^T 误差可能被 softmax 吸收)
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
    _random_hadamard, HAD_SIZE, hif4_calibration_attention,
    standard_hif4_quantize, _dequantize_hif4, _adaptive_n_candidates,
)
import simulate_scoring as ss


def _clip_percentile(x, percentile=99):
    """Clip tensor to percentile of absolute values."""
    if percentile >= 100:
        return x
    abs_x = x.abs()
    thresh = torch.quantile(abs_x.flatten(), percentile / 100.0)
    thresh = max(thresh.item(), 1e-8)
    return x.clamp(-thresh, thresh)


def _clip_per_channel(x, percentile=99):
    """Clip per-channel (last dim) to percentile."""
    if percentile >= 100:
        return x
    abs_x = x.abs()
    thresh = torch.quantile(abs_x, percentile / 100.0, dim=0, keepdim=True)
    thresh = thresh.clamp(min=1e-8)
    return torch.where(x.abs() > thresh, torch.sign(x) * thresh, x)


def _make_calib_vclip(percentile, per_channel=False):
    """V per-token clip: 在动态量化时 clip V 到百分位."""
    def _calib(calib_qkv_list, qh, kvh, hd):
        return hif4_calibration_attention(calib_qkv_list, qh, kvh, hd)
    return _calib


def run_attn_with_vclip(configs, percentile, per_channel=False, label=""):
    """Run attention scoring with V clip applied at dynamic quantization."""
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']

        calib = hif4_calibration_attention(group['calib'], qh, kvh, hd)
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
                    V_clipped = _clip_per_channel(V_ref, percentile)
                else:
                    V_clipped = _clip_percentile(V_ref, percentile)

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
    b_total, b_avg = run_attn_with_vclip(configs, 100, label="baseline")

    print(f"\n--- V 全局 clip ---")
    for p in [99.9, 99, 98, 95, 90]:
        run_attn_with_vclip(configs, p, per_channel=False, label=f"clip_p{p}")

    print(f"\n--- V per-channel clip ---")
    for p in [99, 95, 90]:
        run_attn_with_vclip(configs, p, per_channel=True, label=f"chan_p{p}")

    print(f"\n--- Q/K clip (Q@K^T 误差被 softmax 吸收?) ---")
    # Q/K 也 clip
    scores = []
    for i, cfg in enumerate(configs):
        group = ss.gen_attention_group(**cfg)
        qh, kvh, hd = cfg['q_heads'], cfg['kv_heads'], cfg['head_dim']
        calib = hif4_calibration_attention(group['calib'], qh, kvh, hd)
        H_q = calib['q_state'].get('hadamard')
        v_state = calib['v_state']
        test_scores = []
        for sample in group['test']:
            Q_ref = _dequant_nvfp4(*sample['q'])
            K_ref = _dequant_nvfp4(*sample['k'])
            V_ref = _dequant_nvfp4(*sample['v'])
            Q_p = _apply_hadamard(Q_ref, H_q) if H_q is not None else Q_ref
            K_p = _apply_hadamard(K_ref, H_q) if H_q is not None else K_ref
            Q_p_c = _clip_percentile(Q_p, 99)
            K_p_c = _clip_percentile(K_p, 99)
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
                if rho_mean is not None and int(rho_mean.shape[-1]) == kvh*hd: imp = rho_mean.to(torch.float32)
            V_params = _quantize_hif4(V_ref, n_candidates=_adaptive_n_candidates(V_ref.shape), importance=imp)
            V_hat = _hif4_dequant(V_params, V_ref.shape)
            ref_out = ss.gqa_attention(Q_p, K_p, V_ref, qh, kvh, hd)
            std_out = ss.gqa_attention(
                _dequantize_hif4(standard_hif4_quantize(Q_p), Q_p.shape),
                _dequantize_hif4(standard_hif4_quantize(K_p), K_p.shape),
                _dequantize_hif4(standard_hif4_quantize(V_ref), V_ref.shape), qh, kvh, hd)
            player_out = ss.gqa_attention(Q_hat, K_hat, V_hat, qh, kvh, hd)
            mse_std = ((ref_out - std_out)**2).mean().item()
            mse_player = ((ref_out - player_out)**2).mean().item()
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
        calib = hif4_calibration_attention(group['calib'], qh, kvh, hd)
        H_q = calib['q_state'].get('hadamard')
        v_state = calib['v_state']
        test_scores = []
        for sample in group['test']:
            Q_ref = _dequant_nvfp4(*sample['q'])
            K_ref = _dequant_nvfp4(*sample['k'])
            V_ref = _dequant_nvfp4(*sample['v'])
            Q_p = _apply_hadamard(_clip_percentile(Q_ref, 99), H_q) if H_q is not None else _clip_percentile(Q_ref, 99)
            K_p = _apply_hadamard(_clip_percentile(K_ref, 99), H_q) if H_q is not None else _clip_percentile(K_ref, 99)
            V_c = _clip_percentile(V_ref, 99)
            Q_params = _quantize_hif4(Q_p, n_candidates=_adaptive_n_candidates(Q_p.shape))
            K_params = _quantize_hif4(K_p, n_candidates=_adaptive_n_candidates(K_p.shape))
            V_params = _quantize_hif4(V_c, n_candidates=_adaptive_n_candidates(V_c.shape),
                                       importance=v_state.get('rho').to(torch.float32).transpose(0,1).repeat_interleave(hd,dim=1) if v_state.get('rho') is not None and V_c.shape[0]==v_state.get('calib_seq') else None)
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
            mse_std = ((ref_out - std_out)**2).mean().item()
            mse_player = ((ref_out - player_out)**2).mean().item()
            test_scores.append((mse_std - mse_player) / max(mse_std, 1e-30))
        avg = sum(test_scores) / len(test_scores)
        scores.append(avg)
    total = sum(scores)
    avg = total / len(scores)
    print(f"  [all_clip_p99] 总分: {total:+.4f}  平均: {avg:+.4f}")


if __name__ == "__main__":
    main()
