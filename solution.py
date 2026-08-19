"""HiF4 conversion with output-aware calibration.

The format search is exact over the two HiF4 micro-exponents for every
considered E6M2 scale. Linear calibration uses an invertible SmoothQuant-like
diagonal balance plus output sensitivity weights. Q/K rotations are restricted
to head-aligned blocks, and V uses calibration attention probabilities.
"""

from __future__ import annotations

import math
from typing import Any

import torch

BLK_SIZE = 64
NVFP4_BLK = 16
HAD_SIZE = 64
E6_CANDIDATES = 7
# Calibration is an offline ranking pass.  A five-point window preserves the
# original/reference candidates while avoiding spending the online budget on
# every calibration tensor.  Online calls keep the wider seven-point search.
CALIB_E6_CANDIDATES = 5
ATTN_CURVATURE_MAX_TOKENS = 256
SMOOTH_ALPHA = 0.5
SMOOTH_MIN = 1.0 / 16.0
SMOOTH_MAX = 16.0


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


def _e6m2_candidates(target, n_candidates=E6_CANDIDATES):
    target_flat = target.reshape(-1).double()
    idx = torch.searchsorted(_E6M2_TABLE, target_flat)
    half = n_candidates // 2
    offsets = torch.arange(-half, half + 1, dtype=torch.long)
    if n_candidates % 2 == 0:
        offsets = offsets[:-1]
    cand_idx = idx.unsqueeze(-1) + offsets
    cand_idx = cand_idx.clamp(0, len(_E6M2_TABLE) - 1)
    candidates = _E6M2_TABLE[cand_idx]
    out_shape = list(target.shape[:-1]) + [n_candidates]
    return candidates.reshape(out_shape).to(torch.float32)


def _apply_hadamard(x, H):
    h = H.shape[0]
    C = x.shape[-1]
    assert C % h == 0
    x_re = x.reshape(-1, h)
    x_rot = x_re @ H
    return x_rot.reshape(x.shape).to(torch.float32)


def _apply_head_hadamard(x, num_heads, head_dim, H):
    """Apply the same orthogonal transform inside each head only."""
    if H is None or head_dim % HAD_SIZE != 0:
        return x
    if x.shape[-1] != num_heads * head_dim:
        return x
    x_heads = x.reshape(-1, num_heads, head_dim)
    x_blocks = x_heads.reshape(-1, HAD_SIZE)
    rotated = x_blocks @ H.to(dtype=torch.float32)
    return rotated.reshape_as(x_heads).reshape_as(x).to(torch.float32)


def _quantize_block_given_scale(w, sf, imp=None):
    """Jointly optimize E1_8 and the two E1_16 values for one E6M2 scale."""
    has_imp = imp is not None

    def _loss(dq, ref):
        if has_imp:
            return (imp * (dq - ref).square()).sum(dim=-1)
        return (dq - ref).square().sum(dim=-1)

    per_lv2 = []
    for lv2 in (1.0, 2.0):
        q_by_lv3 = []
        loss_by_lv3 = []
        for lv3 in (1.0, 2.0):
            q = (w / (sf * lv2 * lv3) * 4.0).round().clamp(-7, 7) / 4.0
            dq = q * (sf * lv2 * lv3)
            q_by_lv3.append(q)
            loss_by_lv3.append(_loss(dq, w))

        choose_lv3_2 = loss_by_lv3[1] < loss_by_lv3[0]
        q_final = torch.where(
            choose_lv3_2.unsqueeze(-1), q_by_lv3[1], q_by_lv3[0]
        )
        loss_final = torch.where(choose_lv3_2, loss_by_lv3[1], loss_by_lv3[0])
        per_lv2.append((choose_lv3_2, q_final, loss_final))

    # Each E1_8 is shared by two E1_16 groups, so compare their joint loss.
    lv2_loss = [entry[2].sum(dim=-1) for entry in per_lv2]
    choose_lv2_2 = lv2_loss[1] < lv2_loss[0]
    choose_lv3_2 = torch.where(
        choose_lv2_2.unsqueeze(-1), per_lv2[1][0], per_lv2[0][0]
    )
    q_final = torch.where(
        choose_lv2_2.unsqueeze(-1).unsqueeze(-1), per_lv2[1][1], per_lv2[0][1]
    )
    loss_final = torch.where(choose_lv2_2.unsqueeze(-1), per_lv2[1][2], per_lv2[0][2])

    scale_lv2 = torch.where(choose_lv2_2, 2.0, 1.0)
    scale_lv3 = torch.where(choose_lv3_2, 2.0, 1.0)
    sign = torch.sign(q_final)
    mant = q_final.abs()

    block_mse = loss_final.sum(dim=(-2, -1))
    if has_imp:
        norm = imp.sum(dim=(-3, -2, -1)).clamp(min=1e-12)
        block_mse = block_mse / norm

    return scale_lv2, scale_lv3, sign, mant, block_mse


