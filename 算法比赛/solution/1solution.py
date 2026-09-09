"""
NVFP4 -> HiF4 量化转换算法 solution.py

核心技术（基于 idea.md）：
1. Exact 微指数搜索（4组合联合优化，3除数覆盖）
2. E6M2 对称窗口 Scale Search（自适应候选数）
3. 随机 Hadamard 旋转（outlier分散，block对齐）
4. Linear 输出敏感度加权（lambda_j 激活统计 + w_diag 权重统计）
5. SmoothQuant 对角平衡（小矩阵 alpha 扫描，proxy=重建MSE）
6. Attention V 的 P^TP 加权（token级重要性）

绝对禁止约束：
  不计算 A@W（激活@权重的矩阵乘），不利用 A@W 拟合反推 Q(A)。
  所有加权信号均来自单侧统计量（激活方差 lambda_j、权重列范数 w_diag、
  注意力模式 P^TP），不涉及 A@W 的任何形式。
"""

from __future__ import annotations

import math
from typing import Any

import torch

# ================================================================================
# NVFP4 dequantization helper
# ================================================================================

def dequantize_nvfp4(
    quant_float: torch.Tensor,
    scale_float: torch.Tensor,
    blk_size: int = 16,
) -> torch.Tensor:
    """Dequantize NVFP4 carrier to FP32."""
    channels = int(quant_float.shape[-1])
    if channels % blk_size != 0:
        raise ValueError(
            f"last dimension {channels} is not divisible by block size {blk_size}"
        )
    x = quant_float.unflatten(-1, (-1, blk_size))
    x = x * scale_float.unsqueeze(-1)
    return x.flatten(-2, -1).to(torch.float32)


# ================================================================================
# E6M2 helpers
# ================================================================================

_E6M2_TABLE: torch.Tensor | None = None


def _get_e6m2_table() -> torch.Tensor:
    """Build sorted 1-D tensor of all valid E6M2 values in [2^-48, 49152]."""
    global _E6M2_TABLE
    if _E6M2_TABLE is None:
        vals: list[float] = []
        for e in range(-48, 16):
            for m in (4, 5, 6, 7):
                v = m * (2.0 ** (e - 2))
                if 2.0 ** (-48) <= v <= 49152.0:
                    vals.append(v)
        _E6M2_TABLE = torch.tensor(sorted(set(vals)), dtype=torch.float64)
    return _E6M2_TABLE


def quantize_to_e6m2(x: torch.Tensor) -> torch.Tensor:
    """Quantize *positive* values to nearest E6M2 representable value."""
    table = _get_e6m2_table()
    x_flat = x.flatten().to(torch.float64)
    result = torch.zeros_like(x_flat)
    nonzero = x_flat > 0
    if nonzero.any():
        x_nz = x_flat[nonzero].clamp(min=2.0 ** (-48), max=49152.0)
        idx = torch.searchsorted(table, x_nz)
        idx_lo = (idx - 1).clamp(0, len(table) - 1)
        idx_hi = idx.clamp(0, len(table) - 1)
        val_lo = table[idx_lo]
        val_hi = table[idx_hi]
        choose_hi = (x_nz - val_hi).abs() < (x_nz - val_lo).abs()
        result[nonzero] = torch.where(choose_hi, val_hi, val_lo)
    return result.reshape(x.shape).to(torch.float32)


def _get_e6m2_candidates(
    centers: torch.Tensor, num_candidates: int
) -> torch.Tensor:
    """Return *num_candidates* E6M2 values around each center.

    Args:
        centers: (...,) positive values
    Returns:
        (..., num_candidates) candidate E6M2 values (sorted ascending)
    """
    table = _get_e6m2_table()
    n = len(table)
    centers_flat = centers.flatten().to(torch.float64)
    centers_clamped = centers_flat.clamp(
        min=table[0].item(), max=table[-1].item()
    )
    idx = torch.searchsorted(table, centers_clamped)
    half = num_candidates // 2
    start = (idx - half - 1).clamp(0, n - num_candidates)
    offsets = torch.arange(num_candidates, dtype=torch.long)
    candidate_indices = start.unsqueeze(-1) + offsets
    candidates = table[candidate_indices]
    return candidates.reshape(*centers.shape, num_candidates).to(torch.float32)


