# NVFP4 → HiF4 量化转换算法思路

## 1. 问题分析

### 1.1 核心任务
将NVFP4格式数据（E2M1元素 + E4M3 block scale，block size=16）转换为HiF4格式（E6M2 scale_factor + E1_8微指数 + E1_16微指数 + S1P2元素，block size=64），使得反量化后的MatMul/Attention输出的MSE尽可能小。

### 1.2 格式对比

| 特性 | NVFP4 | HiF4 |
|------|-------|------|
| 元素格式 | E2M1: {0, 0.5, 1, 1.5, 2, 3, 4, 6} | S1P2: {0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75} |
| Block size | 16 | 64 |
| Scale格式 | E4M3 (FP8) + FP32 tensor scale | E6M2 (8-bit FP) |
| 微指数 | 无 | E1_8 (8个1-bit) + E1_16 (16个1-bit) |
| 全局动态范围 | 22 binades | 69 binades |
| 局部动态范围 | 3.58 binades | 4.81 binades |

### 1.3 选手输出约束
每个矩阵输出5个参数张量：
- `scale_factor`: E6M2格式，每64个元素共享1个
- `scale_lv2`: ∈ {1, 2}，每8个元素共享1个（共8个）
- `scale_lv3`: ∈ {1, 2}，每4个元素共享1个（共16个）
- `sign`: ∈ {-1, 0, 1}，每元素1个
- `mant`: ∈ {0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75}，每元素1个

反量化公式：`x_hat = sign * mant * scale_lv3 * scale_lv2 * scale_factor`

### 1.4 标准基线（Algorithm 1 直接转换）
HiF4论文Algorithm 1的转换流程：
1. 三级树形归约求峰值：64→16→8→1
2. `scale_factor = E6M2_quantize(Vmax / 7)` （7 = 2²×1.75为组内最大值）
3. `E1_8[j] = 1 if (V8[j] / scale_factor ≥ 4) else 0` （阈值判定）
4. `E1_16[k] = 1 if (V16[k] / (scale_factor × 2^E1_8) ≥ 2) else 0`
5. `S1P2 = round_to_nearest(V64 / (scale_factor × 2^E1_8 × 2^E1_16))`

### 1.5 基线缺陷分析
1. **E6M2 scale非最优**：`Vmax/7`仅保证峰值不溢出，非MSE最优
2. **微指数阈值固定**：≥4和≥2的阈值不适应不同分布，贪心选择不是联合最优
3. **舍入策略简单**：round-to-nearest不考虑块内误差补偿
4. **无输出敏感度**：优化重建MSE而非输出MSE（Linear的`||X(W_hat-W)^T||²`，Attention的`||P·E_V||²`）
5. **无outlier管理**：未利用SmoothQuant式通道平衡

## 2. 算法设计

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────┐
│               离线校准阶段 (Calibration)                   │
│                                                           │
│  NVFP4数据 → FP32反量化                                   │
│  Linear: SmoothQuant alpha扫描({None,0.5}) + Hadamard旋转 │
│          + 校准激活 lambda_j 加权 + exact微指数             │
│  Attn:   V的P^T P rho_t计算                               │
│          + Q/K Hadamard矩阵生成                            │
│                                                           │
│  Linear:  输出 weight_params + activation_state            │
│           (state: hadamard, importance, smooth_scale)     │
│  Attn:    输出 q/k/v_state                                │
│           (q/k: hadamard, v: rho/rho_mean/seq)           │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│            在线动态量化阶段 (Dynamic)                       │
│                                                           │
│  NVFP4激活 → FP32反量化 → SmoothQuant D^-1 → Hadamard旋转  │
│              → E6M2对称窗口搜索 + exact微指数               │
│                                                           │
│  Linear A: diag(W_hat^T W_hat) 加权                        │
│  Q / K:   Hadamard(若state有)                              │
│  V:       P^T P 的 rho_t token级加权                       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心技术1：Exact微指数搜索（4组合联合优化）

**原理**：标准基线使用固定阈值（≥4和≥2）判定微指数。旧方案用贪心先选lv2再选lv3，不是联合最优。

**精确解**：对每个4元素子组g，令L_g(a,b)为使用(E1_8=a, E1_16=b)的加权平方误差。精确解为：
```
F(a) = Σ_g min_b L_g(a,b)    # 先对每个子组取b的最优
a* = argmin_a F(a)            # 再选a
b_g* = argmin_b L_g(a*, b)    # 最后定每个子组的b
```

**关键优化**：(lv2=1,lv3=2)和(lv2=2,lv3=1)共享总scale 2×sf，因此只需3次量化即可覆盖全部4种组合。

**不劣证明**：精确搜索在同一个有限可行集{(0,0),(0,1),(1,0),(1,1)}上取最小值，而贪心解只是该集合中的一个点，故逐块严格不劣。

### 2.3 核心技术2：E6M2对称窗口Scale Search

**原理**：标准基线使用`Vmax/7`作为scale，仅保证峰值映射。从MSE角度，最优scale可能更小（主动裁剪少数离群点）。

**算法**：以`amax/7`为中心，在E6M2编码索引上取对称窗口`idx + [-half, ..., +half]`。

**嵌套不劣证明**：候选集合S_new ⊇ S_old时，min_{s∈S_new} L(s) ≤ min_{s∈S_old} L(s)。

**自适应候选数**：
- numel > 4M → 5候选（大矩阵省时间）
- numel > 1M → 7候选
- else → 9候选（小矩阵提精度）
- Q/K/V固定9候选（兼顾精度与时间预算）

### 2.4 核心技术3：随机Hadamard旋转

**原理**：对64元素block施加64×64随机Hadamard矩阵，将outlier能量分散到组内所有元素。

**公式**：
```
H = S @ H_64    # S为随机±1对角矩阵, H_64为Sylvester构造的Hadamard矩阵
W_rot = W @ H   # 旋转权重
X_rot = X @ H   # 旋转激活
```

**数学保证**：`X_rot @ W_rot^T = X @ H @ H^T @ W^T = X @ W^T`（因H正交）

**Block对齐**：H_64作用于每个连续64元素block，与HiF4的block size=64完美对齐。

**Attention场景**：Q和K使用相同的H（保证Q@K^T不变），V不旋转（无法保持attention输出）。

**防御机制**：head_dim非64倍数时自动禁用Q/K旋转，避免64元素块跨越head边界破坏Q@K^T等价性。

### 2.5 核心技术4：Linear输出敏感度加权

**原理**：评分目标是`||X(W_hat-W)^T||²`（Linear输出MSE），而非重建MSE`||W_hat-W||²`。二者一般不等价。

**权重重要性**：
```
(1/n)||X E_W^T||² = tr(E_W C_X E_W^T) ≈ Σ_j λ_j (E_W[:,j])²
```
其中λ_j = mean(X_rot[:,j]²)来自校准激活。在Hadamard旋转坐标中C_X近似对角时这是精确最小化。

**激活重要性**：
```
(1/n)||E_X W_hat^T||² ≈ Σ_j w_diag_j (E_X[:,j])²
```
其中w_diag_j = diag(W_hat_rot^T W_hat_rot)来自已量化权重。

### 2.6 核心技术5：SmoothQuant对角平衡

**原理**：对线性层的输入通道施加可逆对角变换D，在activation和weight之间迁移量化难度。

**公式**：
```
X' = X D^(-1),   W' = W D
```
无量化时严格有`X' W'^T = X W^T`。

**SmoothQuant scale**：
```
D_j(α) = max_abs(X[:,j])^α / max_abs(W[:,j])^(1-α)
α ∈ {None(不平滑), 0.5}  (≤4M元素的矩阵)
α ∈ {None}                (大矩阵>4M, 省时间)
```

**候选选择**：用校准集加权重建MSE proxy选择最优α，包含α=None保证不劣。

**实现优化**：alpha扫描使用权重行子采样(256行) + 3候选快速proxy，避免大矩阵全量化。

### 2.7 核心技术6：Attention V的P^T P加权

**原理**：固定Q/K时，V引起的精确输出误差为：
```
||O_hat - O||² = ||P E_V||² = tr(E_V^T P^T P E_V)
```
其中P = softmax(QK^T/√d)。因此敏感度来自P^T P的列范数平方ρ_t = Σ_i P[i,t]²，而非V的数值方差E[V_j²]。

**GQA处理**：每个KV head g被`group`个Q head共享，ρ_g累加该group内所有Q head的P^T P贡献。

**序列长度适配**：
- test_seq == calib_seq：使用逐token的ρ_t（精确）
- test_seq != calib_seq：回退到ρ_mean（每head平均ρ，扩展到channel维）

### 2.8 完整流程

#### Linear场景
```
校准阶段 hif4_calibration_and_quantize_weight:
  1. 反量化NVFP4权重 → FP32
  2. 计算校准激活的max_abs和权重的max_abs
  3. SmoothQuant alpha扫描 (≤4M: {None,0.5}, >4M: {None}):
     a. 对每个alpha: W'=W*D, X'=X/D, Hadamard旋转
     b. 计算lambda_j = mean(X_rot²)
     c. 3候选快速量化, proxy MSE选择
  4. 用最优alpha的全权重Hadamard旋转 + 自适应候选数量化
  5. 计算w_diag = diag(W_hat^T W_hat)
  6. 返回 weight_params + activation_state{hadamard, importance, smooth_scale}

动态量化 hif4_dynamic_quantize_activation:
  1. 反量化NVFP4激活 → FP32
  2. 应用smooth_scale D^-1 (若存在)
  3. 应用Hadamard旋转
  4. 自适应候选数 + w_diag加权量化
```

