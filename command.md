# 运行命令

## 前置条件

```bash
cd /root/A_zxy/ALG/check/example
```

所有命令均在 `/root/A_zxy/ALG/check/example` 目录下执行。

---

## 1. 生成模拟测试样本

```bash
python3 generate_mini_sample.py
```

在 `mini_sample/` 下生成 `linear.pt` 和 `attn.pt`。

---

## 2. self_check.py — HiF4 参数格式校验

```bash
python3 self_check.py \
  --solution_dir /root/A_zxy/ALG/solution \
  --datasets_dir /root/A_zxy/ALG/check/example/mini_sample
```

检查选手输出的 5 个 HiF4 参数张量（scale_factor / scale_lv2 / scale_lv3 / sign / mant）是否符合格式约束，以及 activation_state / q_state / k_state / v_state 是否符合 frozen_state 约束。

---

## 3. 模拟平台打分（mini_sample 数据）

```bash
python3 score_mini_sample.py
```

加载 `mini_sample/linear.pt` 和 `mini_sample/attn.pt`，调用选手 6 个 API 函数，计算每个用例的：

```
Score = (MSE_STD - MSE_PLAYER) / MSE_STD
```

其中 MSE_STD 为标准 HiF4 基线（Algorithm 1 direct cast）的输出 MSE，MSE_PLAYER 为选手输出的 MSE。

---

## 4. 模拟平台打分（合成随机数据）

```bash
python3 simulate_scoring.py
```

内部生成随机 NVFP4 数据（含 outlier），运行 3 组 Linear + 3 组 Attention 场景，输出每组的 MSE_STD / MSE_PLAYER / Score 及汇总。

---

## 5. 快速格式验证（无需 mini_sample 数据）

```bash
python3 test_solution.py
```

内部生成小尺寸随机数据，直接调用 `validate_hif4_params` / `validate_frozen_state` 验证输出格式，不计算 MSE。
