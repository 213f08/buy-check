"""买前尽调 · 零依赖服务器（标准库实现，含在线加固）。

用法：
    python server.py            # http://127.0.0.1:8010
    python server.py 8080

内置在线加固（均可通过环境变量调整，见 .env.example）：
- 每 IP 滑动窗口限流（RATE_LIMIT_PER_MIN，默认 20 次/分，仅限 POST 接口）
- 请求体大小上限（MAX_BODY_BYTES，默认 64KB）
- 安全响应头（nosniff / DENY / Referrer-Policy）
- Gzip 响应压缩（>1KB 且客户端支持时）
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.app.advisor import advise, apply_live_prices  # noqa: E402
from backend.app.catalog import CATEGORIES, DIMENSION_LABELS  # noqa: E402
from backend.app.free_search import organize_items, sort_items  # noqa: E402
from backend.app.hardening import SlidingWindowRateLimiter  # noqa: E402
from backend.app.quota import DailyQuota  # noqa: E402
from backend.app.research import SearchCache, collect_price_evidence  # noqa: E402
from backend.app.yuanbao_client import YuanbaoSearchClient, snap_cnt  # noqa: E402

STATIC_DIR = ROOT / "backend" / "app" / "static"
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
]


def load_env_file(path: Path) -> None:
    """极简 .env 加载：不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ROOT / ".env")
client = YuanbaoSearchClient.from_env()
quota = DailyQuota(
    ROOT / "data" / "daily_quota.json",
    limit=int(os.getenv("DAILY_LIMIT", "60")),
)
search_cache = SearchCache(ttl_seconds=int(os.getenv("CACHE_TTL", "3600")))
rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("RATE_LIMIT_PER_MIN", "20")),
    window_seconds=60.0,
)
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "65536"))


def meta() -> dict:
    return {
        "categories": [
            {
                "key": key,
                "name": cat["name"],
                "keywords": cat["keywords"],
                "dimensions": [
                    {"key": dim, "label": DIMENSION_LABELS[dim]}
                    for dim in cat["dimensions"]
                ],
            }
            for key, cat in CATEGORIES.items()
        ],
        "mode": client.mode,
    }


