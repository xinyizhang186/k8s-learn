"""analyzer.py — 从解析后的特性门推导 "特性变更" 表的确定性行.

范围逻辑 (--range LO HI 由调用方提供):

  对每个特性门, specs 按版本升序:
    ir     = specs 中版本落在 [LO, HI] 内的条目
    before = 版本 < LO 的最后一条 (范围前状态); 无则 None
    first  = specs[0] (最早条目)

  纳入: ir 非空 (在范围内发生过变更)

  变更类型:
    Added      if first.version 在 [LO, HI] 内   (范围内首次引入)
    Deprecated elif ir 中任一条 stage=="Deprecated"
    Changed    otherwise

  特性阶段变化 (净过渡, before -> end):
    start = before or ir[0]; end = ir[-1]
    start.stage==end.stage -> "->end.stage"; 否则 "start.stage->end.stage"

  默认值变化 (净过渡):
    start.default==end.default -> "->after"; 否则 "before->after"

  默认值锁定: ir 中任一条 lock==True -> "->true"; 否则留空

  是否兼容 / 兼容分析:
    Added: 范围内默认值是否变化 或 末值默认开 -> 不兼容; 否则兼容 "特性默认关闭，无影响"
    其他: before.default != ir[0].default 或 范围内默认值变化 -> 不兼容;
          否则兼容: 末值默认关 -> "特性默认关闭，无影响"; 末值默认开 -> "开关状态不变，无影响"

  兼容分析非空时 (兼容), 排查方法/参考资料/详细说明/建议开启/补充说明/英文原文/内容来源 均留空。

  版本变更信息: 保存范围内每个版本的阶段和默认值，避免把版本信息
  从净阶段变化字符串中反推。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .parser import FeatureGate, Spec


@dataclass
class FeatureChange:
    change_type: str
    name: str
    stage_change: str
    default_change: str
    lock_change: Optional[str]
    compatible: bool
    compat_analysis: Optional[str]
    version_changes: str = ""


def _vt(v: str) -> tuple[int, int]:
    parts = v.split(".")
    return (int(parts[0]), int(parts[1]))


def _b(v: bool) -> str:
    return "true" if v else "false"


def analyze_one(gate: FeatureGate, lo: tuple[int, int], hi: tuple[int, int]) -> Optional[FeatureChange]:
    es = gate.specs
    ir = [e for e in es if lo <= _vt(e.version) <= hi]
    if not ir:
        return None
    before_list = [e for e in es if _vt(e.version) < lo]
    before = before_list[-1] if before_list else None
    first = es[0]

    range_versions = set()
    v = lo
    while v <= hi:
        range_versions.add(v)
        v = (v[0], v[1] + 1)
    is_added = _vt(first.version) in range_versions
    is_dep = any(e.stage == "Deprecated" for e in ir)
    if is_added:
        ctype = "Added"
    elif is_dep:
        ctype = "Deprecated"
    else:
        ctype = "Changed"

    st_start = before if before else ir[0]
    st_end = ir[-1]
    if st_start.stage == st_end.stage:
        stage_change = f"->{st_end.stage}"
    else:
        stage_change = f"{st_start.stage}->{st_end.stage}"

    d_s = _b(st_start.default)
    d_e = _b(st_end.default)
    if d_s == d_e:
        default_change = f"->{d_e}"
    else:
        default_change = f"{d_s}->{d_e}"

    locks = [e.lock for e in ir if e.lock is not None]
    if locks:
        lock_change = f"->{('true' if any(locks) else 'false')}"
    else:
        lock_change = None

    if ctype == "Added":
        changed_within = any(ir[i].default != ir[i - 1].default for i in range(1, len(ir)))
        compatible = not (changed_within or ir[-1].default)
        compat_analysis = "特性默认关闭，无影响" if compatible else None
    else:
        b = before.default if before else ir[0].default
        changed = (b != ir[0].default) or any(
            ir[i].default != ir[i - 1].default for i in range(1, len(ir))
        )
        compatible = not changed
        if compatible:
            compat_analysis = "特性默认关闭，无影响" if not ir[-1].default else "开关状态不变，无影响"
        else:
            compat_analysis = None

    version_changes = "；".join(
        f"v{entry.version}（{entry.stage}，默认{'开启' if entry.default else '关闭'}）"
        for entry in ir
    )
    if ctype != "Added" and before:
        before_str = f"v{before.version}（{before.stage}，默认{'开启' if before.default else '关闭'}）"
        version_changes = f"{version_changes} ← {before_str}"

    return FeatureChange(
        change_type=ctype,
        name=gate.name,
        stage_change=stage_change,
        default_change=default_change,
        lock_change=lock_change,
        compatible=compatible,
        compat_analysis=compat_analysis,
        version_changes=version_changes,
    )


def analyze(
    gates: dict[str, FeatureGate],
    lo: tuple[int, int],
    hi: tuple[int, int],
) -> list[FeatureChange]:
    """对全部特性门分析, 返回按特性门字符串值 (区分大小写 ASCII) 升序的变更列表。

    排序键为特性门的字符串值: 带包前缀的取最后一段 (如 genericfeatures.Foo -> Foo),
    普通键用 const 字符串值。大写字母 (A-Z) 排在小写字母 (a-z) 之前, 与 go 源码
    的字母序约定一致。

    lo/hi: 版本范围下/上界 (如 (1,31)/(1,36)), 由调用方通过 --range 提供。
    防御性: lo>hi 时返回空列表 (analyze_one 也各自防御)。
    """
    if lo > hi:
        return []
    ordered = sorted(gates.values(), key=lambda g: g.name)
    rows: list[FeatureChange] = []
    for gate in ordered:
        row = analyze_one(gate, lo, hi)
        if row is not None:
            rows.append(row)
    return rows
