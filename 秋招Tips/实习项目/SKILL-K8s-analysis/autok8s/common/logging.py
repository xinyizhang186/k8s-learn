from __future__ import annotations

import logging
import os


def _default_level() -> int:
    """日志级别: 默认 CRITICAL (终端静默), 可用 AUTOK8S_LOG_LEVEL 覆盖。"""
    env = os.environ.get("AUTOK8S_LOG_LEVEL", "").strip().upper()
    return getattr(logging, env, logging.CRITICAL)


def setup(level: str | None = None) -> None:
    root = logging.getLogger("autok8s")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(_default_level() if level is None else getattr(logging, level.upper(), logging.CRITICAL))


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger("autok8s")
    if not root.handlers:
        setup()
    return logging.getLogger(f"autok8s.{name}")
