"""Identifiers that keep business tasks, sessions and executions separate."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Stable identity bundle passed through the Agent runtime."""

    task_id: str
    session_id: str
    run_id: str
    workspace_id: str

    @classmethod
    def create(cls) -> RunIdentity:
        return cls.for_task(_new_id("task"))

    @classmethod
    def for_task(cls, task_id: str) -> RunIdentity:
        """Continue an existing sandbox with a fresh run id.

        会话里的追问（回答 ``ask_user``、补充材料）必须复用同一个
        ``task_id``，否则新 run 会拿到一个空 workspace，看不到已上传的材料
        和已落盘的证据。``session_id`` / ``workspace_id`` 由 ``task_id``
        派生，保证同一沙箱的三个标识稳定可追。
        """
        suffix = task_id.removeprefix("task_") or uuid4().hex
        return cls(
            task_id=task_id,
            session_id=f"session_{suffix}",
            run_id=_new_id("run"),
            workspace_id=f"workspace_{suffix}",
        )
