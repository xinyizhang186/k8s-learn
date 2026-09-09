"""keywords.py — 正则管线关键词表 (从 content_gen.py 抽出, 外置便于维护)。"""
from __future__ import annotations

import re

_PROBLEM_KEYWORDS = [
    "previously", "before", "historically", "until now", "traditionally",
    "in the past", "has been", "required", "currently", "lacked",
    "could not", "was not", "were not", "cannot", "forced", "limitation",
    "challenge", "difficult", "issue", "problem", "concern", "risk",
    "vulnerab", "gap", "missing", "unable", "no way", "no built",
    "relied on", "depended on", "suffered", "however", "often led",
    "was tightly coupled", "creating", "meant that", "meant",
    "while effective", "while it offered", "maintaining",
    "historically relied", "traditionally relied",
]

_SOLUTION_KEYWORDS = [
    "v1.", "graduates", "graduated", "introduces", "introduced", "enables",
    "this feature", "this enhancement", "this update", "now ", "allows",
    "provides", "supports", "replaces", "eliminates", "reduces", "improves",
    "moves beyond", "addresses", "simplifies", "reaches", "takes",
    "container isolation", "node resource", "node security", "security and",
    "the distribution", "the development", "the kubelet", "the primary benefit",
    "a critical layer", "this long-awaited", "this milestone", "this initiative",
    "this change", "this iteration", "this transition", "this update",
    "kubernetes now", "kubernetes v1.",
]

_SKIP_KEYWORDS = [
    "this work was done", "kep #", "led by sig", "led by wg",
    "for detailed", "refer to", "you can find", "read about",
    "you can also track", "for information on", "check the documentation",
    "to learn more", "because these are security", "this is a selection",
    "for a full list", "this release includes",
]

_VALUE_KEYWORDS_CN = [
    "支持", "允许", "提供", "降低", "提升", "简化", "替代", "动态",
    "安全", "消除", "增强", "实现", "改善", "保护", "防止", "避免",
    "确保", "减少", "加速", "统一", "收紧", "原生", "声明式", "缓解",
    "无需", "映射", "隔离",
]

_TRANSLATION_ARTIFACTS = [
    "MYMEMORY WARNING", "translatedText", "Translate API",
    "HTTPError", "URLError", "[ERROR",
]

_NOISE_PATTERNS = [
    r"This work was done as part of KEP #\d+[^.]*\.",
    r"This work was done[^.]*\.",
    r"This enhancement \(which[^.]*\.\)",
    r"led by SIG [A-Za-z /]+\.?",
    r"led by WG [A-Za-z /]+\.?",
    r"For detailed usage instructions[^.]*\.",
    r"refer to the documentation[^.]*\.",
    r"read about[^.]*\.",
    r"you can also track[^.]*\.",
    r"You can find more[^.]*\.",
    r"For information on[^.]*\.",
    r"This is a selection[^.]*\.",
    r"For a full list[^.]*\.",
    r"This release includes a total of[^.]*\.",
    r"Starting from Kubernetes v\d+\.\d+[^.]*\.",
    r"Introduced as alpha in v\d+\.\d+[^.]*\.",
    r"Initially introduced in v\d+\.\d+[^.]*\.",
    r"Graduated to beta[^.]*\.",
    r"This feature was introduced[^.]*\.",
    r"The feature[^.]*remains in beta[^.]*\.",
    r"Because these are security controls[^.]*\.",
    r"check\s+the documentation[^.]*\.",
    r"To learn more[^.]*\.",
    r"KEP #\d+[^.]*\.",
]

_ZH_PAIN_NEGATIVE = ["随着", "这一里程碑", "这一特性", "该特性", "本特性",
                      "现在", "如今", "目前该", "进阶", "晋升", "升级为",
                      "这一期待", "在 kubernetes v", "在 kubernetes",
                      "进入 beta", "进入稳定", "进入 alpha"]

