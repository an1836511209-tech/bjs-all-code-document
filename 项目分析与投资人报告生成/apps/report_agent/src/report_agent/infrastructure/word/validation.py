"""Structural validation for DOCX reports and source comments."""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from report_agent.domain.documents import DocumentIssue

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENT_AUTHOR = "投资报告智能体"
COMMENTS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)


class WordReportValidator:
    def validate(self, path: Path, *, expected_comments: int) -> tuple[DocumentIssue, ...]:
        issues: list[DocumentIssue] = []
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                required = {
                    "word/document.xml",
                    "word/_rels/document.xml.rels",
                    "[Content_Types].xml",
                }
                if expected_comments:
                    required.add("word/comments.xml")
                for missing in sorted(required - names):
                    issues.append(DocumentIssue(code="MISSING_PART", message=missing))
                if issues:
                    return tuple(issues)
                document = etree.fromstring(archive.read("word/document.xml"))
                relationships = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
                content_types = etree.fromstring(archive.read("[Content_Types].xml"))
                if not expected_comments:
                    return ()
                comments = etree.fromstring(archive.read("word/comments.xml"))
                ids = set(comments.xpath("//w:comment/@w:id", namespaces={"w": W}))
                starts = set(document.xpath("//w:commentRangeStart/@w:id", namespaces={"w": W}))
                ends = set(document.xpath("//w:commentRangeEnd/@w:id", namespaces={"w": W}))
                refs = set(document.xpath("//w:commentReference/@w:id", namespaces={"w": W}))
                authors = comments.xpath("//w:comment/@w:author", namespaces={"w": W})
                if not (ids == starts == ends == refs):
                    issues.append(
                        DocumentIssue(
                            code="COMMENT_ANCHOR_MISMATCH", message="comment ids and anchors differ"
                        )
                    )
                if len(ids) != expected_comments:
                    issues.append(
                        DocumentIssue(
                            code="COMMENT_COUNT_MISMATCH",
                            message=f"expected {expected_comments}, found {len(ids)}",
                        )
                    )
                if any(author != COMMENT_AUTHOR for author in authors):
                    issues.append(
                        DocumentIssue(
                            code="COMMENT_AUTHOR_INVALID", message="unexpected comment author"
                        )
                    )
                relation_types = relationships.xpath("//@Type")
                if COMMENTS_REL not in relation_types:
                    issues.append(
                        DocumentIssue(
                            code="COMMENTS_REL_MISSING", message="comments relationship missing"
                        )
                    )
                overrides = content_types.xpath(
                    "//*[local-name()='Override' and @PartName='/word/comments.xml']/@ContentType"
                )
                if COMMENTS_CONTENT_TYPE not in overrides:
                    issues.append(
                        DocumentIssue(
                            code="COMMENTS_CONTENT_TYPE_MISSING",
                            message="comments content type override missing",
                        )
                    )
        except (OSError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
            issues.append(DocumentIssue(code="DOCX_INVALID", message=str(exc)))
        return tuple(issues)
