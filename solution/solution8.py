"""
HiF4 solution.py — NVFP4 → HiF4 量化转换 (V8: Attention输出损失协同优化)

针对赛题要求"分别对权重、激活(A和Attention Q/K/V)设计最优量化算法"：

  权重 W (离线): SmoothQuant alpha扫描 + Hadamard旋转 + exact微指数 +
                 校准激活 lambda_j 加权 (对齐 ||X E_W^T||^2 输出MSE)
  激活 A (在线): SmoothQuant D^-1 + Hadamard旋转 + exact微指数 +
                 diag(W_hat^T W_hat) 加权 (对齐 ||E_X W_hat^T||^2 输出MSE)
  Q/K   (在线): calibration选择 plain/Hadamard/互易平衡/平衡+Hadamard，
                 以最终 Attention 输出MSE选择模式，并加入Q/K输出敏感度加权
  V     (在线): exact微指数 + 动态E6M2局部搜索；必要时与Q/K共同回退标准HiF4

核心优化:
  1. exact微指数: 4组合联合搜索, 逐块严格不劣于贪心 (3次量化, 同开销)
  2. E6M2连续邻域搜索: 修正小候选窗口的非对称跳点
  3. Linear输出加权: 权重用 lambda_j=mean(X_rot^2), 激活用 diag(W_hat^T W_hat)
  4. Attention Q/K互易平衡: QD 与 KD^-1 在量化前严格保持 QK^T
  5. Attention配置选择: Q/K模式 × V(std/opt)，held-out最终Attention MSE选择
  6. Q/K输出敏感度: 加权/不加权同时作为候选，避免强制近似Hessian
  7. 严格cross-fit: 校准评估与在线部署使用完全相同的balance/importance

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
    if numel > 8_000_000:
        return 5
    elif numel > 2_000_000:
        return 5
    else:
        return 5


def _adaptive_chunk_rows(M):
    if M <= 384:
        return M
    elif M <= 1024:
        return 256
    elif M <= 2048:
        return 512
    else:
        return 1024


def _e6m2_candidates(target, n_candidates=5):
    """Return a contiguous local E6M2 neighborhood around ``target``.

    ``searchsorted`` points to the first table value >= target.  The old
    n=3/4 special cases jumped by +4 table entries, which made calibration
    scans unnecessarily asymmetric.  A contiguous neighborhood is both
    cheaper to reason about and much more stable around an E6M2 boundary.
    """
    target_flat = target.reshape(-1).double()
    idx = torch.searchsorted(_E6M2_TABLE, target_flat)
    half = n_candidates // 2
    if n_candidates % 2 == 1:
        offsets = torch.arange(-half, half + 1, dtype=torch.long)
    else:
        offsets = torch.arange(-half, n_candidates - half, dtype=torch.long)
    idx = idx.clamp(half, len(_E6M2_TABLE) - 1 - max(int(offsets.max()), 0))
    cand_idx = (idx.unsqueeze(-1) + offsets).clamp(0, len(_E6M2_TABLE) - 1)
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


def _quantize_hif4(w_fp, n_candidates=5, importance=None, chunk_rows=None):
    orig_shape = w_fp.shape

    if chunk_rows is None:
        chunk_rows = _adaptive_chunk_rows(w_fp.shape[0]) if w_fp.ndim > 1 else w_fp.shape[0] if w_fp.ndim == 1 else 384

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
# Attention calibration helpers
# ----------------------------------------------------------------------

ATTN_EVAL_SAMPLES = 2
ATTN_EVAL_TOKENS = 48
ATTN_BALANCE_STABILITY_MAX = 0.40


def _apply_q_balance(q_fp, balance, q_num_heads, kv_num_heads, head_dim):
    """Q' = Q D.  D is shared by all Q heads belonging to one KV head."""
    if balance is None:
        return q_fp
    seq = q_fp.shape[0]
    group = q_num_heads // kv_num_heads
    q = q_fp.reshape(seq, q_num_heads, head_dim)
    d_q = balance.unsqueeze(1).expand(kv_num_heads, group, head_dim).reshape(q_num_heads, head_dim)
    return (q * d_q.unsqueeze(0)).reshape_as(q_fp).to(torch.float32)


def _apply_k_balance(k_fp, balance, kv_num_heads, head_dim):
    """K' = K D^-1; paired with _apply_q_balance this preserves QK^T."""
    if balance is None:
        return k_fp
    seq = k_fp.shape[0]
    k = k_fp.reshape(seq, kv_num_heads, head_dim)
    return (k / balance.clamp(min=1e-8).unsqueeze(0)).reshape_as(k_fp).to(torch.float32)


def _apply_attention_transform(q_fp, k_fp, q_num_heads, kv_num_heads, head_dim,
                               balance=None, hadamard=None):
    q_work = _apply_q_balance(q_fp, balance, q_num_heads, kv_num_heads, head_dim)
    k_work = _apply_k_balance(k_fp, balance, kv_num_heads, head_dim)
    if hadamard is not None:
        q_work = _apply_hadamard(q_work, hadamard)
        k_work = _apply_hadamard(k_work, hadamard)
    return q_work, k_work


