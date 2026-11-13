"""Expose task-scoped material operations to the Agent."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.materials import MaterialIngestionService


def _locator_label(locator: dict[str, Any]) -> str:
    """Human locator for a material block: 「材料第 5 页」/「材料第 12 段」.

    Slide scans and PDFs locate by page; Word/plain text locate by paragraph.
    Returns an empty string when the parser supplied neither, so the caller can
    fall back to a plain 「原文：」 note instead of inventing a location.
    """
    page = locator.get("page")
    if isinstance(page, int) and page > 0:
        return f"材料第 {page} 页"
    paragraph = locator.get("paragraph")
    if isinstance(paragraph, int) and paragraph > 0:
        return f"材料第 {paragraph} 段"
    return ""


def build_material_tools(
    service: MaterialIngestionService,
    context_store: WorkspaceContextStore | None = None,
    *,
    upload_markdown=None,
    task_id: str = "",
) -> tuple[StructuredTool, ...]:
    def list_workspace_files() -> str:
        return json.dumps(service.list_input_files(), ensure_ascii=False)

    def parse_materials(path: str) -> str:
        result = service.parse(path)
        evidence_record = result.pop("_evidence_record", None)
        if context_store is not None:
            if evidence_record is not None:
                context_store.record_evidence(evidence_record, json_roots=("/data",))
            context_store.record_material(
                str(result["material_id"]), str(result["source_name"])
            )
        return json.dumps(result, ensure_ascii=False, default=str)

    def read_material_chunk(material_id: str, offset: int = 0, limit: int = 20) -> str:
        chunk = service.read_chunk(material_id, offset, limit)
        # 给每个 block 附一个可直接粘贴的 src 标记：kind=material，pointer 指向
        # /data/blocks/{index}/text，note 用「出处 + 原文」。
        #
        # 出处必须带定位：审阅者要能按页（幻灯片/PDF）或按段（文档）翻回原文。
        # 只写「原文：…」时，客户拿到 Word 批注无从核对这一页在哪。
        blocks = chunk.get("blocks") or []
        for local_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            index = int(chunk.get("offset") or 0) + local_index
            quote = " ".join(text.split())[:120]
            where = _locator_label(block.get("locator") or {})
            note = f"出处：{where}；原文：{quote}" if where else f"原文：{quote}"
            block["src"] = (
                f"<!-- src: material parse_materials /data/blocks/{index}/text ; "
                f"{note} -->"
            )
        return json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))

    def inspect_page_image(material_id: str, page: int) -> list[dict[str, Any]]:
        return service.page_image_content(material_id, page)

    def export_parsed_md(material_id: str) -> str:
        """Upload the complete parsed material and return a download URL.

        ``extract_project_profile`` accepts either ``material_url`` (HTTP URL
        the Data MCP downloads) or ``file_info`` (inline text). Passing the
        model's own summary as ``file_info`` loses most of the material, so the
        preferred path is to export the full markdown here and pass the URL.
        """
        if upload_markdown is None:
            raise ValueError(
                "对象存储未配置，无法生成 material_url。"
                "请改用 file_info，并传入 export_material_text 返回的完整文本。"
            )
        markdown = service.export_markdown(material_id)
        key = f"exports/{task_id or 'task'}/{material_id}.md"
        url, expires = upload_markdown(key, markdown)
        return json.dumps(
            {
                "material_url": url,
                "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else str(expires),
                "chars": len(markdown),
                "usage": "把 material_url 原样传给 extract_project_profile；expires_at 前有效",
            },
            ensure_ascii=False,
        )

    def export_material_text(material_id: str) -> str:
        """Return the complete parsed text for ``file_info`` (no object storage)."""
        text = service.export_markdown(material_id)
        return json.dumps(
            {
                "material_id": material_id,
                "chars": len(text),
                "text": text,
                "usage": "把 text 原样传给 extract_project_profile 的 file_info，不要概括或截断",
            },
            ensure_ascii=False,
        )

    return (
        StructuredTool.from_function(
            list_workspace_files,
            name="list_workspace_files",
            description="List user-provided files in the current task input directory.",
        ),
        StructuredTool.from_function(
            parse_materials,
            name="parse_materials",
            description=(
                "Parse one input file and return a material_id plus routing metadata. "
                "Also returns evidence_id when the service has an evidence store; that "
                "evidence_id MUST be used in EvidenceCitation for facts drawn from this "
                "material, with locators like /data/blocks/N/text pointing into the stored "
                "parsed blocks. Use read_material_chunk to discover block indices first."
            ),
        ),
        StructuredTool.from_function(
            read_material_chunk,
            name="read_material_chunk",
            description=(
                "Read a bounded chunk of parsed material with page, slide, sheet, or "
                "cell locators. limit is the number of blocks per call (default 20); "
                "prefer 10-20 blocks per call so results stay inline instead of being "
                "offloaded."
            ),
        ),
        StructuredTool.from_function(
            inspect_page_image,
            name="inspect_page_image",
            description="View a rendered PDF preview page and classify its visual document type.",
        ),
        StructuredTool.from_function(
            export_parsed_md,
            name="export_parsed_md",
            description=(
                "把解析后的完整材料上传对象存储，返回 presigned material_url。"
                "extract_project_profile 需要材料全文时优先用它；"
                "对象存储未配置时会报错，此时改用 export_material_text + file_info。"
            ),
        ),
        StructuredTool.from_function(
            export_material_text,
            name="export_material_text",
            description=(
                "返回解析后的完整材料文本（不依赖对象存储）。"
                "把返回的 text 原样传给 extract_project_profile 的 file_info，不要概括或截断。"
            ),
        ),
    )