_ZH_PAIN_START = ["过去", "此前", "之前", "历史上", "原本", "原来", "以往",
                  "通常", "传统上", "目前", "当前", "这种", "这种方式",
                  "默认情况下", "如果", "由于", "因为", "在此之前"]
_ZH_PAIN_CONTAINS = [
    "缺乏", "无法", "不能", "不支持", "导致", "迫使", "难以", "缺少",
    "只能", "耦合", "争用", "未支持", "造成", "引发", "问题", "风险",
    "缺点", "不足", "挑战", "限制", "浪费", "死锁", "不理想", "不可变",
    "安全风险", "不一致", "不可靠", "脆弱", "意外", "错误", "失败",
    "粗暴", "往往", "一直", "并不", "并没有", "难以", "遗憾",
]
_ZH_PAIN_FORBIDDEN_RE = re.compile(
    r"在\s*kubernetes\s*v1\.\d+|进阶至.*?(?:稳定|GA|Beta|Alpha)|"
    r"晋升为.*?(?:稳定|GA|Beta|Alpha)|达到正式发布|达到.*?(?:新水平|里程碑)|"
    r"现在可以|如今可以|现已默认|我们很高兴",
    re.I,
)
_ZH_PAIN_VERBOSE_RE = re.compile(
    r"人们才会发现|通常要等到为时已晚|我们很高兴地宣布|"
    r"达到.*?(?:新水平|新高度|重要.*?里程碑|又一个.*?里程碑)|"
    r"这一期待已久|迈出.*?一步|达到新.*?水平",
    re.I,
)
_ZH_ENH_KW = [
    "这一特性", "这一 kep", "这一改进", "该特性", "本特性", "该增强",
    "该 kep", "此 kep", "这一变更", "这一机制", "为了解决",
    "晋升", "进阶", "升级为", "正式发布", "引入", "重构", "解耦",
    "新增", "现已", "通过", "启用", "现在", "允许", "支持",
]
_ZH_ENH_VERSION_KW = ["晋升", "进阶", "升级", "正式发布", "引入", "默认启用",
                      "特性门控", "作为 alpha", "作为 beta"]
_ZH_ENH_CLICHE_RE = re.compile(
    r"我们很高兴|达到.*?(?:新水平|新高度|重要.*?里程碑|又一个.*?里程碑)|"
    r"达到新|迈出.*?一步|达到又一个|达到重要",
    re.I,
)
_ZH_VALUE_KW = [
    "从而", "使得", "让", "有助于", "其主要收益", "其主要模式",
    "这一变更", "这一改进", "这一机制", "提升", "降低", "简化",
    "替代", "消除", "改善", "保护", "防止", "避免", "确保", "减少",
    "加速", "统一", "缓解", "隔离", "无需", "改进", "优化", "恢复",
    "支持", "允许", "提供", "增强", "实现", "去除", "分离", "使你",
    "借助", "彻底", "无需",
]
_ZH_VALUE_SKIP = [
    "此外", "这项工作", "此项工作", "该 kep", "该 kep", "此 kep",
    "随着", "达到", "里程碑", "这一转变", "由 sig", "牵头", "详见",
    "参见", "更多", "请注意", "需要注意的是", "该特性在", "已默认",
    "如需查看", "请参考", "参考文档", "可以找到", "了解更多",
    "这项工作是", "此项工作是", "这部分工作是",
]
_ZH_NOISE_RE = re.compile(
    r"KEP[- ]?\d+|SIG\s|[Ss]ig[A-Z]|牵头完成|参考文档|详见|参见|"
    r"如需查看|请参考|可以找到|了解更多|请注意|需要注意的是|"
    r"请务必|结合文档|如需了解更多|这篇博客",
    re.I,
)
_ZH_PAIN_WEAK_RE = re.compile(
    r"在此前缺乏原生支持或存在明显限制|不具备|没有原生|缺乏原生",
)
