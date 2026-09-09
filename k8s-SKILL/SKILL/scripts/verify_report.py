#!/usr/bin/env python3
"""Verify that a generated report is a readable two-sheet XLSX contract."""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def cell_text(cell) -> str:
    return "".join(node.text or "" for node in cell.findall(".//m:t", NS))


def version_key(value: object) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or ""))) or (0,)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    path = Path(args.report).resolve()
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"corrupt ZIP member: {bad}")
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        names = [item.attrib["name"] for item in workbook.findall("m:sheets/m:sheet", NS)]
        if names != ["版本分析", "特性变更"]:
            raise SystemExit(f"unexpected sheets: {names}")
        counts = []
        for number in (1, 2):
            sheet = ET.fromstring(archive.read(f"xl/worksheets/sheet{number}.xml"))
            counts.append(len(sheet.findall("m:sheetData/m:row", NS)))
        version_sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        change_sheet = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        version_rows = version_sheet.findall("m:sheetData/m:row", NS)
        change_rows = change_sheet.findall("m:sheetData/m:row", NS)
        if len(version_rows) < 5 or cell_text(version_rows[1].find("m:c", NS)) != "关键特性分析":
            raise SystemExit("version analysis hierarchy is missing")
        title = cell_text(version_rows[0].find("m:c", NS))
        if "Release Note/ChangeLog解读" not in title:
            raise SystemExit("version analysis title is missing")
        categories = [cell_text(row.find("m:c", NS)) for row in version_rows[3:] if row.find("m:c", NS) is not None]
        versions = set()
        for category in categories:
            if ":" in category or "：" in category:
                versions.add(category.rsplit(":" if ":" in category else "：", 1)[-1])
        title_versions = re.findall(r"v(\d+\.\d+)", title)
        expected_count = 2 if len(set(title_versions)) > 1 else 1
        if len(versions) < expected_count:
            raise SystemExit(f"version analysis does not cover the full range: {sorted(versions)}")
        risk_header_index = next(
            (index for index, row in enumerate(version_rows) if row.find("m:c", NS) is not None and cell_text(row.find("m:c", NS)) == "关键变更风险分析"),
            None,
        )
        if risk_header_index is None or risk_header_index + 2 >= len(version_rows):
            raise SystemExit("version analysis risk section is empty")
        allowed_feature_categories = {"孵化成熟特性", "增强特性", "新增特性"}
        for row in version_rows[3:risk_header_index]:
            cells = row.findall("m:c", NS)
            if not cells:
                continue
            cat = cell_text(cells[0])
            if not cat:
                continue
            prefix = cat.split(":")[0].split("：")[0]
            if prefix not in allowed_feature_categories:
                raise SystemExit(
                    f"version analysis feature category must be one of 孵化成熟特性/增强特性/新增特性, got: {cat}"
                )
        for row in version_rows[risk_header_index + 2:]:
            cells = row.findall("m:c", NS)
            if cells and cell_text(cells[0]) and (len(cells) < 3 or not cell_text(cells[2])):
                raise SystemExit("version analysis contains a risk row without detailed description")
        change_headers = [cell_text(cell) for cell in change_rows[0].findall("m:c", NS)]
        required_headers = {"版本变更阶段", "分析结论", "详细说明", "补充说明"}
        if not required_headers.issubset(change_headers):
            raise SystemExit("feature change headers are incomplete")
        version_stage_pattern = re.compile(r"^v\d+\.\d+->v\d+\.\d+$")
        for row in change_rows[1:]:
            first_cell = cell_text(row.find("m:c", NS))
            if first_cell and not version_stage_pattern.match(first_cell):
                raise SystemExit(f"feature change 版本变更阶段 must be v<X>->v<Y> format, got: {first_cell}")
        if args.run_dir:
            run_dir = Path(args.run_dir).resolve()
            facts = json.loads((run_dir / "machine-facts.json").read_text(encoding="utf-8-sig"))
            expected_changes = len(facts.get("feature_changes", []))
            actual_changes = max(0, len(change_rows) - 1)
            if actual_changes != expected_changes:
                raise SystemExit(f"feature change row count mismatch: report={actual_changes}, facts={expected_changes}")
            catalog_path = run_dir / "release-catalog.json"
            analysis_path = run_dir / "analysis.json"
            if catalog_path.exists() and analysis_path.exists():
                catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
                analysis = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
                catalog_count = sum(len(item.get("features", [])) for item in catalog.get("versions", []))
                omissions = len(analysis.get("catalog_omissions", []))
                actual_features = sum(
                    1 for item in analysis.get("version_analysis", [])
                    if item.get("category") not in ("弃用与移除", "关键变更风险")
                )
                if actual_features + omissions < catalog_count:
                    raise SystemExit(
                        f"version analysis coverage mismatch: report={actual_features}, omissions={omissions}, catalog={catalog_count}"
                    )
                catalog_by_id = {
                    item["catalog_id"]: item
                    for version in catalog.get("versions", [])
                    for group in ("features", "risks")
                    for item in version.get(group, [])
                }
                feature_analysis = [
                    row for row in analysis.get("version_analysis", [])
                    if row.get("category") not in ("弃用与移除", "关键变更风险")
                ]
                risk_analysis = [
                    row for row in analysis.get("version_analysis", [])
                    if row.get("category") in ("弃用与移除", "关键变更风险")
                ]
                _category_order = {"孵化成熟特性": 0, "增强特性": 1, "新增特性": 2}
                def _cat_prefix(cg):
                    for sep in (":", "："):
                        if sep in str(cg):
                            return str(cg).split(sep, 1)[0]
                    return str(cg)
                for row in feature_analysis:
                    prefix = _cat_prefix(row.get("category_group", ""))
                    if prefix not in _category_order:
                        raise SystemExit(
                            f"version analysis category_group must be one of 孵化成熟特性/增强特性/新增特性, got: {row.get('category_group', '')}"
                        )
                feature_analysis.sort(key=lambda row: _category_order.get(_cat_prefix(row.get("category_group", "")), 3))
                feature_analysis.sort(key=lambda row: version_key(catalog_by_id[row["catalog_id"]]["version"]), reverse=True)
                risk_analysis.sort(key=lambda row: version_key(catalog_by_id[row["catalog_id"]]["version"]), reverse=True)
                expected_feature_names = [catalog_by_id[row["catalog_id"]]["name"] for row in feature_analysis]
                # Blank separator rows are omitted from sheetData, so every
                # physical row before the risk section is a feature row.
                actual_feature_names = [cell_text(row.findall("m:c", NS)[1]) for row in version_rows[3:risk_header_index]]
                if actual_feature_names != expected_feature_names:
                    raise SystemExit("version analysis feature names differ from official release-blog catalog")
                expected_risk_names = [catalog_by_id[row["catalog_id"]]["name"] for row in risk_analysis]
                actual_risk_names = [cell_text(row.findall("m:c", NS)[1]) for row in version_rows[risk_header_index + 2:]]
                if actual_risk_names != expected_risk_names:
                    raise SystemExit("version analysis risk names differ from official release-blog catalog")
    print(f"valid report: {path}")
    print(f"sheets={names}; rows_including_headers={counts}")


if __name__ == "__main__":
    main()
