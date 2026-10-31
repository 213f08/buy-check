"""线索价抽取与实时反哺打分的单元测试（离线）。"""
import unittest

from backend.app.advisor import advise, apply_live_prices
from backend.app.price_extractor import extract_live_prices, summarize_clues

EOSRP = {"id": "eos-rp", "name": "佳能 EOS RP", "aliases": ["EOS RP", "佳能RP"]}
PLAUSIBLE = (500, 100000)


class TestExtract(unittest.TestCase):
    def test_same_sentence_with_price(self):
        # 「成色好的到5000元」与型号子句相邻、句内无其他型号别名 → 收入
        # 注意：裸数字（无「元」）不收——「快门2万次」会被误读，宁可漏收
        items = [{"title": "行情", "passage": "佳能EOS RP二手价4500元左右，成色好的到5000元。", "url": "u1", "site": "s1", "date": "2026/10/01"}]
        clues = extract_live_prices(EOSRP, items, PLAUSIBLE, other_aliases={"索尼a7m3", "尼康z5"})
        self.assertEqual([c["value"] for c in clues], [4500, 5000])

    def test_cross_model_contamination_blocked(self):
        """「EOS RP 4500元，A7M3 6500元」绝不能把 6500 算给 EOS RP。"""
        items = [{"title": "对比帖", "passage": "佳能EOS RP二手4500元，索尼A7M3二手6500元。", "url": "u1", "site": "s1", "date": ""}]
        clues = extract_live_prices(EOSRP, items, PLAUSIBLE, other_aliases={"a7m3", "索尼a7m3"})
        self.assertEqual([c["value"] for c in clues], [4500])

    def test_range_prices(self):
        items = [{"title": "行情", "passage": "EOS RP 目前二手行情 4200-5000 元。", "url": "u1", "site": "s1", "date": ""}]
        clues = extract_live_prices(EOSRP, items, PLAUSIBLE)
        self.assertEqual(sorted(c["value"] for c in clues), [4200, 5000])

    def test_no_attribution_without_alias(self):
        """盘点页里其他机型的价格不能被错认。"""
        items = [{"title": "2026年10月相机回收参考价:40款机型",
                  "passage": "索尼A7M3回收价6200元，佳能R6回收价8000元，尼康Z6II回收价7000元。",
                  "url": "u1", "site": "s1", "date": ""}]
        clues = extract_live_prices(EOSRP, items, PLAUSIBLE)
        self.assertEqual(clues, [])

    def test_plausibility_filter(self):
        items = [{"title": "促销", "passage": "EOS RP 全新套装 8999 元，二手镜盒 3 元。", "url": "u1", "site": "s1", "date": ""}]
        clues = extract_live_prices(EOSRP, items, PLAUSIBLE)
        self.assertEqual([c["value"] for c in clues], [8999])

    def test_summarize_reliability(self):
        clues = [{"value": 4500}, {"value": 4600}]
        band = summarize_clues(clues)
        self.assertTrue(band["reliable"])
        single = summarize_clues([{"value": 4500}])
        self.assertFalse(single["reliable"])


class TestApplyLive(unittest.TestCase):
    def test_live_price_can_flip_ranking(self):
        result = advise("二手相机", 4000, 8000, ["price"], [])
        self.assertEqual(result["recommendations"][0]["model"]["name"], "佳能 EOS RP")

        # 构造证据：EOS RP 涨到 6900（1 条，不可信），Z5 出现可信的 4300/4400
        evidence = [
            {"model": "佳能 EOS RP", "items": [
                {"title": "EOS RP", "passage": "佳能EOS RP二手6900元。", "url": "u", "site": "s", "date": "", "score": 0.9, "authority_level": ""},
            ]},
            {"model": "索尼 A7M3", "items": []},
            {"model": "尼康 Z5", "items": [
                {"title": "Z5 行情A", "passage": "尼康Z5二手4300元。", "url": "u1", "site": "s", "date": "", "score": 0.9, "authority_level": ""},
                {"title": "Z5 行情B", "passage": "尼康Z5成交4400元。", "url": "u2", "site": "s", "date": "", "score": 0.9, "authority_level": ""},
            ]},
        ]
        apply_live_prices(result, evidence, 4000, 8000)
        z5 = next(m for m in result["models"] if m["name"] == "尼康 Z5")
        self.assertTrue(z5["live_band"]["reliable"])
        self.assertEqual(z5["price_source"], "live")
        # Z5 变便宜后应成为首选
        self.assertEqual(result["recommendations"][0]["model"]["name"], "尼康 Z5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
