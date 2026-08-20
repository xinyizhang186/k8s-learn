"""生成 mini_sample 测试数据 (linear.pt + attn.pt)。

数据格式遵循 self_check.py 的 _normalize_nvfp4_pair / _normalize_linear_group / _normalize_attention_group 约定:
  - NVFP4 pair = [quant_tensor, scale_tensor]
  - quant 末维 % 16 == 0 (NVFP4 block), 且 % 64 == 0 (HiF4 block)
  - scale 末维 = quant 末维 // 16
  - E2M1 量化值: {0, ±0.5, ±1, ±1.5, ±2, ±3, ±4, ±6}
  - E4M3 scale: 正浮点数
"""
import os
import math
import torch

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_sample")

E2M1_VALS = torch.tensor([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0], dtype=torch.float32)


def quantize_to_e2m1(x: torch.Tensor) -> torch.Tensor:
    sign = torch.sign(x)
    abs_x = x.abs()
    dist = (abs_x.unsqueeze(-1) - E2M1_VALS).abs()
    idx = dist.argmin(dim=-1)
    return sign * E2M1_VALS[idx]


def quantize_to_e4m3(x: torch.Tensor) -> torch.Tensor:
    x = x.clamp(min=2.0 ** (-14), max=240.0)
    exp = torch.floor(torch.log2(x.clamp(min=2.0 ** (-14))))
    exp = exp.clamp(-14, 7)
    step = 2.0 ** (exp - 2)
    q = torch.round(x / step) * step
    return q.clamp(min=2.0 ** (-14), max=240.0)


def make_nvfp4_pair(shape, sigma=0.3, outlier_prob=0.02, outlier_mag=5.0):
    """生成 NVFP4 (quant, scale) 数据对。"""
    x = torch.randn(shape, dtype=torch.float32) * sigma
    mask = torch.rand(shape) < outlier_prob
    x = torch.where(mask, x * outlier_mag, x)

    C = shape[-1]
    assert C % 16 == 0, f"last dim {C} not divisible by 16"

    x_re = x.reshape(*shape[:-1], -1, 16)
    block_max = x_re.abs().amax(dim=-1) / 6.0
    block_scale = quantize_to_e4m3(block_max)
    quant = quantize_to_e2m1(x_re / block_scale.unsqueeze(-1))

    return [
        quant.reshape(shape).contiguous(),
        block_scale.reshape(*shape[:-1], -1).contiguous(),
    ]


def make_linear_groups():
    """生成 2 组 Linear 数据。"""
    groups = []

    # Group 0: 小尺寸 [64, 128]
    g0 = {
        "weight": make_nvfp4_pair((64, 128), sigma=0.1, outlier_prob=0.01),
        "calib_activation_list": [
            make_nvfp4_pair((16, 128), sigma=0.3)
            for _ in range(3)
        ],
        "test_activation_list": [
            make_nvfp4_pair((16, 128), sigma=0.3)
            for _ in range(3)
        ],
    }
    groups.append(g0)

    # Group 1: 中等尺寸 [128, 256]
    g1 = {
        "weight": make_nvfp4_pair((128, 256), sigma=0.1, outlier_prob=0.01),
        "calib_activation_list": [
            make_nvfp4_pair((32, 256), sigma=0.5)
            for _ in range(3)
        ],
        "test_activation_list": [
            make_nvfp4_pair((32, 256), sigma=0.5)
            for _ in range(3)
        ],
    }
    groups.append(g1)

    return groups


def make_attention_groups():
    """生成 2 组 Attention (GQA) 数据。"""
    groups = []

    # Group 0: 4 Q heads, 2 KV heads, head_dim=64
    q_num_heads_0 = 4
    kv_num_heads_0 = 2
    head_dim_0 = 64
    seq_0 = 32
    q_C_0 = q_num_heads_0 * head_dim_0   # 256
    kv_C_0 = kv_num_heads_0 * head_dim_0  # 128

    def make_attn_sample(sigma=0.3):
        return {
            "q": make_nvfp4_pair((seq_0, q_C_0), sigma=sigma),
            "k": make_nvfp4_pair((seq_0, kv_C_0), sigma=sigma),
            "v": make_nvfp4_pair((seq_0, kv_C_0), sigma=sigma),
        }

    g0 = {
        "q_num_heads": q_num_heads_0,
        "kv_num_heads": kv_num_heads_0,
        "head_dim": head_dim_0,
        "calib": [make_attn_sample(0.3) for _ in range(3)],
        "test": [make_attn_sample(0.3) for _ in range(3)],
    }
    groups.append(g0)

    # Group 1: 8 Q heads, 2 KV heads, head_dim=64
    q_num_heads_1 = 8
    kv_num_heads_1 = 2
    head_dim_1 = 64
    seq_1 = 32
    q_C_1 = q_num_heads_1 * head_dim_1   # 512
    kv_C_1 = kv_num_heads_1 * head_dim_1  # 128

    def make_attn_sample_1(sigma=0.3):
        return {
            "q": make_nvfp4_pair((seq_1, q_C_1), sigma=sigma),
            "k": make_nvfp4_pair((seq_1, kv_C_1), sigma=sigma),
            "v": make_nvfp4_pair((seq_1, kv_C_1), sigma=sigma),
        }

    g1 = {
        "q_num_heads": q_num_heads_1,
        "kv_num_heads": kv_num_heads_1,
        "head_dim": head_dim_1,
        "calib": [make_attn_sample_1(0.5) for _ in range(3)],
        "test": [make_attn_sample_1(0.5) for _ in range(3)],
    }
    groups.append(g1)

    return groups


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    torch.manual_seed(42)

    linear_data = make_linear_groups()
    attn_data = make_attention_groups()

    linear_path = os.path.join(OUTPUT_DIR, "linear.pt")
    attn_path = os.path.join(OUTPUT_DIR, "attn.pt")

    torch.save(linear_data, linear_path)
    torch.save(attn_data, attn_path)

    print(f"Saved {linear_path}")
    print(f"  groups: {len(linear_data)}")
    for i, g in enumerate(linear_data):
        w_q, w_s = g["weight"]
        print(f"    group {i}: weight={w_q.shape}, scale={w_s.shape}, "
              f"calib={len(g['calib_activation_list'])}, test={len(g['test_activation_list'])}")

    print(f"\nSaved {attn_path}")
    print(f"  groups: {len(attn_data)}")
    for i, g in enumerate(attn_data):
        s = g["calib"][0]
        print(f"    group {i}: q_heads={g['q_num_heads']}, kv_heads={g['kv_num_heads']}, "
              f"head_dim={g['head_dim']}, "
              f"q={s['q'][0].shape}, k={s['k'][0].shape}, v={s['v'][0].shape}, "
              f"calib={len(g['calib'])}, test={len(g['test'])}")


if __name__ == "__main__":
    main()
