"""北交互联财务采集与 MCP 响应测试。不访问外网。"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from data_mcp.features.cbex_financials.collector import (
    Client,
    collect_listing_financials,
    extract_financial_data,
    parse_candidates,
)
from data_mcp.mcp.responses import adapt_cbex_listing_financials
from data_mcp.mcp.schemas import validate_tool_output

PROJECT = "示例科技股份有限公司增资项目"
DETAIL = "https://otc.cbex.com/zzkg/detail/1001.html"
DETAIL_OTHER = "https://otc.cbex.com/zzkg/detail/1002.html"
LIST_URL = "https://otc.cbex.com/page/zzkg/search/search_li"

FINANCIAL_PAGE = f"""
<html><head><title>{PROJECT}</title></head><body>
<h1>{PROJECT}</h1>
<table>
<tr><td>主要财务指标（万元）</td><td></td><td></td><td></td></tr>
<tr><td></td><td>2022年</td><td>2023年</td><td>2024年</td></tr>
<tr><td>资产总计（万元）</td><td>100</td><td>200</td><td>300</td></tr>
<tr><td>负债合计（万元）</td><td>40</td><td>50</td><td>60</td></tr>
<tr><td>所有者权益合计（万元）</td><td>60</td><td>150</td><td>240</td></tr>
<tr><td>营业收入（万元）</td><td>10</td><td>20</td><td>30</td></tr>
<tr><td>净利润（万元）</td><td>1</td><td>2</td><td>3</td></tr>
</table>
</body></html>
"""


def _anchor(url: str, title: str) -> str:
    return f'<a href="{url}" title="{title}">{title}</a>'


class FakeClient(Client):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__()
        self.pages = pages

    def fetch(self, url: str, data: dict[str, Any] | None = None, referer: str = "") -> str:
        if url not in self.pages:
            raise AssertionError(f"unexpected url: {url}")
        return self.pages[url]


class CbexFinancialParserTests(unittest.TestCase):
    def test_candidate_deadlines_belong_to_their_own_project(self) -> None:
        html = ('<html><ul><li>' + _anchor(DETAIL, PROJECT)
                + '<span>披露起止日期：2026-10-01 至 2026-11-30</span></li><li>'
                + _anchor(DETAIL_OTHER, PROJECT + '二次挂牌')
                + '<span>信息披露截止日期：2026年12月31日</span></li><li>'
                + _anchor(DETAIL.replace('1001', '1003'), '第三个项目名称')
                + '<span>成立日期：2020-01-01</span></li></ul></html>')
        items = parse_candidates(html, 'zz_gz')
        self.assertEqual([i['disclosure_end_date'] for i in items], ['2026-11-30', '2026-12-31', ''])
        result = collect_listing_financials(PROJECT, category='zz_gz', client=FakeClient({LIST_URL: html}))
        self.assertEqual(result['stage'], 'selection_required')
        self.assertEqual(result['candidates'][0]['disclosure_end_date'], '2026-11-30')
        validate_tool_output('query_cbex_listing_financials', adapt_cbex_listing_financials(result))

    def test_selected_candidate_url_fetches_detail_without_search(self) -> None:
        result = collect_listing_financials(PROJECT, detail_url=DETAIL,
                                           client=FakeClient({DETAIL: FINANCIAL_PAGE}))
        self.assertEqual(result['stage'], 'done')
        self.assertEqual(len(result['annual']), 3)

    def test_extracts_three_annual_statements_in_wan(self) -> None:
        parsed = extract_financial_data(FINANCIAL_PAGE)
        self.assertEqual(parsed["quality"]["status"], "multi_year_extracted")
        self.assertEqual([item["period"] for item in parsed["annual"]], ["2022", "2023", "2024"])
        self.assertEqual(parsed["annual"][2]["values"]["revenue"], "30")
        self.assertEqual(parsed["annual"][2]["values"]["net_profit"], "3")
        self.assertEqual(parsed["annual"][0]["missing_core_fields"], [])
        self.assertNotIn("raw", parsed["annual"][0])

    def test_unique_search_match_opens_detail_page(self) -> None:
        client = FakeClient(
            {
                LIST_URL: "<html><div>" + _anchor("/zzkg/detail/1001.html", PROJECT) + "</div></html>",
                DETAIL: FINANCIAL_PAGE,
            }
        )
        result = collect_listing_financials(PROJECT, category="zz_gz", client=client)
        self.assertEqual(result["stage"], "done")
        self.assertEqual(result["detail_url"], DETAIL)
        self.assertEqual(result["quality_status"], "multi_year_extracted")
        self.assertEqual(len(result["annual"]), 3)

    def test_multiple_matches_require_selection_without_fetching_detail(self) -> None:
        html = "<html><div>" + _anchor("/zzkg/detail/1001.html", PROJECT)
        html += _anchor("/zzkg/detail/1002.html", PROJECT) + "</div></html>"
        client = FakeClient({LIST_URL: html})
        result = collect_listing_financials(PROJECT, category="zz_gz", client=client)
        self.assertEqual(result["stage"], "selection_required")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["annual"], [])

    def test_direct_detail_url_rejects_other_hosts(self) -> None:
        with self.assertRaises(ValueError):
            collect_listing_financials(PROJECT, detail_url="https://example.com/zzkg/detail/1.html")

    def test_adapter_success_partial_empty_and_selection(self) -> None:
        found = collect_listing_financials(
            PROJECT,
            category="zz_gz",
            client=FakeClient(
                {
                    LIST_URL: "<html><div>" + _anchor("/zzkg/detail/1001.html", PROJECT) + "</div></html>",
                    DETAIL: FINANCIAL_PAGE,
                }
            ),
        )
        success = adapt_cbex_listing_financials(found)
        validate_tool_output("query_cbex_listing_financials", success)
        self.assertEqual(success["status"], "success")
        self.assertEqual(success["data"]["unit"], "万元")
        self.assertEqual(success["data"]["annual"][0]["values"]["total_assets"], "100")

        found["issues"] = ["同一期间指标冲突:2024:revenue"]
        partial = adapt_cbex_listing_financials(found)
        validate_tool_output("query_cbex_listing_financials", partial)
        self.assertEqual(partial["status"], "partial")

        empty = adapt_cbex_listing_financials(
            {
                "stage": "not_found",
                "project_name": PROJECT,
                "matched_project_name": "",
                "detail_url": "",
                "project_type": "",
                "match_score": None,
                "quality_status": "",
                "annual": [],
                "latest": [],
                "candidates": [],
                "issues": [],
            }
        )
        validate_tool_output("query_cbex_listing_financials", empty)
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["data"]["annual"], [])

        selection = adapt_cbex_listing_financials(
            {
                "stage": "selection_required",
                "project_name": PROJECT,
                "matched_project_name": "",
                "detail_url": "",
                "project_type": "",
                "match_score": None,
                "quality_status": "",
                "annual": [],
                "latest": [],
                "candidates": [
                    {
                        "project_name": PROJECT,
                        "detail_url": DETAIL,
                        "project_type": "企业增资（国资）",
                        "match_score": 100,
                    },
                    {
                        "project_name": PROJECT,
                        "detail_url": DETAIL_OTHER,
                        "project_type": "企业增资（国资）",
                        "match_score": 100,
                    },
                ],
                "issues": [],
            }
        )
        validate_tool_output("query_cbex_listing_financials", selection)
        self.assertEqual(selection["status"], "partial")
        self.assertEqual(len(selection["data"]["candidates"]), 2)

    def test_mcp_tool_returns_failed_envelope_for_blank_name(self) -> None:
        from data_mcp.mcp.server import query_cbex_listing_financials

        result = query_cbex_listing_financials(project_name=" ")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})

    def test_mcp_tool_uses_collector_result(self) -> None:
        from data_mcp.mcp.server import query_cbex_listing_financials

        payload = {
            "stage": "done",
            "project_name": PROJECT,
            "matched_project_name": PROJECT,
            "detail_url": DETAIL,
            "project_type": "企业增资（国资）",
            "match_score": 100,
            "quality_status": "multi_year_extracted",
            "annual": [
                {
                    "kind": "annual",
                    "period": "2024",
                    "values": {"revenue": "30", "net_profit": "3"},
                    "missing_core_fields": ["total_assets", "total_liabilities", "owners_equity"],
                }
            ],
            "latest": [],
            "candidates": [],
            "issues": ["页面使用近三年模板，但有效年度少于三年；检查原文是否留空"],
        }
        with patch(
            "data_mcp.mcp.server.call_query_cbex_listing_financials",
            return_value=payload,
        ):
            result = query_cbex_listing_financials(project_name=PROJECT, category="zz_gz")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["tool"], "query_cbex_listing_financials")
        self.assertEqual(result["data"]["detail_url"], DETAIL)


if __name__ == "__main__":
    unittest.main()
