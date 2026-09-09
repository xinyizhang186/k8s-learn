from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional


def fetch_url(url: str, timeout: int = 20, accept: str = "text/html") -> Optional[str]:
    if not url.startswith(("https://", "http://")):
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AutoK8s)", "Accept": accept})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
        return None
