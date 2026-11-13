"""中止一个停在提问上的任务：待答问题必须被清掉，否则前端每次重载都重新弹卡片。"""

from __future__ import annotations

from pathlib import Path

import pytest

from report_agent.application.interactions import read_interaction, update_interaction
from report_agent.application.runs import SynchronousRunService
from report_agent.runtime.workspace import TaskWorkspace

TASK_ID = "task_" + "a" * 32


class _Repository:
    def __init__(self) -> None:
        self.failed: list[tuple[str, str]] = []

    def fail(self, identity, reason: str) -> None:  # noqa: ANN001
        self.failed.append((getattr(identity, "run_id", ""), reason))


@pytest.fixture()
def service(tmp_path: Path) -> SynchronousRunService:
    return SynchronousRunService(
        workspace_root=tmp_path,
        executor=object(),  # type: ignore[arg-type]
        repository=_Repository(),  # type: ignore[arg-type]
    )


@pytest.fixture()
def waiting_task(tmp_path: Path) -> TaskWorkspace:
    workspace = TaskWorkspace(tmp_path / TASK_ID)
    workspace.initialize()
    update_interaction(
        workspace,
        status="needs_input",
        run_id="run_x",
        session_id="session_x",
        workspace_id="workspace_x",
        pending_question={"question_id": "q1", "question": "要不要继续？"},
    )
    return workspace


def test_cancel_task_clears_the_pending_question(service, waiting_task):
    assert service.cancel_task(TASK_ID) is True

    interaction = read_interaction(waiting_task)
    assert interaction.get("pending_question") in (None, {})
    assert interaction.get("status") == "cancelled"
    # The console also reads the run record, so it must be marked failed.
    assert service.repository.failed and service.repository.failed[0][1] == "CancelledError"


def test_cancel_task_is_not_repeatable(service, waiting_task):
    assert service.cancel_task(TASK_ID) is True
    assert service.cancel_task(TASK_ID) is False


def test_cancel_task_ignores_a_completed_task(service, tmp_path):
    workspace = TaskWorkspace(tmp_path / TASK_ID)
    workspace.initialize()
    update_interaction(workspace, status="completed", pending_question=None)
    assert service.cancel_task(TASK_ID) is False


def test_cancel_task_ignores_a_missing_task(service):
    assert service.cancel_task("task_" + "b" * 32) is False
