"""Reasoning capture and provider-neutral thinking switches."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import SystemMessage

from report_agent.harness.reasoning import ReasoningStore, extract_reasoning
from report_agent.harness.thinking import (
    ThinkingAdapter,
    ThinkingMode,
    detect_adapter,
    parse_mode,
    resolve_adapter,
    thinking_params,
)
from report_agent.runtime.workspace import TaskWorkspace

# --------------------------------------------------------------------------- #
# thinking switches
# --------------------------------------------------------------------------- #

QWEN = ThinkingAdapter.QWEN
DEEPSEEK = ThinkingAdapter.DEEPSEEK
ANTHROPIC = ThinkingAdapter.ANTHROPIC
OPENAI = ThinkingAdapter.OPENAI
NONE = ThinkingAdapter.NONE


def test_off_never_sends_a_budget():
    """A zero budget does not switch thinking off on any of these providers."""
    assert thinking_params(QWEN, ThinkingMode.OFF) == {"enable_thinking": False}
    assert thinking_params(DEEPSEEK, ThinkingMode.OFF) == {"thinking": {"type": "disabled"}}
    assert thinking_params(ANTHROPIC, ThinkingMode.OFF) == {"thinking": {"type": "disabled"}}
    assert thinking_params(OPENAI, ThinkingMode.OFF) == {"reasoning_effort": "minimal"}
    assert thinking_params(NONE, ThinkingMode.OFF) == {}
    for adapter in (QWEN, DEEPSEEK, ANTHROPIC, OPENAI, NONE):
        params = json.dumps(thinking_params(adapter, ThinkingMode.OFF))
        assert "budget" not in params


def test_auto_leaves_qwen_and_deepseek_to_their_own_default():
    assert thinking_params(QWEN, ThinkingMode.AUTO) == {}
    assert thinking_params(DEEPSEEK, ThinkingMode.AUTO) == {}


def test_auto_asks_anthropic_for_adaptive_explicitly():
    """Omitting ``thinking`` means no thinking on 4.6 but adaptive on Sonnet 5."""
    assert thinking_params(ANTHROPIC, ThinkingMode.AUTO) == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


def test_on_carries_the_optional_budget_for_qwen():
    assert thinking_params(QWEN, ThinkingMode.ON) == {"enable_thinking": True}
    assert thinking_params(QWEN, ThinkingMode.ON, budget=256) == {
        "enable_thinking": True,
        "thinking_budget": 256,
    }


def test_parse_mode_is_forgiving():
    assert parse_mode("OFF") is ThinkingMode.OFF
    assert parse_mode(" on ") is ThinkingMode.ON
    assert parse_mode("") is ThinkingMode.AUTO
    assert parse_mode("nonsense") is ThinkingMode.AUTO


def test_adapter_detection_and_override():
    assert resolve_adapter("auto", "qwen3.6-27b") is QWEN
    assert resolve_adapter("", "deepseek-v3") is DEEPSEEK
    assert resolve_adapter("anthropic", "anything") is ANTHROPIC
    # An unknown configured value falls back to guessing.
    assert resolve_adapter("bogus", "claude-sonnet") is ANTHROPIC
    assert detect_adapter("unknown-model") is NONE


# --------------------------------------------------------------------------- #
# reasoning capture
# --------------------------------------------------------------------------- #

def test_extract_reasoning_reads_every_known_field_name():
    qwen = {"choices": [{"message": {"content": "a", "reasoning_content": "thinking..."}}]}
    openai = {"choices": [{"message": {"content": "a", "reasoning": "thinking..."}}]}
    anthropic = {
        "choices": [
            {"message": {"content": "a", "reasoning": [{"thinking": "step one"}, {"thinking": "step two"}]}}
        ]
    }
    assert extract_reasoning(qwen) == "thinking..."
    assert extract_reasoning(openai) == "thinking..."
    assert extract_reasoning(anthropic) == "step one\nstep two"


def test_extract_reasoning_is_empty_when_there_is_none():
    assert extract_reasoning({"choices": [{"message": {"content": "a"}}]}) == ""
    assert extract_reasoning({}) == ""
    assert extract_reasoning("not a dict") == ""


@pytest.fixture()
def workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    return workspace


def test_store_writes_the_capture_and_the_index(workspace):
    store = ReasoningStore(workspace, "run_abc")
    record = store.record("我先看了材料 A，再看了材料 B。")

    assert record is not None
    assert record.seq == 1
    assert record.chars == len("我先看了材料 A，再看了材料 B。")
    assert (workspace.root / record.path.removeprefix("/workspace/")).is_file()
    index = workspace.read_text("/workspace/state/decision-log.jsonl").strip().splitlines()
    assert len(index) == 1
    assert json.loads(index[0])["seq"] == 1


def test_excerpt_keeps_the_opening_and_the_decision(workspace):
    """A reasoning trace opens by restating the task and closes with the call."""
    store = ReasoningStore(workspace, "run_abc")
    opening = "Here's a thinking process: analyze the task."
    middle = "x" * 2000
    decision = "决定：先写客户验证状态，三一已完成、徐工进行中。"
    store.record(opening + middle + decision)

    block = store.excerpt_block()

    assert opening in block, "开头（定调）必须保留"
    assert decision in block, "结尾（结论）必须保留"
    assert "..." in block, "截断处必须有标记"
    assert "中间省略" in block
    assert "节选" in block, "必须让模型知道这是节选"
    assert "read_file" in block, "要告诉模型全文在哪"


def test_every_step_gets_its_own_excerpt(workspace):
    """Reasoning is what keeps the run coherent, so no step is dropped."""
    store = ReasoningStore(workspace, "run_abc")
    for index in range(5):
        store.record(f"第{index}步的开头。" + ("填充" * 400) + f"第{index}步的结论。")

    block = store.excerpt_block()

    for index in range(5):
        assert f"第{index}步的开头" in block, f"第 {index} 步开头丢了"
        assert f"第{index}步的结论" in block, f"第 {index} 步结论丢了"
    assert block.count("中间省略") == 5, "每一步各自截断，不是整体截一次"


def test_limit_keeps_only_the_last_steps(workspace):
    store = ReasoningStore(workspace, "run_abc")
    store.record("第一条")
    store.record("第二条")
    store.record("第三条")

    block = store.excerpt_block(limit=2)
    assert "第三条" in block
    assert "第二条" in block
    assert "第一条" not in block
    # The framing must say this is not evidence.
    assert "仅供参照" in block


def test_excerpt_never_starts_with_the_capture_file_title(workspace):
    """The excerpt is cut from the reasoning, not from the stored file."""
    store = ReasoningStore(workspace, "run_abc")
    store.record("第一行是真正的推理。" + "填充内容。" * 400)
    block = store.excerpt_block()
    assert "# 第 1 步的推理记录" not in block
    assert "第一行是真正的推理。" in block


def test_excerpt_of_a_short_capture_is_marked_as_complete(workspace):
    store = ReasoningStore(workspace, "run_abc")
    store.record("很短的一段推理。")
    block = store.excerpt_block()
    assert "未截断" in block
    assert "中间省略" not in block


def test_store_ignores_blank_captures(workspace):
    store = ReasoningStore(workspace, "run_abc")
    assert store.record("   ") is None
    assert store.excerpt_block() == ""


# --------------------------------------------------------------------------- #
# streaming capture
# --------------------------------------------------------------------------- #

def test_stream_converter_keeps_the_chain_of_thought(workspace):
    """langchain-openai drops the field from streamed deltas; the patch keeps it."""
    from langchain_core.messages import AIMessageChunk

    from report_agent.harness.reasoning import install_stream_reasoning_patch
    from langchain_openai.chat_models import base as lc_base

    install_stream_reasoning_patch()
    chunk = lc_base._convert_delta_to_message_chunk(
        {"role": "assistant", "content": "", "reasoning_content": "先看材料。"},
        AIMessageChunk,
    )
    assert chunk.additional_kwargs.get("reasoning_content") == "先看材料。"


def test_astream_captures_reasoning_even_though_it_skips_the_result_hook(
    workspace, monkeypatch
):
    """The console always streams, so ``_create_chat_result`` never runs."""
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk
    from langchain_openai import ChatOpenAI

    from report_agent.harness.reasoning import ReasoningChatOpenAI

    async def fake_astream(self, messages, stop=None, run_manager=None, **kwargs):
        for text in ("先核对客户状态。", "再写正文。"):
            chunk = AIMessageChunk(content="")
            chunk.additional_kwargs["reasoning_content"] = text
            yield ChatGenerationChunk(message=chunk)

    monkeypatch.setattr(ChatOpenAI, "_astream", fake_astream)
    store = ReasoningStore(workspace, "run_stream")
    model = ReasoningChatOpenAI(
        model="test", api_key="k", base_url="http://127.0.0.1:1", store=store
    )

    import asyncio

    async def drain():
        return [chunk async for chunk in model._astream([])]

    chunks = asyncio.run(drain())

    assert len(chunks) == 2
    assert len(store.records) == 1, "一次流式调用应落一条完整推理"
    assert store.records[0].chars == len("先核对客户状态。再写正文。")
    # The field stays on the chunk on purpose: the assembled message carries the
    # chain of thought, and the next turn echoes it back as ``reasoning_content``.
    assert "reasoning_content" in (chunks[-1].message.additional_kwargs or {})


# --------------------------------------------------------------------------- #
# echo middleware
# --------------------------------------------------------------------------- #

def _request(system: str = "SYSTEM"):
    from langchain.agents.middleware.types import ModelRequest
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model="test", api_key="test", base_url="http://127.0.0.1:1")
    return ModelRequest(
        model=model,
        messages=[],
        system_message=SystemMessage(content=system),
    )


def test_echo_puts_reasoning_on_the_assistant_turn_not_in_the_system_prompt(workspace):
    """思考作为上下文回传，不再塞进 system prompt。

    DashScope 接受顶层 ``reasoning_content``，但拒绝 ``{"type":"reasoning"}``
    content block（400），所以这里同时断言 content 没被改成列表。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from report_agent.harness.reasoning import ReasoningChatOpenAI

    model = ReasoningChatOpenAI(
        model="test", api_key="test", base_url="http://127.0.0.1:1"
    )
    messages = [
        HumanMessage("今天是几号？"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "先看要不要用工具。"},
            tool_calls=[{"id": "call_1", "name": "get_date", "args": {}}],
        ),
        HumanMessage("直接回答我。"),
    ]
    payload = model._get_request_payload(messages)
    assistant = payload["messages"][1]

    assert assistant["reasoning_content"] == "先看要不要用工具。"
    assert not isinstance(assistant["content"], list), "content 不能变成 reasoning block"


