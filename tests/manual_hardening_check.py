"""在线加固验收脚本（本地）。"""
import gzip
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"


def get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def post(path, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


print("== 1. 健康检查 ==")
s, h, b = get("/api/health")
print(s, json.loads(b.decode("utf-8")))

print("== 2. 安全响应头 ==")
s, h, b = get("/")
print("nosniff:", h.get("X-Content-Type-Options"),
      "| DENY:", h.get("X-Frame-Options"),
      "| Referrer:", h.get("Referrer-Policy"))

print("== 3. Gzip 压缩 ==")
s, h, b = get("/", headers={"Accept-Encoding": "gzip"})
raw = gzip.decompress(b)
print("Content-Encoding:", h.get("Content-Encoding"),
      "| 压缩后:", len(b), "B | 解压后:", len(raw), "B |", "内容OK" if "买前尽调" in raw.decode("utf-8") else "内容异常")

print("== 4. 请求体过大 413 ==")
s, h, b = post("/api/advise", {"query": "二手相机", "pad": "x" * 70000})
print(s, b.decode("utf-8")[:60])

print("== 5. 正常决策卡（应不受影响） ==")
s, h, b = post("/api/advise", {"query": "二手相机", "budget_min": 4000,
                               "budget_max": 8000,
                               "care": ["performance", "portability"],
                               "ignore": ["battery"]})
d = json.loads(b.decode("utf-8"))
print(s, "| searches:", d["meta"]["searches"], "| quota:", d["meta"]["quota_used"],
      "| 首选:", d["recommendations"][0]["model"]["name"])
