"""Regression cases from the interrupted one-pager production log."""
from __future__ import annotations

import json

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from report_agent.application.interactions import update_interaction
from report_agent.application.review_checker import QualityChecker
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.middleware.persistent_questions import (
    PersistentQuestionBoundaryMiddleware,
)
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware
from report_agent.harness.review_tools import build_review_tools
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.runtime.workspace import TaskWorkspace


def _workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    return workspace


def _evidence(workspace, *, tool="parse_materials", text="年租金收入约1.05亿元。"):
    return WorkspaceEvidenceStore(workspace).put(tool, {
        "tool": tool, "status": "success", "summary": "来源",
        "data": {"blocks": [{"text": text}]},
    })


@pytest.mark.parametrize("amount", ["1.05亿元", "10,500万元", "10500.00万元"])
def test_quality_preserves_material_approximate_number(tmp_path, amount):
    workspace = _workspace(tmp_path)
    _evidence(workspace)
    workspace.write_text("/workspace/report/one-pager.md", f"年租金收入约{amount}。")
    tools = build_review_tools(QualityChecker(workspace=workspace), workspace=workspace)
    result = json.loads(tools[0].invoke({"md_path": "/workspace/report/one-pager.md"}))
    assert result["blocking"] is False


@pytest.mark.parametrize("amount", ["1.06亿元", "1.05%", "10,501万元"])
def test_quality_keeps_blocking_unsupported_approximate_numbers(tmp_path, amount):
    workspace = _workspace(tmp_path)
    _evidence(workspace)
    # Quoting a fabricated source in a comment must not create evidence.
    md = f"年租金收入约{amount}。<!-- src: material parse_materials ; 原文：约{amount} -->"
    issues = QualityChecker(workspace=workspace).check(md)
    blocks = [i for i in issues if i.kind == "fabricated_number"]
    assert len(blocks) == 1 and blocks[0].severity == "block"
    assert amount in blocks[0].message


def test_quality_requires_provenance_for_mcp_approximate_number(tmp_path):
    workspace = _workspace(tmp_path)
    _evidence(workspace, tool="query_cbex_listing_financials")
    checker = QualityChecker(workspace=workspace)
    md = "年租金收入约1.05亿元。"
    assert any(i.kind == "fabricated_number" for i in checker.check(md))
    md += "<!-- src: mcp query_cbex_listing_financials /data/annual -->"
    assert not any(i.kind == "fabricated_number" for i in checker.check(md))


@pytest.mark.parametrize("lookup", [
    {"status": "skipped"},
    {"status": "confirmed", "project_name": "用户输入的项目全称"},
    {"status": "selected", "project_name": "用户选定项目", "detail_url": "https://example.test/selected"},
])
def test_repeat_question_returns_the_saved_choice_without_mutating_it(tmp_path, lookup):
    workspace = _workspace(tmp_path)
    update_interaction(workspace, cbex_lookup=lookup)
    result = json.loads(build_ask_user_tools(workspace=workspace)[0].invoke({
        "question": "本项目是否为北交互联正在披露的项目？",
    }))
    assert result["status"] == "already_answered"
    assert result["answer"] == lookup
    assert "question_request" not in result


class _RepeatedQuestionModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "repeated-question-regression"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        results = [m for m in messages if isinstance(m, ToolMessage)]
        asks = [m for m in results if m.name == "ask_user"]
        if len(asks) < 2:
            calls = [{"id": f"ask-{len(asks)}", "name": "ask_user", "args": {
                "question": "本项目是否为北交互联正在披露的项目？",
            }}, {"id": "premature-publish", "name": "publish", "args": {}}]
        elif not any(m.name == "publish" for m in results):
            calls = [{"id": "publish", "name": "publish", "args": {}}]
        else:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="已完成"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))])


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpointed", [False, True])
async def test_first_question_pauses_and_repeat_after_answer_continues_to_publish(tmp_path, checkpointed):
    workspace = _workspace(tmp_path)
    publications = []

    def publish() -> str:
        """Publish only after the user's answer."""
        publications.append("published")
        return "done"

    agent = create_agent(
        _RepeatedQuestionModel(),
        tools=[*build_ask_user_tools(workspace=workspace, resumable=checkpointed),
               StructuredTool.from_function(publish)],
        middleware=[PersistentQuestionBoundaryMiddleware() if checkpointed else QuestionBoundaryMiddleware()],
        checkpointer=InMemorySaver() if checkpointed else None,
    )
    config = {"configurable": {"thread_id": "repeat"}, "recursion_limit": 20}
    first = await agent.ainvoke({"messages": [HumanMessage(content="生成一页纸")]}, config)
    assert publications == []
    update_interaction(workspace, cbex_lookup={"status": "skipped"})
    if checkpointed:
        question = first["__interrupt__"][0].value
        assert question["gate"] == "cbex_listing"
        inputs = Command(resume={"question_id": question["question_id"], "text": "跳过挂牌财务查询"})
    else:
        assert json.loads(first["messages"][-1].content)["status"] == "needs_user_input"
        inputs = {"messages": [*first["messages"], HumanMessage(content="跳过挂牌财务查询")]}
    result = await agent.ainvoke(inputs, config)
    assert not result.get("__interrupt__")
    assert publications == ["published"]
    assert result["messages"][-1].content == "已完成"


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpointed", [False, True])
async def test_other_questions_still_pause_after_disclosure_was_answered(tmp_path, checkpointed):
    workspace = _workspace(tmp_path)
    update_interaction(workspace, cbex_lookup={"status": "skipped"})
    output = await build_ask_user_tools(workspace=workspace, resumable=checkpointed)[0].ainvoke({
        "question": "是否用公开网络搜索补充材料？",
    })
    assert json.loads(output)["status"] == "needs_user_input"
    state = {"messages": [ToolMessage(name="ask_user", content=output, tool_call_id="search")]}
    if not checkpointed:
        assert await QuestionBoundaryMiddleware().abefore_model(state, None) == {"jump_to": "end"}
