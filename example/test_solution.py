"""快速验证 solution.py 的输出格式是否正确。"""
import sys, os
# 指向真正的 solution 目录
sys.path.insert(0, "/root/A_zxy/ALG/solution")
sys.path.insert(0, os.path.dirname(__file__))  # for self_check

import torch
import importlib
import solution as sol

# 重新导入（防止缓存）
importlib.reload(sol)

torch.manual_seed(0)

def make_nvfp4_pair(shape, scale_range=(0.01, 0.5)):
    """生成随机 NVFP4 数据 (quant, scale)。"""
    quant = torch.randn(shape, dtype=torch.float32)
    # 量化到 E2M1 值集 {0, ±0.5, ±1, ±1.5, ±2, ±3, ±4, ±6}
    e2m1_vals = torch.tensor([0, 0.5, 1, 1.5, 2, 3, 4, 6], dtype=torch.float32)
    # 对每个值取最近的 E2M1 值
    for _ in range(1):
        abs_q = quant.abs().unsqueeze(-1)
        dist = (abs_q - e2m1_vals).abs()
        idx = dist.argmin(dim=-1)
        quant = e2m1_vals[idx] * torch.sign(quant)

    C = shape[-1]
    assert C % 16 == 0
    scale = torch.empty(shape[:-1] + (C // 16,), dtype=torch.float32).uniform_(*scale_range)
    return [quant, scale]

# ─── 生成合成数据 ───

print("=" * 60)
print("Linear test")
print("=" * 60)

M, K = 64, 128  # 小尺寸测试
weight_pair = make_nvfp4_pair((M, K))
calib_list = [make_nvfp4_pair((4, K)) for _ in range(3)]
test_list = [make_nvfp4_pair((4, K)) for _ in range(2)]

print(f"  weight: {weight_pair[0].shape}, scale: {weight_pair[1].shape}")
print(f"  calib acts: {len(calib_list)} × {calib_list[0][0].shape}")
print(f"  test acts:  {len(test_list)} × {test_list[0][0].shape}")

# 调用校准
result = sol.hif4_calibration_and_quantize_weight(
    weight_pair[0], weight_pair[1], calib_list
)
wp = result["weight_params"]
state = result["activation_state"]

print(f"  weight_params keys: {list(wp.keys())}")
for k, v in wp.items():
    print(f"    {k}: shape={v.shape}, dtype={v.dtype}")
print(f"  activation_state keys: {list(state.keys()) if isinstance(state, dict) else type(state)}")
print(f"  smooth_scale shape: {state['smooth_scale'].shape}")
print(f"  hadamard shape: {state['hadamard'].shape}")

# 验证格式
from self_check import validate_hif4_params, validate_frozen_state, validate_linear_calibration_result

w_shape = weight_pair[0].shape
errors = validate_linear_calibration_result(result, w_shape, "linear_test")
if errors:
    print("  VALIDATION ERRORS:")
    for e in errors:
        print(f"    {e}")
else:
    print("  ✓ calibration result PASSED validation")

# 调用动态量化
for i, (aq, asc) in enumerate(test_list):
    fresh_state = {k: (v.clone() if isinstance(v, torch.Tensor) else v) for k, v in state.items()}
    act_params = sol.hif4_dynamic_quantize_activation(aq, asc, fresh_state)
    errors = validate_hif4_params(act_params, aq.shape, f"act_test_{i}")
    if errors:
        print(f"  act test {i} ERRORS:")
        for e in errors:
            print(f"    {e}")
    else:
        print(f"  ✓ act test {i} PASSED validation")

# ─── Attention 测试 ───
print()
print("=" * 60)
print("Attention test")
print("=" * 60)

q_num_heads = 4
kv_num_heads = 2
head_dim = 64
seq = 32

q_C = q_num_heads * head_dim     # 256
kv_C = kv_num_heads * head_dim   # 128

calib_attn = []
for _ in range(3):
    calib_attn.append({
        "q": make_nvfp4_pair((seq, q_C)),
        "k": make_nvfp4_pair((seq, kv_C)),
        "v": make_nvfp4_pair((seq, kv_C)),
    })

test_attn = []
for _ in range(2):
    test_attn.append({
        "q": make_nvfp4_pair((seq, q_C)),
        "k": make_nvfp4_pair((seq, kv_C)),
        "v": make_nvfp4_pair((seq, kv_C)),
    })

# 校准
attn_result = sol.hif4_calibration_attention(
    calib_attn, q_num_heads, kv_num_heads, head_dim
)
print(f"  q_state keys: {list(attn_result['q_state'].keys()) if isinstance(attn_result['q_state'], dict) else 'None'}")
print(f"  k_state keys: {list(attn_result['k_state'].keys()) if isinstance(attn_result['k_state'], dict) else 'None'}")
print(f"  v_state keys: {list(attn_result['v_state'].keys()) if isinstance(attn_result['v_state'], dict) else 'None'}")

# 验证 state
from self_check import validate_attention_calibration_result
attn_errors = validate_attention_calibration_result(attn_result, "attn_test")
if attn_errors:
    print("  STATE VALIDATION ERRORS:")
    for e in attn_errors:
        print(f"    {e}")
else:
    print("  ✓ attention calibration state PASSED validation")

# 动态 Q/K/V
for i, sample in enumerate(test_attn):
    for role in ("q", "k", "v"):
        quant, scale = sample[role]
        num_heads = q_num_heads if role == "q" else kv_num_heads
        state_key = f"{role}_state"
        fresh_state = attn_result[state_key]
        if isinstance(fresh_state, dict):
            fresh_state = {k: (v.clone() if isinstance(v, torch.Tensor) else v) for k, v in fresh_state.items()}

        func = getattr(sol, f"hif4_dynamic_quantize_{role}")
        params = func(quant, scale, num_heads, head_dim, fresh_state)
        errors = validate_hif4_params(params, quant.shape, f"attn_test_{i}_{role}")
        if errors:
            print(f"  {role} test {i} ERRORS:")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"  ✓ {role} test {i} PASSED validation")

print()
print("=" * 60)
print("All format checks done.")
print("=" * 60)
