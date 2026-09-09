"""Evidence collection for feature-gate change narratives.

The collector is deliberately data driven.  It does not contain a catalogue of
feature-specific answers: package documentation, KEP/proposal material and the
release changelog are queried in that order and cached under ``data``.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .fetcher import fetch_feature_narrative, translate_to_chinese

_UA = "AutoK8s/2.0 feature-change-evidence"
_TIMEOUT = 20
_ROOT_DATA = Path(__file__).resolve().parents[2] / "data"
_MEMORY: dict[tuple[str, str], Optional[dict]] = {}


def _request(url: str, *, offline: bool = False, accept: str = "text/html") -> Optional[str]:
    if offline:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None


def _cache_dir(data_dir: str | Path | None) -> Path:
    path = Path(data_dir) if data_dir else _ROOT_DATA
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_text(path: Path, text: Optional[str]) -> Optional[str]:
    if text:
        path.write_text(text, encoding="utf-8")
        return text
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def _strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _pkg_record(name: str, page: str) -> Optional[dict]:
    """Extract one constant's comments and links from pkg.go.dev HTML."""
    escaped = re.escape(name)
    marker = re.search(rf'<span[^>]+id="{escaped}"[^>]*data-kind="constant"[^>]*>', page)
    if not marker:
        marker = re.search(rf'<span[^>]+id="{escaped}"[^>]*>', page)
    if not marker:
        return None
    tail = page[marker.start():]
    nxt = re.search(r'<span[^>]+id="[^"]+"[^>]+data-kind="constant"', tail[1:])
    section = tail[:nxt.start() + 1] if nxt else tail[:6000]
    plain = _strip_html(section)
    kep = next(iter(re.findall(r"https?://kep\.k8s\.io/\d+", section)), "")
    links = re.findall(r'href="(https?://[^" ]+)"', section)
    comments = []
    for match in re.finditer(r'<span class="comment">\s*//\s*(.*?)</span>', section, re.S):
        line = _strip_html(match.group(1))
        if line and not re.match(r"^(owner|kep)\s*:", line, re.I):
            comments.append(line)
    return {
        "name": name,
        "key": name,
        "kep": kep or None,
        "description": " ".join(comments),
        "url": f"https://pkg.go.dev/k8s.io/kubernetes/pkg/features#{name}",
        "links": links,
    }


def fetch_pkg_feature(name: str, data_dir: str | Path | None = None, *, offline: bool = False) -> Optional[dict]:
    """Resolve a feature from the authoritative pkg.go.dev package page."""
    cache = _cache_dir(data_dir) / "pkg-features.html"
    page = _cache_text(cache, _request("https://pkg.go.dev/k8s.io/kubernetes/pkg/features?tab=doc", offline=offline))
    return _pkg_record(name, page) if page else None


def _proposal_from_github(key: str, *, offline: bool = False) -> Optional[dict]:
    query = urllib.parse.quote(f"{key} repo:kubernetes/enhancements")
    payload = _request(
        f"https://api.github.com/search/issues?q={query}&per_page=5",
        offline=offline,
        accept="application/vnd.github+json",
    )
    if not payload:
        return None
    try:
        items = json.loads(payload).get("items", [])
    except (TypeError, ValueError):
        return None
    if not items:
        return None
    item = max(
        items,
        key=lambda candidate: (
            str(candidate.get("title") or "").lower().count(key.lower()) * 3
            + str(candidate.get("body") or "").lower().count(key.lower())
        ),
    )
    title = str(item.get("title") or "")
    body = str(item.get("body") or "")
    url = str(item.get("html_url") or "")
    if not body:
        detail = _request(str(item.get("url") or ""), offline=offline, accept="application/vnd.github+json")
        try:
            body = str(json.loads(detail or "{}").get("body") or "")
        except (TypeError, ValueError):
            body = ""
    source = (title + "\n" + body).strip()
    return {"key": key, "title": title, "source": source[:5000], "url": url, "source_type": "GitHub proposal search"}


