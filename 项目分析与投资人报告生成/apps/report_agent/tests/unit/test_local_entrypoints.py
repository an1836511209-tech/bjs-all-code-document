"""The legacy local command must not silently disable opted-in attachments."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agent.entrypoints import api
from report_agent.infrastructure import artifacts


@pytest.mark.parametrize("enabled", [False, True])
def test_legacy_local_command_selects_shared_persistence_only_when_needed(monkeypatch, enabled):
    path = Path(__file__).resolve().parents[2] / "scripts/inmem_server.py"
    spec = importlib.util.spec_from_file_location("local_server_compatibility_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = SimpleNamespace(
        institution_workbook=SimpleNamespace(enabled=enabled),
        persistence=SimpleNamespace(minio=None),
        service=SimpleNamespace(
            workspace_root="unused", workspace_max_mb=1, max_upload_mb=1, dev_trace_max_chars=100
        ),
    )
    calls = []
    monkeypatch.setenv("REPORT_AGENT_CONFIG", "unused.yaml")
    monkeypatch.setattr(module, "load_settings", lambda path: config)
    monkeypatch.setattr(
        sys,
        "argv",
        ["inmem_server.py", "--host", "127.0.0.1", "--port", "8139"],
    )
    monkeypatch.setattr(api, "main", lambda: calls.append("persistent"))
    monkeypatch.setattr(module, "InMemoryRunRepository", lambda: calls.append("memory"))
    monkeypatch.setattr(module, "ConfiguredAgentExecutor", lambda *args, **kwargs: None)
    monkeypatch.setattr(artifacts, "MinioArtifactService", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "SynchronousRunService", lambda **kwargs: None)
    monkeypatch.setattr(module, "create_app", lambda *args, **kwargs: "memory-app")
    monkeypatch.setattr(module.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    module.main()

    assert calls == (
        ["persistent"]
        if enabled
        else ["memory", ("memory-app", {"host": "127.0.0.1", "port": 8139})]
    )
