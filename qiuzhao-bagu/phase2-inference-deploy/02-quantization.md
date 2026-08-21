# 模型压缩与量化 - 八股速记

> 适用范围：秋招 AI Infra 岗位（推理部署方向）
> 当前年份：2026，核对日期：2026-08-21
> 事实均附一手来源链接；不能验证的标注「未验证」
> **关键纠错**：vLLM **没有** `--quantization deepseek_fp8` 方法，DeepSeek-V3/R1 FP8 权重走 `--quantization fp8`

---

## 一、量化原理

### Q1. 量化（Quantization）是什么？
- 把高精度浮点（FP32/FP16/BF16）权重/激活映射到低精度整数（INT8/INT4）或低精度浮点（FP8/FP4）。
- 目的：**减内存 + 加速 + 省能耗**。
- 内存：INT8 比 FP16 减半，INT4 减 4 倍。
- 加速：低精度 Tensor Core 吞吐高 2-4×；weight-only 量化靠减少 weight 读取量加速 decode（memory-bound）。

### Q2. 对称 vs 非对称量化？
- **对称**：量化范围关于 0 对称，`x_q = clip(round(x / scale), -127, 127)`，**无 zero-point**。
  - 适合权重（对称分布）、FP8（天然对称）。
- **非对称**：量化范围可偏移，`x_q = clip(round(x / scale) + zero_point, 0, 255)`，**有 zero_point**。
  - 适合激活（ReLU 后非负、长尾分布）。
- INT8 可选对称/非对称；FP8 只能对称（浮点天然关于 0 对称）。

### Q3. Per-Tensor / Per-Channel / Per-Token / Per-Block 粒度？
| 粒度 | scale 数 | 优势 | 劣势 |
|---|---|---|---|
| Per-Tensor | 1 | 最省内存 | 离群点撑大全局 scale，精度损失大 |
| Per-Channel | N（每通道） | 精度好 | 内存/算力略增 |
| Per-Token | T（每 token，仅激活） | 精度更好 | 动态计算开销 |
| Per-Block | B（每 block） | 离群点隔离 | scale 多、kernel 复杂 |

### Q4. 量化误差来源？
- **截断误差**：超出 [min, max] 的值被 clip。
- **舍入误差**：浮点 → 整数 round。
- **粒度误差**：单一 scale 难覆盖所有值的分布。
- **激活函数后分布变化**：ReLU 后非负、长尾，与权重分布差异大。

---

## 二、量化分类

### Q5. PTQ（Post-Training Quantization）vs QAT（Quantization-Aware Training）？
| 维度 | PTQ | QAT |
|---|---|---|
| 时机 | 训练后 | 训练中 |
| 数据 | 少量校准数据（100-1000 样本） | 完整训练集 |
| 成本 | 低（小时级） | 高（需要重训） |
| 精度 | 一般，INT8 接近全精度；INT4 损失大 | 高，INT4 也能保精度 |
| 工具 | GPTQ / AWQ / SmoothQuant / ModelSlim | PyTorch QAT / TensorRT QAT |
| 适用 | 推理部署（主流） | 极致精度场景 |

### Q6. Weight-only vs Weight+Activation 量化？
| 维度 | Weight-only (Wa16) | Weight+Activation (Wa8) |
|---|---|---|
| 权重 | a-bit | a-bit |
| 激活 | 16-bit | b-bit |
| 硬件 | 任意（权重离线量化，反量化后跑标准 GEMM） | 需低精度 Tensor Core |
| 省内存 | 权重减半/4倍 | 同等 |
| 省算力 | 不省（反量化后还是 16-bit GEMM） | 省 2-4× 吞吐 |
| 省带宽 | **省**（weight memory-bound 时关键） | 省 |
| 代表 | GPTQ/AWQ（W4A16） | FP8 W8A8、SmoothQuant W8A8 |

### Q7. 主流 PTQ 方法对比？
| 方法 | 类型 | 核心思想 | 精度 |
|---|---|---|---|
| **GPTQ** | W4A16 | 基于 Hessian 信息逐列量化权重，用少量校准数据 | INT4 接近全精度 |
| **AWQ** | W4A16 | 保护"重要"权重（按激活 magnitude 选），per-channel scale | INT4 略优于 GPTQ |
| **SmoothQuant** | W8A8 | 把激活的难度"smooth"到权重（scale 折叠进权重） | INT8 接近全精度 |
| **SpQR** | W4A16 + 稀疏 | 检测离群权重单独高精度存 | 接近 GPTQ |
| **ModelSlim** | W8A8 | 华为昇腾量化工具 | 适配 Ascend NPU |
| **llm-compressor** | 多种 | vLLM 集成，支持 W8A8/W4A16/FP8 | - |