# ================================================================================
# Hadamard helpers
# ================================================================================

def _hadamard_matrix(n: int) -> torch.Tensor:
    """Sylvester-type Hadamard matrix of size n (n must be power of 2)."""
    H = torch.ones(1, 1, dtype=torch.float32)
    while H.shape[0] < n:
        H = torch.cat(
            [torch.cat([H, H], dim=-1), torch.cat([H, -H], dim=-1)],
            dim=-2,
        )
    return H


def _make_random_hadamard(n: int, seed: int = 42) -> torch.Tensor:
    """Random +-1 diagonal * Hadamard, normalized by 1/sqrt(n)."""
    H = _hadamard_matrix(n)
    gen = torch.Generator()
    gen.manual_seed(seed)
    S = torch.sign(torch.randn(n, generator=gen, dtype=torch.float32))
    S[S == 0] = 1.0
    return (S.unsqueeze(-1) * H) / math.sqrt(n)


def _apply_hadamard_blocks(x: torch.Tensor, H: torch.Tensor) -> torch.Tensor:
    """Apply H per block along the last dim. Block size = H.shape[0]."""
    C = x.shape[-1]
    bs = H.shape[0]
    assert C % bs == 0, f"C={C} not divisible by block_size={bs}"
    n_blocks = C // bs
    x_blocks = x.reshape(*x.shape[:-1], n_blocks, bs)
    x_rot = x_blocks @ H          # broadcasts over leading dims
    return x_rot.reshape(*x.shape)


def _apply_hadamard_heads(
    x: torch.Tensor, H: torch.Tensor, num_heads: int, head_dim: int
) -> torch.Tensor:
    """Apply H per attention head along head_dim."""
    S = x.shape[0]
    x_r = x.reshape(S, num_heads, head_dim)
    x_rot = x_r @ H               # [S, num_heads, head_dim]
    return x_rot.reshape(S, num_heads * head_dim)


def _apply_per_head_hadamard(
    x: torch.Tensor,
    H_per_head: torch.Tensor,
    num_heads: int,
    head_dim: int,
    kv_num_heads: int,
) -> torch.Tensor:
    """Apply per-(KV-head, block) 64x64 Hadamard, aligned with HiF4 blocks.

    H_per_head: (kv_num_heads, n_hd_blocks, 64, 64)
    Each KV head group AND each 64-element block within a head gets its own H.
    Preserves Q@K^T because H is orthogonal and Q/K share the same H per (group, block).
    """
    S = x.shape[0]
    group = num_heads // kv_num_heads
    n_hd_blocks = head_dim // 64

    if num_heads == kv_num_heads:
        x_r = x.reshape(S, kv_num_heads, n_hd_blocks, 64)
        x_rot = torch.einsum('skbd,kbde->skbe', x_r, H_per_head)
    else:
        x_r = x.reshape(S, kv_num_heads, group, n_hd_blocks, 64)
        x_rot = torch.einsum('skgbd,kbde->skgbe', x_r, H_per_head)

    return x_rot.reshape(S, num_heads * head_dim)


# ================================================================================
# HiF4 dequantization (inverse of quantize)
# ================================================================================

def _dequantize_hif4(
    params: dict[str, torch.Tensor],
    original_shape: tuple[int, ...],
) -> torch.Tensor:
    """Reconstruct FP32 tensor from HiF4 params."""
    sign = params["sign"]
    mant = params["mant"]
    scale_lv2 = params["scale_lv2"]
    scale_lv3 = params["scale_lv3"]
    scale_factor = params["scale_factor"]
    dequant = sign * mant * scale_lv2 * scale_lv3 * scale_factor
    return dequant.reshape(original_shape)


# ================================================================================
# Core HiF4 quantization  (exact micro-exponent + E6M2 scale search)
# ================================================================================

