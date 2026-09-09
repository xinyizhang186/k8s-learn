"""content_store.py — 特性变更叙事内容获取 (自动化, 在线翻译)。

内容来源:
  1. ORIG_ROWS  : 保留需要原样输出的人工原行，从 data/orig_rows.toml 加载
  2. research   : pkg.go.dev -> KEP/提案检索 -> 对应版本 CHANGELOG 的自动取证链路

所有叙事列 (排查方法/详细说明) 均由 fetcher 自动从 KEP 抓取并翻译为中文,
不依赖任何版本特定的硬编码知识库, 支持任意未来 k8s 版本。

溯源: lookup() 返回结果中包含 source_en / source_type / source_url / engine,
      供 xlsx 核查列和审计日志使用。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    import tomllib as _toml_loader
except ModuleNotFoundError:
    import tomli as _toml_loader

_SOURCE_MANUAL = "人工原行"
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_toml(name: str) -> dict:
    p = _DATA_DIR / name
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return _toml_loader.load(f)


ORIG_ROWS: dict = _load_toml("orig_rows.toml")
COMPAT_VALS = {"特性默认关闭，无影响", "开关状态不变，无影响"}
ORIG = set(ORIG_ROWS.keys())


def lookup(
    name: str,
    gate_kep: Optional[str] = None,
    gate_desc: Optional[list[str]] = None,
    *,
    version: str = "",
    data_dir: Optional[str | Path] = None,
    offline: bool = False,
) -> dict[str, Optional[str]]:
    """按特性名查知识库, 返回排查方法/参考资料/详细说明/建议开启/补充说明 + 溯源字段。

    ORIG_ROWS 中的人工原行直接返回 (source_type=人工原行)。
    其他特性: 通过 fetcher 在线抓取 KEP README 并翻译为中文。
    所有输出均为中文。

    溯源字段:
      source_en   : 翻译前英文原文 (供核查对照)
      source_type : 来源类型 (KEP README / GitHub Issue / go 注释翻译 / 人工原行)
      source_url  : KEP README 或 GitHub Issue 的 URL
      engine      : 翻译引擎 (Google Translate / MyMemory)
    """
    ref = gate_kep

    if name in ORIG_ROWS:
        o = ORIG_ROWS[name]
        return {
            "排查方法": o.get("排查方法") or None,
            "参考资料": o.get("参考资料") or None,
            "详细说明": o.get("详细说明") or None,
            "建议开启": o.get("建议开启") or None,
            "补充说明": o.get("补充说明") or None,
            "source_en": None,
            "source_type": _SOURCE_MANUAL,
            "source_url": o.get("参考资料"),
            "engine": None,
        }

    排查 = None
    详说 = None
    source_en = None
    source_type = ""
    source_url = ref or ""
    engine = None
    online: dict = {}

    try:
        from .research import collect_feature_evidence
        online = collect_feature_evidence(
            name, kep_url=ref, description=gate_desc or [], version=version,
            data_dir=data_dir, offline=offline,
        )
        排查 = online.get("排查方法")
        详说 = online.get("详细说明")
        source_en = online.get("source_en")
        source_type = online.get("source_type") or ""
        source_url = online.get("source_url") or ref or ""
        engine = online.get("engine")
    except Exception as e:
        from autok8s.common.logging import get_logger
        get_logger("content_store").warning("在线获取 %s 叙事失败: %s", name, e)

    return {
        "排查方法": 排查,
        "参考资料": online.get("参考资料") or ref or source_url or None,
        "详细说明": 详说,
        "建议开启": None,
        "补充说明": None,
        "source_en": source_en,
        "source_type": source_type,
        "source_url": source_url,
        "engine": engine,
    }


def suggest_enable(change_type: str, stage: str, default: bool) -> str:
    """建议开启列: Deprecated->关闭; GA+默认开->开启; Alpha/Beta+默认关->按需; 否则开启。"""
    if stage == "Deprecated":
        return "关闭"
    if stage == "GA":
        return "开启" if default else "关闭"
    return "按需" if not default else "开启"
