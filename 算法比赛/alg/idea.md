# HiF4 赛题: 8300 分的瓶颈与可证明改进方案

## 结论先行

当前方案不是 HiF4 格式本身的上限，8300 分也不能说明该格式只能到这个水平。它已经有正确的 E6M2 候选搜索和局部尺度结构，但优化的主要是输入张量重建 MSE，而评分的是 **Linear / Attention 最终输出 MSE**。二者一般不等价。

在补充检索 SmoothQuant、QuaRot、SpinQuant、DuQuant、GPTQ 与 BoA（ICML 2025）后，最值得优先实施的改动如下，按预期收益/实现风险排序：

1. 将当前“先定 `E1_8`、再定 `E1_16`”的贪心改为每个 E6M2 候选上的 **精确两层微指数搜索**；并扩展 E6M2 搜索范围。它对当前优化目标有逐块的不劣证明，且不依赖校准数据。
2. 对 Linear 加入 SmoothQuant 式对角平衡，并在相同的函数接口中对两侧应用配对的可逆坐标变换；其未量化输出严格不变。这是当前完全缺失的高优先级 outlier 管理手段。
3. 真正使用 Linear 校准集：权重量化最小化 `E[(X(W_hat-W)^T)^2]`，激活量化最小化 `E[((X_hat-X)W_hat^T)^2]`，而不是普通逐元素 MSE。进一步可用 GPTQ 式全协方差残差补偿；当前 `calib_activation_list` 被完全忽略是最大缺口。
4. Attention 先在校准阶段做 Q/K/V 的联合端到端候选选择，再以一阶曲率作廉价动态代理。V 的正确行重要度来自 `P^T P`，不是当前的 `E[V_j^2]`；Q/K 的重要度来自 softmax Jacobian。
5. 用校准集上真实的端到端 MSE 对少量候选作离线重排序，并保留“普通 MSE 版本”作为回退。所有候选包含旧方案时，校准目标必然不变差。

不能对未知平台测试集严格承诺“必然提升多少分”：评分是隐藏数据的比值 `(MSE_STD-MSE_PLAYER)/MSE_STD`。下面的严格证明针对给定数据或同分布期望；这是能给出的正确理论保证。

## 对当前实现的诊断

### 1. 微指数搜索不是联合最优

[`solution.py`](C:/Users/23363/Desktop/ALG/solution.py) 第 124-162 行先以 `E1_16=0` 的误差选择 `E1_8`，再在该选择下决定 `E1_16`。但 HiF4 的一个 8 元素组含两个 4 元素子组，正确目标应先在每个 4 元素子组比较两种 `E1_16`，再比较两种 `E1_8`。

对固定的 E6M2 scale `s`，令 `L_g(a,b)` 为第 `g` 个 4 元素子组使用 `E1_8=a`、`E1_16=b` 后的（可加权）平方误差，`a,b in {0,1}`。精确解是

```text
F(a) = sum_{g=1,2} min_b L_g(a,b)
a*   = argmin_a F(a)
b_g* = argmin_b L_g(a*,b)
```

当前贪心比较的是 `sum_g L_g(0,0)` 与 `sum_g L_g(1,0)`，这不是 `F(0)` 与 `F(1)`；例如 `a=0,b=1` 可很好地拟合一个子组时，现有代码不会在选择 `a` 时计入该可能性。

**不劣证明。** 旧贪心输出的 `(a_old,b_old)` 属于四种可行组合。精确搜索在相同的有限可行集合上取最小值，因此对每个 8 元素组有

```text
min_{a,b1,b2} [L_1(a,b1)+L_2(a,b2)]
<= L_1(a_old,b1_old)+L_2(a_old,b2_old).
```

块误差是子组误差之和，故对每个 E6M2 候选也不劣。将 E6M2 候选集合扩大为 `S_old subset S_new` 后，`min_{s in S_new} L(s) <= min_{s in S_old} L(s)`。这是最直接、最可靠的第一步。

实现上，每个候选要计算四个倍率组合 `(a,b)=(0,0),(0,1),(1,0),(1,1)`。当前实现约三次量化；精确版约四次，额外开销约 33%，仍远低于一次端到端校准 MatMul。不要只把候选从 5 加到很大：先做精确微指数，随后将 E6M2 查表窗口扩为峰值附近的 `[-6,+6]` 个编码位置，并在校准集实测时间。

### 2. E6M2 候选的截断风险

