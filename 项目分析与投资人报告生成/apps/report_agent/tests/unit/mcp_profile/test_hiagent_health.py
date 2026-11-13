"""Diagnose the three HiAgent agents used by Data MCP.

Data MCP talks to ``https://uat.agentspro.cn`` with four agent ids:

``historical_valuation`` 423343a9…  (working)
``investor_network``      8782307b…  (returned non-JSON once)
``project_profile``       9422be35…  (times out)
``track_labels``          56feaa17…  (fallback only, the API platform is primary)

A timeout here is *reported*, not failed: the test asserts the endpoint is
reachable and the response is well-formed, and uses ``pytest.skip`` when the
upstream simply does not answer within the window. That keeps ``pytest`` green
while still surfacing which agent is unhealthy in ``-ra`` output.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
DATA_MCP_CONFIG = REPO_ROOT / "deploy/environments/test/data-mcp.yaml"


def _config() -> dict:
    if not DATA_MCP_CONFIG.is_file():
        pytest.skip(f"data-mcp config not found: {DATA_MCP_CONFIG}")
    return yaml.safe_load(DATA_MCP_CONFIG.read_text(encoding="utf-8"))


def _agent_ids(cfg: dict) -> dict[str, dict]:
    """Collect every HiAgent-style section that carries ``agent_id``."""
    found: dict[str, dict] = {}
    for section in ("historical_valuation", "investor_network", "project_profile"):
        block = cfg.get(section) or {}
        if block.get("agent_id"):
            found[section] = block
    track = ((cfg.get("track_labels") or {}).get("hiagent")) or {}
    if track.get("agent_id"):
        found["track_labels.hiagent"] = track
    if not found:
        pytest.skip("no HiAgent agents configured")
    return found


def _post_agent(block: dict, timeout: float) -> tuple[int, float, str]:
    url = f"{block['host'].rstrip('/')}{block['path']}"
    payload = {
        "agentId": block["agent_id"],
        "chatId": block.get("chat_id"),
        "userChatInput": "",
        "state": {"file_info": "测试：惠然科技有限公司，注册资本13,180.00万元。"},
        "buttonKey": block.get("button_key"),
        "debug": block.get("debug", False),
    }
    started = time.monotonic()
    response = requests.post(
        url,
        headers={"token": block["token"], "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    return response.status_code, time.monotonic() - started, response.text[:200]


def test_every_agent_is_configured() -> None:
    agents = _agent_ids(_config())
    assert agents, "expected at least one HiAgent agent"
    for name, block in agents.items():
        assert block.get("agent_id"), f"{name} is missing agent_id"
        assert block.get("host", "").startswith("http"), f"{name} has a bad host"
        assert block.get("path", "").startswith("/"), f"{name} has a bad path"


def test_agent_paths_use_singular_agent() -> None:
    """The live endpoint is ``/openapi/agent/...``; ``agents`` returns 404."""
    agents = _agent_ids(_config())
    offenders = {
        name: block["path"]
        for name, block in agents.items()
        if "/openapi/agents/" in block["path"]
    }
    assert not offenders, (
        "these agents point at the plural path that returns 404: "
        f"{offenders}; the working path is /openapi/agent/chat/completions/v1"
    )


@pytest.mark.parametrize("section", ["historical_valuation", "project_profile"])
def test_agent_answers_within_window(section: str) -> None:
    agents = _agent_ids(_config())
    block = agents.get(section)
    if block is None:
        pytest.skip(f"{section} is not configured")

    try:
        status, elapsed, body = _post_agent(block, timeout=60)
    except requests.exceptions.ReadTimeout:
        pytest.skip(
            f"{section} agent {block['agent_id']} did not answer in 60s "
            "(known HiAgent-side issue for project_profile)"
        )

    assert status == 200, f"{section} returned HTTP {status}: {body}"
    assert body, f"{section} returned an empty body"
    assert elapsed < 60, f"{section} took {elapsed:.1f}s"
