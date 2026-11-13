"""真实 stdio MCP 集成测试（经 MCP 协议调用，而非直接调 Python 函数）。"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests.support import CONFIG_FIXTURES, RESPONSE_FIXTURES

MOCK_LOWCODE = RESPONSE_FIXTURES / "historical_valuation.json"
INTEGRATION_CONFIG = CONFIG_FIXTURES / "integration.yaml"


class _MockLowcodeHandler(BaseHTTPRequestHandler):
    payload: dict = {}

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
      length = int(self.headers.get("Content-Length", "0"))
      _ = self.rfile.read(length)
      body = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
      self.send_response(200)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)


class McpStdioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._env = {"DATA_MCP_CONFIG": str(INTEGRATION_CONFIG)}

    def test_list_tools_via_stdio(self) -> None:
        from data_mcp.mcp.client import DataMcpClient

        client = DataMcpClient(env=self._env, call_timeout_seconds=60.0)
        tools = client.list_tools_sync()
        self.assertIn("query_comparable_valuation", tools)
        self.assertIn("extract_project_profile", tools)
        self.assertIn("match_listed_peers", tools)
        self.assertIn("match_investors", tools)
        self.assertIn("query_track_labels", tools)
        self.assertIn("query_company_registry", tools)
        self.assertIn("search_company_web", tools)
        self.assertIn("query_cbex_listing_financials", tools)

    def test_match_listed_peers_via_stdio(self) -> None:
        from data_mcp.mcp.client import DataMcpClient

        client = DataMcpClient(env=self._env, call_timeout_seconds=120.0)
        result = client.call_tool_sync(
            "match_listed_peers",
            {
                "tags": ["动力电池", "储能"],
                "summary": "新能源中游电芯制造与储能系统",
                "top_n": 3,
            },
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["query"]["tags"], ["动力电池", "储能"])
        self.assertEqual(len(result["data"]["peers"]), 3)
        self.assertEqual(result["data"]["meta"]["embedding_backend"], "hash")
        self.assertEqual(result["data"]["meta"]["corpus_size"], 3)

    def test_query_comparable_valuation_via_stdio_with_mock_http(self) -> None:
        from data_mcp.mcp.client import DataMcpClient

        payload = json.loads(MOCK_LOWCODE.read_text(encoding="utf-8"))
        server = HTTPServer(("127.0.0.1", 0), _MockLowcodeHandler)
        _MockLowcodeHandler.payload = payload
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = f"http://127.0.0.1:{server.server_address[1]}"

        config_text = INTEGRATION_CONFIG.read_text(encoding="utf-8")
        config_text = config_text.replace(
            "http://127.0.0.1:0/mock-lowcode",
            host,
        )
        temp_config = CONFIG_FIXTURES / "_runtime_stdio_lowcode_config.yaml"
        temp_config.write_text(config_text, encoding="utf-8")
        try:
            client = DataMcpClient(
                env={"DATA_MCP_CONFIG": str(temp_config)},
                call_timeout_seconds=60.0,
            )
            result = client.call_tool_sync(
                "query_comparable_valuation",
                {
                    "tags": ["科技金融", "普惠金融"],
                    "company_name": "星河智贷科技",
                },
            )
        finally:
            server.shutdown()
            if temp_config.exists():
                temp_config.unlink()

        self.assertEqual(result["status"], "success")
        self.assertIn("可比项目", result["data"]["content"])

    def test_client_rejects_invalid_input_before_stdio(self) -> None:
        from data_mcp.mcp.client import DataMcpClient
        from data_mcp.mcp.errors import McpClientError, McpErrorCode

        client = DataMcpClient(env=self._env, validate_io=True)
        with self.assertRaises(McpClientError) as ctx:
            client.call_tool_sync(
                "extract_project_profile",
                {"company_name": "测试公司"},
            )
        self.assertEqual(ctx.exception.code, McpErrorCode.VALIDATION)

    def test_client_rejects_env_in_tool_input(self) -> None:
        from data_mcp.mcp.client import DataMcpClient
        from data_mcp.mcp.errors import McpClientError, McpErrorCode

        client = DataMcpClient(env=self._env, validate_io=True)
        with self.assertRaises(McpClientError) as ctx:
            client.call_tool_sync(
                "query_comparable_valuation",
                {
                    "tags": ["科技金融"],
                    "company_name": "星河智贷科技",
                    "env": "dev",
                },
            )
        self.assertEqual(ctx.exception.code, McpErrorCode.VALIDATION)


if __name__ == "__main__":
    unittest.main()