def _compute_qk_balance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Estimate a reciprocal Q/K per-dimension balance from calibration data.

    For each GQA KV head and feature r, use
        D_r = sqrt(RMS(K_r) / RMS(Q_r)).
    Then Q' = QD and K' = KD^-1 leave the FP32 attention logits unchanged,
    while reducing Q/K scale anisotropy before HiF4 quantization.

    The returned stability score is the median calibration std of log(D).
    Large values indicate that the per-channel balance is not stable across
    samples; such a balance is not considered by calibration mode selection.
    """
    if not calib_qkv_list:
        return None, float("inf")

    group = q_num_heads // kv_num_heads
    q2_sum = torch.zeros(kv_num_heads, head_dim, dtype=torch.float64)
    k2_sum = torch.zeros_like(q2_sum)
    q_count = 0
    k_count = 0
    logd_samples = []
    eps = 1e-12

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        seq = q_fp.shape[0]
        q = q_fp.reshape(seq, q_num_heads, head_dim).reshape(seq, kv_num_heads, group, head_dim)
        k = k_fp.reshape(seq, kv_num_heads, head_dim)

        q2 = (q.double() ** 2).sum(dim=(0, 2))
        k2 = (k.double() ** 2).sum(dim=0)
        q2_sum += q2
        k2_sum += k2
        q_count += seq * group
        k_count += seq

        q_rms_i = (q2 / max(seq * group, 1) + eps).sqrt()
        k_rms_i = (k2 / max(seq, 1) + eps).sqrt()
        logd_samples.append(0.5 * (torch.log(k_rms_i + eps) - torch.log(q_rms_i + eps)))

    q_rms = (q2_sum / max(q_count, 1) + eps).sqrt()
    k_rms = (k2_sum / max(k_count, 1) + eps).sqrt()
    balance = torch.sqrt((k_rms + eps) / (q_rms + eps)).clamp(0.25, 4.0).float()

    if len(logd_samples) >= 2:
        stack = torch.stack(logd_samples, dim=0)
        stability = stack.std(dim=0, unbiased=False).median().item()
    else:
        stability = 0.0
    return balance.contiguous(), float(stability)


def _normalize_attention_importance(imp):
    """Normalize importance per physical 64-value HiF4 block and damp it.

    Only relative weights inside a block affect the scale/micro-exponent
    candidate ranking.  sqrt damping + clipping makes calibration priors less
    brittle under calibration/test distribution shift.
    """
    flat = imp.reshape(-1).float().clamp(min=1e-12)
    if flat.numel() % BLK_SIZE != 0:
        return torch.ones_like(flat)
    blk = flat.reshape(-1, BLK_SIZE)
    blk = blk / blk.mean(dim=-1, keepdim=True).clamp(min=1e-12)
    blk = torch.sqrt(blk).clamp(0.25, 4.0)
    return blk.reshape(-1).contiguous()


def _compute_qk_importance(calib_qkv_list, q_num_heads, kv_num_heads, head_dim,
                           balance=None, hadamard=None):
    """Diagonal output-aware Q/K metric in the selected transformed domain.

    Q error is weighted by diag(K^T K); K error by diag(Q^T Q).  Under GQA,
    every K head aggregates all Q heads in its group.  This is the diagonal
    approximation to logit error ||E_Q K^T + Q E_K^T||^2.
    """
    if not calib_qkv_list:
        return None, None

    group = q_num_heads // kv_num_heads
    q_imp = torch.zeros(q_num_heads, head_dim, dtype=torch.float64)
    k_imp = torch.zeros(kv_num_heads, head_dim, dtype=torch.float64)
    n_samples = 0

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        q_work, k_work = _apply_attention_transform(
            q_fp, k_fp, q_num_heads, kv_num_heads, head_dim, balance, hadamard
        )
        seq = q_work.shape[0]
        q = q_work.reshape(seq, q_num_heads, head_dim)
        k = k_work.reshape(seq, kv_num_heads, head_dim)

        for g in range(kv_num_heads):
            k_diag = (k[:, g, :].double() ** 2).mean(dim=0)
            q_diag = (q[:, g * group:(g + 1) * group, :].double() ** 2).mean(dim=(0, 1))
            q_imp[g * group:(g + 1) * group] += k_diag.unsqueeze(0)
            k_imp[g] += q_diag
        n_samples += 1

    q_imp /= max(n_samples, 1)
    k_imp /= max(n_samples, 1)
    return (_normalize_attention_importance(q_imp),
            _normalize_attention_importance(k_imp))


def _sample_attention_rows(q, k, v, max_tokens=ATTN_EVAL_TOKENS):
    seq = q.shape[0]
    if seq <= max_tokens:
        return q, k, v
    idx = torch.linspace(0, seq - 1, steps=max_tokens).round().long().unique()
    return q[idx], k[idx], v[idx]


def _attention_candidate_count(x):
    # Keep the online path cheap.  Small tensors can afford two extra local
    # E6M2 candidates without materially affecting the 5-minute total budget.
    return 7 if x.numel() <= 262_144 else 5


def _build_attention_qspecs(fit_calib, q_num_heads, kv_num_heads, head_dim,
                            balance_fit, balance_ok, H):
    """Build *deployment-identical* Q/K candidates from the fit split.

    Each spec contains the exact transform and exact importance tensors that
    will later be stored in q_state/k_state.  This removes a subtle train/test
    mismatch in the previous version, where calibration evaluated unweighted
    Q/K but the dynamic path enabled calibration-derived importance.
    """
    transforms = [("plain", None, None)]
    if H is not None:
        transforms.append(("had", None, H))
    if balance_ok:
        transforms.append(("bal", balance_fit, None))
        if H is not None:
            transforms.append(("balhad", balance_fit, H))

    specs = []
    for name, balance, hadamard in transforms:
        # Always retain an unweighted candidate.  Diagonal Q/K importance is
        # only an approximation to the true softmax-aware Hessian, so forcing
        # it on every case can hurt under distribution shift.
        specs.append({
            "name": name,
            "base_mode": name,
            "balance": balance,
            "hadamard": hadamard,
            "q_imp": None,
            "k_imp": None,
        })

        q_imp, k_imp = _compute_qk_importance(
            fit_calib, q_num_heads, kv_num_heads, head_dim, balance, hadamard
        )
        if q_imp is not None and k_imp is not None:
            specs.append({
                "name": name + "_imp",
                "base_mode": name,
                "balance": balance,
                "hadamard": hadamard,
                "q_imp": q_imp,
                "k_imp": k_imp,
            })
    return specs


def _evaluate_attention_configs(calib_qkv_list, qspecs,
                                q_num_heads, kv_num_heads, head_dim):
    """Evaluate the exact deployable Attention configurations.

    Besides the all-standard safety anchor, V is decoupled from Q/K:
      - std_vopt: standard Q/K + optimized V
      - <qmode>_vstd: optimized Q/K + standard V
      - <qmode>_vopt: optimized Q/K + optimized V

    This matters because V does not need the same reciprocal/orthogonal
    transform as Q/K.  Forcing Q/K/V to fall back together can throw away a
    useful improvement in one branch merely because another branch is risky.
    """
    losses = {"std": [] , "std_vopt": []}
    for spec in qspecs:
        losses[spec["name"] + "_vstd"] = []
        losses[spec["name"] + "_vopt"] = []

    for sample in calib_qkv_list[:ATTN_EVAL_SAMPLES]:
        q_fp = _dequant_nvfp4(*sample["q"])
        k_fp = _dequant_nvfp4(*sample["k"])
        v_fp = _dequant_nvfp4(*sample["v"])
        q_fp, k_fp, v_fp = _sample_attention_rows(q_fp, k_fp, v_fp)
        ref = _attention(q_fp, k_fp, v_fp, q_num_heads, kv_num_heads, head_dim)

        q_std = _hif4_dequant(standard_hif4_quantize(q_fp), q_fp.shape)
        k_std = _hif4_dequant(standard_hif4_quantize(k_fp), k_fp.shape)
        v_std = _hif4_dequant(standard_hif4_quantize(v_fp), v_fp.shape)
        out_std = _attention(q_std, k_std, v_std, q_num_heads, kv_num_heads, head_dim)
        mse_std = ((out_std - ref) ** 2).mean().item()
        losses["std"].append(mse_std)

        nv = _attention_candidate_count(v_fp)
        v_opt = _hif4_dequant(_quantize_hif4(v_fp, n_candidates=nv), v_fp.shape)
        out_std_vopt = _attention(q_std, k_std, v_opt, q_num_heads, kv_num_heads, head_dim)
        losses["std_vopt"].append(((out_std_vopt - ref) ** 2).mean().item())

        for spec in qspecs:
            q_work, k_work = _apply_attention_transform(
                q_fp, k_fp, q_num_heads, kv_num_heads, head_dim,
                spec["balance"], spec["hadamard"]
            )
            nq = _attention_candidate_count(q_work)
            nk = _attention_candidate_count(k_work)
            q_hat = _hif4_dequant(
                _quantize_hif4(q_work, n_candidates=nq, importance=spec["q_imp"]),
                q_work.shape,
            )
            k_hat = _hif4_dequant(
                _quantize_hif4(k_work, n_candidates=nk, importance=spec["k_imp"]),
                k_work.shape,
            )

            out_vstd = _attention(q_hat, k_hat, v_std, q_num_heads, kv_num_heads, head_dim)
            out_vopt = _attention(q_hat, k_hat, v_opt, q_num_heads, kv_num_heads, head_dim)
            losses[spec["name"] + "_vstd"].append(((out_vstd - ref) ** 2).mean().item())
            losses[spec["name"] + "_vopt"].append(((out_vopt - ref) ** 2).mean().item())

    return losses


def _select_attention_config(losses):
    """Conservative selection relative to the official-style HiF4 anchor."""
    std = losses.get("std", [])
    if not std:
        return "std"

    best_name = "std"
    best_ratio = 1.0
    n = len(std)
    for name, vals in losses.items():
        if name == "std" or len(vals) != n:
            continue
        ratios = [v / max(s, 1e-15) for v, s in zip(vals, std)]
        mean_ratio = sum(ratios) / n
        worst_ratio = max(ratios)
        wins = sum(r < 1.0 for r in ratios)

        # Require every held-out sample to improve.  In addition, demand a
        # small per-sample margin so a near-tie does not flip sign on test.
        if n == 1:
            eligible = mean_ratio <= 0.90
        else:
            eligible = mean_ratio <= 0.96 and worst_ratio <= 0.995 and wins == n
        if eligible and mean_ratio < best_ratio:
            best_ratio = mean_ratio
            best_name = name
    return best_name

# ======================================================================
# Attention-output Gauss-Newton rescue (head_dim == 64)
# ----------------------------------------------------------------------
# This is deliberately *not* another heuristic mode family.  It derives a
# quadratic metric from the first-order Attention output perturbation:
#
#   dO = J_softmax(dS) V,      dS_Q = dQ K^T / sqrt(d)
#
# For one query vector q_i,
#   ||dO_i||^2 = dq_i^T H_Q,i dq_i,
#   H_Q,i = A_i A_i^T,  A_i = K^T J_i V / sqrt(d).
#
# For one key vector k_t, averaging over key positions gives
#   H_K ~= E_t sum_i p_it^2 ||v_t-o_i||^2 q_i q_i^T / d.
#
# We estimate one PSD 64x64 matrix per head from the fit split, then use it
# online to choose the HiF4 E6M2 candidate whose *Attention-output local
# quadratic loss* is smallest.  Standard HiF4 is always included as a
# per-block candidate.
# ======================================================================

ATTN_GN_QUERY_SAMPLES = 16
ATTN_GN_SHRINK = 0.10
ATTN_GN_EVAL_QUERIES = 32


def _fixed_rademacher_projection(d: int, r: int, seed: int = 20260827):
    """Deterministic output sketch R with E[RR^T] ~= I."""
    g = torch.Generator().manual_seed(seed)
    R = torch.randint(0, 2, (d, r), generator=g, dtype=torch.int64).float()
    R = (R * 2.0 - 1.0) / math.sqrt(float(r))
    return R


def _regularize_psd_metric(H: torch.Tensor, shrink: float = ATTN_GN_SHRINK):
    """Symmetrize, normalize trace, and add isotropic shrinkage."""
    H = 0.5 * (H + H.transpose(-1, -2))
    d = H.shape[-1]
    tr = H.diagonal(dim1=-2, dim2=-1).sum(dim=-1, keepdim=True).clamp(min=1e-12)
    H = H * (float(d) / tr.unsqueeze(-1))
    eye = torch.eye(d, dtype=H.dtype).expand_as(H)
    H = (1.0 - shrink) * H + shrink * eye
    return H.float().contiguous()


def _compute_attention_gn_hessians(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Estimate the *exact-output* first-order Gauss-Newton metrics for Q/K.

    No random projection is used.  K/V keep the full token axis, so the
    softmax normalization and the V-dependent output sensitivity are both
    preserved.  We only subsample query rows because the online HiF4 mapping
    is row-local and the metric is averaged over queries.
    """
    if not calib_qkv_list or head_dim != BLK_SIZE:
        return None, None
    if q_num_heads % kv_num_heads != 0:
        return None, None

    group = q_num_heads // kv_num_heads
    d = head_dim
    qH = torch.zeros(q_num_heads, d, d, dtype=torch.float64)
    kH = torch.zeros(kv_num_heads, d, d, dtype=torch.float64)
    q_count = torch.zeros(q_num_heads, dtype=torch.float64)
    k_count = torch.zeros(kv_num_heads, dtype=torch.float64)
    inv_sqrt_d = 1.0 / math.sqrt(float(d))

    for sample in calib_qkv_list:
        q_fp = _dequant_nvfp4(*sample["q"]).float()
        k_fp = _dequant_nvfp4(*sample["k"]).float()
        v_fp = _dequant_nvfp4(*sample["v"]).float()
        seq = q_fp.shape[0]
        if seq == 0:
            continue
        q = q_fp.reshape(seq, q_num_heads, d)
        k = k_fp.reshape(seq, kv_num_heads, d)
        v = v_fp.reshape(seq, kv_num_heads, d)

        m = min(ATTN_GN_QUERY_SAMPLES, seq)
        idx = torch.linspace(0, seq - 1, steps=m).round().long().unique()

        for g in range(kv_num_heads):
            Kg = k[:, g, :]                        # (T,d)
            Vg = v[:, g, :]                        # (T,d_v=d)
            Hk_acc = torch.zeros(d, d, dtype=torch.float64)
            Hk_weight = 0.0

            for local_h in range(group):
                h = g * group + local_h
                Qs = q[idx, h, :]                  # (m,d)
                scores = (Qs @ Kg.transpose(0, 1)) * inv_sqrt_d
                P = torch.softmax(scores, dim=-1)  # (m,T)
                O = P @ Vg                         # (m,d)

                # For query i:
                #   J_i V = diag(p_i)V - p_i(p_i^T V)
                #         = p_i[:,None] * (V - o_i).
                B = P.unsqueeze(-1) * (Vg.unsqueeze(0) - O.unsqueeze(1))
                A = torch.einsum('td,mto->mdo', Kg, B) * inv_sqrt_d
                Hq = torch.einsum('mdo,meo->mde', A.double(), A.double()).sum(dim=0)
                qH[h] += Hq
                q_count[h] += float(A.shape[0])

                # For key t:
                # dO_i/dk_t = p_it (v_t-o_i) q_i^T / sqrt(d).
                # Averaging H_k,t over t gives the fixed per-head metric used
                # by the online row-local K quantizer.
                diff2 = (Vg.unsqueeze(0) - O.unsqueeze(1)).pow(2).sum(dim=-1)
                alpha = P.pow(2) * diff2           # (m,T)
                beta = alpha.sum(dim=-1).double()  # sum_t alpha_it
                Hk_acc += torch.einsum('m,md,me->de', beta, Qs.double(), Qs.double()) / float(d * seq)
                Hk_weight += float(Qs.shape[0])

            if Hk_weight > 0:
                kH[g] += Hk_acc
                k_count[g] += Hk_weight

    for h in range(q_num_heads):
        if q_count[h] > 0:
            qH[h] /= q_count[h]
        else:
            qH[h] = torch.eye(d, dtype=torch.float64)
    for g in range(kv_num_heads):
        if k_count[g] > 0:
            kH[g] /= k_count[g]
        else:
            kH[g] = torch.eye(d, dtype=torch.float64)

    return _regularize_psd_metric(qH), _regularize_psd_metric(kH)


