"""HTTP 层集成测试：真实 socket 起服务（强制 MOCK），验证加固行为。

环境变量必须在导入 server 之前设置；限流测试通过替换模块级
rate_limiter 实现用例间隔离，不依赖执行顺序。
"""
import gzip
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request

os.environ["MOCK"] = "1"
os.environ["RATE_LIMIT_PER_MIN"] = "3"
os.environ["MAX_BODY_BYTES"] = "200"

import server  # noqa: E402
from backend.app.hardening import SlidingWindowRateLimiter  # noqa: E402


class TestHTTPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    # ---- helpers ----
    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        return self._open(req)

    def post(self, path, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=body, method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self._open(req)

    @staticmethod
    def _open(req):
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def fresh_limiter(self, limit):
        server.rate_limiter = SlidingWindowRateLimiter(
            limit, 60.0, now_fn=time.time
        )

    def setUp(self):
        self._old_limiter = server.rate_limiter

    def tearDown(self):
        server.rate_limiter = self._old_limiter

    # ---- GET ----
    def test_index_ok_with_security_headers(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("买前尽调", body.decode("utf-8"))

    def test_gzip_when_accepted(self):
        status, headers, body = self.get("/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertIn("买前尽调", gzip.decompress(body).decode("utf-8"))

    def test_health_mock_mode(self):
        status, _, body = self.get("/api/health")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["mode"], "mock")

    def test_unknown_path_404(self):
        self.assertEqual(self.get("/nope")[0], 404)
        self.assertEqual(self.post("/other", {"a": 1})[0], 404)

    # ---- POST /api/advise ----
    def test_advise_ok_in_mock(self):
        self.fresh_limiter(10)
        status, _, body = self.post("/api/advise", {
            "query": "二手相机", "budget_min": 4000, "budget_max": 8000,
            "care": ["performance", "portability"], "ignore": ["battery"],
        })
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(data["meta"]["mock"], True)
        self.assertEqual(len(data["matrix"]), 3)
        self.assertEqual(data["evidence"], [])

    def test_advise_off_topic_400(self):
        self.fresh_limiter(10)
        status, _, body = self.post("/api/advise", {"query": "红烧肉"})
        self.assertEqual(status, 400)
        self.assertIn("暂时只支持", body.decode("utf-8"))

    def test_advise_empty_body_400(self):
        self.fresh_limiter(10)
        req = urllib.request.Request(
            self.base + "/api/advise", data=b"", method="POST",
            headers={"Content-Type": "application/json"},
        )
        status, _, body = self._open(req)
        self.assertEqual(status, 400)

    def test_body_too_large_413(self):
        self.fresh_limiter(10)
        status, _, body = self.post(
            "/api/advise", {"query": "二手相机", "pad": "x" * 500}
        )
        self.assertEqual(status, 413)

    def test_rate_limit_429(self):
        self.fresh_limiter(2)
        payload = {"query": "二手相机", "care": ["price"], "ignore": []}
        self.assertEqual(self.post("/api/advise", payload)[0], 200)
        self.assertEqual(self.post("/api/advise", payload)[0], 200)
        status, headers, body = self.post("/api/advise", payload)
        self.assertEqual(status, 429)
        self.assertGreaterEqual(int(headers.get("Retry-After", "0")), 1)
        self.assertIn("请求太频繁", body.decode("utf-8"))
        # 限流后其他 IP 不受影响（这里用「清空计数」模拟窗口滑过）
        self.fresh_limiter(2)
        self.assertEqual(self.post("/api/advise", payload)[0], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
