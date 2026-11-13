"""Parse the one-pager Markdown file emitted by the Skill into content.

The skill writes a strictly laid-out ``one-pager.md`` because the document
fits on a single page and ambiguity would just push errors downstream.
Every section has a fixed name and uses H2/H3 headings so the parser is a
straight walk through the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from report_agent.domain.one_pager import (
    BusinessType,
    InvestorRow,
    MatchedTag,
    OnePagerContent,
    OnePagerSection,
)
from report_agent.domain.source_markers import strip_source_markers

INTRO_TITLE = "项目介绍"
HIGHLIGHT_TITLE = "项目亮点"
INFO_TITLE = "基本信息"
INVESTOR_TITLE = "投资人匹配"

PLACEHOLDER_TO_FIELD: dict[str, str] = {
    "项目名称": "project_name",
    "公司全称": "company_full_name",
    "所属区域": "region",
    "所属行业": "industry",
    "原始简介": "original_intro",
    "联系人名称": "contact_name",
    "转让底价": "transfer_floor_price",
    "对应持股比例": "equity_ratio",
    "拟募集金额": "capital_raise_amount",
}


class OnePagerMarkdownError(ValueError):
    """The Markdown structure is wrong or required sections are missing."""


#: frontmatter 键 -> 中文展示名，用于补正文表格未覆盖的字段。
_FRONTMATTER_TO_DISPLAY: dict[str, str] = {
    "project_name": "项目名称",
    "company_full_name": "公司全称",
    "region": "所属区域",
    "industry": "所属行业",
    "original_intro": "原始简介",
    "contact_name": "联系人名称",
    "transfer_floor_price": "转让底价",
    "equity_ratio": "对应持股比例",
    "capital_raise_amount": "拟募集金额",
    "fundraising_amount": "拟募集金额",
}


_FIELD_RE = re.compile(r"^-\s*([^：:]+)\s*[:：]\s*(.*)$")
#: 表格行："| 项目名称 | 惠然科技 |"。模型经常把基本信息写成两列表格而不是
#: 项目符号列表，两种都要认，否则字段全空、整份报告被拒。
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|?\s*$")
#: 表头与分隔行，例如 "| 项目 | 内容 |" / "|---|---|"
_TABLE_SKIP = {"项目", "内容", "字段", "值", "名称", "---", ":---", "---:"}


def _extract_frontmatter(md: str) -> dict[str, str]:
    """Read the leading ``---`` YAML block as a field fallback.

    The skill writes ``original_intro`` / ``fundraising_amount`` etc. into the
    frontmatter but the ``## 基本信息`` table only repeats a subset. Falling
    back to the frontmatter keeps those fields from coming back empty.
    """
    match = re.match(r"^---\s*\n(.+?)\n---\s*$", md, re.MULTILINE | re.DOTALL)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _extract_basic_info(md: str, business_type: BusinessType) -> dict[str, str]:
    match = re.search(
        rf"^##\s+{re.escape(INFO_TITLE)}\s*$(.+?)(?=^##\s+|\Z)",
        md,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise OnePagerMarkdownError(f"缺少 `{INFO_TITLE}` 章节")
    block = match.group(1)
    values: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        name = ""
        value = ""
        if line.startswith("-"):
            field = _FIELD_RE.match(line)
            if not field:
                continue
            name = field.group(1).strip()
            value = field.group(2).strip()
        elif line.startswith("|"):
            row = _TABLE_ROW_RE.match(line)
            if not row:
                continue
            name = row.group(1).strip()
            value = row.group(2).strip()
            if name in _TABLE_SKIP or set(value) <= {"-", ":", " "}:
                continue
        else:
            continue
        # Tolerate both "联系人名称" and "联系人" labels.
        if name == "联系人":
            name = "联系人名称"
        if name in PLACEHOLDER_TO_FIELD:
            values[name] = value
    return values


def _extract_sections(
    md: str, *, top_title: str, kind: str
) -> tuple[OnePagerSection, ...]:
    pattern = re.compile(
        rf"^##\s+{re.escape(top_title)}\s*$(.+?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(md)
    if not match:
        raise OnePagerMarkdownError(f"缺少 `{top_title}` 章节")
    body = match.group(1)
    sections: list[OnePagerSection] = []
    # 一次收集所有子段，再统一校验：逐个构造时 pydantic 会在第一个越界处
    # 抛错，模型只能看到一条错误、改一处、再撞下一处，很容易耗尽预算。
    drafts: list[tuple[str, str]] = []
    for heading_match in re.finditer(
        r"^###\s+(.+?)\s*$(.+?)(?=^###\s+|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    ):
        title = heading_match.group(1).strip()
        section_body = heading_match.group(2).strip()
        if not section_body:
            raise OnePagerMarkdownError(f"{top_title} · {title!r} 段正文为空")
        drafts.append((title, section_body))

    if not drafts:
        raise OnePagerMarkdownError(f"`{top_title}` 下没有子段")

    violations: list[str] = []
    for title, section_body in drafts:
        try:
            sections.append(
                OnePagerSection(title=title, body=section_body, kind=kind)
            )
        except Exception as exc:  # noqa: BLE001 - collect instead of bailing
            violations.append(f"{title}：{_clean_validation_message(exc)}")
    if violations:
        raise OnePagerMarkdownError(
            f"{top_title} 有 {len(violations)} 段不合规（一次列出，请一并修改）：\n- "
            + "\n- ".join(violations)
        )
    return tuple(sections)


def _clean_validation_message(exc: Exception) -> str:
    """Strip pydantic's wrapper so the model only sees the actionable sentence."""
    message = str(exc)
    for marker in ("Value error, ", "Assertion failed, "):
        if marker in message:
            message = message.split(marker, 1)[1]
            break
    # pydantic appends "[type=value_error, input_value=..., input_type=dict]"
    # and a docs URL; neither helps the model decide what to change.
    message = re.split(r"\s*\[type=", message, maxsplit=1)[0]
    message = message.split("For further information visit", 1)[0]
    return " ".join(message.split()).strip()


