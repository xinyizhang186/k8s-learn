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

### 1.3 选手输出约束
- `scale_factor`: E6M2格式，每64个元素共享1个
- `scale_lv2`: ∈ {1, 2}，每8个元素共享1个（共8个）
- `scale_lv3`: ∈ {1, 2}，每4个元素共享1个（共16个）
- `sign`: ∈ {-1, 0, 1}，每元素1个
- `mant`: ∈ {0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75}，每元素1个

反量化公式：`x_hat = sign * mant * scale_lv3 * scale_lv2 * scale_factor`

### 1.4 标准基线（Algorithm 1 直接转换）
1. 三级树形归约求峰值：64→16→8→1
2. `scale_factor = E6M2_quantize(Vmax / 7)`
3. `E1_8[j] = 1 if (V8[j] / scale_factor ≥ 4) else 0`
4. `E1_16[k] = 1 if (V16[k] / (scale_factor × 2^E1_8) ≥ 2) else 0`
5. `S1P2 = round_to_nearest(V64 / (scale_factor × 2^E1_8 × 2^E1_16))`

## 2. 当前算法设计

### 2.1 核心技术
1. **Exact微指数搜索**：4组合联合优化（3次量化覆盖4种lv2/lv3组合），逐块严格不劣于贪心
2. **E6M2对称窗口Scale Search**：以max/7为中心，E6M2编码索引对称窗口搜索（已验证全局最优=暴力255候选）
3. **64×64随机Hadamard旋转**：Q/K共用（保证Q@K^T不变），V不旋转
4. **对角重要性加权**：Linear权重用λ_j=mean(X_rot²)，激活用w_diag=diag(W_hat^TW_hat)，V用P^TP的rho_t+attention output norm
5. **SmoothQuant alpha扫描**：{None, 0.5}，proxy MSE选择
6. **自适应候选数**：按矩阵规模分配5/7/9候选，自适应chunk_rows

### 2.2 验证状态
- Linear: 10组平均 +0.2803，稳定（std=0.0015）
- Attention: 10组平均 +0.2026，波动大（std=0.0452，范围 +0.065~+0.276）

## 3. 已验证无效的方向（排除清单）

以下方向均已验证失败，不再尝试：

| 方向 | 失败原因 | 验证位置 |
|------|---------|---------|
| GPTQ二阶Hessian舍入 | 校准/测试泛化gap，MSE升6-7% | verify_gptq.py |
| 全K Hadamard旋转 | per-block scale结构反转，MSE升7.4% | verify_hadamard.py |
| AWQ逐通道显著保护 | 合成数据无结构化通道，proxy总选None | verify_awq.py |
| OWQ弱列识别 | E6M2候选n=7已饱和 | verify_owq.py |
| OptRot旋转种子选择 | sign-invariance，非Hadamard更差 | verify_optrot.py |
| NVFP4→HiF4直接映射 | 4 sub-scale差异大(10×)，HiF4无法表示 | verify_direct_mapping.py |
| V per-token clip | V是P@V乘法对象，clip=输出误差 | verify_vclip.py |
| V carrier直接映射 | 平台不支持per-subblock scale恢复 | verify_direct_nvfp4_hif4_attn.py |
| V两遍carrier+re-encode | 双重量化误差 | verify_direct_nvfp4_hif4_attn.py |
| IRLS残差精化 | +0.14%微小正，3/10组略降 | verify_residual_em.py |
| EM交替优化 | +0.13%微小正，与IRLS相同 | verify_residual_em.py |
| V旋转(QuaRot) | 平台不施加H^T补偿 | verify_attn.py |
| GQA grouped-head rotation | K维度不足 | verify_attn.py |
| Q/K importance(K^TK/Q^TQ) | 候选搜索已饱和，完全无变化 | verify_attn.py |
| V importance+PtP全矩阵 | 校准→test泛化gap | verify_attn.py |
| 自适应候选数(outlier block多候选) | 全局13候选反而更差 | verify_attn.py |
| Q/K用Alg1替代E6M2搜索 | 重建差14%，输出更差 | verify_attn.py |
| 无旋转(全部E6M2无Hadamard) | Hadamard对Q/K不可或缺 | verify_attn.py |
| V用L∞替代L2选scale | 重建差，输出差0.05~0.13 | verify_attn.py |
| V用L2+L∞混合度量 | 比纯L2差 | verify_attn.py |
| V用NVFP4 scale作importance | 不稳定：部分组消除负分，部分组制造更差负分 | verify_attn.py |
| V双重importance(rho×NVFP4×rho) | 无稳定提升 | verify_attn.py |
| V用Alg1 scale+exact微指数(混合) | 整体-0.10，不稳定 | verify_attn.py |
| V用纯Alg1 | 重建差，输出差0.05~0.12 | verify_attn.py |

