"""deprecation_gen.py — 弃用/移除特性风险分析 (从 content_gen.py 抽出)。"""
from __future__ import annotations

import re

from .fetcher import Feature
from .web_search import WebContext, enrich_feature_context
from .keywords import _SKIP_KEYWORDS, _TRANSLATION_ARTIFACTS
from .text_utils import _clean_cn, _truncate_cn, _strip_noise, _split_sentences, _split_zh_sentences
from .domain_classifier import classify_domain


def _generate_deprecation_from_zh(dep: Feature) -> str:
    """基于官方中文描述生成弃用风险描述 (vX.YY + 关键句)。"""
    desc = dep.description_zh
    sents = _split_zh_sentences(desc)
    key = [s for s in sents
           if any(k in s for k in ["弃用", "移除", "终止", "不再", "淘汰", "退役", "默认"])
           and len(s) < 160]
    if not key:
        key = sents[:2]
    body = " ".join(key[:2]).rstrip("。")
    body = re.sub(r"此项工作.*$", "", body).strip()
    body = re.sub(r"KEP[- ]?\d+", "", body, flags=re.I).strip()
    body = re.sub(r"通过\s*[：:]\s*[^，。；]{0,30}\s*跟踪\S*", "", body).strip()
    body = re.sub(r"请阅读关于\s*[^，。；]{0,20}[；;]?", "", body).strip()
    body = re.sub(r"要了解更多信息[，,]?\s*你也可以\S*$", "", body).strip()
    body = re.sub(r"你也可以[。]?$", "", body).strip()
    body = re.sub(r"\s+", " ", body).strip(" ，；")
    body = re.sub(r"。+", "。", body).rstrip("。")
    if not body and sents:
        body = sents[0].rstrip("。")
    if not body:
        body = f"{dep.name_zh or dep.name} 已被弃用或移除"
    return f"v{dep.version} {body}。"


def _initial_deprecation(dep: Feature) -> str:
    """从博客英文描述生成弃用风险中文描述 (intro)。"""
    from autok8s.common.translate import translate_to_chinese
    clean_desc = _strip_noise(dep.description_en)
    sents = _split_sentences(clean_desc)
    key_sents = []
    for s in sents:
        sl = s.lower()
        if any(kw in sl for kw in _SKIP_KEYWORDS):
            continue
        if any(kw in sl for kw in ["deprecat", "remov", "retire", "no longer", "disabled", "end of", "last version", "final", "no further"]):
            key_sents.append(s)
        elif len(key_sents) > 0:
            key_sents.append(s)
    if not key_sents:
        key_sents = sents[:2]
    desc_en = " ".join(key_sents[:2])
    desc_cn = _clean_cn(translate_to_chinese(desc_en[:500]))
    desc_cn = _truncate_cn(desc_cn, 120)
    return f"v{dep.version} {desc_cn}"


def _regenerate_deprecation_with_web(dep: Feature, ctx: WebContext) -> str:
    """用联网上下文重新生成弃用风险描述。"""
    from autok8s.common.translate import translate_to_chinese
    clean_blog = _strip_noise(dep.description_en)
    web_text = ctx.combined_text[:2500]
    combined_en = f"{clean_blog}\n\n{web_text}".strip()
    sents = _split_sentences(combined_en)
    key_sents = []
    for s in sents:
        sl = s.lower()
        if any(kw in sl for kw in ["deprecat", "remov", "retire", "no longer",
                                    "disabled", "end of", "last version",
                                    "final", "no further"]):
            key_sents.append(s)
        elif key_sents:
            key_sents.append(s)
        if len(key_sents) >= 3:
            break
    if not key_sents:
        key_sents = sents[:2]
    desc_en = " ".join(key_sents[:3])
    desc_cn = _clean_cn(translate_to_chinese(desc_en[:700]))
    desc_cn = _truncate_cn(desc_cn, 140)
    return f"v{dep.version} {desc_cn}"


def _deprecation_confident(dep: Feature, intro: str) -> tuple[bool, list[str]]:
    """评估弃用描述是否可信 (无需联网)。"""
    issues: list[str] = []
    body = intro.replace(f"v{dep.version}", "", 1).strip()
    if len(body) < 15:
        issues.append("desc_too_short")
    cn = len(re.findall(r"[\u4e00-\u9fff]", body))
    if cn / max(len(body), 1) < 0.3:
        issues.append("low_chinese_ratio")
    if any(a in intro for a in _TRANSLATION_ARTIFACTS):
        issues.append("translation_artifact")
    if len(dep.description_en) < 200:
        issues.append("blog_desc_short")
    return (len(issues) == 0), issues


def _verify_deprecation(intro: str, dep: Feature) -> tuple[bool, list[str]]:
    """自检弃用风险描述正确性。"""
    issues: list[str] = []
    if dep.version and dep.version not in intro:
        issues.append("version_mismatch")
    body = intro.replace(f"v{dep.version}", "", 1).strip()
    if len(body) < 12:
        issues.append("desc_too_short")
    cn = len(re.findall(r"[\u4e00-\u9fff]", body))
    if cn / max(len(body), 1) < 0.25:
        issues.append("low_chinese_ratio")
    if any(a in intro for a in _TRANSLATION_ARTIFACTS):
        issues.append("translation_artifact")
    return (len(issues) == 0), issues


def generate_deprecation_content(dep: Feature) -> dict[str, str]:
    """为单个弃用生成中文风险内容。

    优先使用官方中文博客描述; 无中文时批量翻译一次英文描述。
    不做联网补充 (已熔断或不可达时不浪费时间)。
    """
    from autok8s.common.logging import get_logger
    _logger = get_logger("deprecation")

    domain = classify_domain(dep.name + " " + dep.description_en)
    impact = f"关键参数弃用，产品需审视是否有使用 {dep.name}，及时适配"
    if "removal" in dep.name.lower() or "retire" in dep.name.lower():
        impact = f"关键特性去除，产品需审视是否依赖 {dep.name}，及时适配"
    base_row = {
        "分类": f"特性剔除:{dep.version}",
        "变更名称": dep.name,
        "推动公司": "Kubernetes社区",
        "风险涉及领域": domain,
        "技术or商业影响": impact,
    }

    if not dep.description_zh:
        from autok8s.common.translate import translate_to_chinese
        translated = translate_to_chinese(dep.description_en[:1200])
        if translated and len(re.findall(r"[\u4e00-\u9fff]", translated)) >= 5:
            dep.description_zh = translated
            if not dep.name_zh:
                dep.name_zh = dep.name

    intro = _generate_deprecation_from_zh(dep) if dep.description_zh else _initial_deprecation(dep)

    if not intro or len(intro.strip()) < 15:
        intro = f"v{dep.version} {dep.name_zh or dep.name} 已被弃用或移除。"
    if dep.version and dep.version not in intro:
        intro = f"v{dep.version} {intro}"

    passed, v_issues = _verify_deprecation(intro, dep)
    if passed:
        _logger.info("弃用 %s: 基于博客描述生成", dep.name)
        return {**base_row, "风险详细描述": intro}
    _logger.warning("[质量门] 弃用 %s 博客回退描述未通过验证 %s；读者字段留空", dep.name, v_issues)
    return {**base_row, "风险详细描述": ""}
