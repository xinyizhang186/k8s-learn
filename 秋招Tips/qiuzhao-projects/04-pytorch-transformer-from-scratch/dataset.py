"""
dataset.py — 简单翻译数据集（toy 英文 -> 中文风格 toy 数据）

实际应用用 IWSLT / WMT 等公开数据集，这里用 toy 数据便于快速跑通。
"""
from __future__ import annotations

import torch
from torch.utils.data import Dataset

from tokenizer import SimpleTokenizer


# Toy 数据（英文 -> 简单"翻译"，实际是替换映射）
TOY_DATA = [
    ("i love machine learning", "我 爱 机器 学习"),
    ("she likes deep learning", "她 喜欢 深度 学习"),
    ("he is a student", "他 是 学生"),
    ("we study together", "我们 一起 学习"),
    ("they work hard", "他们 工作 努力"),
    ("i like cats", "我 喜欢 猫"),
    ("she has a dog", "她 有 狗"),
    ("he reads books", "他 读 书"),
    ("we eat dinner", "我们 吃 晚饭"),
    ("they play games", "他们 玩 游戏"),
    ("the weather is nice", "天气 很好"),
    ("i am happy", "我 开心"),
    ("she is sad", "她 伤心"),
    ("he runs fast", "他 跑得快"),
    ("we go home", "我们 回家"),
    ("they come here", "他们 来这里"),
    ("i want water", "我 要 水"),
    ("she needs help", "她 需要 帮助"),
    ("he knows math", "他 懂 数学"),
    ("we love nature", "我们 爱 大自然"),
]


class TranslationDataset(Dataset):
    """简单翻译数据集。"""

    def __init__(self, data: list[tuple[str, str]] | None = None, max_len: int = 64):
        self.data = data if data is not None else TOY_DATA
        self.max_len = max_len

        # 构建双语统一 tokenizer（简化：中英文混合）
        all_texts = []
        for src, tgt in self.data:
            all_texts.append(src)
            all_texts.append(tgt)
        self.tokenizer = SimpleTokenizer()
        self.tokenizer.build_vocab(all_texts)

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        src_text, tgt_text = self.data[idx]
        src_ids = self.tokenizer.encode(src_text)
        tgt_ids = self.tokenizer.encode(tgt_text)

        # pad 到 max_len
        src_ids = src_ids[: self.max_len] + [self.tokenizer.pad_id] * max(0, self.max_len - len(src_ids))
        tgt_ids = tgt_ids[: self.max_len] + [self.tokenizer.pad_id] * max(0, self.max_len - len(tgt_ids))

        return {
            "src": torch.tensor(src_ids, dtype=torch.long),
            "tgt_in": torch.tensor(tgt_ids[:-1], dtype=torch.long),   # decoder 输入（去掉最后）
            "tgt_out": torch.tensor(tgt_ids[1:], dtype=torch.long),   # decoder 标签（去掉首个）
        }


def collate_fn(batch: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    """把 list of dict -> dict of stacked tensor。"""
    return {key: torch.stack([item[key] for item in batch]) for key in batch[0]}
