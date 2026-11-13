"""Real XLSX and HTTP-boundary regressions for the optional DMP export."""

import base64
import hashlib
import io
import json
from unittest.mock import patch

import httpx
import pytest
from openpyxl import load_workbook

import tests.support  # noqa: F401
from data_mcp.features.investor_match import dmp_client
from data_mcp.features.investor_match.workbook import (
    HEADERS,
    build_institution_workbook,
    export_institution_workbook,
    match_requested_labels,
    normalize_track_tags,
    slim_institution_rows,
)
from data_mcp.mcp.schemas import validate_tool_output


@pytest.mark.parametrize(
    "raw",
    [
        "Ａ， 乙;丙；丁|戊\n己、庚",
        ["Ａ", "乙", "丙", "丁", "戊", "己", "庚"],
        '["Ａ","乙","丙","丁","戊","己","庚"]',
    ],
)
def test_exact_intersection_normalizes_lists_but_never_fuzzy_matches(raw):
    match = match_requested_labels(["A", "己", "其他食品制造", "庚"], raw)
    assert match.labels == ["A", "己", "庚"]
    assert not match.unverified
    assert match_requested_labels(["其他食品制造"], "食品制造").labels == []
    partial = match_requested_labels(["甲", "乙"], "甲,乙…,其他")
    assert partial.labels == ["甲"] and partial.unverified


def test_real_workbook_stable_ranking_types_formula_safety_and_diagnostics():
    items = [
        None,
        {"investor_name": ""},
        {
            "investor_name": "=not_a_formula",
            "match_label_weight_sum": "82.5",
            "match_label_num": "2.0",
            "label_name_list": "甲,乙,其他",
        },
        {
            "investor_name": "同分",
            "match_label_weight_sum": 82.5,
            "match_label_num": 1,
            "label_name_list": "甲",
        },
        {
            "investor_name": "\x00异常",
            "match_label_weight_sum": "NaN",
            "match_label_num": "2.5",
            "label_name_list": None,
        },
        {
            "investor_name": "截断",
            "match_label_weight_sum": False,
            "match_label_num": 2,
            "label_name_list": "乙,其他…",
        },
    ]
    result = slim_institution_rows(items, ["甲", "乙"])
    assert all(
        set(row) == {"investor_name", "match_label_weight_sum", "match_label_num", "matched_labels"}
        for row in result.rows
    )
    content = build_institution_workbook(result)
    book = load_workbook(io.BytesIO(content))
    sheet = book.active
    assert tuple(c.value for c in sheet[1]) == HEADERS
    assert [sheet.cell(i, 1).value for i in range(2, 6)] == [
        "=not_a_formula",
        "同分",
        "异常",
        "截断",
    ]
    assert sheet["A2"].data_type == "s"
    assert sheet["B2"].value == "82.5" and sheet["B2"].data_type == "s"
    assert sheet["B5"].value == "0"  # invalid/False weight rendered as integer text
    assert sheet["C2"].value == 2 and sheet["C4"].value is None
    assert sheet["D2"].value == "甲、乙" and sheet["D5"].value == "乙"
    assert sheet["D5"].comment and sheet["D4"].comment
    assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref == "A1:D5"


@pytest.mark.parametrize("raw", [-1, True, 1.5, "NaN", "Infinity", "1e100000000", "2147483648"])
def test_invalid_count_does_not_create_a_fake_label_number(raw):
    result = slim_institution_rows([{"investor_name": "机构", "match_label_num": raw}], ["甲"])
    assert result.rows[0]["match_label_num"] is None


def test_first_200_sorted_without_retaining_long_label_lists():
    items = [
        {
            "investor_name": str(i),
            "match_label_weight_sum": i,
            "match_label_num": 1,
            "label_name_list": "甲," + "其他," * 10000,
        }
        for i in range(230)
    ]
    result = slim_institution_rows(items, ["甲"])
    assert len(result.rows) == 200 and result.rows[0]["investor_name"] == "229"
    assert len(json.dumps(result.rows, ensure_ascii=False)) < 40000


