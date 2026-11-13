"""query_track_labels 编排与解析测试。"""

from __future__ import annotations

import unittest

import tests.support  # noqa: F401


def _cfg(**overrides):
    from data_mcp.shared.settings import load_track_labels_config

    cfg = dict(load_track_labels_config("dev"))
    cfg["retry"] = {"max_attempts": 2, "interval_seconds": 20}
    cfg["fallback"] = {
        "taxonomy_path": "../../resources/reference_data/data_mcp/taxonomy/track_labels_v202402.xlsx",
    }
    cfg.update(overrides)
    return cfg


class LmsParseTests(unittest.TestCase):
    def test_parse_class4_tags(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response

        tags = parse_track_labels_response(
            {
                "status": 0,
                "msg": "ok",
                "data": [
                    {
                        "corpName": "黑龙江北大荒垦征农机装备有限公司",
                        "class4Tag": ["拖拉机制造", "种植业机械制造", ""],
                    }
                ],
            },
            company_name="黑龙江北大荒垦征农机装备有限公司",
        )
        self.assertEqual(tags, ["拖拉机制造", "种植业机械制造"])

    def test_parse_api_platform_body(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response

        tags = parse_track_labels_response(
            {
                "data": {
                    "corpName": "维谛技术有限公司",
                    "class4Tag": [
                        "高效节能电气机械器材制造",
                        "运行维护服务",
                        "智能电力控制设备及电缆制造",
                        "信息系统集成和物联网技术服务",
                        "网络设备制造",
                    ],
                },
                "status": 0,
            },
            company_name="维谛技术有限公司",
        )
        self.assertEqual(tags[0], "高效节能电气机械器材制造")
        self.assertEqual(len(tags), 5)

    def test_parse_single_enterprise_object(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response

        tags = parse_track_labels_response(
            {
                "status": 0,
                "data": {
                    "corpName": "维谛技术有限公司",
                    "class4Tag": "数据中心基础设施,精密空调",
                },
            },
            company_name="维谛技术有限公司",
        )
        self.assertEqual(tags, ["数据中心基础设施", "精密空调"])

    def test_matches_enterprise_with_half_width_parentheses_in_response(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response

        tags = parse_track_labels_response(
            {
                "status": 0,
                "data": [
                    {"corpName": "示例(上海)科技有限公司", "class4Tag": ["应用软件开发"]},
                    {"corpName": "示例(北京)科技有限公司", "class4Tag": ["通信设备制造"]},
                ],
            },
            company_name="示例（北京）科技有限公司",
        )

        self.assertEqual(tags, ["通信设备制造"])

    def test_gateway_error_raises(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response
        from data_mcp.shared.http.errors import ExternalServiceError

        with self.assertRaises(ExternalServiceError):
            parse_track_labels_response(
                {"error_msg": "404 Route Not Found"},
                company_name="A公司",
            )

    def test_empty_tag_list_is_empty_result(self) -> None:
        from data_mcp.features.track_labels.lms_client import parse_track_labels_response

        self.assertEqual(
            parse_track_labels_response(
                {"status": 0, "data": {"corpName": "A公司", "class4Tag": []}},
                company_name="A公司",
            ),
            [],
        )
        self.assertEqual(
            parse_track_labels_response(
                {"status": 0, "data": []},
                company_name="A公司",
            ),
            [],
        )


class ApiPlatformRequestTests(unittest.TestCase):
    def test_posts_gateway_body(self) -> None:
        from unittest import mock

        from data_mcp.features.track_labels.lms_client import query_lms_track_labels

        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "status": 0,
            "data": [{"corpName": "维谛技术有限公司", "class4Tag": ["精密空调"]}],
        }
        cfg = {
            "api": {
                "base_url": "http://10.254.95.199:9080",
                "path": "/v1/API_LMS_LMS_BROPEN_InquirySingleEnterpriseTrackLabelsSrv",
                "method": "POST",
                "secret_key": "biz-secret",
                "source": "2",
                "x_gw_appid": "AIZT",
                "x_gw_org": "VOLCENGINE",
                "x_gw_token": "test-gw-token",
                "timeout_seconds": 90,
            }
        }
        with mock.patch(
            "data_mcp.features.track_labels.lms_client.http_request",
            return_value=response,
        ) as request, mock.patch(
            "data_mcp.features.track_labels.lms_client.build_jgfw_gateway_headers",
            return_value={"x-gw-token": "signed"},
        ):
            tags = query_lms_track_labels("维谛技术有限公司", config=cfg)

        self.assertEqual(tags, ["精密空调"])
        _, url = request.call_args.args[:2]
        self.assertEqual(
            url,
            "http://10.254.95.199:9080/v1/API_LMS_LMS_BROPEN_InquirySingleEnterpriseTrackLabelsSrv",
        )
        self.assertEqual(
            request.call_args.kwargs["json"],
            {
                "secretKey": "biz-secret",
                "source": "2",
                "corpName": "维谛技术有限公司",
            },
        )
        self.assertEqual(request.call_args.kwargs["headers"]["x-gw-token"], "signed")
        self.assertEqual(request.call_args.kwargs["timeout"], 90)
        self.assertEqual(request.call_args.kwargs["max_retries"], 0)


class QueryTrackLabelsServiceTests(unittest.TestCase):
    def test_requires_company_and_profile(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels

        with self.assertRaises(ValueError):
            query_track_labels("", {"细分赛道": "x"})
        with self.assertRaises(ValueError):
            query_track_labels("A公司", None)
        with self.assertRaises(ValueError):
            query_track_labels("A公司", "")
        with self.assertRaises(ValueError):
            query_track_labels("A公司", {})

    def test_api_success_first_attempt(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels

        sleeps: list[float] = []

        def fetch_api(company_name, env=None, config=None):
            return ["拖拉机制造", "种植业机械制造"]

        result = query_track_labels(
            "黑龙江北大荒垦征农机装备有限公司",
            project_profile={"细分赛道": "农机"},
            env="dev",
            fetch_api=fetch_api,
            sleep_fn=sleeps.append,
            invoke_agent=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent")),
            is_api_configured=lambda _c: True,
            config=_cfg(),
        )
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["tags"], ["拖拉机制造", "种植业机械制造"])
        self.assertEqual(result["meta"]["api_attempts"], 1)
        self.assertFalse(result["meta"]["fallback_used"])
        self.assertEqual(sleeps, [])

    def test_empty_then_retry_success(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels
        from data_mcp.shared.http.errors import ExternalServiceError

        calls = {"n": 0}
        sleeps: list[float] = []

        def fetch_api(company_name, env=None, config=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ExternalServiceError("LMS", "赛道标签为空")
            return ["拖拉机制造"]

        result = query_track_labels(
            "A公司",
            project_profile="画像",
            env="dev",
            fetch_api=fetch_api,
            sleep_fn=sleeps.append,
            invoke_agent=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no agent")),
            is_api_configured=lambda _c: True,
            config=_cfg(),
        )
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["tags"], ["拖拉机制造"])
        self.assertEqual(result["meta"]["api_attempts"], 2)
        self.assertEqual(sleeps, [20])

    def test_unconfigured_skips_wait_goes_fallback_agent(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels

        sleeps: list[float] = []
        api_calls = {"n": 0}
        agent_calls: list[tuple] = []

        def fetch_api(company_name, env=None, config=None):
            api_calls["n"] += 1
            raise RuntimeError("LMS 未配置")

        def agent(company_name, project_profile, env=None, config=None):
            agent_calls.append((company_name, project_profile))
            return ["拖拉机制造", "伪造标签"]

        cfg = _cfg()
        cfg["api"] = {
            "base_url": "",
            "path": "/api/foreign/get/track/labels",
            "secret_key": "",
        }

        result = query_track_labels(
            "A公司",
            project_profile={"细分赛道": "农机"},
            env="dev",
            fetch_api=fetch_api,
            sleep_fn=sleeps.append,
            invoke_agent=agent,
            is_api_configured=lambda c: False,
            config=cfg,
            allowed_tags=frozenset({"拖拉机制造", "种植业机械制造"}),
        )
        self.assertEqual(api_calls["n"], 0)
        self.assertEqual(sleeps, [])
        self.assertEqual(len(agent_calls), 1)
        self.assertEqual(agent_calls[0][0], "A公司")
        self.assertEqual(agent_calls[0][1], {"细分赛道": "农机"})
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["tags"], ["拖拉机制造"])
        self.assertTrue(result["meta"]["fallback_used"])
        self.assertTrue(any("伪造" in w or "非法" in w or "丢弃" in w for w in result["warnings"]))

    def test_empty_list_retries_once_then_fallback(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels

        sleeps: list[float] = []
        api_names: list[str] = []
        fallback_names: list[str] = []

        def fetch_api(company_name, env=None, config=None):
            api_names.append(company_name)
            return []

        def agent(company_name, project_profile, env=None, config=None):
            fallback_names.append(company_name)
            return ["拖拉机制造"]

        result = query_track_labels(
            "  示例(北京)科技有限公司  ",
            project_profile={"细分赛道": "电力设备"},
            env="dev",
            fetch_api=fetch_api,
            sleep_fn=sleeps.append,
            invoke_agent=agent,
            is_api_configured=lambda _c: True,
            config=_cfg(),
            allowed_tags=frozenset({"拖拉机制造"}),
        )
        self.assertEqual(api_names, ["示例（北京）科技有限公司"] * 2)
        self.assertEqual(fallback_names, ["示例（北京）科技有限公司"])
        self.assertEqual(sleeps, [20])
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["tags"], ["拖拉机制造"])
        self.assertTrue(result["meta"]["fallback_used"])

    def test_double_failure_fallback(self) -> None:
        from data_mcp.features.track_labels.service import query_track_labels
        from data_mcp.shared.http.errors import ExternalServiceError

        sleeps: list[float] = []

        def fetch_api(company_name, env=None, config=None):
            raise ExternalServiceError("LMS", "down")

        def agent(company_name, project_profile, env=None, config=None):
            return ["拖拉机制造"]

        result = query_track_labels(
            "A公司",
            project_profile={"细分赛道": "农机"},
            env="dev",
            fetch_api=fetch_api,
            sleep_fn=sleeps.append,
            invoke_agent=agent,
            is_api_configured=lambda _c: True,
            config=_cfg(),
            allowed_tags=frozenset({"拖拉机制造"}),
        )
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["tags"], ["拖拉机制造"])
        self.assertEqual(result["meta"]["api_attempts"], 2)
        self.assertEqual(sleeps, [20])
        self.assertTrue(result["warnings"])

    def test_schema_roundtrip(self) -> None:
        from data_mcp.mcp.schemas import validate_tool_input, validate_tool_output

        validate_tool_input(
            "query_track_labels",
            {"company_name": "A公司", "project_profile": {"细分赛道": "x"}},
        )
        with self.assertRaises(ValueError):
            validate_tool_input("query_track_labels", {"company_name": "A公司"})
        validate_tool_output(
            "query_track_labels",
            {
                "schema_version": "1.0",
                "tool": "query_track_labels",
                "status": "success",
                "summary": "本次获得 1 个赛道标签",
                "data": {"tags": ["拖拉机制造"]},
                "sources": [{"name": "lms", "status": "used"}],
                "warnings": [],
            },
        )


class ParseAgentTagsTests(unittest.TestCase):
    def test_parse_choices_last_saidao_tags(self) -> None:
        from data_mcp.features.track_labels.hiagent_client import parse_selected_tags

        payload = {
            "choices": [
                {
                    "componentName": "三级标签生成",
                    "content": '{"三级标签": ["电子核心产业", "智能制造装备产业", "仪器仪表制造业"]}',
                },
                {
                    "componentName": "智能对话",
                    "content": '{"赛道标签": ["电子专用设备仪器制造", "光学仪器制造"]}',
                },
                {
                    "componentName": "确定回复",
                    "content": '{\n  "赛道标签": ["电子专用设备仪器制造", "光学仪器制造"]\n}',
                },
            ],
            "state": {"company_name": "惠然科技", "tags": ""},
        }
        self.assertEqual(
            parse_selected_tags(payload),
            ["电子专用设备仪器制造", "光学仪器制造"],
        )

    def test_parse_from_choice_array_fallback(self) -> None:
        from data_mcp.features.track_labels.hiagent_client import parse_selected_tags

        self.assertEqual(
            parse_selected_tags(
                {"choice": {"content": '["拖拉机制造", "种植业机械制造"]'}}
            ),
            ["拖拉机制造", "种植业机械制造"],
        )

    def test_parse_legacy_tag123_on_last_choice(self) -> None:
        from data_mcp.features.track_labels.hiagent_client import parse_selected_tags

        payload = {
            "choices": [
                {"content": "分析文字"},
                {
                    "content": (
                        '{"公司名称":"","tag1":"拖拉机制造","tag2":"种植业机械制造","tag3":""}'
                    )
                },
            ]
        }
        self.assertEqual(
            parse_selected_tags(payload),
            ["拖拉机制造", "种植业机械制造"],
        )


if __name__ == "__main__":
    unittest.main()
