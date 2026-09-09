#!/usr/bin/env python3
"""Emit actionable refinement diagnostics without blocking report generation."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


OFFICIAL_HOSTS = (
    "kubernetes.io/",
    "github.com/kubernetes/",
    "raw.githubusercontent.com/kubernetes/",
    "kep.k8s.io/",
)
ACTION_WORDS = ("检查", "确认", "验证", "查看", "核对", "执行", "对照", "审计")
VAGUE_WORDS = ("全面提升", "显著提升", "大幅提升", "极大改善", "强烈建议", "立即开启")
VALUE_VAGUE_WORDS = ("提升效率", "增强稳定性", "提高性能", "提升体验", "提升安全性")
ALLOWED_CATEGORY_PREFIXES = ("孵化成熟特性", "增强特性", "新增特性")
RECOMMENDATIONS = ("", "开启", "关闭")
READABILITY_FIELDS = ("current_problem", "enhancement", "value_analysis", "conclusion", "details", "notes")
VERSION_TEXT_FIELDS = {"current_problem", "enhancement", "value_analysis", "feature_summary"}


def issue(issues: list[dict], severity: str, item_id: str, field: str, code: str, message: str) -> None:
    issues.append({"severity": severity, "item_id": item_id, "field": field, "code": code, "message": message})


def official(url: str) -> bool:
    return url.startswith("https://") and any(host in url for host in OFFICIAL_HOSTS)


def trusted_version_supplement(url: str, refs: set[str]) -> bool:
    if re.fullmatch(r"https://kep\.k8s\.io/\d+/?", url):
        return True
    if url.startswith("https://kubernetes.io/docs/"):
        return True
    if re.match(r"https://github\.com/kubernetes/enhancements/(?:tree|blob)/[^/]+/keps/", url):
        return True
    return any(
        url.startswith(f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/") and
        ("/pkg/features/kube_features.go" in url or "/CHANGELOG/" in url)
        for ref in refs
    )


def check_readability(issues: list[dict], item_id: str, field: str, value: object) -> None:
    text = str(value or "").strip()
    clauses = [item.strip() for item in re.split(r"[。！？；\n]+", text) if item.strip()]
    if any(len(item) > 150 for item in clauses):
        issue(issues, "warning", item_id, field, "clause_too_long", "拆分超长分句，每句只保留一个主要判断")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    analysis = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8-sig"))
    config_path = run_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {"versions": []}
    facts_path = run_dir / "machine-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8-sig")) if facts_path.exists() else {"feature_changes": []}
    catalog_path = run_dir / "release-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig")) if catalog_path.exists() else {"versions": []}
    fact_ids = {item["id"] for item in facts["feature_changes"]}
    configured_refs = {str(value) for value in config.get("refs", {}).values()}
    issues: list[dict] = []

    for index, row in enumerate(analysis.get("version_analysis", []), 1):
        item_id = f"version:{row.get('version', '?')}:{index}"
        for field in ("feature_name", "value_domain", "value_analysis"):
            if not str(row.get(field, "")).strip():
                issue(issues, "error", item_id, field, "missing_key_text", "关键文本为空")
        if row.get("category") not in ("弃用与移除", "关键变更风险"):
            cg = str(row.get("category_group", ""))
            prefix = cg.split(":")[0].split("：")[0] if cg else ""
            if prefix not in ALLOWED_CATEGORY_PREFIXES:
                issue(issues, "error", item_id, "category_group", "invalid_category",
                      "分类严格限定为孵化成熟特性、增强特性或新增特性")
            for field in ("current_problem", "enhancement"):
                text = str(row.get(field, "")).strip()
                if not text:
                    issue(issues, "error", item_id, field, "missing_structured_summary", "关键特性必须拆分为现状与本特性增强")
                elif len(text) < (80 if field == "current_problem" else 100):
                    issue(issues, "warning", item_id, field, "summary_too_shallow", "补充受影响对象、旧行为或限制、目标版本状态、核心机制和使用边界")
                elif field == "enhancement" and not any(word in text for word in ("边界", "需要", "仍", "仅", "取决于", "不支持", "默认关闭", "默认启用")):
                    issue(issues, "warning", item_id, field, "missing_usage_boundary", "本特性增强需明确默认状态、依赖条件或使用边界")
            va_text = str(row.get("value_analysis", "")).strip()
            if len(va_text) < 70:
                issue(issues, "warning", item_id, "value_analysis", "value_too_shallow", "价值分析需包含直接收益以及采用前提或残余风险")
            if any(word in va_text for word in VALUE_VAGUE_WORDS):
                issue(issues, "warning", item_id, "value_analysis", "value_vague", "价值分析必须清晰简洁、准确明确，禁止使用提升效率/增强稳定性等泛化表述")
        elif not str(row.get("feature_summary", "") or row.get("enhancement", "") or row.get("current_problem", "")).strip():
            issue(issues, "error", item_id, "feature_summary", "missing_risk_description", "风险区必须填写风险详细描述")
        sources = row.get("sources", [])
        if not sources:
            issue(issues, "error", item_id, "sources", "missing_source", "版本分析项缺少官方来源")
        elif any(not official(str(url)) for url in sources):
            issue(issues, "error", item_id, "sources", "non_official_source", "存在非 Kubernetes 官方来源")
        combined = " ".join(str(row.get(field, "")) for field in ("feature_summary", "value_analysis"))
        if any(word in combined for word in VAGUE_WORDS):
            issue(issues, "warning", item_id, "text", "unsupported_praise", "删除无证据的泛化提升或开启建议")
        if len(str(row.get("feature_summary", ""))) > 360:
            issue(issues, "info", item_id, "feature_summary", "too_long", "功能介绍过长，保留问题、机制和对象")
        for field in READABILITY_FIELDS[:3]:
            check_readability(issues, item_id, field, row.get(field, ""))

    seen: set[str] = set()
    for row in analysis.get("feature_changes", []):
        item_id = str(row.get("id", ""))
        if not item_id:
            issue(issues, "error", "feature:unknown", "id", "missing_id", "缺少机器事实关联 ID")
            continue
        seen.add(item_id)
        if item_id not in fact_ids:
            issue(issues, "error", item_id, "id", "orphan_analysis", "该分析项不存在对应机器事实")
        sources = row.get("sources", [])
        if not sources:
            issue(issues, "error", item_id, "sources", "missing_source", "缺少解释兼容性或行为的官方来源")
        elif any(not official(str(url)) for url in sources):
            issue(issues, "error", item_id, "sources", "non_official_source", "存在非 Kubernetes 官方来源")
        compatibility_text = str(row.get("compatibility_analysis", "")).strip()
        method = str(row.get("check_method", ""))
        if not compatibility_text and row.get("status") == "ready" and (len(method) < 18 or not any(word in method for word in ACTION_WORDS)):
            issue(issues, "warning", item_id, "check_method", "not_actionable", "写明检查对象、动作和判断依据")
        for field in ("compatibility_analysis", "conclusion", "details", "notes"):
            text = str(row.get(field, ""))
            if any(word in text for word in VAGUE_WORDS):
                issue(issues, "warning", item_id, field, "unsupported_praise", "删除无证据泛化表述")
        if row.get("status") == "ready" and row.get("compatibility") == "待核实":
            issue(issues, "error", item_id, "compatibility", "status_mismatch", "ready 状态不能仍标待核实")
        if not compatibility_text:
            if sources and all("raw.githubusercontent.com/" in str(url) or "CHANGELOG" in str(url) for url in sources):
                issue(issues, "warning", item_id, "sources", "missing_explanatory_source", "高影响行需补充同项 KEP、发布博客或官方文档，源码只证明机器状态")
            for field in ("conclusion", "details", "notes"):
                if not str(row.get(field, "")).strip():
                    issue(issues, "error", item_id, field, "missing_required_analysis", "兼容分析为空时必须填写该字段")
            if len(str(row.get("details", "")).strip()) < 80:
                issue(issues, "warning", item_id, "details", "details_too_shallow", "详细说明需以功能机制描述为主体，禁止复述升级影响模板话术")
        recommendation = str(row.get("recommendation", "")).strip()
        if recommendation not in RECOMMENDATIONS:
            issue(issues, "error", item_id, "recommendation", "invalid_recommendation", "建议开启只允许开启、关闭或空白")
        if len(str(row.get("notes", "")).strip()) > 90:
            issue(issues, "warning", item_id, "notes", "notes_too_long", "补充说明应压缩为一条清晰边界或后续动作")
        for field in READABILITY_FIELDS[3:]:
            check_readability(issues, item_id, field, row.get(field, ""))

    for missing in sorted(fact_ids - seen):
        issue(issues, "error", missing, "id", "missing_analysis", "机器事实缺少对应分析项")

    for field in ("conclusion", "details", "notes"):
        values = [
            re.sub(r"\s+", "", str(row.get(field, "")))
            for row in analysis.get("feature_changes", [])
            if not str(row.get("compatibility_analysis", "")).strip() and str(row.get(field, "")).strip()
        ]
        repeated = [(value, count) for value, count in Counter(values).items() if count >= 3]
        for value, count in repeated:
            issue(
                issues, "warning", "feature-changes", field, "repeated_template",
                f"{field} 有同一文本重复 {count} 次；按特性机制、影响对象和升级动作分别改写",
            )

    covered_versions = {str(row.get("version", "")) for row in analysis.get("version_analysis", [])}
    for version in config.get("versions", []):
        if str(version) not in covered_versions:
            issue(issues, "error", f"version:{version}", "version", "version_not_covered", "版本分析必须覆盖范围内每个版本")

    # Release-blog names are immutable machine fields. The model may analyze a
    # catalog row, but must never translate, abbreviate, normalize or rename it.
    catalog_items = [item for version in catalog.get("versions", []) for item in version.get("features", [])]
    catalog_risks = [item for version in catalog.get("versions", []) for item in version.get("risks", [])]
    catalog_by_id = {item.get("catalog_id"): item for item in catalog_items + catalog_risks}
    analysis_by_id = {
        row.get("catalog_id"): row
        for row in analysis.get("version_analysis", [])
        if row.get("catalog_id")
    }
    analysis_id_counts = Counter(
        row.get("catalog_id") for row in analysis.get("version_analysis", []) if row.get("catalog_id")
    )
    for catalog_id, count in analysis_id_counts.items():
        if count > 1:
            issue(issues, "error", str(catalog_id), "catalog_id", "duplicate_catalog_id", f"同一正式发行博客目录项重复出现 {count} 次")
    omissions = analysis.get("catalog_omissions", [])
    omission_ids = {
        row.get("catalog_id")
        for row in omissions if str(row.get("reason", "")).strip()
    }
    uncovered = [
        f"v{item.get('version')}:{item.get('name')}"
        for item in catalog_items
        if item.get("catalog_id") not in analysis_by_id and item.get("catalog_id") not in omission_ids
    ]
    if uncovered:
        issue(
            issues, "error", "release-catalog", "version_analysis", "catalog_not_covered",
            f"发布博客目录仍有 {len(uncovered)} 项未写入且无排除理由：{' | '.join(uncovered[:8])}",
        )
    for catalog_id, row in analysis_by_id.items():
        item = catalog_by_id.get(catalog_id)
        if item is None:
            issue(issues, "error", str(catalog_id), "catalog_id", "unknown_catalog_id", "版本分析项不存在对应的正式发行博客目录记录")
            continue
        if row.get("feature_name") != item.get("name"):
            issue(
                issues, "error", str(catalog_id), "feature_name", "release_blog_name_modified",
                f"特性名称必须逐字使用正式发行博客标题：{item.get('name')}",
            )
        if str(row.get("version")) != str(item.get("version")):
            issue(issues, "error", str(catalog_id), "version", "release_blog_version_modified", "版本必须与正式发行博客目录记录一致")
        if row.get("name_source") != "official_release_blog":
            issue(issues, "error", str(catalog_id), "name_source", "invalid_name_source", "特性名称来源必须标记为 official_release_blog")
        expected_primary = str(item.get("source", ""))
        if row.get("primary_source") != expected_primary:
            issue(
                issues, "error", str(catalog_id), "primary_source", "invalid_release_blog_primary",
                f"版本分析主体来源必须是该版本正式发行博客：{expected_primary}",
            )
        supplements = row.get("supplemental_sources", [])
        if not isinstance(supplements, list):
            issue(issues, "error", str(catalog_id), "supplemental_sources", "invalid_supplement_schema", "补充来源必须是列表")
            supplements = []
        supplement_urls = []
        for position, supplement in enumerate(supplements, 1):
            if not isinstance(supplement, dict):
                issue(issues, "error", str(catalog_id), "supplemental_sources", "invalid_supplement_schema", f"第 {position} 个补充来源不是结构化对象")
                continue
            url = str(supplement.get("url", ""))
            supports = supplement.get("supports", [])
            reason = str(supplement.get("reason", "")).strip()
            supplement_urls.append(url)
            if not trusted_version_supplement(url, configured_refs):
                issue(issues, "error", str(catalog_id), "supplemental_sources", "untrusted_version_supplement", f"版本分析补充来源不在允许范围：{url}")
            if not isinstance(supports, list) or not supports or any(field not in VERSION_TEXT_FIELDS for field in supports):
                issue(issues, "error", str(catalog_id), "supplemental_sources", "invalid_supplement_supports", "补充来源必须声明其支撑的版本分析文本字段")
            if len(reason) < 8:
                issue(issues, "error", str(catalog_id), "supplemental_sources", "missing_supplement_reason", "说明正式发行博客缺失了什么信息以及为何需要补充来源")
        expected_sources = [expected_primary] + supplement_urls
        if row.get("sources") != expected_sources:
            issue(
                issues, "error", str(catalog_id), "sources", "version_source_order_mismatch",
                "版本分析 sources 必须依次为正式发行博客主体来源和已声明的补充来源，不得加入其他网址",
            )
    for index, row in enumerate(analysis.get("version_analysis", []), 1):
        if not row.get("catalog_id"):
            issue(issues, "error", f"version:{row.get('version', '?')}:{index}", "catalog_id", "missing_catalog_id", "版本分析项必须绑定正式发行博客 catalog_id")

    catalog_count = len(catalog_items)
    feature_count = sum(
        1 for row in analysis.get("version_analysis", [])
        if row.get("category") not in ("弃用与移除", "关键变更风险")
    )
    if catalog_count and feature_count + len(omission_ids) < catalog_count:
        issue(issues, "error", "release-catalog", "version_analysis", "coverage_count_mismatch", "版本分析条目数低于博客目录覆盖基线")

    normalized = []
    for row in analysis.get("version_analysis", []):
        text = re.sub(r"\s+", "", str(row.get("feature_summary", "")) + str(row.get("value_analysis", "")))
        normalized.append(text)
    duplicates = [value for value, count in Counter(normalized).items() if value and count > 1]
    if duplicates:
        issue(issues, "warning", "version-analysis", "text", "duplicate_rows", f"发现 {len(duplicates)} 组完全重复文本")

    counts = Counter(item["severity"] for item in issues)
    result = {
        "summary": {"error": counts["error"], "warning": counts["warning"], "info": counts["info"]},
        "stop_recommendation": "stop" if not counts["error"] and not counts["warning"] else "refine_targeted_fields",
        "issues": issues,
    }
    (run_dir / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"recommendation: {result['stop_recommendation']}")


if __name__ == "__main__":
    main()