## 4. Attention波动根因分析

### 4.1 波动现象
Attention 10组score从+0.065到+0.276，波动4倍。Linear几乎无波动(+0.277~+0.283)。

### 4.2 根因
波动来自`ratio = MSE_ply / MSE_std`的变化，**不是MSE_ply本身**：
- seq越大，attention越均匀(entropy高)，softmax对量化误差放大均匀→ratio接近1→score低
- seq越小，attention越尖锐，放大不均匀→player的E6M2搜索优势显著→ratio低→score高

**核心约束**：E6M2搜索优化per-block重建MSE，但attention输出MSE=||softmax(Q@K^T)@E_V||²是非线性的。重建好≠attention输出好。

### 4.3 已排除的Attention优化（共24项，详见第3节排除清单）
- V importance（rho/rho+Wout/NVFP4 scale/double/none）：对输出几乎无影响或更差
- V候选数（7/9/13/adaptive）：7已饱和，更多更差
- V量化度量（L2/L∞/mixed）：L2最优
- V clip/旋转/carrier直接映射：平台约束或灾难性
- Q/K importance/Alg1替代/无旋转：更差或无变化
- grouped-head rotation/PtP全矩阵：维度约束或泛化gap

## 5. 待探索方向

### 5.1 Q/K的attention感知量化
当前Q/K用E6M2搜索优化重建MSE。但Q/K的误差通过softmax传播到P，再传播到输出。如果Q/K的scale选择能感知P的变化，可能减少波动。但已验证Q/K importance(K^TK)无效果（候选饱和），Q/K用Alg1更差。

**结论**：当前不可行，E6M2搜索对Q/K已是最优。

### 5.2 V的NVFP4 scale作为隐含重要性
NVFP4的E4M3 scale反映了V每个16-block的局部动态范围。初步测试显示在部分组消除负分（组4: -0.005→+0.018），但在其他组制造更差负分（组6: -0.095→-0.177）。

**结论**：不稳定，不能采用。NVFP4 scale反映数据格式而非attention权重，两者不对齐。

### 5.3 降低V量化误差的新策略
当前V的E6M2搜索已全局最优（=暴力255候选）。已排除L∞度量、混合度量、Alg1 scale混合等变体。

**结论**：在per-block重建MSE度量下已到上限，attention输出层面的优化受限于动态量化时无法获取Q/K（无法算P）。

## 6. 2025-08-25 全面分析：新方向探索与排除

### 6.1 关键发现：verify_attn.py 的 Q/K importance 测试存在 Bug

verify_attn.py 中 `_make_calib_qkimp()` 将 per-channel importance 存入 `q_state["importance"]`，
但 solution.py 的 `hif4_dynamic_quantize_q` 读取的是 `q_state["q_imp"]`。**Key 不匹配导致
importance 从未生效**，"完全无变化" 的结论无效。

重新正确实现后测试（per-channel K^T K → Q importance, Q^T Q → K importance）：
- **结果：仍然零变化**。原因：Hadamard 旋转后 per-channel 范数均匀化（CV=0.06，即标准差仅为
  均值的 6%），13 候选搜索在此均匀重要性下选出的 scale/micro-exponent 与无 importance 时完全一致。
- **真正结论**：不是 bug 导致无效果，而是 Hadamard 旋转使 per-channel importance 失效。

### 6.2 波动根因深化：head_dim 是关键变量

| head_dim | Hadamard blocks/head | 10组平均 score | Q/K-only score |
|----------|---------------------|---------------|----------------|
| 64       | 1 (全覆盖)          | +0.245        | +0.166         |
| 128      | 2 (仅覆盖半头)      | +0.173        | +0.086         |

- hd=128 组的 Q/K 贡献比 hd=64 组小 ~2×（0.086 vs 0.166）
- 原因：baseline 对 hd=128 有"平均效应"（2 个 block 的误差部分抵消），player 的优势比例缩小
- **非 Hadamard 大小问题**：测试 HAD_SIZE=128（整头旋转）反而略差（-0.001~-0.002）

