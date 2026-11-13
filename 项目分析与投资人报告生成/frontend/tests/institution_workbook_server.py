"""Local browser fixture: real export coordinator/XLSX, isolated in-memory external IO."""

import asyncio
import io
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from docx import Document
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path("apps/report_agent/tests/unit").resolve()))
from report_agent.api.app import create_app
from report_agent.application.event_bus import RunEventBus
from report_agent.application.institution_workbook.service import (
    InstitutionWorkbookService,
)
from report_agent.application.interactions import read_interaction
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.events import EventType
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from test_institution_workbook import (
    MemoryJobs,
    Publisher,
    build_context,
    settings,
    workbook_payload,
)

root = Path(
    tempfile.mkdtemp(prefix="workbook-browser-", dir=Path(".runtime/diagnostics"))
)
runs = InMemoryRunRepository()
jobs = MemoryJobs(runs)
publisher = Publisher()
bus = RunEventBus()
failures = set()
calls = []
requests = []


async def executor(identity, workspace, message, *, selected_skill=""):
    if read_interaction(workspace).get("institution_workbook"):
        build_context(root, identity=identity, matched_tags=["速冻食品制造"])
    document = Document()
    document.add_paragraph(message)
    stream = io.BytesIO()
    document.save(stream)
    key = f"{identity.task_id}/word.docx"
    publisher.objects[key] = stream.getvalue()
    import hashlib

    artifact = PublishedArtifact(
        artifact_id="artifact_" + identity.run_id.removeprefix("run_"),
        filename=message + ".docx",
        sha256=hashlib.sha256(stream.getvalue()).hexdigest(),
        size=len(stream.getvalue()),
        bucket="test",
        object_key=key,
        download_url="https://unused.test",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    if "附件失败" in message:
        failures.add(identity.task_id)
    bus.emit(identity, EventType.SKILL_ACTIVATED, {"skill": "one-pager"})
    bus.emit(
        identity,
        EventType.ARTIFACT_CREATED,
        {**artifact.model_dump(mode="json"), "size_bytes": artifact.size},
    )
    return {
        "messages": [AIMessage(content="已交付")],
        "skill_name": "one-pager",
        "artifacts": [artifact.model_dump(mode="json")],
    }


class Transport:
    async def call_tool(self, name, arguments):
        calls.append(name)
        requests.append({"name": name, "arguments": arguments})
        await asyncio.sleep(1.5)
        running = next(j for j in jobs.rows.values() if j["status"] == "running")
        if name == "query_track_labels":
            return {
                "schema_version": "1.0",
                "tool": name,
                "status": "partial",
                "summary": "更新完成",
                "data": {"tags": ["其他食品制造", "互联网零售"]},
                "sources": [],
                "warnings": [],
            }
        if running["task_id"] in failures:
            failures.remove(running["task_id"])
            raise RuntimeError("synthetic DMP failure")
        return workbook_payload(arguments["track_tags"])


optional = InstitutionWorkbookService(
    settings(), root, runs, jobs, transport=Transport(), publisher=publisher
)
service = SynchronousRunService(root, executor, runs, event_bus=bus)
app = create_app(
    service,
    dev_ui_enabled=True,
    event_bus=bus,
    artifact_service=publisher,
    institution_workbook_service=optional,
)


@app.get("/qa/stats")
async def stats():
    return {"calls": calls, "requests": requests, "jobs": list(jobs.rows.values())}


async def worker():
    while True:
        # The production worker scans completed markers; skip its ten-second grace in this fixture.
        for run in list(runs._runs.values()):
            workspace = root / run.task_id
            marker = (
                workspace / "state/institution-workbook/requests" / f"{run.run_id}.json"
            )
            if (
                run.status != "completed"
                or not marker.exists()
                or any(j["origin_run_id"] == run.run_id for j in jobs.rows.values())
            ):
                continue
            context = optional._context(run.task_id)
            job = optional._new_job(
                run.task_id, run.run_id, run.artifacts[0].artifact_id, context, "auto"
            )
            jobs.enqueue(job)
        job = jobs.claim(120)
        if job:
            await optional.execute(job)
        await asyncio.sleep(0.1)


from contextlib import asynccontextmanager

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        task = asyncio.create_task(worker())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app.router.lifespan_context = lifespan
uvicorn.run(app, host="127.0.0.1", port=8024, log_level="warning")