def run_advise(payload: dict) -> dict:
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("query 不能为空")

    def to_int(value):
        try:
            return int(value) if value not in (None, "", 0) else None
        except (TypeError, ValueError):
            return None

    budget_min = to_int(payload.get("budget_min"))
    budget_max = to_int(payload.get("budget_max"))
    result = advise(
        query=query,
        budget_min=budget_min,
        budget_max=budget_max,
        care=payload.get("care") or [],
        ignore=payload.get("ignore") or [],
    )

    # ---- 实时行情证据（Live 模式）：额度守卫 -> 检索 -> 线索价反哺 -> 降级 ----
    searches = 0
    evidence: list[dict] = []
    quota_exceeded = False
    search_error = None
    if not client.mock:
        needed = len(result["models"])
        if quota.can_spend(needed):
            evidence, searches = collect_price_evidence(
                result["models"], client, cache=search_cache
            )
            quota.record(searches)
            has_items = any(e.get("items") for e in evidence)
            if searches > 0 and not has_items:
                search_error = "实时检索暂不可用（请检查密钥/网络），本报告基于精选数据生成。"
            # 线索价反哺：可信价格带修正打分基准与预算判定
            apply_live_prices(result, evidence, budget_min, budget_max)
        else:
            quota_exceeded = True

    result["evidence"] = evidence
    result["meta"].update({
        "mode": client.mode,
        "auth": client.auth,
        "searches": searches,
        "quota_used": quota.used_today(),
        "quota_limit": quota.limit,
        "quota_exceeded": quota_exceeded,
        "search_error": search_error,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return result


def run_search(payload: dict) -> dict:
    """自由检索模式：任意关键词 + 价格区间 → 整理后的链接清单。"""
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("关键词不能为空")

    def to_int(value):
        try:
            return int(value) if value not in (None, "", 0) else None
        except (TypeError, ValueError):
            return None

    price_min = to_int(payload.get("price_min"))
    price_max = to_int(payload.get("price_max"))
    cnt = snap_cnt(int(payload.get("cnt") or 10))

    if client.mock:
        return {
            "query": query, "price_min": price_min, "price_max": price_max,
            "items": [], "total": 0, "hits": 0,
            "mock": True,
            "note": "MOCK 模式没有实时检索结果；配置 YUANBAO_API_KEY 后即可搜索任意关键词。",
            "usage": {"searches": 0, "quota_used": quota.used_today(), "quota_limit": quota.limit},
        }

    if not quota.can_spend(1):
        return {
            "query": query, "price_min": price_min, "price_max": price_max,
            "items": [], "total": 0, "hits": 0,
            "quota_exceeded": True,
            "note": "今日实时检索额度已用完，请明天再来或联系博主调整 DAILY_LIMIT。",
            "usage": {"searches": 0, "quota_used": quota.used_today(), "quota_limit": quota.limit},
        }

    key = f"free::{query}::{cnt}"
    cached = search_cache.get(search_cache.key(key))
    if cached is None:
        pages = client.search(query, cnt=cnt)
        searches = 1
        search_cache.put(search_cache.key(key), pages)
        quota.record(1)
    else:
        pages = cached
        searches = 0

    items = [
        {
            "title": p.title, "url": p.url, "site": p.site, "date": p.date,
            "score": p.score, "passage": p.passage[:300],
        }
        for p in pages
    ]
    organized = organize_items(items, price_min, price_max)
    hits = sum(1 for it in organized if it["price_hit"] is True)
    return {
        "query": query, "price_min": price_min, "price_max": price_max,
        "items": organized, "total": len(organized), "hits": hits,
        "mock": False, "searches": searches, "cached": cached is not None,
        "usage": {"searches": searches, "quota_used": quota.used_today(), "quota_limit": quota.limit},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # 所有响应都带 Content-Length，可安全长连接
    server_version = "BuyCheck/1.1"
    timeout = 30

    def log_message(self, fmt: str, *args) -> None:
        pass  # 静音访问日志；错误仍走 log_error 到 stderr（systemd journal 可见）

    # ---- 统一响应出口：安全头 + Gzip ----
    def _send(self, body: bytes, content_type: str, status: int = 200,
              extra: list[tuple[str, str]] | None = None) -> None:
        headers = list(SECURITY_HEADERS) + list(extra or [])
        accept = self.headers.get("Accept-Encoding", "")
        if len(body) > 1024 and "gzip" in accept.lower():
            body = gzip.compress(body, compresslevel=6)
            headers.append(("Content-Encoding", "gzip"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200,
              extra: list[tuple[str, str]] | None = None) -> None:
        self._send(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8", status, extra,
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send((STATIC_DIR / "index.html").read_bytes(),
                       "text/html; charset=utf-8")
            return
        if self.path == "/api/meta":
            self._json(meta())
            return
        if self.path == "/api/health":
            self._json({
                "ok": True,
                "mode": client.mode,
                "quota_used": quota.used_today(),
                "quota_limit": quota.limit,
            })
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/api/advise", "/api/search"):
            self._json({"error": "not found"}, 404)
            return

        # 每 IP 限流（在读取请求体之前拒绝，因此该响应必须关闭连接）
        ip = self.client_address[0]
        if not rate_limiter.allow(ip):
            wait = rate_limiter.retry_after(ip)
            self._json(
                {"error": f"请求太频繁，请 {wait} 秒后再试"},
                429, extra=[("Retry-After", str(wait)), ("Connection", "close")],
            )
            self.close_connection = True
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY_BYTES:
                self._json({"error": "请求体过大"}, 413,
                           extra=[("Connection", "close")])
                self.close_connection = True
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/api/search":
                self._json(run_search(payload))
            else:
                self._json(run_advise(payload))
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            stamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{stamp}] {self.path} 处理失败: {exc}", file=sys.stderr)
            self._json({"error": f"生成失败：{exc}"}, 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    host = os.getenv("HOST", "127.0.0.1")
    print(
        f"买前尽调 running: http://{host}:{port}  (mode={client.mode}, "
        f"rate_limit={rate_limiter.max_requests}/min, max_body={MAX_BODY_BYTES}B)"
    )
    Server((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
