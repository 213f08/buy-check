"""额度守卫与 API 响应解析的单元测试（全部离线，不发起真实请求）。"""
import json
import tempfile
import unittest
from pathlib import Path

from backend.app.quota import DailyQuota
from backend.app.yuanbao_client import _parse_pages, snap_cnt


class TestSnapCnt(unittest.TestCase):
    def test_snap(self):
        self.assertEqual(snap_cnt(1), 10)
        self.assertEqual(snap_cnt(15), 20)
        self.assertEqual(snap_cnt(41), 50)
        self.assertEqual(snap_cnt(99), 50)


class TestParsePages(unittest.TestCase):
    def test_parses_json_string_pages(self):
        payload = {
            "Response": {
                "Pages": [
                    json.dumps({
                        "title": "A7M3 行情",
                        "passage": "二手约 6500 元",
                        "url": "https://example.com/a",
                        "site": "example.com",
                        "date": "2026/10/17 23:05:00",
                        "score": 0.91,
                        "authority_level": "A",
                    })
                ]
            }
        }
        pages = _parse_pages(payload)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].title, "A7M3 行情")
        self.assertEqual(pages[0].score, 0.91)
        self.assertEqual(pages[0].authority_level, "A")

    def test_missing_authority_defaults_empty(self):
        payload = {"Response": {"Pages": [json.dumps({"title": "t", "passage": "p"})]}}
        pages = _parse_pages(payload)
        self.assertEqual(pages[0].authority_level, "")
        self.assertEqual(pages[0].score, 0.0)

    def test_empty_pages(self):
        self.assertEqual(_parse_pages({"Response": {"Pages": []}}), [])
        self.assertEqual(_parse_pages({}), [])


class TestDailyQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_record_and_limit(self):
        quota = DailyQuota(self.path, limit=3)
        self.assertEqual(quota.used_today(), 0)
        self.assertTrue(quota.can_spend(3))
        quota.record(3)
        self.assertEqual(quota.used_today(), 3)
        self.assertFalse(quota.can_spend(1))
        self.assertTrue(quota.can_spend(0))

    def test_persists_across_instances(self):
        DailyQuota(self.path, limit=10).record(2)
        self.assertEqual(DailyQuota(self.path, limit=10).used_today(), 2)

    def test_corrupt_file_is_tolerated(self):
        self.path.write_text("not-json", encoding="utf-8")
        quota = DailyQuota(self.path, limit=5)
        self.assertEqual(quota.used_today(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
