"""Task-scoped immutable evidence storage."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from report_agent.domain.evidence import EvidenceChunk, EvidenceRecord
from report_agent.runtime.workspace import TaskWorkspace

EVIDENCE_ID = re.compile(r"^evidence_[a-f0-9]{32}$")


class WorkspaceEvidenceStore:
    def __init__(self, workspace: TaskWorkspace) -> None:
        self._workspace = workspace

    def put(self, tool: str, payload: dict[str, Any]) -> EvidenceRecord:
        evidence_id = f"evidence_{uuid4().hex}"
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        file_record = self._workspace.import_artifact(
            "evidence", f"{evidence_id}.json", serialized.encode("utf-8")
        )
        return EvidenceRecord(
            evidence_id=evidence_id,
            tool=tool,
            status=payload["status"],
            summary=payload["summary"],
            path=file_record.path,
            sha256=file_record.sha256,
            size=file_record.size,
        )

    def read_chunk(
        self, evidence_id: str, *, offset: int = 0, limit: int = 12_000
    ) -> EvidenceChunk:
        if not EVIDENCE_ID.fullmatch(evidence_id):
            raise ValueError("invalid evidence_id")
        if offset < 0 or limit < 1 or limit > 100_000:
            raise ValueError("invalid evidence chunk range")
        content = self._workspace.read_text(f"/workspace/evidence/{evidence_id}.json")
        end = min(len(content), offset + limit)
        return EvidenceChunk(
            evidence_id=evidence_id,
            offset=offset,
            content=content[offset:end],
            next_offset=end if end < len(content) else None,
            total_chars=len(content),
        )

    def get(self, evidence_id: str) -> dict[str, Any]:
        if not EVIDENCE_ID.fullmatch(evidence_id):
            raise ValueError("invalid evidence_id")
        return json.loads(self._workspace.read_text(f"/workspace/evidence/{evidence_id}.json"))

    def tool_for(self, evidence_id: str) -> str:
        """Return the MCP tool that produced *evidence_id* (``""`` when unknown).

        Read from ``evidence/index.json``; used to stamp the provenance marker
        (``<!-- src: mcp match_listed_peers /data/peers/6 ; ... -->``) so the
        Word comment can be generated while writing instead of afterwards.
        """
        index_path = "/workspace/evidence/index.json"
        try:
            index = json.loads(self._workspace.read_text(index_path))
        except Exception:  # noqa: BLE001 - index is optional for old workspaces
            return ""
        record = (index.get("evidence") or {}).get(evidence_id)
        if not isinstance(record, dict):
            return ""
        return str(record.get("tool") or "")

    def list_pointers(
        self, evidence_id: str, *, prefix: str = "/data", max_depth: int = 3
    ) -> tuple[str, ...]:
        if max_depth < 0 or max_depth > 8:
            raise ValueError("max_depth must be between 0 and 8")
        root = self.get(evidence_id)
        value = self._resolve_pointer(root, prefix)
        pointers: list[str] = []

        def walk(current: Any, pointer: str, depth: int) -> None:
            pointers.append(pointer or "/")
            if depth >= max_depth:
                return
            if isinstance(current, dict):
                for key, child in current.items():
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    walk(child, f"{pointer}/{escaped}", depth + 1)
            elif isinstance(current, list):
                for index, child in enumerate(current[:100]):
                    walk(child, f"{pointer}/{index}", depth + 1)

        walk(value, prefix.rstrip("/"), 0)
        return tuple(pointers)

    def read_pointer(self, evidence_id: str, pointer: str) -> Any:
        return self._resolve_pointer(self.get(evidence_id), pointer)

    def search(
        self, evidence_id: str, query: str, *, regex: bool = False, limit: int = 20
    ) -> tuple[dict[str, Any], ...]:
        if not query or limit < 1 or limit > 100:
            raise ValueError("query is required and limit must be between 1 and 100")
        pattern = re.compile(query) if regex else None
        results: list[dict[str, Any]] = []

        def walk(value: Any, pointer: str) -> None:
            if len(results) >= limit:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    walk(child, f"{pointer}/{escaped}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{pointer}/{index}")
            else:
                text = str(value)
                matched = bool(pattern.search(text)) if pattern else query in text
                if matched:
                    results.append({"pointer": pointer or "/", "value": value})

        walk(self.get(evidence_id), "")
        return tuple(results)

    @staticmethod
    def _resolve_pointer(root: Any, pointer: str) -> Any:
        if pointer in {"", "/"}:
            return root
        if not pointer.startswith("/"):
            raise ValueError("JSON pointer must start with /")
        current = root
        for raw in pointer[1:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                if token not in current:
                    raise KeyError(f"JSON pointer not found: {pointer}")
                current = current[token]
            elif isinstance(current, list):
                try:
                    current = current[int(token)]
                except (ValueError, IndexError) as exc:
                    raise KeyError(f"JSON pointer not found: {pointer}") from exc
            else:
                raise KeyError(f"JSON pointer not found: {pointer}")
        return current
