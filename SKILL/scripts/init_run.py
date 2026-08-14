#!/usr/bin/env python3
"""Create a portable run directory for Kubernetes release analysis."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def minor(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("version must look like 1.36")
    return int(match.group(1)), int(match.group(2))


def fmt(value: tuple[int, int]) -> str:
    return f"{value[0]}.{value[1]}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_version", type=minor)
    parser.add_argument("--to", dest="to_version", required=True, type=minor)
    parser.add_argument("--from-ref")
    parser.add_argument("--to-ref")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    start = args.from_version or (args.to_version[0], args.to_version[1] - 1)
    end = args.to_version
    if start[0] != end[0] or start > end:
        raise SystemExit("only non-descending minor ranges within one major version are supported")

    versions = [(start[0], item) for item in range(start[1], end[1] + 1)]
    refs = {fmt(item): f"v{fmt(item)}.0" for item in versions}
    if args.from_ref:
        refs[fmt(start)] = args.from_ref
    if args.to_ref:
        refs[fmt(end)] = args.to_ref

    run_dir = Path(args.run_dir).resolve()
    (run_dir / "sources").mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "from_version": fmt(start),
        "to_version": fmt(end),
        "versions": [fmt(item) for item in versions],
        "refs": refs,
        "iteration": 0,
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    analysis = {"version_analysis": [], "feature_changes": []}
    target = run_dir / "analysis.json"
    if not target.exists():
        target.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"initialized {run_dir}")
    print(f"versions: {', '.join(config['versions'])}")


if __name__ == "__main__":
    main()
