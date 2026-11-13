"""Indexed workspace context tools exposed to the primary Agent."""

from __future__ import annotations

import json
import re

from langchain_core.tools import StructuredTool

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.skills.catalog import SkillCatalog

#: 单次 ``read_result_chunk`` 最多返回的字符数。
#:
#: 模型的常见动作是把落盘信封里的 ``size_chars`` 直接当 ``limit`` 传（例如一次
#: 13615 字符的材料块），而这里的上限是 12000。旧实现直接抛 ValueError，整轮
#: 运行被判失败。现在超限只截断不报错，返回的 ``next_offset`` 让模型继续翻页；
#: 同一个常量也写进落盘信封（``harness/context.ToolOutputOffloader``），
#: 让模型一开始就知道单次上限和需要几次读完。
RESULT_CHUNK_MAX_CHARS = 12_000


def build_context_tools(
    store: WorkspaceContextStore,
    workspace: TaskWorkspace,
    reference_names: tuple[str, ...],
) -> tuple[StructuredTool, ...]:
    allowed = frozenset(reference_names)

    def get_working_context() -> str:
        return store.working_memory()

    def load_skill_reference(name: str) -> str:
        if name not in allowed:
            raise ValueError(f"unknown skill reference: {name}")
        content = SkillCatalog.read_staged_reference(workspace, name)
        store.mark_reference_loaded(name)
        return content

    def list_context_indexes() -> str:
        return json.dumps(
            {
                "run_state": store.RUN_STATE,
                "data_index": store.DATA_INDEX,
                "report_content": store.REPORT_STATE,
                "artifact_index": store.ARTIFACT_INDEX,
                "result_index": store.RESULT_INDEX,
                "working_memory": store.WORKING_MEMORY,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def list_result_paths(result_id: str) -> str:
        record = store.result_record(result_id)
        content = workspace.read_text(record["path"])
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            roots: list[str] = []
        else:
            roots = (
                [f"/{str(key).replace('~', '~0').replace('/', '~1')}" for key in value]
                if isinstance(value, dict)
                else (["/0"] if isinstance(value, list) and value else [])
            )
        return json.dumps({"result_id": result_id, "paths": roots}, ensure_ascii=False)

    def read_result_chunk(result_id: str, offset: int = 0, limit: int = 4000) -> str:
        if offset < 0 or limit < 1:
            raise ValueError(
                "invalid result chunk range: offset must be >= 0 and limit must be >= 1 "
                f"(got offset={offset}, limit={limit})"
            )
        # 模型往往把落盘信封里的 size_chars 直接当 limit（例如 13615）。超限时
        # 截断到上限而不是抛错：抛错会让整轮运行判失败，而截断只是多一次翻页。
        requested = limit
        limit = min(limit, RESULT_CHUNK_MAX_CHARS)
        record = store.result_record(result_id)
        content = workspace.read_text(record["path"])
        end = min(len(content), offset + limit)
        return json.dumps(
            {
                "result_id": result_id,
                "offset": offset,
                "content": content[offset:end],
                "next_offset": end if end < len(content) else None,
                "total_chars": len(content),
                "limit": limit,
                "max_limit": RESULT_CHUNK_MAX_CHARS,
                "limit_clamped": requested > limit,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def search_result(result_id: str, query: str, mode: str = "literal", limit: int = 20) -> str:
        if mode not in {"literal", "regex"} or not query or limit < 1 or limit > 100:
            raise ValueError("invalid result search request")
        record = store.result_record(result_id)
        lines = workspace.read_text(record["path"]).splitlines() or [""]
        pattern = re.compile(query) if mode == "regex" else None
        matches = []
        for number, line in enumerate(lines, start=1):
            if pattern.search(line) if pattern else query in line:
                matches.append({"line": number, "text": line[:1000]})
                if len(matches) >= limit:
                    break
        return json.dumps({"result_id": result_id, "matches": matches}, ensure_ascii=False)

    return (
        StructuredTool.from_function(
            get_working_context,
            name="get_working_context",
            description="Read the current program-maintained task snapshot after recovery.",
        ),
        StructuredTool.from_function(
            load_skill_reference,
            name="load_skill_reference",
            description=f"Load one staged Skill reference by name. Available: {', '.join(reference_names)}.",
        ),
        StructuredTool.from_function(
            list_context_indexes,
            name="list_context_indexes",
            description="List authoritative workspace state and index paths.",
        ),
        StructuredTool.from_function(
            list_result_paths,
            name="list_result_paths",
            description="List top-level JSON paths in an offloaded generic tool result.",
        ),
        StructuredTool.from_function(
            read_result_chunk,
            name="read_result_chunk",
            description=(
                "Read a bounded character chunk from an offloaded tool result by "
                "result_id. limit is characters per call (default 4000); values above "
                f"{RESULT_CHUNK_MAX_CHARS} are clamped to {RESULT_CHUNK_MAX_CHARS} instead "
                "of failing, and the reply reports limit_clamped. Pass the returned "
                "next_offset as offset to keep paging until next_offset is null."
            ),
        ),
        StructuredTool.from_function(
            search_result,
            name="search_result",
            description="Search an offloaded tool result without loading the entire file.",
        ),
    )