def _changelog_file(version: str, data_dir: str | Path | None, *, offline: bool = False) -> tuple[Optional[Path], Optional[str]]:
    path = _cache_dir(data_dir) / f"CHANGELOG-{version}.md"
    if path.is_file():
        return path, path.read_text(encoding="utf-8", errors="replace")
    raw = _request(
        f"https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-{version}.md",
        offline=offline,
        accept="text/plain",
    )
    return (path, _cache_text(path, raw)) if raw else (path, None)


def _changelog_match(name: str, version: str, data_dir: str | Path | None, *, offline: bool = False) -> Optional[dict]:
    _, text = _changelog_file(version, data_dir, offline=offline)
    if not text:
        return None
    pattern = re.compile(rf"(?i)(?m)^[-*].{{0,500}}(?:`{re.escape(name)}`|\b{re.escape(name)}\b).*$")
    matches = pattern.findall(text)
    if not matches:
        return None
    source = "\n".join(matches[:3])
    cn, engine = translate_to_chinese(source[:1200])
    return {
        "排查方法": None,
        "详细说明": cn,
        "source_en": source,
        "source_type": "Kubernetes CHANGELOG",
        "source_url": f"https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-{version}.md",
        "engine": engine,
    }


def collect_feature_evidence(
    name: str,
    *,
    kep_url: Optional[str] = None,
    description: Optional[list[str]] = None,
    version: str = "",
    data_dir: str | Path | None = None,
    offline: bool = False,
) -> dict:
    """Collect and merge evidence using pkg.go.dev -> proposal -> changelog."""
    cache_key = (name, version)
    if not offline and cache_key in _MEMORY:
        return dict(_MEMORY[cache_key] or {})
    pkg = fetch_pkg_feature(name, data_dir, offline=offline)
    key = (pkg or {}).get("key") or name
    resolved_kep = (pkg or {}).get("kep") or kep_url
    result: dict = {
        "排查方法": None, "详细说明": None, "参考资料": resolved_kep or (pkg or {}).get("url") or "",
        "source_en": None, "source_type": "", "source_url": (pkg or {}).get("url") or resolved_kep or "", "engine": None,
    }
    if not offline and (resolved_kep or description or (pkg or {}).get("description")):
        online = fetch_feature_narrative(name, resolved_kep, description or ([pkg["description"]] if pkg and pkg.get("description") else []))
        if online:
            result.update({k: v for k, v in online.items() if v})
    proposal = _proposal_from_github(key, offline=offline)
    if proposal and not result.get("详细说明"):
        cn, engine = translate_to_chinese(proposal.get("source", "")[:1600])
        result.update({"详细说明": cn, "source_en": proposal.get("source"), "source_type": proposal.get("source_type"), "source_url": proposal.get("url"), "engine": engine})
    # CHANGELOG is the prescribed fallback only when the package catalogue has
    # no such feature.  This also prevents a current changelog line from
    # overriding the package/KEP evidence for a known gate.
    if not pkg and not result.get("详细说明") and version:
        changelog = _changelog_match(name, version, data_dir, offline=offline)
        if changelog:
            result.update({k: v for k, v in changelog.items() if v})
    if not result.get("排查方法") and description:
        result["排查方法"] = "检查集群配置和组件启动参数中的特性门控 {0}，并在升级前后验证相关工作负载。".format(name)
    if not offline:
        _MEMORY[cache_key] = dict(result)
    return result


def verify_evidence(rows: list, research: dict[str, dict]) -> list[dict]:
    """Return one deterministic verification record per generated row."""
    records = []
    for row in rows:
        item = research.get(row.name, {})
        compatible = bool(row.compat_analysis)
        check = str(item.get("排查方法") or "").strip()
        detail = str(item.get("详细说明") or "").strip()
        source = str(item.get("参考资料") or item.get("source_url") or "").strip()
        issues = []
        if not compatible and not check:
            issues.append("missing_check_method")
        if detail and not source:
            issues.append("detail_without_source")
        records.append({"feature": row.name, "compatible": compatible, "source": source, "verified": not issues, "issues": issues})
    return records
