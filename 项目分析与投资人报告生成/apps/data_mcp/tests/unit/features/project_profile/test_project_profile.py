"""Project profile feature tests."""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import tests.support  # noqa: F401
from tests.support import RESPONSE_FIXTURES

FIXTURES = RESPONSE_FIXTURES
PROFILE_KEYS = [
    "上市公司名称",
    "证券简称",
    "证券代码",
    "所在行业",
    "细分赛道",
    "自身在产业链上下游位置",
    "目标客户",
    "主要产品和服务",
    "盈利模式",
    "核心资源与能力",
    "资源依赖路径",
]


@contextmanager
def _patch_external_sources(
    *,
    qichacha_info: str = '{"Name":"星河智贷科技有限公司"}',
    qichacha_warnings: list[str] | None = None,
    zhipu_info: str = '{"company_name":"星河智贷科技有限公司","searches":[]}',
    zhipu_warnings: list[str] | None = None,
):
    with patch(
        "data_mcp.features.project_profile.service.resolve_qichacha_info_for_portrait",
        return_value=(qichacha_info, qichacha_warnings or []),
    ):
        with patch(
            "data_mcp.features.project_profile.service.resolve_zhipu_info_for_portrait",
            return_value=(zhipu_info, zhipu_warnings or []),
        ):
            yield


class LoadProjectProfileConfigTests(unittest.TestCase):
    def test_dev_config_has_required_fields(self) -> None:
        from data_mcp.shared.settings import load_project_profile_config

        cfg = load_project_profile_config("dev")
        self.assertEqual(cfg["env"], "dev")
        self.assertTrue(cfg["host"])
        self.assertEqual(cfg["path"], "/openapi/agents/chat/completions/v1")
        self.assertTrue(cfg["token"])
        self.assertEqual(cfg["agent_id"], "test-agent")
        self.assertIn("timeout_seconds", cfg)
        self.assertTrue(cfg["debug"])

    def test_qichacha_config_loaded(self) -> None:
        from data_mcp.shared.settings import load_project_profile_qichacha_config

        cfg = load_project_profile_qichacha_config("dev")
        self.assertEqual(cfg["key"], "test-qichacha-key")
        self.assertEqual(cfg["secret_key"], "test-qichacha-secret")
        self.assertIn("ECIInfoVerify", cfg["path"])

    def test_zhipu_config_loaded(self) -> None:
        from data_mcp.shared.settings import load_project_profile_zhipu_config

        cfg = load_project_profile_zhipu_config("dev")
        self.assertEqual(cfg["api_key"], "test-api-key")
        self.assertEqual(cfg["search_engine"], "search_pro")
        self.assertIn("{company_name}", cfg["query_templates"][0])


