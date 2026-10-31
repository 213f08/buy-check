"""自由检索模式（最小 MVP）：任意关键词 + 价格区间 → 整理后的链接清单。

设计原则：
- 不做品类限定、不做权重打分、不依赖精选目录——元宝搜到什么就整理什么；
- 只做三件事：搜索、从每条结果提取价格线索、按价格区间整理排序；
- 价格提取复用线索抽取器的子句规则（避免把「4500-5000元」「1.2万」读错）；
- 没有识别到价格的结果不丢弃，标记为「未识别价格」排在最后。
"""
from __future__ import annotations

from .price_extractor import _values_in

# 自由模式没有品类上下文，用一个足够宽的通用区间过滤明显误读（如「10万次」）
GENERIC_PLAUSIBLE = (10, 1_000_000)


def extract_item_prices(text: str, max_prices: int = 4) -> list[int]:
    """从一条结果（标题+摘要）里提取价格线索，升序去重。"""
    values = sorted({
        int(round(v)) for v in _values_in(text or "")
        if GENERIC_PLAUSIBLE[0] <= v <= GENERIC_PLAUSIBLE[1]
    })
    return values[:max_prices]


def organize_items(items: list[dict], price_min: int | None, price_max: int | None) -> list[dict]:
    """给每条结果标注价格线索与区间命中情况。

    price_hit: True=区间内 / False=识别到价格但区间外 / None=未识别到价格
    """
    out: list[dict] = []
    for item in items:
        text = f"{item.get('title', '')}。{item.get('passage', '')}"
        prices = extract_item_prices(text)
        if price_min is None and price_max is None:
            hit = None
        elif not prices:
            hit = None
        else:
            hit = any(
                (price_min is None or v >= price_min) and (price_max is None or v <= price_max)
                for v in prices
            )
        out.append({**item, "prices": prices, "price_hit": hit})
    return out


def sort_items(items: list[dict], mode: str) -> list[dict]:
    """排序：relevance 保持接口原序；price_asc / price_desc 把无价格者排最后。"""
    if mode not in ("price_asc", "price_desc"):
        return items

    def key(item: dict):
        return item["prices"][0] if item["prices"] else None

    has_price = [it for it in items if key(it) is not None]
    no_price = [it for it in items if key(it) is None]
    has_price.sort(key=key, reverse=(mode == "price_desc"))
    return has_price + no_price
