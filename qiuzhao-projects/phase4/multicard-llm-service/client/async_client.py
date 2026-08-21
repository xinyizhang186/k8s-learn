"""
client/async_client.py — 异步并发客户端

用 asyncio + aiohttp 实现高并发请求，模拟真实生产流量。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import aiohttp


@dataclass
class RequestResult:
    success: bool
    elapsed: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""


async def send_one_request(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    """发送单个异步请求。"""
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    start = time.time()
    async with semaphore:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                result = await resp.json()
                elapsed = time.time() - start
                if "choices" in result:
                    return RequestResult(
                        success=True,
                        elapsed=elapsed,
                        prompt_tokens=result["usage"]["prompt_tokens"],
                        completion_tokens=result["usage"]["completion_tokens"],
                    )
                return RequestResult(success=False, elapsed=elapsed, error=str(result))
        except Exception as e:
            return RequestResult(success=False, elapsed=time.time() - start, error=str(e))


async def run_concurrent_requests(
    host: str,
    port: int,
    model: str,
    prompt: str,
    max_tokens: int,
    num_requests: int,
    concurrent: int,
) -> list[RequestResult]:
    """并发发送 N 个请求。"""
    url = f"http://{host}:{port}/v1/completions"
    semaphore = asyncio.Semaphore(concurrent)

    async with aiohttp.ClientSession() as session:
        tasks = [
            send_one_request(session, url, model, prompt, max_tokens, semaphore)
            for _ in range(num_requests)
        ]
        return await asyncio.gather(*tasks)


async def main():
    import sys
    host = "localhost"
    port = 8000
    model = "llm"
    prompt = "请介绍一下人工智能的发展历史。"
    num = 50
    concurrent = 10

    results = await run_concurrent_requests(host, port, model, prompt, 50, num, concurrent)

    successful = [r for r in results if r.success]
    print(f"Successful: {len(successful)}/{len(results)}")
    if successful:
        latencies = [r.elapsed for r in successful]
        tokens = [r.completion_tokens for r in successful]
        print(f"Avg latency: {sum(latencies) / len(latencies):.2f}s")
        print(f"Total tokens: {sum(tokens)}")


if __name__ == "__main__":
    asyncio.run(main())
