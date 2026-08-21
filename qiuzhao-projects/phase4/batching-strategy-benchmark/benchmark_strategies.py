"""
benchmark_strategies.py — 对比不同 batching 策略下的吞吐量

用法：
    python benchmark_strategies.py --host localhost --port 8000 \\
        --model qwen3 --configs configs/baseline.json configs/large_batch.json

说明：
    本脚本假设 vLLM 服务已启动（用对应策略的参数启动）。
    脚本只负责发请求、测指标、对比结果。

完整流程：
    1. 用 config A 启动 vllm serve
    2. 跑本脚本，记录指标
    3. 改 config B 启动 vllm serve
    4. 再跑本脚本
    5. 最后用 analyze_results.py 汇总
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import aiohttp


# 测试 prompt 池
SHORT_PROMPTS = ["你好", "1+1=", "什么是 AI?", "解释机器学习。", "什么是 vLLM?"]
MEDIUM_PROMPTS = [
    "请写一篇 200 字关于人工智能在医疗领域的应用。",
    "解释 Transformer 的 Multi-Head Attention 原理。",
    "比较 Python 和 Rust 在系统编程中的优缺点。",
    "详细介绍大模型的训练流程。",
]
LONG_PROMPTS = [
    "请详细介绍大模型推理框架 vLLM 的 PagedAttention 机制、continuous batching 算法、"
    "chunked prefill 策略，并对比它们对吞吐和延迟的影响。"
] * 3
MIXED_PROMPTS = SHORT_PROMPTS * 4 + MEDIUM_PROMPTS * 2 + LONG_PROMPTS


@dataclass
class Result:
    strategy_name: str
    description: str
    vllm_args: dict
    test_config: dict
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    total_time: float = 0.0


async def send_request(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    semaphore: asyncio.Semaphore,
    latencies: list[float],
    tokens: list[int],
    prompt_tokens: list[int],
    success_count: list[int],
    fail_count: list[int],
    total_count: list[int],
    lock: asyncio.Lock,
):
    """发送单个请求。"""
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    start = time.time()
    async with semaphore:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                result = await resp.json()
                elapsed = time.time() - start
                if "choices" in result:
                    async with lock:
                        latencies.append(elapsed)
                        tokens.append(result["usage"]["completion_tokens"])
                        prompt_tokens.append(result["usage"]["prompt_tokens"])
                        success_count[0] += 1
                else:
                    async with lock:
                        fail_count[0] += 1
        except Exception:
            async with lock:
                fail_count[0] += 1
        finally:
            async with lock:
                total_count[0] += 1


async def run_strategy(
    host: str,
    port: int,
    model: str,
    config: dict,
) -> Result:
    """跑一个策略的压测。"""
    name = config["name"]
    desc = config.get("description", "")
    vllm_args = config.get("vllm_args", {})
    test_cfg = config.get("test_config", {})

    result = Result(strategy_name=name, description=desc, vllm_args=vllm_args, test_config=test_cfg)

    num_requests = test_cfg.get("num_requests", 200)
    concurrent = test_cfg.get("concurrent", 20)
    max_tokens = test_cfg.get("max_tokens", 100)
    prompt_dist = test_cfg.get("prompt_dist", "mixed")

    if prompt_dist == "short":
        prompts = SHORT_PROMPTS
    elif prompt_dist == "medium":
        prompts = MEDIUM_PROMPTS
    elif prompt_dist == "long":
        prompts = LONG_PROMPTS
    else:
        prompts = MIXED_PROMPTS

    url = f"http://{host}:{port}/v1/completions"
    semaphore = asyncio.Semaphore(concurrent)
    lock = asyncio.Lock()

    latencies: list[float] = []
    tokens: list[int] = []
    prompt_tokens: list[int] = []
    success_count = [0]
    fail_count = [0]
    total_count = [0]

    print(f"\n=== Strategy: {name} ===")
    print(f"  Description: {desc}")
    print(f"  Requests: {num_requests}, Concurrent: {concurrent}")

    start = time.time()
    async with aiohttp.ClientSession() as session:
        tasks = [
            send_request(
                session, url, model, random.choice(prompts), max_tokens,
                semaphore, latencies, tokens, prompt_tokens,
                success_count, fail_count, total_count, lock,
            )
            for _ in range(num_requests)
        ]
        await asyncio.gather(*tasks)
    result.total_time = time.time() - start

    result.total_requests = total_count[0]
    result.successful = success_count[0]
    result.failed = fail_count[0]
    result.latencies = latencies
    result.completion_tokens = tokens
    result.prompt_tokens = prompt_tokens

    # 即时打印
    if latencies:
        n = len(latencies)
        print(f"  Result: success={success_count[0]}/{num_requests}")
        print(f"  Throughput: {sum(tokens) / result.total_time:.1f} tok/s")
        print(f"  Latency mean: {statistics.mean(latencies):.3f}s, "
              f"P95: {sorted(latencies)[int(n * 0.95)]:.3f}s")

    return result


def main():
    parser = argparse.ArgumentParser(description="Benchmark vLLM batching strategies")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="llm")
    parser.add_argument("--configs", nargs="+", required=True,
                        help="JSON config files for each strategy")
    parser.add_argument("--output", default="reports/results.json",
                        help="Output file for results")
    args = parser.parse_args()

    results = []
    for cfg_path in args.configs:
        with open(cfg_path) as f:
            config = json.load(f)
        result = asyncio.run(run_strategy(args.host, args.port, args.model, config))
        results.append(asdict(result))

    # 保存
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {args.output}")
    print(f"Run `python analyze_results.py --input {args.output}` to generate report")


if __name__ == "__main__":
    main()
