"""买前尽调 · 推荐引擎。

输入：品类 + 预算 + 「最在乎 / 最不在乎」维度
输出：定位卡、型号矩阵、行情卡、避雷卡、取舍推荐（首选 / 省钱选 / 加钱选）

实时行情：apply_live_prices() 把元宝搜索抽出的「线索价」反哺系统——
可信的价格带会修正打分用的基准价与预算判定，不可信的仅作展示。
"""
from __future__ import annotations

from statistics import median

from .catalog import CATEGORIES, DIMENSION_LABELS
from .price_extractor import _norm, extract_live_prices, summarize_clues


def detect_category(query: str) -> str | None:
    q = (query or "").lower()
    best_key, best_hits = None, 0
    for key, cat in CATEGORIES.items():
        hits = sum(1 for kw in cat["keywords"] if kw.lower() in q)
        if hits > best_hits:
            best_key, best_hits = key, hits
    return best_key


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 1.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _money(value: float) -> str:
    return f"¥{int(round(value)):,}"


def _model_dict(model: dict, category: dict) -> dict:
    return {
        "id": model["id"],
        "name": model["name"],
        "aliases": list(model.get("aliases", [])),
        "price_used": list(model["price_used"]),
        "price_new": model["price_new"],
        "weight_g": model["weight_g"],
        "scores": dict(model["scores"]),
        "pros": list(model["pros"]),
        "cons": list(model["cons"]),
        "pitfalls": list(model["pitfalls"]),
        "dimensions": category["dimensions"],
    }


def _effective_range(model: dict) -> tuple[float, float]:
    """预算判定 / 展示用的有效价带：可信的实时线索优先，否则精选参考价。"""
    live = model.get("live_band")
    if live and live.get("reliable"):
        return float(live["low"]), float(live["high"])
    return float(model["price_used"][0]), float(model["price_used"][1])


def _score(models: list[dict], dims: list[str], care: list[str], ignore: list[str]) -> None:
    """归一化 + 加权打分（价格基准使用 mid_price，可能是实时线索价）。原地更新。"""
    mid_prices = [m["mid_price"] for m in models]
    weights_g = [m["weight_g"] for m in models]
    min_price, max_price = min(mid_prices), max(mid_prices)
    min_weight, max_weight = min(weights_g), max(weights_g)

    for model in models:
        model["attrs"] = {
            "price": 1 - _normalize(model["mid_price"], min_price, max_price),
            "portability": 1 - _normalize(model["weight_g"], min_weight, max_weight),
        }
        for key, value in model["scores"].items():
            model["attrs"][key] = value / 10.0

    base_weights = {d: 1.0 for d in dims}
    for d in care:
        if d in base_weights:
            base_weights[d] = 2.5
    for d in ignore:
        if d in base_weights:
            base_weights[d] = 0.15

    for model in models:
        total_w = sum(base_weights[d] for d in dims)
        score = sum(base_weights[d] * model["attrs"].get(d, 0.5) for d in dims) / max(total_w, 1e-9)
        model["score"] = round(score * 10, 1)


