"""Task-scoped workspace with explicit writable and protected areas."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4


class WorkspacePolicyError(ValueError):
    """Raised when a virtual path escapes or violates workspace policy."""


class WorkspaceQuotaExceeded(RuntimeError):
    """Raised before a write would exceed the task workspace quota."""


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    staged: bool


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    path: str
    kind: Literal["created", "modified", "deleted"]
    before_sha256: str | None
    after_sha256: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    files: dict[str, FileRecord]


class TaskWorkspace:
    """Maps a virtual ``/workspace`` tree to one task-owned host directory.

    This class is a filesystem policy boundary, not the production process
    sandbox. Phase 2 will place the same tree inside Bubblewrap.
    """

    DIRECTORIES = (
        "input",
        "working",
        "state",
        "memory",
        "references",
        "evidence",
        "report",
        "artifacts",
        "output",
        "staging",
        ".trash",
        "logs",
    )
    WRITABLE_AREAS = frozenset(
        {"working", "state", "memory", "report", "artifacts", "output", "staging", ".trash", "logs"}
    )
    PROTECTED_AREAS = frozenset({"input", "references", "evidence"})

    def __init__(self, root: Path, *, max_bytes: int = 2 * 1024 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        self._manifest_lock = threading.RLock()

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in self.DIRECTORIES:
            (self.root / name).mkdir(exist_ok=True)
        if not self.manifest_path.exists():
            with self._manifest_lock:
                if not self.manifest_path.exists():
                    self._write_manifest({"schema_version": "1.0", "files": {}, "trash": {}})

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def access_lock(self) -> Any:
        """Coordinate program metadata writes with this workspace's snapshots."""
        return self._manifest_lock

    def resolve(self, virtual_path: str, *, write: bool = False) -> Path:
        normalized = virtual_path.replace("\\", "/")
        path = PurePosixPath(normalized)
        parts = list(path.parts)
        if parts and parts[0] == "/":
            parts = parts[1:]
        if parts and parts[0] == "workspace":
            parts = parts[1:]
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise WorkspacePolicyError(f"invalid workspace path: {virtual_path}")
        area = parts[0]
        if area not in self.DIRECTORIES:
            raise WorkspacePolicyError(f"unknown workspace area: {area}")
        if write and area not in self.WRITABLE_AREAS:
            raise WorkspacePolicyError(f"workspace area is read-only: {area}")
        candidate = self.root.joinpath(*parts)
        resolved_parent = candidate.parent.resolve()
        if resolved_parent != self.root and self.root not in resolved_parent.parents:
            raise WorkspacePolicyError(f"path escapes workspace: {virtual_path}")
        self._reject_symlink_chain(candidate)
        return candidate

    def write_text(self, virtual_path: str, content: str) -> FileRecord:
        return self.write_bytes(virtual_path, content.encode("utf-8"))

    def write_bytes(self, virtual_path: str, content: bytes) -> FileRecord:
        target = self.resolve(virtual_path, write=True)
        with self._manifest_lock:
            self._ensure_capacity(len(content), replacing=target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)
            return self._record(target, staged=self._area(target) == "staging")

    def read_text(self, virtual_path: str) -> str:
        return self.resolve(virtual_path).read_text(encoding="utf-8")

    def read_bytes(self, virtual_path: str) -> bytes:
        return self.resolve(virtual_path).read_bytes()

    def append_text(self, virtual_path: str, content: str) -> FileRecord:
        target = self.resolve(virtual_path, write=True)
        encoded = content.encode("utf-8")
        self._ensure_capacity(
            (target.stat().st_size if target.exists() else 0) + len(encoded), replacing=target
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="") as stream:
            stream.write(content)
        return self._record(target, staged=self._area(target) == "staging")

    def stage(self, virtual_path: str) -> FileRecord:
        source = self.resolve(virtual_path)
        if self._area(source) != "output" or not source.is_file():
            raise WorkspacePolicyError("only output files can be staged")
        target = self.root / "staging" / source.relative_to(self.root / "output")
        self._ensure_capacity(source.stat().st_size, replacing=target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return self._record(target, staged=True)

    def import_artifact(
        self, area: Literal["input", "references", "evidence"], relative_path: str, content: bytes
    ) -> FileRecord:
        """Import trusted service data into an Agent read-only area."""
        if area not in self.PROTECTED_AREAS:
            raise WorkspacePolicyError("artifact imports must target a protected area")
        target = self.resolve(f"/workspace/{area}/{relative_path}")
        with self._manifest_lock:
            self._ensure_capacity(len(content), replacing=target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)
            return self._record(target, staged=False)

    def export_staged(self, virtual_path: str) -> bytes:
        """Export only a file explicitly copied into staging."""
        source = self.resolve(virtual_path)
        if self._area(source) != "staging" or not source.is_file():
            raise WorkspacePolicyError("only staged files can be exported")
        return source.read_bytes()

    def snapshot(self) -> WorkspaceSnapshot:
        with self._manifest_lock:
            return self._snapshot()

    def _snapshot(self) -> WorkspaceSnapshot:
        files: dict[str, FileRecord] = {}
        for area in self.DIRECTORIES:
            for path in sorted((self.root / area).rglob("*")):
                if path.is_symlink():
                    raise WorkspacePolicyError(f"symbolic links are not allowed: {path}")
                if path.is_file():
                    try:
                        raw = path.read_bytes()
                    except FileNotFoundError:
                        # A concurrent atomic writer can replace its temporary
                        # file after rglob enumerates it. It is absent from this
                        # snapshot, just like a concurrently removed file.
                        continue
                    virtual_path = self._virtual(path)
                    files[virtual_path] = FileRecord(
                        path=virtual_path,
                        size=len(raw),
                        sha256=hashlib.sha256(raw).hexdigest(),
                        staged=area == "staging",
                    )
        return WorkspaceSnapshot(files=files)

    def diff(self, baseline: WorkspaceSnapshot) -> tuple[WorkspaceChange, ...]:
        current = self.snapshot().files
        changes: list[WorkspaceChange] = []
        for path in sorted(set(baseline.files) | set(current)):
            before = baseline.files.get(path)
            after = current.get(path)
            if before is None and after is not None:
                changes.append(WorkspaceChange(path, "created", None, after.sha256))
            elif before is not None and after is None:
                changes.append(WorkspaceChange(path, "deleted", before.sha256, None))
            elif before is not None and after is not None and before.sha256 != after.sha256:
                changes.append(WorkspaceChange(path, "modified", before.sha256, after.sha256))
        return tuple(changes)

    def delete_to_trash(self, virtual_path: str) -> str:
        source = self.resolve(virtual_path, write=True)
        if not source.is_file():
            raise FileNotFoundError(source)
        trash_id = uuid4().hex
        target = self.root / ".trash" / f"{trash_id}-{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), target)
        with self._manifest_lock:
            manifest = self._read_manifest()
            manifest["trash"][trash_id] = {
                "original_path": self._virtual(source),
                "trash_path": self._virtual(target),
            }
            manifest["files"].pop(self._virtual(source), None)
            self._write_manifest(manifest)
        return trash_id

    def restore(self, trash_id: str) -> FileRecord:
        with self._manifest_lock:
            manifest = self._read_manifest()
            entry = manifest["trash"].get(trash_id)
            if not entry:
                raise KeyError(f"unknown trash id: {trash_id}")
            source = self.resolve(entry["trash_path"], write=True)
            target = self.resolve(entry["original_path"], write=True)
            self._ensure_capacity(source.stat().st_size, replacing=target, releasing=source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), target)
            manifest["trash"].pop(trash_id)
            self._write_manifest(manifest)
            return self._record(target, staged=self._area(target) == "staging")

    def _record(self, path: Path, *, staged: bool) -> FileRecord:
        raw = path.read_bytes()
        record = FileRecord(
            path=self._virtual(path),
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            staged=staged,
        )
        with self._manifest_lock:
            manifest = self._read_manifest()
            manifest["files"][record.path] = {
                "size": record.size,
                "sha256": record.sha256,
                "staged": staged,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self._write_manifest(manifest)
        return record

    def usage_bytes(self) -> int:
        return sum(record.size for record in self.snapshot().files.values())

    def _ensure_capacity(
        self, new_size: int, *, replacing: Path, releasing: Path | None = None
    ) -> None:
        replaced_size = replacing.stat().st_size if replacing.is_file() else 0
        released_size = (
            releasing.stat().st_size if releasing is not None and releasing.is_file() else 0
        )
        projected = self.usage_bytes() - replaced_size - released_size + new_size
        if projected > self.max_bytes:
            raise WorkspaceQuotaExceeded(
                f"workspace quota exceeded: projected={projected} limit={self.max_bytes}"
            )

    def _area(self, path: Path) -> str:
        return path.relative_to(self.root).parts[0]

    def _virtual(self, path: Path) -> str:
        return "/workspace/" + path.relative_to(self.root).as_posix()

    def _reject_symlink_chain(self, candidate: Path) -> None:
        current = self.root
        for part in candidate.relative_to(self.root).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise WorkspacePolicyError(f"symbolic links are not allowed: {current}")

    def _read_manifest(self) -> dict[str, Any]:
        text = self.manifest_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # Concurrent writers used to append a second closing fragment
            # onto a finished document. Keep the first object so the next
            # locked rewrite can replace the file with one document.
            if exc.msg != "Extra data":
                raise
            payload, _ = json.JSONDecoder().raw_decode(text)
        if not isinstance(payload, dict):
            raise WorkspacePolicyError("workspace manifest is not an object")
        return payload

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        temporary = self.manifest_path.with_name(f".manifest.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.manifest_path)