def _hessian_loss64(err: torch.Tensor, H: torch.Tensor):
    """err: (M,Hd,64), H: (Hd,64,64) -> (M,Hd)."""
    return torch.einsum('mhi,hij,mhj->mh', err.float(), H.float(), err.float())


def _quantize_hif4_gn64(x: torch.Tensor, H_heads: torch.Tensor, n_candidates: int = 5):
    """HiF4 quantization for head_dim=64 using an output-aware quadratic metric.

    Standard HiF4 is the initial per-row/head candidate.  For every local E6M2
    scale we generate two exact micro-exponent variants: ordinary MSE and
    diag(H)-weighted MSE.  The final candidate is selected by full e^T H e.
    Thus the *only* selection objective is the calibrated Attention-output
    Gauss-Newton metric; no clipping/percentile/seed heuristics are involved.
    """
    orig_shape = x.shape
    C = int(orig_shape[-1])
    n_heads = int(H_heads.shape[0])
    if C != n_heads * BLK_SIZE:
        return _quantize_hif4(x, n_candidates=n_candidates)

    M = int(x.numel() // C)
    w = x.reshape(M, n_heads, BLK_SIZE).float()
    w8224 = w.reshape(M, n_heads, 8, 2, 4)
    H = H_heads.float()

    # Safe anchor: official standard HiF4, per physical 64-value block.
    std = standard_hif4_quantize(x)
    std_dq = _hif4_dequant(std, orig_shape).reshape(M, n_heads, BLK_SIZE)
    best_loss = _hessian_loss64(std_dq - w, H)

    best_sf = std["scale_factor"].reshape(M, n_heads, 1).clone()
    best_lv2 = std["scale_lv2"].reshape(M, n_heads, 8).clone()
    best_lv3 = std["scale_lv3"].reshape(M, n_heads, 8, 2).clone()
    best_sign = std["sign"].reshape(M, n_heads, 8, 2, 4).clone()
    best_mant = std["mant"].reshape(M, n_heads, 8, 2, 4).clone()

    max64 = w.abs().amax(dim=-1, keepdim=True)
    target = (max64 / 7.0).clamp(min=2.0 ** (-48))
    cands = _e6m2_candidates(target, n_candidates)  # (M,H,nc)

    diag = H.diagonal(dim1=-2, dim2=-1).clamp(min=1e-8)
    diag = diag / diag.mean(dim=-1, keepdim=True).clamp(min=1e-8)
    diag_imp = torch.sqrt(diag).clamp(0.25, 4.0).reshape(1, n_heads, 8, 2, 4)

    def consider(sf, use_diag):
        nonlocal best_loss, best_sf, best_lv2, best_lv3, best_sign, best_mant
        sfexp = sf.reshape(M, n_heads, 1, 1, 1)
        imp = diag_imp if use_diag else None
        lv2, lv3, sign, mant, _ = _quantize_block_given_scale(w8224, sfexp, imp)
        dq = (sign * mant * lv3.unsqueeze(-1) * lv2.unsqueeze(-1).unsqueeze(-1) * sfexp).reshape(M, n_heads, BLK_SIZE)
        loss = _hessian_loss64(dq - w, H)
        improved = loss < best_loss
        if not improved.any():
            return
        best_loss = torch.where(improved, loss, best_loss)
        best_sf = torch.where(improved.unsqueeze(-1), sf, best_sf)
        best_lv2 = torch.where(improved.unsqueeze(-1), lv2, best_lv2)
        best_lv3 = torch.where(improved.unsqueeze(-1).unsqueeze(-1), lv3, best_lv3)
        mask = improved.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1)
        best_sign = torch.where(mask, sign, best_sign)
        best_mant = torch.where(mask, mant, best_mant)

    for ci in range(cands.shape[-1]):
        sf = cands[..., ci:ci+1]
        consider(sf, False)
        consider(sf, True)

    prefix = orig_shape[:-1]
    return {
        "scale_factor": best_sf.reshape(*prefix, n_heads, 1, 1, 1).contiguous().float(),
        "scale_lv2": best_lv2.reshape(*prefix, n_heads, 8, 1, 1).contiguous().float(),
        "scale_lv3": best_lv3.reshape(*prefix, n_heads, 8, 2, 1).contiguous().float(),
        "sign": best_sign.reshape(*prefix, n_heads, 8, 2, 4).contiguous().float(),
        "mant": best_mant.reshape(*prefix, n_heads, 8, 2, 4).contiguous().float(),
    }