def _recommend(models: list[dict], dims: list[str], care: list[str], ignore: list[str]) -> tuple[list[dict], list[dict]]:
    ranked = sorted(models, key=lambda m: m["score"], reverse=True)
    primary = ranked[0]

    cheaper_pool = [
        m for m in ranked
        if m["mid_price"] < primary["mid_price"] - 100 and m["id"] != primary["id"]
    ]
    save = cheaper_pool[0] if cheaper_pool else None

    expensive_pool = [m for m in ranked if m["mid_price"] > primary["mid_price"]]
    if expensive_pool:
        upgrade = max(expensive_pool, key=lambda m: m["score"])
        upgrade_label = "加钱选"
    else:
        alternative = [m for m in ranked if m["id"] != primary["id"]]
        upgrade = max(alternative, key=lambda m: m["scores"].get("performance", 0)) if alternative else None
        upgrade_label = "进阶选"

    care_labels = [DIMENSION_LABELS[d] for d in care if d in dims]
    ignore_labels = [DIMENSION_LABELS[d] for d in ignore if d in dims]
    weight_text = (
        f"你在乎：{'、'.join(care_labels) or '无'}；"
        f"不在乎：{'、'.join(ignore_labels) or '无'}。"
    )

    def build_reason(model: dict, role: str) -> str:
        parts = [f"按你的权重计算，综合得分 {model['score']}/10。{weight_text}"]
        if role == "primary":
            parts.append(f"它在 {model['name']} 这一档里最贴合你的需求。")
        elif role == "save":
            diff = primary["mid_price"] - model["mid_price"]
            if diff > 0:
                parts.append(f"比首选便宜约 {_money(diff)}，适合把预算压到最低。")
            else:
                parts.append("是预算内更稳妥的选择。")
        else:
            diff = model["mid_price"] - primary["mid_price"]
            if diff > 0:
                parts.append(f"比首选贵约 {_money(diff)}，换来的是：{'、'.join(model['pros'][:2])}。")
            else:
                parts.append(f"它的强项是：{'、'.join(model['pros'][:2])}。")
            if model["score"] < primary["score"] - 0.3:
                parts.append(
                    f"但综合分 {model['score']} 低于首选 {primary['score']}——"
                    f"只有当你更看重这些强项、愿意牺牲其他维度时才值得考虑。"
                )
        return "".join(parts)

    recommendations = []
    used_ids: set[str] = set()
    for role, model in (("primary", primary), ("save", save), ("upgrade", upgrade)):
        if model is None or model["id"] in used_ids:
            continue
        used_ids.add(model["id"])
        label = {"primary": "首选", "save": "省钱选", "upgrade": upgrade_label}[role]
        recommendations.append({
            "role": role,
            "label": label,
            "model": model,
            "reason": build_reason(model, role),
        })

    why_not = []
    for model in ranked:
        if model["id"] == primary["id"]:
            continue
        diff = model["mid_price"] - primary["mid_price"]
        direction = f"贵约 {_money(diff)}" if diff > 0 else f"便宜约 {_money(-diff)}"
        why_not.append({
            "model": model["name"],
            "text": (
                f"{model['name']}：比首选{direction}，优势是「{'、'.join(model['pros'][:2])}」；"
                f"但短板「{'、'.join(model['cons'][:1])}」会把综合分拉下来，所以在你的权重下排在后面。"
            ),
        })
    return recommendations, why_not


def _matrix_rows(models: list[dict], primary: dict) -> list[dict]:
    return [
        {
            "name": m["name"],
            "price_used": m["price_used"],
            "weight_g": m["weight_g"],
            "score": m["score"],
            "cons": m["cons"][0],
            "pros": m["pros"][:2],
            "is_primary": m["id"] == primary["id"],
        }
        for m in models
    ]


def _market_rows(models: list[dict], budget_min: int | None, budget_max: int | None) -> list[dict]:
    rows = []
    for model in models:
        mid = model["mid_price"]
        eff_low, eff_high = _effective_range(model)
        live = model.get("live_band")
        rows.append({
            "name": model["name"],
            "used_low": model["price_used"][0],
            "used_high": model["price_used"][1],
            "eff_low": eff_low,
            "eff_high": eff_high,
            "new_price": model["price_new"],
            "depreciation": round(1 - mid / model["price_new"], 2) if model["price_new"] else 0,
            "budget_status": _budget_status([eff_low, eff_high], budget_min, budget_max),
            "price_source": model.get("price_source", "curated"),
            "live": live,
        })
    return rows


