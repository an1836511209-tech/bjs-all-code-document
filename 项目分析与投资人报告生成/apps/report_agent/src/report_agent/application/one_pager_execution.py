"""One-pager-only durable execution metadata and single-host exclusion."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from report_agent.runtime.workspace import TaskWorkspace

VERSION = "one-pager-checkpoint-v1"
STATE_PATH = "/workspace/state/one-pager-execution.json"
COMMAND_PATH = "/workspace/state/one-pager-command.json"


def read_json(workspace: TaskWorkspace, path: str) -> dict[str, Any]:
    target = workspace.resolve(path)
    if not target.exists():
        return {}
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid execution metadata: {path}")
    return value


def write_json(workspace: TaskWorkspace, path: str, value: dict[str, Any]) -> None:
    """Replace atomically; a process crash must not leave half a command."""
    with workspace.access_lock:
        _write_json(workspace, path, value)


def _write_json(workspace: TaskWorkspace, path: str, value: dict[str, Any]) -> None:
    target = workspace.resolve(path, write=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".checkpoint-", delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def execution_state(workspace: TaskWorkspace) -> dict[str, Any]:
    state = read_json(workspace, STATE_PATH)
    if state and state.get("version") != VERSION:
        raise ValueError("一页纸执行检查点版本不兼容，请使用对应版本服务恢复")
    return state


@contextmanager
def execution_lock(workspace: TaskWorkspace, name: str = "execution"):
    """OS-owned lock, released on process death. Requires one shared volume."""
    # Windows byte-range locks deny reads of the locked byte. Control locks
    # belong outside the data areas scanned by snapshots and quota checks.
    target = workspace.root / f".one-pager-{name}.lock"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+b") as handle:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            if target.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("当前一页纸任务正在执行，请稍后重试") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("当前一页纸任务正在执行，请稍后重试") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