#### Attention场景
```
校准阶段 hif4_calibration_attention:
  1. 计算rho_t (P^T P列范数平方) from校准Q/K (逐样本seq自适应)
  2. 生成Hadamard矩阵 (head_dim%64==0时, 否则None)
  3. 返回 q_state{hadamard}, k_state{hadamard},
          v_state{rho, rho_mean, calib_seq}

动态量化 Q/K:
  1. 反量化NVFP4 → FP32
  2. 应用Hadamard旋转 (若state中有, 保证Q@K^T不变)
  3. 9候选量化

动态量化 V:
  1. 反量化NVFP4 → FP32
  2. 无旋转
  3. 9候选量化 + rho_t token级加权 (或rho_mean回退)
```

## 3. 理论有效性验证

### 3.1 Exact微指数搜索的不劣性
精确搜索在有限可行集{(0,0),(0,1),(1,0),(1,1)}上取最小值，贪心解是该集合中的一个点。故：
```
min_{a,b1,b2} [L_1(a,b1)+L_2(a,b2)] ≤ L_1(a_old,b1_old)+L_2(a_old,b2_old)
```
逐块不劣，整体不劣。

### 3.2 E6M2对称窗口的嵌套不劣性
候选集合S_new ⊇ S_old时：
```
min_{s∈S_new} L(s) ≤ min_{s∈S_old} L(s)
```

### 3.3 Hadamard旋转的outlier分散
H元素为±1/√64，旋转后outlier被分散为|x_outlier|/√64到所有元素。较小的峰值意味着scale_factor更小，量化分辨率更高，MSE更低。

### 3.4 Linear输出加权的目标对齐
权重用λ_j加权等价于最小化tr(E_W C_X E_W^T)，在C_X对角近似下是Linear输出MSE的精确最小化。激活用w_diag加权等价于最小化tr(E_X W_hat^T W_hat E_X^T)，同理对齐输出MSE。

### 3.5 Attention V的P^T P敏感性
||P E_V||² = tr(E_V^T P^T P E_V)，若误差零均值不相关则E||P E_V||² = Σ_t ρ_t E||E_V[t,:]||²。ρ_t = Σ_i P[i,t]²是attention权重的列范数平方，正确反映token对输出的贡献。

### 3.6 SmoothQuant的等价性
X D^-1 (W D)^T = X D^-1 D^T W^T = X W^T（D对角时D^-1 D^T = I）。无量化时严格等价，量化后通过proxy MSE选择保证不劣。

## 4. 模拟评分结果

### 4.1 18用例模拟（simulate_scoring.py）

| 场景 | 用例数 | 正分 | 负分 | 总分 |
|------|--------|------|------|------|
| Linear | 9 | 9 | 0 | +1.8078 |
| Attention | 9 | 9 | 0 | +2.1567 |
| **总计** | **18** | **18** | **0** | **+3.9645** |

### 4.2 改进对比

| 方案 | 总分 | 正分率 | 负分用例 |
|------|------|--------|----------|
| 旧方案(greedy+E[V²]+无校准) | +2.7583 | 15/18 | 3 |
| 当前(exact+P^TP+校准+SmoothQuant) | +3.9645 | 18/18 | 0 |
| 提升(vs旧方案) | +1.2062 | +3 | -3 |

### 4.3 mini_sample 12用例

| 总分 | 正分 | 负分 |
|------|------|------|
| +2.3203 | 11 | 1 (A0.0=-0.0156, 与基线一致) |

## 5. 时间复杂度分析

- Linear权重[4096,4096]: 校准~5s (含2-alpha扫描), 5×动态~1s, 单组~6s
- Attention(seq=128, 32heads): 校准~0.5s, 5×3动态~2s, 单组~2.5s
- 50组Linear + 50组Attention: 估计~300-380s（取决于真实数据尺寸）
- 大矩阵(>4M)跳过alpha扫描，仅用None，节省~50%校准时间

## 6. 实现要点

1. **E6M2精确表示**：所有E6M2值在float32中可精确表示，用float64计算后转float32
2. **向量化**：scale search和微指数优化对所有block同时执行，避免Python循环
3. **State格式合规**：仅使用dict/float/int/Tensor，深度≤8，节点≤4096，CPU float32，无NaN/Inf
4. **自适应候选数**：大矩阵用5候选省时间，中矩阵7，小矩阵9，Q/K/V固定9候选
5. **SmoothQuant扫描优化**：alpha扫描用256行子采样 + 3候选快速proxy；大矩阵(>4M)仅用None不扫描
6. **Q/K Hadamard防御**：head_dim非64倍数时自动禁用，避免跨head混合
7. **V importance序列适配**：test_seq != calib_seq时回退到rho_mean

## 7. 参考资料

1. HiFloat4 Format for Language Model Inference (arxiv 2602.11287)
2. Pretraining Large LLMs with NVFP4 (arxiv 2509.25149)
3. SmoothQuant (arxiv 2211.10438) — 输出敏感度加权思想
4. GPTQ (arxiv 2210.17323) — 二阶信息量化补偿
5. BoA (ICML 2025) — attention-aware Hessian
6. QuIP (arxiv 2307.13304) — μ-incoherence 理论，首次 LLM 级量化保证
7. QuIP# (arxiv 2402.04396) — Hadamard incoherence，μ=√(2·log(2n²/δ)) 闭式界
8. QuaRot (arxiv 2404.00456) — 端到端 4-bit，在线 Hadamard，6/8-bit 无校准无损
9. AWQ (arxiv 2306.00978) — 逐通道 s_X=mean|X| 显著通道保护，1/s 误差界
10. TurboQuant (arxiv 2504.19874) — 全K随机旋转 + 浓度不等式，MSE ≤ (√3π/2)·4^{-b}
11. OWQ (arxiv 2306.02272) — λ_j=diag(X^T X) 弱列识别
12. SpinQuant (arxiv 2405.16406) — 学习旋转（Stiefel 流形，需 X@Q(W)，禁令禁止）
13. OmniQuant (arxiv 2308.13137) — 可学习裁剪+等价变换（block MSE=X@W，禁令禁止）
14. OptRot (arxiv 2512.24124) — 数据无关旋转选择，min_R Σ(RW)⁴ 四阶矩代理
15. HIGGS (arxiv 2411.17525) — 线性定理：ΔPPL ≈ t·Σ ε_block²，per-block MSE 近优
16. GPTVQ (arxiv 2402.15319) — 块级顺序量化 + Hessian 残差补偿
17. AQLM (arxiv 2401.06118) — 残差 K-means 多码本量化
18. PV-Tuning (arxiv 2405.14852) — 交替优化收敛理论（需 KL 前向，禁令禁止）
19. QuaRot (arxiv 2404.00456) — V 旋转 Wv-Wout 融合（计算不变性），Q/K 在线 Hadamard
20. BoA (arxiv 2406.13474) — Attention-aware Hessian: H_V = A^TA ⊗ Wout^TWout
21. RotateKV (arxiv 2501.16383) — GQA grouped-head rotation, pre-RoPE
22. KIVI (arxiv 2402.02750) — per-channel K + per-token V 不对称量化
23. KVQuant (arxiv 2401.18079) — pre-RoPE K + Fisher 非均匀量化
24. QERA (arxiv 2410.06040) — 闭式解 X^TX 加权误差重构
25. DFRot (arxiv 2412.00648) — 加权损失解决 massive-activation 方差

## 8. Linear 场景瓶颈分析与改进研究方向

（仅针对 Linear 场景；Attention 不在此节范围内）

### 8.1 当前算法瓶颈点

基于对 `hif4_calibration_and_quantize_weight` + `hif4_dynamic_quantize_activation` + `_quantize_block_given_scale` 的逐行分析，识别出以下瓶颈（按理论影响降序）：

**瓶颈1（最大）：对角重要性近似 — 丢弃 Hessian 非对角耦合**

当前权重重要性使用 `λ_j = mean(X_rot[:,j]²)`，即旋转后输入 Gram `H_rot = X_rot^T X_rot` 的对角线。proxy MSE 为 `sum_j λ_j · (W_hat[:,j] - W_rot[:,j])²`，这是真实目标 `tr(E_W · H_rot · E_W^T) = Σ_{i,j} (H_rot)_{ij} (E_W^T E_W)_{ji}` 的对角近似。Hadamard 旋转使 H_rot 更接近对角，但非对角项非零，当前完全忽略。GPTQ/QuIP 理论表明非对角耦合承载二阶舍入补偿信号，丢弃即丢失"免费"MSE 降低。

**瓶颈2：贪心最近舍入 — 无 OBS 二阶补偿**

