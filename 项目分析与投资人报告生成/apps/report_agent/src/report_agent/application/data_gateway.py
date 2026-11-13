"""Contract-first gateway from the Agent to Data MCP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from report_agent.domain.events import AgentEvent, EventType
from report_agent.domain.evidence import EvidenceChunk, EvidenceView
from report_agent.domain.identifiers import RunIdentity
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.infrastructure.mcp import McpContractRegistry, McpTransport

if TYPE_CHECKING:
    from report_agent.application.context_store import WorkspaceContextStore


class DataMcpReadinessError(RuntimeError):
    """Raised when required configured tools are unavailable."""


class EventSink(Protocol):
    def append(self, event: AgentEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class McpReadiness:
    ready: bool
    available_tools: tuple[str, ...]
    missing_tools: tuple[str, ...]


class DataMcpGateway:
    def __init__(
        self,
        transport: McpTransport,
        contracts: McpContractRegistry,
        evidence_store: WorkspaceEvidenceStore,
        *,
        required: bool = True,
        audit: EventSink | None = None,
        identity: RunIdentity | None = None,
        context_store: WorkspaceContextStore | None = None,
        evidence_observer: Callable[[str, dict, Any], None] | None = None,
    ) -> None:
        self._transport = transport
        self._contracts = contracts
        self._evidence_store = evidence_store
        self._required = required
        if (audit is None) != (identity is None):
            raise ValueError("audit and identity must be provided together")
        self._audit = audit
        self._identity = identity
        self._context_store = context_store
        self._evidence_observer = evidence_observer

    @property
    def contracts(self) -> McpContractRegistry:
        return self._contracts

    async def readiness(self, required_tools: frozenset[str] | None = None) -> McpReadiness:
        available = tuple(sorted(set(await self._transport.list_tools())))
        expected = self._contracts.enabled_tools if required_tools is None else required_tools
        missing = tuple(sorted(expected - set(available)))
        readiness = McpReadiness(not missing, available, missing)
        if self._required and missing:
            raise DataMcpReadinessError(
                f"required Data MCP tools are missing: {', '.join(missing)}"
            )
        return readiness

    async def call(self, tool: str, arguments: dict[str, Any]) -> EvidenceView:
        self._emit(EventType.TOOL_STARTED, {"tool": tool, "provider": "data_mcp"})
        try:
            self._contracts.validate_input(tool, arguments)
            payload = await self._transport.call_tool(tool, arguments)
            self._contracts.validate_output(tool, payload)
            if tool == "search_company_web":
                # A web result is the only source whose age the reader cannot
                # judge from the document itself. Stamp the retrieval time onto
                # the evidence so the report can quote it.
                payload = {
                    **payload,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            record = self._evidence_store.put(tool, payload)
        except Exception as exc:
            self._emit(
                EventType.TOOL_FAILED,
                {"tool": tool, "provider": "data_mcp", "error_type": type(exc).__name__},
            )
            raise
        view = EvidenceView(
            evidence_id=record.evidence_id,
            tool=tool,
            status=payload["status"],
            summary=payload["summary"],
            warnings=tuple(payload["warnings"]),
            path=record.path,
            sha256=record.sha256,
            size_bytes=record.size,
            json_roots=tuple(
                f"/data/{str(key).replace('~', '~0').replace('/', '~1')}" for key in payload["data"]
            ),
        )
        if self._context_store is not None:
            self._context_store.record_evidence(record, json_roots=view.json_roots)
        if self._evidence_observer is not None:
            try:
                self._evidence_observer(tool, arguments, record)
            except Exception:
                pass  # Optional provenance cannot break the original data tool.
        self._emit(
            EventType.TOOL_COMPLETED,
            {
                "tool": tool,
                "provider": "data_mcp",
                "status": view.status,
                "evidence_id": view.evidence_id,
            },
        )
        self._emit(
            EventType.ARTIFACT_CREATED,
            {
                "artifact_type": "evidence",
                "tool": tool,
                "evidence_id": view.evidence_id,
                "path": record.path,
                "sha256": record.sha256,
            },
        )
        return view

    def read_evidence_chunk(
        self, evidence_id: str, *, offset: int = 0, limit: int = 12_000
    ) -> EvidenceChunk:
        return self._evidence_store.read_chunk(evidence_id, offset=offset, limit=limit)

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._audit is not None and self._identity is not None:
            self._audit.append(AgentEvent.create(event_type, self._identity, payload))
