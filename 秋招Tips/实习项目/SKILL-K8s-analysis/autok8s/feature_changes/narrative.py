"""Evidence-bound narrative generation for the feature-change worksheet."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from .analyzer import FeatureChange


_ACTION_WORDS = ("检查", "确认", "核对", "查看", "验证", "排查", "审计", "检索")
_PROVENANCE_NOTE_WORDS = ("来源不足", "最小说明", "元数据", "自动生成", "模型生成", "翻译引擎", "抓取失败")


def _fallback(row: FeatureChange, stage: str) -> dict[str, Optional[str]]:
    """Produce an honest, specific minimum when upstream evidence is unavailable."""
    if row.change_type == "Deprecated":
        check = f"检查集群配置、清单和启动参数中是否显式启用 {row.name}，并验证迁移或关闭后相关工作负载的行为。"
    else:
        check = _metadata_check(row, stage)
    return {"排查方法": check, "详细说明": None, "补充说明": None}


def _render_delta(label: str, delta: str, verb: str) -> str:
    """Render analyzer's compact `old->new` notation as fluent Chinese."""
    before, separator, after = delta.partition("->")
    if not separator:
        return f"{label}{delta}"
    if before:
        return f"{label}由 {before} {verb} {after}"
    return f"{label}{verb} {after}"


def _metadata_check(row: FeatureChange, stage: str) -> str:
    """Return a safe check step that does not assume an owning component or API."""
    if row.change_type == "Deprecated":
        return (
            f"在各组件启动参数和配置文件中检索 {row.name}，记录显式设置；"
            "在升级前后的既有验证环境中确认关闭或迁移后依赖功能的行为。"
        )
    if row.default_change and row.default_change != "->false":
        return (
            f"在各组件启动参数和配置文件中检索 {row.name}，记录显式设置；"
            "升级后核对实际生效值，确认默认值变化未被本地配置覆盖。"
        )
    if row.stage_change:
        return (
            f"在各组件启动参数和配置文件中检索 {row.name}，记录显式设置及生效值；"
            "在既有验证环境中确认依赖该特性的工作负载符合当前阶段的预期。"
        )
    return (
        f"在各组件启动参数和配置文件中检索 {row.name}，记录显式设置及生效值；"
        "在升级前后的既有验证环境中确认依赖该特性的工作负载行为。"
    )


def _normalise(text: str) -> str:
    return "".join(ch.lower() for ch in (text or "") if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _is_duplicate_or_near_duplicate(check: str, detail: str) -> bool:
    """Detect same-content columns, including one sentence embedded in the other."""
    left, right = _normalise(check), _normalise(detail)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.72


def _public_note(note: object) -> Optional[str]:
    """Keep only reader-facing notes; suppress generation and evidence-status chatter."""
    text = str(note or "").strip()
    if not text or any(word in text for word in _PROVENANCE_NOTE_WORDS):
        return None
    return text[:300]


def finalise_narrative(
    row: FeatureChange,
    stage: str,
    check_method: object,
    detail: object,
    note: object = None,
) -> dict[str, Optional[str]]:
    """Enforce distinct reader-facing roles for the narrative columns.

    KEP Summary text is explanatory prose, not an operational procedure.  When
    a source supplies duplicate or non-actionable text, retain it as the detail
    and derive one conservative, feature-gate-only check method instead.
    """
    check = str(check_method or "").strip()
    explanation = str(detail or "").strip()

    if not any(word in check for word in _ACTION_WORDS):
        if check and not explanation:
            explanation = check
        check = ""

    if not check:
        fallback = _fallback(row, stage)
        check = str(fallback["排查方法"])

    if explanation and _is_duplicate_or_near_duplicate(check, explanation):
        explanation = ""

    return {"排查方法": check, "详细说明": explanation, "补充说明": _public_note(note)}
