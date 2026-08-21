"""
generate.py — 推理 / 翻译生成

用法：
    python generate.py --input "i love machine learning"
    python generate.py --input "she likes deep learning" --max-len 30
"""
from __future__ import annotations

import argparse

import torch

from dataset import TranslationDataset
from model import Transformer, TransformerConfig, make_src_mask


def load_model(checkpoint_path: str, device: torch.device) -> tuple[Transformer, TranslationDataset]:
    """加载训练好的模型。"""
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = TransformerConfig(**ckpt["config"])
    model = Transformer(config).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    # 重建 dataset 以拿到 tokenizer（词表相同）
    dataset = TranslationDataset()
    return model, dataset


def translate(model: Transformer, dataset: TranslationDataset, text: str, device: torch.device, max_len: int = 50) -> str:
    """翻译单个句子。"""
    tokenizer = dataset.tokenizer
    pad_id = tokenizer.pad_id
    bos_id = tokenizer.bos_id
    eos_id = tokenizer.eos_id

    # 编码源句
    src_ids = tokenizer.encode(text)
    src = torch.tensor([src_ids], dtype=torch.long, device=device)
    src_mask = make_src_mask(src, pad_id).to(device)

    # 生成
    out_ids = model.generate(src, src_mask, max_len=max_len, bos_id=bos_id, eos_id=eos_id)
    out_text = tokenizer.decode(out_ids[0].tolist(), skip_special=True)
    return out_text


def main():
    parser = argparse.ArgumentParser(description="Translate with trained Transformer")
    parser.add_argument("--checkpoint", type=str, default="transformer_checkpoint.pt")
    parser.add_argument("--input", type=str, required=True, help="Source text to translate")
    parser.add_argument("--max-len", type=int, default=50)
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda", "npu"])
    args = parser.parse_args()

    if args.device == "auto":
        if torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            try:
                import torch_npu  # noqa: F401
                device = torch.device("npu") if torch.npu.is_available() else torch.device("cpu")
            except ImportError:
                device = torch.device("cpu")
    else:
        device = torch.device(args.device)

    model, dataset = load_model(args.checkpoint, device)

    print(f"Input:  {args.input}")
    result = translate(model, dataset, args.input, device, args.max_len)
    print(f"Output: {result}")


if __name__ == "__main__":
    main()
