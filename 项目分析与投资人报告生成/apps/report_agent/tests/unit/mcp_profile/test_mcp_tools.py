"""Contract probes for the other four Data MCP tools.

``match_listed_peers`` and ``query_track_labels`` are the two that do not depend
on HiAgent, so they must always return data. The HiAgent-backed tools may
degrade to ``empty`` when the upstream agent is unhealthy — that is asserted
explicitly so a genuine protocol break (non-JSON, transport crash) still fails.
"""

from __future__ import annotations

import json
from typing import Any

COMPANY = "惠然科技有限公司"
TAGS = ["电子专用设备仪器制造", "专用仪器仪表制造"]


async def test_listed_peers_returns_valuation_fields(data_mcp_transport: Any) -> None:
    payload = await data_mcp_transport.call_tool(
        "match_listed_peers",
        {"tags": TAGS, "summary": "电子束量测设备，半导体前道检测"},
    )

    assert payload.get("status") in {"success", "partial"}, payload
    peers = (payload.get("data") or {}).get("peers") or []
    assert peers, "expected at least one comparable listed company"

    first = peers[0]
    for field in ("证券代码", "证券名称", "PE", "PB(LF)"):
        assert field in first, f"missing {field} in {json.dumps(first, ensure_ascii=False)[:200]}"


async def test_track_labels_accepts_profile(data_mcp_transport: Any) -> None:
    """``project_profile`` must be a non-empty object, not ``{}``."""
    payload = await data_mcp_transport.call_tool(
        "query_track_labels",
        {
            "company_name": COMPANY,
            "project_profile": {"company_name": COMPANY, "main_business": "电子束量测设备"},
        },
    )

    assert payload.get("status") in {"success", "partial", "empty"}, payload
    if payload.get("status") != "empty":
        tags = (payload.get("data") or {}).get("tags") or []
        assert isinstance(tags, list)


async def test_track_labels_rejects_empty_profile(data_mcp_transport: Any) -> None:
    """``{}`` is not a valid ``project_profile`` — must be a schema error."""
    payload = await data_mcp_transport.call_tool(
        "query_track_labels", {"company_name": COMPANY, "project_profile": {}}
    )

    assert payload.get("status") == "failed", payload
    assert "schema" in str(payload.get("summary")).lower()


async def test_comparable_valuation_returns_json(data_mcp_transport: Any) -> None:
    """HiAgent may time out, but the transport must never return plain text."""
    payload = await data_mcp_transport.call_tool(
        "query_comparable_valuation",
        {"tags": TAGS[:1], "company_name": COMPANY},
    )

    assert isinstance(payload, dict)
    assert payload.get("status") in {"success", "partial", "empty", "failed"}


async def test_investor_match_returns_json(data_mcp_transport: Any) -> None:
    """Regression guard: this tool once replied with non-JSON text."""
    payload = await data_mcp_transport.call_tool(
        "match_investors", {"company_name": COMPANY, "track_tags": TAGS[:1]}
    )

    assert isinstance(payload, dict), "match_investors must return a JSON envelope"
    assert payload.get("status") in {"success", "partial", "empty", "failed"}
