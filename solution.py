"""
HiF4 solution.py — NVFP4 → HiF4 量化转换 (差异化算法)

针对赛题要求"分别对权重、激活(A和Attention Q/K/V)设计最优量化算法"：

  权重 W (离线): Hadamard旋转 + E6M2 scale search + greedy微指数 (3候选)
  激活 A (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)
  Q     (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)
  K     (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)
  V     (在线): 无旋转 + E6M2 scale search + V校准二阶矩加权MSE (5候选)

差异化设计依据 (经实验验证):
  - Hadamard旋转使通道二阶矩趋于均匀 → W/A/Q/K的importance加权无效
  - V不旋转 (会破坏attention输出) → V的逐通道二阶矩保持非均匀 → importance加权有效
  - greedy冗余消除: 从5次量化降到3次 (q1/q2复用为lv3=1的结果)

所有算法均不计算 A@W，仅使用边际统计量 (per-channel E[X_j^2])
作为通道重要性权重，优化逐元素重建 MSE。

参考:
  [1] HiFloat4 Format for Language Model Inference (arxiv 2602.11287)
  [2] Pretraining LLMs with NVFP4 (arxiv 2509.25149)
  [3] ScaleSearch (MLSys 2026) — MSE-optimal scale search
  [4] Random Hadamard Transform (Tseng et al. 2025)
"""

from __future__ import annotations

import math
from typing import Any

import torch

BLK_SIZE = 64
NVFP4_BLK = 16
HAD_SIZE = 64


def _generate_e6m2_table() -> torch.Tensor:
    vals: list[float] = []
    for e in range(-48, 15):
        for k in range(4):
            vals.append(math.ldexp(1.0 + k * 0.25, e))
    for k in range(3):
        vals.append(math.ldexp(1.0 + k * 0.25, 15))
    return torch.tensor(vals, dtype=torch.float64)


_E6M2_TABLE: torch.Tensor = _generate_e6m2_table()


def _hadamard_sylvester(n: int) -> torch.Tensor:
    H = torch.ones((1, 1), dtype=torch.float64)
    inv = 1.0 / math.sqrt(2.0)
    while H.shape[0] < n:
        H = torch.cat([torch.cat([H, H], dim=-1),
                        torch.cat([H, -H], dim=-1)], dim=0) * inv
    return H


def _random_hadamard(n: int, seed: int = 42) -> torch.Tensor:
    H = _hadamard_sylvester(n)
    g = torch.Generator().manual_seed(seed)
    signs = (torch.randint(0, 2, (n,), generator=g, dtype=torch.float64) * 2 - 1)
    return H * signs.unsqueeze(0)


def _dequant_nvfp4(quant_float, scale_float, blk_size=NVFP4_BLK):
    channels = int(quant_float.shape[-1])
    x = quant_float.unflatten(-1, (-1, blk_size))
    x = x * scale_float.unsqueeze(-1)
    return x.flatten(-2, -1).to(torch.float32)