def _quantize_hif4_core(
    x: torch.Tensor,
    channel_weight: torch.Tensor | None = None,
    num_candidates: int = 9,
) -> dict[str, torch.Tensor]:
    """Quantize FP32 tensor to HiF4 format.

    Implements:
      - Exact micro-exponent search (3 divisors cover 4 combinations)
      - E6M2 symmetric-window scale search with *num_candidates* candidates
      - Optional per-element *channel_weight* for output-sensitive weighting

    Args:
        x: (..., C) with C % 64 == 0
        channel_weight: (..., C) per-element weight for weighted MSE, or None
        num_candidates: number of E6M2 scale candidates (odd recommended)

    Returns:
        dict with scale_factor / scale_lv2 / scale_lv3 / sign / mant
    """
    original_shape = x.shape
    C = int(original_shape[-1])
    n_blocks = C // 64

    x_flat = x.reshape(-1, C)
    N = x_flat.shape[0]

    w_flat: torch.Tensor | None = None
    if channel_weight is not None:
        w_flat = channel_weight.expand_as(x_flat).reshape(-1, C)

    # (N, n_blocks, 8, 2, 4)
    x_blocks = x_flat.reshape(N, n_blocks, 8, 2, 4)
    w_blocks = (
        w_flat.reshape(N, n_blocks, 8, 2, 4)
        if w_flat is not None
        else None
    )

    vmax = x_blocks.abs().amax(dim=(-3, -2, -1))
    nonzero_mask = vmax > 0

    # Candidate scale factors around Vmax/7
    center = (vmax / 7.0).clamp(min=2.0 ** (-48), max=49152.0)
    candidates = _get_e6m2_candidates(center, num_candidates)  # (N, n_blocks, K)

    sign = torch.sign(x_blocks)
    x_abs = x_blocks.abs()

    # ---- Phase 1: find best candidate index per block -----------------------
    best_err = torch.full((N, n_blocks), float("inf"), dtype=torch.float64)
    best_k = torch.zeros(N, n_blocks, dtype=torch.long)

    for k in range(num_candidates):
        sf = candidates[:, :, k]                               # (N, n_blocks)
        sf_exp = sf.clamp(min=1e-38).reshape(N, n_blocks, 1, 1, 1)

        errs: dict[int, torch.Tensor] = {}
        for d_key, d_mult in ((1, 1.0), (2, 2.0), (4, 4.0)):
            d = sf_exp * d_mult
            mant_scaled = torch.round(x_abs * 4.0 / d).clamp(0, 7)
            x_hat = sign * (mant_scaled * 0.25) * d
            err = (x_blocks - x_hat) ** 2
            if w_blocks is not None:
                err = err * w_blocks
            errs[d_key] = err.sum(dim=-1)                      # (N, n_blocks, 8, 2)

        e1, e2, e4 = errs[1], errs[2], errs[4]
        err_lv2_1 = torch.minimum(e1, e2).sum(dim=-1)         # (N, n_blocks, 8)
        err_lv2_2 = torch.minimum(e2, e4).sum(dim=-1)
        total_err = torch.minimum(err_lv2_1, err_lv2_2).sum(dim=-1)
        total_err = total_err.to(torch.float64)
        total_err = torch.where(
            nonzero_mask, total_err, torch.zeros_like(total_err)
        )

        better = total_err < best_err
        best_err = torch.where(better, total_err, best_err)
        best_k = torch.where(better, torch.full_like(best_k, k), best_k)

    # ---- Phase 2: reconstruct params for best candidate --------------------
    best_sf = torch.gather(
        candidates, dim=-1, index=best_k.unsqueeze(-1)
    ).squeeze(-1)                                              # (N, n_blocks)
    sf_exp = best_sf.clamp(min=1e-38).reshape(N, n_blocks, 1, 1, 1)

    mants: dict[int, torch.Tensor] = {}
    errs2: dict[int, torch.Tensor] = {}
    for d_key, d_mult in ((1, 1.0), (2, 2.0), (4, 4.0)):
        d = sf_exp * d_mult
        mant_scaled = torch.round(x_abs * 4.0 / d).clamp(0, 7)
        mants[d_key] = mant_scaled * 0.25
        x_hat = sign * mants[d_key] * d
        err = (x_blocks - x_hat) ** 2
        if w_blocks is not None:
            err = err * w_blocks
        errs2[d_key] = err.sum(dim=-1)                        # (N, n_blocks, 8, 2)

    e1, e2, e4 = errs2[1], errs2[2], errs2[4]
    err_lv2_1 = torch.minimum(e1, e2).sum(dim=-1)             # (N, n_blocks, 8)
    err_lv2_2 = torch.minimum(e2, e4).sum(dim=-1)
    lv2_is_2 = err_lv2_2 < err_lv2_1                          # (N, n_blocks, 8)
    lv2_vals = torch.where(lv2_is_2, 2.0, 1.0)               # (N, n_blocks, 8)

    use_d2_lv1 = e2 < e1                                     # (N, n_blocks, 8, 2)
    use_d4_lv2 = e4 < e2
    lv2_exp = lv2_is_2.unsqueeze(-1)                         # (N, n_blocks, 8, 1)

    d_chosen = torch.where(
        lv2_exp.expand_as(use_d2_lv1),
        torch.where(use_d4_lv2, 4, 2),
        torch.where(use_d2_lv1, 2, 1),
    )                                                         # (N, n_blocks, 8, 2)

    lv3_vals = torch.where(
        d_chosen == 1, 1.0,
        torch.where(
            d_chosen == 4, 2.0,
            torch.where(lv2_exp.expand_as(d_chosen), 1.0, 2.0),
        ),
    )                                                         # (N, n_blocks, 8, 2)

    # Gather mant for chosen divisor
    mant_final = torch.zeros_like(mants[1])
    for d_key in (1, 2, 4):
        mask = (d_chosen == d_key).unsqueeze(-1).expand_as(mants[d_key])
        mant_final = torch.where(mask, mants[d_key], mant_final)

    # Zero-block fix-up
    best_sf = torch.where(
        nonzero_mask, best_sf, torch.full_like(best_sf, 2.0 ** (-48))
    )

    # ---- Format output to expected HiF4 param shapes ------------------------
    prefix = tuple(original_shape[:-1]) + (n_blocks,)
    return {
        "scale_factor": best_sf.reshape(*prefix, 1, 1, 1).to(torch.float32),
        "scale_lv2":    lv2_vals.reshape(*prefix, 8, 1, 1).to(torch.float32),
        "scale_lv3":    lv3_vals.reshape(*prefix, 8, 2, 1).to(torch.float32),
        "sign":         sign.reshape(*prefix, 8, 2, 4).to(torch.float32),
        "mant":         mant_final.reshape(*prefix, 8, 2, 4).to(torch.float32),
    }