def _quantize_hif4(w_fp, n_candidates=E6_CANDIDATES, importance=None, chunk_rows=384):
    orig_shape = w_fp.shape

    if w_fp.ndim <= 1 or w_fp.shape[0] <= chunk_rows:
        return _quantize_hif4_impl(w_fp, n_candidates, importance)

    results = []
    for start in range(0, w_fp.shape[0], chunk_rows):
        end = min(start + chunk_rows, w_fp.shape[0])
        chunk_imp = importance
        if importance is not None and importance.ndim > 1:
            chunk_imp = importance[start:end]
        results.append(_quantize_hif4_impl(w_fp[start:end], n_candidates, chunk_imp))

    return {k: torch.cat([r[k] for r in results], dim=0) for k in results[0]}


def _quantize_hif4_impl(w_fp, n_candidates=E6_CANDIDATES, importance=None):
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


def _dequant_hif4(params):
    values = (
        params["scale_factor"]
        * params["scale_lv2"]
        * params["scale_lv3"]
        * params["sign"]
        * params["mant"]
    )
    return values.reshape(*params["sign"].shape[:-4], -1).to(torch.float32)


def _smooth_scale(weight, calib_activation_list, alpha=SMOOTH_ALPHA):
    """Calibration-only diagonal balancing for X / D and W * D."""
    x_amax = torch.zeros(weight.shape[-1], dtype=torch.float32)
    for quant, scale in calib_activation_list:
        x = _dequant_nvfp4(quant, scale)
        x_amax = torch.maximum(x_amax, x.abs().amax(dim=0))
    w_amax = weight.abs().amax(dim=0)
    eps = 1e-8
    d = (x_amax.clamp(min=eps).pow(alpha) /
         w_amax.clamp(min=eps).pow(1.0 - alpha))
    return d.clamp(min=SMOOTH_MIN, max=SMOOTH_MAX).to(torch.float32)


def _calib_channel_second_moment(calib_activation_list, smooth, H):
    second_moment = torch.zeros_like(smooth)
    count = 0
    for quant, scale in calib_activation_list:
        x = _dequant_nvfp4(quant, scale) / smooth
        x = _apply_hadamard(x, H)
        second_moment += x.square().sum(dim=0)
        count += x.shape[0]
    return (second_moment / max(count, 1)).clamp(min=1e-8)


def _attention_output(q, k, v, q_num_heads, kv_num_heads, head_dim):
    q = q.reshape(-1, q_num_heads, head_dim)
    k = k.reshape(-1, kv_num_heads, head_dim)
    v = v.reshape(-1, kv_num_heads, head_dim)
    repeat = q_num_heads // kv_num_heads
    k = k.repeat_interleave(repeat, dim=1)
    v = v.repeat_interleave(repeat, dim=1)
    logits = torch.einsum("thd,shd->hts", q, k) / math.sqrt(head_dim)
    p = torch.softmax(logits.float(), dim=-1)
    return torch.einsum("hts,shd->thd", p, v).reshape(q.shape[0], -1)


def _normalize_importance(x):
    x = x.clamp(min=1e-8).float()
    return (x / x.mean().clamp(min=1e-8)).clamp(min=0.05, max=20.0)


