"""One-pager BP Skill toolset.

Three tools and nothing else — the Skill reuses other Report Agent capabilities
(parse_materials, extract_project_profile, …) through the wider invocation:

* ``detect_one_pager_business_type`` — classify material as 产权/增资
* ``render_one_pager`` — parse md, fill template, validate, save artifact
* ``validate_and_publish_one_pager`` — stage + push to MinIO

The skill re-uses the same publish callback the investment-report branch uses,
so the bootstrap layer can pass identical infrastructure to both skills.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent.application.interactions import (
    BUSINESS_TYPE_ALIASES,
    business_type_question,
    read_interaction,
    risk_disclosure_question,
    update_interaction,
)
from report_agent.application.one_pager_reports import (
    OnePagerReportResult,
    OnePagerReportService,
)
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.materials import ParsedMaterial
from report_agent.domain.one_pager import (
    FIXED_INTRO_TITLE_WITH_FINANCIALS,
    HIGHLIGHT_BODY_HARD_LIMIT,
    HIGHLIGHT_BODY_RANGE,
    INTRO_BODY_HARD_LIMIT,
    INTRO_BODY_RANGE,
    OUTLINE_EXAMPLE,
    OUTLINE_SCHEMA_HINT,
    BusinessType,
    DetectionConfidence,
    OnePagerOutline,
    detect_business_type_detail,
    normalize_outline_payload,
)
from report_agent.domain.source_markers import strip_source_markers
from report_agent.infrastructure.word.one_pager_md_parser import OnePagerMarkdownError
from report_agent.runtime.workspace import TaskWorkspace, WorkspacePolicyError

_MATERIAL_ID_RE = re.compile(r"^material_[a-f0-9]{32}$")
_BINARY_SUFFIXES = frozenset({".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"})


def _parse_user_hint(raw: str) -> BusinessType | None:
    value = BUSINESS_TYPE_ALIASES.get(raw.strip().lower())
    return BusinessType(value) if value else None


def _blocks_text(payload: dict[str, Any] | ParsedMaterial) -> str:
    if isinstance(payload, ParsedMaterial):
        parts = [str(block.text or "").strip() for block in payload.blocks]
    else:
        parts = [
            str(block.get("text") or "").strip()
            for block in (payload.get("blocks") or [])
            if isinstance(block, dict)
        ]
    return "\n\n".join(part for part in parts if part)


def _load_parsed_material(workspace: TaskWorkspace, material_id: str) -> ParsedMaterial:
    path = f"/workspace/working/materials/{material_id}.json"
    return ParsedMaterial.model_validate_json(workspace.read_text(path))


def _iter_parsed_materials(workspace: TaskWorkspace) -> list[ParsedMaterial]:
    root = workspace.resolve("/workspace/working/materials/.inventory-anchor").parent
    if not root.is_dir():
        return []
    materials: list[ParsedMaterial] = []
    for path in sorted(root.glob("material_*.json")):
        try:
            materials.append(ParsedMaterial.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, ValidationError, ValueError):
            continue
    return materials


def _match_parsed_by_names(
    workspace: TaskWorkspace, *names: str
) -> ParsedMaterial | None:
    wanted = {name.strip() for name in names if name and name.strip()}
    if not wanted:
        return None
    matches = [
        material
        for material in _iter_parsed_materials(workspace)
        if material.source_name in wanted
        or PurePosixPath(material.source_name).name in {PurePosixPath(name).name for name in wanted}
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Resume / re-parse often leaves several material_*.json for the same
    # upload. Prefer the newest file instead of failing detect/render.
    def _mtime(material: ParsedMaterial) -> float:
        path = workspace.resolve(f"/workspace/working/materials/{material.material_id}.json")
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(matches, key=_mtime)


def _material_id_from_token(token: str) -> str | None:
    bare = PurePosixPath(token.replace("\\", "/")).stem
    candidate = bare if _MATERIAL_ID_RE.fullmatch(bare) else token.strip()
    return candidate if _MATERIAL_ID_RE.fullmatch(candidate) else None


def resolve_material_text_for_detection(
    workspace: TaskWorkspace,
    material_path: str,
    filename: str = "",
) -> str:
    """Load UTF-8 material text, falling back to parse_materials output for binaries.

    ``material_path`` may be a workspace text path, a ``material_id``, a parsed
    materials JSON path, or an input binary path whose parsed twin already exists
    under ``/workspace/working/materials/``.
    """
    path = (material_path or "").strip()
    if not path:
        raise ValueError("material_path is required")

    material_id = _material_id_from_token(path)
    if material_id is not None:
        try:
            return _blocks_text(_load_parsed_material(workspace, material_id))
        except FileNotFoundError as exc:
            raise ValueError(
                f"unknown material_id {material_id}; call parse_materials first"
            ) from exc

    suffix = PurePosixPath(path).suffix.lower()
    try:
        if suffix == ".json":
            raw = workspace.read_text(path)
            payload = json.loads(raw)
            if isinstance(payload, dict) and "blocks" in payload:
                text = _blocks_text(payload)
                if text.strip():
                    return text
            return raw
        if suffix not in _BINARY_SUFFIXES:
            return workspace.read_text(path)
    except UnicodeDecodeError:
        pass
    except (FileNotFoundError, WorkspacePolicyError, json.JSONDecodeError, OSError):
        # Fall through to parsed-material matching for wrong areas / missing files.
        pass
    else:
        # Binary suffix: do not attempt UTF-8 read of the original bytes.
        pass

    matched = _match_parsed_by_names(
        workspace,
        filename,
        PurePosixPath(path).name,
        path,
    )
    if matched is not None:
        text = _blocks_text(matched)
        if text.strip():
            return text
        raise ValueError(
            f"parsed material {matched.material_id} has no text blocks; "
            "re-run parse_materials or pass another material_id"
        )

    raise ValueError(
        f"cannot read material at {material_path}: binary or unreadable path; "
        "call parse_materials first, then pass material_id or the input path again"
    )


#: one-pager.md 的最小骨架。渲染失败时原样回传，模型照着补结构即可。
MD_TEMPLATE = """# 项目概览