`_quantize_block_given_scale` 中 mantissa 用 `round(w/sf·4)/4` 纯最近舍入。舍入元素 j 后，残差 `w_j - quant(w_j)` 不向剩余元素补偿。GPTQ 的 OBS 更新 `δ_F = -(w_q - quant(w_q))·H_F^{-1}[:,q] / H_F^{-1}[q,q]` 是该二次 proxy 的贪心最优扰动（Hassibi-Stork 1993），当前完全缺失。

**瓶颈3：block-diagonal 64×64 Hadamard — outlier 仅在块内分散**

`_apply_hadamard` 将 H（64×64）作用于每个连续 64-block，是 block-diagonal 旋转。outlier 仅分散到本 block 的 64 个元素。若 K≫64（如 K=4096），outlier 能量未跨 K 分散。TurboQuant/QuIP# 浓度不等式表明全 K 旋转使 `max_j |x_rot[j]| ≤ ||x||·√(2·log K / K)`，而 block-diagonal-64 仅 `√(2·log 64 / 64)`，outlier block 的 scale_factor 显著偏大。

**瓶颈4：SmoothQuant 仅 {None, 0.5} 两 α，且用 max 而非 mean**

当前 D_j = max_act_j^α / max_w_j^(1-α)，α 仅扫描 {None, 0.5}。AWQ 证明 s_X = mean|X|（非 max）+ α 网格搜索更优；且 AWQ 的 1/s 闭式误差界可替代 X@W proxy。

**瓶颈5：无 OWQ 弱列保护**

所有通道统一 HiF4 格式。OWQ 证明可由 `λ_j = diag(X^T X)`（单边统计）识别"弱列"（量化误差高放大通道）并单独提升其候选预算。

### 8.2 文献支撑

| 文献 | arxiv | 核心贡献 | A@W? |
|------|-------|---------|------|
| GPTQ | 2210.17323 | H=X^T X 二阶 OBS 舍入 + lazy batch | ✅ 允许 |
| QuIP | 2307.13304 | μ-incoherence 理论，首次 LLM 级量化保证 | ✅ 允许 |
| QuIP# | 2402.04396 | Hadamard incoherence，μ=√(2·log(2n²/δ)) 闭式界 | ✅ 允许 |
| QuaRot | 2404.00456 | 端到端 4-bit，在线 Hadamard，6/8-bit 无校准无损 | ✅ 允许 |
| AWQ | 2306.00978 | 逐通道 s_X=mean\|X\| 显著通道保护，1/s 误差界 | ✅ 允许 |
| TurboQuant | 2504.19874 | 全K随机旋转 + 浓度不等式，MSE ≤ (√3π/2)·4^{-b} | ✅ 允许 |
| OWQ | 2306.02272 | λ_j=diag(X^T X) 弱列识别 | ✅ 允许 |
| SpinQuant | 2405.16406 | 学习旋转（Stiefel 流形） | ❌ 禁止（学习需 X@Q(W)） |
| OmniQuant | 2308.13137 | 可学习裁剪+等价变换 | ❌ 禁止（block MSE=X@W） |

### 8.3 研究点一：GPTQ 二阶 Hessian 舍入（核心方向）

**目标**：用 `H = X^T X`（单边统计）的 Cholesky 分解驱动 HiF4 mantissa 舍入，精确最小化 `tr(E_W H E_W^T)`。

**理论可行性证明**：

1. **目标等价**：Linear 输出误差 `||X·E_W^T||²_F = tr(E_W · X^T X · E_W^T) = tr(E_W H E_W^T)`，H=X^T X。这是 GPTQ 的精确目标。当前对角近似 `Σ_j H_jj·E_W[:,j]²` 是其下界（忽略交叉项），故 GPTQ 解不劣于当前解。

2. **HiF4 适配**：HiF4 的 scale_factor + lv2 + lv3 先行确定（保持当前 exact 搜索），mantissa 是逐元素 3-bit（8 级）。固定指数结构后，mantissa 舍入在固定 codebook 上最小化 `tr(E_W H E_W^T)`，这正是 GPTQ 的子问题。

3. **OBS 贪心最优**（Hassibi-Stork 1993）：在二次 proxy `tr(E_W H E_W^T)` 上，逐元素舍入 + 补偿 `δ_F = -(w_q - quant(w_q))·H_F^{-1}[:,q] / H_F^{-1}[q,q]` 是贪心最优扰动。每次舍入不增加 proxy loss。

4. **增益上界**（QuIP Lemma 2 + QuIP# Lemma 3.1）：Hadamard 旋转后 H 为 μ-incoherent，`μ = √(2·log(2n²/δ))`。LDLQ + incoherence 后：
   ```
   E[tr(E_W H E_W^T)] ≤ (μ²/n)·m·σ²·tr(H^{1/2})²
   ```
   vs. 当前对角贪心 `~m·σ²·tr(H)`。比值 `tr(H) / [(μ²/n)·tr(H^{1/2})²]` 对大 n 显著（μ²/n → 0）。

5. **计算可行性**：H 是 K×K（如 4096²），Cholesky O(K³)。但可分块：每 64-block 取 H 的 64×64 子块，O(64³)·(K/64) = O(K·64²)，可接受。lazy batch 128 列进一步降低常数。

#### 8.3.1 验证结论（实测负结果，2026-08-25）

在 `verify_gptq.py` 中实现 block-diagonal 64×64 GPTQ mantissa 精化，5 组 Linear 配置 + 7 档阻尼 λ 扫描：

| 阻尼 λ | 平均分 | Δ vs baseline (RTN) |
|---------|--------|---------------------|
| 1e-6（激进） | +0.2543 | **-8.96%** |
| 1e-4 | +0.2543 | -8.96% |
| 1e-3 | +0.2545 | -8.91% |
| 1e-2 | +0.2557 | -8.45% |
| 1e-1 | +0.2654 | -4.99% |
| 1.0 | +0.2776 | -0.63% |
| 10.0 | +0.2792 | -0.06%（≈RTN） |
| **baseline** | **+0.2793** | — |

**关键诊断**（第 1 组 M=K=512）：
- `tr(E_W H_calib E_W^T)`：GPTQ/RTN = **0.944**（校准 proxy 降 5.6%，理论正确）
- `||X_test @ E_W^T||²`：GPTQ/RTN = **1.06-1.07**（测试输出 MSE 升 6-7%）
- H_rot 块内 off-diag/diag 能量比 = 16%（确有非对角耦合可利用）
- Cholesky 逆误差 ~7e-7（数值正确，非 bug）

**根因分析**：GPTQ 理论保证的是**校准 Hessian 上的 proxy 不劣**，但平台评分用**测试数据**。校准 H_calib ≠ 测试 H_test：
- GPTQ 补偿把残差推向 H_calib 的低特征值方向
- 测试 H_test 的特征结构不同，那些"安全"方向在测试空间可能高敏感
- HiF4 粗 codebook（15 级）下，补偿常把权重推到不同量化级，离散舍入放大了校准/测试失配

λ→∞ 时 GPTQ→RTN（补偿消失，-0.06%），证实实现自洽。但**无 λ 使 GPTQ 净正**。

**结论**：GPTQ 二阶舍入在当前 HiF4 + 合成数据设置下**不可行**。理论 proxy 增益被校准→测试泛化 gap 完全吞噬。此方向**搁置**，除非：
- (a) 真实 LLM 数据（非 i.i.d. 高斯）下 H_calib 更稳定，或
- (b) 找到自适应阻尼（per-block λ 由 H 块谱决定），或
- (c) 联合优化 scale_factor + mantissa（当前仅精化 mantissa，scale 仍为 RTN 最优）

**转向**：研究重心移至**研究点二（全 K Hadamard 旋转）**，该方向数据无关、无泛化 gap。

### 8.4 研究点二：全 K Hadamard 旋转（当前优先方向）

> GPTQ 验证失败后（8.3.1），研究重心转移至此方向。全 K 旋转是**数据无关**的，不存在校准→测试泛化 gap。

**目标**：用 fast Walsh-Hadamard（O(K log K)）替代 block-diagonal 64×64。

**理论可行性证明**：

1. **浓度不等式**（TurboQuant Thm 1 / QuIP# Lemma 3.1）：全 K 随机 Hadamard 旋转后，每坐标 `x_rot[j]` ~ sub-Gaussian，`max_j |x_rot[j]| ≤ ||x||·√(2·log K / K)` w.h.p.。block-diagonal-64 仅 `√(2·log 64 / 64)`，outlier 留在原 block。

2. **block scale 增益**：outlier block 的 scale_factor 比例 = `√(64/K)·||x||/||x_b||`。若 outlier 集中于一个 block（||x_b||≈||x||），K=4096 时 scale_factor 降低 8× → 量化步长 8× → MSE 64× 降低（σ²∝步长²）。

3. **HiF4 兼容**：旋转后 64-block 含混合通道，但 HiF4 不要求通道分组，scale_factor 按旋转后 64-block 计算，无冲突。

4. **计算成本**：fast Walsh-Hadamard O(K log K)，K=4096 → ~49k ops，离线权重一次、在线激活每次，可忽略 vs matmul O(MKT)。

#### 8.4.1 验证结论（实测负结果，2026-08-25）

