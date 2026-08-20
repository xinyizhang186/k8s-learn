"""
模拟平台打分流程:
  1. 生成合成 NVFP4 数据 (linear + attention)
  2. 实现标准 HiF4 基线 (Algorithm 1 direct cast)
  3. 计算 MSE_STD / MSE_PLAYER / Score
"""
import sys, os, math, time
sys.path.insert(0, "/root/A_zxy/ALG/solution")
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn.functional as F

# 导入选手 solution
import solution as player_sol

torch.manual_seed(42)

# ======================================================================
# NVFP4 量化 (模拟平台数据)
# ======================================================================

E2M1_VALS = torch.tensor([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0])

def quantize_to_e2m1(x: torch.Tensor) -> torch.Tensor:
    """量化到 E2M1 值集 (模拟 NVFP4 carrier)。"""
    sign = torch.sign(x)
    abs_x = x.abs()
    dist = (abs_x.unsqueeze(-1) - E2M1_VALS).abs()
    idx = dist.argmin(dim=-1)
    return sign * E2M1_VALS[idx]

def quantize_to_e4m3(x: torch.Tensor) -> torch.Tensor:
    """量化到 E4M3 (FP8) 值集 (模拟 NVFP4 block scale)。
    简化: 使用有限的 E4M3 格点。
    """
    x = x.clamp(min=2.0**(-14), max=240.0)
    exp = torch.floor(torch.log2(x.clamp(min=2.0**(-14))))
    exp = exp.clamp(-14, 7)
    mantissa_steps = 2.0 ** (exp - 2)  # E4M3 有 3 mantissa bits
    quantized = torch.round(x / mantissa_steps) * mantissa_steps
    return quantized.clamp(min=2.0**(-14), max=240.0)

def make_nvfp4_pair(shape, sigma=0.5, outlier_prob=0.02, outlier_mag=5.0):
    """生成模拟 NVFP4 数据 (quant, scale)。
    加入少量 outlier 以模拟真实激活分布。
    """
    x = torch.randn(shape, dtype=torch.float32) * sigma
    # 注入 outlier
    mask = torch.rand(shape) < outlier_prob
    x = torch.where(mask, x * outlier_mag, x)

    # NVFP4 量化: block_size=16
    C = shape[-1]
    assert C % 16 == 0
    x_re = x.reshape(*shape[:-1], -1, 16)
    block_max = x_re.abs().amax(dim=-1) / 6.0  # 映射到 E2M1 最大值 6
    block_scale = quantize_to_e4m3(block_max)
    quant = quantize_to_e2m1(x_re / block_scale.unsqueeze(-1))
    return [quant.reshape(shape).contiguous(), block_scale.reshape(*shape[:-1], -1).contiguous()]

def dequant_nvfp4(quant, scale, blk=16):
    """NVFP4 反量化到 FP32。"""
    x = quant.unflatten(-1, (-1, blk))
    x = x * scale.unsqueeze(-1)
    return x.flatten(-2, -1).to(torch.float32)

# ======================================================================
# 标准 HiF4 基线 (Algorithm 1: direct cast)
# ======================================================================

def quantize_e6m2(x):
    """BF16 → E6M2."""
    x = x.double().clamp(min=2.0**(-48), max=49152.0)
    exp = torch.floor(torch.log2(x.clamp(min=2.0**(-126))))
    exp = exp.clamp(-48, 14)
    normalized = x / (2.0 ** exp)
    k = torch.round((normalized - 1.0) * 4.0).clamp(0, 3)
    return ((1.0 + k / 4.0) * (2.0 ** exp)).float()

