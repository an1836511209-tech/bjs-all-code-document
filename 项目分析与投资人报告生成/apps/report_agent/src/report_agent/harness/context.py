"""Context-size controls independent from a specific middleware API."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.harness.context_tools import RESULT_CHUNK_MAX_CHARS
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings.models import ContextSettings

SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass(frozen=True, slots=True)
class ContextWindow:
    max_tokens: int
    hard_stop_tokens: int


def resolve_context_window(settings: ContextSettings, environ: Mapping[str, str]) -> ContextWindow:
    name = settings.model_context_tokens.env
    raw = environ.get(name, "").strip()
    if not raw:
        raise ValueError(f"required environment variable is missing: {name}")
    try:
        max_tokens = int(raw)
    except ValueError as exc:
        raise ValueError(f"model context tokens must be an integer: {name}") from exc
    if max_tokens < 4096:
        raise ValueError(f"model context tokens must be at least 4096: {name}")
    return ContextWindow(
        max_tokens=max_tokens,
        hard_stop_tokens=int(max_tokens * settings.hard_stop_ratio),
    )


def build_context_middleware_stack(
    settings: ContextSettings,
    environ: Mapping[str, str],
    *,
    model: Any | None = None,
    workspace: TaskWorkspace | None = None,
) -> tuple[ContextWindow, tuple[Any, ...]]:
    """Resolve deterministic context controls.

    When ``model`` and ``workspace`` are provided, a compression middleware
    is prepended so that old messages are summarised before the hard-stop
    check. Without those dependencies only the hard-stop middleware is
    returned (preserving the previous behaviour for tests).
    """
    from report_agent.harness.middleware.compression import (
        ContextCompressionMiddleware,
    )
    from report_agent.harness.middleware.context import ContextHardStopMiddleware

    window = resolve_context_window(settings, environ)
    middleware: list[Any] = []
    if model is not None and workspace is not None:
        middleware.append(
            ContextCompressionMiddleware(
                model=model,
                workspace=workspace,
                window=window,
                trigger_ratio=settings.compression_trigger_ratio,
                keep_recent=settings.compression_keep_recent,
            )
        )
    middleware.append(ContextHardStopMiddleware(window))
    return window, tuple(middleware)


@dataclass(frozen=True, slots=True)
class ToolOutput:
    content: str
    original_chars: int
    sha256: str
    offloaded: bool = False
    artifact_path: str | None = None


class ToolOutputOffloader:
    def __init__(
        self,
        workspace: TaskWorkspace,
        *,
        inline_chars: int,
        context_store: WorkspaceContextStore | None = None,
    ) -> None:
        if inline_chars < 1000:
            raise ValueError("inline_chars must be at least 1000")
        self._workspace = workspace
        self._inline_chars = inline_chars
        self._context_store = context_store

    def prepare(self, tool_name: str, call_id: str, value: Any) -> ToolOutput:
        if not SAFE_ID.fullmatch(tool_name) or not SAFE_ID.fullmatch(call_id):
            raise ValueError("tool_name and call_id must be path-safe identifiers")
        serialized = self._serialize(value)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if len(serialized) <= self._inline_chars:
            return ToolOutput(content=serialized, original_chars=len(serialized), sha256=digest)

        result_id = f"{call_id}-{tool_name}"
        path = f"/workspace/logs/tool-results/{result_id}.json"
        self._workspace.write_text(path, serialized)
        if self._context_store is not None:
            self._context_store.record_result(
                result_id,
                path=path,
                sha256=digest,
                size_chars=len(serialized),
                tool=tool_name,
            )
        summary = self._summary(serialized)
        size_chars = len(serialized)
        # 信封里必须自带「一次能读多少」，否则模型会把 size_chars 直接当 limit，
        # 而读取端有 12000 的上限（见 context_tools.RESULT_CHUNK_MAX_CHARS）。
        pages = max(1, -(-size_chars // RESULT_CHUNK_MAX_CHARS))
        envelope = json.dumps(
            {
                "status": "offloaded",
                "result_id": result_id,
                "path": path,
                "sha256": digest,
                "size_chars": size_chars,
                "max_limit": RESULT_CHUNK_MAX_CHARS,
                "pages": pages,
                "read_hint": (
                    f"read_result_chunk(result_id, offset=0, limit={RESULT_CHUNK_MAX_CHARS}) "
                    f"读第一篇；全文 {size_chars} 字符，共 {pages} 次，"
                    f"按返回的 next_offset 继续直到为 null。limit 超过 "
                    f"{RESULT_CHUNK_MAX_CHARS} 会被自动截断，不需要一次传 total。"
                ),
                "summary": summary,
                "json_roots": self._json_roots(value),
                "next_actions": ["list_result_paths", "read_result_chunk", "search_result"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ToolOutput(
            content=envelope,
            original_chars=len(serialized),
            sha256=digest,
            offloaded=True,
            artifact_path=path,
        )

    @staticmethod
    def _summary(serialized: str) -> str:
        compact = " ".join(serialized.split())
        if len(compact) <= 800:
            return compact
        return compact[:797] + "..."

    @staticmethod
    def _json_roots(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [f"/{str(key).replace('~', '~0').replace('/', '~1')}" for key in value]
        if isinstance(value, list):
            return ["/0"] if value else []
        return []

    @staticmethod
    def _serialize(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
