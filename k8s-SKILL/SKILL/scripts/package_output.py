#!/usr/bin/env python3
"""Package the verified XLSX with its official references and fixed-ref sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


OFFICIAL_HOSTS = (
    "kubernetes.io/",
    "github.com/kubernetes/",
    "raw.githubusercontent.com/kubernetes/",
    "kep.k8s.io/",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official(url: str) -> bool:
    return url.startswith("https://") and any(host in url for host in OFFICIAL_HOSTS)


def safe_ref(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise SystemExit(f"unsafe Kubernetes ref for output path: {value}")
    return value


def contained_file(run_dir: Path, relative: str) -> Path:
    path = (run_dir / relative).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise SystemExit(f"source path escapes run directory: {relative}") from exc
    if not path.is_file():
        raise SystemExit(f"cached source not found: {path}")
    return path


def collect_references(index: dict, analysis: dict, catalog: dict) -> list[dict]:
    by_url: dict[str, dict] = {}
    for item in index.get("sources", []):
        url = str(item.get("url", ""))
        if not official(url):
            raise SystemExit(f"non-official URL in source index: {url}")
        by_url[url] = {
            "type": str(item.get("type", "official_source")),
            "url": url,
            "sha256": str(item.get("sha256", "")),
        }
    analysis_urls = {
        str(url)
        for row in analysis.get("feature_changes", [])
        for url in row.get("sources", [])
    } | {
        str(row.get("primary_source", ""))
        for row in analysis.get("version_analysis", [])
    } | {
        str(entry.get("url", ""))
        for row in analysis.get("version_analysis", [])
        for entry in row.get("supplemental_sources", [])
    }
    catalog_urls = {
        str(item.get("source", ""))
        for version in catalog.get("versions", [])
        for group in ("features", "risks")
        for item in version.get(group, [])
    }
    for url in sorted(analysis_urls | catalog_urls):
        if not url:
            continue
        if not official(url):
            raise SystemExit(f"non-official analysis reference: {url}")
        by_url.setdefault(url, {"type": "analysis_reference", "url": url, "sha256": ""})
    return sorted(by_url.values(), key=lambda item: (item["type"], item["url"]))


def link_label(item: dict) -> str:
    url = item["url"]
    if item["type"] == "changelog":
        match = re.search(r"CHANGELOG-(\d+\.\d+)\.md", url)
        return f"Kubernetes v{match.group(1)} CHANGELOG" if match else "Kubernetes CHANGELOG"
    if re.fullmatch(r"https://kep\.k8s\.io/\d+/?", url):
        return f"KEP #{url.rstrip('/').rsplit('/', 1)[-1]}"
    if url.startswith("https://kubernetes.io/docs/"):
        return "Kubernetes 官方文档"
    return url.rstrip("/").rsplit("/", 1)[-1] or url


def markdown(config: dict, report_name: str, source_rows: list[dict], references: list[dict]) -> str:
    release_blogs = [item for item in references if item["type"] == "release_blog"]
    changelogs = [item for item in references if item["type"] == "changelog"]
    fixed_urls = {item["url"] for item in source_rows}
    supplemental = [
        item for item in references
        if item["url"] not in fixed_urls and item["type"] not in ("release_blog", "changelog")
    ]
    blog_by_version = {}
    for version in config["versions"]:
        markers = [
            f"kubernetes-v{version.replace('.', '-')}-release",
            f"kubernetes-v{version.replace('.', '-')}-sneak-peek",
        ]
        matches = [item for item in release_blogs if any(m in item["url"] for m in markers)]
        if len(matches) != 1:
            raise SystemExit(f"expected one release blog for {version}, found {len(matches)}")
        blog_by_version[version] = matches[0]

    lines = [
        "# Kubernetes 版本分析参考资料",
        "",
        f"> 报告：**{report_name}**  ",
        f"> 范围：**v{config['from_version']} → v{config['to_version']}**  ",
        "> 版本分析以对应版本的正式发行博客为主体；仅在博客信息不足时补充同项 KEP、官方文档或固定 Tag 资料。",
        "",
        "## 核心发行博客",
        "",
    ]
    for version in config["versions"]:
        lines.append(f"- **Kubernetes v{version}**：[正式发行博客]({blog_by_version[version]['url']})")
    lines.extend([
        "",
        "这些页面决定\u201c版本分析\u201d的条目名称、版本归属和主体叙述。",
        "",
        "## 版本 CHANGELOG",
        "",
    ])
    for item in changelogs:
        lines.append(f"- [{link_label(item)}]({item['url']})")
    lines.extend(["", "## 固定 Tag 源码", ""])
    for item in source_rows:
        local = item["local"].removeprefix("data/")
        lines.extend([
            f"### Kubernetes v{item['version']} · `{item['ref']}`",
            "",
            f"- [在线查看 `pkg/features/kube_features.go`]({item['url']})",
            f"- [打开本地副本](./{local})",
            "",
            "<details>",
            "<summary>校验信息</summary>",
            "",
            f"- SHA-256：`{item['sha256']}`",
            f"- 本地路径：`./{local}`",
            "",
            "</details>",
            "",
        ])
    lines.extend([
        "## 来源说明",
        "",
        "- FeatureGate 阶段、默认值和锁定状态只以固定 Tag 源码为准。",
        "- 搜索结果仅用于发现候选页面，不作为事实来源。",
        "- 不收录第三方博客、聚合页或人工样表。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--report", required=True, help="verified candidate XLSX")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    report = Path(args.report).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not report.is_file() or report.suffix.lower() != ".xlsx":
        raise SystemExit(f"verified XLSX not found: {report}")

    config = load_json(run_dir / "config.json")
    index = load_json(run_dir / "source-index.json")
    analysis = load_json(run_dir / "analysis.json")
    catalog = load_json(run_dir / "release-catalog.json")
    version_subdir = f"k8s-v{config['from_version']}-v{config['to_version']}"
    output_dir = (output_dir / version_subdir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    unexpected = [item.name for item in output_dir.iterdir() if item.name not in (report.name, "data")]
    if unexpected:
        raise SystemExit(f"output directory contains unexpected entries: {', '.join(sorted(unexpected))}")

    destination_report = output_dir / report.name
    if report != destination_report:
        shutil.copy2(report, destination_report)

    data_dir = output_dir / "data"
    if data_dir.exists():
        if not data_dir.is_dir():
            raise SystemExit(f"data path is not a directory: {data_dir}")
        shutil.rmtree(data_dir)
    data_dir.mkdir()

    kube_sources = [item for item in index.get("sources", []) if item.get("type") == "kube_features"]
    source_rows = []
    for version in config["versions"]:
        ref = str(config["refs"][version])
        expected_url = f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/pkg/features/kube_features.go"
        matches = [item for item in kube_sources if item.get("url") == expected_url]
        if len(matches) != 1:
            raise SystemExit(f"expected one fixed-ref features source for {version}, found {len(matches)}")
        record = matches[0]
        source = contained_file(run_dir, str(record["path"]))
        digest = sha256(source)
        if digest != record.get("sha256"):
            raise SystemExit(f"cached features source hash mismatch: {source}")
        target_dir = data_dir / safe_ref(ref)
        target_dir.mkdir()
        target = target_dir / "features.go"
        shutil.copy2(source, target)
        if sha256(target) != digest:
            raise SystemExit(f"copied features source hash mismatch: {target}")
        source_rows.append({
            "version": version,
            "ref": ref,
            "url": expected_url,
            "sha256": digest,
            "local": f"data/{ref}/features.go",
        })

    references = collect_references(index, analysis, catalog)
    reference_path = data_dir / "reference.md"
    reference_path.write_text(
        markdown(config, destination_report.name, source_rows, references), encoding="utf-8"
    )

    expected_files = {Path("reference.md")} | {
        Path(item["ref"]) / "features.go" for item in source_rows
    }
    actual_files = {item.relative_to(data_dir) for item in data_dir.rglob("*") if item.is_file()}
    if actual_files != expected_files:
        raise SystemExit(f"unexpected data package: {sorted(map(str, actual_files))}")
    print(f"packaged {destination_report}")
    print(f"references={len(references)}; fixed_sources={len(source_rows)}; data={data_dir}")


if __name__ == "__main__":
    main()
