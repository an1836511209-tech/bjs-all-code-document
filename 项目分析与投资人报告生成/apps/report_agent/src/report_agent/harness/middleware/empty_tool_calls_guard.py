"""Guard against silent termination when the model emits empty tool_calls.

When an LLM returns ``finish_reason="tool_calls"`` but no actual tool_call
objects (and empty content), LangGraph's model→tools conditional edge treats
``len(tool_calls) == 0`` as "model is done" and ends the run. This is a silent
failure: the agent never reaches downstream phases (e.g. report production).
This middleware detects that anomaly and re-prompts the model with an explicit
instruction to either call a tool or produce a final answer, up to
``max_retries`` times.

The guard is intentionally narrow: it only triggers when the last AIMessage
has no ``tool_calls`` AND no textual content. A model that produces a normal
text answer or a valid tool call is never intercepted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, HumanMessage

EMPTY_TOOL_CALLS_MARKER = "report_agent_empty_tool_calls"


class EmptyToolCallsGuardMiddleware(AgentMiddleware[Any, Any, Any]):
    """Re-prompt the model when it returns an empty tool_calls response.

    Detects responses where the AIMessage carries no ``tool_calls`` and no
    textual content — the state that would otherwise end the agent loop
    silently. The guard injects a HumanMessage instructing the model to either
    call a tool or produce a final answer, and retries up to ``max_retries``
    times. If the model keeps returning empty responses after the budget is
    exhausted, the last response is returned as-is (LangGraph will then end
    the run, but at least the retry attempts are visible in the agent log).
    """

    def __init__(self, *, max_retries: int = 2) -> None:
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        self._max_retries = max_retries

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any]:
        if self._max_retries == 0:
            return await handler(request)

        current = request
        response = await handler(current)
        for attempt in range(self._max_retries):
            if not _is_empty_tool_calls_response(response):
                return response
            # Do not append the degenerate AIMessage. Some OpenAI-compatible
            # providers serialize its finish_reason=tool_calls as an assistant
            # tool-call turn even though the call list is empty, then reject the
            # following recovery HumanMessage as an unanswered tool call.
            messages = [
                *current.messages,
                HumanMessage(content=_build_recovery_instruction(attempt)),
            ]
            current = current.override(messages=messages)
            response = await handler(current)
        return response


def _build_recovery_instruction(attempt: int) -> str:
    suffix = f"This is recovery attempt {attempt + 1} of the guard. " if attempt > 0 else ""
    return (
        "The previous response was empty: finish_reason indicated tool_calls but "
        "no tool_call was emitted and the text content was empty. The agent loop "
        f"would end silently here. {suffix}Choose one next action and execute it now: "
        "call the appropriate tool to advance the current phase (with complete "
        "arguments per its schema), or, if data collection is complete, begin "
        "report production via create_word_document, or emit a final natural-language "
        "answer. Do not return an empty response again."
    )


def _is_empty_tool_calls_response(response: ModelCallResult[Any]) -> bool:
    """True when the last AIMessage carries no tool_calls and no text content."""
    messages = _response_messages(response)
    if not messages:
        return False  # nothing to analyze; let upstream decide
    last = messages[-1]
    if not isinstance(last, AIMessage):
        return False
    if bool(last.tool_calls):
        return False
    content = last.content
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return not text.strip()
    # Non-string, non-list content (e.g. structured payload) is not "empty".
    return False


def _response_messages(response: ModelCallResult[Any]) -> list[Any]:
    """Extract the AIMessage(s) from any ModelCallResult variant."""
    if isinstance(response, AIMessage):
        return [response]
    if isinstance(response, ModelResponse):
        return list(response.result)
    if hasattr(response, "model_response"):
        model_response = getattr(response, "model_response", None)
        if isinstance(model_response, ModelResponse):
            return list(model_response.result)
    if hasattr(response, "result"):
        result = getattr(response, "result", None)
        if isinstance(result, list):
            return list(result)
    return []
