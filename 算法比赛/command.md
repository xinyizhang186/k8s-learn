# 运行命令

## 前置条件

```bash
cd /root/A_zxy/ALG/check/example
```

所有命令均在 `/root/A_zxy/ALG/check/example` 目录下执行。

---

## 目录结构

```
/root/A_zxy/ALG/
├── solution/
│   └── solution.py              # 选手提交的量化算法（6个API函数）
├── check/example/
│   ├── self_check.py            # HiF4 参数格式校验
│   ├── generate_mini_sample.py  # 生成 mini_sample 测试数据
│   ├── simulate_scoring.py      # 模拟平台打分（合成随机数据）
│   ├── mini_sample/             # 生成的测试数据（linear.pt / attn.pt）
│   └── solution/
│       └── solution_template.py # 接口模板（仅供参考）
├── idea.md                      # 算法设计思路
└── 算法大赛.md                   # 任务书
```

---

## 1. 生成 mini_sample 测试数据

```bash
python3 generate_mini_sample.py
```

在 `mini_sample/` 下生成 `linear.pt` 和 `attn.pt`，各包含 2 组数据，用于 `self_check.py` 格式校验。

---

## 2. self_check.py — HiF4 参数格式校验

```bash
python3 self_check.py \
  --solution_dir /root/A_zxy/ALG/solution \
  --datasets_dir /root/A_zxy/ALG/check/example/mini_sample
```

校验内容：
- 5 个 HiF4 参数张量（scale_factor / scale_lv2 / scale_lv3 / sign / mant）的 shape、数值范围、E6M2 格式约束
- activation_state / q_state / k_state / v_state 的 frozen_state 约束（类型、深度、节点数）
- 6 个 API 函数能否正常调用并返回合法参数

---

## 3. simulate_scoring.py — 模拟平台打分

```bash
python3 simulate_scoring.py
```

内部生成随机 NVFP4 数据（含 outlier），运行 3 组 Linear + 3 组 Attention 场景。

对每个测试用例计算：

```
Score = (MSE_STD - MSE_PLAYER) / MSE_STD
```

其中：
- MSE_STD = 标准 HiF4 基线（Algorithm 1 direct cast）的输出 MSE
- MSE_PLAYER = 选手 solution.py 输出的 MSE

输出每组的 MSE_STD / MSE_PLAYER / Score、校准与动态量化耗时、汇总总分。

---

## 快速参考

| 命令 | 用途 | 依赖 mini_sample 数据 |
|------|------|------------------------|
| `generate_mini_sample.py` | 生成测试数据 | 否 |
| `self_check.py` | 参数格式校验 | 是 |
| `simulate_scoring.py` | 模拟打分 | 否（内部生成数据） |
