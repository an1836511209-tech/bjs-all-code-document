"""Resume a persisted Agent graph at its actual pending node."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from report_agent.application.one_pager_execution import (
    COMMAND_PATH,
    STATE_PATH,
    execution_lock,
    execution_state,
    read_json,
    write_json,
)


async def run_checkpointed_agent(agent: Any, workspace: Any, identity: Any,
                                initial: dict[str, Any], invoke: Any) -> dict[str, Any]:
    with execution_lock(workspace):
        state = execution_state(workspace)
        config = {"configurable": {"thread_id": state["thread_id"]}, "recursion_limit": 9999}
        current = await agent.aget_state(config)
        interrupts = [i for task in current.tasks for i in task.interrupts]
        command = read_json(workspace, COMMAND_PATH)
        values = current.values or {}
        seen_ids = {getattr(m, "id", None) for m in values.get("messages", [])}
        already_applied = ("answer_" + str(command.get("question_id"))) in seen_ids
        if interrupts:
            question = interrupts[0].value
            if command.get("kind") == "resume" and not already_applied:
                if command.get("question_id") != question.get("question_id"):
                    # The graph may have committed the answer before command
                    # acknowledgement, then compacted that old HumanMessage.
                    # Surface the current question; never answer it with old data.
                    return _project(workspace, identity, current, command)
                inputs: Any = Command(resume={interrupts[0].id: command["answer"]})
            else:
                inputs = None
                # Waiting with no new answer: never invoke the graph or a model.
                return _project(workspace, identity, current, command)
        elif current.next:
            inputs = None  # Crash recovery: the graph owns the execution cursor.
        elif not values:
            if state.get("status") != "new" or command.get("kind") == "resume":
                raise ValueError("MySQL 中未找到原执行检查点，请检查专用 schema；为避免重复执行，不能从头重跑")
            inputs = initial
        elif command.get("kind") == "message" and command.get("id") not in seen_ids:
            inputs = {"messages": [HumanMessage(id=command["id"], content=command["text"])]}
        else:
            return _project(workspace, identity, current, command)
        write_json(workspace, STATE_PATH, {**state, "status": "running", "run_id": identity.run_id,
                                           "pending_question": None})
        await invoke(agent, inputs, config, identity, checkpointed=True)
        # aget_state is authoritative even if the stream's last nested chain
        # event omitted the interrupt or carried an intermediate message list.
        current = await agent.aget_state(config)
        result = _project(workspace, identity, current, command)
        result["trace_messages"] = [m for m in result.get("messages", [])
                                    if getattr(m, "id", None) not in seen_ids]
        return result


def _project(workspace: Any, identity: Any, snapshot: Any, command: dict[str, Any]) -> dict[str, Any]:
    interrupts = [i for task in snapshot.tasks for i in task.interrupts]
    pending = dict(interrupts[0].value) if interrupts else None
    if pending:
        pending.update(run_id=identity.run_id, interrupt_id=interrupts[0].id)
    values = dict(snapshot.values or {})
    values.update(pending_question=pending, execution_status="needs_input" if pending else "completed")
    values["trace_messages"] = []
    state = execution_state(workspace)
    values_config = snapshot.config or {}
    plan = values.get("todos") or state.get("plan") or []
    write_json(workspace, STATE_PATH, {**state, "status": "waiting" if pending else "completed",
               "run_id": identity.run_id, "checkpoint_id": values_config.get("configurable", {}).get("checkpoint_id"),
               "next": list(snapshot.next), "pending_question": pending, "plan": plan})
    write_json(workspace, COMMAND_PATH, {**command, "status": "applied"})
    values["execution"] = execution_state(workspace)
    return values