在 `verify_hadamard.py` 中扫描 Hadamard 块大小 64/128/256/512/auto，10 组 Linear 配置：

| Hadamard 块 | 平均分 | Δ vs baseline (64) |
|-------------|--------|---------------------|
| **64（当前）** | **+0.2800** | — |
| 128 | +0.2712 | -3.17% |
| 256 | +0.2642 | -5.64% |
| 512 | +0.2602 | -7.10% |
| auto（最大） | +0.2592 | -7.44% |

**单调递减**：块越大，分数越低。与理论预测完全相反。

**根因诊断**（第 1 组 M=K=512，T=128）：

| 指标 | hs=64 | hs=512 | 结论 |
|------|-------|--------|------|
| 权重重建 MSE | 2.43e-6 | 2.44e-6 | 几乎相同（权重无 outlier，不受影响） |
| **激活重建 MSE** | **2.29e-3** | **2.42e-3** | **512 差 5.6%（差异全部来自激活）** |
| per-block max 均值 | 1.48 | 1.59 (+7.4%) | **大块 Hadamard 升高所有 block 的 max** |
| per-block max 方差 | 0.377 | 0.300 | 大块更均匀（浓度不等式预测） |
| 全局 max | 3.15 | 2.78 | 大块降低全局 max（TurboQuant 预测） |
| lv2/lv3 使用率 | 0.51/0.68 | 0.51/0.68 | 层级指数使用率不变 |

**核心机制**：HiF4 用 **per-64-block scale_factor** = block_max/7。大块 Hadamard 把 outlier 能量分散到所有 64-block → 所有 block 的 max 升高 → 所有 scale_factor 升高 → 所有量化步长变大 → MSE 升。

TurboQuant/QuIP# 的浓度不等式假设**全局统一量化**（全局 max 降低有利）。但 HiF4 的 **per-block scale 结构反转了这个结论**：outlier 应该**隔离**在单个 block（高 scale 但仅一个 block），而非分散到所有 block（中 scale 但全部 block）。

**64×64 Hadamard 是最优点**：
- 块内分散：单元素 max 从 ~8 降至 ~1.0，HiF4 层级指数（lv2/lv3）处理残余结构
- 块间隔离：非 outlier block 保持低 max/低 scale → 精细量化
- 与 HiF4 的 64-block 结构完美对齐

**结论**：研究点二（全 K Hadamard）**不可行**。当前 64×64 Hadamard 已是 HiF4 格式下的最优旋转大小。此方向**搁置**。

**理论修正**：TurboQuant 的 `E[MSE] ≤ (√3π/2)·4^{-b}` 界对 HiF4 **不适用**，因为 HiF4 用 per-block scale 而非全局 scale。正确的界应包含 block-max 的期望，而非全局 max 的期望。

### 8.5 研究点三：AWQ 逐通道显著保护

**目标**：用 `s_X = mean|X|`（单边）+ α 闭式搜索替代 max + 2-α 扫描。

**理论可行性证明**：

1. **1/s 误差界**（AWQ Lemma）：通道 j 的相对量化误差 ∝ 1/s_j。显著通道（s_X 大）放大 s_j 降低其误差。

2. **mean vs max**：max 对单点 outlier 过敏感，mean 更稳健（AWQ Table 2 验证 s_X alone >> s_W alone）。

3. **闭式 α 搜索**：用 1/s 界替代 X@W proxy，扫描 α∈{0.25,0.5,0.75}，完全 A@W-free。

#### 8.5.1 验证结论（实测负结果，2026-08-25）

在 `verify_awq.py` 中测试 5 个变体，10 组 Linear 配置：

| 变体 | 统计量 | alpha 集 | 公式 | 平均分 | Δ vs baseline |
|------|--------|---------|------|--------|--------------|
| **baseline** | max | {None,0.5} | sq: D=X^a/W^(1-a) | **+0.2800** | — |
| V0 (reimpl) | max | {None,0.5} | sq | +0.2800 | 0.00%（验证重实现正确） |
| V1 more_alpha | max | {None,.25,.5,.75} | sq | +0.2800 | 0.00%（增加 alpha 无效） |
| V2 mean_sq | mean | {None,.25,.5,.75} | sq | +0.2785 | -0.54% |
| V3 awq | mean | {None,.25,.5,.75} | awq: D=X^a·W^(1-a) | +0.2773 | -0.98% |

**根因诊断**（第 1 组）：proxy MSE 随 alpha 单调递增：
- α=None: 5.34e-4（最优，不缩放）
- α=0.25: 5.51e-4
- α=0.5: 5.82e-4
- α=0.75: 6.63e-4

proxy **总是选 α=None（不缩放）**，因为合成数据是 i.i.d. 高斯+随机 outlier（无结构化通道模式）。SmoothQuant 的逐通道缩放设计用于**结构化** outlier（特定通道持续大），对随机 outlier 反而增加 proxy MSE。

V1=baseline 完全相同 → 增加 alpha 候选无效（proxy 总选 None）。mean 和 AWQ 公式更差。

**结论**：研究点三（AWQ 逐通道）在合成数据下**不可行**。proxy 已正确识别"不缩放"最优。此方向**搁置**。

**注意**：对真实 LLM 数据（结构化 outlier），AWQ/SmoothQuant 可能有效，但本地合成数据无法验证。

### 8.6 研究点四：OWQ 弱列识别

**目标**：`λ_j = diag(X^T X)` 识别高敏感通道，单独提升其 exponent 搜索预算。

**理论可行性证明**：`||X·E_W^T||² = Σ_j λ_j·E_W[:,j]²`，λ_j 大的通道误差被放大。对其分配更多 E6M2 候选（如 13 vs 5）在不改变 HiF4 格式下降低敏感通道误差。单边统计，允许。

#### 8.6.1 验证结论（实测：候选 n=7 已饱和，OWQ 不可行，2026-08-25）

在 `verify_owq.py` 中扫描全局 n_candidates 5/7/9/13/17，10 组 Linear 配置：

| n_candidates | 平均分 | Δ(9) | 用时 |
|-------------|--------|------|------|
| 5 | +0.2778 | -0.91% | 14.8s |
| **7** | **+0.2803** | 0.00% | 13.4s |
| 9 | +0.2803 | — | 11.4s |
| 13 | +0.2803 | 0.00% | 15.3s |
| 17 | +0.2803 | 0.00% | 21.4s |

**候选在 n=7 已完全饱和**：7=9=13=17 结果完全相同。5→7 有提升（大矩阵受益），7+ 无增益。

**机制**：`_e6m2_candidates` 生成围绕 `idx` 的对称窗口。n=7 的窗口 `[-3,+3]` 已覆盖最优 scale_factor 邻域。n=9+ 的额外候选（`idx±4`）的 MSE 总是比中心差，从未被选中。

**结论**：研究点四（OWQ per-block 自适应候选）**不可行**。候选在 n=7 已饱和，per-block 分配更多候选不会有额外增益。此方向**搁置**。

**副产品发现（工程优化）**：当前 `_adaptive_n_candidates` 对大矩阵（numel>4M）返回 5，但 5<7（次优）。将最小候选数从 5 提到 7 可获得约 +0.0003/组（10 组 +0.003）。这是**参数调整**，非算法逻辑改动。

### 8.7 A@W 禁令合规性审查

**禁令**：不允许以任何形式计算 A@W 并利用 A@W 拟合反推 Q(A)。

| 研究点 | 使用统计量 | 是否计算 A@W | 合规 |
|--------|-----------|-------------|------|
| GPTQ 二阶舍入 | H = X^T X（输入 Gram）+ W 本身 | 否，H^{-1} 衍生自 X^T X | ✅ |
| 全 K Hadamard | 无（数据无关旋转） | 否 | ✅ |
| AWQ 逐通道 | s_X = mean\|X\| | 否，α 用 1/s 闭式界 | ✅ |
| OWQ 弱列 | λ_j = diag(X^T X) | 否 | ✅ |

**关键区分**：
- `X^T X`（输入 Gram/Hessian）是**单边统计**，仅用 X 自身，不涉及 W。✅ 允许。
- `W^T W`（权重 Gram）是**单边统计**，仅用 W。✅ 允许。
- `X @ W`（前向输出）是**双边**，禁令禁止用它拟合 Q(A)。❌ 禁止。
- SpinQuant（学习旋转）、OmniQuant（可学习裁剪）、AffineQuant 均需 `X @ Q(W)` 评估损失 → ❌ 禁止。本方案不采用。

**结论**：四个研究点全部使用单边统计（X^T X、W^T W、mean|X|、数据无关旋转），不计算 A@W，不以 A@W 反推 Q(A)。完全合规。

### 8.8 理论增益上界汇总（含验证修正）

原理论堆叠（8.3-8.6）：

```
MSE_current / MSE_proposed ≤ [tr(H) / ((μ²/n)·tr(H^{1/2})²)]    (GPTQ 二阶)
                             × [scale_factor_block64 / scale_factor_fullK]²  (全K Hadamard)
                             × [1/s_global / 1/s_per-channel]   (AWQ)
                             × [候选均匀 / 候选自适应]           (OWQ)
```