### Q8. GPTQ 算法步骤？
1. 取少量校准数据（128 样本），跑前向得到每层 activations。
2. 计算 Hessian 矩阵 H = X^T X（X 是该层输入）。
3. 逐列量化权重：对每列 W[:, j]，量化后用剩余列补偿误差（基于 H 的 Cholesky 分解）。
4. 重复直到所有列量化完毕。
- 优势：利用 Hessian 二阶信息，精度好；劣势：逐列串行，量化慢。

### Q9. AWQ 算法步骤？
1. 不依赖梯度或 Hessian，**只用激活的统计信息**。
2. 找"重要"权重（per-channel，按激活 magnitude 排序）。
3. 给重要通道一个 scale（per-channel），把重要权重大幅放大后再量化（精度损失小），反量化时再除掉 scale。
4. **scale 是搜索出来的**（网格 + 优化），不是简单统计。
- 优势：快、稳、泛化好；劣势：仅 weight-only。

### Q10. SmoothQuant 核心思路？
- 激活有离群点（少数值很大），权重分布均匀。
- 把激活的"难度"转移到权重：`x' = x / s`，`W' = W * s`（per-channel s）。
- 量化后 `x_q * W_q ≈ x' * W' = x * W`，但 x' 无离群点更好量化。
- W' 分布变长尾但仍能 INT8 量化（权重天然容差大）。
- 结果：W8A8 INT8，精度接近全精度。

---

## 三、FP8 量化与微缩放