def standard_hif4_quantize(w_fp):
    """标准 HiF4 量化 (Algorithm 1 direct cast)。
    返回与选手相同格式的 dict。
    """
    orig_shape = w_fp.shape
    C = orig_shape[-1]
    w = w_fp.reshape(*orig_shape[:-1], -1, 64)
    w_8224 = w.reshape(*w.shape[:-1], 8, 2, 4)

    # 三级树形归约
    max_4 = w_8224.abs().amax(dim=-1)  # (..., nb, 8, 2)
    max_8 = max_4.amax(dim=-1)          # (..., nb, 8)
    max_64 = max_8.amax(dim=-1)         # (..., nb)

    # E6M2 scale
    sf = quantize_e6m2(max_64 / 7.0)    # (..., nb)

    # E1_8 (scale_lv2): threshold >= 4
    sf_3 = sf.unsqueeze(-1)            # (..., nb, 1)
    scale_lv2 = torch.where(max_8 / sf_3 >= 4.0, 2.0, 1.0)  # (..., nb, 8)

    # E1_16 (scale_lv3): threshold >= 2
    sf_lv2 = sf_3 * scale_lv2          # (..., nb, 8)
    sf_lv2_4 = sf_lv2.unsqueeze(-1)    # (..., nb, 8, 1)
    scale_lv3 = torch.where(max_4 / sf_lv2_4 >= 2.0, 2.0, 1.0)  # (..., nb, 8, 2)

    # S1P2
    sf_5 = sf.reshape(*sf.shape, 1, 1, 1)          # (..., nb, 1, 1, 1)
    lv2_5 = scale_lv2.reshape(*scale_lv2.shape, 1, 1)  # (..., nb, 8, 1, 1)
    lv3_5 = scale_lv3.reshape(*scale_lv3.shape, 1)    # (..., nb, 8, 2, 1)
    total = sf_5 * lv2_5 * lv3_5                     # (..., nb, 8, 2, 1)
    w_scaled = w_8224 / total
    q = (w_scaled * 4.0).round().clamp(-7, 7) / 4.0

    sign = torch.sign(q)
    mant = q.abs()

    num_blocks = C // 64
    prefix = orig_shape[:-1]
    return {
        "scale_factor": sf.reshape(*prefix, num_blocks, 1, 1, 1).contiguous().float(),
        "scale_lv2": scale_lv2.reshape(*prefix, num_blocks, 8, 1, 1).contiguous().float(),
        "scale_lv3": scale_lv3.reshape(*prefix, num_blocks, 8, 2, 1).contiguous().float(),
        "sign": sign.reshape(*prefix, num_blocks, 8, 2, 4).contiguous().float(),
        "mant": mant.reshape(*prefix, num_blocks, 8, 2, 4).contiguous().float(),
    }

def hif4_dequant(params, orig_shape):
    """HiF4 参数反量化到 FP32。"""
    deq = (params["sign"] * params["mant"] * params["scale_lv3"]
           * params["scale_lv2"] * params["scale_factor"])
    return deq.reshape(orig_shape)

# ======================================================================
# 生成测试数据 & 运行评测
# ======================================================================

def run_linear_eval(M=128, K=256, n_calib=3, n_test=3, sigma=0.3):
    """单组 Linear 数据评测。"""
    # 生成 NVFP4 数据
    w_q, w_s = make_nvfp4_pair((M, K), sigma=0.1)
    calib = [make_nvfp4_pair((16, K), sigma=sigma) for _ in range(n_calib)]
    test = [make_nvfp4_pair((16, K), sigma=sigma) for _ in range(n_test)]

    # NVFP4 参考 (反量化后的 FP32)
    w_ref = dequant_nvfp4(w_q, w_s)
    test_ref = [dequant_nvfp4(tq, ts) for tq, ts in test]

    # ── 标准基线 ──
    w_std = hif4_dequant(standard_hif4_quantize(w_ref), w_ref.shape)
    test_std = [hif4_dequant(standard_hif4_quantize(tr), tr.shape) for tr in test_ref]

    # ── 选手 ──
    calib_pairs = [(cq, cs) for cq, cs in calib]
    result = player_sol.hif4_calibration_and_quantize_weight(w_q, w_s, calib_pairs)
    w_player = hif4_dequant(result["weight_params"], w_ref.shape)
    state = result["activation_state"]

    test_player = []
    for tq, ts in test:
        fresh_state = {k: (v.clone() if isinstance(v, torch.Tensor) else v) for k, v in state.items()}
        params = player_sol.hif4_dynamic_quantize_activation(tq, ts, fresh_state)
        test_player.append(hif4_dequant(params, (tq.shape)))

    # ── 计算 MSE ──
    # 参考: X_ref @ W_ref^T
    # 选手: X_player @ W_player^T
    # 标准: X_std @ W_std^T
    ref_outputs = [tr @ w_ref.T for tr in test_ref]
    std_outputs = [ts @ w_std.T for ts in test_std]
    player_outputs = [tp @ w_player.T for tp in test_player]

    mse_std_list = []
    mse_player_list = []
    for i in range(n_test):
        mse_std = ((std_outputs[i] - ref_outputs[i]) ** 2).mean().item()
        mse_player = ((player_outputs[i] - ref_outputs[i]) ** 2).mean().item()
        mse_std_list.append(mse_std)
        mse_player_list.append(mse_player)

    return mse_std_list, mse_player_list