### 6.3 新增排除项（本轮验证）

| 方向 | 结果 | 验证细节 |
|------|------|---------|
| Per-channel Q/K importance (K^TK)（正确实现） | **零变化** | Hadamard 后 CV=0.06，importance 均匀化 |
| K^TV·V^TK importance（含 V 因子） | **零变化** | CV=0.063 vs K^TK 的 0.060，仅多 5%，仍饱和 |
| Q/K Hadamard 大小 = head_dim (128→128×128) | **略差** | -0.001~-0.002，Sylvester 结构差异 |
| V 零偏差修正（minimize ‖Σ E_V‖²） | **零变化** | 偏差仅占实际 V 误差的 0.18%，可忽略 |
| V rank-1 P^TP 修正（top eigenvector, λ=0.5） | **零变化** | diag_frac≈1.0，off-diagonal 贡献 <1% |
| Two-pass V importance（P from quantized Q/K） | **净负** | 坏组 +0.0015，好组 -0.0024，net -0.22% |

### 6.4 V importance 近似精度验证

通过实际计算 `||P @ E_V||²` 与 `Σ_t ρ_t ||E_V[t]||²`（对角近似）对比：

| 组 | head_dim | seq | diag_frac (diag/actual) |
|----|----------|-----|--------------------------|
| 0  | 128      | 128 | 1.009                    |
| 1  | 64       | 128 | 0.955                    |
| 2  | 128      | 192 | 0.990                    |
| 3  | 64       | 256 | 0.980                    |
| 4  | 128      | 96  | 0.952                    |

**diag_frac ≈ 1.0**：当前 rho_t（P^TP 对角线）已是最优 V importance 近似，off-diagonal 项贡献 <5%
且不稳定（校准→测试泛化 gap）。无需更高阶近似。

### 6.5 Hadamard 旋转的"均匀化悖论"

Hadamard 旋转是 Q/K 量化的核心（无旋转时 Q/K 重建差 14%），但它同时使所有 per-channel 统计量
均匀化，导致：

1. **Per-channel importance 失效**：K^TK、K^TVV^TK、Q^TQ 的 per-channel 变异系数仅 6%
2. **Per-token importance 有效**：rho_t（per-token）变异系数大（与 P 的 non-uniformity 对齐）
3. **无法两全**：移除 Hadamard 会大幅恶化 Q/K 重建，保留 Hadamard 则 per-channel importance 无效

### 6.6 根本性约束总结

当前算法已在以下层面达到理论上限：
- **Scale 搜索**：13 候选 = 255 暴力（已验证全局最优）
- **Micro-exponent**：exact 4 组合联合搜索（严格不劣于贪心）
- **V importance**：rho_t 对角近似 diag_frac ≈ 1.0（off-diagonal <5%，不泛化）
- **Q/K importance**：Hadamard 后 per-channel CV=0.06（importance 无法改变 scale 选择）
- **V bias**：仅占 0.18% of attention V 误差（零偏差修正无效）
- **Q/K Hadamard**：HAD=64 最优，更大或更小均更差

**波动来源是数据特性（head_dim=64 vs 128），非算法缺陷。** 在当前 HiF4 格式约束下
（64-element block, E6M2 scale, 2-bit micro-exponent），Attention 的 per-block 重建优化
已到上限。进一步改善需要突破格式约束（如 per-subblock scale、learned rotation、或 attention-
output-aware joint optimization 需要动态时获取 Q/K/V 全部数据）。

## 7. head_dim 自适应研究（基于算法大赛接口）

### 7.1 接口能力分析

算法大赛接口 `hif4_calibration_attention(calib_qkv_list, q_num_heads, kv_num_heads, head_dim)`
传入 head_dim，且 `hif4_dynamic_quantize_q/k/v` 也接收 head_dim，因此**完全支持基于 head_dim 的
自适应策略**。关键约束（§6.5 已述）：Hadamard 旋转后 per-channel CV=0.06，importance 无法改变
scale 选择；V importance per-token，在 64-channel block 内恒定，无法改变 scale 选择。

### 7.2 head_dim 自适应测试结果

