"""
client/benchmark_client.py — 简单压测客户端

用法：
    python client/benchmark_client.py --num-requests 100 --rate 5
    python client/benchmark_client.py --num-requests 500 --rate 10 --concurrent 20
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock


def send_request(host: str, port: int, model: str, prompt: str, max_tokens: int) -> dict:
    """发送一个请求，返回计时结果。"""
    url = f"http://{host}:{port}/v1/completions"
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start
            return {
                "success": True,
                "elapsed": elapsed,
                "prompt_tokens": result["usage"]["prompt_tokens"],
                "completion_tokens": result["usage"]["completion_tokens"],
            }
    except Exception as e:
        elapsed = time.time() - start
        return {"success": False, "elapsed": elapsed, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Benchmark vLLM service")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="qwen3")
    parser.add_argument("--prompt", default="请写一篇关于人工智能的短文。")
    parser.add_argument("--max-tokens", type=int, default=50)
    parser.add_argument("--num-requests", type=int, default=100)
    parser.add_argument("--concurrent", type=int, default=10)
    args = parser.parse_args()

    print(f"=== vLLM Benchmark ===")
    print(f"  URL: http://{args.host}:{args.port}")
    print(f"  Model: {args.model}")
    print(f"  Prompt: {args.prompt[:50]}...")
    print(f"  Max tokens: {args.max_tokens}")
    print(f"  Requests: {args.num_requests}")
    print(f"  Concurrent: {args.concurrent}")
    print()

    results = []
    lock = Lock()
    completed = [0]

    with ThreadPoolExecutor(max_workers=args.concurrent) as executor:
        futures = [
            executor.submit(send_request, args.host, args.port, args.model, args.prompt, args.max_tokens)
            for _ in range(args.num_requests)
        ]

        start_time = time.time()
        for future in as_completed(futures):
            result = future.result()
            with lock:
                results.append(result)
                completed[0] += 1
                if completed[0] % 10 == 0:
                    print(f"  Progress: {completed[0]}/{args.num_requests}")
        total_time = time.time() - start_time

    # 统计
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print(f"\n=== Results ===")
    print(f"  Total time: {total_time:.2f}s")
    print(f"  Successful: {len(successful)}/{len(results)}")
    print(f"  Failed: {len(failed)}")

    if successful:
        latencies = [r["elapsed"] for r in successful]
        tokens = [r["completion_tokens"] for r in successful]

        print(f"\n  Latency (s):")
        print(f"    Mean:   {statistics.mean(latencies):.3f}")
        print(f"    Median: {statistics.median(latencies):.3f}")
        print(f"    P95:    {sorted(latencies)[int(len(latencies) * 0.95)]:.3f}")
        print(f"    P99:    {sorted(latencies)[int(len(latencies) * 0.99)]:.3f}")
        print(f"    Min:    {min(latencies):.3f}")
        print(f"    Max:    {max(latencies):.3f}")

        total_tokens = sum(tokens)
        print(f"\n  Throughput:")
        print(f"    Total tokens: {total_tokens}")
        print(f"    Tokens/sec:   {total_tokens / total_time:.1f}")
        print(f"    Requests/sec: {len(successful) / total_time:.1f}")

    if failed:
        print(f"\n  Errors (first 3):")
        for r in failed[:3]:
            print(f"    - {r.get('error', 'unknown')}")


if __name__ == "__main__":
    main()