# ================================================================================
# Standard HiF4 baseline (Algorithm 1: direct cast)  -- used by scoring script
# ================================================================================

def standard_hif4_quantize(x: torch.Tensor) -> dict[str, torch.Tensor]:
    """Standard HiF4 quantization per Algorithm 1 of the HiFloat4 paper."""
    original_shape = x.shape
    C = int(original_shape[-1])
    n_blocks = C // 64

    x_flat = x.reshape(-1, C)
    N = x_flat.shape[0]
    x_blocks = x_flat.reshape(N, n_blocks, 8, 2, 4)

    vmax = x_blocks.abs().amax(dim=(-3, -2, -1))
    sf = quantize_to_e6m2(vmax / 7.0)                          # (N, n_blocks)
    sf_safe = sf.clamp(min=2.0 ** (-48))

    sf_b = sf_safe.unsqueeze(-1)                                # (N, n_blocks, 1)
    v8 = x_blocks.abs().amax(dim=(-2, -1))                     # (N, n_blocks, 8)
    lv2 = torch.where(v8 / sf_b >= 4.0, 2.0, 1.0)             # (N, n_blocks, 8)

    sf_bb = sf_safe.unsqueeze(-1).unsqueeze(-1)               # (N, n_blocks, 1, 1)
    lv2_b = lv2.unsqueeze(-1)                                  # (N, n_blocks, 8, 1)
    v4 = x_blocks.abs().amax(dim=-1)                           # (N, n_blocks, 8, 2)
    lv3 = torch.where(
        v4 / (sf_bb * lv2_b).clamp(min=1e-38) >= 2.0, 2.0, 1.0
    )                                                         # (N, n_blocks, 8, 2)

    sign = torch.sign(x_blocks)
    d = (sf_safe.reshape(N, n_blocks, 1, 1, 1)
         * lv2.reshape(N, n_blocks, 8, 1, 1)
         * lv3.reshape(N, n_blocks, 8, 2, 1)
    ).clamp(min=1e-38)
    mant_scaled = torch.round(x_blocks.abs() * 4.0 / d).clamp(0, 7)
    mant = mant_scaled * 0.25

    sf = torch.where(
        vmax > 0, sf, torch.full_like(sf, 2.0 ** (-48))
    )

    prefix = tuple(original_shape[:-1]) + (n_blocks,)
    return {
        "scale_factor": sf.reshape(*prefix, 1, 1, 1).to(torch.float32),
        "scale_lv2":    lv2.reshape(*prefix, 8, 1, 1).to(torch.float32),
        "scale_lv3":    lv3.reshape(*prefix, 8, 2, 1).to(torch.float32),
        "sign":         sign.reshape(*prefix, 8, 2, 4).to(torch.float32),
        "mant":         mant.reshape(*prefix, 8, 2, 4).to(torch.float32),
    }