class ProfileCleaningTests(unittest.TestCase):
    def test_parse_plain_json_content(self) -> None:
        from data_mcp.features.project_profile.service import parse_profile_content

        content = json.dumps(
            {
                "上市公司名称": "示例股份有限公司",
                "证券简称": "示例",
                "证券代码": "123456",
                "所在行业": "制造业",
                "细分赛道": "精密部件",
                "自身在产业链上下游位置": "中游",
                "目标客户": "整车厂",
                "主要产品和服务": "精密结构件",
                "盈利模式": "产品销售",
                "核心资源与能力": "工艺与产能",
                "资源依赖路径": "原材料供应",
            },
            ensure_ascii=False,
        )
        result = parse_profile_content(content)
        self.assertIsNotNone(result["profile"])
        self.assertEqual(result["profile"]["上市公司名称"], "示例股份有限公司")
        self.assertIn("field_details", result)
        self.assertEqual(result["conflicts"], [])
        for key in PROFILE_KEYS:
            self.assertIn(key, result["profile"])
            self.assertIsInstance(result["profile"][key], str)
            self.assertIn(key, result["field_details"])

    def test_parse_nested_profile_with_field_details(self) -> None:
        from data_mcp.features.project_profile.service import parse_profile_content

        content = json.dumps(
            {
                "profile": {"上市公司名称": "甲公司", "证券简称": "", "证券代码": ""},
                "field_details": {
                    "上市公司名称": {
                        "status": "supported",
                        "confidence": 0.95,
                        "inference_basis": "",
                        "evidence": [
                            {
                                "source_type": "zhipu",
                                "source_name": "新闻标题",
                                "source_url": "https://example.com/a",
                                "quote": "甲公司主营数字化平台",
                            }
                        ],
                    }
                },
                "conflicts": [],
                "warnings": ["材料页码缺失"],
            },
            ensure_ascii=False,
        )
        result = parse_profile_content(content)
        self.assertEqual(result["profile"]["上市公司名称"], "甲公司")
        detail = result["field_details"]["上市公司名称"]
        self.assertEqual(detail["status"], "supported")
        self.assertEqual(detail["confidence"], 0.95)
        self.assertEqual(len(detail["evidence"]), 1)
        self.assertEqual(result["agent_warnings"], ["材料页码缺失"])

    def test_parse_markdown_fenced_json(self) -> None:
        from data_mcp.features.project_profile.service import parse_profile_content

        inner = (
            '{"上市公司名称":"甲","证券简称":"","证券代码":"","所在行业":"",'
            '"细分赛道":"","自身在产业链上下游位置":"","目标客户":"",'
            '"主要产品和服务":"","盈利模式":"","核心资源与能力":"","资源依赖路径":""}'
        )
        content = f"```json\n{inner}\n```"
        result = parse_profile_content(content)
        self.assertEqual(result["profile"]["上市公司名称"], "甲")

    def test_parse_invalid_content_returns_error_shape(self) -> None:
        from data_mcp.features.project_profile.service import parse_profile_content

        result = parse_profile_content("not-json-at-all")
        self.assertIsNone(result["profile"])
        self.assertIn("error", result)
        self.assertEqual(result["raw_content"], "not-json-at-all")

    def test_missing_fields_filled_with_empty_string(self) -> None:
        from data_mcp.features.project_profile.service import parse_profile_content

        result = parse_profile_content('{"上市公司名称":"仅名称"}')
        self.assertEqual(result["profile"]["上市公司名称"], "仅名称")
        self.assertEqual(result["profile"]["证券代码"], "")

    def test_extract_choice_content_from_list(self) -> None:
        from data_mcp.features.project_profile.service import extract_choice_content

        payload = {"choice": [{"content": '{"上市公司名称":"X"}'}]}
        self.assertEqual(extract_choice_content(payload), '{"上市公司名称":"X"}')


class QichachaSummarizeTests(unittest.TestCase):
    def test_summarize_keeps_face_drops_noise_and_caps_lists(self) -> None:
        from data_mcp.shared.integrations.qichacha_client import summarize_eci_for_portrait

        payload = json.loads(
            (FIXTURES / "qichacha_company.json").read_text(encoding="utf-8")
        )
        partners = list(payload["Result"]["Partners"])
        for i in range(12):
            partners.append(
                {"StockName": f"股东{i}", "StockPercent": "1%", "StockType": "自然人股东"}
            )
        payload["Result"]["Partners"] = partners

        summary = summarize_eci_for_portrait(payload)
        assert summary is not None
        self.assertEqual(summary["Name"], "星河智贷科技有限公司")
        self.assertIn("高新技术企业", summary["Tags"])
        self.assertNotIn("ChangeRecords", summary)
        self.assertNotIn("ContactInfo", summary)
        self.assertNotIn("ImageUrl", summary)
        self.assertEqual(len(summary["Partners"]), 10)
        self.assertEqual(summary["Industry"]["Industry"], "信息传输、软件和信息技术服务业")


class ZhipuSearchTests(unittest.TestCase):
    def test_build_search_queries_merges_templates_and_keywords(self) -> None:
        from data_mcp.features.project_profile.zhipu_client import build_search_queries

        queries = build_search_queries(
            "甲公司",
            ["甲公司 年报", "甲公司 年报"],
        )
        self.assertIn("甲公司 主营业务 产品", queries)
        self.assertIn("甲公司 年报", queries)
        self.assertEqual(len(queries), len(set(queries)))

    def test_summarize_search_response(self) -> None:
        from data_mcp.features.project_profile.zhipu_client import summarize_search_response

        payload = json.loads(
            (FIXTURES / "zhipu_search.json").read_text(encoding="utf-8")
        )
        summary = summarize_search_response("星河智贷科技有限公司 主营业务", payload)
        self.assertEqual(summary["query"], "星河智贷科技有限公司 主营业务")
        self.assertEqual(len(summary["results"]), 1)
        self.assertEqual(summary["results"][0]["title"], "星河智贷科技有限公司 主营业务介绍")
        self.assertEqual(summary["results"][0]["url"], "https://example.com/news/1")

    def test_summarize_keeps_only_top_two_results(self) -> None:
        from data_mcp.features.project_profile.zhipu_client import (
            MAX_RESULTS_PER_QUERY,
            summarize_search_response,
        )

        payload = {
            "search_result": [
                {
                    "title": f"标题{i}",
                    "link": f"https://example.com/{i}",
                    "content": f"摘要{i}",
                    "media": "示例",
                }
                for i in range(1, 6)
            ]
        }
        summary = summarize_search_response("甲公司 主营业务", payload)
        self.assertEqual(MAX_RESULTS_PER_QUERY, 2)
        self.assertEqual(len(summary["results"]), 2)
        self.assertEqual(summary["results"][0]["title"], "标题1")
        self.assertEqual(summary["results"][1]["title"], "标题2")


