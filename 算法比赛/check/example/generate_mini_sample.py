#!/usr/bin/env python3
"""generate_mini_sample.py — 生成 mini_sample/linear.pt 和 attn.pt"""
import os
import sys
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "solution"))
from solution import quantize_nvfp4

OUT_DIR = os.path.join(os.path.dirname(__file__), "mini_sample")
os.makedirs(OUT_DIR, exist_ok=True)


def gen_linear(n_groups=2):
    data = []
    for gi in range(n_groups):
        torch.manual_seed(1000 + gi)
        M, K, T = 128, 256, 64
        W = torch.randn(M, K) * 0.02
        Wq, Ws = quantize_nvfp4(W)
        calib, tests = [], []
        for i in range(5 + 5):
            X = torch.randn(T, K) * 0.5
            mask = torch.rand(T, K) < 0.01
            X[mask] *= 8
            q, s = quantize_nvfp4(X)
            (calib if i < 5 else tests).append([q, s])
        data.append({
            "weight": [Wq, Ws],
            "calib_activation_list": calib,
            "test_activation_list": tests,
        })
    return data


def gen_attention(n_groups=2):
    data = []
    for gi in range(n_groups):
        torch.manual_seed(2000 + gi)
        qh, kvh, hd, S = 16, 4, 64, 64
        def mk():
            Q = torch.randn(S, qh * hd) * 0.5
            K = torch.randn(S, kvh * hd) * 0.5
            V = torch.randn(S, kvh * hd) * 0.5
            for x in (Q, K, V):
                m = torch.rand_like(x) < 0.01
                x[m] *= 5
            return {"q": quantize_nvfp4(Q), "k": quantize_nvfp4(K), "v": quantize_nvfp4(V)}
        calib = [mk() for _ in range(5)]
        tests = [mk() for _ in range(5)]
        data.append({
            "q_num_heads": qh, "kv_num_heads": kvh, "head_dim": hd,
            "calib": calib, "test": tests,
        })
    return data


if __name__ == "__main__":
    torch.save(gen_linear(), os.path.join(OUT_DIR, "linear.pt"))
    torch.save(gen_attention(), os.path.join(OUT_DIR, "attn.pt"))
    print(f"Generated mini_sample in {OUT_DIR}")
