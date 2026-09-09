"""generator.py — 编排: 解析 go 文件 -> 分析变更 -> 填充叙事 -> 写出 xlsx。"""
from __future__ import annotations

from pathlib import Path

from .analyzer import analyze
from .parser import parse_go_file
from .xlsx_writer import write_workbook


def generate_workbook(
    go_file: str | Path,
    out_path: str | Path,
    sheet_name: str = "特性变更",
    lo: tuple[int, int] = (1, 0),
    hi: tuple[int, int] = (1, 0),
    data_dir: str | Path | None = None,
    offline: bool = False,
    audit_path: str | Path | None = None,
) -> int:
    """生成特性变更 xlsx + 审计日志。

    lo/hi: 版本范围下/上界 (如 (1,31)/(1,36)), 由调用方通过 --range 提供。
    """
    gates = parse_go_file(go_file)
    rows = analyze(gates, lo=lo, hi=hi)
    version = f"{hi[0]}.{hi[1]}"
    write_workbook(
        rows, gates, out_path, sheet_name=sheet_name, version=version,
        data_dir=data_dir, offline=offline, audit_path=audit_path,
    )
    return len(rows)