def run_attention_eval(seq=32, q_heads=4, kv_heads=2, head_dim=64, n_calib=3, n_test=3, sigma=0.3):
    """单组 Attention 数据评测 (GQA)。"""
    q_C = q_heads * head_dim
    kv_C = kv_heads * head_dim

    calib_samples = []
    for _ in range(n_calib):
        calib_samples.append({
            "q": make_nvfp4_pair((seq, q_C), sigma=sigma),
            "k": make_nvfp4_pair((seq, kv_C), sigma=sigma),
            "v": make_nvfp4_pair((seq, kv_C), sigma=sigma),
        })

    test_samples = []
    for _ in range(n_test):
        test_samples.append({
            "q": make_nvfp4_pair((seq, q_C), sigma=sigma),
            "k": make_nvfp4_pair((seq, kv_C), sigma=sigma),
            "v": make_nvfp4_pair((seq, kv_C), sigma=sigma),
        })

    # 反量化参考
    def deq_sample(s):
        return {
            "q": dequant_nvfp4(*s["q"]),
            "k": dequant_nvfp4(*s["k"]),
            "v": dequant_nvfp4(*s["v"]),
        }
    calib_ref = [deq_sample(s) for s in calib_samples]
    test_ref = [deq_sample(s) for s in test_samples]

    # ── 标准 HiF4 基线 ──
    def std_quant_sample(s):
        return {
            "q": hif4_dequant(standard_hif4_quantize(s["q"]), s["q"].shape),
            "k": hif4_dequant(standard_hif4_quantize(s["k"]), s["k"].shape),
            "v": hif4_dequant(standard_hif4_quantize(s["v"]), s["v"].shape),
        }
    std_quant_calib = [std_quant_sample(s) for s in calib_ref]
    std_quant_test = [std_quant_sample(s) for s in test_ref]

    # ── 选手 ──
    calib_input = [{"q": s["q"], "k": s["k"], "v": s["v"]} for s in calib_samples]
    attn_result = player_sol.hif4_calibration_attention(
        calib_input, q_heads, kv_heads, head_dim
    )

    player_test = []
    for s in test_samples:
        result = {}
        for role in ("q", "k", "v"):
            tq, ts = s[role]
            num_heads = q_heads if role == "q" else kv_heads
            fresh_state = attn_result[f"{role}_state"]
            if isinstance(fresh_state, dict):
                fresh_state = {k: (v.clone() if isinstance(v, torch.Tensor) else v) for k, v in fresh_state.items()}
            func = getattr(player_sol, f"hif4_dynamic_quantize_{role}")
            params = func(tq, ts, num_heads, head_dim, fresh_state)
            result[role] = hif4_dequant(params, tq.shape)
        player_test.append(result)

    # ── Attention 计算 ──
    def attention(q, k, v, q_heads, kv_heads, head_dim):
        """GQA attention。"""
        seq = q.shape[0]
        q_re = q.reshape(seq, q_heads, head_dim).transpose(0, 1)  # (H_q, S, D)
        k_re = k.reshape(seq, kv_heads, head_dim).transpose(0, 1)  # (H_kv, S, D)
        v_re = v.reshape(seq, kv_heads, head_dim).transpose(0, 1)  # (H_kv, S, D)
        group = q_heads // kv_heads
        # 扩展 K/V 到 Q 的头数
        k_exp = k_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
        v_exp = v_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
        scores = torch.matmul(q_re, k_exp.transpose(-1, -2)) / math.sqrt(head_dim)
        attn = F.softmax(scores, dim=-1)
        out = torch.matmul(attn, v_exp)  # (H_q, S, D)
        return out.transpose(0, 1).reshape(seq, q_heads * head_dim)

    mse_std_list = []
    mse_player_list = []
    for i in range(n_test):
        ref_out = attention(test_ref[i]["q"], test_ref[i]["k"], test_ref[i]["v"], q_heads, kv_heads, head_dim)
        std_out = attention(std_quant_test[i]["q"], std_quant_test[i]["k"], std_quant_test[i]["v"], q_heads, kv_heads, head_dim)
        player_out = attention(player_test[i]["q"], player_test[i]["k"], player_test[i]["v"], q_heads, kv_heads, head_dim)

        mse_std = ((std_out - ref_out) ** 2).mean().item()
        mse_player = ((player_out - ref_out) ** 2).mean().item()
        mse_std_list.append(mse_std)
        mse_player_list.append(mse_player)

    return mse_std_list, mse_player_list

