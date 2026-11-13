# apps/data_mcp/tests/unit/features/investor_match/test_tag_normalize.py
from __future__ import annotations

import unittest


class StripWrappingQuotesTests(unittest.TestCase):
    def test_strips_paired_double_and_single_quotes(self) -> None:
        from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes

        self.assertEqual(strip_wrapping_quotes('"住宿业"'), "住宿业")
        self.assertEqual(strip_wrapping_quotes("'餐饮业'"), "餐饮业")
        self.assertEqual(strip_wrapping_quotes('  "物业管理"  '), "物业管理")
        self.assertEqual(strip_wrapping_quotes('""电信""'), "电信")

    def test_leaves_clean_and_internal_quotes(self) -> None:
        from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes

        self.assertEqual(strip_wrapping_quotes("集成电路制造"), "集成电路制造")
        self.assertEqual(strip_wrapping_quotes('含"内部"引号'), '含"内部"引号')
        self.assertEqual(strip_wrapping_quotes(""), "")
        self.assertEqual(strip_wrapping_quotes("   "), "")


if __name__ == "__main__":
    unittest.main()
