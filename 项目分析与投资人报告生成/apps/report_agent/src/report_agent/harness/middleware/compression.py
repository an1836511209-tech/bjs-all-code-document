"""Conversation compression middleware using workspace-backed markdown offload.

When token usage reaches ``trigger_ratio`` of the model context window, old
messages are summarised by the model and the full transcript is appended to
``/workspace/memory/conversation-history.md``. The messages list is replaced
with one summary HumanMessage plus the most recent ``keep_recent`` messages.

This sits between ToolOutputOffloadMiddleware (single-result offload) and
ContextHardStopMiddleware (90% hard stop) in the middleware chain, so the
hard stop becomes a last-resort safety net rather than the primary control.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from report_agent.harness.context import ContextWindow
from report_agent.runtime.workspace import TaskWorkspace

logger = logging.getLogger(__name__)

_HISTORY_PATH = "/workspace/memory/conversation-history.md"

# Messages from these tools are valuable to keep inline (they carry IDs and
# status that the model needs immediately). They are not exempt from
# compression — they just inform the summariser prompt about what to preserve.
_CRITICAL_TOOL_PATTERNS = frozenset(
    {
        "parse_materials",
        "create_report_content",
        "create_word_document",
        "validate_and_publish_word",
        "validate_report_content",
    }
)

_SUMMARISER_PROMPT = """你是对话历史压缩器。以下是一个投资报告生成Agent的历史对话片段。
请提取并保留以下关键信息，删除冗余的完整工具返回内容（那些已保存在工作区文件中）：

1. **已解析的材料ID和evidence_id**（必须完整保留，格式：material_id→evidence_id→source_name）
2. **已创建的report_id和artifact_id**（必须完整保留）
3. **已读取到的材料关键数据**（公司名、注册资本、财务数据、车辆数、充电桩数、投资人名称等核心事实）
4. **当前工作进度**（哪些章节已写、哪些MCP工具已调用及结果状态、当前phase）
5. **待完成的步骤**和**遇到的错误**（如果有）

