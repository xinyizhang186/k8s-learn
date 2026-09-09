"""Shared text quality gates used before generated content is published."""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_TEMPLATE_PREFIXES = ("此前 Kubernetes 缺乏原生支持", "此前 Kubernetes 缺乏", "此前集群缺乏原生支持", "该特性在此前缺乏原生支持", "该功能在此前缺乏原生支持", "本特性在此前缺乏原生支持")
_GENERIC_VALUE = re.compile(r"^(提升|增强|简化|改善|支持|实现).{0,8}[。！!]?$")
_ACTION_WORDS = ("检查", "确认", "核对", "查看", "验证", "排查", "审计")
_VALUE_PREFIX_RE = re.compile(r"^\s*(?:此项工作|这项工作|这部分工作|这一变更|这一改进|这一机制|这一举措|这项举措|该特性|本特性|此特性|该功能|此功能|此增强|此增强功能|该变更|这可|这会|这将|你现在可以|您现在可以|现在可以|如今可以)", re.I)
_VALUE_BACKGROUND_RE = re.compile(r"KEP\s*#?\s*\d+|\bSIG\b|由\s*SIG|牵头(?:完成|开发)?|(?:最初|首次).{0,16}v?1\.\d+.{0,20}(?:引入|发布)|已于.{0,12}v?1\.\d+.{0,20}(?:晋升|升级|稳定版|GA)|(?:alpha|beta|GA|稳定版).{0,20}(?:引入|晋升|升级)", re.I)
_VALUE_PAIN_RE = re.compile(r"^(?:也)?(?:没有|无法|不能|难以|缺乏|不存在|未提供|不支持)|(?:没有统一方式|缺少统一方式|无法统一)", re.I)
_VALUE_BENEFIT_WORDS = ("提升", "降低", "简化", "消除", "改善", "保护", "防止", "避免", "确保", "减少", "加速", "统一", "缓解", "收敛", "隔离", "恢复", "增强", "替代", "实现", "保障", "支持", "允许")
_ENHANCEMENT_HISTORY_RE = re.compile(r"(?:最初|首次).{0,18}v?1\.\d+.{0,20}(?:引入|发布)|(?:已于|并于).{0,16}v?1\.\d+.{0,20}(?:晋升|升级|稳定版|GA)|作为\s*Alpha\s*引入", re.I)
_ENHANCEMENT_GENERIC_RE = re.compile(r"(?:进一步)?(?:完善|增强|改进)(?:相关)?(?:能力|功能)|相关(?:能力|功能)(?:得到)?(?:完善|增强)|经过.{0,20}(?:alpha|beta|GA|稳定)|随着.{0,20}(?:升级|稳定)|达到.{0,20}(?:通用可用|成熟|里程碑)|期待已久|向前迈出.{0,12}(?:一步|步)", re.I)


def chinese_ratio(text: str) -> float:
    return len(re.findall(r"[\u4e00-\u9fff]", text or "")) / max(len(text or ""), 1)


def value_issues(value: str) -> list[str]:
    text = (value or "").strip()
    issues: list[str] = []
    if len(text) < 14 or _GENERIC_VALUE.match(text): issues.append("value_is_generic")
    if _VALUE_PREFIX_RE.search(text): issues.append("value_has_verbose_prefix")
    if _VALUE_BACKGROUND_RE.search(text): issues.append("value_is_background_or_history")
    if _VALUE_PAIN_RE.search(text): issues.append("value_is_pain_statement")
    if text and not any(word in text for word in _VALUE_BENEFIT_WORDS): issues.append("value_missing_benefit")
    return issues


def enhancement_issues(enhancement: str) -> list[str]:
    text = (enhancement or "").strip()
    issues: list[str] = []
    if len(text) < 20: issues.append("enhancement_incomplete")
    if _ENHANCEMENT_HISTORY_RE.search(text): issues.append("enhancement_has_unnecessary_history")
    if _ENHANCEMENT_GENERIC_RE.search(text): issues.append("enhancement_is_generic")
    return issues


def content_issues(pain: str, enhancement: str, value: str, evidence: str = "") -> list[str]:
    issues: list[str] = []
    if len((pain or "").strip()) < 14 or any((pain or "").strip().startswith(p) for p in _TEMPLATE_PREFIXES): issues.append("pain_is_generic")
    if not any(word in (pain or "") for word in ("无法", "难以", "缺乏", "不一致", "风险", "限制", "依赖", "失败", "不足")): issues.append("pain_missing_problem")
    issues.extend(enhancement_issues(enhancement))
    issues.extend(value_issues(value))
    if chinese_ratio((pain or "") + (enhancement or "") + (value or "")) < 0.20: issues.append("low_chinese_ratio")
    if evidence and not any(token.lower() in evidence.lower() for token in _technical_tokens((enhancement or "") + (value or ""))): issues.append("claim_not_grounded")
    return list(dict.fromkeys(issues))


def is_usable_value(value: str) -> bool:
    return not value_issues(value)


def narrative_issues(check_method: str, detail: str, source_en: str = "") -> list[str]:
    issues: list[str] = []
    if len((check_method or "").strip()) < 18 or not any(word in (check_method or "") for word in _ACTION_WORDS): issues.append("check_method_not_actionable")
    if len((detail or "").strip()) < 20: issues.append("detail_incomplete")
    if chinese_ratio((check_method or "") + (detail or "")) < 0.25: issues.append("narrative_not_chinese")
    if source_en and not _technical_tokens((check_method or "") + (detail or "")): issues.append("narrative_lacks_subject")
    return issues


def duplicate_rows(texts: Iterable[str], threshold: float = 0.82) -> set[int]:
    flagged: set[int] = set(); normalized: list[set[str]] = []
    for index, text in enumerate(texts):
        terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]+", text or ""))
        if any(terms and old and len(terms & old) / len(terms | old) >= threshold for old in normalized): flagged.add(index)
        normalized.append(terms)
    return flagged


def _technical_tokens(text: str) -> list[str]:
    return list(Counter(token.lower() for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]+\b", text or "") if len(token) >= 3))
