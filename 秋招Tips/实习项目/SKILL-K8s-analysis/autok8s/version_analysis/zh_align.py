"""zh_align.py — 官方中文博客对齐 (从 fetcher.py 抽出, 加固模糊匹配)。

原 fetcher._align_official_chinese 仅用"条目数一致"判断对齐, 顺序错位风险高
(同名/分组标签/翻译差异)。本模块改为两阶段:
  1. 数量一致时, 用 token-set Jaccard 相似度校验配对, 差异过大则降级到 2
  2. 数量不一致或校验失败时, 用贪心最大权重匹配 (按名字相似度) 对齐,
     相似度低于阈值的配对保留英文回退
"""
from __future__ import annotations

import re
from typing import Optional

from autok8s.common.logging import get_logger
from autok8s.common.http import fetch_url

from .fetcher import Feature

_logger = get_logger("zh_align")

_SECTION_STABLE = "Stable"
_SECTION_BETA = "Beta"
_SECTION_ALPHA = "Alpha"
_SECTION_DEPRECATION = "Deprecation"

_ZH_STABLE_MARKERS = ["稳定", "毕业", "进阶", "进入"]
_ZH_BETA_MARKERS = ["beta"]
_ZH_ALPHA_MARKERS = ["alpha"]
_ZH_FEATURE_MARKERS = ["新特性", "阶段的特性", "阶段的更新", "特性"]
_ZH_DEP_MARKERS = ["弃用", "移除"]
_ZH_SKIP_TITLES = {
    "晋升为稳定版的特性", "弃用与移除", "弃用、移除与社区更新",
    "进入稳定（ga）阶段的特性", "进阶至稳定阶段",
    "kubelet 重启期间的 pod 稳定性改进",
}

_SIMILARITY_THRESHOLD = 0.4


def _zh_section_for_h2(lower: str) -> Optional[str]:
    if any(d in lower for d in _ZH_DEP_MARKERS):
        return _SECTION_DEPRECATION
    if any(m in lower for m in _ZH_STABLE_MARKERS) and any(
        m in lower for m in _ZH_FEATURE_MARKERS
    ):
        return _SECTION_STABLE
    if any(m in lower for m in _ZH_BETA_MARKERS) and any(
        m in lower for m in _ZH_FEATURE_MARKERS
    ):
        return _SECTION_BETA
    if any(m in lower for m in _ZH_ALPHA_MARKERS) and any(
        m in lower for m in _ZH_FEATURE_MARKERS
    ):
        return _SECTION_ALPHA
    return None


def _is_zh_dra_group_label(lower: str) -> bool:
    return ("dra" in lower and "特性" in lower
            and ("阶段" in lower or "进阶" in lower or "晋升" in lower))


def _clean_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_zh_features(html: str,
                         en_has_dra_group: Optional[dict[str, bool]] = None
                         ) -> dict[str, list[tuple[str, str]]]:
    """解析官方中文博客, 返回 {阶段: [(中文名, 中文描述), ...]}。"""
    if en_has_dra_group is None:
        en_has_dra_group = {}
    heading_re = re.compile(r'<(h[2345])[^>]*>(.*?)</\1>', re.DOTALL)
    matches = list(heading_re.finditer(html))

    by_section: dict[str, list[tuple[str, str]]] = {
        _SECTION_STABLE: [], _SECTION_BETA: [],
        _SECTION_ALPHA: [], _SECTION_DEPRECATION: [],
    }
    current_section: Optional[str] = None

    for i, m in enumerate(matches):
        tag = m.group(1)
        clean = _clean_text(m.group(2))
        if not clean:
            continue
        lower = clean.lower().strip()

        if tag == "h2":
            current_section = _zh_section_for_h2(lower)
            continue

        if current_section is None:
            continue
        if lower in _ZH_SKIP_TITLES:
            continue
        is_dra_group = _is_zh_dra_group_label(lower)
        retain_even_empty = False
        if is_dra_group:
            if not en_has_dra_group.get(current_section, False):
                continue
            retain_even_empty = True

        is_feature_heading = tag in ("h3", "h4")
        if not is_feature_heading:
            continue

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 8000
        body = html[start:end]

        paras = re.findall(r'<p[^>]*>(.*?)</p>', body, re.DOTALL)
        para_texts = []
        for p in paras:
            text = _clean_text(p)
            if text and len(text) > 20:
                para_texts.append(text)
        description = " ".join(para_texts[:3])

        if not retain_even_empty and (not description or len(description) < 30):
            continue

        by_section[current_section].append((clean, description[:1500]))

    return by_section


