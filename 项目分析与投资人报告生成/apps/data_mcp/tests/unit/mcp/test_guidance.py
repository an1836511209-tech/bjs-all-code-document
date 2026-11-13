from __future__ import annotations

import asyncio
import unittest


class McpAgentGuidanceTests(unittest.TestCase):
    def test_server_instructions_cover_orchestration_and_result_handling(self) -> None:
        from data_mcp.mcp.server import mcp

        instructions = mcp.instructions or ""
        self.assertIn("推荐顺序", instructions)
        self.assertIn("调用前检查", instructions)
        self.assertIn("结果解释", instructions)
        self.assertIn("不得猜测必填参数", instructions)
        self.assertIn("profile=null", instructions)
        self.assertIn("shareholder_filter_applied=false", instructions)

    def test_tools_have_chinese_titles_detailed_descriptions_and_annotations(self) -> None:
        from data_mcp.mcp.server import mcp

        tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
        expected_titles = {
            "query_comparable_valuation": "历史成交可比估值查询",
            "extract_project_profile": "项目商业模式画像提取",
            "match_listed_peers": "上市公司可比标的匹配",
            "match_investors": "潜在投资人匹配",
            "query_track_labels": "查询企业赛道标签",
            "query_company_registry": "企业工商信息查询",
            "search_company_web": "企业公开网页搜索",
            "query_cbex_listing_financials": "北交互联挂牌财务查询",
        }

        self.assertEqual(set(tools), set(expected_titles))
        for name, title in expected_titles.items():
            tool = tools[name]
            self.assertEqual(tool.title, title)
            self.assertIn("何时调用", tool.description)
            self.assertIn("调用前", tool.description)
            self.assertIn("结果", tool.description)
            self.assertIsNotNone(tool.annotations)
            self.assertTrue(tool.annotations.read_only_hint)

        self.assertTrue(tools["query_comparable_valuation"].annotations.open_world_hint)
        self.assertTrue(tools["extract_project_profile"].annotations.open_world_hint)
        self.assertFalse(tools["match_listed_peers"].annotations.open_world_hint)
        self.assertTrue(tools["match_investors"].annotations.open_world_hint)
        self.assertTrue(tools["query_track_labels"].annotations.open_world_hint)
        self.assertTrue(tools["query_company_registry"].annotations.open_world_hint)
        self.assertTrue(tools["search_company_web"].annotations.open_world_hint)
        self.assertTrue(tools["query_cbex_listing_financials"].annotations.open_world_hint)


if __name__ == "__main__":
    unittest.main()
