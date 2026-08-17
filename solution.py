"""solution.py — NVFP4 -> HiF4 conversion (self-contained, single-file submission).

Algorithm (idea.md):
  A) MSE-optimal E6M2 scale_factor grid search (13 candidates around vmax/7)
  C) Hadamard orthogonal transform on the shared dot-dim before quantization
  B) Greedy E1_8 / E1_16 micro-exponent refinement (kept on for max MSE gain)

NVFP4 dequant:  quant * scale_float (E4M3 per-16-block).
HiF4 dequant:   sign * mant * scale_lv2 * scale_lv3 * scale_factor.

Per 64-element block, flat index i in [0,64):
    j = i // 8, k = (i % 8) // 4, m = i % 4
    dq[i] = sign[j,k,m] * mant[j,k,m] * scale_lv2[j] * scale_lv3[j,k] * scale_factor
"""
from __future__ import annotations

import torch

# ------------------------------------------------------------------- NVFP4 --
def dequantize_nvfp4(quant, scale_float, blk_size: int = 16):
    x = quant.unflatten(-1, (-1, blk_size))
    return (x * scale_float.unsqueeze(-1)).flatten(-2, -1).to(torch.bfloat16)


# --------------------------------------------------------------- Hadamard --
_H_CACHE: dict[int, torch.Tensor] = {}


