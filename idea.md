# solution-13000.py 的可落地优化方案

更新时间：2026-08-20

本文针对当前平台分数约 13000、最高约 26000 的 `solution-13000.py`，结合比赛接口、HiF4 离散约束和截至 2026-08-20 的相关文献，给出可以在本题中实施的优化方案。文中“保证”分为两类：

* 对固定输入、固定候选集合的数学保证；
* 对隐藏测试集的经验性预期。隐藏测试集未知，因此不能诚实地承诺一定提升到某个分数。

## 一、结论与优先级

当前算法已经包含若干正确方向：HiF4 的 E1 联合搜索、SmoothQuant 形式的可逆平衡、Linear 的二阶通道权重，以及 V 的 `P^T P` token 权重。13000 分的主要瓶颈不是 HiF4 格式本身，而是以下三点：

1. Linear 校准阶段仍以加权逐元素重建 proxy 选择 `alpha`，没有把最终的 `X_HiF4 W_HiF4^T` MSE 作为最终裁判。
2. Attention 只对 V 使用 `rho_t`，Q/K 仍是无校准的普通量化；Q/K/V 也没有在校准集上联合排序。
3. 旋转、平滑、E6M2 候选数量是全局或角色级固定策略，没有按 block/head 的异质性选择；`n_candidates=13` 还会把大量时间花在在线搜索上。

建议顺序如下：

| 优先级 | 改动 | 预期收益 | 风险 |
|---|---|---:|---:|
| P0 | Linear 用真实端到端校准 MSE 选候选，并保留旧方案 | 高 | 低 |
| P0 | Attention 校准时联合量化 Q/K/V 并以 Attention MSE 排序 | 高 | 中 |
| P1 | Q/K softmax-Jacobian 曲率权重 | 中到高 | 中 |
| P1 | GQA 共享的 Q/K 对角平衡 `Q D, K D^{-1}` | 中 | 低 |
| P1 | 64-block/head 内的 rotation on/off 或有限 sign-permutation | 中 | 中 |
| P2 | 受阻尼协方差的 block-GPTQ/TurboBoA 式残差补偿 | 高但不稳定 | 高 |
| P2 | 长序列采用对角曲率近似，短序列才计算 dense Jacobian | 保证不超时 | 低 |

不要直接照搬文献中的非法或不匹配组件：本题返回的 `scale_factor` 必须是 E6M2，不能保存 FOCUS 的任意 full-precision scale；本题只有单个 HiF4 输出，没有 SharQ 的 sparse/dense 第二条 GEMM，也没有 HyperQuant 的额外 bias 通道。

## 二、文献检索结果及可迁移性

以下为截至 2026-08-20 通过 arXiv 检索并核验摘要后的主要资料。

### 1. 直接相关的 FP4/微缩放工作

