#!/usr/bin/env python3
"""Run a dependency-free parser and XLSX smoke test."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = load_module("extract_feature_changes", ROOT / "scripts" / "extract_feature_changes.py")
    old = parser.parse_file(ROOT / "examples" / "fixtures" / "kube_features-1.35.go", "1.35")
    new = parser.parse_file(ROOT / "examples" / "fixtures" / "kube_features-1.36.go", "1.36")
    assert old["ExampleGate"].stage == "Beta"
    assert new["ExampleGate"].stage == "GA"
    assert new["ExampleGate"].default is True
    assert new["ExampleGate"].locked is True
    assert "RemovedGate" in old and "RemovedGate" not in new
    assert "ConfiguredNewGate" in new
    histories = parser.parse_histories(ROOT / "examples" / "fixtures" / "kube_features-1.36.go")
    events = parser.release_events(histories, (1, 35), (1, 36), "1.35", "1.36")
    by_name = {item["feature_name"]: item for item in events}
    assert len(events) == 2
    assert by_name["ExampleGate"]["change_type"] == "Changed"
    assert by_name["ExampleGate"]["stage_change"] == "Alpha->GA"
    assert by_name["ConfiguredNewGate"]["change_type"] == "Added"
    assert by_name["ConfiguredNewGate"]["compatible"] is True

    facts = {
        "feature_changes": [{
            "id": "1.35-to-1.36:ExampleGate", "from_version": "1.35", "to_version": "1.36",
            "feature_name": "ExampleGate", "change_types": ["阶段变化", "默认值变化", "锁定变化"],
            "before": {"stage": "Beta", "default": False, "locked": False},
            "after": {"stage": "GA", "default": True, "locked": True},
        }]
    }
    analysis = json.loads((ROOT / "examples" / "analysis-record.json").read_text(encoding="utf-8-sig"))
    baseline = dict(analysis["version_analysis"][0])
    baseline.update({
        "version": "1.35", "category_group": "孵化成熟特性:1.35",
        "feature_name": "Baseline Example", "current_problem": "基线版本示例用于验证多版本工作簿结构。",
        "enhancement": "基线版本示例用于验证起始版本不会在版本分析中遗漏。",
    })
    analysis["version_analysis"].insert(0, baseline)
    analysis["version_analysis"][1].update({
        "category_group": "孵化成熟特性:1.36", "current_problem": "目标版本示例用于验证富文本现状段。",
        "enhancement": "目标版本示例用于验证富文本增强段与目标版本分组。",
    })
    analysis["version_analysis"].append({
        "catalog_id": "release-blog:1.36:risk:retired-example",
        "version": "1.36", "category": "弃用与移除", "category_group": "特性剔除:1.36",
        "feature_name": "Retired Example (wrong draft name)", "name_source": "official_release_blog",
        "primary_source": "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/",
        "supplemental_sources": [],
        "feature_summary": "示例风险用于验证风险区描述不可为空。",
        "value_domain": "DFX:兼容性", "value_analysis": "升级前检查依赖并完成迁移。",
        "sources": ["https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/"], "status": "ready",
    })
    with tempfile.TemporaryDirectory(prefix="k8s-release-xlsx-") as temporary:
        run_dir = Path(temporary)
        analysis["version_analysis"][0].update({
            "catalog_id": "release-blog:1.35:feature:baseline-example",
            "name_source": "official_release_blog",
            "primary_source": "https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/",
            "supplemental_sources": [],
            "sources": ["https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/"],
        })
        analysis["version_analysis"][1].update({
            "catalog_id": "release-blog:1.36:feature:target-example",
            "feature_name": "Wrong generated feature name",
            "name_source": "official_release_blog",
            "primary_source": "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/",
            "supplemental_sources": [{
                "url": "https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/",
                "supports": ["enhancement", "value_analysis"],
                "reason": "正式发行博客未完整展开策略绑定和失败处理边界",
            }],
            "sources": [
                "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/",
                "https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/",
            ],
        })
        catalog = {
            "versions": [
                {"version": "1.35", "features": [{
                    "catalog_id": "release-blog:1.35:feature:baseline-example", "version": "1.35",
                    "name": "Baseline Example", "source": "https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/",
                }], "risks": []},
                {"version": "1.36", "features": [{
                    "catalog_id": "release-blog:1.36:feature:target-example", "version": "1.36",
                    "name": "Official Release Blog Feature Name", "source": "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/",
                }], "risks": [{
                    "catalog_id": "release-blog:1.36:risk:retired-example", "version": "1.36",
                    "name": "Retired Example", "source": "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/",
                }]},
            ]
        }
        (run_dir / "machine-facts.json").write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
        (run_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        (run_dir / "release-catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        config = {
            "from_version": "1.35", "to_version": "1.36", "versions": ["1.35", "1.36"],
            "refs": {"1.35": "v1.35.0", "1.36": "v1.36.0"},
        }
        (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        source_dir = run_dir / "sources"
        source_dir.mkdir()
        source_records = []
        for version, ref in config["refs"].items():
            payload = f"package features\n\n// fixed source for {ref}\n".encode("utf-8")
            source = source_dir / f"kube_features-{version}-{ref}.go"
            source.write_bytes(payload)
            source_records.append({
                "type": "kube_features",
                "url": f"https://raw.githubusercontent.com/kubernetes/kubernetes/{ref}/pkg/features/kube_features.go",
                "path": str(source.relative_to(run_dir)).replace("\\", "/"),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            })
        for version, url in (
            ("1.35", "https://kubernetes.io/blog/2025/12/17/kubernetes-v1-35-release/"),
            ("1.36", "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/"),
        ):
            payload = f"release {version}".encode("utf-8")
            path = source_dir / f"release-{version}.html"
            path.write_bytes(payload)
            source_records.append({
                "type": "release_blog", "url": url,
                "path": str(path.relative_to(run_dir)).replace("\\", "/"),
                "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            })
        (run_dir / "source-index.json").write_text(
            json.dumps({"sources": source_records}, ensure_ascii=False), encoding="utf-8"
        )
        report = run_dir / "report.xlsx"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_report.py"), "--run-dir", str(run_dir), "--output", str(report)],
            check=True,
        )
        subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--run-dir", str(run_dir)], check=True)
        validation = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_analysis.py"), "--run-dir", str(run_dir)],
            check=True, capture_output=True, text=True,
        )
        report_data = json.loads((run_dir / "validation.json").read_text(encoding="utf-8"))
        assert any(item["code"] == "release_blog_name_modified" for item in report_data["issues"])
        assert not any(item["code"] == "invalid_release_blog_primary" for item in report_data["issues"])
        assert not any(item["code"] == "untrusted_version_supplement" for item in report_data["issues"])
        assert "recommendation:" in validation.stdout
        bad_analysis = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8"))
        bad_analysis["version_analysis"][0]["supplemental_sources"] = [{
            "url": "https://kubernetes.io/blog/2024/01/01/unrelated-feature/",
            "supports": ["enhancement"],
            "reason": "错误示例用于确认其他博客不能替代或补充当前正式发行博客",
        }]
        bad_analysis["version_analysis"][0]["sources"].append("https://kubernetes.io/blog/2024/01/01/unrelated-feature/")
        (run_dir / "analysis.json").write_text(json.dumps(bad_analysis, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_analysis.py"), "--run-dir", str(run_dir)],
            check=True, capture_output=True, text=True,
        )
        bad_report = json.loads((run_dir / "validation.json").read_text(encoding="utf-8"))
        assert any(item["code"] == "untrusted_version_supplement" for item in bad_report["issues"])
        bad_analysis["version_analysis"][0]["supplemental_sources"] = []
        bad_analysis["version_analysis"][0]["sources"] = [bad_analysis["version_analysis"][0]["primary_source"]]
        (run_dir / "analysis.json").write_text(json.dumps(bad_analysis, ensure_ascii=False), encoding="utf-8")
        output_dir = run_dir / "output"
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "package_output.py"),
            "--run-dir", str(run_dir), "--report", str(report), "--output-dir", str(output_dir),
        ], check=True)
        packaged_root = output_dir / "k8s-v1.35-v1.36"
        assert (packaged_root / "report.xlsx").is_file()
        reference = (packaged_root / "data" / "reference.md").read_text(encoding="utf-8")
        assert "## 核心发行博客" in reference
        assert "## 来源说明" in reference
        assert "## 固定 Tag 源码" in reference
        assert "<details>" in reference
        assert "https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/" in reference
        assert "| Kubernetes 版本 |" not in reference
        expected_data = {Path("reference.md")}
        for version, ref in config["refs"].items():
            copied = packaged_root / "data" / ref / "features.go"
            original = source_dir / f"kube_features-{version}-{ref}.go"
            assert copied.read_bytes() == original.read_bytes()
            expected_data.add(Path(ref) / "features.go")
        actual_data = {
            item.relative_to(packaged_root / "data")
            for item in (packaged_root / "data").rglob("*") if item.is_file()
        }
        assert actual_data == expected_data
    print("self-test passed")


if __name__ == "__main__":
    main()