**验证后修正**（2026-08-25，四个研究点全部验证完成）：

| 研究点 | 理论增益 | 实测结果 | 状态 |
|--------|---------|---------|------|
| GPTQ 二阶舍入 | proxy 降 5.6% | 测试 MSE 升 6-7% | ❌ **搁置**（校准/测试泛化 gap） |
| 全 K Hadamard | scale 降 ~8× | 测试 MSE 升 7.4% | ❌ **搁置**（per-block scale 反转结论） |
| AWQ 逐通道 | 1/s 闭式界 | 测试 MSE 升 0.5-1.0% | ❌ **搁置**（合成数据无结构化通道） |
| OWQ 弱列 | 候选自适应 | n=7 已饱和，per-block 无增益 | ❌ **搁置**（候选集饱和） |

**全部四个研究点验证失败**。理论增益均被 HiF4 格式约束或合成数据分布特性吞噬。

**核心结论**：当前 64×64 Hadamard + exact 微指数 + 对角重要性 + proxy MSE 选择已接近 HiF4 格式下的**算法上限**。四个失败的本质原因：

1. **GPTQ**：校准 Hessian ≠ 测试 Hessian（数据相关方法的泛化极限）
2. **全K Hadamard**：HiF4 per-block scale 结构使 outlier 分散反而有害（格式约束反转理论）
3. **AWQ**：合成数据无结构化通道模式，逐通道缩放无效（数据分布特性）
4. **OWQ**：E6M2 候选集在 n=7 已覆盖最优邻域（候选集饱和）

**唯一可行优化**：`_adaptive_n_candidates` 最小值从 5 提到 7（工程参数调整，非算法改动），10 组约 +0.003 总分。

### 8.9 验证方法论

- **独立验证脚本** `check/example/verify_gptq.py`，不动 `solution.py` 主逻辑
- 用 monkey-patch 替换 `hif4_calibration_and_quantize_weight`，复用 `simulate_scoring.py` 的评分管线
- 阻尼扫描 λ ∈ {1e-6, 1e-4, 1e-3, 1e-2, 1e-1, 1, 10} 确认不是单点偶发
- 诊断 `tr(E_W H_calib E_W^T)` vs `||X_test @ E_W^T||²` 分离校准/测试效应
- 后续研究点验证沿用此框架

## 9. Linear 场景架构级瓶颈分析与改进方向

（第 8 节的四个研究点均从**参数/方法**角度优化，全部验证失败。本节从**算法架构**角度重新分析。）

### 9.1 当前算法架构瓶颈（结构层面，非参数）

当前 Linear 流水线是**固定串行单向管线**：

```
NVFP4→FP32 → [SmoothQuant D] → [Hadamard H(seed=42)] → [Per-block独立: scale_search→exact微指数→对角加权] → 输出
```

**瓶颈A（核心）：Per-block 独立量化，无块间协同**
每个 64-block 独立选 scale_factor/lv2/lv3。但 Linear 输出 `y[j] = Σ_b X_b @ W_b[j,:]^T` 跨所有 block 求和。GPTQ 尝试元素级补偿但泛化失败。块级（64维统计）是否更稳健是开放问题。

**瓶颈B：权重→激活单向传递，无 EM 迭代**
W 量化 → w_diag → X 量化（单向）。无交替优化。每次只用单边统计，但无收敛性保证。

**瓶颈C：Hadamard 种子固定，无选择机制**
seed=42 任意。SpinQuant 证明不同随机种子的精度差异可达 **13 个百分点**。当前固定种子是高方差分布中的单次采样，未利用选择机制。

**瓶颈D：SmoothQuant 和 Hadamard 串行独立，无联合优化**
D（对角缩放）→ H（正交旋转）是两个独立模块，无共享目标。

**瓶颈E：Scale_factor per-block 贪心选择，无全局协调**
每个 block 独立选最优 scale_factor。但输出 MSE 跨 block 累加——某些 block 主动 clip 可能降低整体输出 MSE。

### 9.2 文献支撑（架构级创新，2023-2025）

| 文献 | arxiv | 架构创新 | A@W? |
|------|-------|---------|------|
| **OptRot** | 2512.24124 | 数据无关旋转选择：min_R Σ(RW)⁴ 作为 µ_W 平滑代理 | ✅ 允许（仅用 W） |
| **HIGGS** | 2411.17525 | 线性定理：ΔPPL ≈ t·Σ ε_block²，per-block MSE 最优 | ✅ 允许（数据无关） |
| GPTVQ | 2402.15319 | 块级顺序量化 + Hessian 残差补偿 | ✅ 允许（H=X^TX） |
| QuIP# | 2402.04396 | BlockLDLQ + E8 格码本（块级 VQ） | ✅ 核心（微调需 A@W） |
| AQLM | 2401.06118 | 残差 K-means 初始化（粗到细两遍） | ⚠️ 基础版允许 |
| PV-Tuning | 2405.14852 | 交替优化收敛理论（trust-ratio） | ❌ 禁止（用 KL 前向） |
| SpinQuant | 2405.16406 | 学习旋转（13pt 种子方差证据） | ❌ 禁止（前向损失） |

### 9.3 研究点五：Per-block OptRot — 数据无关旋转选择（优先）

**目标**：替换固定 seed=42，用 OptRot 的四阶矩代理 `min_R Σ_{i∈block} (R_{64} W_block)_i⁴` 选择每个 64-block 的旋转。

**理论可行性证明**：

1. **种子方差证据**（SpinQuant）：不同随机 Hadamard 种子的量化精度差异达 13 个百分点。当前 seed=42 是此高方差分布的**单次采样**，未利用选择机制。

2. **四阶矩代理**（OptRot）：QuIP# 的误差界 `err ∝ µ_W`，其中 `µ_W = √n · max_{ij}|W_{ij}| / ||W||_F`。OptRot 证明最小化 `Σ(RW)⁴` 是 `max|W_{ij}|` 的**平滑上界代理**，可在无前向传播下降低 µ_W。

3. **数据无关**：目标函数仅用 W（权重），不涉及 X（激活）或 A@W。每个 64-block 独立优化 64×64 正交矩阵（Stiefel 流形，Cayley SGD，秒级/块）。

4. **HiF4 适配**：旋转后 W_rot 的 block max 更均匀（µ_W 更低）→ scale_factor 更小 → 量化步长更细 → MSE 降。与 HiF4 的 per-block scale 结构兼容。

5. **与之前研究点二的区别**：研究点二（全K Hadamard）改变旋转**大小**（64→512），验证失败（per-block scale 反转）。研究点五改变旋转**选择**（seed→OptRot），大小仍为 64，**不改变 per-block 结构**。

**A@W 合规**：✅ 仅用 W 的四阶矩，数据无关。

#### 9.3.1 验证结论（实测负结果，2026-08-25）

在 `verify_optrot.py` 中执行两阶段验证：

**阶段1：多种子扫描**（8 个种子 42/1/7/13/21/100/2024/999）

| 种子 | 平均分 |
|------|--------|
| 42 / 1 / 7 / 13 / 21 / 100 / 2024 / 999 | **全部 +0.2803** |

std = **0.0000**（完全相同）。确认不同种子生成不同 Hadamard 矩阵（仅列符号翻转不同），但量化结果完全一致。

**数学证明（Sign-Invariance Theorem）**：

`_random_hadamard(n, seed)` 返回 `H_sylvester · diag(±1)`，不同种子仅改变 ±1 对角符号。对于 H₁ = H₀ · S（S 为 ±1 对角矩阵）：

1. W_rot₁ = W · H₁ = W · H₀ · S = W_rot₀ · S（列符号翻转）
2. HiF4 量化对列符号翻转**不变**：block max 用 |·|（符号不变）→ scale_factor 不变 → mantissa 幅值不变 → sign 参数捕获翻转
3. 输出不变：`X_rot₁ @ dequant(params₁)ᵀ = (X·H₀·S) @ (dequant(params₀)·S)ᵀ = X·H₀·dequant(params₀)ᵀ`（S·Sᵀ=I）

故 ±1 符号翻转为 HiF4 量化的**不变量**，种子选择无意义。

**阶段2：非 Hadamard 正交矩阵对比**

| 旋转类型 | 平均分 | Δ vs Hadamard |
|----------|--------|-------------|
| **Hadamard(42)** | **+0.2796** | — |
| RandomOrth（QR 分解非 Hadamard） | +0.2556 | **-2.40%** |
| Identity（无旋转） | 权重重建 MSE 仅差 1.1%（i.i.d. 高斯旋转不变） | — |

**关键发现**：
1. 所有符号翻转 Hadamard 等价（sign-invariance）→ 种子选择无意义
2. 非 Hadamard 正交矩阵更差 -2.4% → Hadamard 结构本身最优
3. 权重是 i.i.d. 高斯 → 旋转对权重量化几乎无影响（高斯旋转不变性）
4. 激活有 outlier → Hadamard 的 ±1/√n 扁平结构比随机正交矩阵更均匀地分散 outlier

**理论解释**：Hadamard 矩阵的 ±1/√n 元素使每个坐标**等量**贡献（最优浓度），而随机正交矩阵的任意浮点元素使某些坐标主导（更差 incoherence）。Hadamard 结构对 HiF4 的 per-block scale 是最优的。

