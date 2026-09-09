"""
client/client_test.py — OpenAI 兼容 API 客户端测试

用法：
    python client/client_test.py --host localhost --port 8000
"""
from __future__ import annotations

import argparse
import json
import urllib.request
import urllib.error


def chat_completion(host: str, port: int, model: str, prompt: str, max_tokens: int = 100) -> dict:
    """调用 /v1/chat/completions 接口。"""
    url = f"http://{host}:{port}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models(host: str, port: int) -> dict:
    """列出已加载模型。"""
    url = f"http://{host}:{port}/v1/models"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Test vLLM OpenAI-compatible API")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="qwen3")
    parser.add_argument("--prompt", default="你好，请介绍一下自己。")
    parser.add_argument("--max-tokens", type=int, default=100)
    args = parser.parse_args()

    # 1. 健康检查
    print(f"=== Health Check: http://{args.host}:{args.port}/health ===")
    try:
        with urllib.request.urlopen(f"http://{args.host}:{args.port}/health") as resp:
            print(f"  Status: {resp.status} ✓")
    except urllib.error.URLError as e:
        print(f"  Service not reachable: {e}")
        return

    # 2. 列出模型
    print(f"\n=== List Models ===")
    try:
        models = list_models(args.host, args.port)
        for m in models.get("data", []):
            print(f"  - {m['id']}")
    except Exception as e:
        print(f"  Error: {e}")

    # 3. Chat completion
    print(f"\n=== Chat Completion ===")
    print(f"  Model: {args.model}")
    print(f"  Prompt: {args.prompt}")
    try:
        result = chat_completion(args.host, args.port, args.model, args.prompt, args.max_tokens)
        content = result["choices"][0]["message"]["content"]
        print(f"  Response: {content}")
        print(f"  Tokens: prompt={result['usage']['prompt_tokens']}, "
              f"completion={result['usage']['completion_tokens']}")
    except Exception as e:
        print(f"  Error: {e}")


if __name__ == "__main__":
    main()