# ================================================================================
# NVFP4 quantization (for test-data generation, not used by platform)
# ================================================================================

def _quantize_e2m1(x: torch.Tensor) -> torch.Tensor:
    """Quantize to nearest E2M1 value: {0, 0.5, 1, 1.5, 2, 3, 4, 6}."""
    x_abs = x.abs()
    sign = torch.sign(x)
    result = torch.zeros_like(x_abs)
    result = torch.where(x_abs >= 5.0,        torch.full_like(x_abs, 6.0), result)
    result = torch.where((x_abs >= 3.5) & (x_abs < 5.0),    torch.full_like(x_abs, 4.0), result)
    result = torch.where((x_abs >= 2.5) & (x_abs < 3.5),    torch.full_like(x_abs, 3.0), result)
    result = torch.where((x_abs >= 1.75) & (x_abs < 2.5),   torch.full_like(x_abs, 2.0), result)
    result = torch.where((x_abs >= 1.25) & (x_abs < 1.75),  torch.full_like(x_abs, 1.5), result)
    result = torch.where((x_abs >= 0.75) & (x_abs < 1.25),  torch.full_like(x_abs, 1.0), result)
    result = torch.where((x_abs >= 0.25) & (x_abs < 0.75),  torch.full_like(x_abs, 0.5), result)
    return sign * result


def _quantize_e4m3(x: torch.Tensor) -> torch.Tensor:
    """Simplified E4M3 (FP8) quantization."""
    sign = torch.sign(x)
    x_abs = x.abs()
    result = torch.zeros_like(x_abs)
    nonzero = x_abs > 0
    if nonzero.any():
        x_nz = x_abs[nonzero].clamp(min=2.0 ** (-9), max=448.0)
        exp = torch.floor(torch.log2(x_nz))
        mant_scaled = torch.round(x_nz / (2.0 ** (exp - 3))).clamp(8, 15)
        carry = mant_scaled >= 16
        mant_scaled = torch.where(carry, mant_scaled - 8, mant_scaled)
        exp = torch.where(carry, exp + 1, exp)
        result[nonzero] = (mant_scaled * (2.0 ** (exp - 3))).clamp(
            min=2.0 ** (-9), max=448.0
        )
    return sign * result


def quantize_nvfp4(
    x: torch.Tensor, blk_size: int = 16
) -> tuple[torch.Tensor, torch.Tensor]:
    """Quantize FP32 to NVFP4 format. Returns (quant_float, scale_float)."""
    x_blocks = x.unflatten(-1, (-1, blk_size))
    vmax = x_blocks.abs().amax(dim=-1, keepdim=True)
    scale = _quantize_e4m3(vmax / 6.0)
    scale = scale.clamp(min=2.0 ** (-16))
    normalized = x_blocks / scale
    quant_float = _quantize_e2m1(normalized)
    return quant_float.flatten(-2, -1), scale.squeeze(-1)