输出格式：简洁的Markdown摘要，不超过2000字。不要包含完整的工具返回内容——那些已保存在工作区文件中。
特别注意：所有evidence_id、material_id、report_id、artifact_id必须原样保留，不得改写或省略。"""


class ContextCompressionMiddleware(AgentMiddleware[Any, Any, Any]):
    """Compress old messages when token usage reaches the trigger ratio."""

    def __init__(
        self,
        model: Any,
        workspace: TaskWorkspace,
        window: ContextWindow,
        *,
        trigger_ratio: float = 0.75,
        keep_recent: int = 6,
    ) -> None:
        self._model = model
        self._workspace = workspace
        self._window = window
        self._trigger_tokens = int(window.max_tokens * trigger_ratio)
        self._keep_recent = keep_recent

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelCallResult[Any]],
    ) -> ModelCallResult[Any] | BaseMessage:
        return handler(self._maybe_compress(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelCallResult[Any]]],
    ) -> ModelCallResult[Any] | BaseMessage:
        return await handler(self._maybe_compress(request))

    def _maybe_compress(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        messages = (
            [request.system_message, *request.messages]
            if request.system_message
            else list(request.messages)
        )
        tokens = count_tokens_approximately(messages, tools=request.tools)
        self._record_usage(tokens, len(request.messages), compressed=False)
        if tokens < self._trigger_tokens:
            return request
        if len(request.messages) <= self._keep_recent:
            # Not enough messages to compress — let the hard-stop middleware
            # handle it (single large message scenario).
            return request
        compressed = self._compress(request)
        # 压缩后再记一次：界面上要看到"已经压过了、现在占用多少"，
        # 而不是一直停在触发线上。
        try:
            after = (
                [compressed.system_message, *compressed.messages]
                if compressed.system_message
                else list(compressed.messages)
            )
            self._record_usage(
                count_tokens_approximately(after, tools=compressed.tools),
                len(compressed.messages),
                compressed=True,
            )
        except Exception:  # noqa: BLE001
            logger.warning("failed to record post-compression usage", exc_info=True)
        return compressed

    #: 前端环形图读这个文件：当前上下文占用 / 窗口大小 / 触发线。
    USAGE_PATH = "/workspace/state/context-usage.json"

    def _record_usage(self, tokens: int, message_count: int, *, compressed: bool) -> None:
        """把本次调用的上下文占用写盘，供控制台展示。

        轮次限制移除后，上下文占用成了唯一的自动管理依据，用户和开发者都需要
        在界面上看到"离压缩还有多远"。
        """
        payload = {
            "schema_version": "1.0",
            "tokens": int(tokens),
            "window": int(self._window.max_tokens),
            "trigger_tokens": int(self._trigger_tokens),
            "ratio": round(tokens / max(1, self._window.max_tokens), 4),
            "messages": int(message_count),
            "compressed": compressed,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        try:
            self._workspace.write_text(
                self.USAGE_PATH, json.dumps(payload, ensure_ascii=False)
            )
        except Exception:  # noqa: BLE001 - 统计失败不能影响模型调用
            logger.warning("failed to record context usage", exc_info=True)

    def _compress(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        cutoff = len(request.messages) - self._keep_recent
        old_messages = list(request.messages[:cutoff])
        recent_messages = list(request.messages[cutoff:])

        if not old_messages:
            return request

        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        transcript = self._serialize_messages(old_messages)

        try:
            self._append_history(timestamp, len(old_messages), transcript)
        except Exception:
            logger.warning("failed to write conversation history to workspace", exc_info=True)

        try:
            summary = self._invoke_summariser(old_messages, request.system_prompt)
        except Exception:
            logger.warning("summariser call failed, keeping messages inline", exc_info=True)
            return request

        summary_message = HumanMessage(
            content=(
                f"# 对话历史摘要（{len(old_messages)}条消息已压缩至 {timestamp}）\n\n"
                f"{summary}\n\n"
                f"完整历史已保存到 {_HISTORY_PATH}，"
                f"可用 read_file 按需查阅。"
            )
        )

        new_messages = [summary_message, *recent_messages]
        logger.info(
            "context compressed: %d messages → 1 summary + %d recent",
            len(old_messages),
            len(recent_messages),
        )
        return request.override(messages=new_messages)

    def _invoke_summariser(self, messages: list[BaseMessage], system_prompt: str | None) -> str:
        context_preview = self._serialize_messages(messages)
        response = self._model.invoke(
            [
                {"role": "system", "content": _SUMMARISER_PROMPT},
                {"role": "user", "content": context_preview},
            ]
        )
        if hasattr(response, "content"):
            return str(response.content)
        return str(response)

    @staticmethod
    def _serialize_messages(messages: list[BaseMessage]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = msg.type
            content = msg.content
            # The chain of thought rides on ``additional_kwargs``, not on
            # ``content``. Without this, compressing a conversation silently
            # discards *why* each step was taken while keeping what it produced —
            # and the summary the model gets afterwards cannot recover either.
            reasoning = (getattr(msg, "additional_kwargs", None) or {}).get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                marker = f"[推理] {reasoning.strip()}"
                content = f"{content}\n{marker}" if content else marker
            tool_calls = getattr(msg, "tool_calls", None)
            name = getattr(msg, "name", None)
            if tool_calls:
                calls = [
                    {"name": tc["name"], "args": tc.get("args", {})} for tc in tool_calls
                ]
                content = f"{content}\n[tool_calls: {json.dumps(calls, ensure_ascii=False)}]"
            if name:
                parts.append(f"### {role} ({name})\n{content}")
            else:
                parts.append(f"### {role}\n{content}")
        return "\n\n".join(parts)

    def _append_history(self, timestamp: str, count: int, transcript: str) -> None:
        section = (
            f"\n## 压缩事件 {timestamp}（压缩了 {count} 条消息）\n\n"
            f"{transcript}\n"
        )
        try:
            existing = self._workspace.read_text(_HISTORY_PATH)
        except FileNotFoundError:
            existing = "# Conversation History\n\n本文件记录被压缩的对话历史，可用 read_file 按需查阅。\n"
        self._workspace.write_text(_HISTORY_PATH, existing + section)
