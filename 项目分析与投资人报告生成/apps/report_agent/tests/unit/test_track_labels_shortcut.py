"""临时覆盖：赛道标签接口不可达时跳过整次查询。

这是**部署环境**的绕行，不是业务逻辑：测试机连不上 10.254.x 网段，一等等 424 秒。
开关走环境变量，网络通了或换机器后取消变量即可，不需要改代码，也不碰 data_mcp。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from report_agent.harness import data_tools


@dataclass
class _View:
    status: str = "ok"
    path: str = ""
    summary: str = ""
    warnings: list = field(default_factory=list)


class _Contracts:
    def description(self, name: str) -> str:
        return f"{name}（测试桩）"

    def input_schema(self, name: str):  # noqa: ANN201
        return None


class _Gateway:
    contracts = _Contracts()

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, name: str, arguments: dict):  # noqa: ANN201
        self.calls.append(name)
        return _View()


def _tool(gateway: _Gateway, name: str):
    return data_tools._build_tool(gateway, name)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(data_tools.SHORTCUT_ENV, raising=False)
    monkeypatch.delenv(data_tools.SHORTCUT_TIMEOUT_ENV, raising=False)


@pytest.mark.asyncio
async def test_shortcut_is_off_without_the_environment_variable():
    gateway = _Gateway()
    await _tool(gateway, "query_track_labels").coroutine(company_name="x")
    assert gateway.calls == ["query_track_labels"], "没开开关就必须照常调用"


@pytest.mark.asyncio
async def test_an_unreachable_host_skips_the_call(monkeypatch):
    monkeypatch.setenv(data_tools.SHORTCUT_ENV, "http://10.254.95.199:9080")
    monkeypatch.setattr(data_tools, "_probe_sync", lambda url, timeout: "10.254.95.199:9080 不可达")
    gateway = _Gateway()

    payload = json.loads(await _tool(gateway, "query_track_labels").coroutine(company_name="x"))

    assert gateway.calls == [], "不可达时不应再触发 MCP 调用"
    assert payload["status"] == "partial"
    assert payload["meta"]["shortcut"] is True
    assert payload["warnings"][0]["code"] == "TRACK_LABELS_SHORTCUT"
    assert "按材料推断" in payload["summary"], "降级说明必须告诉模型怎么继续"


@pytest.mark.asyncio
async def test_a_reachable_host_still_calls(monkeypatch):
    monkeypatch.setenv(data_tools.SHORTCUT_ENV, "http://127.0.0.1:8001")
    monkeypatch.setattr(data_tools, "_probe_sync", lambda url, timeout: "")
    gateway = _Gateway()
    await _tool(gateway, "query_track_labels").coroutine(company_name="x")
    assert gateway.calls == ["query_track_labels"]


@pytest.mark.asyncio
async def test_other_tools_are_never_short_circuited(monkeypatch):
    monkeypatch.setenv(data_tools.SHORTCUT_ENV, "http://10.254.95.199:9080")
    monkeypatch.setattr(data_tools, "_probe_sync", lambda url, timeout: "不可达")
    gateway = _Gateway()
    await _tool(gateway, "match_investors").coroutine(project_profile="x")
    assert gateway.calls == ["match_investors"]


def test_probe_reports_an_unresolvable_host_as_unreachable():
    # 保留真实 socket 路径：确保 _probe_sync 自己也能判断，而不只是被 mock 才生效。
    reason = data_tools._probe_sync("http://127.0.0.1:1", 0.3)
    assert reason, "关闭的端口应判为不可达"
    assert "不可达" in reason