def _hadamard_matrix(n: int) -> torch.Tensor:
    if n in _H_CACHE:
        return _H_CACHE[n]
    if n == 1:
        H = torch.ones(1, 1, dtype=torch.float64)
    else:
        h = _hadamard_matrix(n // 2)
        H = torch.cat([torch.cat([h, h], dim=1),
                       torch.cat([h, -h], dim=1)], dim=0) / (2.0 ** 0.5)
    _H_CACHE[n] = H
    return H


def apply_hadamard(x: torch.Tensor, n: int) -> torch.Tensor:
    """Apply n x n Hadamard to the last dim of x (x @ H, H @ H^T = I).
    n must be a power of 2; if n < x.shape[-1] only the first n cols are rotated."""
    H = _hadamard_matrix(n).to(device=x.device,
                               dtype=x.dtype if x.dtype.is_floating_point else torch.float64)
    if n == x.shape[-1]:
        return x @ H
    out = x.clone()
    out[..., :n] = x[..., :n] @ H
    return out


# --------------------------------------------------------------- E6M2/S1P2 --
def _build_e6m2_lut() -> torch.Tensor:
    vals = []
    for e in range(-48, 16):
        for m in range(4):
            if e == 15 and m == 3:
                continue  # 57344 is NaN in E6M2
            vals.append((2.0 ** e) * (1.0 + m / 4.0))
    vals.sort()
    return torch.tensor(vals, dtype=torch.float64)


E6M2_LUT = _build_e6m2_lut()
E6M2_MIN = float(E6M2_LUT[0].item())
E6M2_MAX = float(E6M2_LUT[-1].item())

S1P2_MAGS = torch.tensor([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75], dtype=torch.float64)
S1P2_BOUNDS = torch.tensor([0.125, 0.375, 0.625, 0.875, 1.125, 1.375, 1.625], dtype=torch.float64)

_BLK_J = torch.arange(64) // 8
_BLK_K = (torch.arange(64) % 8) // 4
_POW2 = torch.tensor([1.0, 2.0], dtype=torch.float64)


def _quantize_to_s1p2(x: torch.Tensor):
    sign = torch.sign(x)
    mant = S1P2_MAGS[torch.searchsorted(S1P2_BOUNDS, x.abs().clamp(max=1.75),
                                         right=True).clamp(min=0, max=7)]
    sign = torch.where(mant == 0.0, torch.zeros_like(sign), sign)
    return sign, mant


def _quant_block(blocks, sf, e1_8, e1_16):
    """Quantize (B, 64) blocks to S1P2 given fixed scales. Returns (sign, mant) (B, 8, 2, 4)."""
    B = blocks.shape[0]
    j = _BLK_J.to(blocks.device)
    k = _BLK_K.to(blocks.device)
    combined = sf[:, None] * _POW2[e1_8.long()][:, j] * _POW2[e1_16.long().view(B, 8, 2)][:, j, k]
    sign_flat, mant_flat = _quantize_to_s1p2(blocks / combined)
    return sign_flat.view(B, 8, 2, 4), mant_flat.view(B, 8, 2, 4)


def _dequant_block(sf, e1_8, e1_16, sign, mant) -> torch.Tensor:
    """Reconstruct (B, 64) from HiF4 params — matches self_check dequantize_hif4."""
    B = sf.shape[0]
    j = _BLK_J.to(sf.device)
    k = _BLK_K.to(sf.device)
    return ((sign * mant).view(B, 64)
            * _POW2[e1_8.long()][:, j]
            * _POW2[e1_16.long().view(B, 8, 2)][:, j, k]
            * sf[:, None])


# --------------------------------------------------------- quantize_blocks --
def quantize_blocks(blocks: torch.Tensor, n_scale_cands: int = 13,
                    refine_e1: bool = True) -> dict:
    """Component A (scale grid search) + Component B (greedy E1 refinement)."""
    blocks = blocks.to(torch.float64)
    B = blocks.shape[0]
    dev = blocks.device

    # Tree reduction for peak magnitudes (Algorithm 1 lines 1-7).
    v16 = blocks.view(B, 16, 4).abs().amax(dim=2)   # (B, 16)
    v8 = v16.view(B, 8, 2).amax(dim=2)              # (B, 8)
    vmax = v8.amax(dim=1)                            # (B,)

    # Component A: enumerate E6M2 candidates around vmax/7 and pick min-MSE.
    base = (vmax / 7.0).clamp(min=E6M2_MIN, max=E6M2_MAX)
    base_idx = torch.searchsorted(E6M2_LUT, base, right=True).clamp(min=1, max=len(E6M2_LUT) - 1)
    half = n_scale_cands // 2
    offsets = torch.arange(-half, n_scale_cands - half, device=dev)
    cand_idx = (base_idx[:, None] + offsets[None, :]).clamp(0, len(E6M2_LUT) - 1)
    sf_cands = E6M2_LUT[cand_idx]                    # (B, n_scale_cands)

    best_mse = torch.full((B,), float('inf'), device=dev)
    best_sf = torch.zeros(B, dtype=torch.float64, device=dev)
    best_e1_8 = torch.zeros(B, 8, dtype=torch.float64, device=dev)
    best_e1_16 = torch.zeros(B, 8, 2, dtype=torch.float64, device=dev)
    best_sign = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)
    best_mant = torch.zeros(B, 8, 2, 4, dtype=torch.float64, device=dev)

    v16_2d = v16.view(B, 8, 2)

    def try_config(sf, e1_8, e1_16):
        """Quantize + dequant + MSE for a candidate config; updates best_* in place."""
        nonlocal best_mse, best_sf, best_e1_8, best_e1_16, best_sign, best_mant
        sign, mant = _quant_block(blocks, sf, e1_8, e1_16)
        dq = _dequant_block(sf, e1_8, e1_16, sign, mant)
        mse = ((dq - blocks) ** 2).mean(dim=1)
        better = mse < best_mse
        _b = better[:, None, None, None]
        best_mse = torch.where(better, mse, best_mse)
        best_sf = torch.where(better, sf, best_sf)
        best_e1_8 = torch.where(better[:, None], e1_8, best_e1_8)
        best_e1_16 = torch.where(better[:, None, None], e1_16, best_e1_16)
        best_sign = torch.where(_b, sign, best_sign)
        best_mant = torch.where(_b, mant, best_mant)

    # Stage 2: scale grid search with standard threshold E1 heuristic.
    for c in range(n_scale_cands):
        sf = sf_cands[:, c]
        rec = 1.0 / sf
        e1_8 = (v8 * rec[:, None] >= 4.0).to(torch.float64)
        e1_16 = (v16_2d * rec[:, None, None]
                 * (1.0 / _POW2[e1_8.long()])[:, :, None] >= 2.0).to(torch.float64)
        try_config(sf, e1_8, e1_16)

    # Stage 3 (Component B): greedy E1_8 then E1_16 bit flips.
    if refine_e1:
        for j in range(8):
            for nv in (0.0, 1.0):
                t = best_e1_8.clone()
                t[:, j] = nv
                e1_16 = (v16_2d * (1.0 / best_sf)[:, None, None]
                         * (1.0 / _POW2[t.long()])[:, :, None] >= 2.0).to(torch.float64)
                try_config(best_sf, t, e1_16)
        for j in range(8):
            for k in range(2):
                for nv in (0.0, 1.0):
                    t = best_e1_16.clone()
                    t[:, j, k] = nv
                    try_config(best_sf, best_e1_8, t)

    return {
        "scale_factor": best_sf.view(B, 1),
        "scale_lv2": _POW2[best_e1_8.long()],
        "scale_lv3": _POW2[best_e1_16.long()],
        "sign": best_sign,
        "mant": best_mant,
    }


