#!/usr/bin/env python3
"""Build the reference-aligned two-sheet XLSX with the Python standard library."""
from __future__ import annotations

import argparse
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


VERSION_HEADERS = ["分类", "特性名称", "特性功能介绍", "特性价值领域", "特性功能价值分析"]
RISK_HEADERS = ["分类", "变更名称", "风险详细描述", "风险涉及领域", "技术or商业影响"]
CHANGE_HEADERS = [
    "版本变更阶段", "变更类型", "特性名称", "特性阶段变化", "默认值变化", "默认值锁定",
    "是否兼容", "兼容分析", "分析结论", "排查方法", "参考资料", "详细说明", "建议开启？", "补充说明",
]


def column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def inline_cell(ref: str, value: object, style: int) -> str:
    text = "" if value is None else str(value)
    preserve = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t{preserve}>{escape(text)}</t></is></c>'


def bool_cell(ref: str, value: bool, style: int) -> str:
    return f'<c r="{ref}" s="{style}" t="b"><v>{1 if value else 0}</v></c>'


def rich_cell(ref: str, runs: list[tuple[str, bool]], style: int) -> str:
    pieces = []
    for text, bold in runs:
        properties = '<rPr><rFont val="微软雅黑"/><family val="2"/><charset val="134"/><sz val="12"/>'
        if bold:
            properties += "<b/>"
        properties += "</rPr>"
        preserve = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
        pieces.append(f'<r>{properties}<t{preserve}>{escape(text)}</t></r>')
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is>{"".join(pieces)}</is></c>'


def version_key(value: object) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts) or (0,)


def row_height(values: list[object], widths: list[float], minimum: float = 42, maximum: float = 180) -> float:
    lines = 1
    for value, width in zip(values, widths):
        text = "" if value is None else str(value)
        explicit_lines = text.splitlines() or [""]
        estimated = sum(
            max(1, math.ceil(sum(2 if "\u4e00" <= char <= "\u9fff" else 1 for char in line) / max(width * 0.78, 1)))
            for line in explicit_lines
        )
        lines = max(lines, estimated)
    return min(maximum, max(minimum, 14.4 * lines + 10))


def catalog_index(catalog: dict) -> dict[str, dict]:
    return {
        item["catalog_id"]: item
        for version in catalog.get("versions", [])
        for group in ("features", "risks")
        for item in version.get(group, [])
    }


def _category_prefix(category_group: str) -> str:
    for sep in (":", "："):
        if sep in category_group:
            return category_group.split(sep, 1)[0]
    return category_group