def _attention_rect(q, k, v, q_heads, kv_heads, head_dim):
    """Sampled Q rows against full K/V; preserves the softmax denominator."""
    nq = q.shape[0]
    nk = k.shape[0]
    q_re = q.reshape(nq, q_heads, head_dim).transpose(0, 1)
    k_re = k.reshape(nk, kv_heads, head_dim).transpose(0, 1)
    v_re = v.reshape(nk, kv_heads, head_dim).transpose(0, 1)
    group = q_heads // kv_heads
    k_exp = k_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, nk, head_dim)
    v_exp = v_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, nk, head_dim)
    scores = torch.matmul(q_re, k_exp.transpose(-1, -2)) / math.sqrt(head_dim)
    p = torch.softmax(scores, dim=-1)
    out = torch.matmul(p, v_exp)
    return out.transpose(0, 1).reshape(nq, q_heads * head_dim)


def _evaluate_gn_rescue(eval_calib, qH, kH, q_num_heads, kv_num_heads, head_dim):
    """Held-out final-output test for the exact deployable GN quantizer."""
    losses = {"std": [], "gn_q": [], "gn_k": [], "gn_qk": []}
    for sample in eval_calib:
        q = _dequant_nvfp4(*sample["q"]).float()
        k = _dequant_nvfp4(*sample["k"]).float()
        v = _dequant_nvfp4(*sample["v"]).float()
        seq = q.shape[0]
        m = min(ATTN_GN_EVAL_QUERIES, seq)
        idx = torch.linspace(0, seq - 1, steps=m).round().long().unique()

        qs_p = standard_hif4_quantize(q)
        ks_p = standard_hif4_quantize(k)
        vs_p = standard_hif4_quantize(v)
        q_std = _hif4_dequant(qs_p, q.shape)
        k_std = _hif4_dequant(ks_p, k.shape)
        v_std = _hif4_dequant(vs_p, v.shape)

        q_gn = _hif4_dequant(_quantize_hif4_gn64(q, qH, _attention_candidate_count(q)), q.shape)
        k_gn = _hif4_dequant(_quantize_hif4_gn64(k, kH, _attention_candidate_count(k)), k.shape)

        ref = _attention_rect(q[idx], k, v, q_num_heads, kv_num_heads, head_dim)
        outs = {
            "std": _attention_rect(q_std[idx], k_std, v_std, q_num_heads, kv_num_heads, head_dim),
            "gn_q": _attention_rect(q_gn[idx], k_std, v_std, q_num_heads, kv_num_heads, head_dim),
            "gn_k": _attention_rect(q_std[idx], k_gn, v_std, q_num_heads, kv_num_heads, head_dim),
            "gn_qk": _attention_rect(q_gn[idx], k_gn, v_std, q_num_heads, kv_num_heads, head_dim),
        }
        for name, out in outs.items():
            losses[name].append(((out - ref) ** 2).mean().item())
    return losses


def _select_gn_rescue(losses):
    """Cross-fit gate.  Candidates come only from the derived Q/K decomposition."""
    std = losses.get("std", [])
    if not std:
        return "std"
    best = "std"
    best_mean = 1.0
    for name in ("gn_q", "gn_k", "gn_qk"):
        vals = losses.get(name, [])
        if len(vals) != len(std):
            continue
        ratios = [v / max(s, 1e-15) for v, s in zip(vals, std)]
        mean_r = sum(ratios) / len(ratios)
        worst_r = max(ratios)
        # Both held-out samples must improve; require a real margin rather than
        # selecting a numerical tie.
        if all(r < 1.0 for r in ratios) and mean_r <= 0.97 and worst_r <= 0.995:
            if mean_r < best_mean:
                best_mean = mean_r
                best = name
    return best



# ======================================================================
# V8: V-only coordinated output-loss quantization
# ----------------------------------------------------------------------
# The V7 diagnostics showed a distinct regime where:
#   Q-only MSE ~= 0, K-only MSE ~= 0, QK-only MSE ~= 0,
#   V-only MSE ~= full standard Attention MSE.
# In that regime the exact task loss reduces to
#
#       L_V = || P (V_hat - V) ||_F^2
#           = Tr(E_V^T (P^T P) E_V).
#
# A per-token weighted reconstruction loss cannot exploit the off-diagonal
# entries of P^T P because every physical HiF4 block (head_dim=64) receives
# only one scalar token weight.  V8 therefore fits a low-rank factor
#
#       G = E[P^T P] ~= B^T B
#
# from calibration and chooses the discrete HiF4 candidate of every
# token/head jointly by deterministic coordinate descent on ||B E_V||^2.
# This is used ONLY after a calibration error decomposition proves that the
# case is V-dominated.  Otherwise the V3/V7 path is untouched.
# ======================================================================