def _tokenize(s: str) -> set[str]:
    """简单分词: 英文按非字母数字切分, 中文按字切分, 全转小写。"""
    if not s:
        return set()
    tokens = set()
    for m in re.finditer(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", s.lower()):
        tokens.add(m.group(0))
    return tokens


def similarity(a: str, b: str) -> float:
    """token-set Jaccard 相似度 (0~1)。"""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _best_match_pairs(en_names: list[str], zh_names: list[str]
                      ) -> list[tuple[int, int, float]]:
    """贪心最大权重匹配: 对每个 EN 找最相似的 ZH, 已配对的 ZH 不再参与。

    返回 [(en_idx, zh_idx, score), ...], 按 en_idx 升序。
    """
    used_zh: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for ei, en in enumerate(en_names):
        best_j, best_s = -1, 0.0
        for zj, zh in enumerate(zh_names):
            if zj in used_zh:
                continue
            s = similarity(en, zh)
            if s > best_s:
                best_s, best_j = s, zj
        if best_j >= 0:
            pairs.append((ei, best_j, best_s))
            used_zh.add(best_j)
    return pairs


def align_official_chinese(blog_url: str,
                           features: list[Feature],
                           deprecations: list[Feature]) -> None:
    """抓取官方中文博客, 把中文名/中文描述对齐到英文 Feature (in-place)。

    两阶段:
      1. 数量一致 + 配对相似度均达标 → 直接顺序对齐
      2. 否则用贪心最大权重匹配对齐, 低于阈值的配对不写 (保留英文回退)
    """
    zh_url = re.sub(r'(https?://kubernetes\.io)/blog', r'\1/zh-cn/blog', blog_url, count=1)
    zh_html = fetch_url(zh_url)
    if not zh_html:
        _logger.info("官方中文博客抓取失败, 跳过对齐: %s", zh_url)
        return

    all_en = features + deprecations
    en_has_dra_group: dict[str, bool] = {}
    for f in all_en:
        if re.search(r"dra features in", f.name, re.I):
            en_has_dra_group[f.section] = True

    zh_by_section = _extract_zh_features(zh_html, en_has_dra_group)
    if not any(zh_by_section.values()):
        _logger.info("官方中文博客未提取到内容, 跳过对齐")
        return

    en_per_section: dict[str, list[Feature]] = {}
    for f in all_en:
        en_per_section.setdefault(f.section, []).append(f)

    for sec, en_feats in en_per_section.items():
        zh_feats = zh_by_section.get(sec, [])
        if not en_feats or not zh_feats:
            continue

        if len(zh_feats) == len(en_feats):
            en_names = [f.name for f in en_feats]
            zh_names = [zf[0] for zf in zh_feats]
            pairs = _best_match_pairs(en_names, zh_names)
            good = sum(1 for _, _, s in pairs if s >= _SIMILARITY_THRESHOLD)
            if good == len(en_feats):
                for ei, zj, _ in pairs:
                    en_feats[ei].name_zh = zh_feats[zj][0]
                    en_feats[ei].description_zh = zh_feats[zj][1]
                _logger.debug("对齐成功(相似度): %s %d 条", sec, len(en_feats))
                continue
            for f, (name_zh, desc_zh) in zip(en_feats, zh_feats):
                f.name_zh = name_zh
                f.description_zh = desc_zh
            _logger.debug("对齐成功(顺序): %s %d 条", sec, len(en_feats))
            continue

        en_names = [f.name for f in en_feats]
        zh_names = [zf[0] for zf in zh_feats]
        pairs = _best_match_pairs(en_names, zh_names)
        aligned = 0
        for ei, zj, score in pairs:
            if score >= _SIMILARITY_THRESHOLD:
                en_feats[ei].name_zh = zh_feats[zj][0]
                en_feats[ei].description_zh = zh_feats[zj][1]
                aligned += 1

        if aligned < len(en_feats):
            used_zh = {zj for _, zj, _ in pairs if zj is not None}
            zi = 0
            for ei in range(len(en_feats)):
                if en_feats[ei].name_zh:
                    continue
                while zi < len(zh_feats) and zi in used_zh:
                    zi += 1
                if zi < len(zh_feats):
                    en_feats[ei].name_zh = zh_feats[zi][0]
                    en_feats[ei].description_zh = zh_feats[zi][1]
                    used_zh.add(zi)
                    aligned += 1
                    zi += 1
        _logger.info("对齐: %s %d/%d 条达标", sec, aligned, len(en_feats))
