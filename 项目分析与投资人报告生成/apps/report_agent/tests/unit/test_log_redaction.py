"""日志脱敏与可关联性：凭证不能落盘，每行要能 join 回 run。"""

from __future__ import annotations

from report_agent.harness.middleware.agent_logger import _redact, _redact_text

PRESIGNED = (
    "http://101.126.54.157:9000/bjstest/exports/a.md"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=admin%2F20261106%2Fcn-north-1"
    "&X-Amz-Signature=deadbeefcafe1234"
    "&X-Amz-Date=20261106T054918Z"
    "&X-Amz-Expires=3600"
)


def test_presigned_signature_is_scrubbed_but_the_url_stays_readable():
    """实测泄漏过：一次真实 run 里 53 条 admin AccessKey 的预签名 URL 明文落盘。"""
    cleaned = _redact_text(PRESIGNED)

    assert "deadbeefcafe1234" not in cleaned
    assert "admin%2F20261106" not in cleaned
    assert "X-Amz-Signature=[REDACTED]" in cleaned
    assert "X-Amz-Credential=[REDACTED]" in cleaned
    # 其余部分保留：排障时仍要知道是哪个桶、哪个对象
    assert "101.126.54.157:9000" in cleaned
    assert "/bjstest/exports/a.md" in cleaned
    assert "X-Amz-Expires=3600" in cleaned


def test_dict_key_redaction_still_works():
    out = _redact({"api_key": "sk-123", "note": "ok", "input_tokens": 42})
    assert out["api_key"] == "[REDACTED]"
    assert out["note"] == "ok"
    # 遥测键不能被当密钥吞掉，否则拿不到 token 用量
    assert out["input_tokens"] == 42


def test_bearer_tokens_in_free_text_are_scrubbed():
    assert "sk-abcdef123456789" not in _redact_text("Authorization: Bearer sk-abcdef123456789")


def test_nested_strings_are_scrubbed():
    payload = {"messages": [{"content": f"看看这个 {PRESIGNED} 能不能下"}]}
    cleaned = str(_redact(payload))
    assert "deadbeefcafe1234" not in cleaned
    assert "看看这个" in cleaned


def test_plain_text_is_left_alone():
    assert _redact_text("没有秘钥的普通日志") == "没有秘钥的普通日志"
    assert _redact_text("") == ""
