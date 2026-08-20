"""
HiF4 solution.py — NVFP4 → HiF4 量化转换 (输出敏感度优化)

针对赛题要求"分别对权重、激活(A和Attention Q/K/V)设计最优量化算法"：

  权重 W (离线): SmoothQuant alpha扫描 + Hadamard旋转 + exact微指数 +
                 校准激活 lambda_j 加权 (对齐 ||X E_W^T||^2 输出MSE)
  激活 A (在线): SmoothQuant D^-1 + Hadamard旋转 + exact微指数 +
                 diag(W_hat^T W_hat) 加权 (对齐 ||E_X W_hat^T||^2 输出MSE)
  Q     (在线): Hadamard旋转 + E6M2 scale search (13候选) + exact微指数
  K     (在线): Hadamard旋转 + E6M2 scale search (13候选) + exact微指数
  V     (在线): 无旋转 + E6M2 scale search (13候选) + exact微指数 +
                 P^T P 的 rho_t token级加权 (对齐 ||P E_V||^2 输出MSE)

核心优化:
  1. exact微指数: 4组合联合搜索, 逐块严格不劣于贪心 (3次量化, 同开销)
  2. E6M2对称窗口: 自适应候选数(大5/中7/小9, Attention固定13), 嵌套不劣
  3. Linear输出加权: 权重用 lambda_j=mean(X_rot^2), 激活用 diag(W_hat^T W_hat)
  4. Attention V加权: rho_t = sum_i P[i,t]^2 来自 P^T P (非 E[V_j^2])
  5. SmoothQuant: alpha扫描{None,0.5}, 校准proxy MSE选择, 无量化时严格等价
  6. P6重排序: Linear alpha选择 (校准集不劣)
  7. Q/K Hadamard防御: head_dim非64倍数时自动禁用

参考:
  [1] HiFloat4 Format for Language Model Inference (arxiv 2602.11287)
  [2] Pretraining LLMs with NVFP4 (arxiv 2509.25149)
  [3] SmoothQuant (arxiv 2211.10438) — 对角平衡
  [4] GPTQ (arxiv 2210.17323) — 二阶信息量化补偿
  [5] BoA (ICML 2025) — attention-aware Hessian
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


def _hif4_dequant(params, shape):
    deq = (params["sign"] * params["mant"] *
           params["scale_lv3"] * params["scale_lv2"] * params["scale_factor"])
    return deq.reshape(shape).to(torch.float32)


def _adaptive_n_candidates(shape):
    numel = 1
    for d in shape:
        numel *= int(d)
    if numel > 4_000_000:
        return 5
    elif numel > 1_000_000:
        return 9
    else:
        return 11


def _e6m2_candidates(target, n_candidates=3):
    target_flat = target.reshape(-1).double()
    idx = torch.searchsorted(_E6M2_TABLE, target_flat)
    half = n_candidates // 2
    idx = idx.clamp(half, len(_E6M2_TABLE) - 1 - half)
    if n_candidates <= 4:
        if n_candidates == 2:
            offsets = torch.tensor([0, 4], dtype=torch.long)
        elif n_candidates == 3:
            offsets = torch.tensor([-1, 0, 4], dtype=torch.long)
        else:
            offsets = torch.tensor([-1, 0, 2, 4], dtype=torch.long)
    else:
        offsets = torch.arange(-half, n_candidates - half, dtype=torch.long)
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


# ======================================================================
# 核心: 带重要性加权的 HiF4 量化
# ----------------------------------------------------------------------

def _quantize_block_given_scale(w, sf, imp=None):
    """Exact 4-combination joint micro-exponent search.

    (lv2=1,lv3=2) and (lv2=2,lv3=1) share total scale 2*sf, so only
    3 distinct quantizations suffice. The exact search enumerates all
    4 (lv2,lv3) combos per sub-group and selects the joint optimum:
      F(a) = sum_g min_b L_g(a, b);  a* = argmin_a F(a);  b_g* = argmin_b L_g(a*, b)
    This is mechanically non-inferior to any single combo (including the old greedy).
    """
    has_imp = imp is not None

    def _mse(dq, ref, dims):
        if has_imp:
            return (imp * (dq - ref) ** 2).sum(dim=dims)
        return ((dq - ref) ** 2).mean(dim=dims)

    # ── 3 quantizations covering all 4 (lv2, lv3) combinations ──
    # q00:  lv2=1, lv3=1, scale = sf
    q00 = (w / sf * 4.0).round().clamp(-7, 7) / 4.0
    dq00 = q00 * sf
    mse00 = _mse(dq00, w, -1)               # (..., 8, 2) per sub-group

    # q_mid: scale = 2*sf  (lv2=1,lv3=2 OR lv2=2,lv3=1)
    q_mid = (w / (sf * 2.0) * 4.0).round().clamp(-7, 7) / 4.0
    dq_mid = q_mid * (sf * 2.0)
    mse_mid = _mse(dq_mid, w, -1)           # (..., 8, 2)

    # q11:  lv2=2, lv3=2, scale = 4*sf
    q11 = (w / (sf * 4.0) * 4.0).round().clamp(-7, 7) / 4.0
    dq11 = q11 * (sf * 4.0)
    mse11 = _mse(dq11, w, -1)               # (..., 8, 2)

    # ── Exact joint search: choose lv2 (per 8-group) ──
    # F(a=0) = sum_g min(mse00, mse_mid);  F(a=1) = sum_g min(mse_mid, mse11)
    F0 = torch.minimum(mse00, mse_mid).sum(dim=-1)   # (..., 8)
    F1 = torch.minimum(mse_mid, mse11).sum(dim=-1)   # (..., 8)
    use_2_lv2 = F1 < F0                               # (..., 8)

    # ── Choose lv3 (per sub-group) given chosen lv2 ──
    b_when_a0 = mse_mid < mse00     # True → lv3=2
    b_when_a1 = mse11 < mse_mid     # True → lv3=2
    use_2_lv3 = torch.where(use_2_lv2.unsqueeze(-1), b_when_a1, b_when_a0)  # (..., 8, 2)

    # ── Select final q/dq: (a=0,b=0)→q00, (a=0,b=1)→q_mid, (a=1,b=0)→q_mid, (a=1,b=1)→q11 ──
    lv3_exp = use_2_lv3.unsqueeze(-1)          # (..., 8, 2, 1)
    q_a0 = torch.where(lv3_exp, q_mid, q00)     # a=0: b=0→q00, b=1→q_mid
    q_a1 = torch.where(lv3_exp, q11, q_mid)    # a=1: b=0→q_mid, b=1→q11
    dq_a0 = torch.where(lv3_exp, dq_mid, dq00)
    dq_a1 = torch.where(lv3_exp, dq11, dq_mid)

    lv2_exp = use_2_lv2.unsqueeze(-1).unsqueeze(-1)  # (..., 8, 1, 1)
    q_final = torch.where(lv2_exp, q_a1, q_a0)
    dq_final = torch.where(lv2_exp, dq_a1, dq_a0)

    sign = torch.sign(q_final)
    mant = q_final.abs()

    scale_lv2 = torch.where(use_2_lv2, 2.0, 1.0)
    scale_lv3 = torch.where(use_2_lv3, 2.0, 1.0)

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
        imp_chunk = importance
        if importance is not None and importance.ndim > 1 and importance.shape[0] == w_fp.shape[0]:
            imp_chunk = importance[start:end]
        results.append(_quantize_hif4_impl(w_fp[start:end], n_candidates, imp_chunk))

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

def _compute_v_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """V token-level importance from P^T P (attention output sensitivity).

    ||P E_V||^2 = tr(E_V^T P^T P E_V) ≈ sum_t rho_t * ||E_V[t,:]||^2
    where rho_t = sum_i P[i,t]^2 (column norm squared of attention matrix).

    For GQA: each KV head g is shared by `group` Q heads; rho_g accumulates
    P^T P contributions from all Q heads in the group.
    """
    group = q_num_heads // kv_num_heads
    scale = 1.0 / math.sqrt(head_dim)

    rho = None
    n_samples = 0

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        cur_seq = q_fp.shape[0]

        if rho is None:
            rho = torch.zeros(kv_num_heads, cur_seq, dtype=torch.float32)
        elif rho.shape[1] != cur_seq:
            break

        q_re = q_fp.reshape(cur_seq, q_num_heads, head_dim).transpose(0, 1)
        k_re = k_fp.reshape(cur_seq, kv_num_heads, head_dim).transpose(0, 1)

        for g in range(kv_num_heads):
            q_group = q_re[g * group:(g + 1) * group]
            k_g = k_re[g:g + 1]
            scores = torch.matmul(q_group, k_g.transpose(-1, -2)) * scale
            attn = torch.softmax(scores, dim=-1)
            rho[g] += (attn ** 2).sum(dim=(0, 1))

        n_samples += 1

    if rho is None:
        rho = torch.ones(kv_num_heads, 1, dtype=torch.float32)
    rho = (rho / max(n_samples, 1)).clamp(min=1e-8)
    return rho


def _compute_qk_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Q/K per-channel importance via diagonal-approx of softmax Jacobian.

    J_i ≈ diag(p_i). Q_imp[i,r] = sum_t K[t,r]^2 * P[i,t]^2 * ||V[t]||^2 / d.
    For GQA: K importance accumulates across all Q heads sharing each KV head.
    """
    group = q_num_heads // kv_num_heads
    scale = 1.0 / math.sqrt(head_dim)

    q_imp = torch.zeros(q_num_heads, head_dim, dtype=torch.float32)
    k_imp = torch.zeros(kv_num_heads, head_dim, dtype=torch.float32)
    n_samples = 0

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        v_fp = _dequant_nvfp4(*sample["v"])
        seq = q_fp.shape[0]

        q_re = q_fp.reshape(seq, q_num_heads, head_dim).transpose(0, 1)
        k_re = k_fp.reshape(seq, kv_num_heads, head_dim).transpose(0, 1)
        v_re = v_fp.reshape(seq, kv_num_heads, head_dim).transpose(0, 1)
        v_nsq = (v_re ** 2).sum(dim=-1)

        for g in range(kv_num_heads):
            k_g = k_re[g]
            v_nsq_g = v_nsq[g]
            k_g_sq = k_g ** 2
            for h in range(g * group, (g + 1) * group):
                q_h = q_re[h]
                scores = torch.matmul(q_h, k_g.transpose(-1, -2)) * scale
                p = torch.softmax(scores, dim=-1)
                p_sq = p ** 2
                q_imp[h] += torch.einsum("tr,it,t->ir", k_g_sq, p_sq, v_nsq_g).mean(dim=0) / head_dim
                k_imp[g] += torch.einsum("it,t,ir->tr", p_sq, v_nsq_g, q_h ** 2).mean(dim=0) / head_dim

        n_samples += 1

    q_imp = (q_imp / max(n_samples, 1)).clamp(min=1e-10)
    k_imp = (k_imp / max(n_samples, 1)).clamp(min=1e-10)
    return q_imp.reshape(q_num_heads * head_dim).contiguous(), k_imp.reshape(kv_num_heads * head_dim).contiguous()


