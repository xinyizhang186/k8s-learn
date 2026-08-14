#!/usr/bin/env python3
"""Extract a deterministic feature/risk catalog from cached release blogs."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path


FEATURE_SECTIONS = {
    "Spotlight on key updates",
    "Features graduating to Stable",
    "Highlights of features graduating to Stable",
    "New features in Beta",
    "Highlights of features graduating to Beta",
    "New features in Alpha",
    "Highlights of new features in Alpha",
    # Sneak Peek / pre-release blog sections
    "Featured enhancements of Kubernetes v1.37",
    "Breaking changes in Kubernetes v1.37",
}
RISK_SECTIONS = {
    "Deprecations, removals and community updates",
    "Deprecations removals, and community updates",
    "Graduations, deprecations, and removals in 1.32",
    "Graduations, deprecations, and removals in 1.33",
    "Graduations, deprecations, and removals in 1.34",
    "Graduations, deprecations, and removals in 1.35",
    "Graduations, deprecations, and removals in 1.36",
    # Sneak Peek / pre-release blog sections
    "Deprecations and removals for Kubernetes v1.37",
    "Ongoing major changes",
}
STOP_SECTIONS = {"Release notes", "Availability", "Release team", "Release Team"}


class HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.level: int | None = None
        self.buffer: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.items: list[tuple[str, str]] = []
        self.current_h2 = ""
        self.current_h3 = ""
        self.in_li = False
        self.li_buffer: list[str] = []
        self.in_heading = False
        self.paragraphs: list[tuple[str, str]] = []
        self._para_buffer: list[str] = []
        self._para_heading = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("h2", "h3", "h4"):
            if self._para_buffer and self._para_heading:
                text = " ".join(html.unescape("".join(self._para_buffer)).split())
                if text:
                    self.paragraphs.append((self._para_heading, text))
                self._para_buffer = []
            self.level = int(tag[1])
            self.buffer = []
            self.in_heading = True
        elif tag == "li":
            self.in_li = True
            self.li_buffer = []
        elif tag == "p" and not self.in_heading:
            self._para_buffer = []

    def handle_data(self, data: str) -> None:
        if self.level is not None:
            self.buffer.append(data)
        elif self.in_li:
            self.li_buffer.append(data)
        elif not self.in_heading:
            self._para_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.level is not None and tag == f"h{self.level}":
            text = " ".join(html.unescape("".join(self.buffer)).split())
            if text:
                self.headings.append((self.level, text))
                if self.level == 2:
                    self.current_h2 = text
                    self.current_h3 = ""
                elif self.level == 3:
                    self.current_h3 = text
            self.level = None
            self.buffer = []
            self.in_heading = False
            self._para_heading = self.current_h3 or self.current_h2
        elif tag == "li" and self.in_li:
            text = " ".join(html.unescape("".join(self.li_buffer)).split())
            if text:
                self.items.append((self.current_h2 + " / " + self.current_h3, text))
            self.in_li = False
            self.li_buffer = []
        elif tag == "p" and not self.in_heading and self._para_buffer:
            text = " ".join(html.unescape("".join(self._para_buffer)).split())
            if text and self._para_heading:
                self.paragraphs.append((self._para_heading, text))
            self._para_buffer = []


def normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def classify_feature(section: str, heading: str, blog_text: str = "") -> str:
    """Classify a feature into exactly one of three categories.

    Returns only 'mature', 'enhanced', or 'new'. Spotlight features
    without a Stable/Beta/Alpha prefix default to 'mature' (孵化成熟特性).
    For Sneak Peek blogs where headings lack the Stable:/Beta:/Alpha: prefix,
    the paragraph text is also checked for stage keywords.
    """
    prefix = heading.split(":", 1)[0].lower() if ":" in heading else ""
    if section == "Features graduating to Stable" or prefix == "stable":
        return "mature"
    if section == "New features in Beta" or prefix == "beta":
        return "enhanced"
    if section == "New features in Alpha" or prefix == "alpha":
        return "new"
    combined = (heading + " " + blog_text).lower()
    if re.search(r"\bga\b|graduate.*stable|goes.*ga|reach.*ga", combined):
        return "mature"
    if "beta" in combined:
        return "enhanced"
    if "alpha" in combined:
        return "new"
    return "mature"


def catalog_id(version: str, kind: str, name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"release-blog:{version}:{kind}:{digest}"


def category_group(category: str, version: str) -> str:
    prefix = {
        "mature": "孵化成熟特性",
        "enhanced": "增强特性",
        "new": "新增特性",
    }[category]
    return f"{prefix}:{version}"


def extract_kep_list(paragraphs: list[tuple[str, str]], heading: str) -> list[dict]:
    """Extract sub-feature KEP references from blog paragraphs following a heading."""
    kep_pattern = re.compile(r"KEP[s]?[-\s]*(?:#\s*)?(\d+)|#\s*(\d+)", re.I)
    sig_pattern = re.compile(r"SIG\s+[\w/]+\s*(?:and|/)\s*SIG\s+[\w/]+|SIG\s+[\w/]+", re.I)
    sub_features: list[dict] = []
    seen_keps: set[str] = set()
    heading_cf = heading.casefold()
    for para_heading, text in paragraphs:
        para_cf = para_heading.casefold()
        if heading_cf not in para_cf and para_cf not in heading_cf:
            continue
        for match in kep_pattern.finditer(text):
            kep_id = match.group(1) or match.group(2)
            if kep_id and kep_id not in seen_keps:
                seen_keps.add(kep_id)
                sig_match = sig_pattern.search(text)
                sub_features.append({
                    "kep_id": kep_id,
                    "kep_url": f"https://kep.k8s.io/{kep_id}",
                    "sig": sig_match.group(0) if sig_match else "",
                })
    return sub_features


def catalog(payload: str, version: str, url: str) -> dict:
    parser = HeadingParser()
    parser.feed(payload)
    section = ""
    risk_subsection = False
    features: list[dict] = []
    risks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for level, raw in parser.headings:
        heading = normalize_heading(raw)
        if level == 2:
            if heading in STOP_SECTIONS:
                section = ""
            else:
                section = heading
            risk_subsection = False
            continue
        if level not in (3, 4):
            continue
        if level == 3 and heading in RISK_SECTIONS:
            risk_subsection = True
            continue
        if section in FEATURE_SECTIONS and level == 3:
            name = re.sub(r"^(Stable|Beta|Alpha):\s*", "", heading, flags=re.I)
            key = ("feature", name.casefold())
            if key not in seen:
                sub_features = extract_kep_list(parser.paragraphs, name)
                blog_text = ""
                for para_heading, para_text in parser.paragraphs:
                    if name.casefold() in para_heading.casefold() or para_heading.casefold() in name.casefold():
                        blog_text += " " + para_text
                features.append({
                    "version": version,
                    "name": name,
                    "category": classify_feature(section, heading, blog_text),
                    "section": section,
                    "source": url,
                    "sub_features": sub_features,
                    "blog_text": blog_text,
                })
                seen.add(key)
        elif (section in RISK_SECTIONS or risk_subsection) and level in (3, 4) and re.search(
            r"deprecat|remov|retire|final call|no longer|prohibit|restrict|cannot", heading, flags=re.I
        ):
            key = ("risk", heading.casefold())
            if key not in seen:
                blog_text = ""
                heading_cf = heading.casefold()
                for para_heading, para_text in parser.paragraphs:
                    para_cf = para_heading.casefold()
                    if heading_cf in para_cf or para_cf in heading_cf:
                        blog_text = para_text[:2000]
                        break
                if not blog_text:
                    for para_heading, para_text in parser.paragraphs:
                        para_cf = para_heading.casefold()
                        if any(word in para_cf for word in heading_cf.split() if len(word) > 4):
                            blog_text = para_text[:2000]
                            break
                risks.append({"version": version, "name": heading, "section": section, "source": url, "blog_text": blog_text})
                seen.add(key)
    for item in features:
        item["catalog_id"] = catalog_id(version, "feature", item["name"])
        item["name_source"] = "official_release_blog"
    for item in risks:
        item["catalog_id"] = catalog_id(version, "risk", item["name"])
        item["name_source"] = "official_release_blog"
    return {"version": version, "source": url, "features": features, "risks": risks}


def sync_analysis(run_dir: Path, result: dict) -> None:
    path = run_dir / "analysis.json"
    analysis = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    existing = {
        str(row.get("catalog_id")): row
        for row in analysis.get("version_analysis", [])
        if row.get("catalog_id")
    }
    existing_exact = {
        (str(row.get("version")), str(row.get("feature_name")), row.get("category") in ("弃用与移除", "关键变更风险")): row
        for row in analysis.get("version_analysis", [])
    }
    rows = []
    for version in result["versions"]:
        for item in version["features"]:
            row = dict(existing.get(item["catalog_id"]) or existing_exact.get((item["version"], item["name"], False), {}))
            supplemental = row.get("supplemental_sources", [])
            row.update({
                "catalog_id": item["catalog_id"],
                "version": item["version"],
                "category": "关键特性" if item["category"] != "enhanced" else "关键变更",
                "category_group": category_group(item["category"], item["version"]),
                "sub_features": item.get("sub_features", []),
                "feature_name": item["name"],
                "name_source": "official_release_blog",
                "primary_source": item["source"],
                "supplemental_sources": supplemental,
                "sources": [item["source"]] + [entry["url"] for entry in supplemental if entry.get("url")],
                "status": row.get("status", "research"),
            })
            rows.append(row)
        for item in version["risks"]:
            row = dict(existing.get(item["catalog_id"]) or existing_exact.get((item["version"], item["name"], True), {}))
            supplemental = row.get("supplemental_sources", [])
            row.update({
                "catalog_id": item["catalog_id"],
                "version": item["version"],
                "category": "弃用与移除",
                "category_group": f"特性剔除:{item['version']}",
                "feature_name": item["name"],
                "name_source": "official_release_blog",
                "primary_source": item["source"],
                "supplemental_sources": supplemental,
                "sources": [item["source"]] + [entry["url"] for entry in supplemental if entry.get("url")],
                "status": row.get("status", "research"),
            })
            rows.append(row)
    analysis["version_analysis"] = rows
    analysis.setdefault("feature_changes", [])
    analysis.setdefault("catalog_omissions", [])
    path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enrich_sub_features(result: dict, run_dir: Path) -> None:
    """Enrich sub_features with gate descriptions from machine-facts.json."""
    facts_path = run_dir / "machine-facts.json"
    if not facts_path.exists():
        return
    facts = json.loads(facts_path.read_text(encoding="utf-8-sig"))
    kep_to_desc: dict[str, str] = {}
    for change in facts.get("feature_changes", []):
        kep_url = change.get("kep_url", "")
        if kep_url:
            kep_id = kep_url.rstrip("/").rsplit("/", 1)[-1]
            kep_to_desc[kep_id] = change.get("gate_description", "")
    for version in result.get("versions", []):
        for item in version.get("features", []):
            for sub in item.get("sub_features", []):
                kid = sub.get("kep_id", "")
                if kid and kid in kep_to_desc and kep_to_desc[kid]:
                    desc = kep_to_desc[kid]
                    desc = re.sub(r"^(alpha|beta|ga):\s*v[\d.]+\s*", "", desc, flags=re.I).strip()
                    desc = re.sub(r"^(onwer|owner):\s*\S+\s*", "", desc, flags=re.I).strip()
                    desc = re.sub(r"\s*See:\s*https?://\S+", "", desc).strip()
                    if desc and desc.lower() != sub.get("kep_id", "").lower():
                        sub["description"] = desc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8-sig"))
    index = json.loads((run_dir / "source-index.json").read_text(encoding="utf-8-sig"))
    blogs = [item for item in index.get("sources", []) if item.get("type") == "release_blog"]
    by_version: dict[str, dict] = {}
    for item in blogs:
        match = re.search(r"kubernetes-v(\d+)-(\d+)-(release|sneak-peek)", item["url"])
        if not match:
            continue
        version = f"{match.group(1)}.{match.group(2)}"
        payload = (run_dir / item["path"]).read_text(encoding="utf-8", errors="replace")
        by_version[version] = catalog(payload, version, item["url"])
    missing = [version for version in config["versions"] if version not in by_version]
    if missing:
        raise SystemExit(f"missing cached release blogs for: {', '.join(missing)}")
    result = {
        "schema_version": 1,
        "versions": [by_version[version] for version in config["versions"]],
    }
    enrich_sub_features(result, run_dir)
    total_features = sum(len(item["features"]) for item in result["versions"])
    total_risks = sum(len(item["risks"]) for item in result["versions"])
    (run_dir / "release-catalog.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sync_analysis(run_dir, result)
    print(f"cataloged {total_features} release-blog features and {total_risks} risks")


if __name__ == "__main__":
    main()
