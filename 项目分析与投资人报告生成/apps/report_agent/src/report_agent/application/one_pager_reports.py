"""Render and publish one-pager BP documents in the agent workspace.

The service is deliberately narrow compared with :class:`WordReportService`:
there are no comments to manage, no per-section edits, just a *parse →
fill → validate → stage → publish* pipeline. Results are tracked in-process
so :func:`validate_and_publish_one_pager` can look up an artifact by id and
hand it to the same MinIO callback used by the report-agent deployment.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from report_agent.application.one_pager_execution import write_json
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.documents import DocumentArtifact, DocumentIssue
from report_agent.domain.one_pager import BusinessType, OnePagerContent
from report_agent.infrastructure.word.one_pager_authoring import (
    OnePagerAuthor,
    OnePagerRenderResult,
    resolve_template,
)
from report_agent.infrastructure.word.one_pager_md_parser import (
    parse_one_pager_markdown,
)
from report_agent.infrastructure.word.rendering import LibreOfficeRenderer, RenderResult
from report_agent.infrastructure.word.validation import WordReportValidator
from report_agent.runtime.workspace import TaskWorkspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OnePagerReportResult:
    """What :meth:`OnePagerReportService.render` returns."""

    artifact_id: str
    sha256: str
    path: str
    business_type: BusinessType
    valid: bool
    issues: tuple[DocumentIssue, ...] = ()
    pages: int | None = None
    notes: tuple[str, ...] = ()
    investor_rows: int = 0
    filled_placeholders: tuple[str, ...] = ()
    document_artifact: DocumentArtifact | None = None
    published: PublishedArtifact | None = None

    def has_warnings(self) -> bool:
        return bool(self.notes) or not self.valid or any(
            issue.code == "PAGE_LIMIT_EXCEEDED" for issue in self.issues
        )


def _artifact_id(sha256: str) -> str:
    return f"artifact_{sha256[:32]}"


def _notes_for_render(render: OnePagerRenderResult, *, pages: int | None) -> tuple[str, ...]:
    notes = list(render.notes)
    if pages is not None and pages > 1:
        notes.append(
            f"渲染后 PDF 共 {pages} 页，超过 1 页目标。可通过收紧投资人行数或压缩亮点段长度优化。"
        )
    return tuple(notes)


def _issues_for_render(*, valid: bool, issues: tuple[DocumentIssue, ...], pages: int | None) -> tuple[DocumentIssue, ...]:
    if valid and pages is not None and pages > 1:
        return issues + (
            DocumentIssue(
                code="PAGE_LIMIT_EXCEEDED",
                message=f"one-pager rendered to {pages} pages; expected single page",
            ),
        )
    return issues


class OnePagerReportService:
    """Compose parse → fill → validate → stage → publish for one-pager output."""

    def __init__(
        self,
        workspace: TaskWorkspace,
        *,
        author: OnePagerAuthor | None = None,
        validator: WordReportValidator | None = None,
        renderer: LibreOfficeRenderer | None = None,
        skill_version: str = "",
        restore_persisted: bool = False,
    ) -> None:
        self.workspace = workspace
        self.author = author or OnePagerAuthor()
        self.validator = validator or WordReportValidator()
        self.renderer = renderer
        self.skill_version = skill_version
        self.restore_persisted = restore_persisted
        self._registry: dict[str, OnePagerReportResult] = {}

    def render(
        self,
        *,
        md_path: str,
        business_type: BusinessType,
        report_id: str,
        filename: str,
    ) -> OnePagerReportResult:
        md_text = self.workspace.read_text(md_path)
        content: OnePagerContent = parse_one_pager_markdown(
            md_text, business_type=business_type, report_id=report_id
        )
        render_result = self.author.render(content)
        target_path = f"/workspace/output/{filename}"
        record = self.workspace.write_bytes(target_path, render_result.content)
        sha256 = record.sha256
        artifact_id = _artifact_id(sha256)
        resolved = self.workspace.resolve(target_path)

        issues = self.validator.validate(resolved, expected_comments=0)
        pages: int | None = None
        if self.renderer is not None:
            try:
                render_paths = self.workspace.resolve("/workspace/working/renders")
                render_paths.mkdir(parents=True, exist_ok=True)
                libo: RenderResult = self.renderer.render(resolved, render_paths)
                pages = len(libo.pages)
            except Exception as exc:  # LibreOffice missing / failure → degrade gracefully
                logger.warning("one-pager render skipped: %s", exc)
                pages = None

        all_issues = _issues_for_render(valid=not issues, issues=tuple(issues), pages=pages)
        notes = _notes_for_render(render_result, pages=pages)
        document_artifact = DocumentArtifact(
            artifact_id=artifact_id,
            path=target_path,
            sha256=sha256,
            skill_version=self.skill_version,
            comment_count=0,
            valid=not issues,
            issues=tuple(issues),
        )
        result = OnePagerReportResult(
            artifact_id=artifact_id,
            sha256=sha256,
            path=target_path,
            business_type=business_type,
            valid=not all_issues,
            issues=all_issues,
            pages=pages,
            notes=notes,
            investor_rows=render_result.investor_rows,
            filled_placeholders=render_result.filled_placeholders,
            document_artifact=document_artifact,
        )
        self._registry[artifact_id] = result
        manifest = {
            "schema_version": "1.0",
            "artifact_id": artifact_id,
            "report_id": report_id,
            "business_type": business_type.value,
            "template": str(render_result.template),
            "path": target_path,
            "sha256": sha256,
            "pages": pages,
            "filled_placeholders": list(render_result.filled_placeholders),
            "investor_rows": render_result.investor_rows,
            "unresolved_placeholders": list(render_result.unresolved_placeholders),
            "notes": list(notes),
            "issues": [issue.model_dump(mode="json") for issue in all_issues],
            "document_artifact": document_artifact.model_dump(mode="json"),
        }
        if self.restore_persisted:
            write_json(self.workspace, target_path + ".render.json", manifest)
        else:
            self.workspace.write_text(target_path + ".render.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return result

    def artifact(self, artifact_id: str) -> OnePagerReportResult:
        try:
            return self._registry[artifact_id]
        except KeyError as exc:
            if self.restore_persisted:
                for path in self.workspace.resolve("/workspace/output").glob("*.render.json"):
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    if manifest.get("artifact_id") != artifact_id:
                        continue
                    source = self.workspace.resolve(manifest["path"])
                    if not source.is_file() or hash_bytes(source.read_bytes()) != manifest["sha256"]:
                        raise ValueError("渲染产物缺失或内容已变化，请重新渲染") from exc
                    result = OnePagerReportResult(
                        artifact_id=artifact_id, sha256=manifest["sha256"], path=manifest["path"],
                        business_type=BusinessType(manifest["business_type"]),
                        valid=not manifest["issues"],
                        issues=tuple(DocumentIssue.model_validate(i) for i in manifest["issues"]),
                        pages=manifest.get("pages"), notes=tuple(manifest.get("notes", [])),
                        investor_rows=manifest.get("investor_rows", 0),
                        filled_placeholders=tuple(manifest.get("filled_placeholders", [])),
                        document_artifact=DocumentArtifact.model_validate(manifest["document_artifact"]),
                        published=PublishedArtifact.model_validate(manifest["published"]) if manifest.get("published") else None,
                    )
                    self._registry[artifact_id] = result
                    return result
            raise LookupError(f"unknown one-pager artifact: {artifact_id}") from exc

    def publish(
        self,
        artifact_id: str,
        publish: Callable[[str], PublishedArtifact],
    ) -> OnePagerReportResult:
        result = self.artifact(artifact_id)
        if result.published is not None:
            return result
        # 发布器只接受 staging/ 根目录下、已登记为 staged 的 docx；渲染结果写在
        # output/，必须先 stage 一次再发布，否则会被 WorkspacePolicyError 拒绝。
        staged = self.workspace.stage(result.path)
        published = publish(staged.path)
        updated = OnePagerReportResult(
            artifact_id=result.artifact_id,
            sha256=result.sha256,
            path=result.path,
            business_type=result.business_type,
            valid=result.valid,
            issues=result.issues,
            pages=result.pages,
            notes=result.notes,
            investor_rows=result.investor_rows,
            filled_placeholders=result.filled_placeholders,
            document_artifact=result.document_artifact,
            published=published,
        )
        self._registry[artifact_id] = updated
        if self.restore_persisted:
            manifest_path = result.path + ".render.json"
            manifest = json.loads(self.workspace.read_text(manifest_path))
            manifest["published"] = published.model_dump(mode="json")
            write_json(self.workspace, manifest_path, manifest)
        return updated


def template_for(business_type: BusinessType) -> Path:
    """Convenience wrapper used by tooling that only has a business type."""
    return resolve_template(business_type)


def compute_artifact_id(sha256: str) -> str:
    return _artifact_id(sha256)


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