#: 表头别名：模型同义改写时仍然能对上列。
_NAME_HEADERS = ("投资人名称", "机构名称", "投资人", "名称", "公司名称")
_SOURCE_HEADERS = ("来源", "数据来源")
_TYPE_HEADERS = ("类型", "投资人类型", "机构类型")
_REASON_HEADERS = ("匹配理由", "理由", "匹配说明", "匹配逻辑")
_SCORE_HEADERS = ("权重分数", "分数", "得分")
_TAG_HEADERS = ("匹配标签", "标签")


def _first_index(index: dict[str, int], candidates: tuple[str, ...]) -> int | None:
    for name in candidates:
        if name in index:
            return index[name]
    return None


def _extract_investors(md: str) -> tuple[InvestorRow, ...]:
    """Pull the investor-matching table from the ``投资人匹配`` section.

    Column order is fixed by the header row, not positional guessing, so the
    optional ``匹配标签`` / ``权重分数`` columns can appear anywhere:

    ``序号 | 来源 | 类型 | 投资人名称 | [匹配标签] | [权重分数] | 匹配理由``
    """
    match = re.search(
        rf"^##\s+{re.escape(INVESTOR_TITLE)}\s*$\n((?:\|.*\n)+)",
        md,
        re.MULTILINE,
    )
    if not match:
        return ()
    lines = [line for line in match.group(1).splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return ()
    columns = _normalize_header(_table_cells(lines[0]))
    index = {name: position for position, name in enumerate(columns)}
    # 模型写表时列名并不稳定：见过「序号 | 机构名称 | 匹配理由」这种三列版本，
    # 以前只要缺「投资人名称」就整表丢弃，最终 docx 里一张表都没有。
    # 这里按别名解析，缺失的列用默认值兜底。
    name_at = _first_index(index, _NAME_HEADERS)
    if name_at is None:
        return ()
    source_at = _first_index(index, _SOURCE_HEADERS)
    type_at = _first_index(index, _TYPE_HEADERS)
    reason_at = _first_index(index, _REASON_HEADERS)
    score_at = _first_index(index, _SCORE_HEADERS)
    tags_at = _first_index(index, _TAG_HEADERS)

    rows: list[InvestorRow] = []
    for line in lines[1:]:
        if re.match(r"^\|[-:\s|]+\|\s*$", line):
            continue
        cells = _table_cells(line)
        if len(cells) <= name_at:
            continue
        raw_source = cells[source_at] if source_at is not None and source_at < len(cells) else ""
        source = "internal" if raw_source in {"内部库", "internal"} or not raw_source else "web"
        raw_type = cells[type_at] if type_at is not None and type_at < len(cells) else ""
        investor_type = "机构" if raw_type in {"", "机构", "internal", "web"} else raw_type
        reason = cells[reason_at] if reason_at is not None and reason_at < len(cells) else ""
        rows.append(
            InvestorRow(
                source=source,
                investor_type=investor_type,
                name=cells[name_at],
                match_reason=reason,
                score=_parse_score(cells[score_at]) if score_at is not None and score_at < len(cells) else None,
                matched_tags=_parse_tags(cells[tags_at]) if tags_at is not None and tags_at < len(cells) else (),
            )
        )
    return tuple(rows)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_header(cells: list[str]) -> list[str]:
    """Map known header spellings onto the canonical column names."""
    aliases = {
        "投资人类型": "类型",
        "投资者类型": "类型",
        "机构类型": "类型",
        "标签": "匹配标签",
        "匹配到的标签": "匹配标签",
        "分数": "权重分数",
        "权重": "权重分数",
    }
    return [aliases.get(cell, cell) for cell in cells]


def _parse_score(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return None


_TAG_SPLIT_RE = re.compile(r"[、,，;；]")


def _parse_tags(raw: str) -> tuple[MatchedTag, ...]:
    """Parse ``标签(0.812)、标签2`` back into structured tags."""
    text = raw.strip()
    if not text or text in {"-", "—", "无"}:
        return ()
    tags: list[MatchedTag] = []
    for chunk in _TAG_SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.match(r"^(.+?)\s*[（(]\s*([0-9.]+)\s*[)）]\s*$", chunk)
        if match:
            tags.append(
                MatchedTag(tag=match.group(1).strip(), weight=float(match.group(2)))
            )
        else:
            tags.append(MatchedTag(tag=chunk))
    return tuple(tags)


#: 写作期插入的来源标记，例如 ``<!-- src: material parse_materials /data/blocks/0/text -->``。
#: 这些是给 Word 批注用的锚点，绝不能出现在正文里；投资报告的 md_parser 已经
#: 剥离，一页纸这条链路漏了，标记会原样落进模板文本框。
def _strip_inline_markers(md: str) -> str:
    cleaned = strip_source_markers(md)
    # 标记删除后常留下行尾空白或整行空行，压平避免段间距被撑开。
    return re.sub(r"[ \t]+\n", "\n", cleaned)


def parse_one_pager_markdown(
    md_text: str,
    *,
    business_type: BusinessType,
    report_id: str,
) -> OnePagerContent:
    """Parse a strict-layout one-pager Markdown file."""
    if not md_text.strip():
        raise OnePagerMarkdownError("Markdown 为空")

    md_text = _strip_inline_markers(md_text)
    info = _extract_basic_info(md_text, business_type)
    # frontmatter 只补空缺字段：正文表格里有值就以正文为准。
    front = _extract_frontmatter(md_text)
    for front_key, display in _FRONTMATTER_TO_DISPLAY.items():
        if not info.get(display) and front.get(front_key):
            info[display] = front[front_key]
    intro_sections = _extract_sections(md_text, top_title=INTRO_TITLE, kind="intro")
    highlight_sections = _extract_sections(
        md_text, top_title=HIGHLIGHT_TITLE, kind="highlight"
    )
    investors = _extract_investors(md_text)

    project_name = info.get("项目名称") or ""
    company_full_name = info.get("公司全称") or ""
    region = info.get("所属区域") or ""
    industry = info.get("所属行业") or ""
    original_intro = info.get("原始简介") or ""
    contact_name = info.get("联系人名称") or ""

    kwargs: dict[str, object] = {
        "report_id": report_id,
        "business_type": business_type,
        "project_name": project_name,
        "company_full_name": company_full_name,
        "region": region,
        "industry": industry,
        "original_intro": original_intro,
        "contact_name": contact_name,
        "intro_sections": intro_sections,
        "highlight_sections": highlight_sections,
        "investors": investors,
    }
    if business_type is BusinessType.PROPERTY:
        kwargs["transfer_floor_price"] = info.get("转让底价")
    else:
        kwargs["equity_ratio"] = info.get("对应持股比例")
        kwargs["capital_raise_amount"] = info.get("拟募集金额")
    return OnePagerContent(**kwargs)


def parse_one_pager_markdown_file(
    path: str | Path,
    *,
    business_type: BusinessType,
    report_id: str,
) -> OnePagerContent:
    """Filesystem-friendly wrapper around :func:`parse_one_pager_markdown`."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_one_pager_markdown(
        text, business_type=business_type, report_id=report_id
    )
