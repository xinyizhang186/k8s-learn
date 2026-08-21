"""
train.py — 训练入口

用法：
    python train.py --epochs 30 --batch-size 32
    python train.py --device cuda
    python train.py --device npu  # 需安装 torch_npu

训练流程：
    1. 创建 dataset + tokenizer
    2. 创建 model + optimizer + loss
    3. 循环：forward -> loss -> backward -> step
    4. 每 epoch 打印 loss + sample 翻译
"""
from __future__ import annotations

import argparse
import math

import torch
from torch.utils.data import DataLoader

from dataset import TranslationDataset, collate_fn
from model import (
    Transformer,
    TransformerConfig,
    LabelSmoothingLoss,
    make_src_mask,
    make_tgt_mask,
)


def get_device(device: str) -> torch.device:
    """选择 device（支持 cuda / npu / cpu）。"""
    if device == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        try:
            import torch_npu  # noqa: F401
            if torch.npu.is_available():
                return torch.device("npu")
        except ImportError:
            pass
        return torch.device("cpu")
    return torch.device(device)


def train_one_epoch(
    model: Transformer,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: LabelSmoothingLoss,
    device: torch.device,
    pad_id: int,
) -> float:
    """训练一个 epoch，返回平均 loss。"""
    model.train()
    total_loss = 0.0
    n_batches = 0

    for batch in dataloader:
        src = batch["src"].to(device)
        tgt_in = batch["tgt_in"].to(device)
        tgt_out = batch["tgt_out"].to(device)

        src_mask = make_src_mask(src, pad_id).to(device)
        tgt_mask = make_tgt_mask(tgt_in, pad_id).to(device)

        logits = model(src, tgt_in, src_mask, tgt_mask)
        loss = criterion(logits, tgt_out)

        optimizer.zero_grad()
        loss.backward()
        # 梯度裁剪（防梯度爆炸，Transformer 必备）
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

    return total_loss / max(n_batches, 1)


@torch.no_grad()
def evaluate(
    model: Transformer,
    dataloader: DataLoader,
    criterion: LabelSmoothingLoss,
    device: torch.device,
    pad_id: int,
) -> float:
    """评估 loss。"""
    model.eval()
    total_loss = 0.0
    n_batches = 0

    for batch in dataloader:
        src = batch["src"].to(device)
        tgt_in = batch["tgt_in"].to(device)
        tgt_out = batch["tgt_out"].to(device)

        src_mask = make_src_mask(src, pad_id).to(device)
        tgt_mask = make_tgt_mask(tgt_in, pad_id).to(device)

        logits = model(src, tgt_in, src_mask, tgt_mask)
        loss = criterion(logits, tgt_out)

        total_loss += loss.item()
        n_batches += 1

    return total_loss / max(n_batches, 1)


def lr_lambda(step: int, warmup_steps: int = 1000, d_model: int = 256) -> float:
    """
    Transformer 原论文 Noam 学习率调度：
        lr = d_model^(-0.5) * min(step^(-0.5), step * warmup^(-1.5))

    特点：前 warmup_steps 线性增，之后按 1/sqrt(step) 衰减。
    """
    step = max(step, 1)
    return d_model ** (-0.5) * min(step ** (-0.5), step * warmup_steps ** (-1.5))


def main():
    parser = argparse.ArgumentParser(description="Train a Transformer from scratch")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda", "npu"])
    parser.add_argument("--d-model", type=int, default=128)
    parser.add_argument("--n-heads", type=int, default=4)
    parser.add_argument("--n-layers", type=int, default=3)
    parser.add_argument("--d-ff", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = get_device(args.device)
    print(f"Using device: {device}")

    # 数据
    dataset = TranslationDataset()
    vocab_size = dataset.tokenizer.vocab_size
    pad_id = dataset.tokenizer.pad_id
    print(f"Vocab size: {vocab_size}, dataset size: {len(dataset)}")

    dataloader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_fn,
    )

    # 模型
    config = TransformerConfig(
        src_vocab_size=vocab_size,
        tgt_vocab_size=vocab_size,
        d_model=args.d_model,
        n_heads=args.n_heads,
        d_ff=args.d_ff,
        num_encoder_layers=args.n_layers,
        num_decoder_layers=args.n_layers,
        max_seq_len=64,
        pad_token_id=pad_id,
        use_rmsnorm=True,  # 用 RMSNorm（现代实践）
    )
    model = Transformer(config).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {n_params:,} ({n_params / 1e6:.2f}M)")

    # 优化器 + 调度器
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, betas=(0.9, 0.98), eps=1e-9, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    criterion = LabelSmoothingLoss(vocab_size, smoothing=0.1, pad_id=pad_id)

    # 训练循环
    for epoch in range(1, args.epochs + 1):
        avg_loss = train_one_epoch(model, dataloader, optimizer, criterion, device, pad_id)
        scheduler.step()

        if epoch % 5 == 0 or epoch == 1:
            ppl = math.exp(min(avg_loss, 20))  # 防 overflow
            print(f"Epoch {epoch:3d} | Loss: {avg_loss:.4f} | PPL: {ppl:.2f} | LR: {scheduler.get_last_lr()[0]:.6f}")

    # 保存
    torch.save({
        "model_state_dict": model.state_dict(),
        "config": config.__dict__,
        "vocab_size": vocab_size,
    }, "transformer_checkpoint.pt")
    print("Model saved to transformer_checkpoint.pt")


if __name__ == "__main__":
    main()