第 213-218 行以 `amax/7` 为中心，第 75-98 行的 5 个候选基本只覆盖“略小于峰值尺度”及更大的尺度。普通 MSE 的最优 scale 可能主动裁剪少数离群点，位于 `amax/7` 更小的多个 E6M2 binade。HiF4 论文的 Algorithm 1 使用 `amax/7` 是硬件友好的参考转换，并不是“对任意数据 MSE 最优”的定理。

应使用 E6M2 表的编码索引做对称窗口搜索，例如 `idx + [-8,...,+8]`，并将其与旧 5 个索引取并集。候选集合嵌套即可继承上一节的逐块不劣性；代价与候选数线性相关。

### 3. Linear 校准数据没有被使用

`hif4_calibration_and_quantize_weight` 的 `calib_activation_list` 只出现在函数签名中（第 286-306 行），没有影响 `weight_params` 或 `activation_state`。这使离线权重、在线激活都在最小化各自的重建误差，而非题目要求的 `X @ W.T` 输出误差。

随机 Hadamard 本身不是必然错误：第 294-325 行对 Linear 的两个操作数使用同一个正交矩阵 `H`，因而在无量化时

```text
(X H)(W H)^T = X H H^T W^T = X W^T.
```

这里要求 `H H^T=I` 且两个操作数的输入通道分块完全对齐。它只是一种降低块内离群值的坐标变换，不能替代输出敏感度优化。

### 4. Attention 的 V 权重不是输出敏感度

当前 V state 保存的是逐隐藏通道二阶矩 `E[V_j^2]`（第 271-279、415-425 行）。固定 Q/K 时，令

```text
P = softmax(Q K^T / sqrt(d) + M),   O = P V,   E_V = V_hat - V.
```

则 V 引起的**精确**输出误差为

```text
||O_hat-O||_F^2 = ||P E_V||_F^2
                = tr(E_V^T P^T P E_V).
```

因此敏感度在 token/序列维度上，来自 `P^T P`，而不是 V 的数值方差。若不同 token 的量化误差近似零均值且不相关，则

```text
E ||P E_V||_F^2 = sum_t rho_t E ||E_V[t,:]||_2^2,
rho_t = sum_i P[i,t]^2.
```

GQA 中应对共享的 KV head 累加映射到该 head 的所有 Q head 的 `rho`。可以将校准得到的 `rho[:, None]` 扩展成与 V 相同形状，直接作为当前 `_quantize_hif4(..., importance=...)` 的逐元素权重；序列长度变化时使用每位置平均权重或回退普通 MSE。`M` 必须等于平台实际的 mask（可能是 causal，也可能没有 mask）；任务书只写 GQA，不能在本地 evaluator 中擅自固定为 causal。

### 5. Q/K 的 Hadamard 只在严格边界条件下等价

第 344、374、399 行把同一个 H 应用于 Q/K。对于同一个 attention head，若 H 只作用于该 head 内的 `d` 个维度，则

```text
(Q_h H)(K_h H)^T = Q_h K_h^T.
```

当前实现按 flattened hidden dimension 的连续 64 个元素变换。只有 `head_dim` 是 64 的倍数、64 块不会跨 head，且 GQA 映射的 Q/K head 使用相同 H 时才满足上式。否则会混合 head，改变原始 logits；应在校准中显式检查这些条件，不满足时禁用 Q/K rotation，或按 `[seq, heads, head_dim]` 逐 head 变换。

参考论文对 NVFP4 前向传播也没有把 RHT 当成通用必需项；它报告在其训练设定中 Fprop/Dgrad 的收益不明显。因此 rotation 应保留为校准集的 A/B 候选，而不是不可回退的前提。

### 6. 接口决定了 Linear 与 Attention 的可优化边界

Linear 的 dynamic activation 函数拿到当前 `X` 和 `activation_state`。state 可以合法保存 CPU `float32` 的 `W`、`W_hat` 或其 Gram 矩阵，因此它可以为当前在线 `X` 计算少量候选的真实

```text
||X_hat W_hat^T - X W^T||_F^2.
```

这使 Linear 可以做“当前样本上的端到端候选重排序”。完整地逐元素联合搜索仍可能超时，但在普通 MSE、对角加权、不同 SmoothQuant alpha 等 3-5 个候选中选择，完全符合接口。

Attention 不同：`hif4_dynamic_quantize_q/k/v` 被独立调用，每次只能看见当前自身张量和本角色 state，不能读取另外两个**在线**张量。因此任何“在线联合重算当次 `softmax(QK^T)V` 后选择 Q/K/V”的方案都不满足接口。正确做法是：在 `hif4_calibration_attention` 中用完整 calibration Q/K/V 联合选择静态 mode、变换和 importance；在线阶段仅作本角色动态 HiF4 搜索。这个限制也意味着 Attention 的端到端不劣保证只对 calibration 集成立。

