"""异常脱敏：上游不应看到 HTTP 响应体、URL、配置路径等。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

import tests.support  # noqa: F401
from data_mcp.mcp.tool_errors import McpToolError, to_mcp_tool_error
from data_mcp.shared.http.errors import (
    ExternalServiceError,
    public_message_for_exception,
    raise_from_http_error,
)


class HttpErrorSanitizationTests(unittest.TestCase):
    def test_http_status_error_hides_response_body(self) -> None:
        response = MagicMock()
        response.status_code = 500
        response.text = "internal secret-token=abc123 https://internal.example/api"
        exc = httpx.HTTPStatusError("error", request=MagicMock(), response=response)

        with self.assertRaises(ExternalServiceError) as ctx:
            raise_from_http_error("hiagent", exc)

        message = str(ctx.exception)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("internal.example", message)
        self.assertIn("HTTP 500", message)

    def test_invalid_json_response_has_generic_message(self) -> None:
        from data_mcp.shared.http.errors import raise_invalid_json_response

        with self.assertRaises(ExternalServiceError) as ctx:
            raise_invalid_json_response(
                "hiagent",
                status_code=200,
                body='{"token":"leaked"}',
            )
        self.assertEqual(str(ctx.exception), "hiagent 返回格式无效")
        self.assertNotIn("leaked", str(ctx.exception))


class AdapterSanitizationTests(unittest.TestCase):
    @patch("data_mcp.features.historical_valuation.service.http_request")
    def test_comparable_valuation_hides_upstream_body_on_http_error(self, mock_request) -> None:
        response = MagicMock()
        response.status_code = 502
        response.text = "gateway leaked-body"
        mock_request.side_effect = httpx.HTTPStatusError(
            "502",
            request=MagicMock(),
            response=response,
        )

        from data_mcp.features.historical_valuation.service import query_comparable_valuation

        with self.assertRaises(ExternalServiceError) as ctx:
            query_comparable_valuation(tags=["科技金融"], company_name="测试公司")
        self.assertNotIn("leaked-body", str(ctx.exception))


class McpToolGuardTests(unittest.TestCase):
    def test_value_error_maps_to_validation(self) -> None:
        err = to_mcp_tool_error("match_listed_peers", ValueError("tags 不能为空"))
        self.assertIsInstance(err, McpToolError)
        self.assertEqual(err.code, "VALIDATION")
        self.assertEqual(str(err), "tags 不能为空")

    def test_corpus_dir_error_passes_through_to_agent(self) -> None:
        err = to_mcp_tool_error(
            "match_listed_peers",
            ValueError(
                "上市公司画像目录不存在: fixtures/no_such_dir。"
                "请在 config.yaml 的 listed_peer_match.data_dir 中配置有效目录。"
            ),
        )
        self.assertEqual(err.code, "VALIDATION")
        self.assertIn("上市公司画像目录不存在", str(err))
        self.assertIn("listed_peer_match.data_dir", str(err))

    def test_config_error_is_redacted(self) -> None:
        err = to_mcp_tool_error(
            "query_comparable_valuation",
            ValueError("请先在 apps/data_mcp/config.yaml 的 historical_valuation.dev.host 中填写地址"),
        )
        self.assertEqual(str(err), "配置无效或不完整")

    def test_external_service_error_passes_public_message(self) -> None:
        upstream = ExternalServiceError("hiagent", "hiagent 请求超时", detail="ConnectTimeout")
        err = to_mcp_tool_error("query_comparable_valuation", upstream)
        self.assertEqual(str(err), "hiagent 请求超时")
        self.assertNotIn("ConnectTimeout", str(err))

    def test_unknown_error_is_generic(self) -> None:
        err = to_mcp_tool_error("match_investors", RuntimeError("db password=secret"))
        self.assertEqual(str(err), "工具执行失败")
        self.assertNotIn("secret", str(err))

    def test_server_tool_wraps_upstream_failure(self) -> None:
        from data_mcp.mcp.server import query_comparable_valuation

        with patch(
            "data_mcp.mcp.server.call_query_comparable_valuation",
            side_effect=ExternalServiceError("hiagent", "hiagent 暂时不可用（HTTP 503）"),
        ):
            result = query_comparable_valuation(tags=["科技金融"], company_name="测试")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})
        self.assertEqual(result["warnings"][0]["code"], "UPSTREAM")
        self.assertNotIn("503", result["summary"])


class PublicMessageHelperTests(unittest.TestCase):
    def test_sanitize_config_path(self) -> None:
        message = public_message_for_exception(
            ValueError("请先在 config.yaml 的 project_profile.dev.token 中填写 token")
        )
        self.assertEqual(message, "配置无效或不完整")


if __name__ == "__main__":
    unittest.main()