**结论**：研究点五（OptRot）**不可行**。
1. 种子选择无意义（sign-invariance 数学证明）
2. OptRot 的四阶矩目标 `Σ(RW)⁴` 也是 sign-invariant（(S·v)⁴=v⁴），无法区分符号翻转
3. 非 Hadamard 正交更差 → Hadamard 结构已是最优旋转
4. SpinQuant 的 13pt 种子方差是针对**真实 LLM**（结构化 outlier），合成数据无此结构

此方向**搁置**。

### 9.4 研究点六：两遍残差精化（AQLM 启发）

**目标**：在当前单遍量化后，计算残差 `R = W_rot - dequant(params1)`，用残差信息**调整 scale_factor/lv2/lv3** 做第二遍量化。

**理论可行性证明**：

1. **残差 K-means**（AQLM）：AQLM 的初始化策略——先聚类主体，再聚类残差——提供粗到细分解。HiF4 只有一组参数，但可用两遍方式：第一遍确定 scale_factor 大范围，第二遍在残差指导下微调。

2. **线性定理支撑**（HIGGS）：`ΔPPL ≈ t·Σ ε_block²`，降低 per-block ε 直接降低 PPL。残差精化降低 ε_block。

3. **数据无关**：残差 `R = W_rot - dequant(params)` 仅用 W 和已量化参数，不涉及 X 或 A@W。

4. **HiF4 适配**：第一遍标准量化 → params1。计算 R 的 block 级统计（如 block max of R）。若 R 的某些 block 残差大，调整那些 block 的 scale_factor（如主动 clip 或选不同 E6M2 候选）做第二遍。

**A@W 合规**：✅ 仅用 W + 已量化参数。

#### 9.4.1 验证结论（实测微小正结果，2026-08-25）

在 `verify_residual_em.py` 中实现 IRLS（迭代重加权最小二乘）残差精化：

**方法**：Pass 1 标准量化 → params1；计算残差 R = W_rot - dequant(params1)；更新 importance `λ_j' = λ_j · (1 + α · R_j²_norm)`；Pass 2 用 λ_j' 重新量化。

**α 扫描**（10 组 Linear）：

| 方法 | 平均分 | Δ vs baseline | 用时 |
|------|--------|--------------|------|
| Baseline | +0.2803 | — | — |
| IRLS α=0.5 | +0.2806 | +0.0003 (+0.10%) | — |
| IRLS α=1.0 | +0.2807 | **+0.0004 (+0.14%)** | 17.0s |
| IRLS α=2.0 | +0.2807 | +0.0004 (+0.13%) | — |

**逐组分析**（α=1.0）：

| 组 | baseline | IRLS | Δ |
|---|---------|------|---|
| 0 | +0.2801 | +0.2798 | -0.0002 |
| 2 | +0.2814 | +0.2829 | **+0.0016** |
| 4 | +0.2801 | +0.2805 | +0.0004 |
| 5 | +0.2826 | +0.2832 | +0.0005 |
| **8** | +0.2791 | +0.2807 | **+0.0016** |
| 其余 5 组 | ~+0.28 | ~+0.28 | ±0.0002 |

6 正 3 负 1 零。增益主要由组 2/8 驱动（各 +0.0016），其余组接近不变。

**结论**：IRLS 残差精化给出**微小正增益**（+0.0004 avg, +0.14%），是 7 个研究点中**唯一正结果**。但：
- 增益微小（<0.2%），3/10 组略降
- 时间成本：每 10 组额外 17s → 50 组约 +85s
- 不一致性：部分组劣化，可能真实数据下不稳定

**决策**：**可选实施**。若时间预算允许（5 分钟限制），在 solution.py 中加入 IRLS pass 2（约 +85s）。若时间紧张则不实施。

### 9.5 理论贡献：线性定理对当前架构的论证

**HIGGS 线性定理**（arXiv:2411.17525）：

```
ΔPPL ≈ Σ_layers t_l · ε_l²
```

其中 `ε_l²` 是 per-layer 重建误差，`t_l` 是层系数。Hadamard 旋转后 `t_l` 跨层近似常数。

**对当前架构的论证**：

1. **Per-block 独立量化是近优的**：线性定理 + Hadamard 去相关 → `ε_layer² ≈ Σ_blocks ε_block²`（块间近似独立）→ `ΔPPL ≈ t·Σ_blocks ε_block²`。**当前 per-block 独立 MSE 最小化是 perplexity 最优的**。

2. **块间补偿增益小**（瓶颈A 的理论回答）：Hadamard 显式抑制块间相关性 → 块间补偿的理论增益小。**这解释了 GPTQ（元素级）和全K Hadamard（块间分散）为何失败**——它们试图利用被 Hadamard 抑制的相关性。

3. **全局 scale 协调无增益**（瓶颈E 的理论回答）：线性定理说所有 block 的系数 `t` 相同 → 无 block 优先级 → per-block 独立选 scale 已最优。**研究点四（OWQ per-block 候选）失败的理论解释**。

4. **对第 8 节四个失败的统一解释**：
   - GPTQ：利用块内 Hessian 非对角（被 Hadamard 部分抑制）→ 增益小 + 泛化 gap
   - 全K Hadamard：改变 per-block 结构 → 违反线性定理的块独立性假设
   - AWQ：合成数据无结构化通道 → 线性定理下 per-block MSE 已最优，缩放无益
   - OWQ：候选集饱和 → 线性定理下所有 block 同等重要，候选均匀已最优

### 9.6 研究点七：单边 EM 式 W↔X 交替优化（开放理论缺口）

**目标**：在校准阶段交替优化 W 和 X 的量化参数，每次只用单边统计。

**理论可行性证明**：

1. **PV-Tuning 收敛理论**（arXiv:2405.14852）：交替离散/连续参数更新，trust-ratio 约束 `||Δ||/||x|| ≤ 0.01`，**收敛到稳定解**。但 PV-Tuning 用 KL 前向损失（禁止）。

2. **开放缺口**：**无现有论文证明单边统计 EM 的收敛性**——交替 `W^T W` 驱动和 `X^T X` 驱动的更新，不计算 `X@W`。这是理论创新点。

3. **具体方案**：
   - E-step：固定 W 量化参数，用 `X^T X` 更新 X 的 importance → 量化 X
   - M-step：固定 X 量化参数，用 `W^T W` 更新 W 的 importance → 量化 W
   - 交替直到收敛（trust-ratio 约束）

4. **HiF4 约束**：X 必须在线动态量化（不能在校准阶段预计算 X 的 HiF4 参数）。但 X 的 **importance**（w_diag）可以在校准阶段交替优化——交替更新 W 量化 → 更新 w_diag → 这影响 X 在线量化时的 importance。这是**校准阶段的单边 EM**。

**A@W 合规**：✅ E-step 用 `X^T X`，M-step 用 `W^T W`，不计算 `X@W`。

**风险**：无收敛证明（开放缺口），可能不收敛或增益微小。

#### 9.6.1 验证结论（实测微小正结果，2026-08-25）

在 `verify_residual_em.py` 中实现单边 EM 交替（3 轮），用 w_diag 替代 λ_j 作为 W importance 重新量化：

| 方法 | 平均分 | Δ vs baseline | 用时 |
|------|--------|--------------|------|
| Baseline | +0.2803 | — | — |
| EM 3 iters | +0.2807 | **+0.0004 (+0.13%)** | 30.0s |

**逐组表现与 IRLS 几乎一致**：6 正 3 负 1 零，增益主要在组 2/8（各 +0.0012/+0.0013）。

**关键观察**：EM 与 IRLS 结果几乎相同（+0.0004 vs +0.0004）。原因：
- EM 用 w_diag 作为 W importance → 改变了量化目标
- IRLS 用 λ_j·(1+α·R²) 作为 importance → 重加权原始目标
- 两者都是"聚焦难量化通道"的不同实现，效果等价

**结论**：EM 交替给出与 IRLS 相同的微小正增益（+0.0004）。但时间成本更高（30s vs 17s per 10 组）。**不推荐**单独实施——IRLS 更简单且效果相同。

### 9.7 A@W 禁令合规性审查

| 研究点 | 使用统计量 | 计算 A@W? | 合规 |
|--------|-----------|----------|------|
| 五：Per-block OptRot | W 的四阶矩 Σ(RW)⁴ | 否（数据无关） | ✅ |
| 六：两遍残差精化 | W_rot + dequant(params) | 否（仅用 W 和已量化参数） | ✅ |
| 七：单边 EM 交替 | E: X^TX, M: W^TW | 否（每次只用单边） | ✅ |
| 理论贡献（线性定理） | 无（纯理论分析） | 否 | ✅ |

**关键区分**：
- OptRot 的 `Σ(RW)⁴` 仅用 W → **单边统计** ✅
- 残差 `R = W - dequant(params)` 仅用 W → **单边统计** ✅
- EM 的 E-step 用 `X^TX`、M-step 用 `W^TW` → **每次单边** ✅
- PV-Tuning 的 KL 前向损失 → **双边** ❌ 禁止，不采用
- SpinQuant 的前向损失 → **双边** ❌ 禁止，不采用