## 输出敏感度目标与证明

### Linear: 权重和激活的正确二阶目标

令一组校准激活组成矩阵 `X`，`C_X=X^T X / n`，并固定某一侧。

对权重误差 `E_W=W_hat-W`：

```text
1/n ||X E_W^T||_F^2 = tr(E_W C_X E_W^T).
```

当 `C_X` 在当前（Hadamard 后）坐标近似对角，`C_X ~= diag(lambda)`，目标化为

```text
sum_{out,j} lambda_j (E_W[out,j])^2.
```

这正是 `_quantize_hif4` 可接受的逐元素 `importance=lambda`。在“对角协方差”假设下，使用 `lambda_j=mean(X[:,j]^2)` 选择 scale/E1 的解，是固定激活时 Linear 输出 MSE 的精确最小化，而不是启发式。

对激活误差 `E_X=X_hat-X`，固定已量化权重 `W_hat`：

```text
1/n ||E_X W_hat^T||_F^2
= tr(E_X (W_hat^T W_hat) E_X^T) / n.
```

所以动态激活的权重应为 `diag(W_hat^T W_hat)`（在旋转坐标中计算），由 weight calibration 写入 `activation_state`。这比当前的普通 MSE 直接对齐评分目标。

两边同时量化时，完整差为

```text
X_hat W_hat^T - X W^T
= E_X W^T + X E_W^T + E_X E_W^T.
```

前两个二阶目标是其一阶项的精确平方；最后一项是二阶小量。实际实现应做 1-2 轮交替优化：先用 `C_X` 量化 W，再由 `W_hat^T W_hat` 量化校准 X，最后以真实 `mean(||X_hat W_hat^T-XW^T||^2)` 选择少量候选。每轮把“旧配置”也作为候选，校准端到端目标必然不增。

### Linear: 漏掉的精确重参数化 - 平滑、旋转和置换

设 `T` 是可逆的、仅作用于 Linear 的输入通道，则定义

```text
X' = X T,                 W' = W T^(-T).
```

无量化时严格有 `X' W'^T = X W^T`。这统一解释了可在本题使用的三类变换：

| 变换 | T | 在线 X | 离线 W | 目的 |
| --- | --- | --- | --- | --- |
| SmoothQuant 式对角平衡 | `D^(-1)` | `X D^(-1)` | `W D` | 在两侧移动通道离群值 |
| 正交旋转 | `R`, `R R^T=I` | `X R` | `W R` | 将离群值分散进 64 值 HiF4 block |
| signed permutation | `P`, `P P^T=I` | `X P` | `W P` | 重新组合通道，降低 block 内动态范围 |

这比只应用固定 Hadamard 更强：先对校准统计量选 `D`，再选 block-wise `R/P`，最后量化。SmoothQuant 的实用初值可写为

```text
D_j(alpha) = max_abs(X[:,j])^alpha / max_abs(W[:,j])^(1-alpha),
alpha in {0, .25, .5, .75, 1}.
```

实际必须以 `eps` 截断分母、限制 `D_j` 的范围，并以完整 calibration Linear MSE 选 alpha，而不是照搬经验 alpha。这样消除了 NVFP4 16 值块升到 HiF4 64 值块时最危险的通道离群值。`D`、`R/P` 和必要的 `W/W_hat` 可作为 CPU tensor 放进 `activation_state`。

**证明与边界。** 上式给出变换前的严格零误差等价性；它并不保证量化后更好。将“无变换的旧方案”作为一个候选，并在同一 calibration 端到端损失上取最小值，才得到不劣保证。任意全矩阵 `R` 不适合直接搜索：state 虽能保存它，但在线 `O(C^2)` 变换会挤占 5 分钟预算。优先使用 64x64 block-diagonal Hadamard、signed permutation，或有限个 Givens rotation 的小候选族。

### Linear: 全协方差 GPTQ/OBQ 残差补偿

`diag(C_X)` 权重丢掉了不同输入通道间的相关性。校准 loss 的精确二次形式是

```text
L_W = tr((W_hat-W) C_X (W_hat-W)^T),
C_X = X^T X / n.
```

因此可对每个 64 通道 HiF4 block 使用 `C_b + lambda I` 的 Cholesky 分解，在固定一个离散量化决定后，按 GPTQ/OBQ 的条件最小化更新尚未量化的连续权重。直观地说，已产生的量化残差沿相关通道搬移，从而尽量保持 `XW^T`。这是将 GPTQ 的 Hessian 思路适配到 HiF4 离散 scale/S1P2 搜索的正确方式。

