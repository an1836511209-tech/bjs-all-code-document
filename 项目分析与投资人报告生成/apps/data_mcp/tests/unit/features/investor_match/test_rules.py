"""投资人匹配领域规则单测。"""

from __future__ import annotations

import unittest

import tests.support  # noqa: F401


class NormalizeNameTests(unittest.TestCase):
    def test_strips_suffix_and_spaces(self) -> None:
        from data_mcp.features.investor_match.rules import normalize_investor_name

        self.assertEqual(
            normalize_investor_name("  红杉资本中国　有限公司 "),
            normalize_investor_name("红杉资本中国"),
        )

    def test_case_insensitive(self) -> None:
        from data_mcp.features.investor_match.rules import normalize_investor_name

        self.assertEqual(normalize_investor_name("ABC Capital"), normalize_investor_name("abc capital"))


class ScoreTests(unittest.TestCase):
    def test_equal_weights_average(self) -> None:
        from data_mcp.features.investor_match.rules import compute_weight_score

        self.assertAlmostEqual(compute_weight_score(1, 2, 3), 2.0)
        self.assertAlmostEqual(compute_weight_score(None, "", 3), 1.0)


class ClassifyTests(unittest.TestCase):
    def test_category_field(self) -> None:
        from data_mcp.features.investor_match.rules import classify_investor_type

        self.assertEqual(classify_investor_type("张三", "个人投资者"), "个人")
        self.assertEqual(classify_investor_type("某某", "机构客户"), "机构")

    def test_heuristic_and_default(self) -> None:
        from data_mcp.features.investor_match.rules import classify_investor_type

        self.assertEqual(classify_investor_type("某某投资基金"), "机构")
        self.assertEqual(classify_investor_type("李四"), "个人")
        self.assertEqual(classify_investor_type("无名", default_institution=True), "机构")


class FilterAndDedupeTests(unittest.TestCase):
    def test_filter_shareholders(self) -> None:
        from data_mcp.features.investor_match.rules import filter_out_shareholders

        cands = [
            {"name": "红杉资本中国有限公司"},
            {"name": "独立基金A"},
        ]
        out = filter_out_shareholders(cands, ["红杉资本中国"])
        self.assertEqual([c["name"] for c in out], ["独立基金A"])

    def test_dedupe_keeps_internal(self) -> None:
        from data_mcp.features.investor_match.rules import dedupe_network_against_internal

        internal = [{"name": "红杉资本中国有限公司"}]
        network = [
            {"name": "红杉资本中国"},
            {"name": "高瓴资本"},
            {"name": "高瓴资本"},
        ]
        out = dedupe_network_against_internal(network, internal)
        self.assertEqual([c["name"] for c in out], ["高瓴资本"])


if __name__ == "__main__":
    unittest.main()
