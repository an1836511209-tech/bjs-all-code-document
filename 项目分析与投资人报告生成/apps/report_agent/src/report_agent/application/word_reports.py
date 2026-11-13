"""Validated Word artifact lifecycle inside a task workspace."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from docx import Document

from report_agent.domain.documents import DocumentArtifact
from report_agent.domain.report_content import ReportContent, ReportStatus
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.infrastructure.word import (
    LibreOfficeRenderer,
    WordReportAuthor,
    WordReportValidator,
)
from report_agent.runtime.workspace import TaskWorkspace


class WordReportService:
    def __init__(
        self,
        workspace: TaskWorkspace,
        evidence_store: WorkspaceEvidenceStore,
        *,
        visual_review_required: bool = True,
    ) -> None:
        self.workspace = workspace
        self.evidence_store = evidence_store
        self.author = WordReportAuthor()
        self.validator = WordReportValidator()
        self.renderer = LibreOfficeRenderer()
        self.visual_review_required = visual_review_required
        self._artifacts: dict[str, DocumentArtifact] = {}

    def create(
        self,
        content: ReportContent,
        *,
        filename: str,
        skill_version: str,
        report_date: date | None = None,
    ) -> DocumentArtifact:
        if content.status != ReportStatus.READY:
            raise ValueError("only validated report content can produce Word artifacts")
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.lower().endswith(".docx"):
            raise ValueError("filename must be a safe DOCX basename")
        with tempfile.TemporaryDirectory() as temporary:
            built = Path(temporary) / safe_name
            comment_count = self.author.create(
                content, self.evidence_store, built, report_date=report_date
            )
            # 写作时随正文落盘的 src 标记在这里变成批注：锚点就是生成它的
            # 那个段落，不经过 match_text 子串查找，所以不会错位或漏掉。
            src_comments = self.author.take_src_comments()
            if src_comments:
                pairs = Path(temporary) / "src-comments.json"
                pairs.write_text(
                    json.dumps(
                        [[text, comment] for text, comment in src_comments],
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                with_comments = Path(temporary) / f"src-{safe_name}"
                self._run_word_script(
                    "comments_add.py",
                    str(built),
                    "--out",
                    str(with_comments),
                    "--author",
                    "投资报告智能体",
                    "--add-json",
                    str(pairs),
                )
                if with_comments.is_file():
                    built = with_comments
                    comment_count += len(src_comments)
            issues = self.validator.validate(built, expected_comments=comment_count)
            if issues:
                raise ValueError(
                    "Word validation failed: " + "; ".join(issue.code for issue in issues)
                )
            record = self.workspace.write_bytes(
                f"/workspace/output/{safe_name}", built.read_bytes()
            )
        artifact = DocumentArtifact(
            artifact_id=f"artifact_{uuid4().hex}",
            path=record.path,
            sha256=record.sha256,
            skill_version=skill_version,
            comment_count=comment_count,
            valid=True,
        )
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def artifact(self, artifact_id: str) -> DocumentArtifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise ValueError("unknown artifact_id") from exc

    def edit(self, artifact_id: str, operations: list[dict[str, str]]) -> DocumentArtifact:
        source = self.artifact(artifact_id)
        document = Document(str(self.workspace.resolve(source.path)))
        for operation in operations:
            if operation.get("action") != "replace_text":
                raise ValueError("supported edit action: replace_text")
            needle, replacement = operation.get("contains", ""), operation.get("text", "")
            if not needle:
                raise ValueError("replace_text requires contains")
            changed = False
            for paragraph in [
                *document.paragraphs,
                *(
                    p
                    for table in document.tables
                    for row in table.rows
                    for cell in row.cells
                    for p in cell.paragraphs
                ),
            ]:
                if needle in paragraph.text:
                    for run in paragraph.runs:
                        if needle in run.text:
                            run.text = run.text.replace(needle, replacement)
                            changed = True
            if not changed:
                raise ValueError(f"text not found: {needle}")
        filename = f"{Path(source.path).stem}-{uuid4().hex[:8]}.docx"
        with tempfile.TemporaryDirectory() as temporary:
            built = Path(temporary) / filename
            document.save(str(built))
            issues = self.validator.validate(built, expected_comments=source.comment_count)
            if issues:
                raise ValueError("Word validation failed: " + "; ".join(i.code for i in issues))
            record = self.workspace.write_bytes(f"/workspace/output/{filename}", built.read_bytes())
        artifact = DocumentArtifact(
            artifact_id=f"artifact_{uuid4().hex}",
            path=record.path,
            sha256=record.sha256,
            skill_version=source.skill_version,
            comment_count=source.comment_count,
            valid=True,
        )
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def validate_and_stage(self, artifact_id: str):
        artifact = self.artifact(artifact_id)
        return self.stage(artifact.path)

    def manage_comments(
        self, artifact_id: str, operations: list[dict[str, object]]
    ) -> dict[str, object] | DocumentArtifact:
        source = self.artifact(artifact_id)
        source_path = self.workspace.resolve(source.path)
        if len(operations) == 1 and operations[0].get("action") == "extract":
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "comments.json"
                self._run_word_script("comments_extract.py", str(source_path), "--out", str(output))
                return json.loads(output.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            current = source_path
            for index, operation in enumerate(operations):
                action = str(operation.get("action", ""))
                output = Path(temporary) / f"comments-{index}.docx"
                if action == "add":
                    contains, comment = (
                        str(operation.get("contains", "")),
                        str(operation.get("text", "")),
                    )
                    if not contains or not comment:
                        raise ValueError("add requires contains and text")
                    self._run_word_script(
                        "comments_add.py",
                        str(current),
                        "--out",
                        str(output),
                        "--author",
                        str(operation.get("author") or "投资报告智能体"),
                        "--add",
                        f"{contains}={comment}",
                    )
                elif action in {"replace", "append", "resolve"}:
                    comment_id = operation.get("comment_id")
                    if not isinstance(comment_id, int):
                        raise ValueError(f"{action} requires integer comment_id")
                    patch: dict[str, object] = {"id": comment_id}
                    patch["resolved" if action == "resolve" else action] = (
                        True if action == "resolve" else str(operation.get("text", ""))
                    )
                    patch_path = Path(temporary) / f"patch-{index}.json"
                    patch_path.write_text(
                        json.dumps({"ops": [patch]}, ensure_ascii=False), encoding="utf-8"
                    )
                    self._run_word_script(
                        "comments_apply_patch.py",
                        str(current),
                        str(patch_path),
                        "--out",
                        str(output),
                    )
                elif action == "remove_all":
                    self._run_word_script("comments_strip.py", str(current), "--out", str(output))
                else:
                    raise ValueError(
                        "supported comment actions: add, replace, append, resolve, remove_all, extract"
                    )
                current = output
            comment_count = self._comment_count(current)
            issues = self.validator.validate(current, expected_comments=comment_count)
            if issues:
                raise ValueError(
                    "Word validation failed after comment operation: "
                    + "; ".join(issue.code for issue in issues)
                )
            filename = f"{source_path.stem}-comments-{uuid4().hex[:8]}.docx"
            record = self.workspace.write_bytes(
                f"/workspace/output/{filename}", current.read_bytes()
            )
        artifact = DocumentArtifact(
            artifact_id=f"artifact_{uuid4().hex}",
            path=record.path,
            sha256=record.sha256,
            skill_version=source.skill_version,
            comment_count=comment_count,
            valid=True,
        )
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    @staticmethod
    def _word_scripts_dir() -> Path:
        # Source layout: apps/report_agent/src/report_agent/application/word_reports.py
        #   -> apps/report_agent/skills/word-document/scripts
        # Installed layout (container): .venv/.../site-packages/report_agent/...
        #   -> /app/apps/report_agent/skills/word-document/scripts
        for base in Path(__file__).resolve().parents:
            for suffix in (
                "skills/word-document/scripts",
                "apps/report_agent/skills/word-document/scripts",
            ):
                candidate = base / suffix
                if candidate.is_dir():
                    return candidate
        raise RuntimeError("word-document skill scripts directory not found")

    def _run_word_script(self, name: str, *arguments: str) -> None:
        script = self._word_scripts_dir() / name
        if not script.is_file():
            raise RuntimeError(f"Word script is missing: {name}")
        completed = subprocess.run(
            [sys.executable, str(script), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if completed.returncode:
            message = (completed.stderr or completed.stdout).strip()
            raise ValueError(f"Word script {name} failed: {message[-500:]}")

    def validate(self, virtual_path: str, *, expected_comments: int) -> tuple[dict[str, str], ...]:
        path = self.workspace.resolve(virtual_path)
        return tuple(
            issue.model_dump()
            for issue in self.validator.validate(path, expected_comments=expected_comments)
        )

    def render(self, virtual_path: str) -> dict[str, object]:
        source = self.workspace.resolve(virtual_path)
        with tempfile.TemporaryDirectory() as temporary:
            rendered = self.renderer.render(source, Path(temporary))
            base = f"/workspace/working/renders/{source.stem}"
            pdf = self.workspace.write_bytes(
                f"{base}/{rendered.pdf.name}", rendered.pdf.read_bytes()
            )
            pages = [
                self.workspace.write_bytes(f"{base}/{page.name}", page.read_bytes()).path
                for page in rendered.pages
            ]
        current_sha256 = sha256(source.read_bytes()).hexdigest()
        self.workspace.write_text(
            self._render_receipt_path(current_sha256),
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source_path": virtual_path,
                    "source_sha256": current_sha256,
                    "pdf": pdf.path,
                    "pages": pages,
                    "inspected_pages": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        return {"pdf": pdf.path, "pages": pages, "visual_review_required": True}

    def inspect_page(self, virtual_path: str) -> list[dict[str, object]]:
        normalized = virtual_path.replace("\\", "/")
        if not re.fullmatch(r"/workspace/working/renders/[^/]+/page-[1-9][0-9]*\.png", normalized):
            raise ValueError("only rendered report page PNGs can be inspected")
        page = self.workspace.resolve(normalized)
        encoded = base64.b64encode(page.read_bytes()).decode("ascii")
        receipt_path, receipt = self._receipt_for_page(normalized)
        existing = receipt.get("inspected_pages")
        if not isinstance(existing, list):
            raise ValueError("render receipt page tracking is invalid")
        inspected = set(existing)
        inspected.add(normalized)
        receipt["inspected_pages"] = sorted(inspected)
        self.workspace.write_text(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2))
        return [
            {
                "type": "text",
                "text": (
                    "Inspect this rendered report page for clipping, overlap, missing glyphs, "
                    "broken tables, spacing defects, and header or footer problems."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            },
        ]

    def stage(self, virtual_path: str):
        source = self.workspace.resolve(virtual_path)
        current_sha256 = sha256(source.read_bytes()).hexdigest()
        if not self.visual_review_required:
            issues = self.validator.validate(
                source,
                expected_comments=self._comment_count(source),
            )
            if issues:
                raise ValueError("only structurally valid Word reports can be staged")
            return self.workspace.stage(virtual_path)
        receipt_path = self._render_receipt_path(current_sha256)
        try:
            receipt = json.loads(self.workspace.read_text(receipt_path))
        except FileNotFoundError as exc:
            raise ValueError("current Word version must be rendered before staging") from exc
        if (
            receipt.get("source_path") != virtual_path
            or receipt.get("source_sha256") != current_sha256
            or not receipt.get("pages")
        ):
            raise ValueError("current Word version must be rendered before staging")
        rendered_pages = receipt.get("pages")
        inspected_pages = receipt.get("inspected_pages")
        if not isinstance(rendered_pages, list) or not isinstance(inspected_pages, list):
            raise ValueError("render receipt page tracking is invalid")
        if set(rendered_pages) != set(inspected_pages):
            raise ValueError("every rendered page must be inspected before staging")
        issues = self.validator.validate(
            source,
            expected_comments=self._comment_count(source),
        )
        if issues:
            raise ValueError("only structurally valid Word reports can be staged")
        return self.workspace.stage(virtual_path)

    @staticmethod
    def _render_receipt_path(source_sha256: str) -> str:
        return f"/workspace/working/render-receipts/{source_sha256}.json"

    def _receipt_for_page(self, page_path: str) -> tuple[str, dict[str, object]]:
        receipts = self.workspace.root / "working" / "render-receipts"
        for candidate in sorted(receipts.glob("*.json")):
            receipt = json.loads(candidate.read_text(encoding="utf-8"))
            pages = receipt.get("pages")
            if isinstance(pages, list) and page_path in pages:
                return f"/workspace/working/render-receipts/{candidate.name}", receipt
        raise ValueError("render receipt not found for report page")

    def delete(self, virtual_path: str) -> str:
        return self.workspace.delete_to_trash(virtual_path)

    def restore(self, trash_id: str):
        return self.workspace.restore(trash_id)

    @staticmethod
    def _comment_count(path: Path) -> int:
        from zipfile import ZipFile

        from lxml import etree  # type: ignore[import-untyped]

        with ZipFile(path) as archive:
            if "word/comments.xml" not in archive.namelist():
                return 0
            root = etree.fromstring(archive.read("word/comments.xml"))
            return len(
                root.xpath(
                    "//w:comment",
                    namespaces={
                        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                    },
                )
            )