def _attention_balance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim, alpha=0.5):
    q_amax = torch.zeros(q_num_heads, head_dim)
    k_amax = torch.zeros(kv_num_heads, head_dim)
    for sample in calib_qkv_list:
        q = _dequant_nvfp4(*sample["q"]).reshape(-1, q_num_heads, head_dim)
        k = _dequant_nvfp4(*sample["k"]).reshape(-1, kv_num_heads, head_dim)
        q_amax = torch.maximum(q_amax, q.abs().amax(dim=0))
        k_amax = torch.maximum(k_amax, k.abs().amax(dim=0))
    q_per_kv = q_num_heads // kv_num_heads
    q_group = q_amax.reshape(kv_num_heads, q_per_kv, head_dim).amax(dim=1)
    eps = 1e-8
    d = q_group.clamp(min=eps).pow(alpha) / k_amax.clamp(min=eps).pow(1.0 - alpha)
    d = d.clamp(min=SMOOTH_MIN, max=SMOOTH_MAX)
    return d.repeat_interleave(q_per_kv, dim=0).reshape(-1), d.reshape(-1)


def _compute_attention_importances(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Diagonal Gauss-Newton proxies for Q, K and V, averaged by channel."""
    q_acc = torch.zeros(q_num_heads * head_dim)
    k_acc = torch.zeros(kv_num_heads * head_dim)
    v_acc = torch.zeros(kv_num_heads * head_dim)
    n = 0
    q_per_kv = q_num_heads // kv_num_heads
    for sample in calib_qkv_list:
        q = _dequant_nvfp4(*sample["q"]).reshape(-1, q_num_heads, head_dim)
        k = _dequant_nvfp4(*sample["k"]).reshape(-1, kv_num_heads, head_dim)
        v = _dequant_nvfp4(*sample["v"]).reshape(-1, kv_num_heads, head_dim)
        # Dense softmax Jacobians scale as O(T^2) memory and O(T^3) work.
        # For long contexts use the diagonal second-order proxy implied by
        # the same Taylor expansion; this keeps calibration bounded while
        # retaining the correct Q/K/V sensitivity ordering.
        if q.shape[0] > ATTN_CURVATURE_MAX_TOKENS:
            k2 = k.square().mean(dim=0)
            v2 = v.square().mean(dim=0)
            q2 = q.square().mean(dim=0)
            for h in range(q_num_heads):
                g = h // q_per_kv
                q_acc[h * head_dim:(h + 1) * head_dim] += (
                    k2[g] * v2[g].mean() / head_dim
                )
                k_acc[g * head_dim:(g + 1) * head_dim] += (
                    q2[h] * v2[g].mean() / head_dim
                )
            v_acc += v2.reshape(-1)
            n += q.shape[0] * q_num_heads
            continue
        for h in range(q_num_heads):
            g = h // q_per_kv
            qh, kh, vh = q[:, h, :], k[:, g, :], v[:, g, :]
            logits = qh @ kh.T / math.sqrt(head_dim)
            p = torch.softmax(logits.float(), dim=-1)
            j = torch.diag_embed(p) - p.unsqueeze(-1) * p.unsqueeze(-2)
            gram_v = vh @ vh.T
            gmat = j @ gram_v @ j.transpose(-1, -2)
            hmat = torch.einsum("ad,tab,be->tde", kh, gmat, kh)
            q_h = hmat.diagonal(dim1=-2, dim2=-1).mean(dim=0) / head_dim
            q_acc[h * head_dim:(h + 1) * head_dim] += q_h
            gdiag = gmat.diagonal(dim1=-2, dim2=-1)
            k_h = (gdiag[:, :, None] * qh[:, None, :].square()).sum(dim=0).mean(dim=0) / head_dim
            k_acc[g * head_dim:(g + 1) * head_dim] += k_h

        logits = torch.einsum("thd,shd->hts", q, k.repeat_interleave(q_per_kv, 1))
        p = torch.softmax((logits / math.sqrt(head_dim)).float(), dim=-1)
        rho = p.square().sum(dim=(0, 1))
        v_acc += (rho[:, None, None] * v.square()).sum(dim=0).reshape(-1)
        n += q.shape[0] * q_num_heads

    if n == 0:
        return None, None, None
    return (_normalize_importance(q_acc / n),
            _normalize_importance(k_acc / n),
            _normalize_importance(v_acc / n))


# ======================================================================
# 1. Linear: 校准 + 权重量化
# ======================================================================

def hif4_calibration_and_quantize_weight(
    weight_quant: torch.Tensor,
    weight_scale: torch.Tensor,
    calib_activation_list: list,
) -> dict[str, Any]:
    """Quantize balanced/rotated weights with calibration output sensitivity."""
    weight_fp = _dequant_nvfp4(weight_quant, weight_scale)
    H0 = _random_hadamard(HAD_SIZE, seed=42).to(torch.float32)
    modes = [("baseline", torch.ones_like(weight_fp[-1]), H0, False)]
    for alpha in (0.25, 0.5, 0.75):
        modes.append((f"smooth_{alpha}", _smooth_scale(weight_fp, calib_activation_list, alpha), H0, True))
    modes.append(("no_rotation", _smooth_scale(weight_fp, calib_activation_list, 0.5), None, True))

    best = None
    for name, smooth, H, weighted in modes:
        weight_t = weight_fp * smooth
        if H is not None:
            weight_t = _apply_hadamard(weight_t, H)
        x_second = _calib_channel_second_moment(calib_activation_list, smooth, H) if H is not None else _calib_channel_second_moment(calib_activation_list, smooth, torch.eye(1))
        weight_params = _quantize_hif4(
            weight_t, n_candidates=CALIB_E6_CANDIDATES,
            importance=x_second if weighted else None,
        )
        weight_hat = _dequant_hif4(weight_params)
        w_imp = _normalize_importance(weight_hat.square().sum(dim=0))
        error = 0.0
        for pair in calib_activation_list:
            x = _dequant_nvfp4(*pair) / smooth
            if H is not None:
                x = _apply_hadamard(x, H)
            x_params = _quantize_hif4(
                x, n_candidates=CALIB_E6_CANDIDATES,
                importance=w_imp if weighted else None,
            )
            x_hat = _dequant_hif4(x_params)
            error += float((x_hat @ weight_hat.T - x @ weight_t.T).square().mean())
        error /= max(len(calib_activation_list), 1)
        if best is None or error < best[0]:
            best = (error, name, smooth, H, weight_params, w_imp)

    _, name, smooth, H, weight_params, activation_importance = best

    activation_state = {
        "mode": name,
        "hadamard": H.contiguous() if H is not None else None,
        "smooth": smooth.contiguous(),
        "importance": activation_importance.contiguous(),
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
    """Quantize balanced activations using diag(W_hat^T W_hat) weights."""
    act_fp = _dequant_nvfp4(activation_quant, activation_scale)

    H = activation_state.get("hadamard") if isinstance(activation_state, dict) else None
    smooth = activation_state.get("smooth") if isinstance(activation_state, dict) else None
    importance = activation_state.get("importance") if isinstance(activation_state, dict) else None
    if smooth is not None and int(smooth.numel()) == int(act_fp.shape[-1]):
        act_fp = act_fp / smooth.to(dtype=torch.float32)
    if H is not None:
        act_fp = _apply_hadamard(act_fp, H.to(torch.float32))
    if importance is not None and int(importance.numel()) != int(act_fp.shape[-1]):
        importance = None

    return _quantize_hif4(act_fp, n_candidates=E6_CANDIDATES, importance=importance)


# ======================================================================
# 3. Attention: 校准
# ======================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Jointly choose Q/K/V mode using calibration Attention reconstruction."""
    H = None
    if head_dim % HAD_SIZE == 0:
        H = _random_hadamard(HAD_SIZE, seed=123).to(torch.float32).contiguous()
    q_imp, k_imp, v_imp = _compute_attention_importances(
        calib_qkv_list, q_num_heads, kv_num_heads, head_dim
    )
    balance_q, balance_k = _attention_balance(
        calib_qkv_list, q_num_heads, kv_num_heads, head_dim, 0.5
    )
    modes = [
        ("baseline", None, None, None, None, None),
        ("head_rotation", H, None, None, None, None),
        ("curvature", None, q_imp, k_imp, None, None),
        ("qk_balance", None, None, None, balance_q, balance_k),
        ("rotation_v_curvature", H, None, None, None, None),
    ]
    max_tokens = max(int(sample["q"][0].shape[0]) for sample in calib_qkv_list)
    if max_tokens > 512:
        # Rotation and the duplicate rotation+V candidate are expensive for
        # long contexts; retain the ordinary, curvature and balance choices.
        modes = [modes[0], modes[2], modes[3]]
    best = None
    for name, mode_h, mode_q_imp, mode_k_imp, mode_q_balance, mode_k_balance in modes:
        mode_v_imp = v_imp if name in ("curvature", "rotation_v_curvature") else None
        error = 0.0
        for sample in calib_qkv_list:
            refs = {role: _dequant_nvfp4(*sample[role]) for role in ("q", "k", "v")}
            q = _apply_head_hadamard(refs["q"], q_num_heads, head_dim, mode_h)
            k = _apply_head_hadamard(refs["k"], kv_num_heads, head_dim, mode_h)
            if mode_q_balance is not None:
                q = q * mode_q_balance
                k = k / mode_k_balance
            q_params = _quantize_hif4(
                q, n_candidates=CALIB_E6_CANDIDATES, importance=mode_q_imp
            )
            k_params = _quantize_hif4(
                k, n_candidates=CALIB_E6_CANDIDATES, importance=mode_k_imp
            )
            v_params = _quantize_hif4(
                refs["v"], n_candidates=CALIB_E6_CANDIDATES,
                importance=mode_v_imp,
            )
            q_hat, k_hat, v_hat = map(_dequant_hif4, (q_params, k_params, v_params))
            error += float((
                _attention_output(q_hat, k_hat, v_hat, q_num_heads, kv_num_heads, head_dim)
                - _attention_output(q, k, refs["v"], q_num_heads, kv_num_heads, head_dim)
            ).square().mean())
        error /= max(len(calib_qkv_list), 1)
        if best is None or error < best[0]:
            best = (error, name, mode_h, mode_q_imp, mode_k_imp, mode_v_imp, mode_q_balance, mode_k_balance)

    _, name, H, q_imp, k_imp, v_imp, balance_q, balance_k = best
    q_state = {"mode": name, "hadamard": H, "importance": q_imp, "balance": balance_q}
    k_state = {"mode": name, "hadamard": H, "importance": k_imp, "balance": balance_k}
    v_state = {"mode": name, "importance": v_imp}

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
    """Q with a transform that cannot cross attention-head boundaries."""
    q_fp = _dequant_nvfp4(q_quant, q_scale)

    if isinstance(q_state, dict):
        H = q_state.get("hadamard")
        importance = q_state.get("importance")
        balance = q_state.get("balance")
    else:
        H = None
        importance = None
        balance = None
    q_fp = _apply_head_hadamard(q_fp, q_num_heads, head_dim, H)
    if balance is not None and int(balance.numel()) == int(q_fp.shape[-1]):
        q_fp = q_fp * balance.to(dtype=torch.float32)

    return _quantize_hif4(q_fp, n_candidates=E6_CANDIDATES, importance=importance)


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
    """K with the Q-matched transform applied within each KV head."""
    k_fp = _dequant_nvfp4(k_quant, k_scale)

    if isinstance(k_state, dict):
        H = k_state.get("hadamard")
        importance = k_state.get("importance")
        balance = k_state.get("balance")
    else:
        H = None
        importance = None
        balance = None
    k_fp = _apply_head_hadamard(k_fp, kv_num_heads, head_dim, H)
    if balance is not None and int(balance.numel()) == int(k_fp.shape[-1]):
        k_fp = k_fp / balance.to(dtype=torch.float32)

    return _quantize_hif4(k_fp, n_candidates=E6_CANDIDATES, importance=importance)


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
    """V with calibration diag(P^T P) token importance when shapes match."""
    v_fp = _dequant_nvfp4(v_quant, v_scale)

    imp = None
    if isinstance(v_state, dict):
        imp = v_state.get("importance")
        if imp is not None and int(imp.shape[-1]) != int(v_fp.shape[-1]):
            imp = None

    return _quantize_hif4(v_fp, n_candidates=E6_CANDIDATES, importance=imp)
