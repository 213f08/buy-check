"""推荐引擎自测（不依赖网络 / FastAPI）。"""
import unittest

from backend.app.advisor import advise, detect_category


class TestDetect(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(detect_category("想买台二手相机"), "camera")
        self.assertEqual(detect_category("收一台轻薄本办公"), "laptop")
        self.assertEqual(detect_category("iPhone 15 二手"), "phone")
        self.assertEqual(detect_category("学生网课 iPad"), "tablet")
        self.assertEqual(detect_category("降噪头戴耳机"), "headphone")
        self.assertIsNone(detect_category("洗衣机"))


class TestAdvise(unittest.TestCase):
    def setUp(self):
        self.result = advise(
            query="二手相机",
            budget_min=4000,
            budget_max=8000,
            care=["performance", "portability"],
            ignore=["battery"],
        )

    def test_basic_shape(self):
        self.assertEqual(self.result["category"]["key"], "camera")
        self.assertEqual(len(self.result["matrix"]), 3)
        self.assertGreaterEqual(len(self.result["recommendations"]), 1)
        self.assertEqual(len(self.result["avoidance"]["inspection"]), 6)

    def test_primary_is_light_and_cheap(self):
        primary = self.result["recommendations"][0]
        self.assertEqual(primary["label"], "首选")
        self.assertEqual(primary["model"]["name"], "佳能 EOS RP")

    def test_upgrade_exists(self):
        labels = [r["label"] for r in self.result["recommendations"]]
        self.assertIn("加钱选", labels)

    def test_budget_filter(self):
        result = advise("二手相机", 3000, 4500, ["portability"], ["battery"])
        names = [m["name"] for m in result["matrix"]]
        self.assertEqual(names, ["佳能 EOS RP"])

    def test_unsupported(self):
        with self.assertRaises(ValueError):
            advise("洗衣机", 1000, 2000, ["price"], [])

    def test_laptop_default(self):
        result = advise("二手轻薄本", 3000, 5000, ["portability", "battery"], ["performance"])
        self.assertEqual(result["category"]["key"], "laptop")
        self.assertEqual(result["recommendations"][0]["model"]["name"], "MacBook Air M1")

    def test_phone(self):
        result = advise("二手手机", 2000, 5000, ["camera", "battery"], ["build"])
        self.assertEqual(result["category"]["key"], "phone")
        self.assertTrue(result["recommendations"])

    def test_tablet(self):
        result = advise("网课平板", 2000, 5000, ["performance", "screen"], ["portability"])
        self.assertEqual(result["category"]["key"], "tablet")
        # 手算复核：在乎性能+屏幕时，Air 5（8.2，便宜 ¥1150）压过 Pro（8.1）
        self.assertEqual(result["recommendations"][0]["model"]["name"], "iPad Air 5")
        upgrade = next((r for r in result["recommendations"] if r["role"] == "upgrade"), None)
        self.assertIsNotNone(upgrade)
        self.assertEqual(upgrade["model"]["name"], "iPad Pro 2021 11寸")

    def test_headphone(self):
        result = advise("降噪耳机", 800, 2000, ["sound", "battery"], ["build"])
        self.assertEqual(result["category"]["key"], "headphone")
        self.assertEqual(len(result["matrix"]), 3)
        # 耳机品类没有屏幕维度
        self.assertNotIn("screen", [d["key"] for d in result["category"]["dimensions"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
