"""自由检索模式（整理链接、价格标注、排序）的单元测试（离线）。"""
import unittest

from backend.app.free_search import extract_item_prices, organize_items, sort_items


def make_item(title, passage, url="u"):
    return {"title": title, "passage": passage, "url": url, "site": "s", "date": "", "score": 0.8}


class TestExtract(unittest.TestCase):
    def test_basic_and_range(self):
        text = "EOS RP 二手行情 4200-5000 元，单机 4500 元"
        self.assertEqual(extract_item_prices(text), [4200, 4500, 5000])

    def test_wan_unit(self):
        self.assertEqual(extract_item_prices("这套设备 1.2万元 出"), [12000])

    def test_filters_noise(self):
        """「快门10万次」「3元贴膜」这类不是价格。"""
        text = "快门10万次，快门数完好；另售镜盒 3 元；机身 4600 元"
        self.assertEqual(extract_item_prices(text), [4600])


class TestOrganize(unittest.TestCase):
    def test_hit_classification(self):
        items = [
            make_item("a", "4500 元"),
            make_item("b", "6500 元"),
            make_item("c", "成色极佳，快门 2 万次"),
        ]
        out = organize_items(items, 4000, 5000)
        self.assertEqual(out[0]["price_hit"], True)
        self.assertEqual(out[1]["price_hit"], False)
        self.assertEqual(out[2]["price_hit"], None)

    def test_no_range_all_none(self):
        out = organize_items([make_item("a", "4500 元")], None, None)
        self.assertIsNone(out[0]["price_hit"])


class TestSort(unittest.TestCase):
    def setUp(self):
        self.items = organize_items(
            [make_item("mid", "6500 元", "u1"),
             make_item("none", "成色好", "u2"),
             make_item("low", "4500 元", "u3"),
             make_item("high", "9000 元", "u4")],
            None, None,
        )

    def test_asc_none_last(self):
        out = sort_items(self.items, "price_asc")
        self.assertEqual([i["title"] for i in out], ["low", "mid", "high", "none"])

    def test_desc_none_last(self):
        out = sort_items(self.items, "price_desc")
        self.assertEqual([i["title"] for i in out], ["high", "mid", "low", "none"])

    def test_relevance_keeps_order(self):
        out = sort_items(self.items, "relevance")
        self.assertEqual([i["title"] for i in out], ["mid", "none", "low", "high"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