| 方向 | 结果 | 细节 |
|------|------|------|
| HAD_SIZE=hd (128→128×128 整头旋转) | **略差** | -0.001~-0.002/组，Sylvester 结构差异 |
| Per-channel Q/K imp (K^TK, 正确key实现) | **零score变化** | 6.8% block scale 变化但 MSE_player 不变 |
| K^TV·V^TK importance (含V因子) | **零变化** | CV=0.063 vs K^TK 的 0.060，仅多5% |
| Cross-function V imp (test-time P) | **零变化** | importance 在 search domain 内恒定 |
| SmoothQuant Q/K (per hd channel, α=0.5) | **零变化** | dot-product 保持验证 ✓，但 block 不平衡未修复 |
| Q attention-output tie-breaking (K^TK proxy) | **零变化** | 72% block 有 near-tie 但 proxy ≈ recon MSE |
| 13→255 候选 (hd=128) | **零变化** | scale diff = 0/2048，确认全局最优 |
| Block 不平衡分析 (hd=128) | 存在但不影响 | ratio 0.67-1.43，E6M2搜索已处理 |

### 7.3 根因：importance 无效的数学结构

**Per-token importance (rho_t)**：在 64-channel block 内恒定 → `_quantize_block_given_scale`
中 `imp * (dq-ref)²` 的 imp 可提取为标量 → 不改变 argmin → scale/micro-exponent 选择不变。

**Per-channel importance (K^TK)**：Hadamard 后 CV=0.06 → importance ≈ uniform → 加权 MSE ≈ 
unweighted MSE × const → 不改变 argmin。

**Cross-function P (test-time)**：P ≈ P_calib (entropy≈0.99, ||P_hat-P_ref||=3.4%) → rho_t 几乎
相同 → importance 不变 → scale 选择不变。

### 7.4 验证：72% block 存在 near-tie 但 tie-breaking 无效

对 hd=128 的 200 个 Q block 分析：
- **72%** 的 block 有 >1 个 E6M2 候选在 5% MSE 范围内（near-tie）
- K^TK importance 改变了 6.8% block 的 scale 选择
- **但 MSE_player 完全不变**：changed block 的 attention 贡献小，且 K^TK proxy ≈ recon MSE

这证实：即使存在大量 near-tie，attention-output tie-breaking 也无法改善，因为 Hadamard 使
K^TK proxy 与 recon MSE 高度相关（选择相同的候选）。

## 8. 从算法大赛任务书角度的全面研究点汇总

### 8.1 已测试且有效（当前 solution.py 采用）

| 研究点 | 场景 | 效果 | 来源 |
|--------|------|------|------|
| Exact 4组合微指数搜索 | Linear+Attn | 严格不劣于贪心 | §2.1 |
| E6M2对称窗口搜索 (13=255暴力) | Linear+Attn | 全局最优 | §2.1 |
| 64×64 随机 Hadamard (Q/K共用) | Attn | Q@K^T保持, 重建+14% | §2.1 |
| 对角重要性加权 (λ_j/diag(W^TW)/rho_t) | Linear+Attn | 输出MSE对齐 | §2.1 |
| SmoothQuant α扫描 {None,0.5} | Linear | proxy MSE选择 | §2.1 |
| 自适应候选数 (5/7/9) | Linear | 时间控制 | §2.1 |
| BoA V importance (rho_t × out_norm, α=0.5) | Attn | Wout^TWout 近似 | §2.1 |

### 8.2 已测试无效（排除清单，含本轮新增）

