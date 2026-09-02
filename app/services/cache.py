import hashlib
import json
import time
from typing import Any

from app.config import get_settings


class Cache:
    def __init__(self) -> None:
        self.memory: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.redis = None
        if get_settings().redis_url:
            try:
                import redis

                self.redis = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
                self.redis.ping()
            except Exception:
                self.redis = None

    @staticmethod
    def key(namespace: str, value: str) -> str:
        return f"kp:{namespace}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

    def get(self, key: str) -> Any | None:
        if self.redis:
            raw = self.redis.get(key)
            if raw:
                self.hits += 1
                return json.loads(raw)
        item = self.memory.get(key)
        if item and item[0] > time.time():
            self.hits += 1
            return item[1]
        self.misses += 1
        return None

    def set(self, key: str, value: Any, ttl: int = 900) -> None:
        if self.redis:
            try:
                self.redis.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
            except Exception:
                pass
        self.memory[key] = (time.time() + ttl, value)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