这里不能宣称 GPTQ 的逐坐标更新一定给出 HiF4 的全局离散最优：scale、E1_8、E1_16 会耦合 64 个值，且补偿后的临时权重不再是原值。可行实现是“每个 block 两轮交替”：固定 scales 搜索 S1P2，再更新未固定坐标；最后直接重算 `L_W`，连同旧量化结果一起候选选择。这样优化近似失败时不会让 calibration 结果退化。对角 `C_X` 近似应先实现；当它已经有效而 runtime 仍充足，再上 block-GPTQ。

### Attention: Q/K/V 一阶曲率

对每个 head，写 `S=QK^T/sqrt(d)+M`、`P=softmax_row(S)`、`O=PV`。第 `i` 行 softmax 的 Jacobian 是

```text
J_i = diag(p_i) - p_i p_i^T.
```

一阶展开为

```text
dO = P dV + dP V,
dP_i = J_i dS_i,
dS = (dQ K^T + Q dK^T) / sqrt(d).
```

令 `G_i = J_i V V^T J_i`。忽略 Q/K/V 误差的交叉三阶项后，Q 第 `i` 个 token 的曲率为

```text
H_Q[i] = K^T G_i K / d,
```

可用其对角 `diag(H_Q[i])` 作为 Q 每个维度的 importance。K 的完全二阶目标会耦合不同 key token；取 token/维度对角近似时，`K[t,r]` 的权重为

```text
w_K[t,r] = sum_i G_i[t,t] Q[i,r]^2 / d.
```

V 则使用上一节的 `rho_t`。对 Q/K/V 分别跨 5 个校准样本、以及 GQA 中共享同一 KV head 的对应 Q heads 做平均/累加，得到 `q_importance`、`k_importance`、`v_importance` 三个 CPU tensor state。其量化时必须以每个 head 为单位计算，再 reshape 回接口要求的 flattened 形状。

**理论含义。** 这些权重是 Attention 输出 MSE 的 Gauss-Newton / 一阶泰勒二阶形式的对角项；在局部量化误差足够小、忽略交叉项时，最小化加权重建 MSE 等价于最小化该近似输出 MSE。曲率权重本身不保证优于无权重的真实 MSE；将无权重配置一并纳入端到端校准候选并取最小值，才给出校准真实目标的不劣保证。隐藏集是否提升仍取决于校准分布代表性。

### Attention: 应采用联合重建，且可做 Q/K 的精确平衡

BoA（ICML 2025）将 GPTQ 的逐层 Hessian 扩展为 attention reconstruction Hessian，核心结论是 Q/K/V 的误差存在模块内耦合，单独量化每个投影不是充分目标。本赛题输入已经是 Q/K/V 张量，不能原样复用 BoA 的“投影权重 Hessian”；但它直接支持以下适配：在 calibration 阶段对一小组 HiF4 mode/变换组合，用真实

```text
mean ||Attention(Q_hat, K_hat, V_hat) - Attention(Q, K, V)||_F^2
```

联合排序，而不是将 Q/K/V 三个重建 MSE 相加。前一节的 Jacobian weights 适合作为产生候选的廉价 proxy，而不是最终裁判。

Q/K 还存在一个类似 SmoothQuant 的严格等价变换。对每个 KV head group 选正对角矩阵 `D_g`，并令其映射到的每个 Q head 使用

```text
Q'_h = Q_h D_g,          K'_g = K_g D_g^(-1).
```

则 `Q'_h K'_g^T = Q_h K_g^T`，故 logits、softmax 与无量化 Attention 输出完全不变。对正交 `R_g` 或 signed permutation `P_g`，Q/K 两侧可同时右乘同一变换。GQA 必须让共享同一 K head 的所有 Q heads 共用该变换；V 没有可配对的输出投影接口，不能做此类变换。优先在每个 head 内做 64 对齐的 block-diagonal 变换，避免跨 head。

把 `D_g` 的有限 alpha 候选、rotation on/off、普通/曲率加权、精确 E1 search 组成少量组合，在 calibration Attention MSE 上选最小者，且含旧方案，即得 calibration 不劣保证。在线阶段不可联合看见 Q/K/V，故只复用该静态选择与各自 state。

## 推荐实施顺序

