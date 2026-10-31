"""每日额度守卫：保护元宝搜索免费额度，防止公开 Demo 被刷爆。

按「天」持久化到 JSON 文件，只保留最近 7 天记录。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class DailyQuota:
    def __init__(self, path: Path, limit: int = 60) -> None:
        self.path = Path(path)
        self.limit = int(limit)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def used_today(self) -> int:
        return int(self._load().get(date.today().isoformat(), 0))

    def can_spend(self, n: int) -> bool:
        return self.used_today() + int(n) <= self.limit

    def record(self, n: int) -> None:
        data = self._load()
        key = date.today().isoformat()
        data[key] = int(data.get(key, 0)) + int(n)
        for stale in sorted(data.keys())[:-7]:
            data.pop(stale, None)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
