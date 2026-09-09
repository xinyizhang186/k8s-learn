#!/usr/bin/env python3
"""Validate this portable skill without external YAML dependencies."""
from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_DIRS = ("references", "examples", "scripts", "assets")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent).resolve()
    skill = root / "SKILL.md"
    if not skill.is_file():
        raise SystemExit("SKILL.md not found")
    text = skill.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\nname:\s*([^\r\n]+)\r?\ndescription:\s*([^\r\n]+)\r?\n---", text)
    if not match:
        raise SystemExit("frontmatter must contain only name and description in that order")
    name, description = match.group(1).strip(), match.group(2).strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise SystemExit(f"invalid skill name: {name}")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        raise SystemExit("invalid description")
    missing = [item for item in REQUIRED_DIRS if not (root / item).is_dir()]
    if missing:
        raise SystemExit(f"missing directories: {', '.join(missing)}")
    absolute_refs = re.findall(r"[A-Za-z]:[\\/]", text)
    if absolute_refs:
        raise SystemExit("SKILL.md contains an absolute Windows path")
    generated = [item for item in root.rglob("*") if item.name == "__pycache__" or item.suffix == ".pyc"]
    if generated:
        raise SystemExit("skill contains generated Python cache files")
    print(f"valid portable skill: {root}")


if __name__ == "__main__":
    main()
