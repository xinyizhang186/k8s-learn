#!/usr/bin/env python3
"""Build a release-event ledger from the target tag and a cross-tag audit."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class State:
    stage: str
    default: bool
    locked: bool


def version_tuple(value: str) -> tuple[int, int]:
    major, minor = value.lstrip("v").split(".")[:2]
    return int(major), int(minor)


def balanced(text: str, start: int, opening: str = "{", closing: str = "}") -> tuple[str, int]:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    raise ValueError("unbalanced Go source block")


def parse_file(path: Path, target_version: str) -> dict[str, State]:
    histories = parse_histories(path)
    target = version_tuple(target_version)
    result: dict[str, State] = {}
    for name, specs in histories.items():
        valid = [item for item in specs if item[0] <= target]
        if valid:
            result[name] = valid[-1][1]
    return result


def parse_histories(path: Path) -> dict[str, list[tuple[tuple[int, int], State, bool]]]:
    source = path.read_text(encoding="utf-8")
    identifiers: dict[str, str] = {}
    declaration = re.compile(
        r"(?m)^\s*([A-Za-z_]\w*)\s+(?:featuregate\.Feature\s*=\s*\"([^\"]+)\"|=\s*featuregate\.Feature\(\"([^\"]+)\"\))"
    )
    for match in declaration.finditer(source):
        identifiers[match.group(1)] = match.group(2) or match.group(3)

    marker = source.find("defaultVersionedKubernetesFeatureGates")
    if marker < 0:
        raise ValueError(f"defaultVersionedKubernetesFeatureGates not found in {path}")
    var_marker = source.find("var defaultVersionedKubernetesFeatureGates", marker)
    if var_marker >= 0:
        marker = var_marker
    block_start = source.find("{", marker)
    body, _ = balanced(source, block_start)
    result: dict[str, list[tuple[tuple[int, int], State, bool]]] = {}
    entry = re.compile(r"(?m)^\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*:\s*\{")
    position = 0
    while True:
        match = entry.search(body, position)
        if not match:
            break
        value_start = body.find("{", match.start())
        value_body, value_end = balanced(body, value_start)
        key = match.group(1).split(".")[-1]
        name = identifiers.get(key, key)
        specs: list[tuple[tuple[int, int], State, bool]] = []
        cursor = 0
        while True:
            item_start = value_body.find("{", cursor)
            if item_start < 0:
                break
            item, item_end = balanced(value_body, item_start)
            version_match = re.search(r'Version:\s*version\.MustParse\("([^"]+)"\)', item)
            default_match = re.search(r"Default:\s*(true|false)", item)
            stage_match = re.search(r"PreRelease:\s*featuregate\.(\w+)", item)
            lock_match = re.search(r"LockToDefault:\s*(true|false)", item)
            if version_match and default_match and stage_match:
                specs.append((
                    version_tuple(version_match.group(1)),
                    State(
                        stage_match.group(1),
                        default_match.group(1) == "true",
                        bool(lock_match and lock_match.group(1) == "true"),
                    ),
                    lock_match is not None,
                ))
            cursor = item_end
        if specs:
            specs.sort(key=lambda item: item[0])
            result[name] = specs
        position = value_end
    if not result:
        raise ValueError(f"no feature-gate histories parsed from {path}")
    return result


def parse_gate_descriptions(path: Path) -> dict[str, dict]:
    source = path.read_text(encoding="utf-8")
    declaration = re.compile(
        r"(?m)^(?P<indent>\s*)(?P<var>[A-Za-z_]\w*)\s+featuregate\.Feature\s*=\s*\"(?P<name>[^\"]+)\""
    )
    descriptions: dict[str, dict] = {}
    for match in declaration.finditer(source):
        var_name = match.group("var")
        gate_name = match.group("name")
        decl_line_start = source.rfind("\n", 0, match.start()) + 1
        lines_before = source[:decl_line_start].split("\n")
        comment_lines: list[str] = []
        for line in reversed(lines_before):
            stripped = line.strip()
            if stripped.startswith("//"):
                comment_lines.insert(0, stripped[2:].strip())
            elif stripped == "":
                if comment_lines:
                    break
                continue
            else:
                break
        kep_url = ""
        description_parts: list[str] = []
        for line in comment_lines:
            kep_match = re.match(r"kep:\s*(https?://\S+)", line, re.I)
            if kep_match:
                kep_url = kep_match.group(1).replace("http://", "https://")
                continue
            if line.startswith("owner:") or line.startswith("owner "):
                continue
            if line:
                description_parts.append(line)
        description = " ".join(description_parts).strip()
        if description.lower() == gate_name.lower():
            description = ""
        descriptions[gate_name] = {
            "kep_url": kep_url,
            "description": description,
        }
    return descriptions


def state_dict(state: State | None) -> dict | None:
    return asdict(state) if state else None


def arrow(left: object | None, right: object | None) -> str:
    def value(item: object | None) -> str:
        if item is None:
            return ""
        if isinstance(item, bool):
            return str(item).lower()
        return str(item)
    a, b = value(left), value(right)
    return f"->{b}" if a == b or not a else f"{a}->{b}"


def release_events(
    histories: dict[str, list[tuple[tuple[int, int], State, bool]]],
    start: tuple[int, int],
    end: tuple[int, int],
    from_version: str,
    to_version: str,
) -> list[dict]:
    """Return one row per gate with a versioned spec inside the inclusive range."""
    changes: list[dict] = []
    for name in sorted(histories):
        specs = histories[name]
        in_range = [item for item in specs if start <= item[0] <= end]
        if not in_range:
            continue
        prior = [item for item in specs if item[0] < start]
        before = prior[-1][1] if prior else None
        after = in_range[-1][1]
        added = start <= specs[0][0] <= end
        deprecated = any(item[1].stage == "Deprecated" for item in in_range)
        change_type = "Added" if added else "Deprecated" if deprecated else "Changed"
        display_start = before or in_range[0][1]
        explicit_locks = [item[1].locked for item in in_range if item[2]]
        lock_change = ""
        if explicit_locks:
            lock_change = f"->{'true' if any(explicit_locks) else 'false'}"

        if added:
            changed_default = any(
                in_range[index - 1][1].default != in_range[index][1].default
                for index in range(1, len(in_range))
            )
            compatible = not (changed_default or after.default)
        else:
            baseline = before.default if before else in_range[0][1].default
            compatible = baseline == in_range[0][1].default and all(
                in_range[index - 1][1].default == in_range[index][1].default
                for index in range(1, len(in_range))
            )

        kinds = ["范围内版本化规格"]
        if added:
            kinds.append("新增")
        else:
            if display_start.stage != after.stage:
                kinds.append("阶段变化")
            if display_start.default != after.default:
                kinds.append("默认值变化")
        if lock_change:
            kinds.append("锁定变化")
        changes.append({
            "id": f"{from_version}-to-{to_version}:{name}",
            "from_version": from_version,
            "to_version": to_version,
            "prior_version": f"{prior[-1][0][0]}.{prior[-1][0][1]}" if prior else f"{in_range[0][0][0]}.{in_range[0][0][1]}",
            "feature_name": name,
            "change_type": change_type,
            "change_types": kinds,
            "before": state_dict(before),
            "after": state_dict(after),
            "stage_change": arrow(display_start.stage, after.stage),
            "default_change": arrow(display_start.default, after.default),
            "lock_change": lock_change,
            "compatible": compatible,
            "version_changes": [
                {"version": f"{item[0][0]}.{item[0][1]}", **asdict(item[1])}
                for item in in_range
            ],
        })
    return changes


def endpoint_differences(old: dict[str, State], new: dict[str, State], old_version: str, new_version: str) -> list[dict]:
    """Keep cross-tag effective-state differences for audit, not workbook rows."""
    rows: list[dict] = []
    for name in sorted(set(old) | set(new)):
        before, after = old.get(name), new.get(name)
        if before == after:
            continue
        rows.append({
            "id": f"{old_version}-to-{new_version}:{name}",
            "feature_name": name,
            "before": state_dict(before),
            "after": state_dict(after),
        })
    return rows


def source_path(run_dir: Path, index: dict, version: str) -> Path:
    needle = f"kube_features-{version}-"
    matches = [item for item in index["sources"] if item["type"] == "kube_features" and needle in item["path"]]
    if len(matches) != 1:
        raise ValueError(f"expected one kube_features source for {version}, found {len(matches)}")
    main_path = run_dir / matches[0]["path"]
    extra_needle = f"versioned_kube_features-{version}-"
    extras = [item for item in index["sources"] if item["type"] == "kube_features_extra" and extra_needle in item["path"]]
    if extras:
        extra_path = run_dir / extras[0]["path"]
        combined = main_path.read_text(encoding="utf-8") + "\n\n" + extra_path.read_text(encoding="utf-8")
        merged = main_path.parent / f"merged-{main_path.name}"
        merged.write_text(combined, encoding="utf-8")
        return merged
    return main_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8-sig"))
    index = json.loads((run_dir / "source-index.json").read_text(encoding="utf-8-sig"))
    versions = config["versions"]
    states = {version: parse_file(source_path(run_dir, index, version), version) for version in versions}
    target_path = source_path(run_dir, index, versions[-1])
    histories = parse_histories(target_path)
    gate_meta = parse_gate_descriptions(target_path)
    changes = release_events(
        histories, version_tuple(versions[0]), version_tuple(versions[-1]), versions[0], versions[-1]
    )
    for change in changes:
        meta = gate_meta.get(change["feature_name"], {})
        change["gate_description"] = meta.get("description", "")
        change["kep_url"] = meta.get("kep_url", "")
    audits: list[dict] = []
    for old_version, new_version in zip(versions, versions[1:]):
        audits.extend(endpoint_differences(states[old_version], states[new_version], old_version, new_version))

    facts = {
        "schema_version": 2,
        "coverage_model": "target-tag-inclusive-versioned-events",
        "versions": versions,
        "feature_changes": changes,
        "endpoint_audit": audits,
    }
    (run_dir / "machine-facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    analysis_path = run_dir / "analysis.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8-sig")) if analysis_path.exists() else {}
    existing = {item.get("id"): item for item in analysis.get("feature_changes", [])}
    rows = []
    for fact in changes:
        row = existing.get(fact["id"], {"id": fact["id"]})
        row.setdefault("compatibility", fact["compatible"])
        row.setdefault("compatibility_analysis", "")
        row.setdefault("conclusion", "")
        row.setdefault("check_method", "")
        row.setdefault("sources", [])
        row.setdefault("details", "")
        row.setdefault("recommendation", "待核实")
        row.setdefault("notes", "")
        row.setdefault("status", "research")
        rows.append(row)
    analysis["version_analysis"] = analysis.get("version_analysis", [])
    analysis["feature_changes"] = rows
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"parsed {len(histories)} target-tag feature-gate histories")
    print(f"found {len(changes)} in-range release events")
    print(f"recorded {len(audits)} cross-tag endpoint audit differences")


if __name__ == "__main__":
    main()