* [HiFloat4 Format for Language Model Inference, arXiv:2602.11287](https://arxiv.org/abs/2602.11287)，2026-02。HiF4 使用 64 个 4-bit 元素和三级缩放层级，目标就是以更大的 block 获得更好的动态范围利用率。它支持本题的基本形状和合法值集，但没有给出本题 NVFP4 输入到 HiF4 的输出敏感度搜索算法。
* [Pretraining Large Language Models with NVFP4, arXiv:2509.25149](https://arxiv.org/abs/2509.25149)，2025-09，2026-03 修订。文中采用 RHT 限制 block outlier，并强调不同前向/反向路径的量化目标不同。对本题的启示是旋转应与算子不变量配对，而不是单独对一个 operand 旋转。
* [FOCUS: FP4 Optimization via Coupled-Relaxation and Dual-Granularity Scaling, arXiv:2608.01847](https://arxiv.org/abs/2608.01847)，2026-08-03。它指出量化 scale 与反量化 scale 被硬件格式强行绑定会造成优化损失，并用 coupled-relaxation 和更细的 dual-granularity scale 改善 NVFP4/MXFP4。对本题能迁移的是“用输出目标搜索合法离散 scale”和“利用子块异质性”；full-precision 的额外 scale 不能写入 HiF4 状态，因此不能直接照搬 CRS。
* [Heterogeneity-Aware Microscaling (AdaMX), arXiv:2608.03867](https://arxiv.org/abs/2608.03867)，2026-08-04。它按 block 选择 precision-recovery scheme，并按 operand 选择 representation，报告在 NVFP4 上显著减少精度损失。对本题的可行版本是为每个 64-block/head 选择有限的合法 mode（普通、旋转、裁剪侧 scale、曲率权重），而不是所有 block 使用同一个全局 mode。
* [MXAttention, arXiv:2607.24377](https://arxiv.org/abs/2607.24377)，2026-07-27。它分析了 power-of-two scaling 的 clipping-underflow trade-off 以及 softmax 行归一化误差。虽然目标格式是 MXFP4，但对本题直接说明：Attention 的 scale 搜索不能只看张量 MSE，应看 logits/softmax/output；如果平台实现存在额外 softmax 量化，则应在校准候选中模拟该归一化。
* [SharQ, arXiv:2606.26587](https://arxiv.org/abs/2606.26587)，2026-06-25。它用输入自适应 sparse backbone 加 dense residual 同时抵消 outlier 和 sparsification error，并声称可迁移到 NVFP4、HiF4、MXFP4。由于本题没有第二个输出路径，不能直接实现 sparse-dense GEMM；能迁移的是“先识别 outlier，再用残差定义量化目标”，具体可实现为 trimmed-scale 候选或 outlier-aware importance。
* [HyperQuant, arXiv:2606.23406](https://arxiv.org/abs/2606.23406)，2026-06-22。它结合 per-tile RHT、低维 lattice 和使 KV inner product 无偏的 bias correction。对本题可用的是 tile/head 内旋转和 inner-product 目标；额外 bias correction 没有 HiF4 输出字段，不能直接写回结果。

### 2. 输出感知、旋转和二阶 PTQ

* [TurboBoA, arXiv:2602.04929](https://arxiv.org/abs/2602.04929)，2026-02-04。它用多 output-channel 联合量化、闭式误差补偿、前层误差修正和 adaptive grid，目标是保留 BoA 的 attention-aware Hessian 收益并加速。可迁移为校准阶段的 block-level residual compensation，不宜直接在在线函数中做顺序 GPTQ。
* [BoA, arXiv:2406.13474](https://arxiv.org/abs/2406.13474)，ICML 2025。它引入 attention-aware Hessian，显式考虑 Attention 模块内部层间依赖。当前接口输入的是 Q/K/V 张量而不是投影权重，因此应使用相同的一阶 Jacobian 推导在 Q/K/V 张量上构造对角或小块曲率。
* [SpinQuant, arXiv:2405.16406](https://arxiv.org/abs/2405.16406)，ICLR 2025。它指出不同随机旋转的量化效果差异很大，并学习能保持 full-precision 输出不变的 rotation。比赛中不能存任意大矩阵并在线做昂贵乘法，但可以在校准集上比较少量固定 sign-permutation/Hadamard 候选。
* [QuaRot, arXiv:2404.00456](https://arxiv.org/abs/2404.00456)。它通过计算不变量旋转消除 outlier，并将该变换应用到 hidden state、FFN、Attention 和 KV。这里最重要的是“不变量”：Q/K 必须使用配对的同一变换，Linear 的 X/W 也必须使用互逆变换。
* [GPTQ, arXiv:2210.17323](https://arxiv.org/abs/2210.17323)。它使用近似二阶信息进行 one-shot weight quantization。本文的 block-GPTQ 方案应视为候选优化器，而不是 HiF4 离散全局最优证明。
* [SmoothQuant, arXiv:2211.10438](https://arxiv.org/abs/2211.10438)。它通过可逆对角变换把 activation outlier 难度迁移到 weight。当前代码已经使用 alpha=0.5 的一个特例，仍应扩大 alpha 候选并以真实 Linear output loss 选择。

## 三、对 solution-13000.py 的逐项审查

### 3.1 E1 搜索已经接近正确，不应首先重写

`_quantize_block_given_scale` 已将两个 4-value 子组的 `E1_16` 选择纳入共享 `E1_8` 的联合比较。固定 E6M2 scale `s` 后，令

```text
L_g(a,b) = sum_j w_j (Q_{s,a,b}(x_{g,j}) - x_{g,j})^2,
a,b in {0,1}.
F(a) = sum_g min_b L_g(a,b).
```

正确选择为 `a*=argmin_a F(a)`，再取每个子组的 `b_g*`。旧贪心的输出属于同一有限可行集合，因此联合搜索满足

```text
min_{a,b_1,b_2} sum_g L_g(a,b_g)
    <= sum_g L_g(a_old,b_old_g).
```

这条保证对“当前加权逐元素目标”成立。它不等于对最终 Attention/MatMul 输出必然不劣，所以进一步改进的重点必须放到校准目标，而不是继续增加 E1 分支。

### 3.2 Linear 的最大缺口是 proxy 与评分目标不一致

当前代码在 `hif4_calibration_and_quantize_weight` 中只扫描 `alpha in {None, 0.5}`，使用 `n_candidates=3` 的权重 proxy，再用 `w_imp` 加权的重建误差选配置，最终却使用 `n_final` 重新量化。也就是说，校准时选的并不是最终真正返回的参数。

建议把每个候选定义为

```text
C = (alpha, H, scale-window, importance-mode, optional block-mode)
```

对每个候选在 5 份校准数据上完整执行：

```text
W_C = dequant(quantize(W * D_alpha, H, C))
X_C = dequant(quantize(X / D_alpha, H, C))
L_cal(C) = mean ||X_C W_C^T - X W^T||_F^2.
```

候选集合必须包含当前 `solution-13000.py` 的配置；选择 `argmin_C L_cal(C)` 后，校准集损失机械地满足 `L_cal(new) <= L_cal(old)`。推荐 alpha 集合为 `{0, 0.25, 0.5, 0.75, 1}`，其中 `0` 是无平滑回退，`1` 是更强 activation smoothing；实际可用 RMS/99.5 percentile 代替 max 统计，避免一个校准 outlier 使 `D` 过大。

#### Linear 理论证明

令 `E_W = W_hat-W`，把校准 activation 堆叠为 `X`，则

```text
1/n ||X E_W^T||_F^2
 = tr(E_W C_X E_W^T),   C_X = X^T X/n.
```

若在 Hadamard 坐标中用 `C_X ~= diag(lambda)`，就得到当前代码的 weighted MSE：

```text
sum_{out,j} lambda_j E_W[out,j]^2.
```

它是输出 MSE 的对角 Hessian 近似。对激活误差 `E_X=X_hat-X`，固定 `W_hat` 后有

```text
1/n ||E_X W_hat^T||_F^2
 = tr(E_X (W_hat^T W_hat) E_X^T)/n.
```

因此 `diag(W_hat^T W_hat)` 作为 activation importance 是有理论依据的；但在两侧同时量化时还存在 `E_X E_W^T` 的二阶交叉项，所以必须用上面的真实端到端校准 loss 做最终排序。

### 3.3 可逆变换应从单一随机 H 扩展为有限候选族

当前 Linear/Attention 使用固定随机 Hadamard。SpinQuant 的结果说明旋转本身存在明显的实例差异。建议在校准阶段比较：

1. identity；
2. 当前 seed=42/123 的 Hadamard；
3. 两个额外 sign-permutation-Hadamard；
4. 仅对 outlier 最强的 64-block 使用 rotation，其余 block identity。

若 `H H^T=I`，Linear 采用

```text
X' = X D^{-1} H,       W' = W D H
```

则无量化时

```text
X' W'^T = X D^{-1} H H^T D W^T = X W^T.
```

Attention 的 GQA 配对变换为：对每个 KV head group `g`，所有映射到它的 Q head 使用同一个 `R_g`：

```text
Q'_h = Q_h R_g,        K'_g = K_g R_g,
Q'_h K'_g^T = Q_h K_g^T.
```

因此 logits、softmax 和无量化 Attention 输出严格不变。不能对 Q、K 独立使用不同随机 H，也不能在 `head_dim` 不满足 64 对齐时跨 head 混合。

### 3.4 Attention Q/K 目前没有输出敏感度

当前校准函数只计算 V 的 `rho`，Q/K 在线函数只是 Hadamard 加 13 个 E6M2 候选。应在 `hif4_calibration_attention` 中计算少量曲率状态。

对单个 head 写

```text
S = QK^T/sqrt(d) + M,   P = softmax(S),   O = PV,
J_i = diag(p_i) - p_i p_i^T.
```

忽略高阶交叉项时，`dP_i = J_i dS_i`，令

```text
G_i = J_i V V^T J_i.
```

则 Q 的 Gauss-Newton 曲率为

```text
H_Q[i] = K^T G_i K / d.
```

可累加 `diag(H_Q[i])` 得到 Q channel importance。对 K 的 token/维度对角近似可取

```text
w_K[t,r] = sum_i G_i[t,t] Q[i,r]^2 / d.
```

V 的精确误差恒等式是

```text
||P(V_hat-V)||_F^2
 = tr(E_V^T P^T P E_V).
```

若不同 token 的 V 量化误差近似不相关，得到当前代码使用的

```text
rho_t = sum_i P[i,t]^2.
```

这说明当前 V 方向是正确的，但 Q/K 也应采用同样的 Jacobian 思路。GQA 中 K 的曲率要把同一 KV head 映射的所有 Q head 累加，否则会低估 K 的重要性。

### 3.5 Attention 必须做校准集上的联合候选排序

建议构造不超过 4–6 个静态 mode：

```text
M0: 当前 baseline；
M1: head-safe H；
M2: Q/K curvature + V rho；
M3: Q/K diagonal balance + V rho；
M4: H + curvature；
M5: H + balance + curvature（仅短序列）。
```

每个 mode 都在全部 calibration sample 上分别量化 Q/K/V，再计算

```text
L_attn(M) = mean ||Attn(Q_hat,K_hat,V_hat)-Attn(Q,K,V)||_F^2.
```

选择最小 mode，并把 mode、Hadamard、importance、balance 保存到纯 CPU state。因为 M0 是旧方案，校准 loss 有严格的不劣保证；隐藏集的提升依赖校准集代表性。

当前 `_compute_v_importance` 要特别检查 mask。若平台是 causal attention，必须用同一个 causal mask `M` 计算 `P`；无 mask 与 causal 的 `rho` 不可混用。题目只写 GQA，不能从题面推断 mask。

### 3.6 Q/K 的对角平衡是低风险新点

对 KV group 选正对角 `D_g`，令

```text
Q'_h = Q_h D_g,
K'_g = K_g D_g^{-1}.
```

则 logits 完全不变。可用 calibration 的 RMS/percentile 统计扫描 `alpha`：

```text
D_j(alpha) = qmax_j^alpha / kmax_j^(1-alpha),
alpha in {0, .25, .5, .75, 1}.
```

限制 `D_j` 在 `[1/16,16]` 内，避免 E6M2 scale 溢出。Q/K 两边必须共享 KV group 的同一个 D；只给 Q 乘 D 或只给 K 除 D 都会改变 logits。

### 3.7 Scale 搜索应使用“旧候选并集 + 低尺度侧窗口”

`amax/7` 是格式参考转换，不是任意分布上的输出 MSE 最优定理。当前代码的 13 点对称窗口方向正确，但应确保候选覆盖低于 `amax/7` 的 binade，而不是只围绕 `searchsorted` 的上侧。对每个 block，设候选集合从 `S_old` 扩展到 `S_new`，则

```text
min_{s in S_new} L(s) <= min_{s in S_old} L(s).
```

这里的 `L` 应使用 weighted reconstruction 或 calibration output loss；候选数量不宜无限增大。推荐：短张量 9 点、常规张量 7 点、超大张量 5 点；Attention 校准 5 点，在线 7–9 点。若在线函数没有校准输出可用，优先保存正确的静态 importance，而不是在线做多次完整 Attention。

### 3.8 AdaMX 式 block heterogeneity 的本题版本

当前算法只对每个 block 搜索 scale，变换和 importance mode 基本是全局固定。可对每个 64 元素 block 计算一个廉价 outlier 指标，例如

```text
r_b = max_abs(block) / (RMS(block)+eps).
```

对 `r_b` 大的 block 比较 identity/Had; 对其余 block 保持 identity。Linear 必须把同一个 block mode 记录到 state，使在线 activation 使用同一 paired transform；Attention 必须以 head/group 为单位。最终仍需把当前全局 mode 作为候选，以避免校准退化。

### 3.9 GPTQ/TurboBoA 只应作为受限离线候选

令输入协方差 `C=X^T X/n`，权重误差按输入通道分成已量化 block `b` 和未量化部分 `r`：

```text
L = tr(E_b C_bb E_b^T)
  + 2 tr(E_b C_br E_r^T)
  + tr(E_r C_rr E_r^T).
```

固定 `E_b` 后，对连续的 `E_r` 求导，得到条件最优补偿

```text
E_r* = - E_b C_br C_rr^{-1}.
```

实现上可使用 `C_rr + lambda I` 的 Cholesky/solve，对相邻 64-block 做一轮补偿，再把补偿后的量化结果与普通结果用真实 calibration output loss 比较。由于 HiF4 的 scale、E1_8、E1_16 是离散且 block-coupled，不能宣称该局部补偿是全局离散最优；必须保留普通候选回退。TurboBoA 的“多 output-channel 联合 + 闭式补偿”可用于减少逐列循环，但不应在线执行。

## 四、校准与隐藏测试的理论边界

### 4.1 校准集不劣不代表隐藏集不劣

若候选集合有限为 `m`，每个 MSE 损失有上界 `B`，校准样本独立同分布，Hoeffding + union bound 给出：以概率至少 `1-delta`，

```text
sup_C |L_test(C)-L_cal(C)|
 <= B * sqrt(log(2m/delta)/(2n)).
```

因此候选集合应小而有针对性；把几十个相关 mode 全部塞入校准会增加选择方差。应记录 50 组上的负分 case 数，而不能只看平均 calibration MSE。

### 4.2 score 与 MSE 的关系

平台每 case 的提升为

```text
score = (MSE_STD - MSE_PLAYER) / MSE_STD.
```

所以优化目标应直接最小化 MSE_PLAYER，而不是单独最小化 weight/activation reconstruction MSE。若某个 mode 让 `MSE_PLAYER > MSE_STD`，该 case 会产生负分；所有候选必须包含当前方案或普通 HiF4 baseline。

## 五、建议的实施顺序与验收标准

### 第一步：Linear 真实目标重排

* alpha 使用 `{0,.25,.5,.75,1}`；
* scale window 使用旧窗口与低尺度额外候选的并集；
* 校准时用最终相同的候选数量；
* 对每个 mode 计算真实 `X_hat @ W_hat.T` MSE；
* state 保存 paired transform、importance 和必要的轻量 Gram；
* 旧方案作为显式回退。

验收：50 组 calibration MSE 不增加，测试集负分 case 不增加，运行时间增加不超过预算的 25%。

### 第二步：Attention 联合 mode

* 先确认平台 mask、softmax dtype、GQA head repeat；
* 短序列计算 Q/K Jacobian 对角曲率，长序列用 diagonal proxy；
* 扫 baseline、H、curvature、Q/K balance 组合；
* 用真实 Attention output MSE 选 mode；
* 测试序列长度与 calibration 不同则对 `rho` 做归一化位置插值或回退 mean，不能直接复制错误长度。

验收：所有返回参数通过 `self_check.py`；不同 head_dim、不同 seq_len、不同 GQA ratio 均不异常；Attention 负分 case 下降。

### 第三步：受限 GPTQ/TurboBoA 候选

只在矩阵较小、校准 token 足够且阻尼协方差条件数可控时启用。必须把普通方案作为候选，且以真实 calibration output MSE 最终裁决。若总耗时接近 5 分钟，先删除 GPTQ，而不是删除 exact E1 搜索或 baseline 回退。

## 六、不可直接采用的“看似高级”方案

1. FOCUS 的 full-precision CRS scale：违反返回参数的 E6M2 `scale_factor` 合法性。
2. SharQ 的 sparse+dense 双路径：本题接口每次只能返回一套 HiF4 参数，评测器只执行一次 GEMM。
3. HyperQuant 的额外 bias correction：state 可以存 bias，但评测器不会自动把 bias 加回 Attention/MatMul 输出。
4. 任意全矩阵 learned rotation：state 虽允许 Tensor，但在线 `O(C^2)` 乘法可能超过 5 分钟，并且必须同时修改 paired operand。
5. 只在 calibration proxy 上选择几十个 mode：会增加 hidden distribution selection variance，且可能造成负分。

## 七、最终判断

最有希望把 13000 分继续推高的不是再增加 E1 分支，而是：

```text
Linear: true end-to-end calibration reranking
      + alpha/block-wise transform candidates

Attention: Q/K Jacobian curvature
          + GQA-shared Q/K balance
          + joint Q/K/V Attention-MSE reranking

Runtime: small candidate set + long-context diagonal approximation
```

这些改动的共同性质是：在不改变 HiF4 合法输出格式的前提下，把优化目标从“元素重建”移到了平台真正评分的 MatMul/Attention 输出。理论上可以保证固定候选集合的 calibration 不劣；隐藏平台能否接近 26000，则取决于校准集代表性、mask 一致性和运行时间是否满足限制。
