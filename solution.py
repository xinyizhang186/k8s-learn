"""
HiF4 solution.py — NVFP4 → HiF4 量化转换 (输出敏感度优化, 严格无 A@W)

针对赛题要求"分别对权重、激活(A和Attention Q/K/V)设计最优量化算法"：

  权重 W (离线): SmoothQuant alpha扫描 + Hadamard旋转 + exact微指数 +
                 校准激活 lambda_j 加权 (对齐 ||X E_W^T||^2 输出MSE)
  激活 A (在线): SmoothQuant D^-1 + Hadamard旋转 + exact微指数 +
                 diag(W_hat^T W_hat) 加权 (对角协方差近似下精确最优)
  Q     (在线): Hadamard/Jacobian 模式选择 + Q/K SmoothQuant 平衡 +
                exact微指数 (Hadamard模式: plain MSE; Jacobian模式: H_Q曲率加权)
  K     (在线): 同 Q (H_K 曲率加权)
  V     (在线): 无旋转 + exact微指数 + P^T P 的 rho_t token级加权

核心优化:
  1. exact微指数: 4组合联合搜索, 逐块严格不劣于贪心 (3次量化, 同开销)
  2. E6M2对称窗口: 自适应候选数(大5/中7/小9, Attention固定13), 嵌套不劣
  3. Linear输出加权: 权重用 lambda_j=mean(X_rot^2), 激活用 diag(W_hat^T W_hat)
  4. Attention V加权: rho_t = sum_i P[i,t]^2 来自 P^T P (非 E[V_j^2])
  5. SmoothQuant: Linear alpha扫描{None,0.5}, Q/K alpha=0.5, 校准proxy MSE选择
  6. Q/K Jacobian曲率: H_Q=K^T G_i K/d, H_K=sum_i G_i[t,t]Q[i,r]^2/d (softmax Jacobian)
  7. Q/K SmoothQuant平衡: Q'=Q/D_g, K'=K*D_g => Q'K'^T=QK^T (logits不变)
  8. Attention模式选择: {Hadamard, Jacobian} x {平衡on/off} 校准attn MSE选最优
  9. Q/K Hadamard防御: head_dim非64倍数时自动禁用

严格无 A@W 约束:
  - 不计算任何形式的 A@W (含校准数据上的 X@W^T)
  - Linear: 用 Gram 对角 diag(X^TX) 等价计算输出MSE (tr(E_W C_X E_W^T))
  - Attention: 仅 Q@K^T (attention scores), 不涉及 Linear A@W
  - 动态激活: 对角协方差近似下 importance 加权即精确最优, 无需 A@W 候选重排序

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
    return _hadamard_sylvester(n)


def _random_orthogonal(n: int, seed: int = 42) -> torch.Tensor:
    g = torch.Generator().manual_seed(seed)
    A = torch.randn(n, n, generator=g, dtype=torch.float64)
    Q, R = torch.linalg.qr(A)
    signs = torch.sign(torch.diagonal(R))
    return (Q * signs.unsqueeze(0)).to(torch.float32)


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
        return 7
    else:
        return 9


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


def _compute_qk_jacobian_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim, max_seq=256):
    """Q/K Jacobian curvature importance from softmax Jacobian (no A@W).

    For each head h:
      G_i = J_i V V^T J_i,  J_i = diag(p_i) - p_i p_i^T  (softmax Jacobian)
      H_Q[h,i,r] = diag(K^T G_i K)[r] / d  = ||row r of (V^T J_i K)||^2 / d
      H_K[h,t,r] = (sum_i G_i[t,t] * Q[i,r]^2) / d

    GQA: K importance accumulates over Q heads sharing the same KV head.
    Returns (q_imp[num_heads, seq, d], k_imp[kv_num_heads, seq, d], calib_seq).
    """
    group = q_num_heads // kv_num_heads
    scale = 1.0 / math.sqrt(head_dim)

    q_imp_total = None
    k_imp_total = None
    calib_seq = 0
    n_samples = 0

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        v_fp = _dequant_nvfp4(*sample["v"])
        seq = q_fp.shape[0]

        if seq > max_seq:
            idx = torch.randperm(seq)[:max_seq]
            q_fp = q_fp[idx]
            k_fp = k_fp[idx]
            v_fp = v_fp[idx]
            seq = max_seq

        if q_imp_total is None:
            calib_seq = seq
            q_imp_total = torch.zeros(q_num_heads, seq, head_dim, dtype=torch.float32)
            k_imp_total = torch.zeros(kv_num_heads, seq, head_dim, dtype=torch.float32)
        elif seq != calib_seq:
            continue

        q_re = q_fp.reshape(seq, q_num_heads, head_dim).transpose(0, 1)
        k_re = k_fp.reshape(seq, kv_num_heads, head_dim).transpose(0, 1)
        v_re = v_fp.reshape(seq, kv_num_heads, head_dim).transpose(0, 1)

        for g in range(kv_num_heads):
            k_g = k_re[g]
            v_g = v_re[g]

            for h_in_g in range(group):
                h = g * group + h_in_g
                q_h = q_re[h]

                scores = torch.matmul(q_h, k_g.transpose(-1, -2)) * scale
                P = torch.softmax(scores, dim=-1)

                # A_i = V^T J_i K = (V*p_i).T @ K - outer(V^T p_i, p_i^T K)
                V_weighted = v_g.unsqueeze(0) * P.unsqueeze(-1)
                Term1 = torch.matmul(V_weighted.transpose(1, 2), k_g)

                VP = torch.matmul(v_g.t(), P)
                PK = torch.matmul(P, k_g)
                Term2 = VP.t().unsqueeze(-1) * PK.unsqueeze(1)

                A = Term1 - Term2
                q_imp_total[h] += (A ** 2).sum(dim=-1) / head_dim

                # G_i[t,t] = p_i[t]^2 * ||V[t] - V_bar_i||^2
                V_bar = torch.matmul(P, v_g)
                V_diff = v_g.unsqueeze(0) - V_bar.unsqueeze(1)
                V_diff_norm = (V_diff ** 2).sum(dim=-1)
                weight_it = (P ** 2) * V_diff_norm
                k_imp_total[g] += torch.matmul(weight_it.t(), q_h ** 2) / head_dim

        n_samples += 1

    if q_imp_total is None or n_samples == 0:
        return None, None, 0

    q_imp_total /= n_samples
    k_imp_total /= n_samples
    return q_imp_total, k_imp_total, calib_seq


def _compute_qk_smooth_scale(calib_qkv_list, q_num_heads, kv_num_heads, head_dim, alpha=0.5):
    """Q/K SmoothQuant diagonal D_g per KV head group (no A@W).

    D_g[r] = max|Q_g[:,r]|^alpha / max|K_g[:,r]|^(1-alpha)
    Q' = Q / D_q_flat,  K' = K * D_k_flat  =>  Q' K'^T = Q K^T (logits unchanged).
    """
    group = q_num_heads // kv_num_heads

    if not calib_qkv_list:
        return None, None

    max_q = torch.zeros(q_num_heads, head_dim, dtype=torch.float32)
    max_k = torch.zeros(kv_num_heads, head_dim, dtype=torch.float32)

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        seq = q_fp.shape[0]

        q_re = q_fp.reshape(seq, q_num_heads, head_dim).transpose(0, 1)
        k_re = k_fp.reshape(seq, kv_num_heads, head_dim).transpose(0, 1)

        max_q = torch.maximum(max_q, q_re.abs().amax(dim=1))
        max_k = torch.maximum(max_k, k_re.abs().amax(dim=1))

    max_q_group = max_q.reshape(kv_num_heads, group, head_dim).amax(dim=1)

    D_g = (max_q_group.clamp(min=1e-8) ** alpha) / (max_k.clamp(min=1e-8) ** (1 - alpha))
    D_g = D_g.clamp(min=1e-4, max=1e4)

    D_q_flat = D_g.repeat_interleave(group, dim=0).reshape(-1).contiguous()
    D_k_flat = D_g.reshape(-1).contiguous()

    return D_q_flat, D_k_flat


def _evaluate_attention_mode(calib_qkv_list, mode, q_imp, k_imp,
                             D_q_flat, D_k_flat, q_num_heads, kv_num_heads,
                             head_dim, rho, H):
    """Evaluate calibration attention MSE for a given mode (no A@W).

    Mode dict: {"hadamard": bool, "jacobian": bool, "balancing": bool}.
    Returns mean MSE across calibration samples (lower is better).
    Subsamples tokens to max_eval_seq for speed on large sequences.
    """
    q_hidden = q_num_heads * head_dim
    kv_hidden = kv_num_heads * head_dim
    calib_seq_imp = q_imp.shape[1] if q_imp is not None else 0
    calib_seq_rho = rho.shape[1] if rho is not None else 0

    total_mse = 0.0
    n_samples = 0

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        v_fp = _dequant_nvfp4(*sample["v"])
        seq = q_fp.shape[0]

        if seq > 256:
            idx = torch.randperm(seq)[:256]
            q_fp = q_fp[idx]
            k_fp = k_fp[idx]
            v_fp = v_fp[idx]
            seq = 256

        if mode["balancing"] and D_q_flat is not None:
            q_proc = q_fp / D_q_flat.to(torch.float32)
            k_proc = k_fp * D_k_flat.to(torch.float32)
        else:
            q_proc = q_fp
            k_proc = k_fp
        v_proc = v_fp

        if mode["hadamard"] and H is not None:
            q_proc = _apply_hadamard(q_proc, H)
            k_proc = _apply_hadamard(k_proc, H)

        q_imp_mode = None
        k_imp_mode = None
        if mode["jacobian"] and q_imp is not None:
            if seq == calib_seq_imp:
                q_imp_flat = q_imp.transpose(0, 1).reshape(seq, q_hidden)
                k_imp_flat = k_imp.transpose(0, 1).reshape(seq, kv_hidden)
            else:
                q_imp_flat = q_imp.mean(dim=1).reshape(q_hidden)
                k_imp_flat = k_imp.mean(dim=1).reshape(kv_hidden)

            if mode["balancing"] and D_q_flat is not None:
                q_imp_flat = q_imp_flat * (D_q_flat ** 2)
                k_imp_flat = k_imp_flat / (D_k_flat ** 2 + 1e-12)

            q_imp_mode = q_imp_flat.to(torch.float32)
            k_imp_mode = k_imp_flat.to(torch.float32)

        v_imp_mode = None
        if rho is not None:
            if seq == calib_seq_rho:
                v_imp_mode = rho.transpose(0, 1).repeat_interleave(head_dim, dim=1)
                if v_imp_mode.shape[-1] != kv_hidden:
                    v_imp_mode = None
            else:
                rho_mean = rho.mean(dim=1).repeat_interleave(head_dim)
                if rho_mean.shape[-1] == kv_hidden:
                    v_imp_mode = rho_mean

        q_params = _quantize_hif4(q_proc, n_candidates=5, importance=q_imp_mode)
        k_params = _quantize_hif4(k_proc, n_candidates=5, importance=k_imp_mode)
        v_params = _quantize_hif4(v_proc, n_candidates=5, importance=v_imp_mode)

        q_hat = _hif4_dequant(q_params, q_proc.shape)
        k_hat = _hif4_dequant(k_params, k_proc.shape)
        v_hat = _hif4_dequant(v_params, v_proc.shape)

        ref_out = _attention(q_fp, k_fp, v_fp, q_num_heads, kv_num_heads, head_dim)
        player_out = _attention(q_hat, k_hat, v_hat, q_num_heads, kv_num_heads, head_dim)

        total_mse += ((player_out - ref_out) ** 2).mean().item()
        n_samples += 1

    return total_mse / max(n_samples, 1)


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

def _apply_block_gptq(weight_params, w_rot, calib_acts, D, H):
    """Block-diagonal GPTQ residual compensation (no A@W, uses Gram X^T X).

    For each 64-channel block:
    1. Compute block Gram C_b = X_rot[:,b]^T @ X_rot[:,b] / n
    2. Fix scales (sf, lv2, lv3) from standard quantization
    3. Batched GPTQ: sequential quantize + update remaining columns
    4. Per-block full-covariance loss comparison; keep lower (non-inferior)

    Loss: L = tr(E_b C_b E_b^T) = (C_b * (E_b^T @ E_b)).sum()
    """
    out_features, K = w_rot.shape
    num_blocks = K // BLK_SIZE
    if num_blocks == 0 or out_features == 0:
        return weight_params

    # Compute block-diagonal Gram from rotated+smoothed calibration activations
    gram_blocks = torch.zeros(num_blocks, BLK_SIZE, BLK_SIZE, dtype=torch.float32)
    total_tokens = 0
    for act in calib_acts:
        act_s = act * (1.0 / D) if D is not None else act
        act_rot = _apply_hadamard(act_s, H) if H is not None else act_s
        for b in range(num_blocks):
            block = act_rot[:, b * BLK_SIZE:(b + 1) * BLK_SIZE]
            gram_blocks[b] += block.t() @ block
        total_tokens += act.shape[0]
    gram_blocks = (gram_blocks / max(total_tokens, 1)).to(torch.float32)

    # Extract total_scale from params (shapes: [out, num_blocks, ...])
    sf = weight_params["scale_factor"].squeeze(-1).squeeze(-1).squeeze(-1)       # [out, nb]
    lv2 = weight_params["scale_lv2"].squeeze(-1).squeeze(-1)                     # [out, nb, 8]
    lv3 = weight_params["scale_lv3"].squeeze(-1)                                  # [out, nb, 8, 2]

    # total_scale[i, b, j] = sf[i,b] * lv2[i,b,j//8] * lv3[i,b,j//8,(j%8)//4]
    lv2_exp = lv2.repeat_interleave(8, dim=-1)                                    # [out, nb, 64]
    lv3_exp = lv3.repeat_interleave(4, dim=-1).reshape(out_features, num_blocks, BLK_SIZE)
    total_scale = (sf.unsqueeze(-1) * lv2_exp * lv3_exp).to(torch.float32)         # [out, nb, 64]

    # Reshape weight: [out, K] -> [out, num_blocks, BLK_SIZE]
    W = w_rot.reshape(out_features, num_blocks, BLK_SIZE).clone()

    # Standard dequant for comparison
    w_hat = _hif4_dequant(weight_params, w_rot.shape)
    E_std = (w_hat - w_rot).reshape(out_features, num_blocks, BLK_SIZE)            # [out, nb, 64]

    # Damped Gram for stability (shared across out rows)
    gram_diag = gram_blocks.diagonal(dim1=-2, dim2=-1)                            # [nb, 64]
    damp = 0.01 * gram_diag.mean(dim=-1, keepdim=True).unsqueeze(-1)              # [nb, 1, 1]
    gram_damped = gram_blocks + damp * torch.eye(BLK_SIZE, dtype=torch.float32).unsqueeze(0)

    # Batched GPTQ: process all (out, blocks) simultaneously, 64 steps
    q = torch.zeros_like(W)
    for j in range(BLK_SIZE):
        ts_j = total_scale[:, :, j]                                               # [out, nb]
        col = W[:, :, j]                                                          # [out, nb]
        q_j = (col / ts_j * 4.0).round().clamp(-7, 7) / 4.0 * ts_j
        q[:, :, j] = q_j
        if j < BLK_SIZE - 1:
            err = q_j - col                                                       # [out, nb]
            h_row = gram_damped[:, j, j + 1:]                                     # [nb, 63-j]
            h_diag = gram_damped[:, j, j].clamp(min=1e-8)                         # [nb]
            ratio = (h_row / h_diag.unsqueeze(-1)).unsqueeze(0)                   # [1, nb, 63-j]
            W[:, :, j + 1:] -= err.unsqueeze(-1) * ratio                          # [out, nb, 63-j]

    # Full-covariance loss comparison
    E_gptq = q - w_rot.reshape(out_features, num_blocks, BLK_SIZE)                # [out, nb, 64]

    # loss_b = (gram_b * (E_b^T @ E_b)).sum(); permute to [nb, out, 64] for bmm
    E_std_perm = E_std.permute(1, 0, 2)                                          # [nb, out, 64]
    E_gptq_perm = E_gptq.permute(1, 0, 2)                                       # [nb, out, 64]
    std_loss = (gram_blocks * torch.bmm(E_std_perm.transpose(1, 2), E_std_perm)).sum(dim=(1, 2))
    gptq_loss = (gram_blocks * torch.bmm(E_gptq_perm.transpose(1, 2), E_gptq_perm)).sum(dim=(1, 2))

    use_gptq = gptq_loss < std_loss * 0.90                                      # [nb]

    # Convert GPTQ q to sign/mant for blocks where GPTQ wins
    q_scaled = (q / total_scale * 4.0).round().clamp(-7, 7) / 4.0                # [out, nb, 64]
    gptq_sign = torch.sign(q_scaled).reshape(out_features, num_blocks, 8, 2, 4)
    gptq_mant = q_scaled.abs().reshape(out_features, num_blocks, 8, 2, 4)

    sign_param = weight_params["sign"].clone()
    mant_param = weight_params["mant"].clone()

    for b in range(num_blocks):
        if use_gptq[b]:
            sign_param[:, b] = gptq_sign[:, b]
            mant_param[:, b] = gptq_mant[:, b]

    weight_params = dict(weight_params)
    weight_params["sign"] = sign_param.contiguous()
    weight_params["mant"] = mant_param.contiguous()

    return weight_params


def _compute_gram_W(w_hat, K):
    """Block-diagonal of W_hat^T @ W_hat (no A@W, uses weight Gram).

    For activation GPTQ: ||E_X W_hat^T||^2 = tr(E_X gram_W E_X^T)
    """
    num_blocks = K // BLK_SIZE
    if num_blocks == 0 or w_hat.shape[0] == 0 or K % BLK_SIZE != 0:
        return None
    w_blocks = w_hat.reshape(-1, num_blocks, BLK_SIZE).permute(1, 0, 2)  # [nb, out, 64]
    return torch.bmm(w_blocks.transpose(1, 2), w_blocks).to(torch.float32)  # [nb, 64, 64]


def _apply_activation_gptq(std_params, act_fp, gram_W):
    """GPTQ for activation using weight Gram (no A@W).

    Fixes scales from standard quantization, then sequentially quantizes
    and compensates along correlated weight channels.
    Minimizes ||E_X W_hat^T||^2 = tr(E_X gram_W E_X^T) exactly.
    Per-block loss comparison keeps standard when GPTQ doesn't help.
    """
    seq, K = act_fp.shape
    num_blocks = K // BLK_SIZE
    if num_blocks == 0 or seq == 0 or gram_W is None:
        return std_params

    sf = std_params["scale_factor"].squeeze(-1).squeeze(-1).squeeze(-1)       # [seq, nb]
    lv2 = std_params["scale_lv2"].squeeze(-1).squeeze(-1)                     # [seq, nb, 8]
    lv3 = std_params["scale_lv3"].squeeze(-1)                                  # [seq, nb, 8, 2]

    lv2_exp = lv2.repeat_interleave(8, dim=-1)                                 # [seq, nb, 64]
    lv3_exp = lv3.repeat_interleave(4, dim=-1).reshape(seq, num_blocks, BLK_SIZE)
    total_scale = (sf.unsqueeze(-1) * lv2_exp * lv3_exp).to(torch.float32)    # [seq, nb, 64]

    X = act_fp.reshape(seq, num_blocks, BLK_SIZE).clone()

    x_hat_std = _hif4_dequant(std_params, act_fp.shape)
    E_std = (x_hat_std - act_fp).reshape(seq, num_blocks, BLK_SIZE)

    gram_diag = gram_W.diagonal(dim1=-2, dim2=-1)
    damp = 0.01 * gram_diag.mean(dim=-1, keepdim=True).unsqueeze(-1)
    gram_damped = gram_W + damp * torch.eye(BLK_SIZE, dtype=torch.float32).unsqueeze(0)

    q = torch.zeros_like(X)
    for j in range(BLK_SIZE):
        ts_j = total_scale[:, :, j]
        col = X[:, :, j]
        q_j = (col / ts_j * 4.0).round().clamp(-7, 7) / 4.0 * ts_j
        q[:, :, j] = q_j
        if j < BLK_SIZE - 1:
            err = q_j - col
            h_row = gram_damped[:, j, j + 1:]
            h_diag = gram_damped[:, j, j].clamp(min=1e-8)
            ratio = (h_row / h_diag.unsqueeze(-1)).unsqueeze(0)
            X[:, :, j + 1:] -= err.unsqueeze(-1) * ratio

    E_gptq = q - act_fp.reshape(seq, num_blocks, BLK_SIZE)

    E_std_perm = E_std.permute(1, 0, 2)
    E_gptq_perm = E_gptq.permute(1, 0, 2)
    std_loss = (gram_W * torch.bmm(E_std_perm.transpose(1, 2), E_std_perm)).sum(dim=(1, 2))
    gptq_loss = (gram_W * torch.bmm(E_gptq_perm.transpose(1, 2), E_gptq_perm)).sum(dim=(1, 2))

    use_gptq = gptq_loss < std_loss * 0.90

    q_scaled = (q / total_scale * 4.0).round().clamp(-7, 7) / 4.0
    gptq_sign = torch.sign(q_scaled).reshape(seq, num_blocks, 8, 2, 4)
    gptq_mant = q_scaled.abs().reshape(seq, num_blocks, 8, 2, 4)

    sign_param = std_params["sign"].clone()
    mant_param = std_params["mant"].clone()

    for b in range(num_blocks):
        if use_gptq[b]:
            sign_param[:, b] = gptq_sign[:, b]
            mant_param[:, b] = gptq_mant[:, b]

    result = dict(std_params)
    result["sign"] = sign_param.contiguous()
    result["mant"] = mant_param.contiguous()
    return result


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
        gram_W = _compute_gram_W(w_hat, K)
        return {
            "weight_params": weight_params,
            "activation_state": {
                "hadamard": H.contiguous(),
                "importance": w_diag.contiguous(),
                "smooth_scale": None,
                "gram_W": gram_W.contiguous() if gram_W is not None else None,
            },
        }

    calib_acts = [_dequant_nvfp4(aq, asc) for aq, asc in calib_activation_list]

    max_act = torch.zeros(K, dtype=torch.float32)
    for act in calib_acts:
        max_act = torch.maximum(max_act, act.abs().amax(dim=0))
    max_w = weight_fp.abs().amax(dim=0).clamp(min=1e-8)

    # Scan (rotation seed, alpha), select by weighted recon MSE proxy
    n_scan = min(256, weight_fp.shape[0])
    w_scan = weight_fp[:n_scan]
    best_proxy = None
    for rot_seed in [None, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
        if rot_seed is None:
            H = _hadamard_sylvester(HAD_SIZE).to(torch.float32)
        else:
            H = _random_orthogonal(HAD_SIZE, seed=rot_seed)
        for alpha in (None, 0.25, 0.5, 0.75, 1.0):
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
                best_proxy = (proxy, alpha, D, w_imp, H)

    best_alpha = best_proxy[1]
    D = best_proxy[2]
    w_imp = best_proxy[3]
    H = best_proxy[4]
    smooth_D = D if best_alpha is not None else None

    w_smooth = weight_fp * D
    w_rot = _apply_hadamard(w_smooth, H)
    weight_params = _quantize_hif4(w_rot, n_candidates=n_final, importance=w_imp)

    # Block-GPTQ: full-covariance residual compensation (no A@W, uses Gram X^T X)
    if K % BLK_SIZE == 0 and weight_fp.shape[0] > 0:
        weight_params = _apply_block_gptq(weight_params, w_rot, calib_acts, smooth_D, H)

    w_hat = _hif4_dequant(weight_params, w_rot.shape)
    w_diag = (w_hat ** 2).sum(dim=0).clamp(min=1e-8)
    gram_W = _compute_gram_W(w_hat, K)

    activation_state = {
        "hadamard": H.contiguous(),
        "importance": w_diag.contiguous(),
        "smooth_scale": smooth_D.contiguous() if smooth_D is not None else None,
        "gram_W": gram_W.contiguous() if gram_W is not None else None,
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
    """激活 A (在线): SmoothQuant + Hadamard + exact微指数 + 激活GPTQ (无 A@W).

    标准量化后用权重Gram做GPTQ补偿, per-blockloss比较保留更优者。
    ||E_X W_hat^T||^2 = tr(E_X gram_W E_X^T), gram_W=block-diag(W_hat^T W_hat)。
    """
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

        gram_W = activation_state.get("gram_W")
    else:
        imp = None
        gram_W = None

    std_params = _quantize_hif4(act_fp, n_candidates=_adaptive_n_candidates(act_fp.shape), importance=imp)

    if gram_W is not None and int(act_fp.shape[-1]) % BLK_SIZE == 0:
        std_params = _apply_activation_gptq(std_params, act_fp, gram_W)

    return std_params


# ======================================================================
# 3. Attention: 校准
# ======================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Attention校准 (严格无 A@W):
    V:   P^T P 的 rho_t token 级 importance
    Q/K: Hadamard/Jacobian 模式选择 + Q/K SmoothQuant 平衡
         候选集含旧方案 (Hadamard plain) => 校准集机械性不劣"""
    rho = _compute_v_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim)
    calib_seq_rho = rho.shape[1] if rho is not None else 0
    rho_mean = rho.mean(dim=1).repeat_interleave(head_dim).contiguous() if rho is not None else None

    H = None
    if head_dim % HAD_SIZE == 0:
        H = _random_hadamard(HAD_SIZE, seed=123).to(torch.float32).contiguous()

    D_q_flat, D_k_flat = _compute_qk_smooth_scale(
        calib_qkv_list, q_num_heads, kv_num_heads, head_dim, alpha=0.5)

    q_imp, k_imp, calib_seq_jac = None, None, 0
    if calib_qkv_list:
        q_imp, k_imp, calib_seq_jac = _compute_qk_jacobian_importance(
            calib_qkv_list, q_num_heads, kv_num_heads, head_dim, max_seq=256)

    modes = []
    if H is not None:
        modes.append({"hadamard": True, "jacobian": False, "balancing": False})
        modes.append({"hadamard": True, "jacobian": False, "balancing": True})
    if q_imp is not None:
        modes.append({"hadamard": False, "jacobian": True, "balancing": False})
        modes.append({"hadamard": False, "jacobian": True, "balancing": True})
    if not modes:
        modes.append({"hadamard": False, "jacobian": False, "balancing": False})

    eval_qkv_list = calib_qkv_list[:3] if len(calib_qkv_list) > 3 else calib_qkv_list
    best_mode = modes[0]
    if len(modes) > 1 and eval_qkv_list:
        best_mse = float("inf")
        for mode in modes:
            mse = _evaluate_attention_mode(
                eval_qkv_list, mode, q_imp, k_imp, D_q_flat, D_k_flat,
                q_num_heads, kv_num_heads, head_dim, rho, H)
            if mse < best_mse:
                best_mse = mse
                best_mode = mode

    use_hadamard = best_mode["hadamard"] and H is not None
    use_jacobian = best_mode["jacobian"] and q_imp is not None
    use_balancing = best_mode["balancing"] and D_q_flat is not None

    q_state = {}
    k_state = {}

    if use_hadamard:
        q_state["hadamard"] = H
        k_state["hadamard"] = H

    if use_jacobian:
        q_state["importance_full"] = q_imp.contiguous()
        q_state["importance_mean"] = q_imp.mean(dim=1).reshape(-1).contiguous()
        k_state["importance_full"] = k_imp.contiguous()
        k_state["importance_mean"] = k_imp.mean(dim=1).reshape(-1).contiguous()
        q_state["calib_seq"] = calib_seq_jac
        k_state["calib_seq"] = calib_seq_jac

    if use_balancing:
        q_state["smooth_scale"] = D_q_flat.contiguous()
        k_state["smooth_scale"] = D_k_flat.contiguous()

    v_state = {
        "rho": rho.contiguous() if rho is not None else None,
        "rho_mean": rho_mean,
        "calib_seq": calib_seq_rho,
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
    """Q (在线): 模式依赖 (Hadamard 或 Jacobian) + 可选 Q/K 平衡 (无 A@W)."""
    q_fp = _dequant_nvfp4(q_quant, q_scale)
    q_hidden = q_num_heads * head_dim

    if not isinstance(q_state, dict):
        return _quantize_hif4(q_fp, n_candidates=13)

    D = q_state.get("smooth_scale")
    if D is not None and int(D.shape[-1]) == q_hidden:
        q_fp = q_fp / D.to(torch.float32)

    H = q_state.get("hadamard")
    if H is not None:
        q_fp = _apply_hadamard(q_fp, H.to(torch.float32))
        return _quantize_hif4(q_fp, n_candidates=13)

    imp_full = q_state.get("importance_full")
    imp_mean = q_state.get("importance_mean")
    calib_seq = q_state.get("calib_seq", 0)
    test_seq = q_fp.shape[0]

    imp = None
    if imp_full is not None and test_seq == calib_seq:
        imp = imp_full.transpose(0, 1).reshape(test_seq, q_hidden).to(torch.float32)
    elif imp_mean is not None and int(imp_mean.shape[-1]) == q_hidden:
        imp = imp_mean.to(torch.float32)

    if imp is not None and D is not None:
        imp = imp * (D.to(torch.float32) ** 2)

    return _quantize_hif4(q_fp, n_candidates=13, importance=imp)


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
    """K (在线): 模式依赖 (Hadamard 或 Jacobian) + 可选 Q/K 平衡 (无 A@W)."""
    k_fp = _dequant_nvfp4(k_quant, k_scale)
    kv_hidden = kv_num_heads * head_dim

    if not isinstance(k_state, dict):
        return _quantize_hif4(k_fp, n_candidates=13)

    D = k_state.get("smooth_scale")
    if D is not None and int(D.shape[-1]) == kv_hidden:
        k_fp = k_fp * D.to(torch.float32)

    H = k_state.get("hadamard")
    if H is not None:
        k_fp = _apply_hadamard(k_fp, H.to(torch.float32))
        return _quantize_hif4(k_fp, n_candidates=13)

    imp_full = k_state.get("importance_full")
    imp_mean = k_state.get("importance_mean")
    calib_seq = k_state.get("calib_seq", 0)
    test_seq = k_fp.shape[0]

    imp = None
    if imp_full is not None and test_seq == calib_seq:
        imp = imp_full.transpose(0, 1).reshape(test_seq, kv_hidden).to(torch.float32)
    elif imp_mean is not None and int(imp_mean.shape[-1]) == kv_hidden:
        imp = imp_mean.to(torch.float32)

    if imp is not None and D is not None:
        imp = imp / (D.to(torch.float32) ** 2 + 1e-12)

    return _quantize_hif4(k_fp, n_candidates=13, importance=imp)


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

    return _quantize_hif4(v_fp, n_candidates=13, importance=imp)