def quantize_tensor(x: torch.Tensor, n_scale_cands: int = 13,
                    refine_e1: bool = True) -> dict:
    """Quantize (..., C) tensor (C % 64 == 0) to HiF4 params with required shapes."""
    x = x.to(torch.float64)
    shape = x.shape
    C = shape[-1]
    if C % 64 != 0:
        raise ValueError(f"Last dim {C} not divisible by HiF4 block size 64")
    prefix = shape[:-1]
    nb = C // 64
    out = quantize_blocks(x.reshape(-1, 64), n_scale_cands=n_scale_cands, refine_e1=refine_e1)
    return {
        "scale_factor": out["scale_factor"].view(*prefix, nb, 1, 1, 1).to(torch.float32),
        "scale_lv2": out["scale_lv2"].view(*prefix, nb, 8, 1, 1).to(torch.float32),
        "scale_lv3": out["scale_lv3"].view(*prefix, nb, 8, 2, 1).to(torch.float32),
        "sign": out["sign"].view(*prefix, nb, 8, 2, 4).to(torch.float32),
        "mant": out["mant"].view(*prefix, nb, 8, 2, 4).to(torch.float32),
    }


# ----------------------------------------------------------- Public API --
def hif4_quantize(w_quant, w_scale, a_quant, a_scale) -> dict:
    """Problem 1 (Linear A@W^T): same Hadamard H_K on K-dim of both operands
    (MatMul invariance via H @ H^T = I), then components A+B."""
    weight = dequantize_nvfp4(w_quant, w_scale).to(torch.float32)
    activation = dequantize_nvfp4(a_quant, a_scale).to(torch.float32)
    K = weight.shape[-1]
    weight_h = apply_hadamard(weight, n=K).to(torch.float32)
    activation_h = apply_hadamard(activation, n=K).to(torch.float32)
    return {
        "weight": quantize_tensor(weight_h, n_scale_cands=13, refine_e1=True),
        "activation": quantize_tensor(activation_h, n_scale_cands=13, refine_e1=True),
    }


def hif4_quantize_attn(q_quant, q_scale, k_quant, k_scale, v_quant, v_scale,
                       q_num_heads: int, kv_num_heads: int, head_dim: int) -> dict:
    """Problem 2 (GQA): same Hadamard H_head_dim on Q and K head_dim axis
    (preserves per-head Q@K^T, hence softmax and output). V is NOT rotated:
    (softmax @ V) @ H != softmax @ V would change output column order."""
    q = dequantize_nvfp4(q_quant, q_scale).to(torch.float32)
    k = dequantize_nvfp4(k_quant, k_scale).to(torch.float32)
    v = dequantize_nvfp4(v_quant, v_scale).to(torch.float32)
    S = q.shape[0]
    q_h = apply_hadamard(q.view(S, q_num_heads, head_dim), n=head_dim).reshape(S, q_num_heads * head_dim)
    k_h = apply_hadamard(k.view(S, kv_num_heads, head_dim), n=head_dim).reshape(S, kv_num_heads * head_dim)
    return {
        "q": quantize_tensor(q_h, n_scale_cands=13, refine_e1=True),
        "k": quantize_tensor(k_h, n_scale_cands=13, refine_e1=True),
        "v": quantize_tensor(v, n_scale_cands=13, refine_e1=True),
    }
