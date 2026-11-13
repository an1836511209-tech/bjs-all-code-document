"""Dedicated, single-concurrency worker. Run separately from the report API."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from report_agent.application.institution_workbook.service import configured_service
from report_agent.application.one_pager_execution import execution_lock, write_json
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings import load_settings

logger = logging.getLogger(__name__)


async def serve(settings):
    service = configured_service(settings, os.environ, worker=True)
    control = TaskWorkspace(Path(settings.service.workspace_root) / ".institution-worker")
    control.initialize()
    with execution_lock(control, "institution-worker"):

        async def heartbeat():
            while True:
                await asyncio.to_thread(
                    write_json,
                    control,
                    "/workspace/state/heartbeat.json",
                    {"at": datetime.now(UTC).isoformat()},
                )
                await asyncio.sleep(5)

        beat = asyncio.create_task(heartbeat())
        try:
            while True:
                try:
                    await asyncio.to_thread(service.discover)
                    job = await asyncio.to_thread(
                        service.jobs.claim, settings.institution_workbook.total_timeout_seconds
                    )
                    if job:
                        await service.execute(job)
                    else:
                        await asyncio.sleep(2)
                except Exception as exc:
                    logger.warning("institution worker unavailable: %s", type(exc).__name__)
                    await asyncio.sleep(5)
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)


def main():
    settings = load_settings(Path(os.environ["REPORT_AGENT_CONFIG"]))
    if not settings.institution_workbook.enabled:
        raise SystemExit("institution_workbook.enabled is false")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
