"""Append-only agent I/O logger for developer observability.

Captures every model call and every tool call (not only Data MCP) into a
per-run ``/workspace/logs/agent.ndjson`` file so the developer API and dev UI
can show exactly what was sent to the model and what came back. This is the
only place in the runtime that records model inputs and outputs end-to-end.

Design notes:

- Persistence is the workspace filesystem, mirroring ``audit.ndjson``. No
  host-level logging is added to keep cross-run isolation trivial.
- Field names matching ``authorization|api_key|password|secret|token|credential``
  (case-insensitive) have their values redacted to ``[REDACTED]`` so secrets
  that leak through tool args (e.g. ``Authorization`` headers) never reach
  disk.
- The middleware never throws on logging failure: log noise must not break
  the agent loop. Errors are reported by silently dropping the entry, which
  is consistent with how ``WorkspaceAuditLog`` operates.
- Output is **not** truncated per the developer UI contract; the developer
  API paginates by line and the dev UI renders each line in its own block.
- The first line per run is a ``session_start`` record carrying the full
  ``system_prompt`` and tool list. Every ``model_call`` records the complete
  final message payload plus a deterministic fingerprint. This deliberately
  favors diagnostic truth over compact incremental logging.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.types import Command

from report_agent.runtime.workspace import TaskWorkspace

SECRET_KEY = re.compile(r"(authorization|api.?key|password|secret|token|credential)", re.I)

#: Token *counts* are telemetry, not secrets. The blanket ``token`` rule used to
#: redact ``input_tokens`` / ``output_tokens`` to ``[REDACTED]``, which left the
#: console with no way to show how full the context window was.
TELEMETRY_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_token_details",
        "output_token_details",
        "reasoning_tokens",
    }
)


def _is_secret(key: object) -> bool:
    name = str(key)
    return name not in TELEMETRY_KEYS and bool(SECRET_KEY.search(name))


class AgentCallLoggerMiddleware(AgentMiddleware[Any, Any, Any]):
    """Persist every model/tool call input and output to ``agent.ndjson``."""

    LOG_PATH = "/workspace/logs/agent.ndjson"

    def __init__(
        self, workspace: TaskWorkspace, *, run_id: str = "", task_id: str = ""
    ) -> None:
        self._workspace = workspace
        self._run_id = str(run_id)
        self._task_id = str(task_id) or getattr(workspace.root, "name", "")
        self._lock = threading.Lock()
        self._sequence = 0
        #: How many messages the previous call already logged, so each line only
        #: carries the new ones (see ``_capture_model_input``).
        self._logged_message_count = 0
        self._session_started = False
        self._system_prompt_sha256: str | None = None
        self._tools_sha256: str | None = None

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any]:
        self._ensure_session_start(request)
        sequence = self._next_sequence()
        started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        input_payload = self._capture_model_input(request)
        try:
            response = await handler(request)
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._write(
                {
                    "kind": "model_call",
                    "sequence": sequence,
                    "started_at": started_at,
                    "elapsed_seconds": elapsed,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "input": input_payload,
                    "output": {"error": _bounded_text(str(exc))},
                }
            )
            raise
        elapsed = time.monotonic() - started
        output_payload = self._capture_model_output(response)
        anomaly = output_payload.get("anomaly")
        status = "warning" if anomaly else "completed"
        self._write(
            {
                "kind": "model_call",
                "sequence": sequence,
                "started_at": started_at,
                "elapsed_seconds": elapsed,
                "status": status,
                "anomaly": anomaly,
                "input": input_payload,
                "output": output_payload,
            }
        )
        return response

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        sequence = self._next_sequence()
        started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", "unknown"))
        tool_args = _redact(tool_call.get("args", {}))
        input_payload = {"tool": tool_name, "args": tool_args}
        try:
            result = await handler(request)
        except Exception as exc:
            elapsed = time.monotonic() - started
            self._write(
                {
                    "kind": "tool_call",
                    "sequence": sequence,
                    "started_at": started_at,
                    "elapsed_seconds": elapsed,
                    "status": "error",
                    "input": input_payload,
                    "output": {
                        "error_type": type(exc).__name__,
                        "error": _bounded_text(str(exc)),
                    },
                }
            )
            raise
        elapsed = time.monotonic() - started
        output_payload = _redact(_serialize_tool_output(result))
        self._write(
            {
                "kind": "tool_call",
                "sequence": sequence,
                "started_at": started_at,
                "elapsed_seconds": elapsed,
                "status": "completed",
                "input": input_payload,
                "output": output_payload,
            }
        )
        return result

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def _ensure_session_start(self, request: ModelRequest[Any]) -> None:
        """Emit a ``session_start`` line once per run with full prompt + tools."""
        if self._session_started:
            return
        system_prompt = request.system_prompt or ""
        self._system_prompt_sha256 = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        tool_names = tuple(_extract_tool_name(tool) for tool in (request.tools or []))
        self._tools_sha256 = hashlib.sha256("|".join(tool_names).encode("utf-8")).hexdigest()
        self._write(
            {
                "kind": "session_start",
                "sequence": self._next_sequence(),
                "started_at": datetime.now(UTC).isoformat(),
                "system_prompt": _redact(system_prompt),
                "system_prompt_sha256": self._system_prompt_sha256,
                "system_prompt_chars": len(system_prompt),
                "tools": [{"name": name} for name in tool_names],
                "tools_count": len(tool_names),
                "tools_sha256": self._tools_sha256,
            }
        )
        self._session_started = True

    def _capture_model_input(self, request: ModelRequest[Any]) -> dict[str, Any]:
        messages = list(request.messages or [])
        system_prompt = request.system_prompt or ""
        current_system_prompt_sha256 = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        # Log only the messages added since the previous call.
        #
        # Writing the whole history every time made this O(n²): one real
        # investment report produced 75 lines / 3.5 MB, with a single line at
        # 131 KB. That is not just size — hitting the workspace quota silently
        # stops logging exactly when a long run needs it most. `messages_count`
        # and `payload_sha256` still describe the full request, so the delta is
        # enough to reconstruct what changed.
        delta = messages[self._logged_message_count :]
        if len(messages) < self._logged_message_count:
            delta = messages  # history was rebuilt (compression): log it all again
        self._logged_message_count = len(messages)
        serialized = [_redact(_serialize_message(message)) for message in delta]
        canonical = json.dumps(
            {
                "system_prompt": _bounded_text(_redact(request.system_prompt or "")),
                "tools": [_extract_tool_name(tool) for tool in (request.tools or [])],
                "messages": serialized,
                "tool_choice": _redact(request.tool_choice),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return {
            "system_prompt_sha256": current_system_prompt_sha256,
            "system_prompt_changed": current_system_prompt_sha256 != self._system_prompt_sha256,
            "system_prompt_chars": len(system_prompt),
            "tools_sha256": self._tools_sha256,
            "tools_count": len(request.tools or []),
            "messages_count": len(messages),
            "messages_logged": len(delta),
            "message_types": [str(item.get("type", "unknown")) for item in serialized],
            "messages": serialized,
            "tool_choice": _redact(request.tool_choice),
            "payload_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    def _capture_model_output(self, response: ModelCallResult[Any]) -> dict[str, Any]:
        messages: list[BaseMessage]
        if isinstance(response, AIMessage):
            messages = [response]
        elif isinstance(response, ModelRequest):  # defensive; should not happen
            messages = []
        elif hasattr(response, "model_response"):
            messages = list(getattr(response.model_response, "result", []) or [])
        elif hasattr(response, "result"):
            messages = list(getattr(response, "result", []) or [])
        else:
            messages = []
        has_tool_calls = any(
            isinstance(message, AIMessage) and bool(message.tool_calls) for message in messages
        )
        stop_reason = _extract_stop_reason(messages)
        anomaly = _detect_anomaly(messages, has_tool_calls, stop_reason)
        return {
            "messages": [_redact(_serialize_message(message)) for message in messages],
            "has_tool_calls": has_tool_calls,
            "stop_reason": stop_reason,
            "anomaly": anomaly,
        }

    def _write(self, payload: dict[str, Any]) -> None:
        # Every line carries the run identity. Without it `agent.ndjson`,
        # `events.ndjson` and the audit trail cannot be joined at all — a
        # multi-round conversation reuses the same files.
        enriched = {
            "run_id": self._run_id,
            "task_id": self._task_id,
            **payload,
            "logged_at": datetime.now(UTC).isoformat(),
        }
        line = json.dumps(_redact(enriched), ensure_ascii=False, default=str)
        try:
            self._workspace.append_text(self.LOG_PATH, line + "\n")
        except Exception:
            # Logging must never break the agent loop. The workspace error
            # will surface through normal run-failure channels if quota is
            # exceeded; dropping a single log line is the safe fallback.
            return


def _serialize_message(message: BaseMessage) -> dict[str, Any]:
    """Flatten a LangChain message into a JSON-safe dict preserving content."""
    kind = getattr(message, "type", message.__class__.__name__)
    payload: dict[str, Any] = {
        "type": kind,
        "content": _coerce_content(getattr(message, "content", "")),
    }
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": str(call.get("id", "")),
                "name": str(call.get("name", "")),
                "args": call.get("args", {}),
            }
            for call in tool_calls
        ]
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = str(getattr(message, "tool_call_id", ""))
        payload["name"] = str(getattr(message, "name", "") or "")
        payload["status"] = str(getattr(message, "status", "") or "")
    response_metadata = getattr(message, "response_metadata", None)
    if response_metadata:
        payload["response_metadata"] = response_metadata
    usage_metadata = getattr(message, "usage_metadata", None)
    if usage_metadata:
        payload["usage_metadata"] = usage_metadata
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if additional_kwargs:
        payload["additional_kwargs"] = additional_kwargs
    return payload


def _extract_tool_name(tool: Any) -> str:
    """Return the name of a tool-like object (BaseTool, dict, or callable)."""
    name = getattr(tool, "name", None)
    if not name and isinstance(tool, dict):
        name = tool.get("name")
    return str(name) if name else "unknown"


def _serialize_tool_output(result: ToolMessage | Command[Any]) -> dict[str, Any]:
    if isinstance(result, ToolMessage):
        return {
            "type": "tool",
            "name": str(result.name or ""),
            "tool_call_id": str(result.tool_call_id),
            "content": _coerce_content(result.content),
            "status": str(result.status or ""),
        }
    if isinstance(result, Command):
        return {
            "type": "command",
            "update": _coerce_content(getattr(result, "update", None)),
        }
    return {"type": "unknown", "content": _coerce_content(result)}


def _coerce_content(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_content(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _coerce_content(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _extract_stop_reason(messages: list[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        metadata = getattr(message, "response_metadata", {}) or {}
        stop = metadata.get("stop_reason") or metadata.get("finish_reason")
        if stop:
            return str(stop)
        if message.tool_calls:
            return "tool_calls"
        return "stop"
    return None


def _detect_anomaly(
    messages: list[BaseMessage],
    has_tool_calls: bool,
    stop_reason: str | None,
) -> str | None:
    """Flag a degenerate response that would silently end the agent loop.

    The condition mirrors ``EmptyToolCallsGuardMiddleware``: the model reported
    ``finish_reason="tool_calls"`` but emitted no ``tool_call`` and produced no
    text content. Without the guard, LangGraph ends the run at this point and
    downstream phases (e.g. report production) are never reached. Marking the
    event here makes it visible in the agent log and the dev UI.
    """
    if has_tool_calls or stop_reason != "tool_calls":
        return None
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        content = message.content
        if isinstance(content, str):
            return "empty_tool_calls" if not content.strip() else None
        if isinstance(content, list):
            text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return "empty_tool_calls" if not text.strip() else None
        # Non-string, non-list content is not "empty".
        return None
    return None


#: Credential-bearing query parameters that live *inside* strings — presigned
#: object-storage URLs are the common case. A dict-key check cannot see them,
#: which is how 53 working `admin` AccessKey URLs ended up in plain text in a
#: real run's log while `[REDACTED]` appeared zero times.
_SECRET_QUERY = (
    "X-Amz-Signature",
    "X-Amz-Credential",
    "X-Amz-Security-Token",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "Signature",
    "signature",
    "access_token",
    "access_key",
    "secret_key",
    "SecretKey",
    "token",
    "password",
    "passwd",
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(name) for name in _SECRET_QUERY) + r")=([^&\s\"'<>]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._\-]{8,})")


def _redact_text(text: str) -> str:
    """Scrub credentials that hide inside a plain string.

    Key-based redaction only covers ``{"token": ...}``; a presigned URL carries
    its signature in the query string, and a model error can quote a bearer
    token verbatim. Both are still secrets.
    """
    if not text:
        return text
    cleaned = _SECRET_QUERY_RE.sub(r"\1=[REDACTED]", text)
    return _BEARER_RE.sub(r"\1 [REDACTED]", cleaned)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_secret(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _bounded_text(text: str) -> str:
    return text if len(text) <= 4000 else text[:4000] + "…[truncated]"
