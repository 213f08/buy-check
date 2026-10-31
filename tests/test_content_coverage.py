"""内容覆盖与不相关输入测试：乱输入不崩、噪声不误报、品类数据完整。"""
import unittest

from backend.app.advisor import advise, detect_category
from backend.app.catalog import CATEGORIES, DIMENSION_LABELS
from backend.app.free_search import extract_item_prices, organize_items, sort_items
from backend.app.price_extractor import extract_live_prices


def item(title, passage, url="u"):
    return {"title": title, "passage": passage, "url": url, "site": "s",
            "date": "", "score": 0.8, "authority_level": ""}


class TestIrrelevantQueries(unittest.TestCase):
    """不相关 / 乱写的输入必须被明确拒绝，而不是硬出一个报告。"""

    def test_off_topic_rejected(self):
        # 注：英文关键词（camera/laptop/phone）是刻意支持的，不算 off-topic
        for q in ["红烧肉怎么做好吃", "洗衣机推荐", "量子力学期末复习",
                  "123456", "   "]:
            with self.assertRaises(ValueError):
                advise(q, 1000, 9000, ["price"], [])

    def test_english_query_supported(self):
        result = advise("used camera for sale", 4000, 8000, ["price"], [])
        self.assertEqual(result["category"]["key"], "camera")

    def test_html_like_query_still_works_if_category_hit(self):
        result = advise("<script>alert(1)</script>二手相机", 4000, 8000,
                        ["price"], [])
        self.assertEqual(result["category"]["key"], "camera")
        # 后端返回原文本，转义由前端负责
        self.assertIn("<script>", result["query"])

    def test_emoji_query(self):
        result = advise("📷📷二手相机📷", 4000, 8000, ["price"], [])
        self.assertEqual(result["category"]["key"], "camera")

    def test_long_query(self):
        result = advise("二手相机" + "很好" * 2000, 4000, 8000, ["price"], [])
        self.assertEqual(result["category"]["key"], "camera")

    def test_unknown_dimensions_ignored(self):
        result = advise("二手相机", 4000, 8000, ["胡说"], ["八道"])
        self.assertEqual(result["weights"]["care"], [])
        self.assertEqual(result["weights"]["ignore"], [])

    def test_care_ignore_same_key_ignore_wins(self):
        result = advise("二手相机", 4000, 8000, ["price"], ["price"])
        # ignore 在 care 之后写入，权重应为 0.15（后写覆盖）
        self.assertIn("price", result["weights"]["ignore"])

    def test_inverted_budget_falls_back(self):
        result = advise("二手相机", 8000, 3000, ["price"], [])
        self.assertTrue(result["budget"]["note"])
        self.assertEqual(len(result["matrix"]), 3)

    def test_zero_budget_means_no_filter(self):
        result = advise("二手相机", 0, 0, ["price"], [])
        self.assertEqual(len(result["matrix"]), 3)
        self.assertEqual(result["budget"]["note"], "")


class TestPriceNoise(unittest.TestCase):
    """自由检索里常见噪声不得被误读为价格。"""

    def test_noise_not_extracted(self):
        cases = [
            ("快门10万次", []),
            ("客服电话 13800138000", []),
            ("2026 年新品发布", []),
            ("二手价 $1,299", []),          # 外币暂不提取
            ("发光二极管 5mm", []),          # 数字后无「元」
            ("编号 99999999", []),           # 8 位数字超出正则单段
            ("重量 206g，含税 4600 元", [4600]),
        ]
        for text, expect in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_item_prices(text), expect)

    def test_valid_formats_still_extracted(self):
        self.assertEqual(extract_item_prices("4200-5000元"), [4200, 5000])
        self.assertEqual(extract_item_prices("这套 1.2万元 出"), [12000])
        self.assertEqual(extract_item_prices("4500元左右"), [4500])

    def test_organize_marks_noise_as_unrecognized(self):
        out = organize_items(
            [item("noise", "快门10万次，成色好"), item("priced", "4600 元")],
            4000, 5000,
        )
        self.assertIsNone(out[0]["price_hit"])
        self.assertTrue(out[1]["price_hit"])

    def test_sort_puts_noise_last(self):
        items = organize_items(
            [item("a", "6500 元"), item("b", "没价格"), item("c", "4500 元")],
            None, None,
        )
        self.assertEqual([i["title"] for i in sort_items(items, "price_asc")],
                         ["c", "a", "b"])


class TestLivePriceNoise(unittest.TestCase):
    def test_model_context_ignores_noise(self):
        model = {"id": "eos-rp", "name": "佳能 EOS RP", "aliases": ["EOS RP"]}
        items = [item("t", "EOS RP 到手 4600 元，快门 2 万次，成色 95新，2026年购入")]
        clues = extract_live_prices(model, items, (500, 100000))
        # 「2 万次」「95新」「2026年」都没有「元」收尾，不会被误读
        self.assertEqual([c["value"] for c in clues], [4600])


class TestCatalogCoverage(unittest.TestCase):
    """五个品类的数据完整性：乱数据进来，推荐就会乱出去。"""

    def test_all_categories_complete(self):
        seen_ids, seen_names = set(), set()
        for key, cat in CATEGORIES.items():
            with self.subTest(category=key):
                self.assertTrue(cat["name"])
                self.assertTrue(cat["keywords"])
                self.assertTrue(cat["positioning"])
                self.assertGreaterEqual(len(cat["inspection"]), 6)
                self.assertLessEqual(set(cat["dimensions"]),
                                     set(DIMENSION_LABELS.keys()))
                self.assertIn("price", cat["dimensions"])
                low_p, high_p = cat["price_plausible"]
                self.assertTrue(0 < low_p < high_p)

                self.assertEqual(len(cat["models"]), 3)
                for model in cat["models"]:
                    self.assertNotIn(model["id"], seen_ids)
                    self.assertNotIn(model["name"], seen_names)
                    seen_ids.add(model["id"])
                    seen_names.add(model["name"])

                    self.assertTrue(model["aliases"])
                    low, high = model["price_used"]
                    self.assertLessEqual(low, high)
                    self.assertGreaterEqual(low, low_p)
                    self.assertLessEqual(high, high_p)
                    self.assertGreater(model["price_new"], low)
                    self.assertGreater(model["weight_g"], 0)
                    for dim in model["scores"]:
                        self.assertIn(dim, cat["dimensions"])

    def test_discover_pool_no_collision_with_models(self):
        for key, cat in CATEGORIES.items():
            model_names = {m["name"] for m in cat["models"]}
            for pooled in cat.get("discover_pool", []):
                self.assertNotIn(pooled["name"], model_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
