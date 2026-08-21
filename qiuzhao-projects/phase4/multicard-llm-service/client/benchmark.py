"""
client/benchmark.py — vLLM 服务压测脚本

支持：
  - 并发请求
  - 持续时长（duration）
  - 请求速率（rate）
  - 多种 prompt 长度分布
  - 完整统计：吞吐 / 延迟分位 / 成功率

用法：
    python client/benchmark.py --host localhost --port 8000 \\
        --concurrent 20 --duration 60 --rate 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field

import aiohttp


# 测试 prompt 集合（不同长度分布，模拟真实流量）
SHORT_PROMPTS = [
    "你好",
    "1+1=",
    "今天天气怎么样？",
    "解释什么是机器学习。",
]

MEDIUM_PROMPTS = [
    "请写一篇关于人工智能在医疗领域应用的短文，约 200 字。",
    "解释 Transformer 架构中的 Multi-Head Attention 原理。",
    "比较 Python 和 Rust 在系统编程中的优缺点。",
]

LONG_PROMPTS = [
    "请详细介绍大模型推理框架 vLLM 的 PagedAttention 机制、continuous batching 算法、"
    "chunked prefill 策略，并对比它们对吞吐和延迟的影响。"
] * 5


@dataclass
class Stats:
    """压测统计。"""
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0


async def send_request(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    stats: Stats,
    lock: asyncio.Lock,
):
    """发送单个请求并更新统计。"""
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    start = time.time()
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
            result = await resp.json()
            elapsed = time.time() - start
            if "choices" in result:
                async with lock:
                    stats.successful += 1
                    stats.latencies.append(elapsed)
                    stats.prompt_tokens.append(result["usage"]["prompt_tokens"])
                    stats.completion_tokens.append(result["usage"]["completion_tokens"])
            else:
                async with lock:
                    stats.failed += 1
    except Exception as e:
        async with lock:
            stats.failed += 1
    finally:
        async with lock:
            stats.total_requests += 1


async def run_benchmark(
    host: str,
    port: int,
    model: str,
    concurrent: int,
    duration: int,
    rate: float,
    max_tokens: int,
    prompt_dist: str,
):
    """执行压测。"""
    url = f"http://{host}:{port}/v1/completions"
    stats = Stats()
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrent)

    # 选择 prompt 集合
    if prompt_dist == "short":
        prompts = SHORT_PROMPTS
    elif prompt_dist == "medium":
        prompts = MEDIUM_PROMPTS
    elif prompt_dist == "long":
        prompts = LONG_PROMPTS
    else:  # mixed
        prompts = SHORT_PROMPTS + MEDIUM_PROMPTS + LONG_PROMPTS

    interval = 1.0 / rate if rate > 0 else 0
    stats.start_time = time.time()
    end_time = stats.start_time + duration

    print(f"=== Benchmark Start ===")
    print(f"  URL: {url}")
    print(f"  Concurrent: {concurrent}")
    print(f"  Duration: {duration}s")
    print(f"  Rate: {rate} req/s")
    print(f"  Prompt distribution: {prompt_dist}")
    print()

    tasks = []
    request_count = 0

    async with aiohttp.ClientSession() as session:
        while time.time() < end_time:
            prompt = random.choice(prompts)
            async with semaphore:
                task = asyncio.create_task(
                    send_request(session, url, model, prompt, max_tokens, stats, lock)
                )
                tasks.append(task)
                request_count += 1

            if request_count % 50 == 0:
                print(f"  Sent {request_count} requests, success={stats.successful}, failed={stats.failed}")

            if interval > 0:
                await asyncio.sleep(interval)
            else:
                await asyncio.sleep(0)  # yield control

        # 等待所有任务完成
        print(f"\nWaiting for {len(tasks)} pending requests...")
        await asyncio.gather(*tasks, return_exceptions=True)

    stats.end_time = time.time()
    return stats


def print_report(stats: Stats):
    """打印压测报告。"""
    total_time = stats.end_time - stats.start_time

    print(f"\n{'=' * 50}")
    print(f"Benchmark Report")
    print(f"{'=' * 50}")
    print(f"Total time:      {total_time:.2f}s")
    print(f"Total requests:  {stats.total_requests}")
    print(f"Successful:      {stats.successful}")
    print(f"Failed:          {stats.failed}")
    success_rate = stats.successful / max(stats.total_requests, 1) * 100
    print(f"Success rate:    {success_rate:.1f}%")

    if stats.latencies:
        lats = sorted(stats.latencies)
        n = len(lats)
        print(f"\nLatency (s):")
        print(f"  Mean:   {statistics.mean(lats):.3f}")
        print(f"  Median: {lats[n // 2]:.3f}")
        print(f"  P90:    {lats[int(n * 0.9)]:.3f}")
        print(f"  P95:    {lats[int(n * 0.95)]:.3f}")
        print(f"  P99:    {lats[min(int(n * 0.99), n - 1)]:.3f}")
        print(f"  Min:    {lats[0]:.3f}")
        print(f"  Max:    {lats[-1]:.3f}")

    if stats.completion_tokens:
        total_tokens = sum(stats.completion_tokens)
        print(f"\nThroughput:")
        print(f"  Total output tokens: {total_tokens}")
        print(f"  Tokens/sec:          {total_tokens / total_time:.1f}")
        print(f"  Requests/sec:       {stats.successful / total_time:.1f}")

    # 保存报告到 JSON
    report = {
        "total_time": total_time,
        "total_requests": stats.total_requests,
        "successful": stats.successful,
        "failed": stats.failed,
        "success_rate": success_rate,
        "latency_mean": statistics.mean(stats.latencies) if stats.latencies else 0,
        "latency_p50": stats.latencies[len(stats.latencies) // 2] if stats.latencies else 0,
        "latency_p95": stats.latencies[int(len(stats.latencies) * 0.95)] if stats.latencies else 0,
        "latency_p99": stats.latencies[min(int(len(stats.latencies) * 0.99), len(stats.latencies) - 1)] if stats.latencies else 0,
        "tokens_per_sec": sum(stats.completion_tokens) / total_time if stats.completion_tokens else 0,
        "requests_per_sec": stats.successful / total_time,
    }
    with open("benchmark_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to benchmark_report.json")


def main():
    parser = argparse.ArgumentParser(description="vLLM benchmark")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="llm")
    parser.add_argument("--concurrent", type=int, default=20, help="并发数")
    parser.add_argument("--duration", type=int, default=60, help="持续时间（秒）")
    parser.add_argument("--rate", type=float, default=10, help="请求速率（req/s），0=不限")
    parser.add_argument("--max-tokens", type=int, default=50, help="每请求最大输出 token")
    parser.add_argument("--prompt-dist", default="mixed", choices=["short", "medium", "long", "mixed"])
    args = parser.parse_args()

    stats = asyncio.run(run_benchmark(
        host=args.host,
        port=args.port,
        model=args.model,
        concurrent=args.concurrent,
        duration=args.duration,
        rate=args.rate,
        max_tokens=args.max_tokens,
        prompt_dist=args.prompt_dist,
    ))
    print_report(stats)


if __name__ == "__main__":
    main()
