"""Async submit (scheme A): accept immediately, finish in background."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from report_agent.api.app import (
    CONSOLE_PAGE_PATH,
    CONSOLE_PUBLIC_PATH,
    INVESTMENT_PAGE_PATH,
    INVESTMENT_PAGE_PREFIX,
    INVESTMENT_PUBLIC_PATH,
    create_app,
)
from report_agent.application.runs import SynchronousRunService, UploadedMaterial
from report_agent.domain.identifiers import RunIdentity
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace


def _artifact_payload() -> dict:
    return {
        "artifact_id": "artifact_" + ("a" * 32),
        "filename": "report.docx",
        "sha256": "b" * 64,
        "size": 12,
        "download_url": "https://example.test/report.docx",
        "bucket": "reports",
        "object_key": "reports/report.docx",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }


@pytest.mark.asyncio
async def test_submit_returns_running_before_executor_finishes(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_executor(
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
    ) -> dict:
        started.set()
        await release.wait()
        return {"messages": [], "artifacts": [_artifact_payload()]}

    service = SynchronousRunService(
        workspace_root=tmp_path / "workspaces",
        executor=slow_executor,
        repository=InMemoryRunRepository(),
    )
    accepted = await service.submit("请生成报告", [])
    assert accepted.status == "running"
    assert accepted.task_id.startswith("task_")
    assert accepted.run_id.startswith("run_")
    assert service.repository.get_run(accepted.run_id).status == "running"

    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert service.repository.get_run(accepted.run_id).status == "running"

    release.set()
    await service.drain()
    stored = service.repository.get_run(accepted.run_id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.artifacts


@pytest.mark.asyncio
async def test_submit_records_failed_when_executor_raises(tmp_path: Path) -> None:
    async def boom_executor(
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
    ) -> dict:
        raise RuntimeError("executor exploded")

    service = SynchronousRunService(
        workspace_root=tmp_path / "workspaces",
        executor=boom_executor,
        repository=InMemoryRunRepository(),
    )
    accepted = await service.submit("please fail", [UploadedMaterial(filename="a.txt", content=b"x")])
    await service.drain()
    stored = service.repository.get_run(accepted.run_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_type == "RuntimeError"


@pytest.mark.asyncio
async def test_dev_runs_api_returns_202_and_completes_via_poll(tmp_path: Path) -> None:
    async def quick_executor(
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
    ) -> dict:
        await asyncio.sleep(0.05)
        return {"messages": [], "artifacts": [_artifact_payload()]}

    service = SynchronousRunService(
        workspace_root=tmp_path / "workspaces",
        executor=quick_executor,
        repository=InMemoryRunRepository(),
    )
    app = create_app(service, dev_ui_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/dev/runs", data={"message": "异步生成"})
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "running"
        run_id = body["run_id"]
        task_id = body["task_id"]

        await service.drain()

        run = await client.get(f"/api/runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "completed"

        task = await client.get(f"/api/tasks/{task_id}")
        assert task.status_code == 200
        assert task.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_encrypted_console_entry_and_prefixed_api(tmp_path: Path) -> None:
    async def unused(
        identity: RunIdentity, workspace: TaskWorkspace, message: str
    ) -> dict:
        return {"messages": []}

    service = SynchronousRunService(
        workspace_root=tmp_path / "workspaces",
        executor=unused,
        repository=InMemoryRunRepository(),
    )
    app = create_app(service, dev_ui_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Old encrypted bookmark redirects into the console under the same prefix.
        legacy = await client.get(INVESTMENT_PAGE_PATH, follow_redirects=False)
        assert legacy.status_code == 307
        assert legacy.headers["location"] == CONSOLE_PAGE_PATH

        console = await client.get(CONSOLE_PAGE_PATH)
        assert console.status_code == 200
        assert "bjsConsolePrefix" in console.text
        assert "history.replaceState" in console.text
        # Copied address-bar path (no opaque prefix) must not reopen the page.
        assert (await client.get(CONSOLE_PUBLIC_PATH)).status_code == 404
        assert (await client.get("/console/")).status_code == 404
        # Relative assets after replaceState still load on the public path.
        assets = await client.get(f"{CONSOLE_PUBLIC_PATH.rstrip('/')}/assets/modules/10-run.js")
        assert assets.status_code == 200

        submitted = await client.post(
            f"{INVESTMENT_PAGE_PREFIX}/api/dev/runs",
            data={"message": "对外提交"},
        )
        assert submitted.status_code == 202
        await service.drain()
        polled = await client.get(
            f"{INVESTMENT_PAGE_PREFIX}/api/runs/{submitted.json()['run_id']}"
        )
        assert polled.status_code == 200
        assert (await client.get(INVESTMENT_PUBLIC_PATH)).status_code == 404
        dev = await client.get("/dev")
        assert dev.status_code == 200
        assert "bjsInvestmentPrefix" in dev.text
        assert "POLL_MS=5000" in dev.text

    disabled = create_app(service, dev_ui_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=disabled), base_url="http://test") as client:
        assert (await client.get(INVESTMENT_PAGE_PATH, follow_redirects=False)).status_code == 404
        assert (await client.get(INVESTMENT_PUBLIC_PATH)).status_code == 404
        assert (await client.get("/dev")).status_code == 404
        # Console HTML is not gated by dev_ui_enabled, but still needs the prefix.
        assert (await client.get(CONSOLE_PAGE_PATH)).status_code == 200
        assert (await client.get(CONSOLE_PUBLIC_PATH)).status_code == 404


class _ObjectReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.seen: tuple[str, str] | None = None

    def read_object(self, bucket: str, object_key: str) -> bytes:
        self.seen = (bucket, object_key)
        return self.payload


@pytest.mark.asyncio
async def test_investment_page_downloads_artifact_through_agent(tmp_path: Path) -> None:
    async def executor(
        identity: RunIdentity, workspace: TaskWorkspace, message: str, *, selected_skill: str = ""
    ) -> dict:
        return {"messages": [], "artifacts": [_artifact_payload()]}

    service = SynchronousRunService(
        workspace_root=tmp_path / "workspaces",
        executor=executor,
        repository=InMemoryRunRepository(),
    )
    reader = _ObjectReader(b"word-bytes")
    app = create_app(service, dev_ui_enabled=True, artifact_service=reader)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get(CONSOLE_PAGE_PATH)
        assert page.status_code == 200
        assert "bjsConsolePrefix" in page.text
        accepted = await client.post(
            f"{INVESTMENT_PAGE_PREFIX}/api/dev/runs",
            data={"message": "生成报告"},
        )
        assert accepted.status_code == 202
        await service.drain()
        artifact_id = _artifact_payload()["artifact_id"]
        downloaded = await client.get(
            f"{INVESTMENT_PAGE_PREFIX}/api/artifacts/{artifact_id}/content"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"word-bytes"
        assert downloaded.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "attachment" in downloaded.headers["content-disposition"]
        assert reader.seen == ("reports", "reports/report.docx")
        missing = await client.get(
            f"{INVESTMENT_PAGE_PREFIX}/api/artifacts/artifact_{'c' * 32}/content"
        )
        assert missing.status_code == 404

    disabled = create_app(service, dev_ui_enabled=False, artifact_service=reader)
    async with AsyncClient(transport=ASGITransport(app=disabled), base_url="http://test") as client:
        denied = await client.get(
            f"{INVESTMENT_PAGE_PREFIX}/api/artifacts/{_artifact_payload()['artifact_id']}/content"
        )
        assert denied.status_code == 404