def version_layout(analysis: dict, catalog: dict, config: dict, widths: list[float]) -> tuple[str, int]:
    start = config["from_version"]
    end = config["to_version"]
    official = catalog_index(catalog)
    features = []
    risks = []
    for item in analysis.get("version_analysis", []):
        catalog_id = str(item.get("catalog_id", ""))
        if catalog_id not in official:
            raise ValueError(f"version analysis row has no official release-blog catalog entry: {catalog_id or '<missing>'}")
        item = dict(item)
        item["feature_name"] = official[catalog_id]["name"]
        item["version"] = official[catalog_id]["version"]
        if item.get("category") in ("弃用与移除", "关键变更风险"):
            risks.append(item)
        else:
            features.append(item)

    category_order = {"孵化成熟特性": 0, "增强特性": 1, "新增特性": 2}
    features.sort(key=lambda item: (
        category_order.get(_category_prefix(item.get("category_group", "")), 3),
    ))
    features.sort(key=lambda item: version_key(item.get("version")), reverse=True)
    risks.sort(key=lambda item: version_key(item.get("version")), reverse=True)

    rows: list[str] = []
    merges = ["A1:E1", "A2:E2"]
    title = f"kubernetes v{start}-v{end} Release Note/ChangeLog解读"
    rows.append(f'<row r="1" ht="22" customHeight="1">{inline_cell("A1", title, 1)}</row>')
    rows.append(f'<row r="2" ht="30" customHeight="1">{inline_cell("A2", "关键特性分析", 2)}</row>')
    rows.append('<row r="3" ht="16" customHeight="1">' + "".join(
        inline_cell(f"{column_name(index)}3", value, 3) for index, value in enumerate(VERSION_HEADERS, 1)
    ) + "</row>")

    row_index = 4
    for item in features:
        category = item.get("category_group") or f"孵化成熟特性:{item.get('version', end)}"
        problem = item.get("current_problem", "")
        enhancement = item.get("enhancement", "") or item.get("feature_summary", "")
        summary_plain = f"现状：{problem}\n本特性增强：{enhancement}"
        values = [category, item.get("feature_name", ""), summary_plain, item.get("value_domain", ""), item.get("value_analysis", "")]
        cells = [
            inline_cell(f"A{row_index}", values[0], 5),
            inline_cell(f"B{row_index}", values[1], 5),
            rich_cell(f"C{row_index}", [("现状：", True), (problem + "\n", False), ("本特性增强：", True), (enhancement, False)], 5),
            inline_cell(f"D{row_index}", values[3], 5),
            inline_cell(f"E{row_index}", values[4], 5),
        ]
        rows.append(f'<row r="{row_index}" ht="{row_height(values, widths, 76, 260)}" customHeight="1">{"".join(cells)}</row>')
        row_index += 1

    row_index += 1
    risk_section = row_index
    merges.append(f"A{risk_section}:E{risk_section}")
    rows.append(f'<row r="{row_index}" ht="30" customHeight="1">{inline_cell(f"A{row_index}", "关键变更风险分析", 10)}</row>')
    row_index += 1
    rows.append(f'<row r="{row_index}" ht="27" customHeight="1">' + "".join(
        inline_cell(f"{column_name(index)}{row_index}", value, 6) for index, value in enumerate(RISK_HEADERS, 1)
    ) + "</row>")
    row_index += 1
    for item in risks:
        risk_description = item.get("feature_summary", "") or item.get("enhancement", "") or item.get("current_problem", "")
        values = [
            item.get("category_group") or f"特性剔除:{item.get('version', end)}",
            item.get("feature_name", ""), risk_description, item.get("value_domain", ""), item.get("value_analysis", ""),
        ]
        rows.append(f'<row r="{row_index}" ht="{row_height(values, widths, 42, 140)}" customHeight="1">' + "".join(
            inline_cell(f"{column_name(index)}{row_index}", value, 7) for index, value in enumerate(values, 1)
        ) + "</row>")
        row_index += 1

    last = max(row_index - 1, 3)
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    merge_xml = f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{item}"/>' for item in merges) + "</mergeCells>"
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<dimension ref="A1:E{last}"/><sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews>
<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols><sheetData>{''.join(rows)}</sheetData>{merge_xml}
<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/></worksheet>'''
    return xml, last


def compact_state(before: dict | None, after: dict | None, field: str) -> str:
    def value(state: dict | None) -> str:
        if state is None:
            return ""
        raw = state.get(field)
        if isinstance(raw, bool):
            return str(raw).lower()
        return str(raw)
    left, right = value(before), value(after)
    if field == "locked" and not left and right == "false":
        return ""
    if field == "locked" and left == right == "false":
        return ""
    if left == right:
        return f"->{right}" if right else ""
    return f"{left}->{right}"


def display_change_type(before: dict | None, after: dict | None) -> str:
    if after is None:
        return "Removed"
    if after.get("stage") == "Deprecated":
        return "Deprecated"
    if before is None:
        return "Added"
    return "Changed"


def compatible(before: dict | None, after: dict | None) -> bool:
    if after is None:
        return False
    if after.get("stage") == "Deprecated" and (before is None or before.get("stage") != "Deprecated"):
        return False
    if before is None:
        return not after.get("default", False)
    if before.get("default") != after.get("default"):
        return False
    return True


def direct_source(values: list[str]) -> str:
    for value in values:
        if "kep.k8s.io/" in value:
            return value.replace("http://", "https://")
    for value in values:
        if "kubernetes.io/" in value and "raw.githubusercontent.com" not in value:
            return value
    for value in values:
        if "CHANGELOG" in value:
            return value
    return values[0] if values else ""


def version_range_label(prior_version: str, to_version: str) -> str:
    return f"v{prior_version}->v{to_version}"


def change_rows(facts: dict, analysis: dict) -> list[list[object]]:
    by_id = {item.get("id"): item for item in analysis.get("feature_changes", [])}
    rows = []
    for fact in facts.get("feature_changes", []):
        text = by_id.get(fact["id"], {})
        before, after = fact.get("before"), fact.get("after")
        safe = bool(fact.get("compatible", compatible(before, after)))
        default_off = after is not None and not after.get("default", False)
        no_impact = "特性默认关闭，无影响" if default_off else "开关状态不变，无影响"
        if safe:
            compat_text = no_impact
            conclusion = check = source = details = recommendation = notes = ""
        else:
            compat_text = ""
            conclusion = text.get("conclusion", "")
            check = text.get("check_method", "")
            source = direct_source(text.get("sources", []))
            details = text.get("details", "")
            if after is None or (after and after.get("stage") == "Deprecated"):
                recommendation = "关闭"
            elif (before is None and after and after.get("default")) or (before and after and not before.get("default") and after.get("default")):
                recommendation = "开启"
            else:
                recommendation = ""
            notes = str(text.get("notes", "")).strip()
            if len(notes) > 90:
                notes = notes.split("。", 1)[0].strip() + "。"
        rows.append([
            version_range_label(fact.get("prior_version", fact["from_version"]), fact["to_version"]), fact.get("change_type") or display_change_type(before, after), fact["feature_name"],
            fact.get("stage_change") or compact_state(before, after, "stage"),
            fact.get("default_change") or compact_state(before, after, "default"),
            fact.get("lock_change") or compact_state(before, after, "locked"),
            safe, compat_text, conclusion, check, source, details, recommendation, notes,
        ])
    return rows


def change_layout(rows_data: list[list[object]], widths: list[float]) -> str:
    rows = ['<row r="1" ht="25" customHeight="1">' + "".join(
        inline_cell(f"{column_name(index)}1", value, 8) for index, value in enumerate(CHANGE_HEADERS, 1)
    ) + "</row>"]
    for row_index, values in enumerate(rows_data, 2):
        cells = []
        for index, value in enumerate(values, 1):
            ref = f"{column_name(index)}{row_index}"
            cells.append(bool_cell(ref, value, 9) if isinstance(value, bool) else inline_cell(ref, value, 9))
        rows.append(f'<row r="{row_index}" ht="{row_height(values, widths, 28, 92)}" customHeight="1">{"".join(cells)}</row>')
    last = max(len(rows_data) + 1, 1)
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:N{last}"/>
<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols><sheetData>{''.join(rows)}</sheetData>
<autoFilter ref="A1:N{last}"/><pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/></worksheet>'''