# ================================================================================
# SmoothQuant helper
# ================================================================================

def _smoothquant_scale(
    act_max_abs: torch.Tensor,
    weight_max_abs: torch.Tensor,
    alpha: float = 0.5,
) -> torch.Tensor:
    """Compute SmoothQuant diagonal scale D_j = act^alpha / weight^(1-alpha)."""
    eps = 1e-8
    act_safe = act_max_abs.clamp(min=eps)
    weight_safe = weight_max_abs.clamp(min=eps)
    return (act_safe ** alpha) / (weight_safe ** (1.0 - alpha))


# ================================================================================
# Attention helpers (P^T P computation, GQA attention)
# ================================================================================

def _compute_rho_t(
    Q: torch.Tensor,
    K: torch.Tensor,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> torch.Tensor:
    """Compute P^T P column-norm-squared per (token, kv_head).

    This is the sensitivity weight for V quantization.  It uses the
    attention pattern P = softmax(Q @ K^T / sqrt(d)), NOT A@W.

    Returns: rho_t [seq_len, kv_num_heads]
    """
    S = Q.shape[0]
    group = q_num_heads // kv_num_heads

    Q_h = Q.reshape(S, q_num_heads, head_dim).transpose(0, 1)   # [H_q, S, D]
    K_h = K.reshape(S, kv_num_heads, head_dim).transpose(0, 1)  # [H_kv, S, D]

    rho = torch.zeros(S, kv_num_heads, dtype=torch.float32)
    scale = 1.0 / math.sqrt(head_dim)

    for g in range(kv_num_heads):
        q_g = Q_h[g * group:(g + 1) * group]                   # [group, S, D]
        k_g = K_h[g]                                            # [S, D]
        scores = torch.matmul(q_g, k_g.transpose(-2, -1)) * scale  # [group, S, S]
        attn = torch.softmax(scores, dim=-1)                   # [group, S, S]
        rho[:, g] = (attn ** 2).sum(dim=(0, 1))                # [S]

    return rho


# ================================================================================
# 1. Linear: calibration + weight quantization
# ================================================================================

def hif4_calibration_and_quantize_weight(
    weight_quant: torch.Tensor,
    weight_scale: torch.Tensor,
    calib_activation_list: list,
) -> dict[str, Any]:
    """Offline weight quantization + activation-state preparation.

    Uses:
      - Random Hadamard rotation (64x64, per-block, aligned with HiF4)
      - Exact micro-exponent + E6M2 scale search
      - Output-sensitive weighting (lambda_j from calibration activations)

    NO A@W is computed anywhere.
    """
    W = dequantize_nvfp4(weight_quant, weight_scale)            # [M, K]
    M, K = W.shape

    calib_acts = [
        dequantize_nvfp4(q, s) for q, s in calib_activation_list
    ]

    H = _make_random_hadamard(64, seed=42)                      # [64, 64]

    W_rot = _apply_hadamard_blocks(W, H)                        # [M, K]

    lambda_j = torch.zeros(K, dtype=torch.float32)
    for act in calib_acts:
        act_rot = _apply_hadamard_blocks(act, H)
        lambda_j += (act_rot ** 2).mean(dim=0)
    lambda_j /= max(len(calib_acts), 1)
    lambda_j = lambda_j.clamp(min=1e-12)

    numel = M * K
    num_candidates_w = 9 if numel <= 4_000_000 else 5
    weight_params = _quantize_hif4_core(
        W_rot,
        channel_weight=lambda_j.unsqueeze(0).expand(M, K),
        num_candidates=num_candidates_w,
    )

    W_hat = _dequantize_hif4(weight_params, W_rot.shape)
    w_diag = (W_hat ** 2).sum(dim=0)                            # [K]
    w_diag = w_diag.clamp(min=1e-12)

    activation_state: dict[str, Any] = {
        "hadamard": H,
        "w_diag": w_diag,
    }

    return {
        "weight_params": weight_params,
        "activation_state": activation_state,
    }


# ================================================================================
# 2. Linear: dynamic activation quantization
# ================================================================================

def hif4_dynamic_quantize_activation(
    activation_quant: torch.Tensor,
    activation_scale: torch.Tensor,
    activation_state: Any,
) -> dict[str, torch.Tensor]:
    """Online dynamic HiF4 quantization of activation."""
    X = dequantize_nvfp4(activation_quant, activation_scale)    # [T, K]
    T, K = X.shape

    H = activation_state["hadamard"]
    w_diag = activation_state.get("w_diag")

    X_rot = _apply_hadamard_blocks(X, H)                      # [T, K]

    numel = T * K
    if numel > 4_000_000:
        num_cand = 5
    elif numel > 1_000_000:
        num_cand = 7
    else:
        num_cand = 9

    cw = w_diag.unsqueeze(0).expand(T, K) if w_diag is not None else None

    return _quantize_hif4_core(X_rot, channel_weight=cw, num_candidates=num_cand)


# ================================================================================
# 3. Attention: calibration
# ================================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Generate Q/K/V online-quantization states from calibration data."""
    n_hd_blocks = head_dim // 64

    if head_dim % 64 == 0 and head_dim >= 64:
        H_base = torch.stack([
            _make_random_hadamard(64, seed=42 + g * 17)
            for g in range(kv_num_heads)
        ])
        H_attn = H_base.unsqueeze(1).expand(
            kv_num_heads, n_hd_blocks, 64, 64
        ).contiguous()
    else:
        H_attn = None

    q_state: dict[str, Any] = {"hadamard": H_attn, "kv_num_heads": kv_num_heads}
    k_state: dict[str, Any] = {"hadamard": H_attn, "kv_num_heads": kv_num_heads}
    v_state: dict[str, Any] = {}

    return {"q_state": q_state, "k_state": k_state, "v_state": v_state}


# ================================================================================
# 4. Dynamic Q quantization
# ================================================================================

def hif4_dynamic_quantize_q(
    q_quant: torch.Tensor,
    q_scale: torch.Tensor,
    q_num_heads: int,
    head_dim: int,
    q_state: Any,
) -> dict[str, torch.Tensor]:
    """Dynamic HiF4 quantization of online Q."""
    Q = dequantize_nvfp4(q_quant, q_scale)                     # [S, H_q*D]
    H = q_state.get("hadamard") if q_state else None

    if H is not None:
        kv_num_heads = q_state.get("kv_num_heads", q_num_heads)
        Q_rot = _apply_per_head_hadamard(
            Q, H, q_num_heads, head_dim, kv_num_heads
        )
    else:
        Q_rot = Q

    return _quantize_hif4_core(Q_rot, channel_weight=None, num_candidates=9)


# ================================================================================
# 5. Dynamic K quantization
# ================================================================================

def hif4_dynamic_quantize_k(
    k_quant: torch.Tensor,
    k_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    k_state: Any,
) -> dict[str, torch.Tensor]:
    """Dynamic HiF4 quantization of online K."""
    K = dequantize_nvfp4(k_quant, k_scale)                      # [S, H_kv*D]
    H = k_state.get("hadamard") if k_state else None

    if H is not None:
        K_rot = _apply_per_head_hadamard(
            K, H, kv_num_heads, head_dim, kv_num_heads
        )
    else:
        K_rot = K

    return _quantize_hif4_core(K_rot, channel_weight=None, num_candidates=9)


# ================================================================================
# 6. Dynamic V quantization
# ================================================================================

def hif4_dynamic_quantize_v(
    v_quant: torch.Tensor,
    v_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    v_state: Any,
) -> dict[str, torch.Tensor]:
    """Dynamic HiF4 quantization of online V."""
    V = dequantize_nvfp4(v_quant, v_scale)
    return _quantize_hif4_core(V, channel_weight=None, num_candidates=9)
