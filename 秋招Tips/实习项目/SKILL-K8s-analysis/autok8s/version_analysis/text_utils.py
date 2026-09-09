"""text_utils.py — 文本清洗/分句/截断工具 (从 content_gen.py 抽出)。"""
from __future__ import annotations

import re

from .keywords import (
    _NOISE_PATTERNS, _ZH_NOISE_RE, _ZH_PAIN_FORBIDDEN_RE, _ZH_ENH_CLICHE_RE,
)


_STAGE_WORDS_RE = re.compile(r"升级为|晋升为|进阶至|进阶为|达到.*GA|正式发布|引入.*Alpha|进阶.*Beta|升级到稳定|升级至稳定|进阶至稳定|晋升为稳定|达到稳定|进阶为GA|晋升至GA|升级为.*稳定|升级为.*Beta|晋升为.*稳定|晋升为.*Beta|进阶为.*稳定|进阶为.*Beta")


def _assemble_intro(pain: str, prefix: str, enh: str, feature, name: str) -> str:
    """组装 intro, 自动去重: enh 已含阶段声明时不拼接 prefix。

    避免 "v1.36 将X晋升为 GA，X升级为稳定版" 重复 (prefix 与 enh 表达同一阶段信息)。
    判断 enh 是否已含阶段声明: 含任一阶段词 (升级为/晋升为/进阶至/稳定版/Beta版 等)。
    """
    ver = getattr(feature, "version", "")
    enh_has_stage = False
    if enh and ver:
        stage_match = re.search(
            r"升级为|晋升为|进阶至|进阶为|达到.*GA|正式发布|"
            r"升级到稳定|升级至稳定|进阶至稳定|晋升为稳定|达到稳定|"
            r"进阶为GA|晋升至GA|升级为.*稳定|升级为.*Beta|"
            r"晋升为.*稳定|晋升为.*Beta|进阶为.*稳定|进阶为.*Beta",
            enh,
        )
        enh_has_stage = bool(stage_match)
    if enh_has_stage:
        enh_part = enh
    else:
        enh_part = f"{prefix}，{enh}" if enh else prefix

    if pain and enh_part:
        return f"现状：{pain}\n本特性增强：{enh_part}"
    if pain:
        return f"现状：{pain}\n本特性增强：{prefix}"
    return (f"现状：{name} 在此前缺乏原生支持或存在明显限制。\n"
            f"本特性增强：{enh_part}")


def _clean_cn(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    text = text.replace("( ", "(").replace(" )", ")")
    text = text.replace("（ ", "（").replace(" ）", "）")
    text = re.sub(r"。+", "。", text)
    text = re.sub(r"，。", "。", text)
    text = re.sub(r"。+", "。", text)
    text = re.sub(r"KEP[- ]?\d+", "", text, flags=re.I)
    text = re.sub(r"SIG\s*[A-Za-z /]+", "SIG", text, flags=re.I)
    text = re.sub(r"SIG[A-Z]", "SIG", text)
    text = re.sub(r"mount-ocontext", "mount -o context", text)
    text = re.sub(r"([^A-Z])([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.replace("SuspidedJobs", "SuspendedJobs")
    text = text.replace("SuspishedJobs", "SuspendedJobs")
    text = re.sub(r"。+", "。", text)
    text = re.sub(r"^[。，、；\s]+", "", text)
    return text.strip()


def _is_valid_cn_value(text: str) -> bool:
    if not text or len(text.strip()) < 5:
        return False
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(text.strip())
    return cn >= 5 or cn / max(total, 1) >= 0.3


def _strip_noise(text: str) -> str:
    for pat in _NOISE_PATTERNS:
        text = re.sub(pat, "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\s*,\s*,", ",", text)
    return text


def _split_sentences(text: str) -> list[str]:
    sents = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sents if s.strip()]


def _split_cn_sentences(text: str) -> list[str]:
    sents = re.split(r'[。！？]', text)
    return [s.strip() for s in sents if s.strip()]


def _split_zh_sentences(text: str) -> list[str]:
    sents = re.split(r'(?<=[。！？])', text)
    return [s.strip() for s in sents if s.strip()]


def _cn_count(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def _cn_ratio_ok(s: str, minimum: float = 0.25) -> bool:
    return _cn_count(s) / max(len(s), 1) >= minimum


def _is_noise(s: str) -> bool:
    return bool(_ZH_NOISE_RE.search(s))


def _join_cjk(left: str, right: str) -> str:
    """在 CJK 与 ASCII 边界插入空格 (如 'Pod晋升' -> 'Pod 晋升')。"""
    if not left or not right:
        return left + right
    last = left[-1]
    first = right[0]
    is_cjk = lambda c: ord(c) > 0x2E80
    if (is_cjk(last) and first.isalnum() and not is_cjk(first)) or \
       (not is_cjk(last) and last.isalnum() and is_cjk(first)):
        return left + " " + right
    return left + right


def _truncate_cn(text: str, max_len: int) -> str:
    text = _clean_cn(text)
    text = re.sub(r"\d+。", "。", text)
    text = re.sub(r"^[。，、；\s]+", "", text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_period = cut.rfind("。")
    if last_period > max_len // 2:
        return cut[:last_period + 1]
    last_comma = max(cut.rfind("，"), cut.rfind("、"), cut.rfind("；"))
    if last_comma > max_len // 2:
        return cut[:last_comma] + "。"
    return cut[:max_len] + "。"


def _truncate_value_zh(s: str, max_len: int = 60) -> str:
    """将价值句截断到 max_len 字以内, 在自然停顿处 (从而/使得/，) 断句。"""
    s = s.strip().rstrip("。")
    if len(s) <= max_len:
        return s + "。"
    for sep in ["，从而", "，使得", "，让", "，有助于", "，", "；"]:
        idx = s.find(sep, max_len // 2)
        if 0 < idx <= max_len + 10:
            return s[:idx] + "。"
    cut = s[:max_len]
    for sep in ["，", "、", "；", " "]:
        idx = cut.rfind(sep)
        if idx > max_len // 2:
            return cut[:idx] + "。"
    return cut + "。"


def _truncate_pain_zh(s: str, max_len: int = 100) -> str:
    """将痛点句截断到 max_len 字以内, 在逗号处断句保留完整语义。"""
    s = s.strip().rstrip("。")
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    for sep in ["，", "；", "、"]:
        idx = cut.rfind(sep)
        if idx > max_len // 2:
            return s[:idx]
    return cut


def _clean_pain_verbose(s: str) -> str:
    """精简痛点句中的主观冗余短语 (如 '人们才会发现', '通常要等到为时已晚')。"""
    s = re.sub(r"通常要等到为时已晚[，,]?\s*", "", s)
    s = re.sub(r"即[^，。;]{0,15}之后[，,]?\s*人们才会发现[，,]?\s*", "，", s)
    s = re.sub(r"人们才会发现[，,]?\s*", "", s)
    s = re.sub(r"我们很高兴地宣布[，,]?\s*", "", s)
    s = re.sub(r"这一期待已久的特性\s*", "", s)
    s = re.sub(r"^[，,；;、\s]+", "", s)
    s = re.sub(r"[，,；;、\s]+$", "", s)
    s = re.sub(r"，[，,]+", "，", s)
    return s.strip()
