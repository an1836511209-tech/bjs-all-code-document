"""Evidence references returned to the Agent instead of raw MCP payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

McpStatus = Literal["success", "partial", "empty", "failed"]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    tool: str
    status: McpStatus
    summary: str
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class EvidenceView:
    evidence_id: str
    tool: str
    status: McpStatus
    summary: str
    warnings: tuple[dict[str, Any], ...]
    path: str
    sha256: str
    size_bytes: int
    json_roots: tuple[str, ...]
    next_actions: tuple[str, ...] = ("read_evidence_pack", "read_evidence")


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    evidence_id: str
    offset: int
    content: str
    next_offset: int | None
    total_chars: int