1. **P0: 本地 evaluator 与格式回归。** 先确认 platform Attention 的 mask、GQA head repeat、softmax dtype 与缩放语义；任务书没有明确 causal。没有这个基准，不应调任何 Attention 超参。
2. **P1: 纯量化内核。** 新写 `_quantize_block_exact`：四种 `(E1_8,E1_16)` 组合的联合搜索；E6M2 候选索引窗口取“旧集合并对称窗口”。先验证新旧重建 MSE 逐块 `new <= old`。
3. **P2: Linear 对角平衡 + 输出加权。** 在 calibration 上扫描少量 SmoothQuant alpha、rotation/permutation on/off；保存 `x2_mean` 用于 W，保存 `diag(W_hat.T @ W_hat)`、变换和必要的 `W/W_hat` 用于在线 A。每个 state Tensor 必须是 CPU/float32/有限值，符合 `self_check.py`。
4. **P3: Linear 端到端候选选择。** 由于在线 activation 可见固定 W，针对每个测试 activation 在 3-5 个候选中以真实 `X_hat @ W_hat.T` MSE 选优；先测总耗时。若时间不足，退化为 `diag(W_hat.T @ W_hat)` 加权，不要加入全量在线坐标搜索。
5. **P4: Linear block-GPTQ。** 只在 P2/P3 已经稳定后，按 64 通道 block 做阻尼 Cholesky 和一至两轮补偿；最终仍以直接 calibration 输出 MSE 决定是否启用。
6. **P5: Attention 联合校准。** 对普通 MSE、V 的 `P^T P` 对角、Q/K Jacobian、Q/K 平衡和 per-head rotation 的少量组合，以真实 calibration Attention MSE 选一个静态 mode；回归 GQA 映射、mask 与缩放。

## 验收标准与防退化策略

* 每次提交前运行 `example/self_check.py`；它验证格式，不验证数值质量。
* 写本地 evaluator，计算同一输入的 NVFP4 reference、HiF4 dequant、Linear/GQA Attention 输出以及每个用例 MSE。mask、GQA head 映射、softmax 精度必须以平台脚本为准，不能默认 causal。
* 对每一组 calibration 记录四个数：W 重建 MSE、A 重建 MSE、Linear 输出 MSE、Attention 输出 MSE。只看前两个会误导搜索方向。
* 候选选择必须包含当前的普通 MSE配置；这样对校准集的最终 MSE 有机械性的 `min(new candidates) <= old candidate` 保证。测试集的改善应以 50 组的分位数和负分 case 数量衡量，不能只看均值。
* 把时间预算留给最有价值的部分：精确 E1 搜索、Linear 平衡和输出加权通常优先于大规模 Attention Hessian。若扩展 E6M2 令耗时超限，减少候选数前先保留“旧候选 + 低尺度侧的额外候选”。

## 参考依据

* [HiFloat4 Format for Language Model Inference](C:/Users/23363/Desktop/ALG/pdf/HiFloat4%20Format%20for%20Language%20Model%20Inference.pdf): HiF4 的 64 值单元、E6M2/E1_8/E1_16 层级、`amax/7` 参考转换和 S1P2 表示。
* [Pretraining Large Language Models with NVFP4](C:/Users/23363/Desktop/ALG/pdf/Pretraining%20Large%20Language%20Models%20with%20NVFP4.pdf): NVFP4 的 16 值块尺度背景，以及 RHT 只在满足算子变换关系时使用的工程限制。
* [SmoothQuant](https://arxiv.org/abs/2211.10438): 以严格等价的通道缩放在 activation/weight 之间迁移量化难度；本赛题可以直接适配为 `X D^-1, W D`。
* [QuaRot](https://arxiv.org/abs/2404.00456), [SpinQuant](https://arxiv.org/abs/2405.16406), [DuQuant](https://arxiv.org/abs/2406.01721): 旋转、学习旋转和 permutation 用于 outlier 管理。它们支持把当前固定 Hadamard 变成有限候选的变换搜索，但不免除本题中 operand 配对、head 对齐和运行时间约束。
* [GPTQ](https://arxiv.org/abs/2210.17323): 用二阶信息在离散量化决定后补偿剩余权重，启发本文件的 Linear block-GPTQ。
* [BoA: Attention-aware Post-training Quantization without Backpropagation](https://arxiv.org/abs/2406.13474)（ICML 2025）: 提出 attention-aware Hessian，论证 Q/K/V 的耦合与“用真实 attention reconstruction 选校准候选”的必要性；赛题给的是 Q/K/V 张量，故这里采用其目标而非直接复刻投影权重量化算法。
* [FP4 All the Way: Fully Quantized Training of LLMs](https://arxiv.org/abs/2505.19115): 2025 年 FP4 训练研究，进一步说明 block size 与 scale format 是精度关键变量；它是训练工作，不可直接当作本赛题转换算法的证据。
