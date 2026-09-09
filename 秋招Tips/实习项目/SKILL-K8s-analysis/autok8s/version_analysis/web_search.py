"""web_search.py — 联网搜索为不确定特性补充权威上下文, 并支持答案自检。

设计动机:
  content_gen.py 原本只把博客英文描述机器翻译为中文, 在以下场景质量不可靠:
    - 博客描述过短或缺少"痛点/方案"语句
    - 翻译失败导致输出仍是英文
    - 价值摘要回退成特性名本身
  本模块在遇到这类不确定/模糊答案时, 用"特性名 + KEP号 + 版本"作为 key 联网搜索,
  抓取权威页面正文 (KEP markdown / 官方文档 / 社区讨论) 作为补充上下文,
  供 content_gen 重新生成并交叉验证。

搜索策略 (按优先级, 任一失败自动降级):
  1. KEP 直查: 若博客描述里出现 "KEP #NNNN", 直接抓取
     https://raw.githubusercontent.com/kubernetes/enhancements/master/keps/<sig>/NNNN-*.md
     (先通过 GitHub 代码搜索 API 定位文件路径, 无 token 也可用, 限速 10/分钟)
  2. DuckDuckGo HTML 搜索: 广覆盖, 返回标题/URL/摘要
  3. 抓取命中页面正文 (最多 2 个) 拼接为上下文文本

缓存: 进程内字典按 (feature_name, version) 缓存, 避免重复搜索同一特性。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

from .fetcher import Feature
from autok8s.common.quality import content_issues, enhancement_issues, value_issues


_FETCH_TIMEOUT = 5
_KEP_FETCH_TIMEOUT = 10
_KEP_SUMMARY_TIMEOUT = 5
_UA = "Mozilla/5.0 (K8sVersionAnalysis/1.0; K8sReleaseAnalysis)"

_MAX_DDG_FAILURES = 2
_ddg_disabled = False
_ddg_failures = 0
_ddg_lock = threading.Lock()

_MAX_KEP_FETCH_FAILURES = 2
_kep_fetch_disabled = False
_kep_fetch_failures = 0
_kep_fetch_lock = threading.Lock()


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class WebContext:
    """某特性联网搜索得到的补充上下文。"""
    feature_name: str
    version: str
    kep_number: str = ""
    kep_summary: str = ""
    web_snippets: list[str] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        """拼接所有来源为一段上下文文本 (供翻译/抽取使用)。"""
        parts: list[str] = []
        if self.kep_summary:
            parts.append(self.kep_summary)
        if self.web_snippets:
            parts.extend(self.web_snippets)
        if self.page_texts:
            parts.extend(self.page_texts)
        return "\n".join(p for p in parts if p and p.strip())


# (feature_name, version) -> WebContext, 进程内缓存避免重复搜索
# 线程安全: _context_cache_lock 防止多线程并发抓取同一特性
_context_cache: dict[tuple[str, str], WebContext] = {}
_context_cache_locks: dict[tuple[str, str], threading.Lock] = {}
_context_cache_locks_guard = threading.Lock()

# DDG 搜索并发限流 (防止并行抓取时触发限速)
_ddg_semaphore = threading.Semaphore(3)


def _get_context_lock(cache_key: tuple[str, str]) -> threading.Lock:
    with _context_cache_locks_guard:
        if cache_key not in _context_cache_locks:
            _context_cache_locks[cache_key] = threading.Lock()
        return _context_cache_locks[cache_key]


def probe_web_endpoints() -> None:
    """Test DDG and raw.githubusercontent.com connectivity once before batch work.

    If either is unreachable (SSL timeout, network blocked), trip the circuit
    breaker immediately so no per-feature call wastes time on timeouts.
    """
    global _ddg_disabled, _kep_fetch_disabled
    from autok8s.common.logging import get_logger
    _logger = get_logger("web_search")

    try:
        req = urllib.request.Request(
            "https://lite.duckduckgo.com/lite/?q=test",
            headers={"User-Agent": _UA, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read(1024)
    except Exception:
        if not _ddg_disabled:
            _ddg_disabled = True
            _logger.warning("DuckDuckGo 不可达, 已预熔断; 后续搜索将跳过")

    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/kubernetes/enhancements/master/README.md",
            headers={"User-Agent": _UA, "Accept": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read(1024)
    except Exception:
        if not _kep_fetch_disabled:
            _kep_fetch_disabled = True
            _logger.warning("raw.githubusercontent.com 不可达, 已预熔断; 后续 KEP 摘要将跳过")


def _http_get(url: str, timeout: int = _FETCH_TIMEOUT,
              accept: str = "text/html,application/xhtml+xml") -> Optional[str]:
    """通用 GET, 返回解码后的文本; 失败返回 None。"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UA,
                "Accept": accept,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = "utf-8"
            ct = resp.headers.get("Content-Type", "")
            if "charset=" in ct:
                encoding = ct.split("charset=")[-1].strip().split(";")[0]
            return raw.decode(encoding, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None


def _clean_html(text: str) -> str:
    """剥离 HTML 标签, 压缩空白。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_kep_number(text: str) -> str:
    """从文本中提取首个 KEP 编号 (如 'KEP #1234' -> '1234'); 无则空串。"""
    if not text:
        return ""
    m = re.search(r"KEP\s*#?\s*(\d{1,5})", text, re.I)
    return m.group(1) if m else ""


def _html_unescape(text: str) -> str:
    """轻量 HTML 实体反转义 (&amp; &lt; &gt; &quot; &#39; &nbsp;)。"""
    if not text:
        return ""
    return (text.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#39;", "'").replace("&nbsp;", " "))


def _decode_ddg_redirect(href: str) -> str:
    """DuckDuckGo 结果链接是跳转 URL, 解析出真实地址。"""
    if not href:
        return ""
    href = _html_unescape(href)
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def ddg_html_search(query: str, num_results: int = 6) -> list[SearchResult]:
    """DuckDuckGo 搜索, 返回结果列表。

    优先用 lite.duckduckgo.com (反爬较宽松, 纯 HTML), 失败回退 html 端点。
    无需 API key。被限速或失败时返回空列表 (调用方降级处理)。
    连续失败 2 次后熔断, 后续调用直接返回空列表。
    """
    global _ddg_disabled
    if _ddg_disabled:
        return []
    if not query or not query.strip():
        return []
    encoded = urllib.parse.quote(query.strip())

    results: list[SearchResult] = []
    with _ddg_semaphore:
        endpoints = [f"https://lite.duckduckgo.com/lite/?q={encoded}",
                     f"https://html.duckduckgo.com/html/?q={encoded}"]
        for endpoint in endpoints:
            html = _http_get(endpoint)
            if not html:
                continue

            for m in re.finditer(r"<a\b([^>]*?)>(.*?)</a>", html, re.DOTALL | re.I):
                attrs = m.group(1)
                if "result-link" not in attrs:
                    continue
                href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
                if not href_m:
                    continue
                real_url = _decode_ddg_redirect(href_m.group(1))
                title = _clean_html(m.group(2))
                if title and real_url:
                    results.append(SearchResult(title=title, url=real_url))
                if len(results) >= num_results:
                    break

            if not results:
                for m in re.finditer(r"<a\b([^>]*?)>(.*?)</a>", html, re.DOTALL | re.I):
                    attrs = m.group(1)
                    if "result__a" not in attrs:
                        continue
                    href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
                    if not href_m:
                        continue
                    real_url = _decode_ddg_redirect(href_m.group(1))
                    title = _clean_html(m.group(2))
                    if title and real_url:
                        results.append(SearchResult(title=title, url=real_url))
                    if len(results) >= num_results:
                        break

            if results:
                snip_blocks = re.findall(
                    r"<(?:td|a)[^>]*class=['\"]?result[-_]snippet['\"]?[^>]*>(.*?)</(?:td|a)>",
                    html, re.DOTALL | re.I,
                )
                for i, snip in enumerate(snip_blocks):
                    if i >= len(results):
                        break
                    results[i].snippet = _clean_html(snip)
                break

    if not results:
        global _ddg_failures
        with _ddg_lock:
            _ddg_failures += 1
            if _ddg_failures >= _MAX_DDG_FAILURES and not _ddg_disabled:
                _ddg_disabled = True
                from autok8s.common.logging import get_logger
                get_logger("web_search").warning(
                    "DuckDuckGo 搜索连续失败 %d 次, 已熔断; 后续搜索将跳过", _ddg_failures,
                )
    else:
        with _ddg_lock:
            _ddg_failures = 0
    return results[:num_results]


# kubernetes/enhancements 仓库的 KEP 文件路径列表 (进程内缓存, 仅抓取一次)
_kep_tree_cache: list[str] | None = None
_kep_tree_lock = threading.Lock()


def _load_kep_tree() -> list[str]:
    """抓取 kubernetes/enhancements 仓库的完整文件树, 返回所有 .md 路径。

    git/trees API 对公开仓库无需鉴权 (限速 60/分钟), 一次抓取后进程内缓存。
    失败时返回空列表 (调用方降级到纯 web 搜索)。
    """
    global _kep_tree_cache
    if _kep_tree_cache is not None:
        return _kep_tree_cache
    with _kep_tree_lock:
        if _kep_tree_cache is not None:
            return _kep_tree_cache
        url = ("https://api.github.com/repos/kubernetes/enhancements/"
               "git/trees/master?recursive=1")
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=_KEP_FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            from autok8s.common.logging import get_logger
            get_logger("web_search").warning("KEP 文件树加载失败: %s", e)
            _kep_tree_cache = []
            return _kep_tree_cache

        paths = [
            t["path"] for t in (data.get("tree") or [])
            if t.get("type") == "blob" and t.get("path", "").endswith(".md")
        ]
        _kep_tree_cache = paths
        return paths


def _github_kep_path_search(kep_number: str) -> Optional[str]:
    """在 kubernetes/enhancements 仓库定位 KEP markdown 路径。

    KEP 文件有两种布局:
      - keps/<sig>/<num>-<name>.md          (单文件)
      - keps/<sig>/<num>-<name>/README.md   (目录+README)
    匹配规则: 路径中存在以 "<num>-" 开头的路径段, 且在 keps/ 下。
    """
    if not kep_number:
        return None
    tree = _load_kep_tree()
    if not tree:
        return None
    prefix = f"{kep_number}-"
    candidates: list[str] = []
    for path in tree:
        if not path.startswith("keps/"):
            continue
        segments = path.split("/")
        # segments[0]=='keps', segments[1]==sig, segments[2]==<num>-<name> or file
        if len(segments) < 3:
            continue
        third = segments[2]
        if third.startswith(prefix):
            candidates.append(path)
    if not candidates:
        return None
    # 优先 README.md (目录式), 其次单文件
    for c in candidates:
        if c.rsplit("/", 1)[-1] == "README.md":
            return c
    return candidates[0]


def _fetch_kep_summary(kep_path: str, max_chars: int = 4000) -> Optional[str]:
    """抓取 KEP markdown 原文, 截取 Summary/Motivation 段落。

    raw.githubusercontent.com 不可达时熔断 (连续失败 2 次后跳过)。
    """
    global _kep_fetch_disabled, _kep_fetch_failures
    if not kep_path:
        return None
    if _kep_fetch_disabled:
        return None
    raw_url = f"https://raw.githubusercontent.com/kubernetes/enhancements/master/{kep_path}"
    text = _http_get(raw_url, timeout=_KEP_SUMMARY_TIMEOUT,
                     accept="text/plain,application/octet-stream,*/*")
    if not text:
        with _kep_fetch_lock:
            _kep_fetch_failures += 1
            if _kep_fetch_failures >= _MAX_KEP_FETCH_FAILURES and not _kep_fetch_disabled:
                _kep_fetch_disabled = True
                from autok8s.common.logging import get_logger
                get_logger("web_search").warning(
                    "KEP 原文抓取连续失败 %d 次, 已熔断; 后续将跳过 KEP 摘要", _kep_fetch_failures,
                )
        return None
    with _kep_fetch_lock:
        _kep_fetch_failures = 0

    # KEP markdown 结构: ## Summary / ## Motivation / ## Proposal ...
    # 优先抓 Summary 段, 其次 Motivation
    sections: dict[str, str] = {}
    cur_heading = ""
    buf: list[str] = []
    for line in text.splitlines():
        hm = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if hm:
            if cur_heading:
                sections[cur_heading.lower()] = "\n".join(buf).strip()
            cur_heading = hm.group(2)
            buf = []
        else:
            buf.append(line)
    if cur_heading:
        sections[cur_heading.lower()] = "\n".join(buf).strip()

    for key in ("motivation", "summary", "proposal", "goals"):
        body = sections.get(key, "")
        if body and len(body) > 80:
            return body[:max_chars]
    return text[:max_chars]


def _fetch_page_text(url: str, max_chars: int = 3500) -> Optional[str]:
    """抓取普通网页正文 (剥离 HTML), 截断到 max_chars。"""
    if not url or not url.startswith(("http://", "https://")):
        return None
    html = _http_get(url)
    if not html:
        return None
    text = _clean_html(html)
    if len(text) < 80:
        return None
    return text[:max_chars]


def _build_search_queries(feature: Feature) -> list[str]:
    """为特性构造多组搜索 key (特性名 + KEP + 版本 + K8s 限定词)。"""
    name = feature.name.strip()
    ver = feature.version.strip()
    qs: list[str] = []
    kep = extract_kep_number(feature.description_en)
    if kep:
        qs.append(f"KEP {kep} kubernetes {ver}")
    qs.append(f"{name} kubernetes v{ver}")
    qs.append(f"{name} kubernetes KEP enhancement")
    return qs


def enrich_feature_context(feature: Feature) -> WebContext:
    """联网搜索为特性补充权威上下文。

    流程:
      1. (缓存命中) 直接返回已有上下文
      2. KEP 直查: 博客描述含 KEP# -> GitHub 搜索路径 -> 抓取 KEP Summary
      3. DuckDuckGo 搜索: 三组 key 轮询, 取首个非空结果集
      4. 抓取命中页面正文 (最多 2 个)
    """
    cache_key = (feature.name.strip(), feature.version.strip())
    if cache_key in _context_cache:
        return _context_cache[cache_key]

    lock = _get_context_lock(cache_key)
    with lock:
        if cache_key in _context_cache:
            return _context_cache[cache_key]

        ctx = WebContext(feature_name=feature.name, version=feature.version)

        kep_num = extract_kep_number(feature.description_en)
        if kep_num:
            ctx.kep_number = kep_num
            kep_path = _github_kep_path_search(kep_num)
            if kep_path:
                summary = _fetch_kep_summary(kep_path)
                if summary:
                    ctx.kep_summary = summary
                    ctx.sources.append(
                        f"https://github.com/kubernetes/enhancements/blob/master/{kep_path}"
                    )

        queries = _build_search_queries(feature)
        seen_urls: set[str] = set()
        for q in queries:
            if ctx.web_snippets and len(ctx.web_snippets) >= 4:
                break
            if _ddg_disabled:
                break
            results = ddg_html_search(q, num_results=5)
            if results:
                time.sleep(0.4)
            for r in results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                if r.snippet:
                    ctx.web_snippets.append(f"{r.title}: {r.snippet}")
                ctx.sources.append(r.url)
            if ctx.web_snippets:
                break

        candidate_urls = [
            u for u in ctx.sources
            if u and "github.com/kubernetes/enhancements" not in u
            and u.startswith(("http://", "https://"))
        ]
        for url in candidate_urls[:2]:
            text = _fetch_page_text(url)
            if text:
                ctx.page_texts.append(text)
                time.sleep(0.3)

        _context_cache[cache_key] = ctx
        return ctx


def clear_cache() -> None:
    """清空进程内搜索缓存。"""
    _context_cache.clear()
    with _context_cache_locks_guard:
        _context_cache_locks.clear()


# ---------------------------------------------------------------------------
# 答案自检 (cross-validation against web context)
# ---------------------------------------------------------------------------

# 翻译为中文后通常会原样保留的技术术语 (acronym + 常见 k8s 专有词)。
# 仅用这些做"关键术语覆盖"自检, 避免把会被翻译掉的普通首字母大写词误判为缺失。
# 注: 不含 ga/beta/alpha/sig/kep 等阶段/引用词 (每个特性都有, 无区分度)。
_PRESERVED_TECH_TERMS = {
    "api", "csi", "dra", "rbac", "hpa", "cidr", "ip", "crd", "psi", "numa",
    "oci", "grpc", "cel", "yaml", "kubelet", "kubectl", "containerd",
    "sidecar", "pod", "pv", "pvc", "cri", "cni", "cgroup", "seccomp",
    "apparmor", "selinux", "ssa", "token", "tls", "ssl", "http", "tcp",
    "udp", "dns", "vip",
}

# 看起来像缩写但实为普通英语词或阶段/引用词的全大写 token, 不纳入关键术语
_NOISE_ACRONYMS = {
    "GA", "IT", "IS", "TO", "OF", "IN", "ON", "OR", "AN", "AT", "BY",
    "WE", "HE", "BE", "DO", "IF", "AS", "SO", "NO", "UP", "US", "GO",
    "KEP", "SIG", "WG", "PR", "CI", "CD", "OK",
}


def _extract_key_terms(text: str, max_terms: int = 6) -> list[str]:
    """从英文文本抽取翻译后仍会保留的关键术语 (用于交叉验证中文答案是否跑题)。

    只保留两类:
      1. 全大写缩写 (CRD, CSI, DRA, RBAC, CIDR) — 中文里几乎原样保留
      2. 已知 k8s 技术专有词 (kubelet, sidecar, apparmor) — 不被翻译
    普通首字母大写词 (Mutating, Admission) 会被翻译掉, 不纳入检查, 避免误报。
    """
    if not text:
        return []
    lower = text.lower()
    seen: set[str] = set()
    terms: list[str] = []

    for m in re.finditer(r"\b([A-Z]{2,6})\b", text):
        t = m.group(1)
        if t in _NOISE_ACRONYMS:
            continue
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        terms.append(t)
        if len(terms) >= max_terms:
            return terms

    for term in _PRESERVED_TECH_TERMS:
        if len(terms) >= max_terms:
            break
        if term in seen:
            continue
        if re.search(rf"\b{re.escape(term)}\b", lower):
            seen.add(term)
            terms.append(term)
    return terms


def verify_content(intro: str, value: str, feature: Feature,
                   ctx: Optional[WebContext] = None) -> tuple[bool, list[str]]:
    """自检生成答案的正确性, 返回 (是否通过, 问题列表)。

    检查项:
      1. 版本一致: intro 必须包含 feature.version
      2. 阶段一致: intro 必须包含与 feature.section 对应的阶段词 (GA/beta/alpha)
      3. 中文质量: value 中文占比 >= 0.3
      4. 翻译伪迹: 不含 "MYMEMORY WARNING" / "Translate" 等机翻残留
      5. 关键术语覆盖: intro/value 至少命中 1 个从描述抽取的关键术语
      6. 上下文一致 (若提供 ctx): 关键术语与 KEP/web 摘要有重叠
      7. 长度合规: value 在 12~70 字之间, intro 非空
      8. 痛点真实性: 现状不得是收益/条件描述伪装
      9. 价值真实性: 价值不得是功能描述伪装
      10. 增强句去重: 增强句不得出现版本号/阶段词重复
    """
    issues: list[str] = []
    full = f"{intro} {value}"

    if feature.version and feature.version not in intro:
        issues.append("version_mismatch")

    stage_map = {
        "Stable": ["GA", "稳定", "孵化"],
        "Beta": ["beta", "Beta", "增强"],
        "Alpha": ["alpha", "Alpha", "新增"],
    }
    expected = stage_map.get(feature.section, [])
    if expected and not any(s in intro for s in expected):
        issues.append("stage_mismatch")

    cn = len(re.findall(r"[\u4e00-\u9fff]", value))
    total = max(len(value), 1)
    if cn / total < 0.3:
        issues.append("low_chinese_ratio")

    artifacts = ["MYMEMORY WARNING", "translatedText", "Translate API",
                 "HTTPError", "URLError"]
    if any(a in value for a in artifacts) or any(a in intro for a in artifacts):
        issues.append("translation_artifact")

    terms = _extract_key_terms(feature.description_en)
    if terms:
        full_lower = full.lower()
        hit = any(t.lower() in full_lower for t in terms)
        if not hit and len(value.strip()) < 25:
            issues.append("missing_key_terms")

    if ctx and ctx.combined_text:
        ctx_lower = ctx.combined_text.lower()
        if terms:
            ctx_hits = sum(1 for t in terms if t.lower() in ctx_lower)
            if ctx_hits == 0:
                issues.append("context_no_overlap")
        if ctx.kep_number and ctx.kep_number not in feature.description_en:
            pass

    if not value or len(value.strip()) < 12:
        issues.append("value_too_short")
    elif len(value.strip()) > 70:
        issues.append("value_too_long")
    if not intro or len(intro.strip()) < 20:
        issues.append("intro_too_short")

    if "现状：" not in intro or "本特性增强：" not in intro:
        issues.append("intro_missing_required_sections")

    if "现状：" in intro and "本特性增强：" in intro:
        pain_part = intro.split("本特性增强：", 1)[0].replace("现状：", "").strip()
        if pain_part and _is_fake_pain_text(pain_part):
            issues.append("pain_is_fake")
        enh_part = intro.split("本特性增强：", 1)[1].strip()
        if enh_part:
            if _is_stage_only_enhancement(enh_part):
                issues.append("enhancement_is_stage_only")
            standalone_vers = re.findall(r"(?<![A-Za-z])v\d+\.\d+", enh_part)
            stage_count = len(re.findall(r"升级为|晋升为|进阶至|进阶为|正式发布|升级到稳定|升级至稳定|进阶至稳定|晋升为稳定|达到稳定|进阶为GA|晋升至GA|升级为.*稳定|升级为.*Beta|晋升为.*稳定|晋升为.*Beta|进阶为.*稳定|进阶为.*Beta", enh_part))
            if len(standalone_vers) >= 2 or stage_count >= 2:
                issues.append("enhancement_duplicate")
            issues.extend(enhancement_issues(enh_part))
        # This cross-field gate catches role confusion that individual regexes
        # miss, such as a benefit written as "现状" or a mechanism copied into
        # "特性功能价值分析".
        issues.extend(content_issues(pain_part, enh_part, value))

    if value and _is_fake_value_text(value):
        issues.append("value_is_function_desc")

    issues.extend(value_issues(value))

    return (len(issues) == 0), issues


def _is_stage_only_enhancement(text: str) -> bool:
    """Reject a release-stage announcement presented as a feature enhancement."""
    normalized = re.sub(r"\s+", "", (text or "").strip().rstrip("。"))
    return bool(re.fullmatch(
        r"v\d+\.\d+(?:中)?[“\"].+?[”\"](?:作为)?(?:Alpha|alpha|Beta|beta|GA|稳定)(?:特性)?(?:发布|阶段|引入)?",
        normalized,
        re.I,
    ))


_ZH_FAKE_PAIN_VERIFY_RE = re.compile(
    r"^这\s*(确保|保证|使得|让|允许|意味着|表示|说明|保证|有助)|"
    r"^这对|^这一特性|^该特性|^本特性|"
    r"^如果.{0,30}(则|那么|就)|"
    r"^现在\s*(可以|能够|允许)|^如今|^随着|"
    r"^通过|^对.{0,35}(?:支持|能力).{0,25}(?:依赖|允许)|"
    r"^该\s*(机制|方案|特性|功能|能力)|"
    r"^它\s*(允许|使|让|提供|支持)",
    re.I,
)
_ZH_VALUE_FUNC_VERIFY_RE = re.compile(
    r"此特性\s*(使|让|允许|提供|支持|能够)|"
    r"该特性\s*(使|让|允许|提供|支持)|"
    r"本特性\s*(使|让|允许|提供|支持)|"
    r"(使|让)\s*kubelet\s*(能够|可以|报告|提供)|"
    r"(使|让)\s*apiserver\s*(能够|可以)|"
    r"(使|让)\s*集群\s*(能够|可以)|"
    r"提供\s*了?\s*(一种|一个)\s*(方法|机制|方式|接口)|"
    r"^(?:这可|这会|这将|这一举措|这项举措)",
    re.I,
)


def _is_fake_pain_text(text: str) -> bool:
    return bool(_ZH_FAKE_PAIN_VERIFY_RE.search(text.strip()))


def _is_fake_value_text(text: str) -> bool:
    return bool(_ZH_VALUE_FUNC_VERIFY_RE.search(text.strip()))
