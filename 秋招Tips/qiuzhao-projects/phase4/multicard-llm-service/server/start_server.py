"""
server/start_server.py — vLLM 服务启动入口（Python API 版）

相比 CLI 启动，Python API 更灵活，可程序化控制启动参数。

用法：
    python server/start_server.py --model /models/Llama-3-8B --tp 4
"""
from __future__ import annotations

import argparse
import logging

from vllm import LLM, SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.entrypoints.openai.api_server import run_server


def parse_args():
    parser = argparse.ArgumentParser(description="Start vLLM server")
    parser.add_argument("--model", required=True, help="Model path")
    parser.add_argument("--tp", type=int, default=1, help="Tensor parallel size")
    parser.add_argument("--pp", type=int, default=1, help="Pipeline parallel size")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--max-num-seqs", type=int, default=256)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.9)
    parser.add_argument("--enable-prefix-caching", action="store_true")
    parser.add_argument("--quantization", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    logger.info(f"Starting vLLM server: model={args.model}, tp={args.tp}, pp={args.pp}")

    # 用 EngineArgs 构造参数（CLI 等价）
    engine_args = AsyncEngineArgs(
        model=args.model,
        tensor_parallel_size=args.tp,
        pipeline_parallel_size=args.pp,
        max_model_len=args.max_model_len,
        max_num_seqs=args.max_num_seqs,
        gpu_memory_utilization=args.gpu_memory_utilization,
        enable_prefix_caching=args.enable_prefix_caching,
        quantization=args.quantization,
        trust_remote_code=True,
        distributed_executor_backend="mp",
    )

    # 启动 OpenAI 兼容 server
    run_server(engine_args, args.port)


if __name__ == "__main__":
    main()
