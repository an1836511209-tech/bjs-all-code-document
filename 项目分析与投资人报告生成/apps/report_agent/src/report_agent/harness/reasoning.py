"""Keep what the model thought, instead of paying for it and throwing it away.

Reasoning models return their chain of thought next to the answer, but the
field name is provider-specific: Qwen and DeepSeek call it
``reasoning_content``, the OpenAI standard calls it ``reasoning``, Anthropic
returns thinking blocks. The OpenAI-compatible client in this stack maps none
of them back onto the message, so the tokens are billed and the trace is
dropped on the floor.

This module captures that text, writes it into the task workspace, and builds a
head-and-tail excerpt the agent can carry into its next turn. The excerpt is a
plain string cut — there is no summariser call — so the only cost is the tokens
it carries.

The captured text deliberately stays **out** of the message. Sending it back
inside an assistant turn changes the request shape every provider sees (and
DeepSeek rejects requests whose reasoning was not echoed in full), so the
digest travels in the system message instead — one shape for every provider.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

#: Response fields that carry a chain of thought, in the order we prefer them.
REASONING_FIELDS = ("reasoning_content", "reasoning")

REASONING_DIR = "/workspace/state/reasoning"
DECISION_LOG = "/workspace/state/decision-log.jsonl"

#: Marker left where a chain of thought was cut. The model has to see that it
#: is reading an excerpt, or it will treat a fragment as the whole argument.
EXCERPT_MARKER = "..."


def _snap_head(text: str, limit: int) -> str:
    """Cut at ``limit``, preferring the last line break so no sentence is cut open."""
    cut = text[:limit]
    newline = cut.rfind("\n")
    return cut[:newline] if newline > limit * 0.5 else cut


def _snap_tail(text: str, limit: int) -> str:
    """Take the last ``limit`` characters, starting at a line break when possible."""
    cut = text[-limit:]
    newline = cut.find("\n")
    return cut[newline + 1:] if 0 <= newline < limit * 0.5 else cut


def _excerpt(body: str, *, head: int, tail: int) -> tuple[str, int]:
    """Cut ``body`` down to its opening and closing parts.

    A reasoning trace opens by restating the task and closes with the decision,
    so keeping only the head throws away the part that matters. Both cuts snap
    to line breaks, and the gap is marked so the reader knows the middle is
    missing. Returns the excerpt plus how many characters were dropped.
    """
    if len(body) <= head + tail:
        return body, 0
    opening = _snap_head(body, head)
    closing = _snap_tail(body, tail)
    omitted = max(0, len(body) - len(opening) - len(closing))
    return (
        f"{opening}\n"
        f"{EXCERPT_MARKER}（中间省略 {omitted} 字）{EXCERPT_MARKER}\n"
        f"{closing}",
        omitted,
    )


@dataclass(frozen=True, slots=True)
class ReasoningRecord:
    """One captured chain of thought.

    The excerpt is cut **once at capture time** and cached, so building the
    next request is pure string joining — no file reads, no model calls.
    """

    seq: int
    chars: int
    path: str
    excerpt: str
    omitted: int


def extract_reasoning(response: Any) -> str:
    """Pull the chain of thought out of a chat-completion response."""
    payload: Any = response
    if not isinstance(payload, dict):
        dump = getattr(payload, "model_dump", None)
        payload = dump() if callable(dump) else {}
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        return ""
    for field in REASONING_FIELDS:
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):  # Anthropic-style thinking blocks
            parts = [
                str(block.get("thinking") or block.get("text") or "")
                for block in value
                if isinstance(block, dict)
            ]
            text = "\n".join(part for part in parts if part.strip())
            if text.strip():
                return text
    return ""


class ReasoningStore:
    """Captured chains of thought for one run."""

    def __init__(
        self,
        workspace: Any,
        run_id: str,
        *,
        max_chars: int = 8000,
        keep_in_memory: int = 200,
        excerpt_chars: int = 500,
        excerpt_head_ratio: float = 0.3,
    ) -> None:
        self._workspace = workspace
        self._run_id = run_id or "unknown"
        self._max_chars = max_chars
        self._keep = keep_in_memory
        self._excerpt_chars = max(2, excerpt_chars)
        self._excerpt_head = max(1, int(self._excerpt_chars * excerpt_head_ratio))
        self._excerpt_tail = max(1, self._excerpt_chars - self._excerpt_head)
        self._records: list[ReasoningRecord] = []

    @property
    def records(self) -> tuple[ReasoningRecord, ...]:
        return tuple(self._records)

    def record(self, text: str) -> ReasoningRecord | None:
        """Persist one chain of thought, cache its excerpt and index it."""
        body = (text or "").strip()
        if not body:
            return None
        stored = body[: self._max_chars]
        seq = len(self._records) + 1
        path = f"{REASONING_DIR}/{self._run_id}/{seq:04d}.md"
        try:
            self._workspace.write_text(
                path,
                f"# 第 {seq} 步的推理记录\n\n{stored}\n",
            )
        except Exception:  # noqa: BLE001 - a lost capture must not fail the run
            logger.warning("failed to persist reasoning record %s", seq, exc_info=True)
            return None
        excerpt, omitted = _excerpt(
            stored, head=self._excerpt_head, tail=self._excerpt_tail
        )
        record = ReasoningRecord(
            seq=seq,
            chars=len(body),
            path=path,
            excerpt=excerpt,
            omitted=omitted,
        )
        self._records.append(record)
        del self._records[: max(0, len(self._records) - self._keep)]
        self._append_index(record)
        return record

    def _append_index(self, record: ReasoningRecord) -> None:
        """One JSON line per captured step — the structured view the console reads.

        ``preview`` carries the opening of the thought so a list/时间线 can render
        without opening every ``.md`` file; the full text stays next to it.
        """
        line = json.dumps(
            {
                "seq": record.seq,
                "chars": record.chars,
                "path": record.path,
                "preview": record.excerpt.replace("\n", " ")[:200],
                "omitted": record.omitted,
                "at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        try:
            existing = self._workspace.read_text(DECISION_LOG)
        except FileNotFoundError:
            existing = ""
        except Exception:  # noqa: BLE001
            logger.warning("failed to read decision log", exc_info=True)
            return
        try:
            self._workspace.write_text(DECISION_LOG, existing + line + "\n")
        except Exception:  # noqa: BLE001
            logger.warning("failed to append decision log", exc_info=True)

    def excerpt_block(self, *, limit: int | None = None) -> str:
        """Every captured step, each carrying its own head-and-tail excerpt.

        ``limit=None`` keeps every step; an integer keeps only the last N.
        Joining cached excerpts is pure string work — no summariser call, no
        file reads — so the only cost is the tokens it carries.
        """
        if not self._records:
            return ""
        records = self._records if limit is None else self._records[-limit:]
        lines: list[str] = []
        for record in records:
            if not record.excerpt.strip():
                continue
            label = (
                f"全文 {record.chars} 字，本节选保留开头 {self._excerpt_head} 字"
                f"与结尾 {self._excerpt_tail} 字"
                if record.omitted
                else f"全文 {record.chars} 字，未截断"
            )
            lines.append(f"[第 {record.seq} 步 · {label}]\n{record.excerpt}")
        if not lines:
            return ""
        return (
            "## 推理记录（每一步各取一段节选）\n"
            "（模型自述的分析过程，仅供参照，不是已核实的结论，写正文仍以证据为准。\n"
            f" 每一步内部标有 {EXCERPT_MARKER} 的位置表示该步原文在此被截断；"
            f"该步完整原文在 {REASONING_DIR}/<run_id>/ 下，可用 read_file 查看。）\n\n"
            + "\n\n".join(lines)
        )


def take_reasoning(chunk: Any, parts: list[str]) -> None:
    """Collect one streamed chunk's reasoning into ``parts``.

    ``_astream`` yields ``ChatGenerationChunk`` (a message inside a wrapper), so
    unwrap before looking for the field.

    The field is **left on the chunk** on purpose: ``AIMessageChunk`` addition
    concatenates string values in ``additional_kwargs``, so the assembled
    message carries the full chain of thought, and
    :meth:`ReasoningChatOpenAI._get_request_payload` echoes it back to the
    provider on the next turn.

    Echo shape matters: a ``{"type":"reasoning"}`` *content block* is rejected
    with HTTP 400 by DashScope, while the flat ``reasoning_content`` key is
    accepted — and echoing it cut a probe's reasoning tokens from 1179 to 37,
    i.e. the model stopped re-deriving what it had already worked out.
    """
    target = getattr(chunk, "message", chunk)
    kwargs = getattr(target, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return
    for field in REASONING_FIELDS:
        value = kwargs.get(field)
        if isinstance(value, str) and value:
            parts.append(value)
            return


#: Safety valve for echoing. Measured runs sit far below this (longest single
#: step 3,030 chars, average 323), so it never trims a normal turn — it only
#: stops one runaway turn from bloating every later request.
MAX_ECHO_CHARS = 6000


def _reasoning_of(message: Any) -> str:
    """The chain of thought a message carries, ready to echo back."""
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return ""
    for field in REASONING_FIELDS:
        value = kwargs.get(field)
        if isinstance(value, str) and value.strip():
            return value[:MAX_ECHO_CHARS]
    return ""


#: ``langchain_openai`` drops ``reasoning_content`` from streamed deltas — its
#: module docstring says so outright ("reasoning_content, reasoning_details ...
#: are not extracted"). The non-streaming path is covered by
#: ``_create_chat_result``, but the console subscribes an event bus, so every
#: real run streams and used to lose the capture completely.
_STREAM_PATCHED = False


def install_stream_reasoning_patch() -> None:
    """Teach the streaming converter to keep the chain of thought."""
    global _STREAM_PATCHED
    if _STREAM_PATCHED:
        return
    from langchain_openai.chat_models import base as _base

    original = _base._convert_delta_to_message_chunk

    def patched(_dict: Any, default_class: Any) -> Any:
        chunk = original(_dict, default_class)
        for field in REASONING_FIELDS:
            value = _dict.get(field)
            if isinstance(value, str) and value:
                chunk.additional_kwargs[field] = value
                break
        return chunk

    _base._convert_delta_to_message_chunk = patched
    _STREAM_PATCHED = True


class ReasoningChatOpenAI(ChatOpenAI):
    """``ChatOpenAI`` that keeps the model's chain of thought.

    ``_create_chat_result`` covers the non-streaming paths; ``_astream`` and
    ``_stream`` cover streaming, which is what the console actually uses.
    """

    def __init__(self, *args: Any, store: ReasoningStore | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reasoning_store = store
        if store is not None:
            install_stream_reasoning_patch()

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> Any:
        result = super()._create_chat_result(response, generation_info)
        store = self._reasoning_store
        if store is None:
            return result
        try:
            text = extract_reasoning(response)
        except Exception:  # noqa: BLE001 - never break the run over a capture
            logger.warning("failed to extract reasoning", exc_info=True)
            return result
        if text.strip():
            store.record(text)
        return result

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict:
        """Echo each assistant turn's chain of thought back to the provider.

        ``langchain_openai`` drops ``reasoning_content`` when converting a
        message, so a captured chain of thought would never reach the next
        request on its own. Putting it back here keeps the rest of the payload
        untouched and uses the flat key the provider accepts.
        """
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        entries = payload.get("messages")
        if not isinstance(entries, list):
            return payload
        try:
            sources = self._convert_input(input_).to_messages()
        except Exception:  # noqa: BLE001 - echoing is best effort
            return payload
        for index, message in enumerate(sources):
            if index >= len(entries):
                break
            text = _reasoning_of(message)
            if not text:
                continue
            entry = entries[index]
            if isinstance(entry, dict) and entry.get("role") == "assistant":
                entry["reasoning_content"] = text
        return payload

    async def _astream(self, messages: Any, stop: Any = None, run_manager: Any = None,
                       **kwargs: Any) -> Any:
        store = self._reasoning_store
        parts: list[str] = []
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            if store is not None:
                take_reasoning(chunk, parts)
            yield chunk
        if store is not None and parts:
            store.record("".join(parts))

    def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None,
                **kwargs: Any) -> Any:
        store = self._reasoning_store
        parts: list[str] = []
        for chunk in super()._stream(messages, stop, run_manager, **kwargs):
            if store is not None:
                take_reasoning(chunk, parts)
            yield chunk
        if store is not None and parts:
            store.record("".join(parts))


def reasoning_dir_for(run_id: str) -> Path:
    """Host path of the reasoning captures for a run (for humans to browse)."""
    return Path(REASONING_DIR.strip("/")) / (run_id or "unknown")