**结论**：三个新研究点全部使用单边统计，不计算 A@W，完全合规。

### 9.8 优先级与可行性评估（含验证更新）

| 研究点 | 理论支撑 | A@W | 实现复杂度 | 预期增益 | 实测结果 | 状态 |
|--------|---------|-----|-----------|---------|---------|------|
| **五：Per-block OptRot** | SpinQuant 13pt + OptRot | ✅ | 低 | 中 | 种子 std=0, 非Hadamard -2.4% | ❌ **搁置** |
| **六：两遍残差精化** | AQLM + 线性定理 | ✅ | 中 | 低-中 | 待验证 | ⏳ |
| **七：单边 EM 交替** | PV-Tuning（开放缺口） | ✅ | 中 | 不确定 | 待验证 | ⏳ |

**更新后推荐验证顺序**：研究点六（残差精化）→ 研究点七（EM 交替）。

**理论预测**（基于 HIGGS 线性定理）：
- 研究点六预期增益低——当前单遍量化已是 per-block MSE 近优，残差精化只能在 per-block 最优解上微调
- 研究点七不确定——开放理论缺口，但单边 EM 的收敛性和增益均无保证
| 理论贡献（线性定理） | HIGGS 定理 | ✅ | 无（纯理论） | 解释力 | — |

**更新后推荐验证顺序**：~~研究点五（OptRot）~~→ 研究点六（残差精化）→ 研究点七（EM 交替）。

**验证后修正**：
- 研究点五（OptRot）：❌ 失败（sign-invariance + Hadamard 最优）
- 研究点六（IRLS 残差精化）：✅ **微小正增益** +0.0004（+0.14%），唯一正结果，可选实施
- 研究点七（EM 交替）：✅ 微小正增益 +0.0004（与 IRLS 相同），时间成本更高，不推荐单独实施

**最终结论**：7 个研究点中，仅 IRLS/EM 给出微小正增益（+0.0004 avg）。HIGGS 线性定理预测正确——当前 per-block 独立量化 + Hadamard 已接近 HiF4 格式下的算法上限。

### 9.9 与第 8 节四个失败方向的对比

| 维度 | 第 8 节（参数级） | 第 9 节（架构级） |
|------|------------------|------------------|
| 优化对象 | 参数（Hessian/旋转大小/统计量/候选数） | 架构（旋转选择/量化遍数/交替优化） |
| 数据依赖 | 部分（GPTQ/AWQ 用校准数据） | OptRot 数据无关 |
| 理论基础 | TurboQuant/QuIP#（全局量化假设） | HIGGS 线性定理（per-block 最优） |
| 失败/成功 | 全部失败 | 待验证 |
| 关键区别 | 改变量化**方法** | 改变量化**架构**（选择/迭代/交替） |

## 10. Attention 场景架构瓶颈分析与改进方向

（Attention 场景波动大：10 组 +0.156~+0.276，平均 +0.2020。本节从架构层面分析瓶颈。）

### 10.1 当前算法架构瓶颈

当前 Attention 流水线：

```
校准: 计算 P^TP 的 rho_t (V importance) + 生成 Q/K 共享 Hadamard(64)
动态 Q: NVFP4→FP32→Hadamard(64)→13候选量化 (无 importance)
动态 K: NVFP4→FP32→Hadamard(64)→13候选量化 (无 importance)
动态 V: NVFP4→FP32→无旋转→13候选量化 + rho_t importance
```

**瓶颈A（核心）：V importance `P^TP` 是完整 Hessian 的不完整近似**

BoA (arXiv:2406.13474) 证明 V 的精确 attention-aware Hessian 为：
```
H_V = 2 · X · A^T·A · X^T  ⊗  Wout^T·Wout
```
当前 rho_t = `Σ_i P[i,t]²` = `diag(A^T·A)` 仅是 `A^T·A` 的对角，**缺失 `Wout^T·Wout` 因子**。诊断确认：加 Wout 加权有小幅正向提升（+0.0004~+0.0037），但当前用单位矩阵近似 Wout，真实 Wout 可能更强。

**瓶颈B：V 无旋转 — outlier 未分散**

Q/K 有 Hadamard 旋转（保证 Q@K^T 不变），但 V 不旋转（"无法保持 attention 输出"）。QuaRot (arXiv:2404.00456) 证明 V 可通过 `Wv←Wv·H, Wout←H·Wout` 融合旋转，保持输出不变。当前缺失此旋转。

诊断：V 无旋转时 outlier 集中在个别 token/block，13 候选搜索无法有效分散。这与组间波动直接相关。

**瓶颈C：Q/K 量化无 importance 加权**

当前 Q/K 量化用均匀 importance（None）。BoA 的 relaxed Hessian 建议：
- Q importance ≈ `K^T·K`（每 KV head 的 K 列范数）
- K importance ≈ `Q^T·Q`（每 KV head 的 Q 列范数）

这些是单边统计（仅用 Q 或 K 自身），不涉及 A@W。

**瓶颈D：head_dim=64 时 Hadamard 旋转维度小**

64×64 Hadamard 在 head_dim=64 下仅 1 个旋转块/head。RotateKV (arXiv:2501.16383) 证明 GQA group 内多 head 联合旋转可增大有效维度（`H_{64×group}`），改善小 GQA group 的表现。

**瓶颈E：随机 Hadamard 种子方差**

SpinQuant (arXiv:2405.16406) 证明不同随机种子的 Hadamard 产生高达 13 个百分点差异。当前 seed=123 固定，未利用选择机制。DFRot (arXiv:2412.00648) 证明方差来自 massive-activation token（长尾分布）。

### 10.2 文献支撑（Attention 专用，2024-2025）

| 文献 | arxiv | 核心创新 | A@W? |
|------|-------|---------|------|
| **QuaRot** | 2404.00456 | V 旋转: `Wv←Wv·H, Wout←H·Wout`（融合，输出不变） | ✅ |
| **BoA** | 2406.13474 | Attention-aware Hessian: `H_V = A^TA ⊗ Wout^TWout` | ✅ |
| **RotateKV** | 2501.16383 | GQA grouped-head rotation: `H_{64×group}` | ✅ |
| **SpinQuant** | 2405.16406 | 学习旋转 R2 (V-Wo pair), 种子方差 13pt | ⚠️ 学习需前向 |
| **DFRot** | 2412.00648 | 加权损失解决 massive-activation 方差 | ⚠️ Procrustes 需迭代 |
| **KIVI** | 2402.02750 | per-channel K + per-token V 不对称量化 | ✅ |
| **KVQuant** | 2401.18079 | Pre-RoPE K + Fisher 非均匀量化 | ✅ |
| **QERA** | 2410.06040 | 闭式解: X^TX 加权误差重构 | ✅ |

### 10.3 研究点八：V 旋转 — QuaRot Wv-Wout 融合（优先）

**目标**：对 V 施加 head-wise Hadamard 旋转，通过 `Wout←H·Wout` 融合补偿，保持 attention 输出不变。

**理论可行性证明**：

1. **计算不变性**（QuaRot）：`Y = Σ_h P_h · X·Wv^(h)·Wout^(h)`。插入 `H_dh`：`Y = Σ_h P_h · X·Wv·H·H^T·Wout = Σ_h P_h · X·Wv·Wout`（H 正交）。全精度下输出严格不变。

2. **outlier 分散**：V 旋转后每 head 的 V 值从"少数 outlier 主导"变为"均匀分布"。per-64-block 的 max 降低 → scale_factor 更小 → 量化步长更细 → V 重建 MSE 降。

3. **HiF4 适配**：V 是在线动态量化。旋转 `V_rot = V @ H` 需在在线阶段施加。但 `Wout←H·Wout` 的融合是离线的（校准阶段）。**问题**：当前竞赛接口不提供 Wout（仅 Q/K/V 的 NVFP4 carrier），无法融合旋转到 Wout。

4. **替代方案**：直接在线旋转 V 并量化，**在反量化后施加 H^T** 还原。即 `V_hat = dequant(quant(V @ H)) @ H^T`。这在功能上等价于 Wv-Wout 融合，但需要在线施加 H^T。当前 `hif4_dynamic_quantize_v` 返回 HiF4 参数，平台反量化后做 attention——如果 V 的 HiF4 参数编码的是 `V@H` 的量化值，则平台反量化得到 `dequant(quant(V@H))`，需要 `@H^T` 还原。**但平台直接用反量化值做 attention，不施加 H^T**——所以 V 旋转会改变 attention 输出。

5. **关键约束**：竞赛平台执行 `Attention(Q_hif4, K_hif4, V_hif4)`，其中 Q/K/V_hif4 是反量化值。如果 V_hif4 = dequant(quant(V@H))（旋转域），平台用 `(V@H)_hat` 做 attention，但 Q@K^T 不变（Q/K 同旋转），所以 `P = softmax(Q_rot @ K_rot^T) = softmax(Q @ K^T)` 不变。attention 输出 = `P @ (V@H)_hat`。需要 `P @ (V@H)_hat @ H^T = P @ V_hat'` 才等于原始。**但平台不施加 H^T**。所以 V 旋转**无法在当前接口下实现**。

