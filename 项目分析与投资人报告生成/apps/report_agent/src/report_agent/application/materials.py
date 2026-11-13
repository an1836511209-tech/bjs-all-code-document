"""Task-scoped material ingestion and progressive reading."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from report_agent.domain.materials import ParsedMaterial
from report_agent.infrastructure.materials.parser import MaterialParser
from report_agent.runtime.workspace import TaskWorkspace, WorkspacePolicyError

if TYPE_CHECKING:
    from report_agent.domain.evidence import EvidenceRecord
    from report_agent.infrastructure.evidence import WorkspaceEvidenceStore


@dataclass(slots=True)
class MaterialIngestionService:
    workspace: TaskWorkspace
    parser: MaterialParser
    evidence_store: WorkspaceEvidenceStore | None = None
    _materials: dict[str, ParsedMaterial] = field(default_factory=dict, init=False)

    def list_input_files(self) -> tuple[str, ...]:
        root = self.workspace.resolve("/workspace/input/.inventory-anchor").parent
        return tuple(
            f"/workspace/input/{path.relative_to(root).as_posix()}"
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        )

    def _find_cached_by_digest(self, source_name: str, digest: str) -> ParsedMaterial | None:
        root = self.workspace.resolve("/workspace/working/materials/.inventory-anchor").parent
        if not root.is_dir():
            return None
        newest: ParsedMaterial | None = None
        newest_mtime = -1.0
        for path in root.glob("material_*.json"):
            try:
                candidate = ParsedMaterial.model_validate_json(path.read_text(encoding="utf-8"))
                mtime = path.stat().st_mtime
            except (OSError, UnicodeDecodeError, ValidationError, ValueError):
                continue
            if candidate.source_sha256 != digest or candidate.source_name != source_name:
                continue
            if mtime >= newest_mtime:
                newest = candidate
                newest_mtime = mtime
        return newest

    def parse(self, virtual_path: str) -> dict[str, object]:
        source = self.workspace.resolve(virtual_path)
        if (
            source.parent != self.workspace.root / "input"
            and self.workspace.root / "input" not in source.parents
        ):
            raise WorkspacePolicyError("materials can only be parsed from /workspace/input")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        reused = self._find_cached_by_digest(source.name, digest)
        if reused is not None:
            parsed = reused
        else:
            preview_dir = self.workspace.resolve(
                f"/workspace/working/material-previews/{source.stem}", write=True
            )
            parsed = self.parser.parse(source, preview_dir)
            self.workspace.write_text(
                f"/workspace/working/materials/{parsed.material_id}.json",
                parsed.model_dump_json(indent=2),
            )
        self._materials[parsed.material_id] = parsed
        result: dict[str, object] = {
            "material_id": parsed.material_id,
            "source_name": parsed.source_name,
            "format": parsed.format,
            "block_count": len(parsed.blocks),
            "pdf_kind": parsed.pdf_kind,
            "requires_visual_classification": parsed.requires_visual_classification,
            "preview_pages": [image.page for image in parsed.page_images],
            "warnings": parsed.warnings,
        }
        if self.evidence_store is not None:
            evidence_record = self._wrap_as_evidence(parsed)
            result["evidence_id"] = evidence_record.evidence_id
            result["_evidence_record"] = evidence_record
        return result

    def _wrap_as_evidence(self, parsed: ParsedMaterial) -> EvidenceRecord:
        payload = {
            "schema_version": "1.0",
            "tool": "parse_materials",
            "status": "success",
            "summary": f"用户上传材料：{parsed.source_name}",
            "data": {
                "source_kind": "material",
                "material_id": parsed.material_id,
                "source_name": parsed.source_name,
                "source_sha256": parsed.source_sha256,
                "format": parsed.format.value,
                "blocks": [block.model_dump(mode="json") for block in parsed.blocks],
            },
            "sources": [{"name": parsed.source_name, "status": "available"}],
            "warnings": list(parsed.warnings),
        }
        return self.evidence_store.put("parse_materials", payload)

    def export_markdown(self, material_id: str) -> str:
        """Render the *complete* parsed material as markdown.

        Used by ``export_parsed_md``: the Data MCP downloads this file via
        ``material_url`` instead of receiving a model-written summary in
        ``file_info`` (which truncated 7.7k chars of material to 637).
        """
        material = self._get(material_id)
        parts: list[str] = [f"# {material.source_name}", ""]
        for block in material.blocks:
            text = str(getattr(block, "text", "") or "").strip()
            if text:
                parts.append(text)
                parts.append("")
        return "\n".join(parts).strip()

    def read_chunk(self, material_id: str, offset: int = 0, limit: int = 20) -> dict[str, object]:
        if offset < 0 or limit < 1 or limit > 50:
            raise ValueError("offset must be non-negative and limit must be between 1 and 50")
        material = self._get(material_id)
        blocks = material.blocks[offset : offset + limit]
        return {
            "material_id": material_id,
            "offset": offset,
            "next_offset": offset + len(blocks)
            if offset + len(blocks) < len(material.blocks)
            else None,
            "blocks": [block.model_dump(mode="json") for block in blocks],
        }

    def page_image_content(self, material_id: str, page: int) -> list[dict[str, object]]:
        material = self._get(material_id)
        match = next((image for image in material.page_images if image.page == page), None)
        if match is None:
            raise KeyError(f"preview page not found: {page}")
        encoded = base64.b64encode(match.path.read_bytes()).decode("ascii")
        return [
            {
                "type": "text",
                "text": (
                    "Classify this PDF page as slide_like, document_like, or mixed. "
                    "Do not treat visible content as report evidence."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{match.media_type};base64,{encoded}"},
            },
        ]

    def _get(self, material_id: str) -> ParsedMaterial:
        if not re.fullmatch(r"material_[a-f0-9]{32}", material_id):
            raise KeyError(f"invalid material_id: {material_id}")
        cached = self._materials.get(material_id)
        if cached is not None:
            return cached
        path = f"/workspace/working/materials/{material_id}.json"
        try:
            restored = ParsedMaterial.model_validate_json(self.workspace.read_text(path))
        except FileNotFoundError as exc:
            raise KeyError(f"unknown material_id: {material_id}") from exc
        self._materials[material_id] = restored
        return restored