## 基本信息

- 项目名称：<必填>
- 公司全称：<必填>
- 所属区域：<必填，省市>
- 所属行业：<必填>
- 原始简介：<必填，2-3 句>
- 联系人名称：<必填，无则写「待补充」>
- 拟募集金额：<增资项目必填>
- 对应持股比例：<增资项目必填>
- 转让底价：<产权项目必填>

## 项目介绍

### 核心产品
<正文建议 225-250 字，仅作建议，不为差几字改稿>

### <第二个介绍标题，3-6 字>
<如为「经营分析」，用 2-3 句纯文本概括核心财务指标，建议 120 字以内，禁止表格。其余标题仍建议 225-250 字>

### <第三个介绍标题，3-6 字>
<正文建议 225-250 字，仅作建议，不为差几字改稿>

## 项目亮点

### <亮点标题，5-9 字>
<正文建议 170-185 字，仅作建议，不为差几字改稿>

### <亮点标题，5-9 字>
<正文建议 170-185 字，仅作建议，不为差几字改稿>

### <亮点标题，5-9 字>
<正文建议 170-185 字，仅作建议，不为差几字改稿>

## 投资人匹配

| 序号 | 来源 | 投资人类型 | 投资人名称 | 匹配理由 |
|------|------|-----------|-----------|---------|
| 1 | 内部库 | 机构 | <机构名> | <匹配理由> |
"""

_REQUIRED_INFO: tuple[str, ...] = (
    "项目名称", "公司全称", "所属区域", "所属行业", "原始简介", "联系人名称",
)
_INFO_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|")
_INFO_LINE = re.compile(r"^-\s*([^：:]+)\s*[:：]\s*(.*)$")
# Detect pipe-prefixed rows, alignment rows with optional outer pipes, and HTML tables.
_FINANCIAL_TABLE_RE = re.compile(
    r"^[ \t]*\|"
    r"|^(?=[^\n]*\|)[ \t]*:?-+:?(?:[ \t]*\|[ \t]*:?-+:?)*[ \t]*\|?[ \t]*$"
    r"|<table\b",
    re.MULTILINE | re.IGNORECASE,
)


def _basic_info_map(md: str) -> dict[str, str]:
    """把 `## 基本信息` 里的字段抽出来（兼容 - 列表与两列表格两种写法）。"""
    block = re.search(r"^##\s+基本信息\s*$(.+?)(?=^##\s+|\Z)", md, re.MULTILINE | re.DOTALL)
    if not block:
        return {}
    values: dict[str, str] = {}
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if line.startswith("-"):
            match = _INFO_LINE.match(line)
            if match:
                values[match.group(1).strip()] = match.group(2).strip()
        elif line.startswith("|"):
            match = _INFO_ROW.match(line)
            if match:
                name = match.group(1).strip()
                if name in {"字段", "项目名称"} and name == "字段":
                    continue
                values[name] = match.group(2).strip()
    return values


def preflight_one_pager_md(md: str, business_type: str) -> list[dict[str, str]]:
    """渲染前把能一次查完的问题全部查出来。

    之前每渲染一次只报一个问题（先「缺少基本信息」、再「region 为空」、再
    「original_intro 为空」），每次都要一次模型往返。这里一次性返回全部问题
    与 md 骨架，模型一轮就能补齐。
    """
    issues: list[dict[str, str]] = []
    if not md.strip():
        return [{"field": "<root>", "message": "Markdown 为空"}]
    # Source comments may span lines and contain headings or quoted facts.
    # Exclude them before discovering sections as well as counting body text.
    md = strip_source_markers(md)

    info = _basic_info_map(md)
    if not info:
        issues.append({"field": "基本信息", "message": "缺少 `## 基本信息` 章节（或该章节里没有任何字段）"})
    else:
        for name in _REQUIRED_INFO:
            if not (info.get(name) or "").strip():
                issues.append({"field": f"基本信息.{name}", "message": f"「{name}」为空，必须填写（没有就写「待补充」）"})
        price_label = "拟募集金额" if business_type == "增资" else "转让底价"
        if not (info.get(price_label) or "").strip():
            issues.append({"field": f"基本信息.{price_label}", "message": f"{business_type}项目必须填写「{price_label}」"})

    for top in ("项目介绍", "项目亮点"):
        block = re.search(rf"^##\s+{re.escape(top)}\s*$(.+?)(?=^##\s+|\Z)", md, re.MULTILINE | re.DOTALL)
        if not block:
            issues.append({"field": top, "message": f"缺少 `## {top}` 章节"})
            continue
        subsections = list(
            re.finditer(r"^###\s+(.+?)\s*$(.*?)(?=^###\s+|\Z)", block.group(1), re.MULTILINE | re.DOTALL)
        )
        if len(subsections) != 3:
            issues.append({"field": top, "message": f"`{top}` 必须恰好 3 个子段（###），实际 {len(subsections)} 个"})
        hard_limit = INTRO_BODY_HARD_LIMIT if top == "项目介绍" else HIGHLIGHT_BODY_HARD_LIMIT
        for match in subsections:
            title = match.group(1).strip()
            body = match.group(2).strip()
            if not body:
                issues.append({"field": f"{top}.{title}", "message": f"「{title}」段正文为空"})
                continue
            if (
                top == "项目介绍"
                and title == FIXED_INTRO_TITLE_WITH_FINANCIALS
                and _FINANCIAL_TABLE_RE.search(body)
            ):
                issues.append(
                    {
                        "field": f"{top}.{title}",
                        "message": "「经营分析」正文禁止表格。请改为 2-3 句纯文本，概括最新一期核心财务指标及可核实的趋势，建议 120 字以内。",
                    }
                )
                continue
            length = len("".join(body.split()))
            if length <= hard_limit:
                continue
            issues.append(
                {
                    "field": f"{top}.{title}",
                    "message": (
                        f"「{title}」正文字数 {length}，硬上限 {hard_limit} 字（不含来源标记和空白）。"
                        f"超出 {length - hard_limit} 字，请压缩此段；其他合规段落不要重写。"
                    ),
                }
            )
    return issues


def build_one_pager_tools(
    workspace: TaskWorkspace,
    *,
    service: OnePagerReportService | None = None,
    publish: Callable[[str], PublishedArtifact] | None = None,
) -> tuple[Any, ...]:
    """Assemble the three-tool surface for the ``one-pager`` Skill.

    The shared parsing / MCP / evidence / review tools are added by
    ``bootstrap`` so the two Skills share the same plumbing. This entry point
    is intentionally narrow: it owns only the tools specific to one-pager
    rendering and publication.
    """
    if service is None:
        service = OnePagerReportService(workspace)

    def detect_one_pager_business_type(
        material_path: str,
        filename: str = "",
        user_hint: str = "",
    ) -> str:
        """Decide whether a one-pager is 产权 or 增资.

        ``material_path`` may be UTF-8 text under ``/workspace/``, a
        ``material_id``, or an input binary path. For PDF/DOCX/etc. the tool
        loads text from ``parse_materials`` output under
        ``/workspace/working/materials/``. Persisted user choices take
        precedence. A prior decided selection (user / filename / high) is kept
        when a later call cannot decide, so resume must not wipe it or re-ask.
        Unconfirmed model hints are ignored; first-time undecidable results
        carry a question_request for the runtime to display.
        """
        selection = read_interaction(workspace).get("business_type_selection") or {}
        prior = _parse_user_hint(str(selection.get("value") or ""))
        prior_source = str(selection.get("source") or "")
        # Resume often omits filename; fall back to the path basename (and any
        # earlier material_path) so 股权转让/增资 cues in the name still apply.
        effective_filename = (
            (filename or "").strip()
            or PurePosixPath((material_path or "").replace("\\", "/")).name
            or PurePosixPath(str(selection.get("material_path") or "").replace("\\", "/")).name
        )
        try:
            text = resolve_material_text_for_detection(
                workspace, material_path, effective_filename
            )
        except Exception as exc:
            return json.dumps(
                {
                    "status": "failed",
                    "error": f"cannot read material at {material_path}: {exc}",
                },
                ensure_ascii=False,
            )
        # Model-supplied user_hint is not evidence that the user chose a type.
        # Only an answer validated and persisted by the service is authoritative.
        detail = detect_business_type_detail(text, filename=effective_filename)
        if prior is not None and prior_source == "user":
            detail = detail.model_copy(update={
                "business_type": prior, "confidence": DetectionConfidence.USER,
                "conflict": detail.business_type is not None and detail.business_type != prior,
                "reason": f"沿用用户在当前任务明确选择的业务类型：{prior.value}",
            })
        elif not detail.decided and prior is not None:
            # Keep a previous system decision; never overwrite it with null and
            # never re-open the business-type card on the same task.
            kept = (
                DetectionConfidence(prior_source)
                if prior_source in {item.value for item in DetectionConfidence}
                else DetectionConfidence.FILENAME
            )
            detail = detail.model_copy(update={
                "business_type": prior,
                "confidence": kept,
                "conflict": False,
                "reason": f"沿用当前任务已判定的业务类型：{prior.value}",
            })
        if detail.decided:
            update_interaction(workspace, business_type_selection={
                "value": detail.business_type.value if detail.business_type else None,
                "source": detail.confidence.value, "material_path": material_path,
            })
        elif prior is None:
            # First undecidable call only — leave room for the question card.
            update_interaction(workspace, business_type_selection={
                "value": None, "source": DetectionConfidence.NONE.value,
                "material_path": material_path,
            })
        request = {"question_request": business_type_question()} if not detail.decided else {}
        return json.dumps(
            {
                **request,
                "status": "ok" if detail.decided else "needs_user_input",
                "business_type": detail.business_type.value if detail.business_type else None,
                "confidence": detail.confidence.value,
                "property_score": detail.property_score,
                "capital_score": detail.capital_score,
                "conflict": detail.conflict,
                "reason": detail.reason,
            },
            ensure_ascii=False,
        )

    def render_one_pager(
        md_path: str,
        business_type: str,
        report_id: str,
        filename: str,
    ) -> str:
        """Parse ``md_path`` and fill the appropriate template.

        ``filename`` must end with ``.docx``. ``business_type`` is the human
        form: ``产权`` or ``增资``. Returns a JSON payload describing the
        produced artifact and any validation issues.

        Content problems are reported as ``status="invalid_content"`` with a
        per-field breakdown rather than raised, because a raised exception
        reaches the model through the generic tool-error wrapper and loses the
        detail it needs to repair the markdown.
        """
        selection = read_interaction(workspace).get("business_type_selection") or {}
        selected = _parse_user_hint(str(selection.get("value") or ""))
        if selected is None:
            return json.dumps({"status": "needs_user_input", "question_request": business_type_question()}, ensure_ascii=False)
        if business_type != selected.value:
            return json.dumps({"status": "invalid_arguments", "error": f"当前任务已确定业务类型为{selected.value}，请使用该类型渲染。", "allowed": [selected.value]}, ensure_ascii=False)
        try:
            business = BusinessType(business_type)
        except ValueError:
            return json.dumps(
                {
                    "status": "invalid_arguments",
                    "error": f"business_type must be 产权 or 增资, got {business_type!r}",
                    "allowed": ["产权", "增资"],
                },
                ensure_ascii=False,
            )
        if not filename.endswith(".docx"):
            return json.dumps(
                {
                    "status": "invalid_arguments",
                    "error": f"filename must end with .docx, got {filename!r}",
                },
                ensure_ascii=False,
            )
        # 渲染前把结构问题一次性查完：过去要「缺章节 → 字段为空」来回三轮，
        # 每轮都是一次模型往返。风险展示确认优先于结构检查，避免未确认时先要求改稿。
        risk_choice = read_interaction(workspace).get("risk_disclosure") or {}
        review = read_interaction(workspace).get("risk_review") or {}
        try:
            md_text = workspace.read_text(md_path)
        except (FileNotFoundError, ValueError) as exc:
            return json.dumps(
                {
                    "status": "invalid_arguments",
                    "error": f"读取 {md_path} 失败: {exc}",
                },
                ensure_ascii=False,
            )
        has_risk_heading = bool(re.search(r"(?m)^#{1,6}\s+[^\n]*风险提示[^\n]*$", md_text))
        if not risk_choice and (has_risk_heading or review.get("risk_items")):
            return json.dumps({"status": "needs_user_input", "question_request": risk_disclosure_question(
                review.get("risk_items") or ["报告中拟展示的风险提示内容"], context=review.get("source_quote", ""))}, ensure_ascii=False)
        if risk_choice and has_risk_heading != (risk_choice["value"] == "show"):
            return json.dumps({"status": "invalid_content", "error": (
                "用户已选择展示风险事实，请补充风险提示段落。" if risk_choice["value"] == "show"
                else "用户已选择不展示非优质项目信息，请移除风险提示段落并按其他材料内容重写第三段。")}, ensure_ascii=False)
        preflight = preflight_one_pager_md(md_text, business.value)
        if preflight:
            return json.dumps(
                {
                    "status": "invalid_content",
                    "error": (
                        "one-pager.md 还不满足模板要求。**请按 issues 一次性全部修完**"
                        "（缺的章节、空字段、子段数量都要一起补），再调用本工具。"
                    ),
                    "issues": preflight,
                    "md_template": MD_TEMPLATE,
                },
                ensure_ascii=False,
            )
        try:
            result = service.render(
                md_path=md_path,
                business_type=business,
                report_id=report_id,
                filename=filename,
            )
        except FileNotFoundError as exc:
            return json.dumps(
                {"status": "invalid_arguments", "error": str(exc)},
                ensure_ascii=False,
            )
        except ValidationError as exc:
            return json.dumps(
                {
                    "status": "invalid_content",
                    "error": "one-pager.md 内容不满足模板约束，请一次性改完 errors 里的全部问题后重试",
                    "errors": [
                        {
                            "field": ".".join(str(p) for p in error["loc"]) or "<root>",
                            "message": error["msg"],
                        }
                        for error in exc.errors()
                    ],
                    "md_template": MD_TEMPLATE,
                },
                ensure_ascii=False,
            )
        except (OnePagerMarkdownError, ValueError) as exc:
            return json.dumps(
                {
                    "status": "invalid_content",
                    "error": str(exc),
                    "errors": [],
                    "md_template": MD_TEMPLATE,
                },
                ensure_ascii=False,
            )
        return _report_result_payload(result)

    def validate_and_publish_one_pager(artifact_id: str) -> str:
        """Stage and publish a previously rendered one-pager.

        ``publish`` is supplied by bootstrap; when it is ``None`` the tool only
        stages the file and reports the path.
        """
        result = service.artifact(artifact_id)
        if publish is None:

            staged = workspace.stage(result.path)
            return json.dumps(
                {
                    "status": "staged_only",
                    "artifact_id": result.artifact_id,
                    "path": staged.path,
                    "sha256": staged.sha256,
                    "pages": result.pages,
                    "valid": result.valid,
                    "issues": [issue.model_dump(mode="json") for issue in result.issues],
                    "notes": list(result.notes),
                },
                ensure_ascii=False,
            )
        updated = service.publish(artifact_id, publish)
        return json.dumps(
            {
                "status": "published",
                "artifact_id": updated.artifact_id,
                "object_key": updated.published.object_key,
                "download_url": updated.published.download_url,
                "expires_at": updated.published.expires_at.isoformat(),
                "sha256": updated.sha256,
                "pages": updated.pages,
                "valid": updated.valid,
                "issues": [issue.model_dump(mode="json") for issue in updated.issues],
                "notes": list(updated.notes),
            },
            ensure_ascii=False,
        )

    def check_one_pager_outline(outline: dict[str, object]) -> str:
        """Validate the six planned section titles before any prose is written.

        ``outline`` mirrors the Lingda workflow's 5-1 → 5-2 pair: the model
        decides all six titles in one pass, each with its own content points and
        source quote, and this tool enforces the decision table plus the
        uniqueness / non-overlap rules. Fixing titles first is what keeps intro
        ("what it is") and highlight ("why it is worth investing in") from
        restating each other.

        Expected shape::

            {
              "report_id": "op-0001",
              "business_type": "增资",
              "has_financial_analysis": false,
              "has_risk_facts": false,
              "intro_sections": [
                {"index": 1, "title": "核心产品", "key_points": ["…"],
                 "source_quote": "材料原句"},
                …3 items
              ],
              "highlight_sections": [ …3 items ]
            }

        Returns ``status="ok"`` plus the applied decision table, or
        ``status="invalid_outline"`` with a per-field error list.
        """
        interaction = read_interaction(workspace)
        choice = interaction.get("risk_disclosure") or {}
        review = interaction.get("risk_review") or {}
        has_risk = outline.get("has_risk_facts") is True or bool(choice) or bool(review.get("risk_items"))
        if has_risk and not choice:
            slots = outline.get("intro_sections") or []
            risk_slot = next((s for s in slots if isinstance(s, dict) and s.get("index") == 3), {}) if isinstance(slots, list) else {}
            points = risk_slot.get("key_points") or []
            items = [p for p in points if isinstance(p, str) and p.strip()] if isinstance(points, list) else []
            items = review.get("risk_items") or items or ["材料中识别到的风险或瑕疵"]
            quote = review.get("source_quote") or str(risk_slot.get("source_quote") or "")
            update_interaction(workspace, risk_review={"risk_items": items, "source_quote": quote})
            return json.dumps({"status": "needs_user_input", "question_request": risk_disclosure_question(
                items, context=quote)}, ensure_ascii=False)
        # Identification and the user's disclosure choice remain separate.
        outline = {**outline, "has_risk_facts": has_risk,
                   "include_risk_facts": has_risk and choice.get("value") == "show"}
        try:
            parsed = OnePagerOutline.model_validate(normalize_outline_payload(outline))
        except ValidationError as exc:
            return json.dumps(
                {
                    "status": "invalid_outline",
                    "error": (
                        "大纲不符合约束。**请一次性改完下面所有 errors**，"
                        "并严格照 schema/example 的字段名提交；字段名写错、"
                        "多写未定义字段都会被拒绝。"
                    ),
                    "errors": [
                        {
                            "field": ".".join(str(p) for p in error["loc"]) or "<root>",
                            "message": error["msg"],
                        }
                        for error in exc.errors()
                    ],
                    "schema": OUTLINE_SCHEMA_HINT,
                    "example": OUTLINE_EXAMPLE,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "ok",
                "business_type": parsed.business_type.value,
                "decision_table": list(parsed.decision_table()),
                "intro_titles": [s.title for s in parsed.intro_sections],
                "highlight_titles": [s.title for s in parsed.highlight_sections],
                "next_step": (
                    f"按此大纲撰写项目介绍 3 段正文（除「经营分析」外，每段建议 {INTRO_BODY_RANGE[0]}-{INTRO_BODY_RANGE[1]} 字），"
                    "「经营分析」用 2-3 句纯文本概括核心财务指标，建议 120 字以内，禁止表格。"
                    "只写「是什么」；项目亮点正文留到介绍定稿后再写"
                    f"（每段 {HIGHLIGHT_BODY_RANGE[0]}-{HIGHLIGHT_BODY_RANGE[1]} 字），"
                    "目标字数仅作建议，差几字不需要改稿，不得为凑字数重复改写或新增事实。"
                    "并把介绍全文带入以避免重复。"
                    + ("用户选择不展示的非优质项目信息不得写入任何段落。" if choice.get("value") == "hide" else "")
                ),
            },
            ensure_ascii=False,
        )

    definitions = (
        (
            detect_one_pager_business_type,
            "detect_one_pager_business_type",
            "判定项目材料属于「产权转让」或「增资扩股」。material_path 可传 /workspace/input 原文件、"
            "material_id，或 UTF-8 文本路径；PDF/DOCX 等二进制会自动改用 parse_materials 后的正文。"
            "返回 JSON {business_type, confidence, reason}。",
        ),
        (
            check_one_pager_outline,
            "check_one_pager_outline",
            "写正文之前先校验 6 个板块标题（含决策表：有财务数据→固定「经营分析」，有非优质信息先由用户确认是否展示，确认展示后固定「风险提示」；"
            "第 1 个固定「核心产品」）。返回 status=ok 与实际生效的标题；"
            "不合法时返回 invalid_outline + errors + schema + example，"
            "请一次性改完所有 errors 再提交。",
        ),
        (
            render_one_pager,
            "render_one_pager",
            "解析 one-pager.md 并按业务类型（产权/增资）渲染对应模板生成 docx 到 /workspace/output/。filename 必须以 .docx 结尾。",
        ),
        (
            validate_and_publish_one_pager,
            "validate_and_publish_one_pager",
            "校验已生成的 docx、阶段化并发布到对象存储；返回 {object_key, download_url} 或告警。",
        ),
    )
    return tuple(
        StructuredTool.from_function(fn, name=name, description=description)
        for fn, name, description in definitions
    )


def _report_result_payload(result: OnePagerReportResult) -> str:
    return json.dumps(
        {
            "status": "ok",
            "artifact_id": result.artifact_id,
            "path": result.path,
            "sha256": result.sha256,
            "business_type": result.business_type.value,
            "valid": result.valid,
            "pages": result.pages,
            "issues": [issue.model_dump(mode="json") for issue in result.issues],
            "filled_placeholders": list(result.filled_placeholders),
            "investor_rows": result.investor_rows,
            "notes": list(result.notes),
        },
        ensure_ascii=False,
    )


def stage_only_path(workspace: TaskWorkspace, path: str) -> Path:
    """Expose :meth:`TaskWorkspace.stage` for callers that bypass the tool."""
    return workspace.stage(path)