**结论**：研究点八（V 旋转）在当前竞赛接口下**不可行**（平台不施加 H^T 补偿）。需要平台支持 V 的在线旋转补偿，或 Wout 融合。搁置。

### 10.4 研究点九：V importance 加 Wout^T·Wout 因子（可行）

**目标**：将 V importance 从 `rho_t = Σ_i P[i,t]²` 升级为 `rho_t = Σ_i P[i,t]² · ||Wout[:,t]||²`（BoA 精确 Hessian 的对角近似）。

**理论可行性证明**：

1. **BoA 精确 Hessian**（arXiv:2406.13474）：`H_V = 2 · X · A^T·A · X^T ⊗ Wout^T·Wout`。对角近似：`importance_t = diag(A^TA)_t · diag(Wout^T·Wout)_t`。当前仅用 `diag(A^TA)_t`（= rho_t），缺失 `diag(Wout^T·Wout)_t`。

2. **当前接口约束**：竞赛不提供 Wout 矩阵。但可用 **attention output 的列范数** 近似 `Wout^T·Wout` 的影响：`out_norm_sq_t = ||Σ_h P[:,t] · V[t,:]||²`（attention 输出 per-token 范数）。这是单边统计（仅用 P 和 V，不计算 A@W）。

3. **诊断确认**（3 组测试）：

| 组 | rho (当前) | rho+out_norm (BoA) | Δ |
|---|---|---|---|
| hd=128 grp=4 | +0.1366 | +0.1381 | +0.0014 |
| hd=64 grp=4 | +0.1730 | +0.1734 | +0.0004 |
| hd=128 grp=4 | +0.1469 | +0.1479 | +0.0010 |
| hd=64 grp=4 | +0.0832 | +0.0870 | +0.0037 |

全部正向，hd=64 小 GQA 组增益最大（+0.0037）。**与瓶颈D（小 GQA 组表现差）直接对应**。

4. **A@W 合规**：`out_norm_sq_t` 用 P（来自 calibration Q,K）和 V（来自 calibration V），不计算 A@W。✅

**实现**：在 `_compute_v_importance` 中，计算 attention output per-token 范数，乘到 rho 上。

### 10.5 研究点十：Q/K importance 加权（可行）

**目标**：当前 Q/K 量化无 importance。用 BoA relaxed Hessian 加权：Q importance = `K^T·K`，K importance = `Q^T·Q`。

**理论可行性证明**：

1. **BoA relaxed Hessian**：
   - `H_WQ ≈ 2·XX^T ⊗ K_h^T·K_h`（Q 的 importance 来自 K 的列范数）
   - `H_WK ≈ 2·XX^T ⊗ Q_h^T·Q_h`（K 的 importance 来自 Q 的列范数）

2. **单边统计**：Q importance 用 K（仅 K 自身），K importance 用 Q（仅 Q 自身）。不涉及 A@W。✅

3. **HiF4 适配**：Q/K 是 [seq, q_heads×head_dim]。importance 是 per-channel（head_dim 维）。在 `hif4_dynamic_quantize_q/k` 中传入 importance。

4. **预期效果**：当前 Q/K 用均匀量化，13 候选搜索空间均匀分配。加 importance 后，敏感通道（对应 K/Q 大值的通道）获更优候选。尤其对 head_dim=64 的小 GQA 组，Q/K 频谱更集中，importance 加权效果更显著。

**A@W 合规**：✅ K^T·K 和 Q^T·Q 是单边统计。

### 10.6 研究点十一：GQA grouped-head rotation（可行）

**目标**：对 head_dim=64 的小 GQA group，用 `H_{64×group}`（跨 group 内多 head 联合旋转）替代 `H_64`（per-head 独立旋转）。

**理论可行性证明**：

1. **RotateKV**（arXiv:2501.16383）：GQA group 内 `group` 个 Q head 共享 1 个 K/V head。per-head 旋转维度 = head_dim。grouped-head 旋转维度 = `group × head_dim`，增大 `group` 倍。

2. **浓度不等式**：旋转维度 d → `max|x_rot| ≤ ||x||·√(2·log d / d)`。d=64 → 0.30；d=256（group=4）→ 0.15。scale_factor 降 2× → MSE 降 4×。

3. **Q@K^T 不变性**：grouped-head 旋转对 group 内所有 Q head 和共享 K head 施加同一 `H_{group×hd}`。`Q_rot @ K_rot^T = Q @ H^T @ H @ K^T = Q @ K^T`（H 正交）。✅

4. **HiF4 适配**：将 Hadamard 从 `H_64` 改为 `H_{64×group}`。`_apply_hadamard` 的 block size 从 64 改为 `64×group`。需要 `q_heads×head_dim % (64×group) == 0`（满足，因为 group = q_heads/kv_heads，`q_heads×hd / (64×group) = kv_heads × hd / 64`，当 hd=64 时 = kv_heads，整数）。

**A@W 合规**：✅ 数据无关旋转。

### 10.7 研究点十二：多种子 Hadamard 选择（可行但增量小）

**目标**：从多个随机 Hadamard 种子中选最优（用 Q^T·Q 或 K^T·K 频谱评估）。

**理论可行性证明**：SpinQuant 证明种子方差达 13pt。但 Attention 的 Q/K Hadamard 是 sign-invariant 的（同 Linear 场景），所以种子选择对 Q/K 量化无影响。对 V（无旋转）更无影响。

**结论**：Attention 场景下种子选择**不可行**（sign-invariance 同 Linear）。搁置。

### 10.8 A@W 禁令合规性审查

| 研究点 | 使用统计量 | 计算 A@W? | 合规 |
|--------|-----------|----------|------|
| 八：V 旋转 (QuaRot) | 无（数据无关旋转） | 平台不支持 H^T 补偿 | ⛔ 接口约束 |
| 九：V importance + Wout | P (from calib Q,K) + V (from calib) → out_norm | 否 | ✅ |
| 十：Q/K importance | Q^T·Q, K^T·K (单边) | 否 | ✅ |
| 十一：grouped-head rot | 无（数据无关旋转） | 否 | ✅ |
| 十二：多种子选择 | Q^T·Q 频谱 (单边) | sign-invariant | ⛔ 不可行 |

**结论**：研究点九/十/十一全部使用单边统计或数据无关旋转，不计算 A@W，完全合规。研究点八受接口约束搁置。

### 10.9 验证结论（2026-08-25，三个研究点全部完成）

在 `verify_attn.py` 中对 10 组 Attention 配置验证：

| 方法 | 平均分 | Δ vs baseline | 结论 |
|------|--------|--------------|------|
| **Baseline** | **+0.2020** | — | — |
| 九: V imp + Wout α=1.0 | +0.2019 | -0.0001 (-0.05%) | ❌ 无增益 |
| 九: V imp + Wout α=0.5 | +0.2026 | +0.0006 (+0.30%) | 微小正，不稳定 |
| 十: Q/K importance | +0.2020 | 0.0000 (0.00%) | ❌ 完全无变化 |
| 九+十: Combined | +0.2019 | -0.0001 (-0.05%) | ❌ 无增益 |
| 十一: grouped-head rot | — | — | ⛔ K 维度不足 |

**逐组分析**（研究点九 α=0.5，唯一正结果）：
- 增益来自少数组（组 5/7/9 等 hd=64 小 GQA 组），其余组略降
- α=1.0 反而负 → 增益不稳定，依赖 α 调参
- Q/K importance（研究点十）完全无变化 → Q/K 量化已饱和（13 候选足够）

**研究点十一（grouped-head rotation）失败原因**：
- GQA 中 K 的维度 = `kvh × hd`，而 grouped 旋转需要 `hd × group = hd × (qh/kvh)`
- 对 K：`kvh × hd` vs `hd × qh/kvh` → 需要 `kvh² ≥ qh`，一般不满足（如 qh=32, kvh=8 → 需要 64 ≥ 32，满足但 k_dim=1024 < target=512... 实际 k_dim=1024%512=0 可行；但 qh=8,kvh=2 → k_dim=256%512=256≠0，不可行）
- **K 维度不足时 grouped 旋转无法施加**（Q/K 必须用同一旋转保证 Q@K^T 不变）

**统一解释**（与 Linear 场景一致）：
1. V importance + Wout：增益微小（+0.0006），因 attention output 范数近似 Wout^TWout 不够精确（真实 Wout 不可用）
2. Q/K importance：完全无变化，因 Q/K 13 候选搜索已饱和（同 OWQ 候选饱和）
3. Grouped rotation：K 维度约束使跨 head 联合旋转不可行

**结论**：Attention 场景三个研究点**全部验证失败或增益微小**。当前算法（P^TP importance + Hadamard Q/K + 13 候选）已接近 Attention 场景的算法上限。

**与 Linear 场景的一致性**：两个场景的共同教训：
- importance 加权（V+rho, Q/K+K^TK）在候选搜索饱和时无效（同 OWQ）
- 旋转大小/选择在 sign-invariance 或维度约束下无效（同 OptRot/全K Hadamard）
- 当前 Hadamard + exact 微指数 + 13 候选已是 HiF4 格式下的近优架构