| 研究点 | 场景 | 结果 | 验证 |
|--------|------|------|------|
| GPTQ二阶Hessian舍入 | Linear | MSE升6-7% | verify_gptq.py |
| 全K Hadamard旋转 | Attn | MSE升7.4% | verify_hadamard.py |
| AWQ逐通道显著保护 | Linear | proxy总选None | verify_awq.py |
| OWQ弱列识别 | Linear | 候选n=7已饱和 | verify_owq.py |
| OptRot旋转种子选择 | Attn | sign-invariance | verify_optrot.py |
| NVFP4→HiF4直接映射 | Attn | 4 sub-scale差异10× | verify_direct_mapping.py |
| V per-token clip | Attn | clip=输出误差 | verify_vclip.py |
| V carrier直接映射 | Attn | 平台不支持 | verify_direct_nvfp4_hif4_attn.py |
| IRLS残差精化 | Linear | +0.14%微小 | verify_residual_em.py |
| EM交替优化 | Linear | +0.13%微小 | verify_residual_em.py |
| V旋转(QuaRot) | Attn | 无H^T补偿 | verify_attn.py |
| GQA grouped-head rotation | Attn | K维度不足 | verify_attn.py |
| Q/K importance(K^TK) | Attn | **零变化**(bug修复后确认) | verify_attn.py + 本轮 |
| V importance+PtP全矩阵 | Attn | 泛化gap | verify_attn.py |
| 自适应候选数(outlier block多候选) | Attn | 全局13反而更差 | verify_attn.py |
| Q/K用Alg1替代E6M2搜索 | Attn | 重建差14% | verify_attn.py |
| 无旋转 | Attn | Hadamard不可或缺 | verify_attn.py |
| V用L∞/L2混合度量 | Attn | 比纯L2差 | verify_attn.py |
| V用NVFP4 scale作importance | Attn | 不稳定 | verify_attn.py |
| V双重importance | Attn | 无稳定提升 | verify_attn.py |
| V用Alg1 scale+exact微指数 | Attn | -0.10不稳定 | verify_attn.py |
| **HAD_SIZE=hd (整头旋转)** | **Attn** | **略差-0.001~-0.002** | **本轮** |
| **K^TV·V^TK importance** | **Attn** | **零变化(CV仅多5%)** | **本轮** |
| **Cross-function V imp (test-time P)** | **Attn** | **零变化(imp恒定)** | **本轮** |
| **V零偏差修正** | **Attn** | **零变化(偏差0.18%)** | **本轮** |
| **V rank-1 P^TP修正** | **Attn** | **零变化(diag_frac≈1.0)** | **本轮** |
| **SmoothQuant Q/K (per hd channel)** | **Attn** | **零变化(不可平衡block)** | **本轮** |
| **Q attention-output tie-breaking** | **Attn** | **零变化(proxy≈recon)** | **本轮** |
| **Two-pass V importance** | **Attn** | **净负-0.22%** | **本轮** |

### 8.3 从任务书三大挑战出发的研究点

#### 挑战1: Scale层级断裂 (NVFP4 FP32+E4M3 → HiF4 E6M2+E1_8+E1_16)

| 研究点 | 思路 | 可行性 | 状态 |
|--------|------|--------|------|
| NVFP4 E4M3 scale → micro-exponent hint | 用4个sub-block的E4M3 scale ratio推断lv2/lv3 | 已排除(§3: NVFP4 scale不稳定) | ❌ |
| NVFP4 E4M3 scale → E6M2 scale_factor warm start | 用E4M3的max作为E6M2搜索起点 | 13=255已全局最优，起点无意义 | ❌ |
| 跨格式scale联合优化 | 同时优化NVFP4和HiF4 scale | NVFP4是输入(不可修改) | ❌ |

#### 挑战2: 值集空间错位 (E2M1 {0,0.5,1,...,6} → S1P2 {0,0.25,...,1.75})

| 研究点 | 思路 | 可行性 | 状态 |
|--------|------|--------|------|
| E2M1→S1P2 value-aware rounding | 考虑E2M1原值，选择最接近的S1P2值 | FP32精确值已知，E2M1原值无额外信息 | ❌ |
| 反量化-再量化误差补偿 | 对二次截断误差做补偿 | IRLS/EM已测试，+0.14%微小 | ❌ |
| Stochastic rounding | 用随机舍入代替round-to-nearest | round-to-nearest是MSE最优；bias仅0.18% | ❌ |
| Biased rounding toward zero | 减少aggregate bias | bias仅0.18%，零偏差修正无效 | ❌ |

#### 挑战3: Outlier敏感度跃升 (block_size 16→64)

| 研究点 | 思路 | 可行性 | 状态 |
|--------|------|--------|------|
| Hadamard outlier suppression | 64×64随机旋转 | **已采用**，Q/K不可或缺 | ✅ |
| Per-block max clipping | 对极端outlier做clip | clip=输出误差(已排除) | ❌ |
| SmoothQuant outlier migration | 用D将outlier从激活迁移到权重 | Linear已采用(α扫描)；Q/K零效果 | ⚠️ |
| NVFP4 scale作outlier indicator | E4M3 scale大=outlier存在 | 不稳定(§3) | ❌ |
| Block-level adaptive scale | 不同block用不同策略 | 13=255已全局最优 | ❌ |

### 8.4 从接口约束出发的未测试研究点

