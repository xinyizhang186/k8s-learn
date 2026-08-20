"""快速对比: 不同配置下的 MSE 表现。"""
import sys, os, math, time
sys.path.insert(0, "/root/A_zxy/ALG/solution")
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn.functional as F
import importlib
import solution as sol

# 导入模拟工具
from simulate_scoring import (
    make_nvfp4_pair, dequant_nvfp4, quantize_e6m2,
    standard_hif4_quantize, hif4_dequant, run_linear_eval, run_attention_eval
)

def main():
    torch.manual_seed(42)

    configs = [
        ("NO  pre-transform", False, False),
        ("Hadamard only",     False, True),
        ("SmoothQuant only",  True,  False),
        ("SmoothQuant+Hadamard", True, True),
    ]

    for name, use_sq, use_hd in configs:
        sol.USE_SMOOTHQUANT = use_sq
        sol.USE_HADAMARD = use_hd
        importlib.reload(sol)
        sol.USE_SMOOTHQUANT = use_sq
        sol.USE_HADAMARD = use_hd

        print(f"\n{'='*60}")
        print(f"Config: {name}  (SQ={use_sq}, HD={use_hd})")
        print(f"{'='*60}")

        all_scores = []

        # Linear
        for ci, (M, K, sigma) in enumerate([(64,128,0.3), (64,256,0.5), (128,256,0.2)]):
            mse_std, mse_player = run_linear_eval(M=M, K=K, sigma=sigma, n_calib=3, n_test=3)
            for i in range(len(mse_std)):
                score = (mse_std[i] - mse_player[i]) / max(mse_std[i], 1e-12)
                all_scores.append(score)
                tag = "↑" if score > 0 else "↓"
                print(f"  L{ci}.{i}: STD={mse_std[i]:.4e} PLA={mse_player[i]:.4e} S={score:+.4f} {tag}")

        # Attention
        for ci, (seq, qh, kvh, hd, sigma) in enumerate([(32,4,2,64,0.3), (32,8,2,64,0.5), (64,4,2,64,0.2)]):
            mse_std, mse_player = run_attention_eval(seq=seq, q_heads=qh, kv_heads=kvh, head_dim=hd, sigma=sigma, n_calib=3, n_test=3)
            for i in range(len(mse_std)):
                score = (mse_std[i] - mse_player[i]) / max(mse_std[i], 1e-12)
                all_scores.append(score)
                tag = "↑" if score > 0 else "↓"
                print(f"  A{ci}.{i}: STD={mse_std[i]:.4e} PLA={mse_player[i]:.4e} S={score:+.4f} {tag}")

        pos = [s for s in all_scores if s > 0]
        neg = [s for s in all_scores if s <= 0]
        total = sum(all_scores)
        print(f"  TOTAL: {total:+.4f}  (pos={len(pos)}, neg={len(neg)}, avg={total/len(all_scores):+.4f})")

if __name__ == "__main__":
    main()
