"""Minimal in-memory sliding-window rate limiter (per process).

For multi-worker deployments, put a reverse proxy / Redis-based limiter in
front; this guard is a defense-in-depth layer for the API.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._hits[key]
            while window and window[0] <= now - self.window_seconds:
                window.popleft()
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            window = self._hits.get(key, deque())
            while window and window[0] <= now - self.window_seconds:
                window.popleft()
            return max(0, self.max_requests - len(window))
