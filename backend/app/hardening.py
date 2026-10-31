"""在线服务加固件：每 IP 滑动窗口限流。全部标准库实现，保持零依赖。"""
from __future__ import annotations

import time
from typing import Callable


class SlidingWindowRateLimiter:
    """按 key（通常是客户端 IP）的滑动窗口限流。

    now_fn 可注入，测试时替换时钟即可，不用 sleep。
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float = 60.0,
        now_fn: Callable[[], float] = time.time,
        max_keys: int = 10000,
    ) -> None:
        self.max_requests = max(int(max_requests), 1)
        self.window_seconds = float(window_seconds)
        self._now = now_fn
        self._max_keys = max_keys
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._now()
        hits = [t for t in self._hits.get(key, ()) if now - t < self.window_seconds]
        allowed = len(hits) < self.max_requests
        if allowed:
            hits.append(now)
        self._hits[key] = hits
        self._prune(now)
        return allowed

    def retry_after(self, key: str) -> int:
        """被限流时建议等待的秒数（>=1）。"""
        hits = self._hits.get(key, [])
        if not hits:
            return 0
        elapsed = self._now() - hits[0]
        return max(1, int(self.window_seconds - elapsed) + 1)

    def _prune(self, now: float) -> None:
        """key 数量超限时清理已过期的条目，防止内存无限增长。"""
        if len(self._hits) <= self._max_keys:
            return
        expired = [
            k for k, v in self._hits.items()
            if not v or now - v[-1] >= self.window_seconds
        ]
        for k in expired:
            self._hits.pop(k, None)