def _e6m2_candidates(target, n_candidates=3):
    target_flat = target.reshape(-1).double()
    idx = torch.searchsorted(_E6M2_TABLE, target_flat)
    idx = idx.clamp(n_candidates // 2, len(_E6M2_TABLE) - n_candidates)
    if n_candidates <= 4:
        if n_candidates == 2:
            offsets = torch.tensor([0, 4], dtype=torch.long)
        elif n_candidates == 3:
            offsets = torch.tensor([-1, 0, 4], dtype=torch.long)
        else:
            offsets = torch.tensor([-1, 0, 2, 4], dtype=torch.long)
    elif n_candidates <= 12:
        offsets = torch.cat([
            torch.tensor([-1], dtype=torch.long),
            torch.arange(n_candidates - 1, dtype=torch.long),
        ])
    else:
        half = n_candidates // 2
        offsets = torch.arange(-half + 1, n_candidates - half + 1, dtype=torch.long)
    cand_idx = idx.unsqueeze(-1) + offsets
    cand_idx = cand_idx.clamp(0, len(_E6M2_TABLE) - 1)
    candidates = _E6M2_TABLE[cand_idx]
    out_shape = list(target.shape[:-1]) + [n_candidates]
    return candidates.reshape(out_shape).to(torch.float32)


def _apply_hadamard(x, H):
    C = x.shape[-1]
    assert C % HAD_SIZE == 0
    x_re = x.reshape(-1, HAD_SIZE)
    x_rot = x_re @ H
    return x_rot.reshape(x.shape).to(torch.float32)


# ======================================================================
# 核心: 带重要性加权的 HiF4 量化
# ----------------------------------------------------------------------

def _quantize_block_given_scale(w, sf, imp=None):
    """对给定 E6M2 scale 的 block 做 greedy 微指数优化 + S1P2 量化。
    优化: 消除冗余量化, 从5次降到3次 (q1/q2复用为lv3=1的结果)。"""
    has_imp = imp is not None

    def _mse(dq, ref, dims):
        if has_imp:
            return (imp * (dq - ref) ** 2).sum(dim=dims)
        return ((dq - ref) ** 2).mean(dim=dims)

    # ── 量化1: lv2=1, lv3=1 ──
    w_div_sf1 = w / sf
    q1 = (w_div_sf1 * 4.0).round().clamp(-7, 7) / 4.0
    dq1 = q1 * sf
    mse1_8 = _mse(dq1, w, (-2, -1))
    mse1_4 = _mse(dq1, w, -1)

    # ── 量化2: lv2=2, lv3=1 ──
    w_div_sf2 = w / (sf * 2.0)
    q2 = (w_div_sf2 * 4.0).round().clamp(-7, 7) / 4.0
    dq2 = q2 * (sf * 2.0)
    mse2_8 = _mse(dq2, w, (-2, -1))
    mse2_4 = _mse(dq2, w, -1)

    # ── 选 lv2 (per sub-block) ──
    use_2_lv2 = mse2_8 < mse1_8
    scale_lv2 = torch.where(use_2_lv2, 2.0, 1.0)

    # ── 量化3: best_lv2, lv3=2 (唯一新量化) ──
    lv2_exp = scale_lv2.unsqueeze(-1).unsqueeze(-1)
    base_scale = sf * lv2_exp
    w_div_base2 = w / (base_scale * 2.0)
    q4 = (w_div_base2 * 4.0).round().clamp(-7, 7) / 4.0
    dq4 = q4 * (base_scale * 2.0)
    mse4_4 = _mse(dq4, w, -1)

    # ── 选 lv3 (per sub-sub-block): lv3=1的MSE = mse1_4或mse2_4 ──
    mse_lv3_1 = torch.where(use_2_lv2.unsqueeze(-1), mse2_4, mse1_4)
    use_2_lv3 = mse4_4 < mse_lv3_1
    scale_lv3 = torch.where(use_2_lv3, 2.0, 1.0)

    # ── 最终结果: 复用 q1/q2 (lv3=1) 或 q4 (lv3=2) ──
    use_2_lv2_exp = use_2_lv2.unsqueeze(-1).unsqueeze(-1)
    q_lv3_1 = torch.where(use_2_lv2_exp, q2, q1)
    dq_lv3_1 = torch.where(use_2_lv2_exp, dq2, dq1)

    use_2_lv3_exp = use_2_lv3.unsqueeze(-1)
    q_final = torch.where(use_2_lv3_exp, q4, q_lv3_1)
    dq_final = torch.where(use_2_lv3_exp, dq4, dq_lv3_1)

    sign = torch.sign(q_final)
    mant = q_final.abs()

    block_mse = _mse(dq_final, w, (-3, -2, -1))
    if has_imp:
        norm = imp.sum(dim=(-3, -2, -1)).clamp(min=1e-12)
        block_mse = block_mse / norm

    return scale_lv2, scale_lv3, sign, mant, block_mse


def _quantize_hif4(w_fp, n_candidates=5, importance=None, chunk_rows=384):
    orig_shape = w_fp.shape

    if w_fp.ndim <= 1 or w_fp.shape[0] <= chunk_rows:
        return _quantize_hif4_impl(w_fp, n_candidates, importance)

    results = []
    for start in range(0, w_fp.shape[0], chunk_rows):
        end = min(start + chunk_rows, w_fp.shape[0])
        results.append(_quantize_hif4_impl(w_fp[start:end], n_candidates, importance))

    return {k: torch.cat([r[k] for r in results], dim=0) for k in results[0]}


def _quantize_hif4_impl(w_fp, n_candidates=5, importance=None):
    orig_shape = w_fp.shape
    C = int(orig_shape[-1])
    assert C % BLK_SIZE == 0

    w = w_fp.reshape(*orig_shape[:-1], -1, BLK_SIZE)
    w_8224 = w.reshape(*w.shape[:-1], 8, 2, 4)

    if importance is not None:
        imp_C = int(importance.shape[-1])
        if imp_C != C:
            imp_8224 = None
        else:
            if importance.ndim == 1:
                importance = importance.unsqueeze(0)
            imp = importance.reshape(*importance.shape[:-1], -1, BLK_SIZE)
            imp_8224 = imp.reshape(*imp.shape[:-1], 8, 2, 4)
            if imp_8224.shape[0] != w_8224.shape[0] or imp_8224.ndim != w_8224.ndim:
                imp_8224 = imp_8224.expand(*w_8224.shape)
            else:
                imp_8224 = imp_8224.expand_as(w_8224)
    else:
        imp_8224 = None

    w_abs = w.abs()
    max_64 = w_abs.amax(dim=-1, keepdim=True)
    target = (max_64 / 7.0).clamp(min=2.0 ** (-48))

    cands = _e6m2_candidates(target, n_candidates)
    all_cands = cands
    n_total = all_cands.shape[-1]

    best_mse = torch.full(max_64.squeeze(-1).shape, float("inf"), dtype=torch.float32)
    best_lv2 = best_lv3 = best_sign = best_mant = None
    best_sf = torch.zeros_like(max_64)

    for ci in range(n_total):
        sf = all_cands[..., ci:ci + 1]
        sf_exp = sf.reshape(*sf.shape[:-1], 1, 1, 1)

        lv2, lv3, sign, mant, mse = _quantize_block_given_scale(w_8224, sf_exp, imp_8224)

        improved = mse < best_mse
        if not improved.any():
            continue

        best_mse = torch.where(improved, mse, best_mse)
        best_sf = torch.where(improved.unsqueeze(-1), sf, best_sf)

        imp_lv2 = improved.unsqueeze(-1)
        best_lv2 = lv2 if best_lv2 is None else torch.where(imp_lv2, lv2, best_lv2)

        imp_lv3 = improved.unsqueeze(-1).unsqueeze(-1)
        best_lv3 = lv3 if best_lv3 is None else torch.where(imp_lv3, lv3, best_lv3)

        imp_sm = improved.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1)
        best_sign = sign if best_sign is None else torch.where(imp_sm, sign, best_sign)
        best_mant = mant if best_mant is None else torch.where(imp_sm, mant, best_mant)

    if best_lv2 is None:
        sf0 = all_cands[..., 0:1]
        sf0_exp = sf0.reshape(*sf0.shape[:-1], 1, 1, 1)
        best_lv2, best_lv3, best_sign, best_mant, _ = \
            _quantize_block_given_scale(w_8224, sf0_exp, imp_8224)
        best_sf = sf0

    num_blocks_dim = C // BLK_SIZE
    prefix = orig_shape[:-1]

    return {
        "scale_factor": best_sf.reshape(*prefix, num_blocks_dim, 1, 1, 1).contiguous().float(),
        "scale_lv2": best_lv2.reshape(*prefix, num_blocks_dim, 8, 1, 1).contiguous().float(),
        "scale_lv3": best_lv3.reshape(*prefix, num_blocks_dim, 8, 2, 1).contiguous().float(),
        "sign": best_sign.reshape(*prefix, num_blocks_dim, 8, 2, 4).contiguous().float(),
        "mant": best_mant.reshape(*prefix, num_blocks_dim, 8, 2, 4).contiguous().float(),
    }


