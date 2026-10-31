"""自由检索联调脚本（本地验证后可删）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8010"

for q, lo, hi in [
    ("尼康 Z5 二手 价格 行情", 4000, 6500),
    ("小新pro14 二手 出 价格", 2500, 4000),
]:
    body = json.dumps({"query": q, "price_min": lo, "price_max": hi}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/search", data=body, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
    print(f"== {q} | total {d['total']} | hits {d['hits']} | quota {d['usage']['quota_used']}")
    for it in d["items"][:4]:
        row = {"t": it["title"][:28], "prices": it["prices"], "hit": it["price_hit"], "site": it["site"][:10]}
        print(json.dumps(row, ensure_ascii=False))
    print()