# ======================================================================
# 主程序
# ======================================================================

def main():
    print("=" * 60)
    print("模拟平台打分流程")
    print("=" * 60)

    all_scores = []

    # ─── Linear 评测 ───
    print("\n--- Linear 场景 ---")
    linear_configs = [
        (64, 128, 0.3),   # 小尺寸, 中等outlier
        (64, 256, 0.5),   # 中等尺寸, 较大outlier
        (128, 256, 0.2),  # 较大尺寸, 小outlier
    ]

    for ci, (M, K, sigma) in enumerate(linear_configs):
        t0 = time.time()
        mse_std, mse_player = run_linear_eval(M=M, K=K, sigma=sigma, n_calib=3, n_test=3)
        elapsed = time.time() - t0

        for i in range(len(mse_std)):
            score = (mse_std[i] - mse_player[i]) / max(mse_std[i], 1e-12)
            all_scores.append(score)
            tag = "↑" if score > 0 else "↓"
            print(f"  L{ci}.{i}: MSE_STD={mse_std[i]:.6e}, MSE_PLAYER={mse_player[i]:.6e}, "
                  f"Score={score:+.4f} {tag}  ({elapsed:.1f}s)")

    # ─── Attention 评测 ───
    print("\n--- Attention 场景 ---")
    attn_configs = [
        (32, 4, 2, 64, 0.3),  # 标准GQA
        (32, 8, 2, 64, 0.5),  # 更多Q头
        (64, 4, 2, 64, 0.2),  # 更长序列
    ]

    for ci, (seq, qh, kvh, hd, sigma) in enumerate(attn_configs):
        t0 = time.time()
        mse_std, mse_player = run_attention_eval(
            seq=seq, q_heads=qh, kv_heads=kvh, head_dim=hd, sigma=sigma,
            n_calib=3, n_test=3
        )
        elapsed = time.time() - t0

        for i in range(len(mse_std)):
            score = (mse_std[i] - mse_player[i]) / max(mse_std[i], 1e-12)
            all_scores.append(score)
            tag = "↑" if score > 0 else "↓"
            print(f"  A{ci}.{i}: MSE_STD={mse_std[i]:.6e}, MSE_PLAYER={mse_player[i]:.6e}, "
                  f"Score={score:+.4f} {tag}  ({elapsed:.1f}s)")

    # ─── 汇总 ───
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    pos = [s for s in all_scores if s > 0]
    neg = [s for s in all_scores if s <= 0]
    total = sum(all_scores)
    print(f"  总用例数: {len(all_scores)}")
    print(f"  正分用例: {len(pos)} (平均 {sum(pos)/len(pos):+.4f})" if pos else "  正分用例: 0")
    print(f"  负分用例: {len(neg)} (平均 {sum(neg)/len(neg):+.4f})" if neg else "  负分用例: 0")
    print(f"  总得分: {total:+.4f}")
    print(f"  平均得分: {total/len(all_scores):+.4f}")

if __name__ == "__main__":
    main()