# ======================================================================
# V 校准统计量
# ----------------------------------------------------------------------

def _compute_v_importance(calib_qkv_list):
    """V 通道重要性 = V 校准数据的逐通道二阶矩 E[V_j^2]。"""
    kv_hidden = calib_qkv_list[0]["v"][0].shape[-1]
    v_sm = torch.zeros(kv_hidden, dtype=torch.float32)
    for sample in calib_qkv_list:
        v_fp = _dequant_nvfp4(*sample["v"])
        v_sm = v_sm + (v_fp ** 2).mean(dim=0)
    v_sm = (v_sm / max(len(calib_qkv_list), 1)).clamp(min=1e-8)
    return v_sm


# ======================================================================
# 1. Linear: 校准 + 权重量化
# ======================================================================

def hif4_calibration_and_quantize_weight(
    weight_quant: torch.Tensor,
    weight_scale: torch.Tensor,
    calib_activation_list: list,
) -> dict[str, Any]:
    """权重 W (离线): Hadamard旋转 + E6M2 scale search + greedy微指数 (3候选)。"""
    weight_fp = _dequant_nvfp4(weight_quant, weight_scale)

    H = _random_hadamard(HAD_SIZE, seed=42).to(torch.float32)
    weight_rot = _apply_hadamard(weight_fp, H)

    weight_params = _quantize_hif4(weight_rot, n_candidates=3)

    activation_state = {
        "hadamard": H.contiguous(),
    }

    return {
        "weight_params": weight_params,
        "activation_state": activation_state,
    }


