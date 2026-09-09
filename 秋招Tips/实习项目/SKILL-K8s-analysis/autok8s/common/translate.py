from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request

from .logging import get_logger

_logger = get_logger("translate")

_TIMEOUT = 8
_MAX_FAILURES = 2
_disabled = False
_failures = 0
_lock = threading.Lock()

_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_MAX_CACHE_SIZE = 500


def _cache_get(text: str) -> str | None:
    with _cache_lock:
        return _cache.get(text)


def _cache_put(text: str, result: str) -> None:
    with _cache_lock:
        if len(_cache) < _MAX_CACHE_SIZE:
            _cache[text] = result


def _should_skip() -> bool:
    return _disabled


def _record_failure() -> None:
    global _disabled, _failures
    with _lock:
        _failures += 1
        if _failures >= _MAX_FAILURES and not _disabled:
            _disabled = True
            _logger.warning(
                "翻译 API 连续失败 %d 次, 已熔断; 后续翻译将返回原文", _failures,
            )


def _record_success() -> None:
    global _failures
    with _lock:
        _failures = 0


def translate_to_chinese(text: str) -> str:
    global _disabled
    text = (text or "").strip()
    if not text or len(text) < 3 or len(re.findall(r"[\u4e00-\u9fff]", text)) >= 3:
        return text
    if _should_skip():
        return text
    cached = _cache_get(text)
    if cached is not None:
        return cached
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=" + urllib.parse.quote(text[:1800])
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AutoK8s)"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        result = "".join(part[0] for part in data[0] if part and part[0]).strip() or text
        _record_success()
        _cache_put(text, result)
        return result
    except (ValueError, OSError, TimeoutError) as e:
        _record_failure()
        return text


def is_translate_available() -> bool:
    return not _disabled


def probe_translate() -> None:
    """Test Google Translate API connectivity once before batch work."""
    global _disabled
    if _disabled:
        return
    test_url = ("https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=en&tl=zh-CN&dt=t&q=hello")
    try:
        request = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0 (AutoK8s)"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            json.loads(response.read().decode("utf-8"))
        _record_success()
    except (ValueError, OSError, TimeoutError):
        _disabled = True
        _logger.warning("Google Translate API 不可达, 已预熔断; 后续翻译将返回原文")


def reset_translate_circuit() -> None:
    global _disabled, _failures
    with _lock:
        _disabled = False
        _failures = 0