### Q1. FP8 格式：E4M3 vs E5M2？
- **E4M3**：1 符号 + 4 指数 + 3 尾数，bias=7；最大值 **±448**，精度高、范围小。
- **E5M2**：1 符号 + 5 指数 + 2 尾数，bias=15；最大值 **±57,344**，精度低、范围大。
- 用途分工：**前向（权重/激活）用 E4M3**（要精度），**反向（梯度）用 E5M2**（要动态范围）。
- 来源：[NVIDIA TE fp8_primer](https://nvidia.github.io/TransformerEngine/examples/fp8_primer.html)

### Q2. 哪些硬件原生支持 FP8？
- **NVIDIA H100/H200（Hopper）**：第 4 代 Tensor Cores 原生支持，峰值 2000 TFLOPS（稀疏 4000）。
- **NVIDIA GB200（Blackwell）**：在 Hopper FP8 基础上新增 **MXFP8 + NVFP4**。
- **AMD MI300（MI300X/A）**：Matrix Cores 原生支持 float8(E4M3) 和 float8(E5M2)。注意 AMD 的 E5M2 部分文档称作 `bfloat8`。
- **Intel Gaudi 2/3**：MME 支持 FP8 E4M3+E5M2；Gaudi 2 的 E4M3 最大值仅 ±240；**Gaudi 3 扩展到 ±448**（对齐 OCP）。Gaudi **不支持 MX**。

### Q3. FP8 vs INT8 对比？
| 维度 | FP8 | INT8 |
|---|---|---|
| 动态范围 | ±57,344 (E5M2) | ±127 |
| 对称性 | 天然对称（无 zero-point） | 可对称/非对称 |
| 校准 | 动态 per-token 无需校准 | 通常需 SmoothQuant/GPTQ 校准 |
| 精度 | W8A8 ≈0% 损失（lossless） | W8A8 1-3% 下降 |
| 吞吐（老硬件） | 需 Hopper+ | Volta 起成熟 |
| 离群点处理 | 浮点天然容差 | 需 SmoothQuant 等 |

### Q4. 微缩放（Microscaling, MX）格式？
- **OCP MX Spec v1.0**（2023-09，AMD/Arm/Intel/Meta/Microsoft/NVIDIA/Qualcomm 联合发布）。
- 块结构：**1 个共享 scale + 32 个同格式元素**。
- scale 用 **E8M0**（8 位纯指数，无符号/尾数，表示 2 的幂）。
- 四种格式：**MXFP8 / MXFP6 / MXFP4 / MXINT8**。
- 来源：[OCP MX Spec](https://www.opencompute.org/documents/ocp-microscaling-formats-mx-v1-0-spec-final-pdf)

### Q5. MX vs Per-Tensor FP8 区别（关键）？
- per-tensor FP8：每 tensor 一个 FP32 scale，要求全 tensor "挤" 进 FP8 动态范围 → 梯度等大范围 tensor 不得不降级用 E5M2。
- **MXFP8**：每 32 元素一个 E8M0 scale，局部自适应 → **所有 tensor 都能用 E4M3**（精度更高）。
- 离群点只影响它所在那 32 元素块的 scale，不影响其他块 → 局部动态范围被充分利用。

### Q6. NVFP4 vs MXFP4 区别？
- **MXFP4**：E8M0 scale（纯 2 的幂），块 32。
- **NVFP4**：E4M3 scale（有尾数），块 16，外加一个 per-tensor FP32 scale 补偿 E4M3 表达范围不足。
- NVFP4 精度通常优于 MXFP4。

### Q7. NVIDIA Transformer Engine（TE）三种 recipe？
1. **DelayedScaling**：per-tensor，用历史 amax（`amax_history_len` 默认 1024）。
2. **Float8CurrentScaling**：per-tensor，当前 amax（更自适应但每次需两次 tensor 读）。
3. **MXFP8BlockScaling**：Blackwell 块级（32 元素 + E8M0）。
- 来源：[TE Common API](https://docs.nvidia.com/deeplearning/transformer-engine/user-guide/api/common.html)

### Q8. amax → scale 公式？
- `new_scaling_factor = (FP8_MAX / amax) / (2^margin)`
- FP8_MAX：E4M3=448、E5M2=57344。

### Q9. DeepSeek-V3/R1 FP8 训练方案（重点考点）？
- DeepSeek-V3 首次在 671B MoE 上验证 FP8 训练，相对 BF16 loss 误差 **< 0.25%**。
- **三个关键创新**：
  1. **细粒度量化**：激活按 **1×128 tile**、权重按 **128×128 block**（比 per-tensor 细）。
  2. **在线量化**（Online Quantization）：不用历史 amax（区别于 TE Delayed Scaling），每步在线为每个 tile/block 算 amax → 导 scale。
  3. **FP32 精确累加**：在 GEMM 内层引入 per-block scale 后，部分和拷到 CUDA cores 乘 scale 再 FP32 累加。
- MoE 激活以 FP8 缓存与 dispatch；optimizer state 存 BF16。
- 来源：[DeepSeek-V3 技报 §3.3](https://arxiv.org/abs/2412.19437)

### Q10. DeepSeek 对未来硬件的建议？
- 当前 GPU 只支持 per-tensor 量化、缺原生细粒度（tile/block）支持。
- 呼吁未来芯片支持：**MMA with group scaling**、FP8 cast 与 TMA 融合、转置 GEMM。
- 这正是 Blackwell MXFP8 部分回应的方向。

---

## 四、量化精度评估

### Q1. 常用评估指标？
- **PPL（Perplexity）**：WikiText-2，语言建模质量。
- **MMLU / MMLU-Pro**：知识。
- **GSM8K**：数学推理。
- **HumanEval / MBPP**：代码生成。
- **IFEval**：指令遵循。
- **TruthfulQA**：事实性。

### Q2. 各精度预期降幅速记？
| 精度 | 平均降幅 | 备注 |
|---|---|---|
| FP8 (W8A8-FP) | ~0% | ACL 论文称 "essentially lossless"，99.75% 恢复 |
| INT8 (W8A8-INT，调优后) | 1-3% | 早期文献报 10%+ 是校准没调好 |
| INT4 (W4A16-INT, GPTQ+MSE) | 1-3% 平均 | 代码任务（HumanEval）降幅更大 |
| INT4 (W4A16, 小模型 1-3B) | 5-25% | 小模型对量化最敏感 |

### Q3. 任务敏感性排序？
- 代码生成（HumanEval）> 多步数学（GSM8K）> 指令遵循（IFEval）> 知识（MMLU）> 常识（HellaSwag）。
- **小模型 + 4-bit** 是重灾区，可能掉 20%+。

### Q4. PPL 与下游任务不一致？
- PPL 低 ≠ 下游好。
- 多个 5-bit 方案 PPL 几乎相同但 GSM8K/IFEval 差异大。
- 评估量化必须跑下游 benchmark，不能只看 PPL。

### Q5. 量化精度评估工具？
- **llm-eval-harness**（EleutherAI）：综合 benchmark。
- **lm-evaluation-harness**：HuggingFace 版。
- **MMLU/MMLU-Pro**：多选题知识。
- **HumanEval/MBPP**：代码功能正确性。
- **vLLM 量化示例脚本**：`examples/quantization_zeroed.py`。

---

## 五、vLLM FP8 支持（含关键纠错）

### Q1. 主方法名？
- `--quantization fp8`（`Fp8Config`，`get_name()` 返回 `"fp8"`）。
- **vLLM 不存在 `--quantization deepseek_fp8` 方法**。
- 来源：[vLLM fp8.py + __init__.py](https://github.com/vllm-project/vllm/blob/0a21947d710f5aedb1865038ebef20e141b29c58/vllm/model_executor/layers/quantization/__init__.py)

### Q2. DeepSeek-V3/R1 FP8 权重加载？
- checkpoint 的 `quantization_config` 里 `quant_method: "fp8"` + `weight_block_size: [128, 128]`。
- vLLM 的 `Fp8Config` 检测到 `weight_block_size` 即走 **block 量化路径**。
- 命令仍是 `--quantization fp8`。
- 来源：[DeepSeek-V3 权重文档](https://github.com/deepseek-ai/deepseek-v3/blob/main/README_WEIGHTS.md)

### Q3. DeepSeek-V4？
- vLLM 有独立的 `"deepseek_v4_fp8"` 方法（`DeepseekV4FP8Config`），用于更新的 V4 模型。
- **不是** V3/R1。

### Q4. 在线动态量化 shorthand？
- `fp8_per_tensor`、`fp8_per_block`、`fp8_per_channel`、`mxfp8`、`nvfp4_per_token`。
- 无需校准数据，运行时量化。

### Q5. 内核后端？
- `CutlassFP8ScaledMMLinearKernel`：Hopper/Ada W8A8，走 `torch._scaled_mm`。
- `MarlinFP8ScaledMMLinearKernel`：**无 FP8 硬件的 GPU 上做 weight-only W8A16**。
- `FlashInferFP8`、`Humming`、PyTorch 原生。

### Q6. MoE FP8？
- `Fp8MoEMethod` 支持 per-tensor 与 block(128×128) 两种。
- block 量化走 `use_deepseek_fp8_block_scale` 路径（**内核内部布尔标志**，非 CLI 量化方法名）。
- 后端可选 FlashInfer/CUTLASS/Triton/DeepGEMM。

### Q7. FP8 KV cache？
- `--kv-cache-dtype fp8`，减半 KV cache 显存。

### Q8. 仅用 float8_e4m3fn？
- vLLM FP8 线性层只支持 E4M3（受 `torch._scaled_mm` 限制）。
- E5M2 主要用于训练反向，推理少见。

### Q9. AMD MI300 适配？
- vLLM 检测到 MI300 的 FNUZ 格式会调用 `normalize_e4m3fn_to_e4m3fnuz` 转换。

### Q10. Marlin FP8 用途（易错）？
- Marlin FP8 内核是给**没有 FP8 Tensor Core 的旧卡**（Turing/Ampere）做 **weight-only W8A16** 用的。
- 权重存 FP8 省显存、推理时反量化成 BF16 算。
- **不是** W8A8。

### Q11. vLLM 硬件门槛？
- SM ≥ 8.9（Ada/Hopper）→ 可 W8A8(FP8 Cutlass) 或 W8A8(INT8)。
- SM 7.5–8.6（Turing/Ampere）→ FP8 自动降级为 **W8A16（Marlin）**，INT4 走 `gptq_marlin`。

---

## 六、一页速记卡

| 类别 | 必背 |
|---|---|
| 量化目的 | 减内存 + 加速 + 省能耗 |
| 对称 vs 非对称 | 对称无 zero-point（FP8/权重）；非对称有 zero-point（INT8 激活） |
| 粒度 | Per-Tensor / Per-Channel / Per-Token / Per-Block（越细精度越好但开销大） |
| PTQ vs QAT | PTQ 训练后 + 校准数据；QAT 训练中 + 完整训练集 |
| Weight-only vs W+a | Wa16 任意硬件、只省内存；Wa8 需低精度 TC、省算力+省内存+省 KV cache |
| GPTQ | W4A16，Hessian 信息逐列量化 |
| AWQ | W4A16，per-channel scale 保护重要权重 |
| SmoothQuant | W8A8，把激活难度转移到权重 |
| FP8 格式 | E4M3（±448，前向）/ E5M2（±57344，反向） |
| FP8 硬件 | Hopper (2000T)、Blackwell (+MXFP8/NVFP4)、MI300、Gaudi 2/3 |
| MX | OCP v1.0；32 元素 + E8M0 scale；MXFP8/6/4/INT8 |
| TE recipe | DelayedScaling（历史 amax）/ CurrentScaling（即时）/ MXFP8BlockScaling |
| DeepSeek FP8 | 1×128 激活 tile + 128×128 权重 block + 在线量化 + FP32 累加 |
| 精度速记 | FP8 ~0% / INT8 1-3% / INT4 1-3%（代码任务降幅大） |
| vLLM FP8 | `--quantization fp8`（**无 deepseek_fp8 方法！**）；V4 用 deepseek_v4_fp8 |
| vLLM 内核 | Cutlass W8A8（Ada/Hopper）/ Marlin W8A16（Turing/Ampere weight-only） |
| KV cache | `--kv-cache-dtype fp8` 减半显存 |
| 硬件门槛 | SM≥8.9 W8A8；SM 7.5-8.6 降级 W8A16 |
