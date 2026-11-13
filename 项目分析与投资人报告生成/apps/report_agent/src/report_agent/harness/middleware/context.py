"""LangChain middleware adapter for large tool result offload."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

from report_agent.harness.context import ContextWindow, ToolOutputOffloader


class ContextLimitExceeded(RuntimeError):
    pass


class ContextHardStopMiddleware(AgentMiddleware[Any, Any, Any]):
    """Reject a model call if compaction failed to get below the hard limit."""

    def __init__(self, window: ContextWindow) -> None:
        self._window = window

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any] | AIMessage:
        self._check(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any] | AIMessage:
        self._check(request)
        return await handler(request)

    def _check(self, request: ModelRequest[Any]) -> None:
        messages = (
            [request.system_message, *request.messages]
            if request.system_message
            else request.messages
        )
        tokens = count_tokens_approximately(messages, tools=request.tools)
        if tokens >= self._window.hard_stop_tokens:
            raise ContextLimitExceeded(
                f"context hard limit reached: estimated={tokens}, limit={self._window.hard_stop_tokens}"
            )


class ToolOutputOffloadMiddleware(AgentMiddleware[Any, Any, Any]):
    # Tools whose purpose is to read offloaded results. Their output must stay
    # inline — otherwise a second offload creates a cascading reference that the
    # model cannot resolve without yet another read, ad infinitum.
    _OFFLOAD_EXEMPT: frozenset[str] = frozenset(
        {
            "read_result_chunk",
            "search_result",
            "list_result_paths",
            "read_evidence",
            "read_evidence_pack",
            "run_writing_review",
        }
    )

    def __init__(self, offloader: ToolOutputOffloader, *, exempt_tools: frozenset[str] = frozenset()) -> None:
        self._offloader = offloader
        self._OFFLOAD_EXEMPT = self._OFFLOAD_EXEMPT | exempt_tools

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        return self._offload(handler(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        return self._offload(await handler(request))

    def _offload(self, response: ToolMessage | Command[Any]) -> ToolMessage | Command[Any]:
        if not isinstance(response, ToolMessage):
            return response
        # Validation/failure messages are control flow, not data artifacts. Keeping
        # them inline preserves ``status=error`` and lets argument recovery see the
        # real schema error instead of an opaque offload reference.
        if response.status == "error":
            return response
        tool_name = response.name or "tool"
        # Offload-retrieval tools must stay inline to avoid cascading offload.
        if tool_name in self._OFFLOAD_EXEMPT:
            return response
        result = self._offloader.prepare(tool_name, response.tool_call_id, response.content)
        if not result.offloaded:
            return response
        metadata = dict(response.additional_kwargs)
        metadata["report_agent_artifact"] = {
            "path": result.artifact_path,
            "sha256": result.sha256,
            "original_chars": result.original_chars,
        }
        return response.model_copy(
            update={"content": result.content, "additional_kwargs": metadata}
        )
