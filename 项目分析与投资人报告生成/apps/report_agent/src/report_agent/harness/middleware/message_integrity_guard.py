"""Guard against broken AIMessage(tool_calls)/ToolMessage pairings.

When retries across middleware layers (ToolArgumentRecovery,
EmptyToolCallsGuard, SummarizationMiddleware) reshape the message history,
an ``AIMessage`` carrying ``tool_calls`` may end up without a corresponding
``ToolMessage`` response. Providers reject this with HTTP 400:

    An assistant message with "tool_calls" must be followed by tool messages
    responding to each "tool_call_id".

This middleware performs a pre-emptive scan before every model call: it
collects all ``tool_call_id`` values that already have a ``ToolMessage``
response and inserts a placeholder ``ToolMessage`` for any that do not.
In a well-formed history (the normal case) the scan finds zero missing
pairings and the request passes through unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import AIMessage, ToolMessage

PLACEHOLDER_TOOL_RESPONSE = (
    "This tool call was not executed in this session and no result is "
    "available. Proceed with the information you already have, or call the "
    "tool again if the result is still needed."
)


class MessageIntegrityGuardMiddleware(AgentMiddleware[Any, Any, Any]):
    """Ensure every AIMessage(tool_calls) has a matching ToolMessage response.

    Pre-emptive scan before each model call: if any ``tool_call_id`` lacks a
    ``ToolMessage`` response, a placeholder response is appended so the
    provider does not reject the request with HTTP 400.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any]:
        repaired = _ensure_pairing(request.messages)
        if len(repaired) == len(request.messages):
            return await handler(request)
        return await handler(request.override(messages=repaired))


def _ensure_pairing(messages: list[Any]) -> list[Any]:
    """Ensure tool responses immediately follow the AI call that emitted them.

    Provider validation is positional, not merely a global ID-set check.  A
    response appearing later in history does not repair an interrupted
    assistant/tool block, so placeholders are inserted before the first
    non-tool message following that AIMessage.
    """
    repaired: list[Any] = []
    changed = False
    index = 0
    while index < len(messages):
        message = messages[index]
        # Summarization can remove the assistant side of an old tool exchange
        # while leaving its ToolMessage behind.  Providers reject such orphan
        # tool messages, so discard them at the final model boundary.
        if isinstance(message, ToolMessage):
            changed = True
            index += 1
            continue
        repaired.append(message)
        index += 1
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue

        expected: dict[str, str] = {}
        for call in message.tool_calls:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            call_name = (
                call.get("name", "tool")
                if isinstance(call, dict)
                else getattr(call, "name", "tool")
            )
            if call_id:
                expected[str(call_id)] = str(call_name)

        while index < len(messages) and isinstance(messages[index], ToolMessage):
            tool_message = messages[index]
            tool_call_id = str(tool_message.tool_call_id)
            if tool_call_id in expected:
                repaired.append(tool_message)
                expected.pop(tool_call_id)
            else:
                # Drop duplicate or unrelated responses inside the block.
                changed = True
            index += 1

        for call_id, call_name in expected.items():
            repaired.append(
                ToolMessage(
                    content=PLACEHOLDER_TOOL_RESPONSE,
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            changed = True

    return repaired if changed else messages
