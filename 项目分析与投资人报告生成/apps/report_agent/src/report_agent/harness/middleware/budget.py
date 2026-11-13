"""LangChain middleware adapter for deterministic run budgets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from report_agent.harness.budget import RunBudget


class BudgetMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(self, budget: RunBudget) -> None:
        self._budget = budget

    def before_model(self, state: Any, runtime: Runtime[Any]) -> None:
        self._budget.consume_model_call()

    async def abefore_model(self, state: Any, runtime: Runtime[Any]) -> None:
        self._budget.consume_model_call()

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        self._budget.consume_tool_call()
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        self._budget.consume_tool_call()
        return await handler(request)