| 研究点 | 接口利用 | 可行性分析 | 优先级 |
|--------|----------|-----------|--------|
| SmoothQuant α扫描扩展 ({None,0.25,0.5,0.75,1.0}) | Linear calib_state | 当前{None,0.5}可能非最优；但Linear已+0.28稳定 | 低 |
| Cross-function Q/K/V联合 (module cache) | q/k/v_state + 模块变量 | test-time P→V importance：零效果(imp恒定) | ❌ 已测 |
| Per-head adaptive SmoothQuant α | calib_state per-head | Hadamard后CV=0.06，per-head无差异 | ❌ |
| Inter-sample adaptation (每test sample更新state) | q_state/k_state/v_state | 运行时更新state→下一样本受益；但5样本太少 | 低 |
| State compression (节省state空间存更多统计量) | state 4096节点限制 | 当前state远低于限制，无需压缩 | N/A |
| Time budget allocation (难组多花时间) | 总时间5分钟/50组 | 当前每组~5s，50组=250s<300s，有余量 | 中 |
| Score-floor guarantee (保守量化防负分) | 所有场景 | 当前10/10正分，无负分风险 | 低 |
| Full P^TP for V (非对角项) | v_state + cross-fn | diag_frac≈1.0, off-diag<5%不泛化 | ❌ 已测 |
| Attention-output-aware Q scale (full ‖E_Q@K^T‖²) | q_state + cross-fn K | = K^TK importance（已测零效果） | ❌ 已测 |

### 8.5 理论上限分析

当前 solution.py 在 HiF4 格式约束下的优化层次：

```
┌─────────────────────────────────────────────────────────┐
│ Scale Factor (E6M2)   13候选 = 255暴力    ← 已全局最优  │
│ Micro-Exponent (lv2/lv3)  exact 4组合     ← 已严格最优  │
│ Rounding              round-to-nearest    ← MSE最优     │
│ Hadamard              64×64 Sylvester     ← 最优大小    │
│ V Importance          rho_t (P^TP diag)   ← diag_frac≈1 │
│ Q/K Importance        per-channel CV=0.06  ← Hadamard均化│
│ V Bias                0.18% of error       ← 可忽略     │
│ Q/K P preservation    P_hat≈P_ref (3.4%)  ← 几乎相同   │
└─────────────────────────────────────────────────────────┘
```

**结论**：在 HiF4 格式约束下（64-element block, E6M2 scale, 2-bit micro-exponent,
S1P2 mantissa），所有可调参数均已达到理论上限。波动来源是数据特性（head_dim=64 vs 128），
具体是 baseline 对 hd=128 的"多block平均效应"使 MSE_std 偏小，导致 player 的提升比例缩小。

**进一步改善的唯一途径**（均需突破当前格式/接口约束）：
1. **Per-subblock scale**：允许 64-block 内的 16-element sub-block 有独立 scale → 需要 HiF4 格式扩展
2. **Learned rotation**：用数据驱动的旋转矩阵替代固定 Hadamard → 需要离线训练 + 在线推理开销
3. **Attention-output joint optimization**：需要 Q/K/V 全部数据同时可用（当前接口分3次调用）
4. **Non-uniform block size**：对 outlier 密集区域用更小 block → 需要格式支持

## 9. 参考资料

1. HiFloat4 Format for Language Model Inference (arxiv 2602.11287)
2. Pretraining Large LLMs with NVFP4 (arxiv 2509.25149)
3. SmoothQuant (arxiv 2211.10438)
4. GPTQ (arxiv 2210.17323)
5. QuIP (arxiv 2307.13304)
6. QuIP# (arxiv 2402.04396)
7. QuaRot (arxiv 2404.00456)
8. AWQ (arxiv 2306.00978)
9. TurboQuant (arxiv 2504.19874)
10. OWQ (arxiv 2306.02272)
11. OptRot (arxiv 2512.24124)
12. HIGGS (arxiv 2411.17525)
13. GPTVQ (arxiv 2402.15319)
14. AQLM (arxiv 2401.06118)
15. PV-Tuning (arxiv 2405.14852)
16. BoA (arxiv 2406.13474)
17. RotateKV (arxiv 2501.16383)
18. KIVI (arxiv 2402.02750)
19. KVQuant (arxiv 2401.18079)
20. QERA (arxiv 2410.06040)
21. DFRot (arxiv 2412.00648)
22. SpinQuant (arxiv 2405.16406)
