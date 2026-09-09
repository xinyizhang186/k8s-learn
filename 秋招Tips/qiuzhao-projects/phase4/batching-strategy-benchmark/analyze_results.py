"""
analyze_results.py — 分析 benchmark 结果，输出 markdown 调优报告

用法：
    python analyze_results.py --input reports/results.json --output reports/tuning_report.md
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def percentile(sorted_list: list[float], p: float) -> float:
    """计算分位数。"""
    if not sorted_list:
        return 0.0
    n = len(sorted_list)
    idx = min(int(n * p), n - 1)
    return sorted_list[idx]


def generate_report(results: list[dict], output_path: str) -> str:
    """生成 markdown 报告。"""
    lines = []
    lines.append("# vLLM Batching 策略调优报告\n")
    lines.append(f"生成时间：{__import__('datetime').datetime.now().isoformat()}\n")

    # 1. 实验环境
    lines.append("## 1. 实验环境\n")
    if results:
        first = results[0]
        lines.append(f"- 测试请求总数：{first['test_config'].get('num_requests', 'N/A')}")
        lines.append(f"- 并发数变化：{', '.join(str(r['test_config'].get('concurrent', '?')) for r in results)}")
        lines.append(f"- 每请求 max_tokens：{first['test_config'].get('max_tokens', 'N/A')}")
        lines.append(f"- prompt 分布：{first['test_config'].get('prompt_dist', 'mixed')}")
    lines.append("")

    # 2. 策略对比表
    lines.append("## 2. 策略对比\n")
    lines.append("| 策略 | 描述 | max_num_seqs | max_num_batched_tokens | chunked_prefill | 并发 | 吞吐(tok/s) | P50延迟 | P95延迟 | P99延迟 | 成功率 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for r in results:
        name = r["strategy_name"]
        desc = r["description"]
        va = r["vllm_args"]
        tc = r["test_config"]
        lats = sorted(r["latencies"]) if r["latencies"] else [0]
        total_time = r["total_time"] or 1
        throughput = sum(r["completion_tokens"]) / total_time if r["completion_tokens"] else 0
        p50 = percentile(lats, 0.5)
        p95 = percentile(lats, 0.95)
        p99 = percentile(lats, 0.99)
        success_rate = r["successful"] / max(r["total_requests"], 1) * 100

        lines.append(
            f"| {name} | {desc} | {va.get('max_num_seqs', '-')} | "
            f"{va.get('max_num_batched_tokens', '-')} | "
            f"{va.get('enable_chunked_prefill', '-')} | "
            f"{tc.get('concurrent', '-')} | "
            f"{throughput:.1f} | {p50:.3f}s | {p95:.3f}s | {p99:.3f}s | {success_rate:.1f}% |"
        )
    lines.append("")

    # 3. 详细分析
    lines.append("## 3. 详细分析\n")
    for r in results:
        name = r["strategy_name"]
        lats = r["latencies"]
        tokens = r["completion_tokens"]
        total_time = r["total_time"]

        lines.append(f"### {name}\n")
        lines.append(f"- 描述：{r['description']}")
        lines.append(f"- vLLM 参数：{json.dumps(r['vllm_args'], ensure_ascii=False)}")
        lines.append(f"- 总请求数：{r['total_requests']}")
        lines.append(f"- 成功：{r['successful']}，失败：{r['failed']}")
        if lats:
            lines.append(f"- 延迟均值：{statistics.mean(lats):.3f}s")
            lines.append(f"- 延迟中位数：{statistics.median(lats):.3f}s")
            lines.append(f"- 延迟标准差：{statistics.stdev(lats):.3f}s" if len(lats) > 1 else "- 延迟标准差：N/A")
            lines.append(f"- 延迟 P90：{percentile(sorted(lats), 0.9):.3f}s")
            lines.append(f"- 延迟 P95：{percentile(sorted(lats), 0.95):.3f}s")
            lines.append(f"- 延迟 P99：{percentile(sorted(lats), 0.99):.3f}s")
        if tokens:
            lines.append(f"- 总输出 token：{sum(tokens)}")
            lines.append(f"- 吞吐：{sum(tokens) / total_time:.1f} tok/s")
            lines.append(f"- QPS：{r['successful'] / total_time:.1f} req/s")
        lines.append("")

    # 4. 结论
    lines.append("## 4. 结论与建议\n")
    if results:
        # 找吞吐最高、延迟最低的策略
        best_throughput = max(results, key=lambda r: sum(r["completion_tokens"]) / (r["total_time"] or 1))
        best_latency = min(
            [r for r in results if r["latencies"]],
            key=lambda r: statistics.mean(r["latencies"]),
            default=None,
        )

        lines.append(f"- **吞吐最高**：`{best_throughput['strategy_name']}`")
        if best_latency:
            lines.append(f"- **延迟最低**：`{best_latency['strategy_name']}`")
        lines.append("")
        lines.append("### 选型建议\n")
        lines.append("- **高吞吐场景**（批量处理、离线推理）：选吞吐最高的策略，容忍较高延迟。")
        lines.append("- **低延迟场景**（实时对话、代码补全）：选延迟最低的策略，吞吐次之。")
        lines.append("- **综合场景**：通常基线配置（max_num_seqs=128, max_num_batched_tokens=2048）"
                     "在吞吐与延迟间取得平衡，是默认推荐。")
        lines.append("- **chunked prefill**：对混合 prompt 长度的场景，强烈推荐开启，"
                     "可显著降低 TTFT 抖动（ITL）。")
        lines.append("- **大 batch**：提升吞吐但增加显存压力，需监控 OOM；"
                     "并发请求数受 `max_num_seqs` 上限约束。")

    # 5. 调优旋钮速查
    lines.append("\n## 5. 调优旋钮速查\n")
    lines.append("| 参数 | 作用 | 调优方向 |")
    lines.append("|---|---|---|")
    lines.append("| `--max-num-seqs` | 最大并发请求数 | ↑ 吞吐↑ 但延迟↑、显存↑ |")
    lines.append("| `--max-num-batched-tokens` | 每 step token 预算 | ↑ 吞吐↑ 但 ITL 抖动↑ |")
    lines.append("| `--enable-chunked-prefill` | 分块 prefill | 默认开（V1），降 TTFT 抖动 |")
    lines.append("| `--enable-prefix-caching` | 前缀缓存 | V1 默认开，重复 prompt 命中加速 |")
    lines.append("| `--block-size` | PagedAttention 块大小 | GPU=16, NPU 推荐 128 |")
    lines.append("| `--gpu-memory-utilization` | 显存使用率 | 0.85-0.95，留 buffer |")
    lines.append("| `--tensor-parallel-size` | TP 数 | 单机 8 卡可设 8 |")
    lines.append("| `--quantization` | 权重量化 | fp8/ascend 提速省显存 |")
    lines.append("| `--kv-cache-dtype` | KV cache 量化 | fp8 减半 KV 显存 |")
    lines.append("| `--speculative-config` | 投机解码 | eagle/mtp 适合代码等高 accept rate 任务 |")

    report = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)
    print(f"Report saved to {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument("--input", required=True, help="JSON results file")
    parser.add_argument("--output", default="reports/tuning_report.md", help="Output markdown report")
    args = parser.parse_args()

    with open(args.input) as f:
        results = json.load(f)

    generate_report(results, args.output)


if __name__ == "__main__":
    main()
