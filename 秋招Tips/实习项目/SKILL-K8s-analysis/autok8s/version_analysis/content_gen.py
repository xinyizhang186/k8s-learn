"""content_gen.py — 编排器 (LLM 优先 + 正则回退 + 答案自检)。

原 1267 行已拆为: keywords / text_utils / domain_classifier /
regex_pipeline_en / regex_pipeline_zh / deprecation_gen。本文件只保留
顶层编排逻辑 + 向后兼容 re-export。

并行优化: generate_analysis / generate_multi_version_analysis 使用
ThreadPoolExecutor 并行处理特性, 将 N 个特性的串行耗时
(web 搜索 + LLM 调用) 压缩为 O(N/concurrency)。
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .fetcher import Feature, BlogData
from .web_search import WebContext, verify_content
from .domain_classifier import classify_domain
from .deprecation_gen import generate_deprecation_content


_MAX_CONTENT_WORKERS = int(os.environ.get("AUTOK8S_WORKERS", "8"))


def _stage_prefix(feature: Feature, name: str) -> str:
    """构建特性阶段前缀 (v{ver} 中“{name}”进入 {stage} 阶段)。

    撑伞特性 (含 'features in'/'阶段的...特性') 用框架级表述。
    """
    ver = feature.version
    is_umbrella = bool(re.search(r"features in|阶段的.*特性", name, re.I))
    if is_umbrella:
        core = "DRA" if "DRA" in name.upper() else re.sub(
            r"(?:Alpha|Beta|Stable)\s*阶段.*?特性", "", name).strip() or name
        if feature.section == "Alpha":
            return f"v{ver} 中{core} 框架引入若干 Alpha 阶段增强"
        if feature.section == "Beta":
            return f"v{ver} 中{core} 框架的若干核心特性进阶至 Beta"
        return f"v{ver} 中{core} 框架的相关特性晋升为 GA"
    if feature.section == "Alpha":
        return f"v{ver} 中“{name}”作为 Alpha 特性发布"
    if feature.section == "Beta":
        return f"v{ver} 中“{name}”进入 Beta 阶段"
    return f"v{ver} 中“{name}”进入 GA 阶段"


def _source_safe_content(feature: Feature) -> tuple[str, str]:
    """Do not publish a stage announcement as a functional introduction.

    A release section is evidence that a feature changed stage, but it does not
    establish its prior limitation, delivered behavior, or value.  Publishing
    it alone under ``本特性增强`` is misleading, so the reader-facing fields
    remain empty until online/official evidence supports the full statement.
    """
    return "", ""


def _finalize_feature_content(
    base_row: dict[str, str], feature: Feature, intro: str, value: str, logger,
    ctx: WebContext | None = None,
) -> dict[str, str]:
    """Hard publication gate: rejected prose cannot reach the workbook."""
    passed, issues = verify_content(intro, value, feature, ctx)
    if passed:
        return {**base_row, "特性功能介绍": intro, "特性功能价值分析": value}
    safe_intro, safe_value = _source_safe_content(feature)
    logger.warning(
        "[质量门] %s 未通过最终验证 %s；缺少可证实的现状或功能行为，读者字段留空",
        feature.name, issues,
    )
    return {**base_row, "特性功能介绍": safe_intro, "特性功能价值分析": safe_value}


def _generate_feature_content_safe(feature: Feature) -> dict[str, str]:
    """generate_feature_content 的线程安全包装, 异常时返回基础行而非崩溃。"""
    from autok8s.common.logging import get_logger
    _logger = get_logger("content")
    try:
        return generate_feature_content(feature)
    except Exception as e:
        _logger.error("特性 %s 处理异常: %s", feature.name, e)
        domain = classify_domain(feature.name + " " + feature.description_en)
        section_label_map = {
            "Stable": f"孵化成熟特性:{feature.version}",
            "Beta": f"增强特性：{feature.version}",
            "Alpha": f"新增特性：{feature.version}",
        }
        return {
            "分类": section_label_map.get(feature.section, f"新增特性：{feature.version}"),
            "特性名称": feature.name,
            "推动公司": "",
            "特性价值领域": domain,
            "特性功能介绍": "",
            "特性功能价值分析": "",
        }


def _generate_deprecation_content_safe(dep: Feature) -> dict[str, str]:
    """generate_deprecation_content 的线程安全包装, 异常时返回基础行而非崩溃。"""
    from autok8s.common.logging import get_logger
    _logger = get_logger("deprecation")
    try:
        return generate_deprecation_content(dep)
    except Exception as e:
        _logger.error("弃用 %s 处理异常: %s", dep.name, e)
        domain = classify_domain(dep.name + " " + dep.description_en)
        return {
            "分类": f"特性剔除:{dep.version}",
            "变更名称": dep.name,
            "推动公司": "Kubernetes社区",
            "风险涉及领域": domain,
            "技术or商业影响": f"关键参数弃用，产品需审视是否有使用 {dep.name}，及时适配",
            "风险详细描述": "",
        }


def _parallel_generate(items: list, worker_fn) -> list:
    """并行执行 worker_fn 处理每个 item, 保持输入顺序返回结果。"""
    if not items:
        return []
    results: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=_MAX_CONTENT_WORKERS) as ex:
        future_to_idx = {ex.submit(worker_fn, item): i for i, item in enumerate(items)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                from autok8s.common.logging import get_logger
                get_logger("content").error("并行处理第 %d 项异常: %s", idx, e)
                results[idx] = {}
    return results


_PAIN_MARKERS = [
    "棘手", "迫使", "难以", "无法", "不支持", "缺乏", "风险",
    "争用", "问题", "痛点", "传统", "默认情况下", "此前", "过去",
    "不一致", "不可靠", "复杂", "低效", "局限", "不足",
    "只能", "而不能", "不能", "导致", "可能引发", "可能造成", "受损",
    "不得不", "粗暴地",
]

_SOLUTION_START_WORDS = [
    "该特性", "这一特性", "此项工作", "该功能", "此功能",
    "引入了", "新增", "现已", "现在可以", "为了解决",
    "使其", "使得", "使Kubernetes", "使集群",
]

_SOLUTION_VERBS = [
    "引入了", "新增了", "允许", "支持", "提供", "实现",
    "现已", "现在可以", "现已更新",
]

_BENEFIT_CLAUSE_MARKERS = ["从而", "使得", "有助于", "确保", "其主要收益", "显著提升"]

_BLOG_NOISE_PATTERNS = [
    r"此项工作是\s*KEP\s*#?\d+.*?(?:牵头完成|一部分)。?",
    r"此项工作.*?KEP.*?SIG.*?。?",
    r"此项工作.*?KEP.*?WG.*?。?",
    r"KEP\s*#?\d+",
    r"由\s*SIG\s*\w+\s*.*?牵头完成。?",
    r"由\s*WG\s*\w+\s*.*?牵头完成。?",
    r"由\s*SIG\s*\w+\s*牵头完成。?",
    r"由\s*WG\s*\w+\s*牵头完成。?",
    r"如需查看详细用法.*?。",
    r"请参考文档.*?。",
    r"关于\s*\w+\s*上的.*?可参见.*?。",
]

_STAGEN_MAP_CN = {
    "Stable": "GA",
    "Beta": "Beta",
    "Alpha": "Alpha",
}

_VALUE_DOMAIN_TEMPLATES = {
    "存储": "提升存储管理灵活性与运维效率",
    "网络": "增强网络管控能力与安全性",
    "安全": "提升安全防护能力与最小权限控制",
    "调度": "提升调度灵活性与资源利用率",
    "Node": "增强节点管理能力与稳定性",
    "API": "提升 API 可管理性与扩展性",
    "扩缩容": "提升自动伸缩能力与资源利用率",
    "运维": "提升运维可观测性与排查效率",
    "可靠": "提升系统可靠性与故障恢复能力",
    "性能": "提升系统性能与资源利用效率",
}

_VALUE_BENEFIT_KEYWORDS = [
    "提升", "降低", "简化", "消除", "改善", "防止", "避免", "确保",
    "减少", "加速", "统一", "收紧", "缓解", "无需", "隔离", "收敛",
    "恢复", "保障", "减轻", "缩短", "增强", "替代", "保护",
]


def _strip_blog_metadata(text: str) -> str:
    for pat in _BLOG_NOISE_PATTERNS:
        text = re.sub(pat, "", text)
    return text.strip()


def _classify_sentence(s: str, ver: str) -> str:
    """把句子分类, 返回主要角色。

    分类优先级 (高→低):
      noise > stage > feature > benefit > pain > background > other

    关键改进: 含方案动词(允许/支持/引入/提供)的句子优先分类为 feature,
    即使它同时含收益词(从而/使得)。这样 _build_enhancement 能使用它。
    """
    if re.search(r"KEP\s*#?\d|由\s*SIG\s*\w|由\s*WG\s*\w|此项工作|如需查看|请参考文档|可参见", s):
        return "noise"

    is_stage = (
        (ver and ver in s and any(kw in s for kw in ["晋升为", "升级为", "稳定版", "GA", "Beta", "Alpha", "默认启用"]))
        or bool(re.search(r"作为\s*(?:Alpha|Beta)\s*引入", s))
        or bool(re.search(r"在\s*v\d+\.\d+\s*中(?:仍|也)?(?:处于|属于)", s))
    )

    is_feature = (
        any(s.startswith(p) for p in _SOLUTION_START_WORDS)
        or (re.match(r"^(Kubernetes|kubelet|kube-scheduler|kubectl|API\s*Server|Volume[A-Z]|DRA|Pod|CRD|CSI|DSR)", s) and any(kw in s for kw in _SOLUTION_VERBS))
        or any(s.startswith(p) for p in _SOLUTION_VERBS)
        or bool(re.match(r"^[A-Z][A-Za-z\s]+(?:是一种|已|现已|现在|允许|支持)", s))
        or any(kw in s for kw in ["允许", "支持", "提供", "实现"]) and any(kw in s for kw in ["引入", "新增", "现已", "现在", "该特性", "这一特性"])
    )

    has_benefit = any(kw in s for kw in _BENEFIT_CLAUSE_MARKERS)

    is_pain = any(kw in s for kw in _PAIN_MARKERS) and not is_feature
    is_background = any(s.startswith(p) for p in ["默认", "传统", "此前", "过去", "原本", "以往"])

    if is_feature:
        return "feature"
    if is_stage and not is_feature:
        return "stage"
    if has_benefit and not is_feature:
        return "benefit"
    if is_pain:
        return "pain"
    if is_background:
        return "background"
    return "other"


def _overlaps(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a_c, b_c = a.strip(), b.strip()
    if a_c == b_c:
        return True
    if len(a_c) > 8 and a_c in b_c:
        return True
    if len(b_c) > 8 and b_c in a_c:
        return True
    if len(a_c) >= 10 and len(b_c) >= 10:
        for i in range(len(a_c) - 10):
            if a_c[i:i+10] in b_c:
                return True
    return False


def _truncate_pain(text: str, max_len: int = 80) -> str:
    text = text.strip().rstrip("，；：")
    if not text.endswith("。"):
        text += "。"
    if len(text) <= max_len:
        return text
    for sep in ["。", "；"]:
        if sep in text:
            parts = text.split(sep)
            for p in parts:
                if len(p) >= 15:
                    candidate = p.strip() + "。"
                    if len(candidate) <= max_len:
                        return candidate
    if "，" in text:
        idx = 0
        while idx < len(text):
            next_comma = text.find("，", idx + 1)
            if next_comma == -1 or next_comma > max_len:
                break
            idx = next_comma
        if idx > 15:
            return text[:idx].strip() + "。"
    return text[:max_len].rstrip("，；：") + "。"


def _extract_pain_point(sents: list[str], classified: list[str], feature: Feature, name: str) -> str:
    """提取痛点 (现状)。

    优先级: pain 句 > background 句 > other 句 > 从 feature 句反推(<=30字)

    质量约束: 选出的句子必须含问题词(无法/难以/缺乏/不一致/风险/限制/依赖/失败/不足),
    否则视为不是真实痛点, 继续尝试下一优先级, 最终走反推。
    """
    from .text_utils import _truncate_cn

    _PROBLEM_WORDS = ("无法", "难以", "缺乏", "不一致", "风险", "限制", "依赖", "失败", "不足", "不能", "缺少", "不存在")

    def _is_real_pain(text: str) -> bool:
        return any(w in text for w in _PROBLEM_WORDS)

    for s, role in zip(sents, classified):
        if role == "pain":
            cleaned = _strip_blog_metadata(s)
            if len(cleaned) >= 12 and _is_real_pain(cleaned):
                return _truncate_pain(cleaned)

    for s, role in zip(sents, classified):
        if role == "background":
            cleaned = _strip_blog_metadata(s)
            if len(cleaned) >= 12 and _is_real_pain(cleaned):
                return _truncate_pain(cleaned)

    for s, role in zip(sents, classified):
        if role == "other" and len(s) >= 12:
            cleaned = _strip_blog_metadata(s)
            if len(cleaned) >= 12 and _is_real_pain(cleaned):
                return _truncate_pain(cleaned)

    # 无含问题词的句子时，从 feature 句反推痛点
    return _derive_pain_from_feature(sents, classified, feature, name)


def _derive_pain_from_feature(sents: list[str], classified: list[str],
                                feature: Feature, name: str) -> str:
    """从功能描述句反推痛点 (压缩到<=30字)。

    "允许用户在存储提供商不支持时取消扩容操作" → "此前无法取消扩容操作"
    策略: 从"允许/支持/可以"后提取最近的一个动词短语(5-20字), 而非整个从句。
    """
    for s, role in zip(sents, classified):
        if role not in ("feature", "benefit"):
            continue
        for verb in ["允许", "支持", "可以", "能够"]:
            m = re.search(rf"{verb}(.+?)(?:[。，,；]|$)", s)
            if m:
                raw = m.group(1).strip().rstrip("。，；")
                # If the clause is too long (>25 chars), try to find a shorter action
                if len(raw) > 25:
                    # Look for a noun phrase at the end (last 5-20 chars before punctuation)
                    short = re.search(r"([\u4e00-\u9fff]{3,15}(?:操作|能力|配置|机制|功能|行为|方式|方法|请求|策略|标准))", raw)
                    if short:
                        return f"此前无法{short.group(1)}。"
                    # Take last 10-20 chars
                    if len(raw) > 10:
                        return f"此前无法{raw[-20:].strip()}。"
                if 5 <= len(raw) <= 25:
                    return f"此前无法{raw}。"
        body = re.sub(r"^(该特性|这一特性|此项工作|该功能|此功能|Kubernetes|kubelet|kube-scheduler|kubectl|DSR)\s*", "", s)
        body = re.sub(r"^(引入了|新增了?|现已|现在可以?|允许|支持|使用户|使得|可以)\s*(用户\s*)?(可以\s*)?", "", body)
        body = body[:20].rstrip("，；：")
        if body and len(body) >= 5:
            return f"此前{name}缺乏{body[:12]}的能力。"
    return f"此前{name}缺乏原生支持。"


def _clean_stage_redundancy(text: str, ver: str) -> str:
    # Split on stage declarations in the middle; keep parts before and after
    stage_split = re.split(r"[，,]?\s*(?:在\s*)?v\d+\.\d+\s*(?:中)?(?:晋升|升级|进入)为?\s*(?:稳定版|GA|Beta|Alpha)(?:\s*(?:并|且)\s*默认启用)?[，。]?", text)
    if len(stage_split) > 1:
        parts = [p.strip() for p in stage_split if p and p.strip() and len(p.strip()) >= 5]
        if parts:
            text = "，".join(parts)
    text = re.sub(r"[，,]?\s*(?:已于|并于|并在|而在|已于|于|在)?\s*v\d+\.\d+(?:\s*中)?(?:晋升|升级|进入)为?\s*(?:稳定版|GA|Beta|Alpha)(?:，且默认启用)?。?$", "", text)
    text = re.sub(r"[，,]?\s*该特性\s*(?:在\s*)?v?\d+\.\d+(?:\s*中)?(?:仍|也)?(?:处于|属于)?\s*(?:Beta|Alpha|GA).*$", "", text)
    text = re.sub(r"[，,]?\s*该特性(?:最初|首次|已于)?\s*(?:于)?\s*v?\d+\.\d+.*?(?:晋升|升级|稳定|GA|Beta).*$", "", text)
    text = re.sub(r"[，,]?\s*(?:最初|首次)于\s*v\d+\.\d+\s*(?:作为\s*)?(?:Alpha|Beta)\s*引入.*$", "", text)
    text = re.sub(r"[，,]?\s*作为\s*(?:Alpha|Beta)\s*引入.*$", "", text)
    text = re.sub(r"[，,]?\s*于\s*v\d+\.\d+\s*(?:晋升|升级)为.*$", "", text)
    text = re.sub(r"[，,]?\s*在\s*v\d+\.\d+\s*中(?:仍|也)?(?:处于|属于)\s*(?:Beta|Alpha|GA).*$", "", text)
    text = re.sub(r"[，,]?\s*当时由环境变量.*$", "", text)
    text = re.sub(r"[，,]?\s*Kubernetes\s*v\d+\.\d+\s*引入了.*$", "", text)
    text = re.sub(r"[，,]?\s*Kubernetes\s*v\d+\.\d+\s*(?:通过|中|引入).*$", "", text)
    text = re.sub(r"[，,]?\s*在\s*Kubernetes\s*v\d+\.\d+\s*中.*$", "", text)
    text = re.sub(r"[，,]?\s*在\s*\w+\s*特性门控之下.*$", "", text)
    text = re.sub(r"[，,]?\s*Pod.*?在\s*v\d+\.\d+\s*(?:晋升|升级)为?\s*Beta.*?$", "", text)
    text = re.sub(r"[，,]?\s*\w+\s*已在\s*v\d+\.\d+\s*(?:晋升|升级).*$", "", text)
    text = re.sub(r"[，,]?\s*v\d+\.\d+\s*(?:晋升|升级)为\s*(?:稳定版|GA|Beta|Alpha).*$", "", text)
    text = re.sub(r"[，,]?\s*(?:而在|在)?\s*v\d+\.\d+\s*中(?:又)?(?:进一步)?得到改进[，,]?\s*", "，", text)
    return text.strip("，。；")


def _build_enhancement(sents: list[str], classified: list[str],
                       feature: Feature, name: str, used_pain: str = "") -> str:
    """构建增强句: v{ver} 将 {name} 升级为 {stage}，{behavior}

    behavior 来源优先级:
      1. feature 句 (功能行为描述)
      2. benefit 句 (含"从而"的功能+收益描述, 取"从而"前的部分)
      3. other 句 (含方案动词的普通句)
      4. stage 句 (清洗后提取行为部分)
      5. 仅前缀 (无可用行为句)

    当痛点为反推生成(此前无法/缺乏)时, 放宽与痛点的重叠检查,
    因为反推痛点本身就来自功能描述句。
    """
    from .text_utils import _truncate_cn
    ver = feature.version
    stage = _STAGEN_MAP_CN.get(feature.section, feature.section)
    prefix = f"v{ver} 将{name}升级为 {stage}"

    pain_is_derived = used_pain.startswith("此前") and ("无法" in used_pain or "缺乏" in used_pain)

    def _check_overlap(s):
        if pain_is_derived:
            return False
        has_solution = any(kw in s for kw in _SOLUTION_VERBS) or any(s.startswith(p) for p in _SOLUTION_START_WORDS)
        return _overlaps(s, used_pain) and len(used_pain) > 20 and not has_solution

    for s, role in zip(sents, classified):
        if role != "feature" or _check_overlap(s):
            continue
        behavior = _strip_blog_metadata(s)
        behavior = re.sub(r"^(该特性|这一特性|此项工作|这一变更|该功能|此功能|为了解决这一[问题限制][，,]?\s*)", "", behavior)
        behavior = _clean_stage_redundancy(behavior, ver)
        if behavior and len(behavior) >= 10:
            return f"{prefix}，{_truncate_cn(behavior, 100)}"

    for s, role in zip(sents, classified):
        if role != "benefit" or _check_overlap(s):
            continue
        behavior = _strip_blog_metadata(s)
        for marker in _BENEFIT_CLAUSE_MARKERS:
            if marker in behavior:
                pre_marker = behavior[:behavior.find(marker)].rstrip("，。；")
                if len(pre_marker) >= 10:
                    behavior = pre_marker
                    break
        behavior = re.sub(r"^(该特性|这一特性|此项工作|该功能|此功能|为了解决)", "", behavior)
        behavior = _clean_stage_redundancy(behavior, ver)
        if behavior and len(behavior) >= 10:
            return f"{prefix}，{_truncate_cn(behavior, 100)}"

    for s, role in zip(sents, classified):
        if role != "other" or _check_overlap(s):
            continue
        behavior = _strip_blog_metadata(s)
        behavior = _clean_stage_redundancy(behavior, ver)
        if behavior and len(behavior) >= 10:
            return f"{prefix}，{_truncate_cn(behavior, 100)}"

    for s, role in zip(sents, classified):
        if role != "stage" or _check_overlap(s):
            continue
        behavior = _strip_blog_metadata(s)
        behavior = re.sub(r"(?:在\s*)?v\d+\.\d+\s*作为\s*(?:Alpha|Beta)\s*引入[，,]?\s*(?:并\s*)?(?:已于\s*)?", "", behavior)
        behavior = re.sub(r"这一改进\s*", "", behavior)
        m = re.search(r"包括(.+)$", behavior)
        if m:
            behavior = "包括" + m.group(1)
        else:
            parts = re.split(r"[，,]\s*(?:并于|并在|而在|该特性|如需|当时|包括)", behavior)
            behavior = parts[0] if parts else behavior
        behavior = _clean_stage_redundancy(behavior, ver)
        if behavior and len(behavior) >= 10:
            return f"{prefix}，{_truncate_cn(behavior, 100)}"

    return prefix


_VALUE_BEHAVIOR_MAP = [
    ("在线对卷进行纵向扩展", "在线调整卷性能，平衡成本与资源利用"),
    ("报告.*?DRA.*?资源", "提升专用设备资源可观测性"),
    ("报告.*?分配.*?资源", "提升资源分配可观测性"),
    ("Sleep动作", "提供容器优雅关闭能力"),
    ("环境变量名.*?特殊字符", "支持更多框架的变量名约定"),
    ("直接回送.*?客户端", "减轻负载均衡器压力并降低延迟"),
    ("取消.*?扩容操作", "提高卷扩容成功率"),
    ("修改卷参数", "提升卷参数在线调整能力"),
    ("更细粒度.*?授权", "落实最小权限原则"),
    ("匿名.*?端点.*?白名单", "收紧匿名访问权限范围"),
    ("声明式.*?校验", "提升配置校验可管理性"),
    ("流式.*?编码", "降低大规模列表的内存占用"),
    ("Watch.*?Cache.*?初始化", "提升控制面启动可靠性"),
    ("放宽.*?DNS.*?校验", "提升复杂网络环境兼容性"),
    ("Swap.*?支持", "提升工作负载在内存压力下的稳定性"),
    ("有序.*?删除", "确保资源移除安全且确定"),
    ("重试.*?调度", "提升调度吞吐与资源利用率"),
    ("结构化.*?认证", "提升认证配置可管理性与可审计性"),
    ("AdminAccess", "支持管理员安全访问已分配设备"),
    ("优先级.*?备选", "为设备请求提供灵活的备选策略"),
    ("ContainerRestartRules|容器重启规则", "支持容器级独立重启策略，避免整体重建"),
    ("禁止.*?远程探针|forbids.*?remote", "收紧安全标准，防止探针绕过安全控制"),
    ("降低内存使用量", "支持降低内存调整量，优化资源利用"),
    ("Recovery from volume expansion|从卷扩容失败中恢复", "提高卷扩容成功率，降低运维成本"),
    ("Direct Service Return|DSR", "减轻负载均衡器压力并降低网络延迟"),
    ("In-place Pod resize|原地调整资源", "支持容器资源原地调整，避免重建丢失进度"),
]


def _synthesize_value_from_behavior(enh: str, feature: Feature, name: str) -> str:
    if not enh:
        return ""
    text = enh + " " + (feature.name or "") + " " + (feature.description_en or "")
    for pattern, template in _VALUE_BEHAVIOR_MAP:
        if re.search(pattern, text, re.I):
            return template
    return ""


def _build_value_summary(sents: list[str], classified: list[str],
                         feature: Feature, name: str,
                         used_pain: str = "", used_enh: str = "") -> str:
    """合成价值分析: 15-35字收益概括。"""
    from .text_utils import _truncate_cn
    ver = feature.version

    for s, role in zip(sents, classified):
        if role != "benefit" or _overlaps(s, used_pain) or _overlaps(s, used_enh):
            continue
        for marker in _BENEFIT_CLAUSE_MARKERS:
            if marker in s:
                idx = s.find(marker)
                clause = s[idx:].rstrip("。。，；")
                clause = re.sub(r"^(从而|使得|有助于|确保|其主要收益在于[，,]?\s*|显著)", "", clause)
                clause = _clean_stage_redundancy(clause, ver)
                clause = clause.strip("，。；")
                if 10 <= len(clause) <= 40:
                    return clause

    for s, role in zip(sents, classified):
        if role in ("noise", "stage") or _overlaps(s, used_pain) or _overlaps(s, used_enh):
            continue
        if 12 <= len(s) <= 40 and any(kw in s for kw in _VALUE_BENEFIT_KEYWORDS):
            cleaned = s.rstrip("。。，；")
            if len(cleaned) >= 10:
                return cleaned

    for s, role in zip(sents, classified):
        if role in ("noise", "stage") or _overlaps(s, used_pain) or _overlaps(s, used_enh):
            continue
        if any(kw in s for kw in _VALUE_BENEFIT_KEYWORDS):
            for marker in ["从而", "使得", "有助于", "确保", "能够", "可以"]:
                if marker in s:
                    idx = s.find(marker)
                    clause = s[idx:idx + 35]
                    clause = re.sub(r"^(从而|使得|有助于|确保|能够|可以)", "", clause)
                    clause = clause.rstrip("。。，；")
                    if len(clause) >= 10:
                        return clause
            cleaned = _truncate_cn(s, 35).rstrip("。。，；")
            if len(cleaned) >= 10:
                return cleaned

    if used_enh:
        for marker in _BENEFIT_CLAUSE_MARKERS:
            if marker in used_enh:
                idx = used_enh.find(marker)
                clause = used_enh[idx:]
                clause = re.sub(r"^(从而|使得|有助于|确保|其主要收益在于[，,]?\s*|显著)", "", clause)
                clause = _clean_stage_redundancy(clause, ver)
                clause = clause.strip("，。；")
                if 10 <= len(clause) <= 35:
                    return clause

    value_synthesized = _synthesize_value_from_behavior(used_enh, feature, name)
    if value_synthesized:
        return value_synthesized

    domain = classify_domain(name + " " + (feature.description_en or ""))
    for domain_key, template in _VALUE_DOMAIN_TEMPLATES.items():
        if domain_key in domain:
            return template

    return f"增强{name[:15]}的管理与运维能力"


def _generate_blog_analysis(feature: Feature) -> tuple[str, str]:
    """直接从博客中文描述生成 intro + value。

    六步:
      1. 分句 + 去噪声
      2. 逐句角色分类 (noise/stage/background/pain/feature/benefit/other)
      3. 提取痛点 (pain > background > other > 反推)
      4. 构建增强句 (feature 句 > stage 句 > 仅前缀)
      5. 合成价值分析 (benefit 句 > 含收益词的短句 > 行为映射 > 领域模板)
      6. 三段互斥检查
    """
    from .text_utils import _split_zh_sentences

    desc = feature.description_zh or ""
    name = feature.name_zh or feature.name
    if not desc:
        return "", ""

    sents = _split_zh_sentences(desc)
    sents = [_strip_blog_metadata(s).strip() for s in sents]
    sents = [s for s in sents if s and len(s) >= 5]
    if not sents:
        return "", ""

    ver = feature.version
    classified = [_classify_sentence(s, ver) for s in sents]

    pain = _extract_pain_point(sents, classified, feature, name)
    enhancement = _build_enhancement(sents, classified, feature, name, used_pain=pain)
    value = _build_value_summary(sents, classified, feature, name, used_pain=pain, used_enh=enhancement)

    intro = f"现状：{pain}\n本特性增强：{enhancement}"
    intro = re.sub(r"。+", "。", intro)
    intro = re.sub(r"。$", "", intro)
    if not intro.endswith("。") and not intro.endswith("）"):
        intro += "。"
    if value:
        value = value.rstrip("。") + "。"

    return intro, value


def _generate_value_fallback(feature: Feature, intro: str) -> str:
    """当 zh 管线未提取到价值句时, 从描述或关键词生成简单兜底。"""
    desc = feature.description_zh or ""
    if not desc:
        return ""
    for kw in _VALUE_BENEFIT_KEYWORDS:
        idx = desc.find(kw)
        if idx >= 0:
            end = desc.find("。", idx)
            if end < 0:
                end = min(idx + 40, len(desc))
            frag = desc[idx:end].strip().rstrip("。，；")
            if len(frag) >= 12:
                return frag
    sents = re.split(r"[。；\n]", desc)
    for s in sents:
        s = s.strip()
        if 15 <= len(s) <= 35 and any(kw in s for kw in _VALUE_BENEFIT_KEYWORDS):
            return s
    return ""


def generate_feature_content(feature: Feature) -> dict[str, str]:
    """为单个特性生成中文分析内容。

    优先使用官方中文博客描述 (无需翻译API, 质量最高, 速度最快)。
    无中文描述时, 对英文描述做一次批量翻译, 再用中文管线提取。
    不做联网补充 (已熔断或不可达时不浪费时间)。
    """
    from autok8s.common.logging import get_logger
    _logger = get_logger("content")

    domain = classify_domain(feature.name + " " + feature.description_en)
    section_label_map = {
        "Stable": f"孵化成熟特性:{feature.version}",
        "Beta": f"增强特性：{feature.version}",
        "Alpha": f"新增特性：{feature.version}",
    }
    base_row = {
        "分类": section_label_map.get(feature.section, f"新增特性：{feature.version}"),
        "特性名称": feature.name,
        "推动公司": "",
        "特性价值领域": domain,
    }

    if not feature.description_zh:
        from autok8s.common.translate import translate_to_chinese
        translated = translate_to_chinese(feature.description_en[:1800])
        if translated and len(re.findall(r"[\u4e00-\u9fff]", translated)) >= 5:
            feature.description_zh = translated
            if not feature.name_zh:
                feature.name_zh = feature.name

    intro, value = _generate_blog_analysis(feature)

    if not intro or len(intro.strip()) < 20:
        prefix = _stage_prefix(feature, feature.name_zh or feature.name)
        desc = feature.description_zh or feature.description_en
        intro = f"现状：{desc[:100].strip()}\n本特性增强：{prefix}。"
        _logger.info("[博客] %s: 中文描述不足, 用描述首句兜底", feature.name)
    else:
        _logger.info("[博客] %s: 基于官方中文描述生成", feature.name)

    if not value or len(value.strip()) < 12:
        value = _generate_value_fallback(feature, intro)

    intro = re.sub(r"。+", "。", intro)
    intro = re.sub(r"。$", "", intro)
    if not intro.endswith("。") and not intro.endswith("）"):
        intro += "。"
    if value:
        value = value.rstrip("。") + "。"

    ok, v_issues = verify_content(intro, value, feature, None)
    if ok:
        return {**base_row, "特性功能介绍": intro, "特性功能价值分析": value}

    pain_issues = [i for i in v_issues if "pain" in i or "intro" in i or "version" in i or "stage" in i or "enhancement" in i]
    if not pain_issues:
        _logger.info("[质量门] %s 介绍通过但价值未通过 %s；仅价值字段留空", feature.name, v_issues)
        return {**base_row, "特性功能介绍": intro, "特性功能价值分析": ""}

    _logger.warning("[质量门] %s 博客回退内容未通过验证 %s；读者字段留空", feature.name, v_issues)
    return {**base_row, "特性功能介绍": "", "特性功能价值分析": ""}


def generate_analysis(blog_data: BlogData) -> dict:
    """生成完整分析数据 (并行处理特性/弃用)。"""
    feature_rows = _parallel_generate(
        blog_data.features, _generate_feature_content_safe,
    )
    deprecation_rows = _parallel_generate(
        blog_data.deprecations, _generate_deprecation_content_safe,
    )
    return {
        "version": blog_data.version,
        "title": f"kubernetes v{blog_data.version} Release Note解读",
        "features": feature_rows,
        "deprecations": deprecation_rows,
    }


def generate_multi_version_analysis(all_blog_data: list[BlogData]) -> dict:
    """合并多版本分析数据, 版本号从高到低排列 (并行处理)。"""
    def _ver_tuple(v: str) -> tuple[int, int]:
        parts = v.split(".")
        return (int(parts[0]), int(parts[1])) if len(parts) == 2 else (0, 0)

    def _section_rank(feat: dict) -> int:
        cat = feat["分类"]
        if "孵化" in cat: return 0
        if "增强" in cat: return 1
        if "新增" in cat: return 2
        return 3

    def _ver_from_cat(cat: str) -> tuple[int, int]:
        for sep in (":", "："):
            if sep in cat:
                return _ver_tuple(cat.split(sep)[-1].strip())
        return (0, 0)

    all_features = [f for b in all_blog_data for f in b.features]
    all_deprecations = [d for b in all_blog_data for d in b.deprecations]

    feature_rows = _parallel_generate(all_features, _generate_feature_content_safe)
    deprecation_rows = _parallel_generate(all_deprecations, _generate_deprecation_content_safe)

    feature_rows.sort(key=lambda x: (-_ver_from_cat(x["分类"])[0], -_ver_from_cat(x["分类"])[1], _section_rank(x)))
    deprecation_rows.sort(key=lambda x: (-_ver_from_cat(x["分类"])[0], -_ver_from_cat(x["分类"])[1]))

    versions = [b.version for b in all_blog_data]
    lo = min(versions, key=_ver_tuple)
    hi = max(versions, key=_ver_tuple)

    return {
        "version": hi,
        "title": f"kubernetes v{lo}-v{hi} Release Note解读",
        "features": feature_rows,
        "deprecations": deprecation_rows,
    }
