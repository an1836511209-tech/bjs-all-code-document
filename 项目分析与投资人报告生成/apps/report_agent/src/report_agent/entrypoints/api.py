"""CLI entrypoint for the Report Agent HTTP API and developer page."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Awaitable
from pathlib import Path

import uvicorn

from report_agent.api import create_app
from report_agent.application.bootstrap import (
    ConfiguredAgentExecutor,
    suggest_conversation_title,
)
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.infrastructure.artifacts import MinioArtifactService
from report_agent.infrastructure.persistence import MySQLRunRepository, mysql_connection_factory
from report_agent.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Report Agent HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    raw_config_path = os.environ.get("REPORT_AGENT_CONFIG", "").strip()
    if not raw_config_path:
        raise SystemExit("REPORT_AGENT_CONFIG is required")
    config_path = Path(raw_config_path).expanduser()
    settings = load_settings(config_path)
    artifact_service = MinioArtifactService(settings.persistence.minio, os.environ)
    repository = MySQLRunRepository(
        mysql_connection_factory(settings.persistence.mysql, os.environ)
    )
    event_bus = RunEventBus()
    service = SynchronousRunService(
        workspace_root=Path(settings.service.workspace_root),
        executor=ConfiguredAgentExecutor(
            settings, artifact_service=artifact_service, event_bus=event_bus
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
        dev_ui_enabled=settings.service.dev_ui_enabled,
        artifact_service=artifact_service,
        event_bus=event_bus,
        title_suggester=suggest_title,
        institution_workbook_service=_workbook_service(settings),
    )
    uvicorn.run(app, host=args.host, port=args.port)


def _workbook_service(settings):
    if not settings.institution_workbook.enabled:
        return None
    from report_agent.application.institution_workbook.service import configured_service
    try:
        return configured_service(settings,os.environ)
    except Exception as exc:
        # Optional transport/contracts/credentials must not become startup requirements.
        logging.getLogger(__name__).warning("optional workbook initialization failed: %s", type(exc).__name__)
        return None


if __name__ == "__main__":
    main()