def test_assistant_without_reasoning_is_left_untouched():
    from langchain_core.messages import AIMessage, HumanMessage

    from report_agent.harness.reasoning import ReasoningChatOpenAI

    model = ReasoningChatOpenAI(
        model="test", api_key="test", base_url="http://127.0.0.1:1"
    )
    messages = [HumanMessage("hi"), AIMessage(content="hello")]
    payload = model._get_request_payload(messages)
    assert "reasoning_content" not in payload["messages"][1]


def test_streamed_reasoning_stays_on_the_chunk_for_echoing():
    """分片上的字段不能被弹掉，否则下一轮无从回传。"""
    from langchain_core.messages import AIMessageChunk

    from report_agent.harness.reasoning import take_reasoning

    chunk = AIMessageChunk(content="")
    chunk.additional_kwargs["reasoning_content"] = "先核对客户状态。"
    parts: list[str] = []
    take_reasoning(chunk, parts)

    assert parts == ["先核对客户状态。"]
    assert chunk.additional_kwargs.get("reasoning_content") == "先核对客户状态。"


def test_echo_safety_valve_trims_only_runaway_reasoning():
    from langchain_core.messages import AIMessage

    from report_agent.harness.reasoning import MAX_ECHO_CHARS, _reasoning_of

    normal = AIMessage(content="", additional_kwargs={"reasoning_content": "短推理"})
    assert _reasoning_of(normal) == "短推理"

    runaway = AIMessage(
        content="", additional_kwargs={"reasoning_content": "长" * (MAX_ECHO_CHARS + 500)}
    )
    assert len(_reasoning_of(runaway)) == MAX_ECHO_CHARS