def _eval_attn_mode(calib_qkv_list, q_num_heads, kv_num_heads, head_dim,
                    hadamard, q_imp, k_imp, v_rho, max_samples=1, n_cand=5):
    """Evaluate attention reconstruction MSE for a given mode on calibration data."""
    total_mse = 0.0
    n_eval = 0
    for sample in calib_qkv_list[:max_samples]:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        v_fp = _dequant_nvfp4(*sample["v"])
        seq = q_fp.shape[0]

        q_work = q_fp.clone()
        k_work = k_fp.clone()
        v_work = v_fp.clone()
        if hadamard is not None:
            q_work = _apply_hadamard(q_work, hadamard)
            k_work = _apply_hadamard(k_work, hadamard)

        q_params = _quantize_hif4(q_work, n_candidates=n_cand, importance=q_imp)
        k_params = _quantize_hif4(k_work, n_candidates=n_cand, importance=k_imp)
        v_imp = None
        if v_rho is not None and v_rho.shape[1] == seq:
            v_imp = v_rho.transpose(0, 1).repeat_interleave(head_dim, dim=1).reshape(seq, kv_num_heads * head_dim)
        v_params = _quantize_hif4(v_work, n_candidates=n_cand, importance=v_imp)

        q_hat = _hif4_dequant(q_params, q_work.shape)
        k_hat = _hif4_dequant(k_params, k_work.shape)
        v_hat = _hif4_dequant(v_params, v_work.shape)

        ref_out = _attention(q_fp, k_fp, v_fp, q_num_heads, kv_num_heads, head_dim)
        mode_out = _attention(q_hat, k_hat, v_hat, q_num_heads, kv_num_heads, head_dim)
        total_mse += ((mode_out - ref_out) ** 2).mean().item()
        n_eval += 1
    return total_mse / max(n_eval, 1)


