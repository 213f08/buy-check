"""行情证据采集：为每个候选机型发起元宝搜索，抓取「二手价格/行情」线索。

设计要点：
- Mock 模式下返回空列表（报告由 catalog 精选数据生成）；
- Live 模式下每条线索带 URL / 站点 / 日期 / 抓取时间，前端可点回原文；
- 查询结果带 TTL 缓存（相同机型 1 小时内不重复扣额度）；
- 单个机型检索失败只标记该机型，不拖垮整份报告（降级策略）。
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Optional

from .yuanbao_client import SearchPage, YuanbaoSearchClient


class SearchCache:
    """极简 TTL 缓存：key = query 的 sha256。"""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, list[SearchPage]]] = {}

    @staticmethod
    def key(query: str) -> str:
        return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[list[SearchPage]]:
        item = self._data.get(key)
        if not item:
            return None
        expires_at, pages = item
        if time.time() > expires_at:
            self._data.pop(key, None)
            return None
        return pages

    def put(self, key: str, pages: list[SearchPage]) -> None:
        self._data[key] = (time.time() + self.ttl, pages)


def collect_price_evidence(
    models: list[dict],
    client: YuanbaoSearchClient,
    cache: Optional[SearchCache] = None,
) -> tuple[list[dict], int]:
    """为每个机型采集行情证据。返回 (evidence, 实际发起的搜索次数)。"""
    if client.mock:
        return [], 0

    evidence: list[dict] = []
    searches = 0
    for model in models:
        query = f"{model['name']} 二手 价格 行情"
        entry: dict = {
            "model": model["name"],
            "query": query,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "items": [],
        }
        key = SearchCache.key(query)
        cached = cache.get(key) if cache else None
        try:
            if cached is None:
                pages = client.search(query, cnt=10)
                searches += 1
                if cache is not None:
                    cache.put(key, pages)
            else:
                pages = cached
                entry["cached"] = True
            entry["items"] = [
                {
                    "title": page.title,
                    "url": page.url,
                    "site": page.site,
                    "date": page.date,
                    "passage": page.passage[:600],
                    "score": page.score,
                    "authority_level": page.authority_level,
                }
                for page in pages[:3]
            ]
        except Exception as exc:  # noqa: BLE001 - 单机型失败不影响整份报告
            entry["error"] = str(exc)[:200]
        evidence.append(entry)
    return evidence, searches
