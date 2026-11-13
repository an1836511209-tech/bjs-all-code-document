"""``extract_project_profile`` probes over the real Data MCP transport.

The tool has two ways to receive material:

* ``material_url`` — a presigned link the Data MCP downloads itself
* ``file_info``    — the parsed text sent inline

Both were historically broken in different ways (local paths rejected; model
summaries truncating 7.7k chars to 637). These tests pin the observable
contract so a regression shows up as a red test instead of an empty profile
buried in a 40-minute report run.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

COMPANY = "惠然科技有限公司"
KEYWORDS = ["电子束", "扫描电镜"]


async def _call_profile(transport: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = await transport.call_tool("extract_project_profile", arguments)
    assert isinstance(payload, dict), "MCP must return a JSON object"
    assert payload.get("status") in {"success", "partial", "empty", "failed"}, payload
    return payload


@pytest.mark.parametrize("limit", [600, 2000])
async def test_profile_with_small_material_url(
    data_mcp_transport: Any,
    minio_service: Any,
    material_text: str,
    limit: int,
) -> None:
    """Small payloads must not be rejected for size or URL scheme reasons."""
    snippet = material_text[:limit]
    assert snippet, "material snippet is empty"

    url, _ = minio_service.upload_markdown(
        f"exports/pytest/profile_{limit}.md", snippet
    )
    payload = await _call_profile(
        data_mcp_transport,
        {"company_name": COMPANY, "material_url": url, "search_keywords": KEYWORDS},
    )

    # The upstream HiAgent agent may time out; what must never happen is a
    # schema rejection ("material_url 仅支持 http/https") or a transport crash.
    assert payload.get("status") != "failed" or "schema" not in str(
        payload.get("summary")
    ).lower(), payload


async def test_profile_rejects_local_path(
    data_mcp_transport: Any,
) -> None:
    """A workspace path is not a URL and must be reported as a validation error."""
    payload = await _call_profile(
        data_mcp_transport,
        {
            "company_name": COMPANY,
            "material_url": "/workspace/input/material.pdf",
            "search_keywords": KEYWORDS,
        },
    )

    assert payload.get("status") == "failed", payload
    assert "http" in str(payload.get("summary")).lower()
    warnings = payload.get("warnings") or []
    assert any("VALIDATION" in json.dumps(item) for item in warnings), warnings


async def test_profile_with_inline_file_info(
    data_mcp_transport: Any, material_text: str
) -> None:
    """``file_info`` must be accepted and reach the same code path as a URL."""
    payload = await _call_profile(
        data_mcp_transport,
        {
            "company_name": COMPANY,
            "file_info": material_text[:2000],
            "search_keywords": KEYWORDS,
        },
    )

    assert payload.get("status") != "failed" or "schema" not in str(
        payload.get("summary")
    ).lower(), payload


async def test_profile_requires_material(
    data_mcp_transport: Any,
) -> None:
    """Neither ``material_url`` nor ``file_info`` is a schema violation."""
    payload = await data_mcp_transport.call_tool(
        "extract_project_profile", {"company_name": COMPANY}
    )
    assert payload.get("status") == "failed", payload
    assert "schema" in str(payload.get("summary")).lower() or "material" in str(
        payload.get("summary")
    ).lower()
