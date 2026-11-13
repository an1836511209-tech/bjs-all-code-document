"""Small artifact-id based Word tool surface for the main Agent."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.reports import ReportContentService
from report_agent.application.word_reports import WordReportService
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.infrastructure.word.md_parser import parse_report_markdown
from report_agent.runtime.workspace import TaskWorkspace


#: Comment provenance categories. The label is prefixed to the rendered
#: comment so a reviewer can see how trustworthy each statement is.
COMMENT_KIND_LABELS: dict[str, str] = {
    "material": "原材料",
    "reasoned": "有因推理",
    "unreasoned": "无因推理",
    "web": "网上来源",
    "web_reasoned": "网上来源推理",
    # Data MCP 返回的结构化数据（企查查工商、可比公司、投资人、历史估值）。
    # 与「网上来源」区分：后者是模型自己检索到的网页，前者是工具落盘的证据。
    "mcp": "MCP数据",
}

#: A legal-entity name. A comment is anchored to one paragraph; it may name
#: that paragraph's entity, but a *different* legal entity means the comment
#: drifted onto another row — the failure that put one fund's profile on a
#: different fund's table row.
ENTITY_NAME_RE = re.compile(
    r"[一-鿿A-Za-z0-9·]{2,24}?"
    r"(?:股份有限公司|有限责任公司|有限公司|合伙企业|有限合伙|集团公司)"
)


def _entity_names(text: str) -> list[str]:
    seen: list[str] = []
    for match in ENTITY_NAME_RE.finditer(text or ""):
        name = match.group(0)
        if name not in seen:
            seen.append(name)
    return seen


#: 「第 6 页」/「第 12 段」 are locators, not quoted facts — strip them before
#: comparing numbers, otherwise every page reference looks like a stray number.
_LOCATOR_REF_RE = re.compile(r"第\s*\d+\s*[页段章节]")
#: Only values worth checking: two or more digits, decimals, percentages. Small
#: ordinals ("1."、"2)") are list markers and would flood the check.
_QTY_RE = re.compile(r"\d+(?:\.\d+)?%?")


def _comment_numbers(text: str) -> set[str]:
    cleaned = _LOCATOR_REF_RE.sub("", text or "")
    return {
        value
        for value in _QTY_RE.findall(cleaned)
        if len(value.rstrip("%").replace(".", "")) >= 2 or "." in value or value.endswith("%")
    }


#: ``mcp`` 批注的格式是「来源：<工具>；字段：<pointer>；值：…」——只核对「值：」这一段。
_MCP_VALUE_RE = re.compile(r"值[：:]\s*(.+?)(?:[；;]|$)", re.S)


def _mcp_value_numbers(text: str) -> set[str]:
    match = _MCP_VALUE_RE.search(text or "")
    return _comment_numbers(match.group(1)) if match else set()


class ReportComment(BaseModel):
    """A single Word comment to add by paragraph substring match."""

    match_text: str = Field(
        min_length=1,
        description="报告正文中的子串，用于定位要加批注的段落",
    )
    comment_text: str = Field(
        min_length=1,
        description="模型生成的完整批注文本，包含出处说明、来源、网页（如有）、原文或原始数据",
    )
    kind: Literal["material", "reasoned", "unreasoned", "web", "web_reasoned", "mcp"] = Field(
        default="material",
        description=(
            "批注来源类别：material=原材料直接引用、reasoned=基于材料的有因推理、"
            "unreasoned=无依据的无因推理、web=网上来源、web_reasoned=基于网上来源的推理、"
            "mcp=Data MCP 工具返回的结构化数据（企查查/可比公司/投资人/历史估值）"
        ),
    )


def validate_report_comments(comments: list[ReportComment]) -> list[dict[str, object]]:
    """Reject comments that do not belong to the paragraph they anchor to.

    Five rules:

    * a comment may not name a different legal entity than the one its anchor
      paragraph names — that is how one fund's profile ended up on another
      fund's row;
    * a comment may not quote a number the anchor paragraph does not contain —
      that is how one fund's 匹配分 ended up in another fund's row comment;
    * an ``mcp`` comment may not present an API field as original text;
    * a ``reasoned`` comment must state **where the basis is** (``依据：``) and
      **what the inference is** (``推理：``). "基于材料推理" alone tells a reviewer
      nothing, and the whole point of the tag is to let them judge credibility;
    * an ``unreasoned`` comment must say outright that it has no material basis,
      otherwise it reads like a material fact.

    Returns a list of problems; empty means the comments are acceptable.
    """
    problems: list[dict[str, object]] = []
    for index, comment in enumerate(comments):
        # Only an ``mcp`` comment claims "the anchor paragraph shows value X", so
        # it is the only kind where a missing number is wrong. A ``reasoned``
        # comment deliberately cites numbers from *other* pages, and a
        # ``material`` one quotes the source sentence, not the body wording.
        if comment.kind == "mcp":
            anchor_numbers = _comment_numbers(comment.match_text)
            quoted_numbers = _mcp_value_numbers(comment.comment_text)
            stray = sorted(n for n in quoted_numbers if n not in anchor_numbers)
            if stray:
                problems.append({
                    "index": index,
                    "problem": "comment_number_not_in_anchor",
                    "numbers": stray,
                    "detail": (
                        "批注声明的值 " + "、".join(stray)
                        + " 在锚定段落里找不到。批注只能解释它所锚定的这一段；"
                        "引用别处的数字，会把 A 行的数据贴到 B 行上。"
                    ),
                })
        anchored = _entity_names(comment.match_text)
        mentioned = [
            name
            for name in _entity_names(comment.comment_text)
            if name not in comment.match_text
        ]
        if anchored and mentioned:
            problems.append({
                "index": index,
                "problem": "comment_names_a_different_entity",
                "anchored_entities": anchored,
                "comment_entities": mentioned,
                "detail": (
                    "批注锚定段落的实体是 "
                    + "、".join(anchored)
                    + "，但批注正文提到了 "
                    + "、".join(mentioned)
                    + "。批注必须讲锚定段落自己的实体。"
                ),
            })
        if comment.kind == "mcp" and "原文" in comment.comment_text:
            problems.append({
                "index": index,
                "problem": "mcp_comment_claims_to_be_original_text",
                "detail": (
                    "mcp 类批注的来源是接口返回的结构化字段，不是材料原文，"
                    "不能写「原文：…」。请改成「来源：<工具>；字段：<json_pointer>；值：…」"
                ),
            })
        if comment.kind == "reasoned":
            missing = [word for word in ("依据", "推理") if word not in comment.comment_text]
            if missing:
                problems.append({
                    "index": index,
                    "problem": "reasoned_comment_missing_basis",
                    "detail": (
                        "reasoned 类批注必须写成「依据：材料第 N 页 [+ 第 M 页]；"
                        "推理：<一句逻辑链>」，当前缺少：" + "、".join(missing)
                        + "。审阅者要靠这两段判断这个推断站不站得住。"
                    ),
                })
        if comment.kind == "unreasoned" and "无材料依据" not in comment.comment_text:
            problems.append({
                "index": index,
                "problem": "unreasoned_comment_not_labelled",
                "detail": (
                    "unreasoned 类批注必须明写「无材料依据，属经验判断：…」，"
                    "否则读者会把它当成材料事实。"
                ),
            })
    return problems


def build_word_tools(
    service: WordReportService,
    *,
    skill_version: str,
    report_service: ReportContentService,
    publish: Callable[[str], PublishedArtifact],
    context_store: WorkspaceContextStore | None = None,
    workspace: TaskWorkspace | None = None,
):
    def create_word_document(report_id: str, filename: str, report_date: str | None = None) -> str:
        artifact = service.create(
            report_service.get(report_id),
            filename=filename,
            skill_version=skill_version,
            report_date=date.fromisoformat(report_date) if report_date else None,
        )
        _record(context_store, artifact)
        return artifact.model_dump_json()

    def create_word_from_md(
        md_path: str,
        report_id: str,
        filename: str,
        company_name: str,
        title_evidence_id: str,
        report_date: str | None = None,
    ) -> str:
        """Parse a Markdown report file into ReportContent and generate DOCX.

        The model writes report content as Markdown in the workspace using
        ``write_file``/``edit_file``, with ``<!-- cite: evidence_xxx -->``
        markers for citations. This tool parses the Markdown into
        ReportContent, validates evidence, and generates Word.
        """
        if workspace is None:
            raise RuntimeError("workspace not configured for md tools")
        content = workspace.read_text(md_path)
        report = parse_report_markdown(
            content,
            report_id=report_id,
            title=filename.removesuffix(".docx"),
            company_name=company_name,
            title_evidence_id=title_evidence_id,
        )
        # Save as ReportContent for validation and evidence checks
        saved = report_service.save(report)
        validated = report_service.validate(report_id)
        if context_store:
            context_store.record_report("create_word_from_md", validated)
        parsed_date = _parse_date(report_date) if report_date else None
        artifact = service.create(
            validated,
            filename=filename,
            skill_version=skill_version,
            report_date=parsed_date,
        )
        _record(context_store, artifact)
        return artifact.model_dump_json()

    def edit_word_document(artifact_id: str, operations: list[dict[str, str]]) -> str:
        artifact = service.edit(artifact_id, operations)
        _record(context_store, artifact)
        return artifact.model_dump_json()

    def manage_word_comments(artifact_id: str, operations: list[dict[str, object]]) -> str:
        result = service.manage_comments(artifact_id, operations)
        if hasattr(result, "model_dump_json"):
            _record(context_store, result)
            return result.model_dump_json()
        return json.dumps(result, ensure_ascii=False)

    def add_report_comments(artifact_id: str, comments: list[ReportComment]) -> str:
        problems = validate_report_comments(comments)
        if problems:
            return json.dumps(
                {
                    "status": "error",
                    "error": "批注未通过校验，请修正后重新提交",
                    "problems": problems,
                },
                ensure_ascii=False,
            )
        # 先生成 docx 时，`src` 标记已经自动变成过一批批注；这里再加同一个事实，
        # 客户就会在同一段下面看到两条一模一样的话（实测 55 条批注里有 15 组重复）。
        # 所以加之前先读一遍现有批注，文本完全相同的跳过。
        existing_texts: set[str] = set()
        try:
            extracted = service.manage_comments(artifact_id, [{"action": "extract"}])
            if isinstance(extracted, dict):
                existing_texts = {
                    str(item.get("text") or "").strip()
                    for item in (extracted.get("comments") or [])
                    if isinstance(item, dict)
                }
        except Exception:  # noqa: BLE001 - 去重失败不能挡住加批注
            existing_texts = set()
        operations = []
        skipped = 0
        for comment in comments:
            label = COMMENT_KIND_LABELS.get(comment.kind)
            text = f"【{label}】{comment.comment_text}" if label else comment.comment_text
            if text.strip() in existing_texts:
                skipped += 1
                continue
            operations.append(
                {"action": "add", "contains": comment.match_text, "text": text}
            )
        if not operations:
            return json.dumps(
                {
                    "status": "ok",
                    "added": 0,
                    "skipped_duplicates": skipped,
                    "summary": f"这 {skipped} 条批注与已有批注完全相同，未重复添加。",
                },
                ensure_ascii=False,
            )
        artifact = service.manage_comments(artifact_id, operations)
        _record(context_store, artifact)
        payload = json.loads(artifact.model_dump_json())
        payload["added"] = len(operations)
        payload["skipped_duplicates"] = skipped
        return json.dumps(payload, ensure_ascii=False)

    def validate_and_publish_word(artifact_id: str) -> str:
        staged = service.validate_and_stage(artifact_id)
        published = publish(staged.path)
        if context_store:
            context_store.record_artifact(
                published.artifact_id,
                kind="published_docx",
                path=staged.path,
                status="published",
                sha256=published.sha256,
                details={"object_key": published.object_key},
            )
        return published.model_dump_json()

    definitions = (
        (
            create_word_document,
            "create_word_document",
            "Create a DOCX from validated ReportContent (no inline comments).",
        ),
        (
            create_word_from_md,
            "create_word_from_md",
            "Parse a workspace Markdown report file into ReportContent and generate DOCX. Use after writing/editing the report as Markdown with write_file/edit_file. Citations are marked with <!-- cite: evidence_xxx --> in the Markdown.",
        ),
        (
            edit_word_document,
            "edit_word_document",
            "Create a new DOCX version from artifact_id using replace_text operations.",
        ),
        (
            add_report_comments,
            "add_report_comments",
            "Add Word comments by paragraph substring match. Model provides match_text (a substring from the report text) and comment_text (the full comment). Comments are attached to the paragraph containing the match_text.",
        ),
        (
            manage_word_comments,
            "manage_word_comments",
            "Add, replace, append, resolve, remove all, or extract Word comments. "
            "Each operation is a dict with 'action' plus fields: "
            "add -> {'action':'add','contains':'<report substring>','text':'<comment>'} "
            "(requires both contains and text); "
            "replace/append -> same but also requires integer 'comment_id'; "
            "resolve -> {'action':'resolve','comment_id':N}; "
            "remove_all -> {'action':'remove_all'}; "
            "extract -> {'action':'extract'} (single op, returns current comments). "
            "Prefer add_report_comments for adding comments. Mutations create a new artifact version.",
        ),
        (
            validate_and_publish_word,
            "validate_and_publish_word",
            "Validate, optionally apply configured visual review, stage, upload to MinIO, and return authoritative PublishedArtifact.",
        ),
    )
    return tuple(
        StructuredTool.from_function(fn, name=name, description=description)
        for fn, name, description in definitions
    )


def _record(store: WorkspaceContextStore | None, artifact) -> None:
    if store:
        store.record_artifact(
            artifact.artifact_id,
            kind="docx",
            path=artifact.path,
            status="created",
            sha256=artifact.sha256,
            details={"comment_count": artifact.comment_count},
        )


def _parse_date(value: str) -> date | None:
    """Parse a date string that may be ISO format or Chinese format."""
    value = value.strip()
    # Try ISO format first: 2025-07-15
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    # Try Chinese format: 2025年7月15日
    match = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None
