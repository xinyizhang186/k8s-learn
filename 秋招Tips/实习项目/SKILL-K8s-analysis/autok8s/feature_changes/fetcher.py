"""fetcher.py — 在线获取 KEP 摘要并翻译为中文, 自动填充排查方法与详细说明。

流程:
  1. 从 go 注释提取 KEP 编号
  2. 在线抓取 kubernetes/enhancements 仓库的 KEP README
  3. 提取 Summary / Motivation / Proposal 段落
  4. 调用翻译 API (Google Translate / MyMemory 备选) 将英文翻译为中文
  5. 生成排查方法 (Summary 翻译) 与详细说明 (Motivation+Proposal 翻译)

无 KEP 链接的特性: 翻译 go 注释中的英文描述作为排查方法。
所有输出均为中文, 不使用英文 fallback。

溯源: 返回结果中包含 source_en (英文原文) / source_type (来源类型) / kep_url,
      供 xlsx 核查列和审计日志使用。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional


_FETCH_TIMEOUT = 20
_CACHE: dict[str, dict] = {}
_KEP_PATH_CACHE: dict[str, Optional[str]] = {}
_KEP_TREE: Optional[list[str]] = None

_UA = "Mozilla/5.0 (K8sFeatureChangeAnalysis/1.0; K8sFeatureChangeAnalysis)"

_SOURCE_KEP_README = "KEP README"
_SOURCE_GITHUB_ISSUE = "GitHub Issue"
_SOURCE_GO_DESC = "go 注释翻译"
_SOURCE_MANUAL = "人工原行"
_SOURCE_NONE = ""


def _fetch_url(url: str, accept: str = "text/html") -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None


def _extract_kep_number(kep_url: str) -> Optional[str]:
    m = re.search(r"kep\.k8s\.io/(\d+)", kep_url)
    return m.group(1) if m else None


def _fetch_kep_readme(kep_num: str) -> tuple[Optional[str], Optional[str]]:
    """返回 (readme_text, readme_url)。"""
    path = _find_kep_readme_path(kep_num)
    if path:
        readme_url = f"https://raw.githubusercontent.com/kubernetes/enhancements/master/{path}"
        readme = _fetch_url(readme_url)
        if readme and len(readme) > 200:
            return readme, readme_url

    return None, None


def _find_kep_readme_path(kep_num: str) -> Optional[str]:
    """Locate a KEP once per process instead of querying GitHub for every row."""
    if kep_num in _KEP_PATH_CACHE:
        return _KEP_PATH_CACHE[kep_num]
    global _KEP_TREE
    if _KEP_TREE is None:
        tree_url = "https://api.github.com/repos/kubernetes/enhancements/git/trees/master?recursive=1"
        payload = _fetch_url(tree_url, accept="application/vnd.github.v3+json")
        try:
            data = json.loads(payload) if payload else {}
            _KEP_TREE = [item.get("path", "") for item in data.get("tree", [])]
        except (ValueError, AttributeError):
            _KEP_TREE = []
    prefix = f"/{kep_num}-"
    candidates = [
        path for path in _KEP_TREE
        if path.startswith("keps/") and prefix in path and path.endswith("/README.md")
    ]
    # Some older KEPs are a single Markdown file rather than a README directory.
    if not candidates:
        candidates = [
            path for path in _KEP_TREE
            if path.startswith("keps/") and prefix in path and path.endswith(".md")
        ]
    result = candidates[0] if candidates else None
    _KEP_PATH_CACHE[kep_num] = result
    return result


def _truncate_at_sentence_boundary(text: str, max_chars: int) -> str:
    """按句子边界截断, 丢弃末尾不完整的句子, 避免半句翻译。

    例: "Sentence one. Sentence two. Partial sente" -> "Sentence one. Sentence two."
    """
    if not text or len(text) <= max_chars:
        return text or ""
    cut = text[:max_chars]
    last_stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_stop > max_chars // 2:
        return cut[:last_stop + 1].strip()
    if cut.rstrip().endswith((".", "!", "?")):
        return cut.rstrip()
    return cut.rsplit(" ", 1)[0].rstrip(",;: ") if " " in cut else cut


def _clean_text(text: str) -> str:
    # 剥离 YAML frontmatter 块 (KEP README 开头的 --- ... --- 元数据)
    text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\n>\s*[^\n]+\n", "\n", text)
    text = re.sub(r"[`*_#>]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*-\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # 过滤 KEP YAML frontmatter 字段行 (Stage/Status/SIG/owner/kep/讨论链接 等, 含中英变体)
    text = re.sub(r"^\s*(Stage|Status|SIG|Approver|Author|Owner|KEP|Discussion|Tracking|Review|Tracker|Replaces|Superseded|Requires|Depends|Latest|kubernetes/[\w-]+|kubernetes-sigs/[\w-]+|kubernetes\.k8s\.io/[\w-]+)\s*[:：].*$",
                  "", text, flags=re.MULTILINE | re.I)
    # 过滤 KEP-XXXX 编号行 (frontmatter 残留)
    text = re.sub(r"^\s*KEP[- ]?\d{1,5}\s*$", "", text, flags=re.MULTILINE | re.I)
    # 过滤机翻产生的 KEP 元数据 (中英变体, 含行内夹杂)
    text = re.sub(r"[Kk]ubernetes\s*(增强提案|增强|enhancement\s*proposal)\s*[:：]",
                  "", text, flags=re.I)
    text = re.sub(r"讨论链接\s*[:：]\s*\S*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()





def _truncate_cn_at_sentence(text: str, max_chars: int) -> str:
    """中文文本按句号边界截断, 丢弃末尾不完整的句子, 并兜底补句号。

    翻译后的中文若直接 [:300] 截断会切断句子 (如 "调度" 变 "调")。
    在最后的句号/分号处截断, 保证语义完整。同时剥离机翻产生的 KEP 元数据和已知误译。
    """
    if not text:
        return ""
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    text = text.replace("租赁", "Lease").replace("吊舱", "Pod").replace("豆荚", "Pod")
    text = text.replace("观看流", "watch 流").replace("取决于", "依赖")
    text = text.replace("的功能门", "特性门").replace("此功能门", "此特性门").replace("功能门以恢复", "特性门以恢复")
    text = re.sub(r"^(beta|alpha|ga)\s*[：:]\s*v1\.\d+\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[Kk]ubernetes\s*(增强提案|增强|enhancement\s*proposal)\s*[:：]?", "", text)
    text = re.sub(r"讨论链接\s*[:：]\s*\S*", "", text)
    text = re.sub(r"[，,；;]?\s*[Kk][Ee][Pp]\s*[:：]?\s*$", "", text)
    text = re.sub(r"\n\n", "\x00PARA\x00", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\x00PARA\x00", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.rstrip(" ，,；;:")
    if not text:
        return ""
    if len(text) <= max_chars:
        if text.endswith(("。", "！", "？", ".", "!", "?", "）", ")", "；")):
            return text
        return text + "。"
    cut = text[:max_chars]
    for stop in ("。", "；", "！", "？", ". ", "! ", "? "):
        idx = cut.rfind(stop)
        if idx > max_chars // 2:
            return text[:idx + len(stop)].strip()
    for stop in ("，", "、", ", "):
        idx = cut.rfind(stop)
        if idx > max_chars // 2:
            return text[:idx].rstrip(stop) + "。"
    return cut.rstrip(",，、；; ") + "。"




_SUBSECTION_HEADINGS = re.compile(
    r"^#+\s*(User\s+Stories?|Goals|Non-Goals|Non\s*Goals|Proposal|Risks|Risks\s+and\s+Mitigations|Design\s+Details|Alternatives|Implementation\s+History|Graduation\s+Criteria|Notes?|Examples?|Test\s+Plan)\b",
    re.IGNORECASE,
)


def _extract_sections(readme: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    in_subsection = False
    buf: list[str] = []
    for line in readme.splitlines():
        m = re.match(r"^#+\s*(Summary|Motivation|Proposal|Goals|Objective|Introduction)\b", line, re.I)
        sub = _SUBSECTION_HEADINGS.match(line)
        if m:
            if current:
                sections[current] = _clean_text("\n".join(buf))
            current = m.group(1).capitalize()
            buf = []
            in_subsection = False
        elif sub and current:
            in_subsection = True
        elif in_subsection:
            continue
        else:
            buf.append(line)
    if current:
        sections[current] = _clean_text("\n".join(buf))
    return sections


def _translate_google(text: str) -> Optional[str]:
    if not text or len(text.strip()) < 10:
        return None
    encoded = urllib.parse.quote(text[:2000])
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q={encoded}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return "".join(s[0] for s in data[0] if s and s[0])
    except Exception as e:
        from autok8s.common.logging import get_logger
        get_logger("fetcher").debug("Google 翻译失败: %s", e)
        return None


def _translate_mymemory(text: str) -> Optional[str]:
    if not text or len(text.strip()) < 10:
        return None
    encoded = urllib.parse.quote(text[:500])
    url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|zh-CN"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("responseData", {}).get("translatedText", "")
        if result and len(result) > 5:
            if "MYMEMORY WARNING" in result.upper() or "INVALID" in result.upper():
                return None
            return result
        return None
    except Exception as e:
        from autok8s.common.logging import get_logger
        get_logger("fetcher").debug("MyMemory 翻译失败: %s", e)
        return None


def translate_to_chinese(text: str) -> tuple[Optional[str], Optional[str]]:
    """翻译英文文本为中文。优先 Google Translate, 失败用 MyMemory。

    返回 (中文翻译, 翻译引擎名称)。"""
    if not text or not text.strip():
        return None, None
    text = text.strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    if not text or len(text) < 10:
        return None, None
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    if cn >= 10:
        return text, "已是中文"

    for name, fn in [("Google Translate", _translate_google), ("MyMemory", _translate_mymemory)]:
        result = fn(text)
        if result and len(re.findall(r'[\u4e00-\u9fff]', result)) >= 3:
            return result, name
    return None, None


def _summarize_readme(readme: str, readme_url: str) -> dict[str, Optional[str]]:
    """从 KEP README 提取并翻译 Summary/Motivation/Proposal。"""
    sections = _extract_sections(readme)

    summary_en = sections.get("Summary", "")
    motivation_en = sections.get("Motivation", "")
    proposal_en = sections.get("Proposal", sections.get("Goals", ""))

    排查方法 = None
    排查方法_en = None
    详细说明 = None
    详细说明_en = None
    engine_chk = None
    engine_det = None

    if summary_en:
        sents = re.split(r"(?<=[.!?])\s+", summary_en)
        first_sents = " ".join(sents[:3]).strip()
        if first_sents and len(first_sents) > 20:
            截断 = _truncate_at_sentence_boundary(first_sents, 400)
            排查方法, engine_chk = translate_to_chinese(截断)
            if 排查方法:
                排查方法 = _truncate_cn_at_sentence(排查方法, 300)
                排查方法_en = 截断[:300]

    detail_en_parts = []
    for part in [motivation_en, proposal_en]:
        if part:
            clean = _clean_text(part)
            sents = re.split(r"(?<=[.!?])\s+", clean)
            if sents:
                detail_en_parts.append(_truncate_at_sentence_boundary(
                    " ".join(sents[:3]).strip(), 300))

    if detail_en_parts:
        combined_en = " ".join(detail_en_parts)
        if len(combined_en) > 30:
            截断 = _truncate_at_sentence_boundary(combined_en, 500)
            详细说明, engine_det = translate_to_chinese(截断)
            if 详细说明:
                详细说明 = _truncate_cn_at_sentence(详细说明, 400)
                详细说明_en = 截断[:400]

    return {
        "排查方法": 排查方法,
        "详细说明": 详细说明,
        "source_en": (排查方法_en or "") + ((" | " + 详细说明_en) if 详细说明_en else ""),
        "source_type": _SOURCE_KEP_README,
        "source_url": readme_url or "",
        "engine": " / ".join(filter(None, [engine_chk, engine_det])) or "",
    }


def _fetch_kep_issue_page(kep_num: str) -> Optional[dict[str, Optional[str]]]:
    """兜底: 从 GitHub issue 页面提取标题与摘要并翻译。"""
    url = f"https://github.com/kubernetes/enhancements/issues/{kep_num}"
    html = _fetch_url(url)
    if not html:
        return None
    import html as html_unesc
    title_m = re.search(r"<title>([^<]+)</title>", html, re.I)
    title = html_unesc.unescape(title_m.group(1)).strip() if title_m else ""
    title = re.sub(r"\s*\|\s*kubernetes/enhancements.*", "", title).strip()
    title = re.sub(r"^\[KEP[:\s]*\d+\]\s*", "", title, flags=re.I).strip()

    desc_m = re.search(r'<meta name="description" content="([^"]+)"', html, re.I)
    desc = html_unesc.unescape(desc_m.group(1)).strip() if desc_m else ""

    og_m = re.search(r'<meta property="og:description" content="([^"]+)"', html, re.I)
    og_desc = html_unesc.unescape(og_m.group(1)).strip() if og_m else ""

    summary_en = title
    if desc and len(desc) > len(summary_en):
        summary_en = desc
    if og_desc and len(og_desc) > len(summary_en):
        summary_en = og_desc

    summary_en = re.sub(
        r"Enhancement Description One-line enhancement description \(can be used as a release note\):\s*",
        "", summary_en,
    ).strip()
    summary_en = re.sub(r"^-\s*", "", summary_en).strip()

    if not summary_en or len(summary_en) < 15:
        return None

    翻译, engine = translate_to_chinese(_truncate_at_sentence_boundary(summary_en, 400))
    if not 翻译 or len(re.findall(r'[\u4e00-\u9fff]', 翻译)) < 5:
        return None

    详细说明 = None
    详细说明_en = None
    if og_desc and og_desc != title and len(og_desc) > 30:
        clean_og = re.sub(
            r"Enhancement Description One-line enhancement description \(can be used as a release note\):\s*",
            "", og_desc,
        ).strip()
        if len(clean_og) > 30:
            截断 = _truncate_at_sentence_boundary(clean_og, 400)
            详细说明, engine2 = translate_to_chinese(截断)
            详细说明_en = 截断[:400]

    return {
        "排查方法": _truncate_cn_at_sentence(翻译, 300),
        "详细说明": _truncate_cn_at_sentence(详细说明, 400) if 详细说明 else None,
        "source_en": summary_en[:300] + ((" | " + 详细说明_en) if 详细说明_en else ""),
        "source_type": _SOURCE_GITHUB_ISSUE,
        "source_url": url,
        "engine": engine or "",
    }


def fetch_kep_summary(kep_url: str) -> Optional[dict[str, Optional[str]]]:
    if not kep_url:
        return None
    if kep_url in _CACHE:
        return _CACHE[kep_url]

    kep_num = _extract_kep_number(kep_url)
    if not kep_num:
        _CACHE[kep_url] = None
        return None

    readme, readme_url = _fetch_kep_readme(kep_num)
    if readme:
        result = _summarize_readme(readme, readme_url)
        if result["排查方法"] or result["详细说明"]:
            _CACHE[kep_url] = result
            return result

    issue_result = _fetch_kep_issue_page(kep_num)
    if issue_result and (issue_result["排查方法"] or issue_result["详细说明"]):
        _CACHE[kep_url] = issue_result
        return issue_result

    _CACHE[kep_url] = None
    return None


def fetch_feature_narrative(name: str, kep_url: Optional[str], desc: list[str]) -> dict[str, Optional[str]]:
    """获取特性叙事内容并翻译为中文。

    优先 KEP 在线抓取翻译, 无 KEP 链接时翻译 go 注释描述。
    所有输出均为中文, 不使用英文 fallback。

    返回字段:
      排查方法: 中文排查方法
      详细说明: 中文详细说明
      source_en: 翻译前英文原文 (供核查对照)
      source_type: 来源类型 (KEP README / GitHub Issue / go 注释翻译)
      source_url: KEP README 或 GitHub Issue 的 URL
      engine: 翻译引擎 (Google Translate / MyMemory)
    """
    result: dict[str, Optional[str]] = {
        "排查方法": None, "详细说明": None,
        "source_en": None, "source_type": _SOURCE_NONE,
        "source_url": kep_url or "", "engine": None,
    }

    if kep_url:
        kep_result = fetch_kep_summary(kep_url)
        if kep_result:
            result.update(kep_result)

    if not result["排查方法"] and desc:
        combined_desc = " ".join(desc).strip()
        if combined_desc and len(combined_desc) > 10:
            截断 = _truncate_at_sentence_boundary(combined_desc, 400)
            翻译, engine = translate_to_chinese(截断)
            if 翻译:
                result["排查方法"] = _truncate_cn_at_sentence(翻译, 300)
                result["source_en"] = 截断[:300]
                result["source_type"] = _SOURCE_GO_DESC
                result["source_url"] = kep_url or ""
                result["engine"] = engine

    return result
