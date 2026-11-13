"""Make a question a real execution boundary, even in a mixed tool batch."""
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage


class QuestionBoundaryMiddleware(AgentMiddleware[Any, Any, Any]):
    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break
            if message.name == "ask_user" and isinstance(message.content, str):
                try:
                    output = json.loads(message.content)
                except ValueError:
                    continue
                if isinstance(output, dict) and output.get("status") == "needs_user_input":
                    return {"jump_to": "end"}
            if message.name in {"query_company_registry", "query_cbex_listing_financials", "detect_one_pager_business_type", "check_one_pager_outline", "render_one_pager"} and isinstance(message.content, str):
                try:
                    output = json.loads(message.content)
                except ValueError:
                    continue
                if isinstance(output, dict) and output.get("question_request"):
                    return {"jump_to": "end"}
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        message = state["messages"][-1]
        if isinstance(message, AIMessage):
            detections = [call for call in message.tool_calls if call["name"] == "detect_one_pager_business_type"]
            if detections and len(message.tool_calls) > 1:
                return {"messages": [message.model_copy(update={"tool_calls": detections[:1]})]}
            questions = [call for call in message.tool_calls if call["name"] == "ask_user"]
            if questions:
                # Run one question first; the boundary handles whether it needs
                # input or can reuse an answer already saved in this task.
                return {"messages": [message.model_copy(update={"tool_calls": questions[:1]})]}
            for name in ("detect_one_pager_business_type", "check_one_pager_outline", "query_company_registry", "query_cbex_listing_financials", "render_one_pager"):
                gates = [call for call in message.tool_calls if call["name"] == name]
                if gates and len(message.tool_calls) > 1:
                    # A gate must be resolved before dependent tools can run.
                    return {"messages": [message.model_copy(update={"tool_calls": gates[:1]})]}
        return None
