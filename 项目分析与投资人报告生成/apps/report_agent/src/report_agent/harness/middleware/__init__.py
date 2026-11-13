"""Project-owned middleware adapters for the selected Harness."""

from report_agent.harness.middleware.agent_logger import AgentCallLoggerMiddleware
from report_agent.harness.middleware.budget import BudgetMiddleware
from report_agent.harness.middleware.context import (
    ContextHardStopMiddleware,
    ContextLimitExceeded,
    ToolOutputOffloadMiddleware,
)
from report_agent.harness.middleware.empty_tool_calls_guard import (
    EmptyToolCallsGuardMiddleware,
)
from report_agent.harness.middleware.tool_recovery import (
    ToolArgumentRecoveryMiddleware,
    ToolFailureEnvelopeMiddleware,
)

__all__ = [
    "AgentCallLoggerMiddleware",
    "BudgetMiddleware",
    "ContextHardStopMiddleware",
    "ContextLimitExceeded",
    "EmptyToolCallsGuardMiddleware",
    "ToolOutputOffloadMiddleware",
    "ToolArgumentRecoveryMiddleware",
    "ToolFailureEnvelopeMiddleware",
]
