"""用 mock 数据联测两个 MCP 工具：query_comparable_valuation / match_listed_peers。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import tests.support  # noqa: F401  # 设置 DATA_MCP_CONFIG
from tests.support import DATA_FIXTURES, RESPONSE_FIXTURES

PEER_FIXTURES = DATA_FIXTURES / "listed_peers"
MOCK_XLSX = PEER_FIXTURES / "companies.xlsx"
MOCK_LOWCODE = RESPONSE_FIXTURES / "historical_valuation.json"


def _mock_peer_config(**overrides):
    from data_mcp.shared.settings import load_listed_peer_match_config

    cfg = load_listed_peer_match_config()
    cfg = dict(cfg)
    cfg["data_dir"] = str(PEER_FIXTURES)
    cfg["embedding"] = dict(cfg["embedding"])
    cfg["embedding"]["backend"] = "hash"
    cfg["enable_rerank"] = False
    cfg["index_dir"] = str(PEER_FIXTURES / ".index")
    cfg.update(overrides)
    return cfg


class LoadComparableValuationConfigTests(unittest.TestCase):
    def test_dev_config_has_required_fields(self) -> None:
        from data_mcp.shared.settings import load_historical_valuation_config

        cfg = load_historical_valuation_config("dev")
        self.assertEqual(cfg["env"], "dev")
        self.assertTrue(cfg["host"])
        self.assertEqual(cfg["path"], "/openapi/agents/chat/completions/v1")
        self.assertTrue(cfg["token"])
        self.assertEqual(cfg["agent_id"], "test-agent")
        self.assertIn("timeout_seconds", cfg)
        self.assertTrue(cfg["debug"])
        self.assertNotIn("user_chat_input", cfg)


class QueryComparableValuationMockTests(unittest.TestCase):
    def test_mcp_tool_returns_choice_and_state(self) -> None:
        payload = json.loads(MOCK_LOWCODE.read_text(encoding="utf-8"))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload, ensure_ascii=False)

        with patch("data_mcp.features.historical_valuation.service.http_request", return_value=mock_response) as post:
            from data_mcp.mcp.server import query_comparable_valuation

            result = query_comparable_valuation(
                tags=["科技金融", "普惠金融"],
                company_name="星河智贷科技",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tool"], "query_comparable_valuation")
        content = result["data"]["content"]
        self.assertIn("可比项目", content)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["agentId"], "test-agent")
        self.assertEqual(body["userChatInput"], "")
        self.assertEqual(body["state"]["company_name"], "星河智贷科技")
        self.assertEqual(body["state"]["tags"], "[科技金融，普惠金融]")
        self.assertIn("token", post.call_args.kwargs["headers"])
        self.assertTrue(
            post.call_args.args[1].endswith("/openapi/agents/chat/completions/v1")
        )

    def test_normalize_tags_list_and_string(self) -> None:
        from data_mcp.features.historical_valuation.service import normalize_tags

        self.assertEqual(normalize_tags(["A", "B"]), "[A，B]")
        self.assertEqual(normalize_tags("[地产]"), "[地产]")

    def test_tags_required_company_name_optional(self) -> None:
        payload = json.loads(MOCK_LOWCODE.read_text(encoding="utf-8"))
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload, ensure_ascii=False)

        with patch(
            "data_mcp.features.historical_valuation.service.http_request",
            return_value=mock_response,
        ) as post:
            from data_mcp.mcp.server import query_comparable_valuation

            result = query_comparable_valuation(tags=["科技金融"])

        self.assertEqual(result["status"], "success")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["state"]["tags"], "[科技金融]")
        self.assertEqual(body["state"]["company_name"], "")

        from data_mcp.mcp.schemas import validate_tool_input

        with self.assertRaises(ValueError):
            validate_tool_input("query_comparable_valuation", {"company_name": "仅公司名"})

    def test_no_result_text_maps_to_empty_status(self) -> None:
        from data_mcp.mcp.responses import adapt_comparable_valuation

        result = adapt_comparable_valuation(
            {"choice": [{"content": "在过去北交所项目中，未找到可比历史估值"}]}
        )
        self.assertEqual(result["status"], "empty")
        self.assertIn("未获得", result["summary"])


class MatchListedPeersMockTests(unittest.TestCase):
    def test_loads_mock_corpus(self) -> None:
        from data_mcp.features.listed_peer_match.corpus import load_listed_corpus

        companies = load_listed_corpus(MOCK_XLSX)
        self.assertEqual(len(companies), 3)
        names = {c.security_name for c in companies}
        self.assertEqual(names, {"平安银行", "宁德时代", "中芯国际"})

    def test_mcp_tool_returns_ranked_peers(self) -> None:
        with patch(
            "data_mcp.features.listed_peer_match.service.load_listed_peer_match_config",
            side_effect=lambda _env=None: _mock_peer_config(),
        ):
            from data_mcp.mcp.server import match_listed_peers

            result = match_listed_peers(
                tags=["动力电池", "储能"],
                summary="新能源中游电芯制造与储能系统",
                top_n=3,
            )

        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertEqual(data["query"]["tags"], ["动力电池", "储能"])
        weights = data["weights_used"]
        self.assertAlmostEqual(
            weights["industry_chain_position"] + weights["products_services"],
            0.75,
        )
        self.assertEqual(data["meta"]["corpus_size"], 3)
        self.assertEqual(data["meta"]["embedding_backend"], "hash")
        self.assertNotIn("data_dir", data["meta"])
        self.assertNotIn("source_files", data["meta"])
        self.assertEqual(len(data["peers"]), 3)

        names = {p["证券名称"] for p in data["peers"]}
        self.assertEqual(names, {"平安银行", "宁德时代", "中芯国际"})
        self.assertEqual(data["meta"]["matching_version"], "retrieval_v2")
        self.assertEqual(data["meta"]["score_kind"], "reciprocal_rank_fusion")
        for peer in data["peers"]:
            self.assertIn("field_scores", peer)
            self.assertIn("evidence", peer)
            self.assertIn("citations", peer)
            self.assertEqual(peer["citations"][0]["source_type"], "listed_peer_corpus")
            self.assertEqual(peer["citations"][0]["source_name"], "companies.xlsx")
            self.assertEqual(peer["citations"][0]["source_url"], "")
            self.assertTrue(peer["citations"][0]["quote"])
            self.assertIn("PE", peer)
            self.assertNotIn("valuation", peer)
            self.assertNotIn("security_code", peer)
            self.assertEqual(peer["match_category"], "clue")
            self.assertEqual(peer["assessment_status"], "not_assessed")
            self.assertGreaterEqual(peer["final_score"], 0.0)
            self.assertIn(peer["confidence"], {"high", "medium", "low"})

        # 应已按 final_score 降序
        scores = [p["final_score"] for p in data["peers"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rejects_invalid_override_weights(self) -> None:
        bad_weights = {
            "industry_chain_position": 0.2,
            "products_services": 0.2,
            "track_tags": 0.4,
            "target_customers": 0.1,
            "profit_model": 0.1,
        }
        with patch(
            "data_mcp.features.listed_peer_match.service.load_listed_peer_match_config",
            side_effect=lambda _env=None: _mock_peer_config(),
        ):
            from data_mcp.mcp.server import match_listed_peers
            result = match_listed_peers(tags=["半导体"], field_weights=bad_weights)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})
        self.assertIn("0.75", result["summary"])

    def test_missing_corpus_dir_returns_actionable_mcp_error(self) -> None:
        with patch(
            "data_mcp.features.listed_peer_match.service.load_listed_peer_match_config",
            side_effect=lambda _env=None: _mock_peer_config(
                data_dir="tests/fixtures/data/listed_peers/no_such_dir"
            ),
        ):
            from data_mcp.mcp.server import match_listed_peers
            result = match_listed_peers(tags=["半导体"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["data"], {})
        self.assertIn("上市公司画像目录不存在", result["summary"])


class McpServerRegistryTests(unittest.TestCase):
    def test_all_tools_registered(self) -> None:
        from data_mcp.mcp.server import mcp

        tool_names: set[str] = set()
        manager = getattr(mcp, "_tool_manager", None)
        if manager is not None:
            tools = getattr(manager, "_tools", {})
            if isinstance(tools, dict):
                tool_names = set(tools.keys())

        if not tool_names:
            # 兼容不同 MCPServer 实现
            for attr in ("_tools", "tools"):
                maybe = getattr(mcp, attr, None)
                if isinstance(maybe, dict):
                    tool_names = set(maybe.keys())
                    break

        self.assertTrue(
            tool_names,
            "无法从 MCPServer 读取已注册工具列表，请检查 mcp 包版本",
        )
        self.assertIn("query_comparable_valuation", tool_names)
        self.assertIn("extract_project_profile", tool_names)
        self.assertIn("match_listed_peers", tool_names)
        self.assertIn("match_investors", tool_names)
        self.assertIn("query_track_labels", tool_names)
        self.assertIn("query_company_registry", tool_names)
        self.assertIn("search_company_web", tool_names)
        self.assertIn("query_cbex_listing_financials", tool_names)


if __name__ == "__main__":
    unittest.main()
