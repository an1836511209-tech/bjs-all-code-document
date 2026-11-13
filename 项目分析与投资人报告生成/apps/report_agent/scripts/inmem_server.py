"""Legacy local entrypoint; use the persistent API when workbook export is enabled.

No MySQL, no Redis: runs live in process memory, uploaded workspaces still go
to disk under ``settings.service.workspace_root``. MinIO is optional — when it
is configured, ``export_parsed_md`` can hand the Data MCP a presigned URL;
otherwise the agent falls back to ``export_material_text``.

The optional workbook worker requires shared MySQL state. When that feature is
enabled this compatibility command delegates to the normal persistent API;
otherwise the original in-memory mode is preserved.

Usage::

    REPORT_AGENT_CONFIG=deploy/environments/test/report-agent.local.yaml \
        python apps/report_agent/scripts/inmem_server.py --port 8000
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import uvicorn

from report_agent.api import create_app
from report_agent.application.bootstrap import (
    ConfiguredAgentExecutor,
    suggest_conversation_title,
)
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.settings import load_settings


class _NoArtifactService:
    """Artifact storage stub used when MinIO is not reachable."""

    def publish(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("artifact storage is not configured in the in-memory server")

    def presign(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("artifact storage is not configured in the in-memory server")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Report Agent API (in-memory)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    raw_config_path = os.environ.get("REPORT_AGENT_CONFIG", "").strip()
    if not raw_config_path:
        raise SystemExit("REPORT_AGENT_CONFIG is required")
    settings = load_settings(Path(raw_config_path).expanduser())

    if settings.institution_workbook.enabled:
        from report_agent.entrypoints.api import main as persistent_main

        print("[local] Workbook attachments enabled; using the persistent Report Agent API.")
        print("[local] Start the attachment worker separately: scripts/start-local.ps1 workbook-worker")
        persistent_main()
        return

    event_bus = RunEventBus()
    repository = InMemoryRunRepository()

    # MinIO is optional: with it, export_parsed_md can publish a material_url;
    # without it the agent falls back to export_material_text.
    executor_artifact_service: Any | None = None
    api_artifact_service: Any = _NoArtifactService()
    try:
        from report_agent.infrastructure.artifacts import MinioArtifactService

        minio_service = MinioArtifactService(settings.persistence.minio, os.environ)
        executor_artifact_service = minio_service
        api_artifact_service = minio_service
    except Exception as exc:  # noqa: BLE001
        print(f"[inmem] MinIO unavailable, using stub: {type(exc).__name__}: {exc}")

    service = SynchronousRunService(
        workspace_root=Path(settings.service.workspace_root),
        executor=ConfiguredAgentExecutor(
            settings,
            artifact_service=executor_artifact_service,
            event_bus=event_bus,
        ),
        repository=repository,
        workspace_max_bytes=settings.service.workspace_max_mb * 1024 * 1024,
        max_upload_bytes=settings.service.max_upload_mb * 1024 * 1024,
        trace_max_chars=settings.service.dev_trace_max_chars,
        event_bus=event_bus,
    )

    def suggest_title(message: str) -> Awaitable[str]:
        return suggest_conversation_title(settings, os.environ, message)

    app = create_app(
        service,
        dev_ui_enabled=True,
        artifact_service=api_artifact_service,
        event_bus=event_bus,
        title_suggester=suggest_title,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
