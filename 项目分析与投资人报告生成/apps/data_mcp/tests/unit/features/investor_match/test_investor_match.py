"""match_investors 编排与 adapter mock 测试。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import tests.support  # noqa: F401
from tests.support import RESPONSE_FIXTURES

FIXTURES = RESPONSE_FIXTURES


def _base_config(**overrides):
    from data_mcp.shared.settings import load_investor_match_config

    cfg = load_investor_match_config("dev")
    cfg = dict(cfg)
    cfg["internal_top_n"] = 100
    cfg["network_top_n"] = 10
    cfg.update(overrides)
    return cfg


def _dmp_result(
    institutions: list[dict] | None = None,
    *,
    individual_count: int = 0,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "institutions": list(institutions or []),
        "individual_count": individual_count,
        "warnings": list(warnings or []),
    }


class MatchInvestorsServiceTests(unittest.TestCase):
    def test_requires_core_inputs(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        with self.assertRaises(ValueError):
            match_investors("", ["a"], "profile")
        with self.assertRaises(ValueError):
            match_investors("co", [], "profile")
        with self.assertRaises(ValueError):
            match_investors("co", ["a"], "")

    def test_dmp_preferred_uses_individual_count_and_network(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        dmp_calls: list[tuple] = []
        db_calls: list[tuple] = []

        def fetch_dmp(*args, **kwargs):
            dmp_calls.append((args, kwargs))
            return _dmp_result(
                [
                    {
                        "name": "独立基金A",
                        "score": 0.9,
                        "match_reason": "DMP",
                        "usr_cgy_cd_dsc": "机构",
                        "raw": {},
                    },
                    {
                        "name": "红杉资本中国有限公司",
                        "score": 0.8,
                        "match_reason": "DMP",
                        "usr_cgy_cd_dsc": "机构",
                        "raw": {},
                    },
                ],
                individual_count=42,
            )

        def fetch_db(*args, **kwargs):
            db_calls.append((args, kwargs))
            return []

        def fetch_shareholders(company, env=None):
            return ["红杉资本中国"]

        def fetch_network(profile, tags, env=None):
            return [
                {"name": "红杉资本中国", "match_reason": "网络", "raw": {}},
                {"name": "高瓴资本", "match_reason": "网络", "raw": {}},
            ]

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile={"所在行业": "金融科技"},
            env="dev",
            fetch_dmp=fetch_dmp,
            fetch_db=fetch_db,
            fetch_shareholders=fetch_shareholders,
            fetch_network=fetch_network,
            config=_base_config(),
        )

        self.assertEqual(len(dmp_calls), 1)
        self.assertEqual(dmp_calls[0][0][0], ["科技金融"])
        self.assertEqual(db_calls, [])
        self.assertEqual(result["meta"]["internal_source"], "dmp")
        self.assertEqual(result["meta"]["label_type"], "股权转让/增资")
        names = [i["name"] for i in result["internal"]["institutions"]]
        self.assertEqual(names, ["独立基金A"])
        self.assertEqual(result["internal"]["individual_count"], 42)
        self.assertEqual(result["internal"]["institution_count"], 1)
        net_names = [i["name"] for i in result["network"]["institutions"]]
        self.assertEqual(net_names, ["高瓴资本"])
        self.assertTrue(result["meta"]["shareholders_filtered"])
        self.assertEqual(result["warnings"], [])

        internal = next(c for c in result["merged"] if c["name"] == "独立基金A")
        self.assertEqual(internal["citations"][0]["source_type"], "dmp")
        self.assertEqual(internal["citations"][0]["source_name"], "DMP 标签库")

        network = next(c for c in result["merged"] if c["name"] == "高瓴资本")
        self.assertEqual(network["citations"][0]["source_type"], "network")
        self.assertEqual(network["citations"][0]["source_name"], "公开网络信息")
        self.assertIn("网络", network["citations"][0]["quote"])

    def test_dmp_failure_falls_back_to_db(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        def fetch_dmp(*args, **kwargs):
            raise RuntimeError("DMP down")

        def fetch_db(tags, env=None, weight_ratio=None):
            return [
                {
                    "name": "兜底基金",
                    "score": 1.0,
                    "match_reason": "db",
                    "usr_cgy_cd_dsc": "机构",
                    "raw": {},
                },
                {
                    "name": "个人投资者乙",
                    "score": 0.5,
                    "match_reason": "库内",
                    "usr_cgy_cd_dsc": "个人",
                    "raw": {},
                },
            ]

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像文本",
            env="dev",
            fetch_dmp=fetch_dmp,
            fetch_db=fetch_db,
            fetch_shareholders=lambda *a, **k: [],
            fetch_network=lambda *a, **k: [],
            config=_base_config(),
        )
        self.assertEqual(result["meta"]["internal_source"], "db_fallback")
        self.assertTrue(any("DMP" in w for w in result["warnings"]))
        self.assertEqual(result["internal"]["institutions"][0]["name"], "兜底基金")
        self.assertEqual(result["internal"]["individual_count"], 1)
        self.assertEqual(result["merged"][0]["citations"][0]["source_name"], "内部投资人库")

    def test_dmp_candidates_use_dmp_citation_name(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        db_calls: list[tuple] = []

        def fetch_db(*args, **kwargs):
            db_calls.append((args, kwargs))
            return []

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像文本",
            env="dev",
            fetch_dmp=lambda *a, **k: _dmp_result(
                [
                    {
                        "name": "DMP基金",
                        "score": 1.0,
                        "match_reason": "DMP 匹配标签: 科技金融; 权重和 1.0",
                        "usr_cgy_cd_dsc": "机构",
                        "raw": {},
                    }
                ],
                individual_count=3,
            ),
            fetch_db=fetch_db,
            fetch_shareholders=lambda *a, **k: [],
            fetch_network=lambda *a, **k: [],
            config=_base_config(),
        )
        self.assertEqual(db_calls, [])
        self.assertEqual(result["meta"]["internal_source"], "dmp")
        self.assertEqual(result["internal"]["individual_count"], 3)
        cite = result["merged"][0]["citations"][0]
        self.assertEqual(cite["source_type"], "dmp")
        self.assertEqual(cite["source_name"], "DMP 标签库")
        self.assertIn("科技金融", cite["quote"])

    def test_network_candidate_keeps_page_title_and_url(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像",
            fetch_db=lambda *a, **k: [],
            fetch_dmp=lambda *a, **k: _dmp_result(),
            fetch_shareholders=lambda *a, **k: [],
            fetch_network=lambda *a, **k: [
                {
                    "name": "高瓴资本",
                    "match_reason": "关注科技金融",
                    "source_name": "某财经报道",
                    "source_url": "https://example.com/news",
                    "raw": {"phone": "不应进入批注"},
                }
            ],
            config=_base_config(),
        )
        cite = result["merged"][0]["citations"][0]
        self.assertEqual(cite["source_type"], "network")
        self.assertEqual(cite["source_name"], "某财经报道")
        self.assertEqual(cite["source_url"], "https://example.com/news")
        self.assertEqual(cite["quote"], "关注科技金融")
        self.assertNotIn("phone", cite)
        self.assertNotIn("不应进入批注", cite["quote"])

    def test_qichacha_failure_still_returns(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像",
            fetch_dmp=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dmp down")),
            fetch_db=lambda *a, **k: [
                {
                    "name": "基金X",
                    "score": 1,
                    "match_reason": "db",
                    "usr_cgy_cd_dsc": "机构",
                    "raw": {},
                }
            ],
            fetch_shareholders=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("qcc fail")),
            fetch_network=lambda *a, **k: [],
            config=_base_config(),
        )
        self.assertFalse(result["meta"]["shareholders_filtered"])
        self.assertEqual(result["internal"]["institution_count"], 1)
        self.assertTrue(any("企查查" in w for w in result["warnings"]))

    def test_network_top_n_and_internal_top_n(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        dmp_rows = [
            {
                "name": f"机构{i}",
                "score": 100 - i,
                "match_reason": "dmp",
                "usr_cgy_cd_dsc": "机构",
                "raw": {},
            }
            for i in range(5)
        ]
        net_rows = [{"name": f"网{i}", "match_reason": "n", "raw": {}} for i in range(5)]

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像",
            fetch_db=lambda *a, **k: [],
            fetch_dmp=lambda *a, **k: _dmp_result(dmp_rows, individual_count=9),
            fetch_shareholders=lambda *a, **k: [],
            fetch_network=lambda *a, **k: net_rows,
            config=_base_config(internal_top_n=2, network_top_n=3),
        )
        self.assertEqual(result["internal"]["institution_count"], 2)
        self.assertEqual(result["internal"]["individual_count"], 9)
        self.assertEqual(result["network"]["institution_count"], 3)

    def test_agent_candidates_do_not_expose_raw_source_rows(self) -> None:
        from data_mcp.features.investor_match.service import match_investors

        result = match_investors(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像",
            fetch_db=lambda *a, **k: [],
            fetch_dmp=lambda *a, **k: _dmp_result(
                [
                    {
                        "name": "示例资本",
                        "score": 1,
                        "match_reason": "dmp",
                        "usr_cgy_cd_dsc": "机构",
                        "raw": {"phone": "不应进入 Agent 上下文"},
                    }
                ]
            ),
            fetch_shareholders=lambda *a, **k: [],
            fetch_network=lambda *a, **k: [],
            config=_base_config(),
        )

        self.assertNotIn("raw", result["internal"]["institutions"][0])
        self.assertNotIn("raw", result["merged"][0])
        self.assertEqual(
            set(result["merged"][0]["citations"][0]),
            {"source_type", "source_name", "source_url", "quote"},
        )


class NetworkInvestorAdapterTests(unittest.TestCase):
    def test_parse_content_list(self) -> None:
        from data_mcp.features.investor_match.network_client import parse_network_investor_content

        items = parse_network_investor_content(
            '```json\n[{"name":"甲基金"},{"investor_name":"乙资本"}]\n```'
        )
        self.assertEqual([i["name"] for i in items], ["甲基金", "乙资本"])
        self.assertEqual(items[0]["source_url"], "")
        self.assertEqual(items[0]["source_name"], "")

    def test_parse_content_extracts_title_and_url(self) -> None:
        from data_mcp.features.investor_match.network_client import parse_network_investor_content

        items = parse_network_investor_content(
            json.dumps(
                [
                    {
                        "name": "甲基金",
                        "reason": "关注新能源",
                        "url": "https://example.com/a",
                        "title": "财经网",
                    }
                ],
                ensure_ascii=False,
            )
        )
        self.assertEqual(items[0]["name"], "甲基金")
        self.assertEqual(items[0]["match_reason"], "关注新能源")
        self.assertEqual(items[0]["source_url"], "https://example.com/a")
        self.assertEqual(items[0]["source_name"], "财经网")

    def test_invoke_builds_expected_payload(self) -> None:
        payload = json.loads(
            (FIXTURES / "network_investors.json").read_text(encoding="utf-8")
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload, ensure_ascii=False)

        with patch("data_mcp.features.investor_match.network_client.http_request", return_value=mock_response) as post:
            from data_mcp.features.investor_match.network_client import (
                invoke_network_investor_agent,
            )

            items = invoke_network_investor_agent(
                project_profile={"所在行业": "金融科技"},
                track_tags=["科技金融", "普惠金融"],
                env="dev",
            )

        self.assertGreaterEqual(len(items), 2)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["userChatInput"], "")
        self.assertEqual(body["agentId"], "test-agent")
        self.assertIn("project_profile", body["state"])
        self.assertEqual(body["state"]["track_tags"], "[科技金融，普惠金融]")


class InvestorRepositoryMappingTests(unittest.TestCase):
    def test_prefers_organization_name_over_internal_user_id(self) -> None:
        from data_mcp.features.investor_match.repository import query_touziren_investors

        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchall.side_effect = [
            [{"usr_id": 123, "lbl_nm": "金融信息服务", "lbl_wgt": 3, "pref_wgt": 3, "smy_wgt": 3}],
            [{"usr_id": 123, "org_nm": "示例资本有限公司", "cust_nm": "张三", "usr_cgy_cd_dsc": "机构"}],
        ]
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with patch(
            "data_mcp.features.investor_match.repository.load_investor_match_config",
            return_value={
                "database": {"host": "db", "database": "test"},
                "weight_ratio": {"lbl_wgt": 1, "pref_wgt": 1, "smy_wgt": 1},
            },
        ):
            result = query_touziren_investors(
                ["金融信息服务"],
                connect=lambda _cfg: connection,
            )

        self.assertEqual(result[0]["name"], "示例资本有限公司")


class QichachaAdapterTests(unittest.TestCase):
    def test_extract_partners(self) -> None:
        from data_mcp.shared.integrations.qichacha_client import _extract_shareholder_names

        data = json.loads((FIXTURES / "qichacha_shareholders.json").read_text(encoding="utf-8"))
        names = _extract_shareholder_names(data)
        self.assertIn("红杉资本中国有限公司", names)
        self.assertIn("张三", names)

    def test_token_header(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = json.loads(
            (FIXTURES / "qichacha_shareholders.json").read_text(encoding="utf-8")
        )
        mock_response.text = "{}"

        cfg = _base_config()
        cfg["qichacha"] = {
            "key": "k1",
            "secret_key": "s1",
            "base_url": "https://api.qichacha.com",
            "path": "/ECIInfoVerify/GetInfo",
            "timeout_seconds": 30,
        }

        with patch("data_mcp.shared.integrations.qichacha_client.load_investor_match_config", return_value=cfg):
            with patch("data_mcp.shared.integrations.qichacha_client.http_request", return_value=mock_response) as get:
                from data_mcp.shared.integrations.qichacha_client import fetch_shareholders

                names = fetch_shareholders("星河智贷", env="dev")

        self.assertTrue(names)
        headers = get.call_args.kwargs["headers"]
        self.assertIn("Token", headers)
        self.assertIn("Timespan", headers)


class ConfigTests(unittest.TestCase):
    def test_investor_match_and_network_config(self) -> None:
        from data_mcp.shared.settings import (
            load_investor_match_config,
            load_investor_network_config,
        )

        im = load_investor_match_config("dev")
        self.assertEqual(im["internal_top_n"], 10)
        self.assertIn("dmp", im)
        self.assertIn("database", im)
        self.assertIn("qichacha", im)

        ni = load_investor_network_config("dev")
        self.assertEqual(ni["agent_id"], "test-agent")
        self.assertEqual(ni["path"], "/openapi/agents/chat/completions/v1")


class McpToolTests(unittest.TestCase):
    def test_mcp_match_investors_wired(self) -> None:
        from data_mcp.mcp.server import match_investors as tool

        valid_result = {
            "internal": {
                "institutions": [],
                "institution_count": 0,
                "individual_count": 0,
                "total_after_filter": 0,
            },
            "network": {
                "institutions": [],
                "institution_count": 0,
            },
            "merged": [],
            "warnings": [],
            "meta": {"env": "dev"},
        }
        with patch(
            "data_mcp.mcp.server.call_match_investors",
            return_value=valid_result,
        ) as mocked:
            out = tool(
                company_name="星河智贷",
                track_tags=["科技金融"],
                project_profile="画像",
                label_type="",
            )
        self.assertEqual(out["status"], "empty")
        self.assertEqual(out["data"]["candidates"], [])
        mocked.assert_called_once_with(
            company_name="星河智贷",
            track_tags=["科技金融"],
            project_profile="画像",
            label_type="",
            env=None,
        )

    def test_mcp_match_investors_keeps_candidate_citations(self) -> None:
        from data_mcp.mcp.server import match_investors as tool

        valid_result = {
            "internal": {
                "institutions": [],
                "institution_count": 1,
                "individual_count": 0,
                "total_after_filter": 1,
            },
            "network": {"institutions": [], "institution_count": 0},
            "merged": [
                {
                    "name": "示例资本",
                    "investor_type": "机构",
                    "source": "internal",
                    "score": 1.0,
                    "match_reason": "库内标签匹配: 科技金融; 权重分 1.0000",
                    "citations": [
                        {
                            "source_type": "investor_db",
                            "source_name": "内部投资人库",
                            "source_url": "",
                            "quote": "库内标签匹配: 科技金融; 权重分 1.0000",
                        }
                    ],
                }
            ],
            "warnings": [],
            "meta": {"env": "dev", "internal_source": "db_fallback", "shareholders_filtered": True},
        }
        with patch("data_mcp.mcp.server.call_match_investors", return_value=valid_result):
            out = tool(
                company_name="星河智贷",
                track_tags=["科技金融"],
                project_profile="画像",
            )
        self.assertEqual(out["status"], "success")
        cite = out["data"]["candidates"][0]["citations"][0]
        self.assertEqual(cite["source_name"], "内部投资人库")
        self.assertIn("科技金融", cite["quote"])


class JoinLabelNamesTests(unittest.TestCase):
    def test_join_strips_wrapping_quotes(self) -> None:
        from data_mcp.features.investor_match.dmp_client import _join_label_names

        self.assertEqual(
            _join_label_names(['"住宿业"', '"餐饮业"', "物业管理"]),
            "住宿业,餐饮业,物业管理",
        )
        self.assertEqual(
            _join_label_names(["集成电路制造", "高可靠功率半导体"]),
            "集成电路制造,高可靠功率半导体",
        )


class DmpClientTests(unittest.TestCase):
    def test_query_dmp_calls_institution_and_individual(self) -> None:
        from data_mcp.features.investor_match import dmp_client

        bodies: list[dict] = []
        seen_headers: list[dict] = []

        class _Resp:
            status_code = 200

            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def json(self) -> dict:
                return self._payload

        def fake_http(method, url, **kwargs):
            body = kwargs.get("json") or kwargs.get("params") or {}
            bodies.append(dict(body))
            seen_headers.append(dict(kwargs.get("headers") or {}))
            if body.get("investor_type") == "机构":
                items = [
                    {
                        "investor_name": f"资本{index}",
                        "match_label_num": index,
                        "match_label_weight_sum": float(index),
                        "label_name_list": "不应进入结果的长文本",
                        "extra_payload": "x" * 50,
                    }
                    for index in range(1, 36)
                ]
                items[0] = {
                    "investor_name": "甲资本",
                    "match_label_num": 3,
                    "match_label_weight_sum": 12.5,
                    "label_name_list": "金融",
                }
                return _Resp({"count": 35, "items": items, "totalResults": None})
            return _Resp({"count": 7, "items": [{"investor_name": "某人"}], "totalResults": 88})

        cfg = {
            "base_url": "https://dmp.example",
            "path": "/v3/API_DMP_DMP_APEX_InquiryInvestorProfileMatchingSrv",
            "method": "POST",
            "x_gw_token": "tok",
            "app_key": "d7463684-4c6a-4f1e-809a-298d23e28097",
            "app_secret": "app-secret",
            "timeout_seconds": 5,
            "institution_offset": 0,
            "institution_limit": 30,
            "individual_offset": 5,
            "individual_limit": 1,
        }
        with (
            patch.object(
                dmp_client,
                "load_investor_match_config",
                return_value={"dmp": cfg},
            ),
            patch.object(
                dmp_client,
                "load_http_retry_config",
                return_value={
                    "max_retries": 0,
                    "backoff_base_seconds": 0,
                    "backoff_max_seconds": 0,
                },
            ),
            patch.object(dmp_client, "build_jgfw_gateway_headers", return_value={}),
            patch.object(dmp_client, "build_dmp_auth_headers", return_value={
                "appKey": "d7463684-4c6a-4f1e-809a-298d23e28097",
                "nonce": "abcDEF1234",
                "timestamp": "1700000000000",
                "signature": "signed",
            }),
            patch.object(dmp_client, "http_request", side_effect=fake_http),
        ):
            result = dmp_client.query_dmp_investors(["金融", "机械设备"], env="dev")

        self.assertEqual(len(bodies), 2)
        by_type = {body["investor_type"]: body for body in bodies}
        institution_body = by_type["机构"]
        individual_body = by_type["个人"]
        self.assertEqual(institution_body["label_type"], "股权转让/增资")
        self.assertEqual(institution_body["label_name"], "金融,机械设备")
        self.assertEqual(institution_body["offset"], 0)
        self.assertEqual(institution_body["limit"], 30)
        self.assertEqual(individual_body["offset"], 5)
        self.assertEqual(individual_body["limit"], 1)
        self.assertEqual(len(result["institutions"]), 30)
        top = result["institutions"][0]
        self.assertEqual(top["name"], "资本35")
        self.assertNotIn("raw", top)
        self.assertNotIn("extra_payload", top)
        self.assertIn("匹配标签数 35", top["match_reason"])
        self.assertEqual(result["individual_count"], 7)
        self.assertEqual(result["warnings"], [])
        auth_header = next(
            header for header in seen_headers if header.get("appKey")
        )
        self.assertEqual(auth_header["appKey"], "d7463684-4c6a-4f1e-809a-298d23e28097")
        self.assertEqual(auth_header["nonce"], "abcDEF1234")
        self.assertEqual(auth_header["timestamp"], "1700000000000")
        self.assertEqual(auth_header["signature"], "signed")

    def test_signature_matches_sha1_concat(self) -> None:
        from data_mcp.features.investor_match.dmp_client import (
            build_dmp_auth_headers,
            dmp_signature,
        )

        signature = dmp_signature("app-key", "app-secret", "1700000000000", "abcDEF1234")
        self.assertEqual(signature, "0d1e0080a634e0ee919c4f568c0f16ce643cf0a1")
        headers = build_dmp_auth_headers(
            {"app_key": "app-key", "app_secret": "app-secret"},
            nonce="abcDEF1234",
            timestamp_ms=1700000000000,
        )
        self.assertEqual(headers["signature"], signature)
        self.assertEqual(len(headers["nonce"]), 10)


class NormalizeTagsTests(unittest.TestCase):
    def test_strips_wrapping_quotes_from_string_and_list(self) -> None:
        from data_mcp.features.investor_match.service import _normalize_tags

        self.assertEqual(
            _normalize_tags('"住宿业","餐饮业","物业管理"'),
            ["住宿业", "餐饮业", "物业管理"],
        )
        self.assertEqual(
            _normalize_tags(['"集成电路制造"', '"特种电子"']),
            ["集成电路制造", "特种电子"],
        )
        self.assertEqual(
            _normalize_tags("集成电路制造,高可靠功率半导体"),
            ["集成电路制造", "高可靠功率半导体"],
        )


if __name__ == "__main__":
    unittest.main()