def advise(
    query: str,
    budget_min: int | None = None,
    budget_max: int | None = None,
    care: list[str] | None = None,
    ignore: list[str] | None = None,
) -> dict:
    care = [d for d in (care or []) if d in DIMENSION_LABELS]
    ignore = [d for d in (ignore or []) if d in DIMENSION_LABELS]

    category_key = detect_category(query)
    if not category_key:
        raise ValueError(
            f"暂时只支持：{' / '.join(c['name'] for c in CATEGORIES.values())}（其他品类可用「自由检索」模式）"
        )
    category = CATEGORIES[category_key]
    dims = category["dimensions"]

    models = [_model_dict(m, category) for m in category["models"]]

    # ---- 预算筛选 ----
    budget_note = ""
    selected = []
    for model in models:
        low, high = model["price_used"]
        if budget_max and low > budget_max:
            continue
        if budget_min and high < budget_min:
            continue
        selected.append(model)
    if not selected:
        selected = models
        budget_note = "预算内没有完全匹配的机型，以下为相邻价位参考。"
    models = selected

    for model in models:
        model["mid_price"] = (model["price_used"][0] + model["price_used"][1]) / 2
        model["price_source"] = "curated"

    _score(models, dims, care, ignore)
    ranked = sorted(models, key=lambda m: m["score"], reverse=True)
    recommendations, why_not = _recommend(models, dims, care, ignore)
    primary = ranked[0]

    return {
        "query": query,
        "category": {
            "key": category_key,
            "name": category["name"],
            "positioning": category["positioning"],
            "suitable": category["suitable"],
            "unsuitable": category["unsuitable"],
            "dimensions": [
                {"key": d, "label": DIMENSION_LABELS[d]} for d in dims
            ],
        },
        "budget": {"min": budget_min, "max": budget_max, "note": budget_note},
        "models": models,
        "matrix": _matrix_rows(models, primary),
        "market": _market_rows(models, budget_min, budget_max),
        "avoidance": {
            "items": [
                {"model": model["name"], "pitfalls": model["pitfalls"]}
                for model in models
            ],
            "inspection": category["inspection"],
            "market_note": category["market_note"],
        },
        "recommendations": recommendations,
        "why_not": why_not,
        "weights": {"care": care, "ignore": ignore},
        "meta": {"mock": True, "data_note": "演示数据：价格为示意，实际以实时检索与面交验机为准。"},
    }


def apply_live_prices(result: dict, evidence: list[dict],
                      budget_min: int | None, budget_max: int | None) -> dict:
    """把实时线索价反哺进报告：可信价格带修正打分基准与预算判定。"""
    category = CATEGORIES[result["category"]["key"]]
    dims = [d["key"] for d in result["category"]["dimensions"]]
    care = result["weights"]["care"]
    ignore = result["weights"]["ignore"]
    plausible = tuple(category["price_plausible"])

    evidence_by_model = {e["model"]: e for e in evidence or []}
    live_applied = 0
    for model in result["models"]:
        entry = evidence_by_model.get(model["name"])
        # 跨型号隔离：其他所有型号（含发现池）的别名都视为「别人家」
        others = set()
        for m in category["models"]:
            if m["id"] == model["id"]:
                continue
            others.add(_norm(m["name"]))
            others.update(_norm(a) for a in m.get("aliases", []))
        for pooled in category.get("discover_pool", []):
            if pooled["name"] != model["name"]:
                others.add(_norm(pooled["name"]))
                others.update(_norm(a) for a in pooled.get("aliases", []))
        clues = extract_live_prices(
            model, (entry or {}).get("items", []), plausible, other_aliases=others
        )
        band = summarize_clues(clues)
        model["live_prices"] = clues
        model["live_band"] = band
        if band and band.get("reliable"):
            model["mid_price"] = float(band["median"])
            model["price_source"] = "live"
            live_applied += 1
        else:
            model["price_source"] = model.get("price_source", "curated")

    # 用修正后的基准价重新归一化、打分、重建推荐与行情
    _score(result["models"], dims, care, ignore)
    ranked = sorted(result["models"], key=lambda m: m["score"], reverse=True)
    result["recommendations"], result["why_not"] = _recommend(
        result["models"], dims, care, ignore
    )
    result["matrix"] = _matrix_rows(result["models"], ranked[0])
    result["market"] = _market_rows(result["models"], budget_min, budget_max)
    result["meta"]["live_market_applied"] = live_applied
    return result


def _budget_status(price_range: list[float], budget_min: int | None, budget_max: int | None) -> str:
    low, high = price_range
    if budget_max and low > budget_max:
        return "略超预算"
    if budget_min and high < budget_min:
        return "低于预算"
    return "预算内"
