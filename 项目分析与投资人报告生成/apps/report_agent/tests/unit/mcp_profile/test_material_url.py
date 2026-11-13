"""MinIO round-trip used by ``export_parsed_md`` → ``material_url``.

``extract_project_profile`` accepts either an inline ``file_info`` string or a
``material_url`` the Data MCP downloads itself. The URL path only works when we
can upload the parsed markdown and hand out a presigned link, so these two
probes protect that contract.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests


def test_upload_markdown_returns_downloadable_url(
    minio_service: Any, runtime_env: dict[str, str]
) -> None:
    """The presigned URL must be fetched back byte-for-byte."""
    markdown = "# 测试材料\n\n惠然科技有限公司，注册资本13,180.00万元。"
    key = "exports/pytest/material_url_roundtrip.md"

    url, expires = minio_service.upload_markdown(key, markdown)

    assert url.startswith("http"), f"expected an HTTP URL, got {url[:40]!r}"
    assert expires is not None

    response = requests.get(url, timeout=20)
    assert response.status_code == 200, response.text[:200]
    assert response.text == markdown


def test_upload_markdown_overwrites_same_key(minio_service: Any) -> None:
    """Re-uploading the same key must serve the newest content."""
    key = "exports/pytest/material_url_overwrite.md"

    first_url, _ = minio_service.upload_markdown(key, "第一版")
    second_url, _ = minio_service.upload_markdown(key, "第二版")

    assert requests.get(first_url, timeout=20).text == "第一版"
    assert requests.get(second_url, timeout=20).text == "第二版"


def test_export_parsed_md_tool_requires_object_storage() -> None:
    """Without an uploader the tool must fail loudly, not silently truncate."""
    import asyncio
    import json

    from report_agent.application.materials import MaterialIngestionService
    from report_agent.harness.material_tools import build_material_tools

    tools = {
        tool.name: tool
        for tool in build_material_tools(
            MaterialIngestionService.__new__(MaterialIngestionService)
        )
    }
    assert "export_parsed_md" in tools
    assert "export_material_text" in tools

    with pytest.raises(Exception) as excinfo:
        asyncio.run(
            tools["export_parsed_md"].ainvoke({"material_id": "material_" + "0" * 32})
        )
    assert "对象存储未配置" in str(excinfo.value)


def test_env_has_minio_credentials(runtime_env: dict[str, str]) -> None:
    """Guard against the secret drifting from the running container."""
    assert runtime_env.get("MINIO_ENDPOINT"), "MINIO_ENDPOINT is missing"
    assert runtime_env.get("MINIO_BUCKET"), "MINIO_BUCKET is missing"
    secret = runtime_env.get("MINIO_SECRET_KEY", "")
    assert secret, "MINIO_SECRET_KEY is missing"
