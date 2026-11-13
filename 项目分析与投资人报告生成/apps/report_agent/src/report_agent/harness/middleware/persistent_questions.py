"""Real graph interrupts for opted-in one-pagers; legacy questions stay unchanged."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import interrupt

from report_agent.application.interactions import question_payload
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware


class PersistentQuestionBoundaryMiddleware(QuestionBoundaryMiddleware):
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        message = state["messages"][-1]
        if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
            return None
        if message.name not in {"ask_user", "query_company_registry", "query_cbex_listing_financials",
                                "detect_one_pager_business_type", "check_one_pager_outline", "render_one_pager"}:
            return None
        try:
            output = json.loads(message.content)
        except ValueError:
            return None
        if not isinstance(output, dict):
            return None
        if message.name == "ask_user" and output.get("status") != "needs_user_input":
            return None
        question = output if message.name == "ask_user" else output.get("question_request")
        if not isinstance(question, dict):
            return None
        question = question_payload(str(question.get("question") or ""), question, "")
        identity = f"{message.id}:{message.tool_call_id}"
        qid = "question_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        question.update(question_id=qid, approval_id=qid, origin_tool=message.name,
                        resume_node=f"{self.name}.before_model", checkpointed=True)
        # No I/O or budget mutation before interrupt: LangGraph replays this node.
        answer = interrupt(question)
        if not isinstance(answer, dict) or answer.get("question_id") != qid or not answer.get("text"):
            raise ValueError("恢复回答与当前检查点问题不一致")
        return {"messages": [HumanMessage(id="answer_" + qid, content=answer["text"])]}
