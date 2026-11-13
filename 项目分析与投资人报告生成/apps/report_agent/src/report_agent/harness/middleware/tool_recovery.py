"""Semantic recovery loop for failed Agent tool calls."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

RECOVERY_MARKER = "report_agent_tool_failure"


class ToolFailureEnvelopeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Convert tool exceptions into bounded structured state visible to the model."""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            tool_name = request.tool.name if request.tool else request.tool_call["name"]
            retryable = isinstance(exc, (ValueError, TimeoutError, ConnectionError))
            is_evidence_error = type(exc).__name__ == "EvidenceValidationError" and hasattr(
                exc, "issues"
            )
            strategy = (
                "read_evidence_then_upsert_invalid_content_and_revalidate"
                if is_evidence_error
                else "revise_arguments_and_retry_tool"
                if isinstance(exc, ValueError)
                else "retry_tool"
                if retryable
                else "stop_and_report_business_failure"
            )
            envelope = {
                "marker": RECOVERY_MARKER,
                "status": "failed",
                "tool": tool_name,
                "retryable": retryable,
                "error_type": type(exc).__name__,
                "error": _bounded_error(str(exc)) if retryable else "tool execution failed",
                "next_action": strategy,
            }
            if is_evidence_error:
                envelope["retryable"] = True
                issues = cast(Any, exc).issues
                envelope["issues"] = [
                    asdict(cast(Any, issue)) if is_dataclass(issue) else str(issue)
                    for issue in issues
                ]
                envelope["instructions"] = (
                    "For each issue, the cited evidence is empty/failed or not found. "
                    "Edit the markdown file with edit_file to replace the unusable "
                    "<!-- cite: evidence_xxx --> with a valid evidence_id (use read_evidence "
                    "or search_evidence to find one), or remove the citation if no valid "
                    "evidence exists. Then call create_word_from_md again."
                )
            return ToolMessage(
                content=json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                tool_call_id=request.tool_call["id"],
                name=tool_name,
                status="error",
            )


class ToolArgumentRecoveryMiddleware(AgentMiddleware[Any, Any, Any]):
    """Make semantic tool failures actionable and require a corrected call attempt."""

    def __init__(self, *, max_repair_attempts: int = 2) -> None:
        if max_repair_attempts < 0 or max_repair_attempts > 5:
            raise ValueError("max_repair_attempts must be between 0 and 5")
        self._max_repair_attempts = max_repair_attempts

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any]:
        failure = _latest_tool_failure(request.messages, request.tools)
        if failure is None or not failure["retryable"] or self._max_repair_attempts == 0:
            return await handler(request)

        error_brief = failure["error"][:300] if failure.get("error") else "unknown error"
        # Keep recovery guidance as a user message.  Some OpenAI-compatible
        # providers only accept system messages at the beginning of history;
        # injecting one after an assistant/tool pair can make them report the
        # preceding tool_call_id as unanswered even though its ToolMessage is
        # present.
        if failure.get("next_action") == "read_evidence_then_upsert_invalid_content_and_revalidate":
            recovery_action = (
                "For each issue, the cited evidence is empty/failed or not found. "
                "Edit the markdown file with edit_file to replace the unusable "
                "<!-- cite: evidence_xxx --> with a valid evidence_id, or remove it. "
                "Then call create_word_from_md again."
            )
        else:
            recovery_action = (
                "Read allowed_schema carefully, match every field name and type exactly, do not "
                "include extra fields, fix the arguments, and call the tool again. Never repeat "
                "identical failed arguments."
            )
        instruction = HumanMessage(
            content=(
                f"A tool call to '{failure['tool']}' failed: {error_brief}. "
                "This is recoverable runtime state, not a final answer. "
                f"{recovery_action}"
            )
        )
        messages = [*_normalized_messages(request.messages, failure), instruction]
        current = request.override(messages=messages)
        for attempt in range(self._max_repair_attempts + 1):
            response = await handler(current)
            if _has_tool_call(response) or attempt >= self._max_repair_attempts:
                return response
            messages = [
                *messages,
                *_response_messages(response),
                HumanMessage(
                    content=(
                        f"Recovery attempt {attempt + 1} ended without a corrected tool call. "
                        "Read the allowed_schema in the error response, fix the field names "
                        "and types to match it exactly, and call the tool now. If required "
                        "business input is genuinely unavailable, ask only for it."
                    )
                ),
            ]
            current = request.override(messages=messages)
        return response


_MAX_CONSECUTIVE_SAME_TOOL_FAILURES = 3


def _latest_tool_failure(messages: list[Any], tools: list[Any]) -> dict[str, Any] | None:
    # Count how many times the same tool has failed consecutively at the tail
    # of the message history. If the same tool keeps failing, stop retrying
    # to avoid burning the model-call budget on an unrecoverable schema
    # mismatch — the model should instead try a different approach.
    consecutive_failures = 0
    last_tool_name: str | None = None
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        if message.status != "error":
            break
        tool_name = message.name or "unknown"
        if last_tool_name is None:
            last_tool_name = tool_name
            consecutive_failures = 1
        elif tool_name == last_tool_name:
            consecutive_failures += 1
        else:
            break

    if consecutive_failures >= _MAX_CONSECUTIVE_SAME_TOOL_FAILURES:
        return None  # give up retrying the same tool

    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            continue
        if message.status != "error":
            return None
        tool_name = message.name or "unknown"
        tool = next((candidate for candidate in tools if candidate.name == tool_name), None)
        schema: Any = None
        if tool is not None:
            args_schema = getattr(tool, "args_schema", None)
            schema = (
                args_schema
                if isinstance(args_schema, dict)
                else tool.get_input_schema().model_json_schema()
            )
        existing = _parse_failure(message.content)
        return {
            "marker": RECOVERY_MARKER,
            "status": "failed",
            "tool": tool_name,
            "retryable": bool(existing.get("retryable", True)),
            "error_type": existing.get("error_type", "ToolValidationError"),
            "error": existing.get("error", _bounded_error(message.content)),
            "allowed_schema": schema,
            "next_action": existing.get("next_action", "revise_arguments_and_retry_tool"),
        }
    return None


def _normalized_messages(messages: list[Any], failure: dict[str, Any]) -> list[Any]:
    normalized = list(messages)
    for index in range(len(normalized) - 1, -1, -1):
        message = normalized[index]
        if isinstance(message, ToolMessage) and message.status == "error":
            normalized[index] = message.model_copy(
                update={"content": json.dumps(failure, ensure_ascii=False, separators=(",", ":"))}
            )
            break
    return normalized


def _bounded_error(content: Any) -> str:
    text = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, default=str)
    )
    return text[:2000]


def _parse_failure(content: Any) -> dict[str, Any]:
    if not isinstance(content, str):
        return {}
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) and value.get("marker") == RECOVERY_MARKER else {}


def _response_messages(response: ModelCallResult[Any]) -> list[Any]:
    if isinstance(response, AIMessage):
        return [response]
    if isinstance(response, ModelResponse):
        return list(response.result)
    # ExtendedModelResponse: extract messages from the wrapped model_response
    # without assuming the attribute is always present.
    model_response = getattr(response, "model_response", None)
    if isinstance(model_response, ModelResponse):
        return list(model_response.result)
    result = getattr(response, "result", None)
    if isinstance(result, list):
        return list(result)
    return []


def _has_tool_call(response: ModelCallResult[Any]) -> bool:
    return any(
        isinstance(message, AIMessage) and bool(message.tool_calls)
        for message in _response_messages(response)
    )