def styles(style: dict) -> str:
    change_header = style.get("change_header_fill", "24566F")
    section_theme = style.get("section_theme", 9)
    section_tint = style.get("section_tint", 0.7999816888943144)
    header_theme = style.get("header_theme", 3)
    header_tint = style.get("header_tint", 0.7999816888943144)
    risk_header = style.get("risk_header_fill", "D9E1F2")
    border = style.get("border", "A9B8C3")
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="5"><font><sz val="11"/><name val="微软雅黑"/></font><font><b/><sz val="16"/><name val="微软雅黑"/><color rgb="FF000000"/></font><font><b/><sz val="14"/><name val="微软雅黑"/><color rgb="FF000000"/></font><font><b/><sz val="12"/><name val="微软雅黑"/><color rgb="FF000000"/></font><font><b/><sz val="11"/><name val="微软雅黑"/><color rgb="FFFFFFFF"/></font></fonts>
<fills count="7"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor theme="{section_theme}" tint="{section_tint}"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor theme="{header_theme}" tint="{header_tint}"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FF{change_header}"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FF{risk_header}"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FF{border}"/></left><right style="thin"><color rgb="FF{border}"/></right><top style="thin"><color rgb="FF{border}"/></top><bottom style="thin"><color rgb="FF{border}"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="3" fillId="6" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="4" fillId="5" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles><dxfs count="0"/><tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>'''


def write_xlsx(output: Path, analysis: dict, facts: dict, catalog: dict, config: dict, style: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    version_xml, _ = version_layout(analysis, catalog, config, style["version_analysis_widths"])
    changes = change_rows(facts, analysis)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView/></bookViews><sheets><sheet name="版本分析" sheetId="1" r:id="rId1"/><sheet name="特性变更" sheetId="2" r:id="rId2"/></sheets><calcPr calcId="191029"/></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": version_xml,
        "xl/worksheets/sheet2.xml": change_layout(changes, style["feature_changes_widths"]),
        "xl/styles.xml": styles(style),
        "docProps/core.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Kubernetes 版本分析</dc:title><dc:creator>k8s-release-xlsx</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created></cp:coreProperties>',
        "docProps/app.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>k8s-release-xlsx</Application></Properties>',
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    load = lambda name: json.loads((run_dir / name).read_text(encoding="utf-8-sig"))
    analysis, facts, catalog, config = load("analysis.json"), load("machine-facts.json"), load("release-catalog.json"), load("config.json")
    style = json.loads((Path(__file__).resolve().parent.parent / "assets" / "report-style.json").read_text(encoding="utf-8-sig"))
    output = Path(args.output).resolve()
    write_xlsx(output, analysis, facts, catalog, config, style)
    print(f"wrote {output}")
    print(f"rows: version_analysis={len(analysis.get('version_analysis', []))}, feature_changes={len(facts.get('feature_changes', []))}")


if __name__ == "__main__":
    main()