class ExtractProjectProfileMockTests(unittest.TestCase):
    def test_success_includes_qichacha_and_zhipu_in_state(self) -> None:
        portrait_payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        qcc_payload = json.loads(
            (FIXTURES / "qichacha_company.json").read_text(encoding="utf-8")
        )

        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = portrait_payload
        mock_post.text = json.dumps(portrait_payload, ensure_ascii=False)

        mock_get = MagicMock()
        mock_get.raise_for_status = MagicMock()
        mock_get.json.return_value = qcc_payload
        mock_get.text = json.dumps(qcc_payload, ensure_ascii=False)

        zhipu_info = json.dumps(
            {
                "company_name": "星河智贷科技有限公司",
                "searches": [
                    {
                        "query": "星河智贷科技有限公司 主营业务 产品",
                        "results": [
                            {
                                "title": "新闻",
                                "url": "https://example.com/a",
                                "summary": "数字化信贷平台",
                                "site_name": "示例",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_post) as post:
            with patch("data_mcp.shared.integrations.qichacha_client.http_request", return_value=mock_get):
                with _patch_external_sources(zhipu_info=zhipu_info):
                    from data_mcp.features.project_profile.service import extract_project_profile

                    result = extract_project_profile(
                        file_info="这是解析后的材料文本",
                        company_name="星河智贷科技有限公司",
                        user_chat_input="补充：聚焦科技金融",
                        env="dev",
                    )

        self.assertIsNotNone(result["profile"])
        self.assertEqual(result["profile"]["上市公司名称"], "星河智贷科技有限公司")
        self.assertIn("field_details", result)
        self.assertEqual(result.get("conflicts"), [])
        self.assertEqual(result.get("warnings"), [])
        self.assertEqual(result["qichacha_info"]["Name"], "星河智贷科技有限公司")
        self.assertEqual(result["zhipu_info"]["company_name"], "星河智贷科技有限公司")
        self.assertEqual(len(result["zhipu_info"]["searches"]), 1)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["agentId"], "test-agent")
        self.assertEqual(body["userChatInput"], "补充：聚焦科技金融")
        self.assertEqual(body["state"]["file_info"], "这是解析后的材料文本")
        self.assertEqual(
            set(body["state"].keys()),
            {"file_info", "qichacha_info", "zhipu_info"},
        )
        qinfo = json.loads(body["state"]["qichacha_info"])
        self.assertEqual(qinfo["Name"], "星河智贷科技有限公司")
        zinfo = json.loads(body["state"]["zhipu_info"])
        self.assertEqual(zinfo["company_name"], "星河智贷科技有限公司")

    def test_qichacha_failure_still_calls_agent_with_warning(self) -> None:
        portrait_payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = portrait_payload
        mock_post.text = json.dumps(portrait_payload, ensure_ascii=False)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_post) as post:
            with patch(
                "data_mcp.features.project_profile.service.resolve_qichacha_info_for_portrait",
                return_value=("", ["企查查调用失败: boom"]),
            ):
                with patch(
                    "data_mcp.features.project_profile.service.resolve_zhipu_info_for_portrait",
                    return_value=('{"company_name":"某某公司","searches":[]}', []),
                ):
                    from data_mcp.features.project_profile.service import extract_project_profile

                    result = extract_project_profile(
                        file_info="材料",
                        company_name="某某公司",
                        env="dev",
                    )

        self.assertIsNotNone(result["profile"])
        self.assertTrue(result["warnings"])
        self.assertIn("企查查", result["warnings"][0])
        self.assertIsNone(result["qichacha_info"])
        self.assertEqual(result["zhipu_info"]["company_name"], "某某公司")
        self.assertEqual(post.call_args.kwargs["json"]["state"]["qichacha_info"], "")

    def test_zhipu_failure_still_calls_agent_with_warning(self) -> None:
        portrait_payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = portrait_payload
        mock_post.text = json.dumps(portrait_payload, ensure_ascii=False)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_post):
            with _patch_external_sources(
                zhipu_info="",
                zhipu_warnings=["智谱搜索未返回可用结果: 全部查询无结果"],
            ):
                from data_mcp.features.project_profile.service import extract_project_profile

                result = extract_project_profile(
                    file_info="材料",
                    company_name="某某公司",
                    env="dev",
                )

        self.assertIsNotNone(result["profile"])
        self.assertTrue(any("智谱" in warning for warning in result["warnings"]))
        self.assertIsNone(result["zhipu_info"])
        self.assertEqual(result["qichacha_info"]["Name"], "星河智贷科技有限公司")

    def test_empty_file_info_raises(self) -> None:
        from data_mcp.features.project_profile.service import extract_project_profile

        with self.assertRaises(ValueError):
            extract_project_profile(file_info="  ", company_name="甲公司", env="dev")

    def test_empty_company_name_raises(self) -> None:
        from data_mcp.features.project_profile.service import extract_project_profile

        with self.assertRaises(ValueError):
            extract_project_profile(file_info="材料", company_name="  ", env="dev")

    def test_material_url_overrides_file_info_and_sets_source_name(self) -> None:
        portrait_payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.status_code = 200
        mock_post.json.return_value = portrait_payload
        mock_post.text = json.dumps(portrait_payload, ensure_ascii=False)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_post) as post:
            with _patch_external_sources():
                with patch(
                    "data_mcp.features.project_profile.material_loader.download_markdown_from_url",
                    return_value="# 从 MinIO 下载的 markdown 正文",
                ) as download:
                    from data_mcp.features.project_profile.service import extract_project_profile

                    result = extract_project_profile(
                        company_name="星河智贷科技有限公司",
                        file_info="旧文本应被忽略",
                        material_url="https://minio.example.com/bucket/report.md",
                        env="dev",
                    )

        self.assertIsNotNone(result["profile"])
        download.assert_called_once_with("https://minio.example.com/bucket/report.md")
        state = post.call_args.kwargs["json"]["state"]
        self.assertEqual(state["file_info"], "# 从 MinIO 下载的 markdown 正文")
        self.assertEqual(state["material_source_name"], "report.md")

    def test_search_keywords_forwarded_to_zhipu_resolver(self) -> None:
        portrait_payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        mock_post = MagicMock()
        mock_post.raise_for_status = MagicMock()
        mock_post.json.return_value = portrait_payload
        mock_post.text = json.dumps(portrait_payload, ensure_ascii=False)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_post):
            with _patch_external_sources():
                with patch(
                    "data_mcp.features.project_profile.service.resolve_zhipu_info_for_portrait",
                    return_value=('{"company_name":"甲公司","searches":[]}', []),
                ) as resolve_zhipu:
                    from data_mcp.features.project_profile.service import extract_project_profile

                    extract_project_profile(
                        file_info="材料",
                        company_name="甲公司",
                        search_keywords=["甲公司 年报"],
                        env="dev",
                    )

        resolve_zhipu.assert_called_once_with(
            "甲公司",
            "dev",
            search_keywords=["甲公司 年报"],
        )

    def test_invalid_choice_content_returns_error_shape(self) -> None:
        payload = {"choice": [{"content": "### not json"}]}
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_response):
            with _patch_external_sources():
                from data_mcp.features.project_profile.service import extract_project_profile

                result = extract_project_profile(
                    file_info="材料",
                    company_name="甲公司",
                    env="dev",
                )

        self.assertIsNone(result["profile"])
        self.assertIn("error", result)
        self.assertIn("raw_content", result)
        self.assertIn("qichacha_info", result)
        self.assertIn("zhipu_info", result)


class McpExtractProjectProfileTests(unittest.TestCase):
    def test_mcp_tool_delegates(self) -> None:
        payload = json.loads(
            (FIXTURES / "project_profile.json").read_text(encoding="utf-8")
        )
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload
        mock_response.text = json.dumps(payload, ensure_ascii=False)

        with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_response):
            with _patch_external_sources():
                from data_mcp.mcp.server import extract_project_profile

                result = extract_project_profile(
                    file_info="材料",
                    company_name="星河智贷科技有限公司",
                    user_chat_input="",
                )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["profile"]["上市公司名称"], "星河智贷科技有限公司")
        self.assertIn("field_details", result["data"])
        self.assertNotIn("qichacha_info", result["data"])
        self.assertNotIn("zhipu_info", result["data"])


if __name__ == "__main__":
    unittest.main()
