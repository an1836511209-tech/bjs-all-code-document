"""工商查询与公开网页搜索的 MCP 工具测试。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import tests.support  # noqa: F401
from tests.support import RESPONSE_FIXTURES


def _http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    response.text = json.dumps(payload, ensure_ascii=False)
    return response


class QueryCompanyRegistryToolTests(unittest.TestCase):
    def test_returns_registry_summary_without_supplier_raw_fields(self) -> None:
        payload = json.loads((RESPONSE_FIXTURES / "qichacha_company.json").read_text(encoding="utf-8"))
        with patch(
            "data_mcp.shared.integrations.qichacha_client.http_request",
            return_value=_http_response(payload),
        ) as request:
            from data_mcp.mcp.server import query_company_registry

            result = query_company_registry("星河智贷科技有限公司")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tool"], "query_company_registry")
        company = result["data"]["company"]
        self.assertEqual(company["name"], "星河智贷科技有限公司")
        self.assertEqual(company["credit_code"], "91110000MA01234567")
        self.assertEqual(company["listed"], "否")
        self.assertEqual(company["industry"]["sub_industry"], "软件和信息技术服务业")
        self.assertEqual(company["shareholders"][0]["name"], "红杉资本中国有限公司")
        self.assertEqual(company["executives"][0]["title"], "执行董事")
        self.assertNotIn("ContactInfo", company)
        self.assertNotIn("ImageUrl", company)
        self.assertEqual(result["sources"][0]["name"], "qichacha")
        url = request.call_args.args[1]
        self.assertIn("searchKey=", url)
        self.assertIn("ECIInfoVerify/GetInfo", url)
        self.assertIn("Token", request.call_args.kwargs["headers"])

    def test_no_result_status_is_empty(self) -> None:
        payload = {"Status": "201", "Message": "查询无结果", "Result": None}
        with patch(
            "data_mcp.shared.integrations.qichacha_client.http_request",
            return_value=_http_response(payload),
        ):
            from data_mcp.mcp.server import query_company_registry

            result = query_company_registry("不存在的企业有限公司")

        self.assertEqual(result["status"], "empty")
        self.assertIsNone(result["data"]["company"])
        self.assertEqual(result["warnings"][0]["code"], "COMPANY_NOT_FOUND")

    def test_nonexact_name_is_warning_and_never_returns_another_company(self) -> None:
        payload = json.loads((RESPONSE_FIXTURES / "qichacha_company.json").read_text(encoding="utf-8"))
        with patch("data_mcp.shared.integrations.qichacha_client.http_request", return_value=_http_response(payload)):
            from data_mcp.mcp.server import query_company_registry
            result = query_company_registry("星河智贷")
        self.assertEqual(result["status"], "empty")
        self.assertIsNone(result["data"]["company"])
        self.assertEqual(result["warnings"][0]["code"], "COMPANY_NAME_NOT_EXACT")
        self.assertTrue(result["warnings"][0]["retryable"])

    def test_upstream_failure_is_failed_without_response_body(self) -> None:
        with patch(
            "data_mcp.shared.integrations.qichacha_client.http_request",
            side_effect=RuntimeError("secret body https://api.qichacha.com/raw"),
        ):
            from data_mcp.mcp.server import query_company_registry

            result = query_company_registry("星河智贷科技有限公司")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})
        self.assertNotIn("secret", result["summary"])
        self.assertNotIn("http", result["summary"].lower())

    def test_blank_company_name_fails_validation(self) -> None:
        from data_mcp.mcp.server import query_company_registry

        result = query_company_registry("  ")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["warnings"][0]["code"], "VALIDATION")


class SearchCompanyWebToolTests(unittest.TestCase):
    def test_default_templates_return_deduped_results(self) -> None:
        first = json.loads((RESPONSE_FIXTURES / "zhipu_search.json").read_text(encoding="utf-8"))
        second = json.loads(json.dumps(first))
        second["search_result"][0]["link"] = "https://example.com/news/2"
        second["search_result"][0]["title"] = "星河智贷科技有限公司 行业报道"
        with patch(
            "data_mcp.features.project_profile.zhipu_client.http_request",
            side_effect=[_http_response(first), _http_response(second)],
        ) as request:
            from data_mcp.mcp.server import search_company_web

            result = search_company_web("星河智贷科技有限公司")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["company_name"], "星河智贷科技有限公司")
        self.assertEqual(len(result["data"]["searches"]), 2)
        self.assertEqual(result["data"]["searches"][0]["results"][0]["site_name"], "示例新闻")
        self.assertNotIn("request_id", result["data"])
        queries = [call.kwargs["json"]["search_query"] for call in request.call_args_list]
        self.assertEqual(
            queries,
            ["星河智贷科技有限公司 主营业务 产品", "星河智贷科技有限公司 行业 赛道"],
        )
        self.assertTrue(request.call_args.kwargs["headers"]["Authorization"].startswith("Bearer "))

    def test_search_keywords_replace_default_templates(self) -> None:
        payload = json.loads((RESPONSE_FIXTURES / "zhipu_search.json").read_text(encoding="utf-8"))
        with patch(
            "data_mcp.features.project_profile.zhipu_client.http_request",
            return_value=_http_response(payload),
        ) as request:
            from data_mcp.mcp.server import search_company_web

            result = search_company_web("星河智贷科技有限公司", search_keywords="2024年营业收入")

        self.assertEqual(result["status"], "success")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(
            request.call_args.kwargs["json"]["search_query"],
            "星河智贷科技有限公司 2024年营业收入",
        )

    def test_partial_when_one_query_fails(self) -> None:
        payload = json.loads((RESPONSE_FIXTURES / "zhipu_search.json").read_text(encoding="utf-8"))
        with patch(
            "data_mcp.features.project_profile.zhipu_client.http_request",
            side_effect=[_http_response(payload), RuntimeError("upstream")],
        ):
            from data_mcp.mcp.server import search_company_web

            result = search_company_web("星河智贷科技有限公司")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["data"]["searches"]), 1)
        self.assertTrue(result["warnings"])

    def test_all_queries_failing_is_failed(self) -> None:
        with patch(
            "data_mcp.features.project_profile.zhipu_client.http_request",
            side_effect=RuntimeError("upstream"),
        ):
            from data_mcp.mcp.server import search_company_web

            result = search_company_web("星河智贷科技有限公司")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})
        self.assertNotIn("upstream", result["summary"])

    def test_empty_search_result(self) -> None:
        with patch(
            "data_mcp.features.project_profile.zhipu_client.http_request",
            return_value=_http_response({"search_result": []}),
        ):
            from data_mcp.mcp.server import search_company_web

            result = search_company_web("星河智贷科技有限公司", search_keywords=["融资"])

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["data"]["searches"], [])
