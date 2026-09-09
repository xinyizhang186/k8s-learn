"""fetcher.py — 抓取 Kubernetes 发布博客, 提取结构化特性数据。

从博客 HTML 中提取:
  - 版本号 (从 URL)
  - 各阶段特性 (Stable/Beta/Alpha) 的名称和英文描述
  - 弃用/移除特性 (Deprecation/Removal) 的名称和英文描述

博客页面的 HTML 结构:
  <h2>Features graduating to Stable</h2>  → 孵化成熟特性
    <h3>Feature Name</h3>
    <p>Description...</p>
  <h2>New features in Beta</h2>           → 增强特性
  <h2>New features in Alpha</h2>          → 新增特性
  <h2>Deprecations removals...</h2>       → 特性剔除
"""
from __future__ import annotations

import re
import time
import urllib.request
import urllib.error
from typing import Optional
from dataclasses import dataclass, field


_FETCH_TIMEOUT = 30
_FETCH_RETRIES = 3
_UA = "Mozilla/5.0 (K8sVersionAnalysis/1.0; K8sReleaseAnalysis)"

_SECTION_STABLE = "Stable"
_SECTION_BETA = "Beta"
_SECTION_ALPHA = "Alpha"
_SECTION_DEPRECATION = "Deprecation"

_SECTION_MAP = {
    "Features graduating to Stable": _SECTION_STABLE,
    "New features in Beta": _SECTION_BETA,
    "New features in Alpha": _SECTION_ALPHA,
    "Deprecations removals, and community updates": _SECTION_DEPRECATION,
    "Deprecations, removals, and community updates": _SECTION_DEPRECATION,
    "Deprecations and removals": _SECTION_DEPRECATION,
    "Deprecations, removals and community updates": _SECTION_DEPRECATION,
}


# 官方中文对齐逻辑已迁移到 zh_align.py (模糊匹配, 更稳健)


@dataclass
class Feature:
    section: str
    name: str
    description_en: str
    version: str = ""
    name_zh: str = ""
    description_zh: str = ""


@dataclass
class BlogData:
    version: str
    blog_url: str
    features: list[Feature] = field(default_factory=list)
    deprecations: list[Feature] = field(default_factory=list)


def _fetch_url(url: str) -> Optional[str]:
    for attempt in range(_FETCH_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read()
                encoding = "utf-8"
                ct = resp.headers.get("Content-Type", "")
                if "charset=" in ct:
                    encoding = ct.split("charset=")[-1].strip()
                return raw.decode(encoding, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None
    return None


def extract_version_from_url(url: str) -> str:
    m = re.search(r'v1-(\d+)', url)
    if m:
        return f"1.{m.group(1)}"
    m = re.search(r'v1\.(\d+)', url)
    if m:
        return f"1.{m.group(1)}"
    return ""


def _clean_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_features_from_html(html: str, version: str) -> tuple[list[Feature], list[Feature]]:
    """从博客 HTML 中提取特性列表和弃用列表。"""
    heading_re = re.compile(r'<(h[2345])[^>]*>(.*?)</\1>', re.DOTALL)
    matches = list(heading_re.finditer(html))

    features: list[Feature] = []
    deprecations: list[Feature] = []
    current_section: Optional[str] = None

    section_markers = {
        "features graduating to stable": _SECTION_STABLE,
        "new features in beta": _SECTION_BETA,
        "new features in alpha": _SECTION_ALPHA,
    }
    deprecation_section_markers = {
        "deprecations removals",
        "deprecations, removals",
        "deprecation of service .spec.externalips",
        "removal of the gitrepo volume driver",
        "ingress nginx retirement",
        "removal of cgroup v1 support",
        "deprecation of ipvs mode",
        "final call for containerd",
        "manual cgroup driver configuration is deprecated",
        "kubernetes to end containerd",
        "preferclose traffic distribution is deprecated",
    }
    skip_titles = {
        "spotlight on key updates",
        "release theme and logo",
        "graduations to stable",
        "graduations, deprecations, and removals",
        "release notes",
        "availability",
        "release team",
        "project velocity",
        "events update",
        "event update",
        "upcoming release webinar",
        "want to know more?",
        "get involved",
        "kubernetes blog",
        "other notable changes",
        "continued innovation in dynamic resource allocation",
        "comparable resource version semantics",
        "deprecations removals, and community updates",
        "deprecations, removals and community updates",
        "deprecations, removals, and community updates",
        "deprecations and removals",
        "improved pod stability during kubelet restarts",
    }

    for i, m in enumerate(matches):
        tag = m.group(1)
        raw_content = m.group(2)
        clean = _clean_text(raw_content)

        if not clean:
            continue
        lower = clean.lower().strip()

        if lower in skip_titles:
            if "other notable changes" in lower:
                current_section = None
            continue

        section_match = None
        for marker, sec in section_markers.items():
            if marker in lower:
                section_match = sec
                break
        if section_match:
            current_section = section_match
            continue

        if any(dm in lower for dm in deprecation_section_markers):
            current_section = _SECTION_DEPRECATION

        if current_section is None:
            continue

        is_feature_heading = (
            tag in ("h3", "h4")
            or (tag == "h2" and current_section == _SECTION_DEPRECATION)
        )
        if not is_feature_heading:
            continue

        start = m.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = start + 8000
        section_html = html[start:end]

        paras = re.findall(r'<p[^>]*>(.*?)</p>', section_html, re.DOTALL)
        para_texts = []
        for p in paras:
            text = _clean_text(p)
            if text and len(text) > 20:
                para_texts.append(text)
        description = " ".join(para_texts[:3])

        if not description or len(description) < 30:
            continue

        feature = Feature(
            section=current_section,
            name=clean,
            description_en=description[:1500],
            version=version,
        )

        if current_section == _SECTION_DEPRECATION:
            deprecations.append(feature)
        else:
            features.append(feature)

    return features, deprecations


def fetch_release_blog(blog_url: str) -> Optional[BlogData]:
    """抓取发布博客, 返回结构化数据。"""
    html = _fetch_url(blog_url)
    if not html:
        return None

    version = extract_version_from_url(blog_url)
    if not version:
        return None

    features, deprecations = _extract_features_from_html(html, version)

    # 官方中文对齐已抽到 zh_align 模块 (模糊匹配, 更稳健)
    from .zh_align import align_official_chinese
    align_official_chinese(blog_url, features, deprecations)

    return BlogData(
        version=version,
        blog_url=blog_url,
        features=features,
        deprecations=deprecations,
    )


# 官方中文对齐 (_zh_blog_url / _extract_zh_features / _align_official_chinese 等)
# 已整体迁移到 zh_align.py
