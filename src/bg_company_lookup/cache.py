"""
Прост thread-safe in-memory кеш с TTL (time-to-live).

Не е споделен между gunicorn worker процеси (`-w 2` в render.yaml) — всеки
worker пази собствено копие. За личен инструмент с нисък трафик това е
приемлив компромис срещу сложността на споделен кеш (Redis и т.н.).
"""

from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)