def test_export_envelope_has_real_empty_xlsx_and_no_raw_rows():
    with patch.object(
        dmp_client,
        "query_dmp_institutions_for_export",
        return_value=slim_institution_rows([], ["甲"]),
    ):
        payload = export_institution_workbook(["甲"])
    validate_tool_output("export_matched_institutions", payload)
    content = base64.b64decode(payload["data"]["content_base64"], validate=True)
    assert hashlib.sha256(content).hexdigest() == payload["data"]["sha256"]
    assert payload["status"] == "empty" and payload["data"]["row_count"] == 0
    assert "items" not in payload["data"] and "label_name_list" not in json.dumps(payload)
    assert load_workbook(io.BytesIO(content)).active.max_row == 1


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("wrapper", [None, "body", "data"])
def test_export_http_is_one_institution_request_with_own_limits(monkeypatch, method, wrapper):
    calls = []

    def handle(request):
        body = dict(request.url.params) if method == "GET" else json.loads(request.content)
        calls.append(body)
        assert str(body["limit"]) == "200" and str(body["offset"]) == "0"
        assert body["investor_type"] == "机构" and body["label_type"] == "股权转让/增资"
        assert body["label_name"] == "甲,乙" and "signature" in request.headers
        business = {
            "count": 30,
            "hasMore": True,
            "items": [
                {
                    "investor_name": "机构",
                    "match_label_weight_sum": 82.5,
                    "match_label_num": 2,
                    "label_name_list": "甲,其他食品制造,...",
                },
            ],
        }
        return httpx.Response(200, json={wrapper: business} if wrapper else business)

    config = {
        "dmp": dict(
            base_url="https://dmp.test",
            path="/query",
            method=method,
            x_gw_token="token",
            app_key="key",
            app_secret="secret",
        )
    }
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(dmp_client, "load_investor_match_config", lambda env: config)
    monkeypatch.setattr(dmp_client, "build_jgfw_gateway_headers", lambda cfg: {"x-test": "yes"})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    result = dmp_client.query_dmp_institutions_for_export(["甲", "乙"])
    assert len(calls) == 1 and result.rows[0]["matched_labels"] == ["甲"]
    assert result.rows[0]["match_label_weight_sum"] == 82.5
    assert result.rows[0]["match_label_num"] == 2
    assert result.diagnostics == [(True, True)]


def test_response_limit_counts_actual_bytes_and_does_not_retry(monkeypatch):
    from data_mcp.shared import settings

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 2048, headers={"Content-Length": "10"})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(
        dmp_client,
        "load_investor_match_config",
        lambda env: {
            "dmp": dict(
                base_url="https://dmp.test", path="/q", x_gw_token="x", app_key="a", app_secret="b"
            )
        },
    )
    monkeypatch.setattr(dmp_client, "build_jgfw_gateway_headers", lambda cfg: {})
    monkeypatch.setattr(
        settings,
        "load_workbook_export_config",
        lambda: dict(request_timeout_seconds=1, max_response_bytes=1024),
    )
    with pytest.raises(ValueError, match="TOO_LARGE"):
        dmp_client.query_dmp_institutions_for_export(["甲"])
    assert len(calls) == 1


def test_tool_validation_failure_does_not_log_or_return_large_payload(monkeypatch, caplog):
    from data_mcp.features.investor_match import workbook
    from data_mcp.mcp.server import export_matched_institutions

    marker = "SENSITIVE_BASE64_MARKER"
    monkeypatch.setattr(
        workbook,
        "export_institution_workbook",
        lambda tags: {"data": {"content_base64": marker * 10000}},
    )
    result = export_matched_institutions(["甲"])
    assert result["status"] == "failed" and result["data"] == {}
    assert marker not in caplog.text and marker not in json.dumps(result)


def test_normalized_tags_reject_expansion_and_invalid_arrays():
    assert normalize_track_tags("Ａ，A；乙") == ["A", "乙"]
    for value in ([], ["甲"] * 0, ["甲,乙"], ["甲", True], [str(i) for i in range(11)]):
        with pytest.raises(ValueError):
            normalize_track_tags(value)


def test_normalize_track_tags_strips_wrapping_quotes():
    assert normalize_track_tags('"住宿业","餐饮业"') == ["住宿业", "餐饮业"]
    assert normalize_track_tags(['"集成电路制造"', '"特种电子"']) == [
        "集成电路制造",
        "特种电子",
    ]


@pytest.mark.parametrize(
    "content", [b"not-json", b"[]", b'{"items":null}', b'{"body":"not-an-object"}']
)
def test_invalid_export_responses_return_fixed_diagnostic_code(monkeypatch, content, caplog):
    from data_mcp.mcp.server import export_matched_institutions

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    )
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(
        dmp_client,
        "load_investor_match_config",
        lambda env: {
            "dmp": dict(
                base_url="https://dmp.test",
                path="/query",
                x_gw_token="token",
                app_key="key",
                app_secret="secret",
            )
        },
    )
    monkeypatch.setattr(dmp_client, "build_jgfw_gateway_headers", lambda cfg: {})
    payload = export_matched_institutions(["甲"])
    validate_tool_output("export_matched_institutions", payload)
    assert payload["status"] == "failed" and payload["data"] == {}
    assert payload["warnings"][0]["code"] == "DMP_EXPORT_INVALID_RESPONSE"
    assert "not-an-object" not in caplog.text


@pytest.mark.parametrize(
    "exc,code",
    [
        (ValueError("DMP_EXPORT_NOT_CONFIGURED"), "DMP_EXPORT_NOT_CONFIGURED"),
        (httpx.ConnectError("private network details"), "DMP_EXPORT_UNAVAILABLE"),
        (httpx.ReadTimeout("private network details"), "DMP_EXPORT_TIMEOUT"),
    ],
)
def test_export_reports_configuration_connection_and_timeout_separately(monkeypatch, exc, code):
    from data_mcp.mcp.server import export_matched_institutions

    def fail(*args):
        raise exc

    monkeypatch.setattr(dmp_client, "query_dmp_institutions_for_export", fail)
    payload = export_matched_institutions(["甲"])
    assert payload["warnings"][0]["code"] == code
    assert "private" not in json.dumps(payload)
