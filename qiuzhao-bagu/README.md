# 秋招八股 + 实操项目

> 根据 `/root/A_zxy/qiuzhao.md` 四阶段大纲整理
> AI Infra 方向（昇腾 NPU / vLLM 推理部署 / 大模型工程）

## 目录结构

```
qiuzhao-bagu/                          # 八股速记（背诵用）
├── phase1-fundamentals/               # 第一阶段：工程基础
│   ├── 01-linux-shell.md              # Linux 开发与 Shell
│   ├── 02-docker.md                   # Docker 容器化
│   ├── 03-k8s-pod.md                  # k8s 与 Pod 开发
│   ├── 04-git-workflow.md             # Git 工作流
│   ├── 05-llm-basics.md               # LLM 基础（Transformer/GPT/训练范式/Tokenizer/Prefill-Decode）
│   ├── 06-ai-tasks-models.md          # 场景 AI 任务与模型（NLP/CV/多模态）
│   ├── 07-ascend-npu.md               # 昇腾 NPU 架构 + vllm_ascend
│   └── 08-claude-vibe-coding.md       # Claude Code 的 Vibe Coding
│
├── phase2-inference-deploy/           # 第二阶段：推理部署
│   ├── 01-vllm-deep-dive.md           # vLLM 深度解析（PagedAttention/Continuous Batching/V1）
│   └── 02-quantization.md             # 模型压缩与量化（PTQ/FP8/微缩放）
│
├── phase3-framework-integration/      # 第三阶段：推理框架集成与模型加载
│   └── 01-model-loading-integration.md # HF 集成/权重加载/TP/PP/分布式
│
└── phase4-performance-tuning/         # 第四阶段：推理性能调优
    └── 01-performance-concepts.md     # 性能概念（TTFT/TPOT/屋顶线/MFU/调优手段）

qiuzhao-projects/                      # 实操项目（可运行代码）
├── 01-vllm-ascend-deploy/             # 实操1：搭建开发环境，运行 vllm_ascend 容器
│   ├── Dockerfile                     # 自定义镜像
│   ├── docker-compose.yml             # 一键启动
│   ├── scripts/                       # 启动/停止/健康检查脚本
│   ├── client/                        # OpenAI 兼容客户端 + 压测
│   ├── configs/                       # 推理参数配置
│   └── docs/                         # 环境变量速查 + 排障指南
│
├── 04-pytorch-transformer-from-scratch/ # 实操4：从零实现 Transformer
│   ├── model.py                       # 完整模型（attention/PE/encoder/decoder）
│   ├── tokenizer.py                  # 简单字符级 tokenizer
│   ├── dataset.py                    # 翻译数据集
│   ├── train.py                      # 训练入口
│   ├── generate.py                   # 推理/翻译生成
│   └── tests/                        # 单元测试
│
└── phase4/
    ├── multicard-llm-service/        # 实操P4.1：多卡 LLM 推理服务
    │   ├── deploy/                   # TP/PP 部署脚本
    │   ├── server/                   # 服务启动入口
    │   ├── client/                   # 异步并发客户端 + 压测
    │   └── docs/                     # 调优指南
    │
    └── batching-strategy-benchmark/  # 实操P4.2：Batching 策略对比
        ├── configs/                  # 多种策略配置
        ├── benchmark_strategies.py  # 对比脚本
        ├── analyze_results.py        # 生成调优报告
        └── report_template.md        # 报告模板
```

## 使用方式

### 八股背诵
每篇文件结构：**Q&A 形式 + 加粗结论 + 一页速记卡**。面试前 30 分钟扫一遍速记卡即可。

### 实操项目
每个项目都有独立的 README，按步骤运行即可。

## 实操对照表

| qiuzhao.md 中的实操 | 对应项目 |
|---|---|
| 实操1：搭建开发环境，运行 vllm_ascend 容器，部署大模型 | `01-vllm-ascend-deploy/` |
| 实操2：修改一个问题单 DTS，学习解决问题单流程 | （参考 git-workflow 八股 + 项目实操） |
| 实操3：需求 review，学习需求交付流程 | （参考 git-workflow + k8s 八股） |
| 实操4：用 PyTorch NPU/GPU 从零实现小型 Transformer 模块 | `04-pytorch-transformer-from-scratch/` |
| P4 实操1：部署多卡 LLM 推理服务，支持并发请求，压测优化 | `phase4/multicard-llm-service/` |
| P4 实操2：对比不同 Batching 策略下的吞吐量，输出调优报告 | `phase4/batching-strategy-benchmark/` |

## 关键纠错（面试常见误解）

1. **`HCCL_TIMEOUT` 不存在**：CANN 中正确变量是 `HCCL_EXEC_TIMEOUT`（默认 1836 秒）。
2. **vLLM 没有 `--quantization deepseek_fp8`**：DeepSeek-V3/R1 FP8 权重走 `--quantization fp8`（靠 checkpoint 的 `weight_block_size` 触发 block 量化路径）。vLLM 有 `deepseek_v4_fp8` 方法，但那是 V4 模型专用。
3. **`torchatb` 不是独立包**：`atb` = Ascend Tensor Boost，由 NNAL 提供 `libatb.so`，属于 CANN 一部分，Python 走 `torch_npu.atb.*` 命名空间。
4. **vLLM spec decode 没有 "lookahead" 方法**：早期有 Lookahead Decoding，现已更名为 **"N-Gram"**。
5. **vLLM V0 调度器三队列（waiting/running/swapped）已被移除**：当前 main 分支用 V1 scheduler，队列结构简化为 `waiting` + `running` + `skipped_waiting`。V1 也移除了 GPU↔CPU KV swap。
6. **vLLM 默认 block size = 16**（CPU 后端 = 128），**昇腾推荐用 128**（因 Cube Unit 大）。
7. **vLLM 平台类名是 `NPUPlatform`**（不是 `AscendPlatform`），`_enum = PlatformEnum.OOT`（out-of-tree 平台）。

## 文件统计

- 八股文件：12 篇（每篇 40-60 个 Q&A + 速记卡）
- 实操项目：4 个（含 30+ 个源文件）
- 代码语言：Python / Bash / YAML / Dockerfile
- 总计：约 50 个文件

## 更新日志

- 2026-08-21：初版完成，覆盖 qiuzhao.md 全部四阶段内容
