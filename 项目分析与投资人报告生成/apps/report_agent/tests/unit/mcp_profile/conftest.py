"""Shared fixtures for the Data MCP project-profile integration probes.

These tests talk to real services (MinIO, Data MCP, and through it 企查查 /
智谱 / HiAgent). They skip instead of failing when a service is not running so
that ``pytest`` stays green on a laptop without the full stack.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests

from report_agent.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[5]
RUNTIME_ENV = REPO_ROOT / "deploy/environments/test/runtime.env"
AGENT_CONFIG = REPO_ROOT / "deploy/environments/test/report-agent.local.yaml"
# Filled in by a previous run; the probe reuses its parsed material so we do
# not need to parse a PDF (and run OCR) inside the test suite.
DEFAULT_MATERIAL = (
    REPO_ROOT
    / ".runtime/report-agent-workspaces"
    / "task_c3d9037ddc0a48028e2bad4fd6b66740"
    / "working/materials/material_0887c12259ae46149e422703124227e0.json"
)


def load_runtime_env(path: Path = RUNTIME_ENV) -> dict[str, str]:
    """Parse ``KEY=value`` lines, tolerating quotes and a UTF-8 BOM."""
    if not path.is_file():
        pytest.skip(f"runtime env not found: {path}")
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        env[key.strip()] = value
    return env


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def runtime_env() -> dict[str, str]:
    return load_runtime_env()


@pytest.fixture(scope="session")
def settings() -> Any:
    if not AGENT_CONFIG.is_file():
        pytest.skip(f"agent config not found: {AGENT_CONFIG}")
    return load_settings(AGENT_CONFIG)


@pytest.fixture(scope="session")
def material_text() -> str:
    """Full parsed material text, reused from a previous run's workspace."""
    if not DEFAULT_MATERIAL.is_file():
        pytest.skip(
            "no parsed material available; run an investment-report task first "
            f"or set MCP_PROFILE_MATERIAL to a material JSON path ({DEFAULT_MATERIAL})"
        )
    override = os.environ.get("MCP_PROFILE_MATERIAL", "").strip()
    path = Path(override) if override else DEFAULT_MATERIAL
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = payload.get("blocks") or []
    text = "\n\n".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if str(block.get("text") or "").strip()
    )
    if not text:
        pytest.skip(f"material file has no text blocks: {path}")
    return text


@pytest.fixture(scope="session")
def minio_service(settings: Any, runtime_env: dict[str, str]) -> Any:
    try:
        from report_agent.infrastructure.artifacts import MinioArtifactService

        service = MinioArtifactService(settings.persistence.minio, runtime_env)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MinIO not configured: {type(exc).__name__}: {exc}")
    try:
        service._client.bucket_exists(service._bucket)  # noqa: SLF001 - probe only
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MinIO unreachable: {type(exc).__name__}: {exc}")
    return service


@pytest.fixture(scope="session")
def data_mcp_transport(settings: Any) -> Iterator[Any]:
    from report_agent.infrastructure.mcp.streamable_http import (
        StreamableHttpMcpTransport,
    )

    url = getattr(settings.data_mcp, "url", "") or ""
    if not url:
        pytest.skip("data_mcp.url is not configured")
    probe_url = url.replace("/mcp", "") + "/health"
    try:
        requests.get(probe_url, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Data MCP not reachable at {url}: {type(exc).__name__}")
    yield StreamableHttpMcpTransport(url, timeout_seconds=300)
