"""实时线索价抽取：从行情证据中提取「这个型号值多少钱」的线索。

归因规则（防止张冠李戴）：
1. 句号级分句后，再按逗号切成子句；价格认领以子句为单位：
   - 子句内出现本型号别名 → 收取该子句价格；
   - 子句无别名，但**整句没有其他型号别名**且与型号子句相邻 → 收取
     （覆盖「小新pro14，3200元出」这类常见出帖格式）；
   - 整句出现其他型号别名 → 只收本型号子句的价格
     （「EOS RP 4500元，A7M3 6500元」绝不会把 6500 算给 EOS RP）；
2. 价格必须落在品类合理区间（price_plausible），否则丢弃；
3. 同一来源同一价格去重；最多保留 5 条线索。

可信度聚合：>= 2 条且极差/中位数 <= 40% → reliable（参与打分）；1 条仅展示。
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

SENT_SPLIT_RE = re.compile(r"[。！？!?；;\n]")
CLAUSE_SPLIT_RE = re.compile(r"[，,]")
RANGE_RE = re.compile(
    r"(\d{1,6}(?:\.\d+)?)\s*(万)?\s*[-~—–]{1,2}\s*(\d{1,6}(?:\.\d+)?)\s*(万)?\s*元"
)
SINGLE_RE = re.compile(r"(\d{1,6}(?:\.\d+)?)\s*(万)?\s*元")


def _norm(text: str) -> str:
    return re.sub(r"[\s·・、]", "", text or "").lower()


def _values_in(clause: str) -> list[float]:
    """从单个子句里提取价格候选值（元）。"""
    values: list[float] = []
    for m in RANGE_RE.finditer(clause):
        low = float(m.group(1)) * (10000 if m.group(2) else 1)
        high = float(m.group(3)) * (10000 if m.group(4) else 1)
        if low <= high:
            values.extend([low, high])
    for m in SINGLE_RE.finditer(clause):
        values.append(float(m.group(1)) * (10000 if m.group(2) else 1))
    return values


def extract_live_prices(
    model: dict,
    evidence_items: list[dict],
    plausible: tuple[float, float],
    other_aliases: Optional[Iterable[str]] = None,
    max_clues: int = 5,
) -> list[dict]:
    """从该机型的证据条目中抽取线索价。

    other_aliases：其他所有型号的别名（归一化后），用于句内隔离。
    """
    aliases = [_norm(a) for a in ([model["name"]] + model.get("aliases", []))]
    others = {_norm(a) for a in (other_aliases or []) if a}
    clues: list[dict] = []
    seen: set[tuple] = set()

    for item in evidence_items or []:
        text = f"{item.get('title', '')}。{item.get('passage', '')}"
        for sentence in SENT_SPLIT_RE.split(text):
            clauses = [c for c in CLAUSE_SPLIT_RE.split(sentence) if c.strip()]
            if not clauses:
                continue
            normed = [_norm(c) for c in clauses]
            model_hits = {i for i, c in enumerate(normed) if any(a in c for a in aliases)}
            other_in_sentence = any(
                a in c for i, c in enumerate(normed) for a in others if i not in model_hits
            )

            for i, clause in enumerate(normed):
                if i in model_hits:
                    attributed = True
                elif other_in_sentence:
                    attributed = False
                else:
                    attributed = any(abs(i - j) <= 1 for j in model_hits)
                if not attributed:
                    continue
                for value in _values_in(clauses[i]):
                    if not (plausible[0] <= value <= plausible[1]):
                        continue
                    key = (int(value), item.get("url", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    clues.append({
                        "value": int(round(value)),
                        "site": item.get("site", ""),
                        "date": item.get("date", ""),
                        "url": item.get("url", ""),
                        "snippet": clauses[i].strip()[:60],
                    })
                    if len(clues) >= max_clues:
                        return clues
    return clues


def summarize_clues(clues: list[dict]) -> Optional[dict]:
    """把线索聚合成价格带；>= 2 条且离散度可控才可信。"""
    if not clues:
        return None
    values = sorted(c["value"] for c in clues)
    med = values[len(values) // 2]
    low, high = values[0], values[-1]
    spread = (high - low) / med if med else 1.0
    return {
        "low": low,
        "high": high,
        "median": med,
        "count": len(clues),
        "reliable": bool(len(clues) >= 2 and spread <= 0.40),
    }