ATTN_VONLY_EPS = 0.02
ATTN_VONLY_V_TOL = 0.05
ATTN_VCOORD_QUERY_SAMPLES = 32
ATTN_VCOORD_EVAL_QUERIES = 48
ATTN_VCOORD_RANK = 16
ATTN_VCOORD_SWEEPS = 2


def _sample_query_indices(seq: int, n: int):
    m = min(int(n), int(seq))
    if m <= 0:
        return torch.empty(0, dtype=torch.long)
    return torch.linspace(0, seq - 1, steps=m).round().long().unique()


def _v_only_profile(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Exact calibration error decomposition for deciding whether V dominates.

    No fitted parameters are used here, so all calibration samples may be used
    without train/eval leakage.  Ratios are relative to all-standard Attention.
    """
    ratios = []
    for sample in calib_qkv_list:
        q = _dequant_nvfp4(*sample["q"]).float()
        k = _dequant_nvfp4(*sample["k"]).float()
        v = _dequant_nvfp4(*sample["v"]).float()
        if q.shape[0] == 0 or k.shape[0] != v.shape[0]:
            return None

        idx = _sample_query_indices(q.shape[0], ATTN_VCOORD_EVAL_QUERIES)
        qs = q[idx]

        q_std = _hif4_dequant(standard_hif4_quantize(qs), qs.shape)
        k_std = _hif4_dequant(standard_hif4_quantize(k), k.shape)
        v_std = _hif4_dequant(standard_hif4_quantize(v), v.shape)

        ref = _attention_rect(qs, k, v, q_num_heads, kv_num_heads, head_dim)
        out_std = _attention_rect(q_std, k_std, v_std, q_num_heads, kv_num_heads, head_dim)
        mse_std = ((out_std - ref) ** 2).mean().item()
        if mse_std <= 1e-20:
            return None

        q_only = _attention_rect(q_std, k, v, q_num_heads, kv_num_heads, head_dim)
        k_only = _attention_rect(qs, k_std, v, q_num_heads, kv_num_heads, head_dim)
        qk_only = _attention_rect(q_std, k_std, v, q_num_heads, kv_num_heads, head_dim)
        v_only = _attention_rect(qs, k, v_std, q_num_heads, kv_num_heads, head_dim)

        # Data-independent optimized V path.  Because it does not fit any
        # calibration state, evaluating it on all five calibration samples is
        # a legitimate generalization check rather than post-selection reuse.
        nv = _attention_candidate_count(v)
        v_opt = _hif4_dequant(_quantize_hif4(v, n_candidates=nv), v.shape)
        out_vopt = _attention_rect(q_std, k_std, v_opt, q_num_heads, kv_num_heads, head_dim)

        ratios.append({
            "q": ((q_only - ref) ** 2).mean().item() / mse_std,
            "k": ((k_only - ref) ** 2).mean().item() / mse_std,
            "qk": ((qk_only - ref) ** 2).mean().item() / mse_std,
            "v": ((v_only - ref) ** 2).mean().item() / mse_std,
            "vopt": ((out_vopt - ref) ** 2).mean().item() / mse_std,
        })

    if not ratios:
        return None

    # "V-only" is not guessed from tensor statistics.  It is defined directly
    # by the final Attention error decomposition.
    is_v_only = all(
        r["q"] <= ATTN_VONLY_EPS
        and r["k"] <= ATTN_VONLY_EPS
        and r["qk"] <= ATTN_VONLY_EPS
        and abs(r["v"] - 1.0) <= ATTN_VONLY_V_TOL
        for r in ratios
    )
    generic_ok = all(r["vopt"] < 0.999 for r in ratios)
    return {
        "is_v_only": is_v_only,
        "generic_ok": generic_ok,
        "vopt_mean": sum(r["vopt"] for r in ratios) / len(ratios),
        "vopt_worst": max(r["vopt"] for r in ratios),
        "ratios": ratios,
    }


def _fit_v_attention_factor(calib_qkv_list, q_num_heads, kv_num_heads, head_dim):
    """Fit B such that mean(P^T P) ~= B^T B, one factor per KV head.

    P is computed using *standard-HiF4 Q/K*, exactly matching the deployment
    path in the V-only rescue.  Query rows are subsampled but the full key axis
    is retained, so the softmax denominator is unchanged.
    """
    if not calib_qkv_list or head_dim != BLK_SIZE:
        return None, None
    if q_num_heads % kv_num_heads != 0:
        return None, None

    seqs = [int(_dequant_nvfp4(*s["k"]).shape[0]) for s in calib_qkv_list]
    if not seqs or any(t != seqs[0] for t in seqs):
        return None, None
    seq = seqs[0]
    if seq <= 0:
        return None, None

    group = q_num_heads // kv_num_heads
    rows = [[] for _ in range(kv_num_heads)]
    inv_sqrt_d = 1.0 / math.sqrt(float(head_dim))

    for sample in calib_qkv_list:
        q = _dequant_nvfp4(*sample["q"]).float()
        k = _dequant_nvfp4(*sample["k"]).float()
        if q.shape[0] != seq:
            return None, None

        # Deployment uses standard Q/K in this regime.
        q_std = _hif4_dequant(standard_hif4_quantize(q), q.shape)
        k_std = _hif4_dequant(standard_hif4_quantize(k), k.shape)

        qr = q_std.reshape(seq, q_num_heads, head_dim)
        kr = k_std.reshape(seq, kv_num_heads, head_dim)
        idx = _sample_query_indices(seq, ATTN_VCOORD_QUERY_SAMPLES)

        for g in range(kv_num_heads):
            Kg = kr[:, g, :]
            for local_h in range(group):
                h = g * group + local_h
                Qs = qr[idx, h, :]
                P = torch.softmax((Qs @ Kg.transpose(0, 1)) * inv_sqrt_d, dim=-1)
                rows[g].append(P.float())

    factors = []
    energy = []
    for g in range(kv_num_heads):
        if not rows[g]:
            return None, None
        A = torch.cat(rows[g], dim=0)  # (R,T)
        Rn = max(int(A.shape[0]), 1)
        # SVD gives G=A^T A/R = V diag(S^2/R) V^T directly, without forming
        # a potentially large dense T x T Gram matrix.
        try:
            _, S, Vh = torch.linalg.svd(A, full_matrices=False)
        except RuntimeError:
            return None, None
        r = min(ATTN_VCOORD_RANK, int(S.numel()), seq)
        if r <= 0:
            return None, None
        B = (S[:r].unsqueeze(-1) * Vh[:r, :]) / math.sqrt(float(Rn))
        factors.append(B.contiguous())
        denom = S.pow(2).sum().clamp(min=1e-12)
        energy.append(float((S[:r].pow(2).sum() / denom).item()))

    # All heads have the same rank for fixed seq/sample count, but pad
    # defensively if a backend returns a smaller numerical rank.
    rmax = max(b.shape[0] for b in factors)
    out = torch.zeros(kv_num_heads, rmax, seq, dtype=torch.float32)
    for g, b in enumerate(factors):
        out[g, :b.shape[0], :] = b
    return out.contiguous(), torch.tensor(energy, dtype=torch.float32)


def _build_v_candidate_bank(v_fp, kv_num_heads, head_dim, n_candidates):
    """Return all legal local HiF4 candidates for each token/head block.

    Candidate 0 is official standard HiF4.  The remaining candidates use each
    local E6M2 scale with the exact micro-exponent search.  The bank is later
    optimized *jointly across tokens* by the P^T P objective.
    """
    if v_fp.ndim != 2 or head_dim != BLK_SIZE:
        return None
    T, C = int(v_fp.shape[0]), int(v_fp.shape[1])
    if C != kv_num_heads * head_dim:
        return None

    w = v_fp.reshape(T, kv_num_heads, head_dim).float()
    w8224 = w.reshape(T, kv_num_heads, 8, 2, 4)

    std = standard_hif4_quantize(v_fp)
    dq_std = _hif4_dequant(std, v_fp.shape).reshape(T, kv_num_heads, head_dim)

    sf_list = [std["scale_factor"].reshape(T, kv_num_heads, 1)]
    lv2_list = [std["scale_lv2"].reshape(T, kv_num_heads, 8)]
    lv3_list = [std["scale_lv3"].reshape(T, kv_num_heads, 8, 2)]
    sign_list = [std["sign"].reshape(T, kv_num_heads, 8, 2, 4)]
    mant_list = [std["mant"].reshape(T, kv_num_heads, 8, 2, 4)]
    dq_list = [dq_std]

    target = (w.abs().amax(dim=-1, keepdim=True) / 7.0).clamp(min=2.0 ** (-48))
    cands = _e6m2_candidates(target, n_candidates)

    for ci in range(cands.shape[-1]):
        sf = cands[..., ci:ci + 1]
        sfexp = sf.reshape(T, kv_num_heads, 1, 1, 1)
        lv2, lv3, sign, mant, _ = _quantize_block_given_scale(w8224, sfexp, None)
        dq = (
            sign * mant
            * lv3.unsqueeze(-1)
            * lv2.unsqueeze(-1).unsqueeze(-1)
            * sfexp
        ).reshape(T, kv_num_heads, head_dim)
        sf_list.append(sf)
        lv2_list.append(lv2)
        lv3_list.append(lv3)
        sign_list.append(sign)
        mant_list.append(mant)
        dq_list.append(dq)

    return {
        "dq": torch.stack(dq_list, dim=0),           # (K,T,H,64)
        "sf": torch.stack(sf_list, dim=0),           # (K,T,H,1)
        "lv2": torch.stack(lv2_list, dim=0),         # (K,T,H,8)
        "lv3": torch.stack(lv3_list, dim=0),         # (K,T,H,8,2)
        "sign": torch.stack(sign_list, dim=0),       # (K,T,H,8,2,4)
        "mant": torch.stack(mant_list, dim=0),
        "ref": w,
    }


def _coordinate_v_choices(bank, factor):
    """Discrete coordinate descent on ||B(V_hat-V)||_F^2.

    For changing one token error e_t by Delta:
        Delta L = 2 Delta^T (B_t^T Z) + ||B_t||^2 ||Delta||^2,
        Z = B E.
    Hence every coordinate update is evaluated exactly for the fitted
    low-rank P^T P objective; no surrogate token weight is used.
    """
    dq = bank["dq"].float()  # (K,T,H,D)
    ref = bank["ref"].float()
    err = dq - ref.unsqueeze(0)
    Kc, T, Hn, D = err.shape
    B = factor.float()
    if B.shape[0] != Hn or B.shape[-1] != T:
        return None

    # Two deterministic starts: official standard and the independent
    # per-block MSE optimum.  Keep whichever has the smaller *task* objective.
    local_choice = err.pow(2).sum(dim=-1).argmin(dim=0)  # (T,H)
    starts = [
        torch.zeros((T, Hn), dtype=torch.long),
        local_choice.clone().long(),
    ]

    best_total = None
    best_choice = None
    tidx = torch.arange(T)

    for init in starts:
        choice = init.clone()
        total_loss = 0.0

        for h in range(Hn):
            Bh = B[h]  # (r,T)
            ch = choice[:, h].clone()
            E = err[ch, tidx, h, :].clone()  # (T,D)
            Z = Bh @ E                        # (r,D)

            for _ in range(ATTN_VCOORD_SWEEPS):
                changed = 0
                for t in range(T):
                    b = Bh[:, t]
                    gtt = float(torch.dot(b, b).item())
                    if gtt <= 1e-20:
                        continue
                    cur_idx = int(ch[t].item())
                    cur_e = E[t]
                    cand_e = err[:, t, h, :]             # (K,D)
                    delta = cand_e - cur_e.unsqueeze(0)
                    c = b @ Z                             # (D,)
                    dloss = 2.0 * (delta * c.unsqueeze(0)).sum(dim=-1)
                    dloss = dloss + gtt * delta.pow(2).sum(dim=-1)
                    new_idx = int(torch.argmin(dloss).item())
                    if new_idx != cur_idx:
                        de = delta[new_idx]
                        Z = Z + b.unsqueeze(-1) * de.unsqueeze(0)
                        E[t] = cand_e[new_idx]
                        ch[t] = new_idx
                        changed += 1
                if changed == 0:
                    break

            choice[:, h] = ch
            total_loss += float(Z.pow(2).sum().item())

        if best_total is None or total_loss < best_total:
            best_total = total_loss
            best_choice = choice.clone()

    return best_choice


def _gather_v_bank_params(bank, choice, orig_shape, kv_num_heads):
    T = int(choice.shape[0])
    t = torch.arange(T).unsqueeze(1).expand(T, kv_num_heads)
    h = torch.arange(kv_num_heads).unsqueeze(0).expand(T, kv_num_heads)

    sf = bank["sf"][choice, t, h]
    lv2 = bank["lv2"][choice, t, h]
    lv3 = bank["lv3"][choice, t, h]
    sign = bank["sign"][choice, t, h]
    mant = bank["mant"][choice, t, h]

    prefix = orig_shape[:-1]
    return {
        "scale_factor": sf.reshape(*prefix, kv_num_heads, 1, 1, 1).contiguous().float(),
        "scale_lv2": lv2.reshape(*prefix, kv_num_heads, 8, 1, 1).contiguous().float(),
        "scale_lv3": lv3.reshape(*prefix, kv_num_heads, 8, 2, 1).contiguous().float(),
        "sign": sign.reshape(*prefix, kv_num_heads, 8, 2, 4).contiguous().float(),
        "mant": mant.reshape(*prefix, kv_num_heads, 8, 2, 4).contiguous().float(),
    }


def _quantize_v_coordinated(v_fp, factor, kv_num_heads, head_dim):
    if (
        factor is None
        or v_fp.ndim != 2
        or head_dim != BLK_SIZE
        or int(v_fp.shape[0]) != int(factor.shape[-1])
    ):
        return standard_hif4_quantize(v_fp)

    bank = _build_v_candidate_bank(
        v_fp, kv_num_heads, head_dim, _attention_candidate_count(v_fp)
    )
    if bank is None:
        return standard_hif4_quantize(v_fp)
    choice = _coordinate_v_choices(bank, factor)
    if choice is None:
        return standard_hif4_quantize(v_fp)
    return _gather_v_bank_params(bank, choice, v_fp.shape, kv_num_heads)


def _evaluate_vcoord(eval_calib, factor, q_num_heads, kv_num_heads, head_dim):
    losses = {"std": [], "vcoord": []}
    if factor is None:
        return losses

    for sample in eval_calib:
        q = _dequant_nvfp4(*sample["q"]).float()
        k = _dequant_nvfp4(*sample["k"]).float()
        v = _dequant_nvfp4(*sample["v"]).float()
        if int(v.shape[0]) != int(factor.shape[-1]):
            return {"std": [], "vcoord": []}

        idx = _sample_query_indices(q.shape[0], ATTN_VCOORD_EVAL_QUERIES)
        qs = q[idx]
        q_std = _hif4_dequant(standard_hif4_quantize(qs), qs.shape)
        k_std = _hif4_dequant(standard_hif4_quantize(k), k.shape)
        v_std = _hif4_dequant(standard_hif4_quantize(v), v.shape)
        v_coord = _hif4_dequant(
            _quantize_v_coordinated(v, factor, kv_num_heads, head_dim), v.shape
        )

        ref = _attention_rect(qs, k, v, q_num_heads, kv_num_heads, head_dim)
        out_std = _attention_rect(q_std, k_std, v_std, q_num_heads, kv_num_heads, head_dim)
        out_coord = _attention_rect(q_std, k_std, v_coord, q_num_heads, kv_num_heads, head_dim)
        losses["std"].append(((out_std - ref) ** 2).mean().item())
        losses["vcoord"].append(((out_coord - ref) ** 2).mean().item())

    return losses


def _accept_vcoord(losses):
    std = losses.get("std", [])
    vals = losses.get("vcoord", [])
    if not std or len(vals) != len(std):
        return False, 1.0, 1.0
    ratios = [v / max(s, 1e-20) for v, s in zip(vals, std)]
    mean_r = sum(ratios) / len(ratios)
    worst_r = max(ratios)
    # This is cross-fit: B was fitted on the other calibration samples.
    # Therefore only reject numerical ties; do not impose the unrelated 4%
    # margin used by the general-purpose V3 mode selector.
    ok = all(r < 0.9995 for r in ratios) and mean_r < 0.999
    return ok, mean_r, worst_r

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

    # P5+P6: scan alpha, select by weighted recon MSE proxy
    n_scan = min(8, weight_fp.shape[0])
    w_scan = weight_fp[:n_scan]
    best_proxy = None
    for alpha in (None, 0.5):
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
# 3. Attention: calibration + robust mode selection
# ======================================================================

def hif4_calibration_attention(
    calib_qkv_list: list,
    q_num_heads: int,
    kv_num_heads: int,
    head_dim: int,
) -> dict[str, Any]:
    """Robust Attention calibration with strict cross-fit deployment matching.

    The first calibration split estimates reciprocal balance / QK importance;
    the held-out split chooses the final Q/K/V configuration by *final
    Attention output MSE*.  The exact fitted tensors used during that held-out
    evaluation are stored and reused online -- no post-selection re-fitting.
    """
    if q_num_heads % kv_num_heads != 0:
        raise ValueError("q_num_heads must be divisible by kv_num_heads for GQA")

    H = None
    if head_dim % HAD_SIZE == 0:
        H = _random_hadamard(HAD_SIZE, seed=123).to(torch.float32).contiguous()

    # 5 calibration sets in the official task -> 3 fit + 2 held-out.
    if len(calib_qkv_list) >= 4:
        fit_calib = calib_qkv_list[:-2]
        eval_calib = calib_qkv_list[-2:]
    elif len(calib_qkv_list) >= 2:
        fit_calib = calib_qkv_list[:-1]
        eval_calib = calib_qkv_list[-1:]
    else:
        fit_calib = calib_qkv_list
        eval_calib = calib_qkv_list

    balance_fit, balance_stability = _compute_qk_balance(
        fit_calib, q_num_heads, kv_num_heads, head_dim
    )
    balance_ok = balance_fit is not None and balance_stability <= ATTN_BALANCE_STABILITY_MAX

    qspecs = _build_attention_qspecs(
        fit_calib, q_num_heads, kv_num_heads, head_dim,
        balance_fit, balance_ok, H
    )

    if eval_calib:
        losses = _evaluate_attention_configs(
            eval_calib, qspecs, q_num_heads, kv_num_heads, head_dim
        )
        selected = _select_attention_config(losses)
    else:
        selected = "std"

    # V8: first use an *observed final-output error decomposition* to detect
    # the V-only regime exposed by the diagnostics.  In that regime Q/K are
    # kept exactly on the standard anchor and only V is optimized.
    if selected == "std" and calib_qkv_list and head_dim == BLK_SIZE:
        vprof = _v_only_profile(
            calib_qkv_list, q_num_heads, kv_num_heads, head_dim
        )
        if vprof is not None and vprof["is_v_only"]:
            factor, factor_energy = _fit_v_attention_factor(
                fit_calib, q_num_heads, kv_num_heads, head_dim
            )
            if factor is not None and eval_calib:
                vcoord_losses = _evaluate_vcoord(
                    eval_calib, factor, q_num_heads, kv_num_heads, head_dim
                )
                vcoord_ok, _, _ = _accept_vcoord(vcoord_losses)
                if vcoord_ok:
                    return {
                        "q_state": {"use_standard": True, "mode": "vcoord"},
                        "k_state": {"use_standard": True, "mode": "vcoord"},
                        "v_state": {
                            "use_standard": False,
                            "mode": "vcoord",
                            "v_coord_factor": factor.to(torch.float16).contiguous(),
                            "v_seq_len": int(factor.shape[-1]),
                        },
                    }

            # Even if off-diagonal coordination does not generalize, the
            # ordinary V optimizer is data-independent.  If it improves on
            # *every* calibration sample in a proven V-only regime, enable it
            # without the V3 selector's unrelated 4% margin.
            if vprof["generic_ok"]:
                return {
                    "q_state": {"use_standard": True, "mode": "vonly_vopt"},
                    "k_state": {"use_standard": True, "mode": "vonly_vopt"},
                    "v_state": {"use_standard": False, "mode": "vonly_vopt"},
                }

    # Preserve V7's analytically-derived Q/K Gauss-Newton rescue for any
    # remaining pure-standard cases that are not V-dominated.
    if selected == "std" and eval_calib and head_dim == BLK_SIZE:
        qH, kH = _compute_attention_gn_hessians(
            fit_calib, q_num_heads, kv_num_heads, head_dim
        )
        if qH is not None and kH is not None:
            gn_losses = _evaluate_gn_rescue(
                eval_calib, qH, kH, q_num_heads, kv_num_heads, head_dim
            )
            gn_selected = _select_gn_rescue(gn_losses)
            if gn_selected != "std":
                return {
                    "q_state": {
                        "use_standard": gn_selected == "gn_k",
                        "mode": gn_selected,
                        "gn_hessian": None if gn_selected == "gn_k" else qH.to(torch.float16).contiguous(),
                    },
                    "k_state": {
                        "use_standard": gn_selected == "gn_q",
                        "mode": gn_selected,
                        "gn_hessian": None if gn_selected == "gn_q" else kH.to(torch.float16).contiguous(),
                    },
                    "v_state": {"use_standard": True, "mode": gn_selected},
                }

    # Pure standard anchor.
    if selected == "std":
        return {
            "q_state": {"use_standard": True, "mode": "std"},
            "k_state": {"use_standard": True, "mode": "std"},
            "v_state": {"use_standard": True, "mode": "std"},
        }

    # Standard Q/K can still pair with optimized V.
    if selected == "std_vopt":
        return {
            "q_state": {"use_standard": True, "mode": "std_vopt"},
            "k_state": {"use_standard": True, "mode": "std_vopt"},
            "v_state": {"use_standard": False, "mode": "std_vopt"},
        }

    if selected.endswith("_vstd"):
        qname = selected[:-5]
        v_use_standard = True
    elif selected.endswith("_vopt"):
        qname = selected[:-5]
        v_use_standard = False
    else:
        qname = selected
        v_use_standard = False

    spec = next((x for x in qspecs if x["name"] == qname), None)
    if spec is None:
        return {
            "q_state": {"use_standard": True, "mode": "std"},
            "k_state": {"use_standard": True, "mode": "std"},
            "v_state": {"use_standard": True, "mode": "std"},
        }

    # IMPORTANT: store exactly the same fitted balance/importance that was
    # validated on held-out calibration.  Do not refit after selection.
    q_state = {
        "use_standard": False,
        "balance": spec["balance"].contiguous() if spec["balance"] is not None else None,
        "hadamard": spec["hadamard"],
        "importance": spec["q_imp"],
        "mode": selected,
    }
    k_state = {
        "use_standard": False,
        "balance": spec["balance"].contiguous() if spec["balance"] is not None else None,
        "hadamard": spec["hadamard"],
        "importance": spec["k_imp"],
        "mode": selected,
    }
    v_state = {"use_standard": v_use_standard, "mode": selected}
    return {"q_state": q_state, "k_state": k_state, "v_state": v_state}


# ======================================================================
# 4. Dynamic Q
# ======================================================================

def hif4_dynamic_quantize_q(
    q_quant: torch.Tensor,
    q_scale: torch.Tensor,
    q_num_heads: int,
    head_dim: int,
    q_state: Any,
) -> dict[str, torch.Tensor]:
    q_fp = _dequant_nvfp4(q_quant, q_scale)
    if isinstance(q_state, dict) and q_state.get("use_standard", False):
        return standard_hif4_quantize(q_fp)

    gnH = q_state.get("gn_hessian") if isinstance(q_state, dict) else None
    if gnH is not None and head_dim == BLK_SIZE:
        return _quantize_hif4_gn64(
            q_fp, gnH.to(torch.float32), n_candidates=_attention_candidate_count(q_fp)
        )

    balance = q_state.get("balance") if isinstance(q_state, dict) else None
    if balance is not None:
        kv_num_heads = int(balance.shape[0])
        q_fp = _apply_q_balance(q_fp, balance.to(torch.float32), q_num_heads, kv_num_heads, head_dim)

    H = q_state.get("hadamard") if isinstance(q_state, dict) else None
    if H is not None:
        q_fp = _apply_hadamard(q_fp, H.to(torch.float32))

    imp = q_state.get("importance") if isinstance(q_state, dict) else None
    if imp is not None and int(imp.numel()) != int(q_fp.shape[-1]):
        imp = None
    return _quantize_hif4(q_fp, n_candidates=_attention_candidate_count(q_fp), importance=imp)


# ======================================================================
# 5. Dynamic K
# ======================================================================

def hif4_dynamic_quantize_k(
    k_quant: torch.Tensor,
    k_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    k_state: Any,
) -> dict[str, torch.Tensor]:
    k_fp = _dequant_nvfp4(k_quant, k_scale)
    if isinstance(k_state, dict) and k_state.get("use_standard", False):
        return standard_hif4_quantize(k_fp)

    gnH = k_state.get("gn_hessian") if isinstance(k_state, dict) else None
    if gnH is not None and head_dim == BLK_SIZE:
        return _quantize_hif4_gn64(
            k_fp, gnH.to(torch.float32), n_candidates=_attention_candidate_count(k_fp)
        )

    balance = k_state.get("balance") if isinstance(k_state, dict) else None
    if balance is not None:
        k_fp = _apply_k_balance(k_fp, balance.to(torch.float32), kv_num_heads, head_dim)

    H = k_state.get("hadamard") if isinstance(k_state, dict) else None
    if H is not None:
        k_fp = _apply_hadamard(k_fp, H.to(torch.float32))

    imp = k_state.get("importance") if isinstance(k_state, dict) else None
    if imp is not None and int(imp.numel()) != int(k_fp.shape[-1]):
        imp = None
    return _quantize_hif4(k_fp, n_candidates=_attention_candidate_count(k_fp), importance=imp)


# ======================================================================
# 6. Dynamic V
# ======================================================================

def hif4_dynamic_quantize_v(
    v_quant: torch.Tensor,
    v_scale: torch.Tensor,
    kv_num_heads: int,
    head_dim: int,
    v_state: Any,
) -> dict[str, torch.Tensor]:
    v_fp = _dequant_nvfp4(v_quant, v_scale)
    if isinstance(v_state, dict) and v_state.get("use_standard", False):
        return standard_hif4_quantize(v_fp)

    factor = v_state.get("v_coord_factor") if isinstance(v_state, dict) else None
    if factor is not None and head_dim == BLK_SIZE:
        return _quantize_v_coordinated(
            v_fp, factor.to(torch.float32), kv_num_heads, head_dim
        )

    return _quantize_hif4(v_fp, n_candidates=_attention_candidate_count(v_fp))


# ======================================================================
# Platform interface helpers
# ----------------------------------------------------------------------
# These utilities are expected by the scoring platform (simulate_scoring.py
# / self_check.py / generate_mini_sample.py): NVFP4 (de)quant helpers, the
# E6M2 rounding helper, the standard HiF4 baseline (Algorithm 1), and the
# HiF4 dequantizer. They are pure infrastructure — the quantization algorithm
# above (the 6 API functions + _quantize_hif4) is unchanged.
# ======================================================================

def dequantize_nvfp4(
    quant_float: torch.Tensor,
    scale_float: torch.Tensor,
    blk_size: int = NVFP4_BLK,
) -> torch.Tensor:
    """Dequantize NVFP4 carrier to FP32 (matches template interface)."""
    channels = int(quant_float.shape[-1])
    if channels % blk_size != 0:
        raise ValueError(
            f"last dimension {channels} is not divisible by block size {blk_size}"
        )
    x = quant_float.unflatten(-1, (-1, blk_size))
    x = x * scale_float.unsqueeze(-1)
    return x.flatten(-2, -1).to(torch.float32)


def quantize_to_e6m2(x: torch.Tensor) -> torch.Tensor:
    """Quantize *positive* values to nearest E6M2 representable value."""
    table = _E6M2_TABLE
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


def _dequantize_hif4(
    params: dict[str, torch.Tensor],
    original_shape: tuple[int, ...],
) -> torch.Tensor:
    """Reconstruct FP32 tensor from HiF4 params (inverse of quantize)."""
    dequant = (
        params["sign"]
        * params["mant"]
        * params["scale_lv2"]
        * params["scale_lv3"]
        * params["scale_factor"]
    )
    return dequant.reshape(original_shape).to(torch.float32)


def standard_hif4_quantize(x: torch.Tensor) -> dict[str, torch.Tensor]:
    """Standard HiF4 quantization per Algorithm 1 of the HiFloat4 paper.

    Direct-cast baseline: E6M2 block scale + greedy lv2/lv3 micro-exponents.
    Used by the scoring platform as the MSE_STD reference.
    """
    original_shape = x.shape
    C = int(original_shape[-1])
    n_blocks = C // BLK_SIZE

    x_flat = x.reshape(-1, C)
    N = x_flat.shape[0]
    x_blocks = x_flat.reshape(N, n_blocks, 8, 2, 4)

    vmax = x_blocks.abs().amax(dim=(-3, -2, -1))
    sf = quantize_to_e6m2(vmax / 7.0)                            # (N, n_blocks)
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


def _quantize_e2m1(x: torch.Tensor) -> torch.Tensor:
    """Quantize to nearest E2M1 value: {0, 0.5, 1, 1.5, 2, 3, 4, 6}."""
    x_abs = x.abs()
    sign = torch.sign(x)
    result = torch.zeros_like(x_abs)
    result = torch.where(x_abs >= 5.0,                       torch.full_like(x_abs, 6.0), result)
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
    x: torch.Tensor, blk_size: int = NVFP4_BLK
) -> tuple[torch.Tensor, torch.Tensor]:
    """Quantize FP32 to NVFP4 format. Returns (quant_float, scale_float).

    Used by the scoring platform for synthetic test-data generation.
    """
    x_blocks = x.unflatten(-1, (-1, blk_size))
    vmax = x_blocks.abs().amax(dim=-1, keepdim=True)
    scale = _quantize_e4m3(vmax / 6.0)
    scale = scale.clamp(min=2.0 ** (-16))
    normalized = x_blocks / scale
    quant_float = _quantize_e2m1(normalized)
    return quant_float.flatten(-2, -1), scale.squeeze(-1)