def _attention(q, k, v, q_heads, kv_heads, head_dim):
    """GQA attention (no mask, matching simulate_scoring.py platform behavior)."""
    seq = q.shape[0]
    q_re = q.reshape(seq, q_heads, head_dim).transpose(0, 1)
    k_re = k.reshape(seq, kv_heads, head_dim).transpose(0, 1)
    v_re = v.reshape(seq, kv_heads, head_dim).transpose(0, 1)
    group = q_heads // kv_heads
    k_exp = k_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
    v_exp = v_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
    scores = torch.matmul(q_re, k_exp.transpose(-1, -2)) / math.sqrt(head_dim)
    attn = torch.softmax(scores, dim=-1)
    out = torch.matmul(attn, v_exp)
    return out.transpose(0, 1).reshape(seq, q_heads * head_dim)


# ======================================================================
# 1. Linear: 校准 + 权重量化
# ======================================================================

def hif4_calibration_and_quantize_weight(
    weight_quant: torch.Tensor,
    weight_scale: torch.Tensor,
    calib_activation_list: list,
) -> dict[str, Any]:
    """权重 W (离线): SmoothQuant alpha扫描 + Hadamard旋转 + exact微指数 +
    校准激活 lambda_j 加权。自适应候选数控制时间。"""
    weight_fp = _dequant_nvfp4(weight_quant, weight_scale)
    K = weight_fp.shape[-1]
    H = _random_hadamard(HAD_SIZE, seed=42).to(torch.float32)
    n_final = _adaptive_n_candidates(weight_fp.shape)

    if not calib_activation_list:
        weight_rot = _apply_hadamard(weight_fp, H)
        weight_params = _quantize_hif4(weight_rot, n_candidates=n_final)
        w_hat = _hif4_dequant(weight_params, weight_rot.shape)
        w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)
        return {
            "weight_params": weight_params,
            "activation_state": {
                "hadamard": H.contiguous(),
                "importance": w_diag.contiguous(),
                "smooth_scale": None,
            },
        }

    calib_acts = [_dequant_nvfp4(aq, asc) for aq, asc in calib_activation_list]

    max_act = torch.zeros(K, dtype=torch.float32)
    for act in calib_acts:
        max_act = torch.maximum(max_act, act.abs().amax(dim=0))
    max_w = weight_fp.abs().amax(dim=0).clamp(min=1e-8)

    w_numel = weight_fp.numel()
    if w_numel > 4_000_000:
        alpha_list = (None, 0.5)
    else:
        alpha_list = (None, 0.25, 0.5, 0.75, 1.0)
    n_scan = min(256, weight_fp.shape[0])
    w_scan = weight_fp[:n_scan]
    best_proxy = None
    for alpha in alpha_list:
        if alpha is None:
            D = torch.ones(K, dtype=torch.float32)
        else:
            D = (max_act.clamp(min=1e-8) ** alpha) / (max_w ** (1 - alpha))
            D = D.clamp(min=1e-4, max=1e4)

        w_rot = _apply_hadamard(w_scan * D, H)

        x_sq_sum = torch.zeros(K, dtype=torch.float32)
        total_tokens = 0
        for act in calib_acts:
            act_rot = _apply_hadamard(act * (1.0 / D), H)
            x_sq_sum += (act_rot ** 2).sum(dim=0)
            total_tokens += act.shape[0]
        w_imp = (x_sq_sum / max(total_tokens, 1)).clamp(min=1e-8)

        wp = _quantize_hif4(w_rot, n_candidates=3, importance=w_imp)
        w_hat = _hif4_dequant(wp, w_rot.shape)
        proxy = (w_imp * (w_hat - w_rot) ** 2).sum().item() / n_scan

        if best_proxy is None or proxy < best_proxy[0]:
            best_proxy = (proxy, alpha, D, w_imp)

    best_alpha = best_proxy[1]
    D = best_proxy[2]
    w_imp = best_proxy[3]

    w_smooth = weight_fp * D
    w_rot = _apply_hadamard(w_smooth, H)
    weight_params = _quantize_hif4(w_rot, n_candidates=n_final, importance=w_imp)

    w_hat = _hif4_dequant(weight_params, w_rot.shape)
    w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)

    smooth_D = D if best_alpha is not None else None

    activation_state = {
        "hadamard": H.contiguous(),
        "importance": w_diag.contiguous(),
        "smooth_scale": smooth_D.contiguous() if smooth_D is not None else None,
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
    """激活 A (在线): SmoothQuant D^-1 + Hadamard旋转 + exact微指数 +
    W_hat^T W_hat 加权。自适应候选数。"""
    act_fp = _dequant_nvfp4(activation_quant, activation_scale)

    if isinstance(activation_state, dict):
        D = activation_state.get("smooth_scale")
        if D is not None:
            act_fp = act_fp * (1.0 / D.to(torch.float32))

        H = activation_state.get("hadamard")
        if H is not None:
            act_fp = _apply_hadamard(act_fp, H.to(torch.float32))

        imp = activation_state.get("importance")
        if imp is not None and int(imp.shape[-1]) != int(act_fp.shape[-1]):
            imp = None
    else:
        imp = None

    return _quantize_hif4(act_fp, n_candidates=_adaptive_n_candidates(act_fp.shape), importance=imp)


# ======================================================================
# 3. Attention: 校准
# ======================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Attention calibration with mode selection (non-inferior).

    Computes V importance (rho) and Q/K Jacobian importance, then selects
    the best mode by calibration attention MSE.  Non-baseline modes require
    ≥10% lower MSE than the baseline to be selected (safety margin).
    """
    rho = _compute_v_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim)
    calib_seq = rho.shape[1]
    rho_mean = rho.mean(dim=1).repeat_interleave(head_dim).contiguous()

    q_imp_flat, k_imp_flat = _compute_qk_importance(
        calib_qkv_list, q_num_heads, kv_num_heads, head_dim
    )

    H = None
    if head_dim % HAD_SIZE == 0:
        H = _random_hadamard(HAD_SIZE, seed=123).to(torch.float32).contiguous()

    q_hidden = q_num_heads * head_dim
    kv_hidden = kv_num_heads * head_dim
    q_imp_valid = int(q_imp_flat.shape[-1]) == q_hidden
    k_imp_valid = int(k_imp_flat.shape[-1]) == kv_hidden

    modes = []
    if H is not None:
        modes.append({"hadamard": H, "q_imp": None, "k_imp": None, "name": "had"})
    if q_imp_valid and k_imp_valid:
        modes.append({"hadamard": None, "q_imp": q_imp_flat, "k_imp": k_imp_flat, "name": "jac"})
    if not modes:
        modes.append({"hadamard": None, "q_imp": None, "k_imp": None, "name": "plain"})

    best_mode = modes[0]
    calib_seq_len = calib_qkv_list[0]["q"][0].shape[0] if calib_qkv_list else 0
    do_mode_eval = calib_seq_len <= 32 and q_hidden <= 512

    if do_mode_eval:
        best_mse = float("inf")
        baseline_mse = None
        for mode in modes:
            try:
                mse = _eval_attn_mode(
                    calib_qkv_list, q_num_heads, kv_num_heads, head_dim,
                    mode["hadamard"], mode["q_imp"], mode["k_imp"], rho
                )
            except Exception:
                continue
            is_baseline = mode["name"] in ("had", "plain")
            if is_baseline:
                baseline_mse = mse
                best_mse = mse
                best_mode = mode
            elif baseline_mse is not None and mse < baseline_mse * 0.90:
                best_mse = mse
                best_mode = mode
            elif baseline_mse is None and mse < best_mse:
                best_mse = mse
                best_mode = mode

    q_state = {"hadamard": best_mode["hadamard"], "importance": best_mode["q_imp"]}
    k_state = {"hadamard": best_mode["hadamard"], "importance": best_mode["k_imp"]}
    v_state = {
        "rho": rho.contiguous(),
        "rho_mean": rho_mean,
        "calib_seq": calib_seq,
    }

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
    """Q (online): Hadamard (if in state) + E6M2 scale search + optional Jacobian importance."""
    q_fp = _dequant_nvfp4(q_quant, q_scale)

    imp = None
    if isinstance(q_state, dict):
        H = q_state.get("hadamard")
        imp = q_state.get("importance")
    else:
        H = None
    if H is not None:
        q_fp = _apply_hadamard(q_fp, H.to(torch.float32))
    if imp is not None and int(imp.shape[-1]) == int(q_fp.shape[-1]):
        pass
    else:
        imp = None

    return _quantize_hif4(q_fp, n_candidates=9, importance=imp)


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
    """K (online): Hadamard (if in state) + E6M2 scale search + optional Jacobian importance."""
    k_fp = _dequant_nvfp4(k_quant, k_scale)

    imp = None
    if isinstance(k_state, dict):
        H = k_state.get("hadamard")
        imp = k_state.get("importance")
    else:
        H = None
    if H is not None:
        k_fp = _apply_hadamard(k_fp, H.to(torch.float32))
    if imp is not None and int(imp.shape[-1]) == int(k_fp.shape[-1]):
        pass
    else:
        imp = None

    return _quantize_hif4(k_fp, n_candidates=9, importance=imp)


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
    """V (在线): 无旋转 + E6M2 scale search (13候选) +
    P^T P 的 rho_t 作为 token 级 importance。"""
    v_fp = _dequant_nvfp4(v_quant, v_scale)

    imp = None
    if isinstance(v_state, dict):
        rho = v_state.get("rho")
        calib_seq = v_state.get("calib_seq")
        kv_hidden = kv_num_heads * head_dim
        test_seq = v_fp.shape[0]

        if rho is not None and calib_seq is not None and test_seq == calib_seq:
            rho = rho.to(torch.float32)
            imp = rho.transpose(0, 1).repeat_interleave(head_dim, dim=1)
            if int(imp.shape[-1]) != int(v_fp.shape[-1]):
                imp = None
        else:
            rho_mean = v_state.get("rho_mean")
            if rho_mean is not None and int(rho_mean.shape[-1]) == kv_hidden:
                imp = rho_mean.to(torch.float32)

    return _quantize_hif4(v_fp, n_candidates=9, importance=imp)
