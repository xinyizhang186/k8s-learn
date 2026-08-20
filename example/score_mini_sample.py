"""用 mini_sample 数据运行完整打分流程 (标准基线 vs 选手)。"""
import sys, os, math
sys.path.insert(0, "/root/A_zxy/ALG/solution")
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn.functional as F
import solution as player_sol
from simulate_scoring import standard_hif4_quantize, hif4_dequant

MINI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_sample")


def dequant_nvfp4(quant, scale, blk=16):
    x = quant.unflatten(-1, (-1, blk))
    x = x * scale.unsqueeze(-1)
    return x.flatten(-2, -1).to(torch.float32)


def attention(q, k, v, q_heads, kv_heads, head_dim):
    seq = q.shape[0]
    q_re = q.reshape(seq, q_heads, head_dim).transpose(0, 1)
    k_re = k.reshape(seq, kv_heads, head_dim).transpose(0, 1)
    v_re = v.reshape(seq, kv_heads, head_dim).transpose(0, 1)
    group = q_heads // kv_heads
    k_exp = k_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
    v_exp = v_re.unsqueeze(1).expand(-1, group, -1, -1).reshape(q_heads, seq, head_dim)
    scores = torch.matmul(q_re, k_exp.transpose(-1, -2)) / math.sqrt(head_dim)
    attn = F.softmax(scores, dim=-1)
    out = torch.matmul(attn, v_exp)
    return out.transpose(0, 1).reshape(seq, q_heads * head_dim)


def run_linear_scoring():
    print("=" * 60)
    print("Linear 场景打分")
    print("=" * 60)

    linear_data = torch.load(os.path.join(MINI_DIR, "linear.pt"),
                             weights_only=True, map_location="cpu")

    all_scores = []
    for gi, group in enumerate(linear_data):
        w_q, w_s = group["weight"]
        calib_pairs = [(pair[0], pair[1]) for pair in group["calib_activation_list"]]
        test_pairs = [(pair[0], pair[1]) for pair in group["test_activation_list"]]

        # NVFP4 参考
        w_ref = dequant_nvfp4(w_q, w_s)
        test_ref = [dequant_nvfp4(tq, ts) for tq, ts in test_pairs]

        # 标准基线
        w_std = hif4_dequant(standard_hif4_quantize(w_ref), w_ref.shape)
        test_std = [hif4_dequant(standard_hif4_quantize(tr), tr.shape) for tr in test_ref]

        # 选手
        result = player_sol.hif4_calibration_and_quantize_weight(w_q, w_s, calib_pairs)
        w_player = hif4_dequant(result["weight_params"], w_ref.shape)
        state = result["activation_state"]
        test_player = []
        for tq, ts in test_pairs:
            fresh = {k: (v.clone() if isinstance(v, torch.Tensor) else v)
                      for k, v in state.items()}
            params = player_sol.hif4_dynamic_quantize_activation(tq, ts, fresh)
            test_player.append(hif4_dequant(params, tq.shape))

        for i in range(len(test_ref)):
            ref_out = test_ref[i] @ w_ref.T
            std_out = test_std[i] @ w_std.T
            player_out = test_player[i] @ w_player.T

            mse_std = ((std_out - ref_out) ** 2).mean().item()
            mse_player = ((player_out - ref_out) ** 2).mean().item()
            score = (mse_std - mse_player) / max(mse_std, 1e-12)
            all_scores.append(score)
            tag = "↑" if score > 0 else "↓"
            print(f"  L{gi}.{i}: MSE_STD={mse_std:.4e}  MSE_PLA={mse_player:.4e}  "
                  f"Score={score:+.4f} {tag}")

    return all_scores


def run_attention_scoring():
    print("\n" + "=" * 60)
    print("Attention 场景打分")
    print("=" * 60)

    attn_data = torch.load(os.path.join(MINI_DIR, "attn.pt"),
                           weights_only=True, map_location="cpu")

    all_scores = []
    for gi, group in enumerate(attn_data):
        qh = group["q_num_heads"]
        kvh = group["kv_num_heads"]
        hd = group["head_dim"]

        # 校准 & 测试数据 (NVFP4 格式)
        calib_input = [s for s in group["calib"]]
        test_input = [s for s in group["test"]]

        # NVFP4 参考
        def deq_s(s):
            return {"q": dequant_nvfp4(*s["q"]),
                    "k": dequant_nvfp4(*s["k"]),
                    "v": dequant_nvfp4(*s["v"])}
        test_ref = [deq_s(s) for s in test_input]

        # 标准基线
        def std_s(s):
            return {"q": hif4_dequant(standard_hif4_quantize(deq_s(s)["q"]),
                                       deq_s(s)["q"].shape),
                    "k": hif4_dequant(standard_hif4_quantize(deq_s(s)["k"]),
                                       deq_s(s)["k"].shape),
                    "v": hif4_dequant(standard_hif4_quantize(deq_s(s)["v"]),
                                       deq_s(s)["v"].shape)}
        test_std = [std_s(s) for s in test_input]

        # 选手
        attn_result = player_sol.hif4_calibration_attention(calib_input, qh, kvh, hd)
        test_player = []
        for s in test_input:
            result = {}
            for role in ("q", "k", "v"):
                tq, ts = s[role]
                num_heads = qh if role == "q" else kvh
                fresh = attn_result[f"{role}_state"]
                if isinstance(fresh, dict):
                    fresh = {k: (v.clone() if isinstance(v, torch.Tensor) else v)
                             for k, v in fresh.items()}
                func = getattr(player_sol, f"hif4_dynamic_quantize_{role}")
                params = func(tq, ts, num_heads, hd, fresh)
                result[role] = hif4_dequant(params, tq.shape)
            test_player.append(result)

        for i in range(len(test_ref)):
            ref_out = attention(test_ref[i]["q"], test_ref[i]["k"], test_ref[i]["v"],
                                qh, kvh, hd)
            std_out = attention(test_std[i]["q"], test_std[i]["k"], test_std[i]["v"],
                                qh, kvh, hd)
            player_out = attention(test_player[i]["q"], test_player[i]["k"],
                                   test_player[i]["v"], qh, kvh, hd)

            mse_std = ((std_out - ref_out) ** 2).mean().item()
            mse_player = ((player_out - ref_out) ** 2).mean().item()
            score = (mse_std - mse_player) / max(mse_std, 1e-12)
            all_scores.append(score)
            tag = "↑" if score > 0 else "↓"
            print(f"  A{gi}.{i}: MSE_STD={mse_std:.4e}  MSE_PLA={mse_player:.4e}  "
                  f"Score={score:+.4f} {tag}")

    return all_scores


def main():
    torch.manual_seed(0)
    linear_scores = run_linear_scoring()
    attn_scores = run_attention_scoring()
    all_scores = linear_scores + attn_scores

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    pos = [s for s in all_scores if s > 0]
    neg = [s for s in all_scores if s <= 0]
    total = sum(all_scores)
    print(f"  总用例数: {len(all_scores)}")
    if pos:
        print(f"  正分用例: {len(pos)} (平均 {sum(pos)/len(pos):+.4f})")
    if neg:
        print(f"  负分用例: {len(neg)} (平均 {sum(neg)/len(neg):+.4f})")
    print(f"  总得分:   {total:+.4f}")
    print(f"  平均得分: {total/len(all_scores):+.4f}")


if __name__ == "__main__":
    main()
