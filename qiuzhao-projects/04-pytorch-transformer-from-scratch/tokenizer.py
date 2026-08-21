"""
tokenizer.py — 简单字符级 tokenizer（教学用）

实际生产用 BPE/BBPE/SentencePiece，这里为了教学简洁实现字符级分词。
"""
from __future__ import annotations

from collections import Counter


class SimpleTokenizer:
    """
    字符级 tokenizer：
      - 把文本拆成单字符
      - 构建词表：每个字符一个 id
      - 特殊 token: <pad>=0, <bos>=1, <eos>=2, <unk>=3
    """

    PAD = "<pad>"
    BOS = "<bos>"
    EOS = "<eos>"
    UNK = "<unk>"
    SPECIAL_TOKENS = [PAD, BOS, EOS, UNK]

    def __init__(self):
        self.char2id: dict[str, int] = {}
        self.id2char: dict[int, str] = {}
        for i, tok in enumerate(self.SPECIAL_TOKENS):
            self.char2id[tok] = i
            self.id2char[i] = tok

    @property
    def pad_id(self) -> int:
        return self.char2id[self.PAD]

    @property
    def bos_id(self) -> int:
        return self.char2id[self.BOS]

    @property
    def eos_id(self) -> int:
        return self.char2id[self.EOS]

    @property
    def vocab_size(self) -> int:
        return len(self.char2id)

    def build_vocab(self, texts: list[str], min_freq: int = 1) -> None:
        """从文本集合构建词表。"""
        counter = Counter()
        for text in texts:
            counter.update(text)
        for char, freq in counter.most_common():
            if freq >= min_freq and char not in self.char2id:
                idx = len(self.char2id)
                self.char2id[char] = idx
                self.id2char[idx] = char

    def encode(self, text: str, add_special: bool = True) -> list[int]:
        """文本 -> id 列表。"""
        ids = [self.char2id.get(ch, self.char2id[self.UNK]) for ch in text]
        if add_special:
            ids = [self.bos_id] + ids + [self.eos_id]
        return ids

    def decode(self, ids: list[int], skip_special: bool = True) -> str:
        """id 列表 -> 文本。"""
        chars = []
        for i in ids:
            ch = self.id2char.get(i, self.UNK)
            if skip_special and ch in self.SPECIAL_TOKENS:
                continue
            chars.append(ch)
        return "".join(chars)