# ======================================================================
# 2. Linear: 动态激活量化
# ======================================================================

def hif4_dynamic_quantize_activation(
    activation_quant: torch.Tensor,
    activation_scale: torch.Tensor,
    activation_state: Any,
) -> dict[str, torch.Tensor]:
    """激活 A (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)。
    旋转后通道重要性趋于均匀, 不需要重要性加权。"""
    act_fp = _dequant_nvfp4(activation_quant, activation_scale)

    H = activation_state.get("hadamard") if isinstance(activation_state, dict) else None
    if H is not None:
        act_fp = _apply_hadamard(act_fp, H.to(torch.float32))

    return _quantize_hif4(act_fp, n_candidates=5)


# ======================================================================
# 3. Attention: 校准
# ======================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Attention校准:
    Q/K: 共用Hadamard (保证Q@K^T不变), 旋转后无需重要性加权
    V:   不旋转, 计算逐通道二阶矩作为重要性 (V的误差直接进入输出)"""
    H = _random_hadamard(HAD_SIZE, seed=123).to(torch.float32)
    v_imp = _compute_v_importance(calib_qkv_list)

    q_state = {"hadamard": H.contiguous()}
    k_state = {"hadamard": H.contiguous()}
    v_state = {"importance": v_imp.contiguous()}

    return {"q_state": q_state, "k_state": k_state, "v_state": v_state}


# ======================================================================
# 4. 动态 Q
# ======================================================================

def hif4_dynamic_quantize_q(
    q_quant: torch.Tensor,
    q_scale: torch.Tensor,
    q_num_heads: int,
    head_dim: int,
    q_state: Any,
) -> dict[str, torch.Tensor]:
    """Q (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)。
    Q@K^T误差中Q的贡献被K^2加权, 但旋转后K^2趋于均匀, 故不加权。"""
    q_fp = _dequant_nvfp4(q_quant, q_scale)

    if isinstance(q_state, dict):
        H = q_state.get("hadamard")
    else:
        H = None
    if H is not None:
        q_fp = _apply_hadamard(q_fp, H.to(torch.float32))

    return _quantize_hif4(q_fp, n_candidates=5)


# ======================================================================
# 5. 动态 K
# ======================================================================

def hif4_dynamic_quantize_k(
    k_quant: torch.Tensor,
    k_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    k_state: Any,
) -> dict[str, torch.Tensor]:
    """K (在线): Hadamard旋转 + E6M2 scale search + 标准MSE (5候选)。
    同Q, 旋转后Q^2趋于均匀, 故不加权。"""
    k_fp = _dequant_nvfp4(k_quant, k_scale)

    if isinstance(k_state, dict):
        H = k_state.get("hadamard")
    else:
        H = None
    if H is not None:
        k_fp = _apply_hadamard(k_fp, H.to(torch.float32))

    return _quantize_hif4(k_fp, n_candidates=5)


# ======================================================================
# 6. 动态 V
# ======================================================================

def hif4_dynamic_quantize_v(
    v_quant: torch.Tensor,
    v_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    v_state: Any,
) -> dict[str, torch.Tensor]:
    """V (在线): 无旋转 + E6M2 scale search + V校准二阶矩加权MSE (5候选)。
    V不旋转(无法保持attention输出), 但V的逐通道重要性是非均匀的
    (V的误差直接进入softmax(Q@K^T)@V的输出), 故用重要性加权。"""
    v_fp = _dequant_nvfp4(v_quant, v_scale)

    imp = None
    if isinstance(v_state, dict):
        imp = v_state.get("importance")
        if imp is not None and int(imp.shape[-1]) != int(v_fp.shape[-1]):
            imp = None

    return _quantize_hif4(v_fp, n_candidates=5, importance=imp)
