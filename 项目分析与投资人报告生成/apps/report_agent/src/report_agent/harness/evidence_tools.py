"""Bounded reading of complete Data MCP evidence stored in the workspace."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from report_agent.infrastructure.evidence import WorkspaceEvidenceStore

#: MCP 工具 → 批注 kind。MCP 返回的都标「MCP数据」，材料解析标「原材料」。
_TOOL_KIND = {
    "parse_materials": "material",
    "extract_project_profile": "mcp",
    "query_track_labels": "mcp",
    "match_listed_peers": "mcp",
    "query_comparable_valuation": "mcp",
    "match_investors": "mcp",
    "query_company_registry": "mcp",
    "search_company_web": "web",
    "query_cbex_listing_financials": "mcp",
}

#: 各 MCP 写报告时常用的默认指针包；read_evidence_pack 未传 pointers 时按工具选用。
DEFAULT_EVIDENCE_PACKS: dict[str, tuple[str, ...]] = {
    "extract_project_profile": ("/data/profile", "/data/field_details"),
    "query_track_labels": ("/data/tags",),
    "match_listed_peers": ("/data/peers",),
    "query_comparable_valuation": ("/data/content",),
    "match_investors": ("/data/candidates", "/data/counts"),
    "query_company_registry": ("/data/company",),
    "search_company_web": ("/data/searches",),
    "query_cbex_listing_financials": ("/data/annual", "/data/latest"),
    "parse_materials": ("/data/blocks",),
}


def _kind_for(tool: str) -> str:
    return _TOOL_KIND.get(tool, "mcp")


def _src_marker(kind: str, tool: str, pointer: str, note: str) -> str:
    """Build the write-time provenance marker the model pastes after a sentence."""
    note = " ".join(str(note or "").split())
    return f"<!-- src: {kind} {tool} {pointer} ; {note} -->"


#: API 字段名 -> 阅读者看得懂的中文名。
#:
#: The comment is read by an investment reviewer, not by an engineer: a note that
#: says ``insured_count=127`` forces them to translate, and the field name has
#: leaked into delivered documents. Unknown keys fall through unchanged so a new
#: API field still shows up instead of being silently dropped.
_FIELD_LABELS: dict[str, str] = {
    # 工商
    "company": "工商信息",
    "registered_capital": "注册资本",
    "paid_in_capital": "实缴资本",
    "establish_date": "成立日期",
    "legal_representative": "法定代表人",
    "address": "注册地址",
    "business_scope": "经营范围",
    "insured_count": "参保人数",
    "staff_range": "员工规模",
    "company_name": "公司名称",
    # 投资人匹配
    "candidates": "投资人候选",
    "counts": "计数",
    "internal_institutions": "内部库机构数",
    "internal_individuals_excluded": "已排除个人候选数",
    "network_institutions": "网络机构数",
    "shareholder_filter_applied": "已按股东过滤",
    "investor_type": "投资人类型",
    "match_reason": "匹配理由",
    "match_text": "匹配文本",
    "score": "权重分数",
    "source": "来源",
    "name": "名称",
    # 赛道与画像
    "tags": "赛道标签",
    "profile": "项目画像",
    "industry": "所属行业",
    "main_business": "主营业务",
    "peers": "可比上市公司",
    "content": "内容",
    "status": "状态",
    # 财务（保留通行缩写）
    "revenue": "营业收入",
    "net_profit": "净利润",
}


def _label(key: object) -> str:
    name = str(key)
    return _FIELD_LABELS.get(name, name)


def _summarize(value: object, *, limit: int = 80) -> str:
    """One-line preview of an evidence slice, used as the default comment text."""
    if isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:4]:
            if isinstance(item, (dict, list)):
                continue
            parts.append(f"{_label(key)}={item}")
        text = " / ".join(parts)
    elif isinstance(value, list):
        if value and isinstance(value[0], dict):
            first = value[0]
            parts = []
            for key, item in list(first.items())[:4]:
                if isinstance(item, (dict, list)):
                    continue
                parts.append(f"{_label(key)}={item}")
            text = "；".join(parts)
            if len(value) > 1:
                text = f"[共{len(value)}条] " + text
        else:
            text = "、".join(str(v) for v in value[:6])
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:limit]


def _retrieved_at(store: WorkspaceEvidenceStore, evidence_id: str) -> str:
    """When the source was fetched. Only web sources carry one."""
    try:
        payload = store.get(evidence_id)
    except Exception:  # noqa: BLE001 - an unreadable envelope is not fatal here
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("retrieved_at") or "")


def _web_note(value: object, retrieved_at: str) -> str:
    """A web citation note that already carries the four required elements.

    Publisher, title, link and retrieval date — without them a reader cannot
    re-check the claim or tell how old it is.
    """
    items = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        site = str(item.get("site_name") or "").strip()
        if not (title or url):
            continue
        parts.append("｜".join(part for part in (site, title, url) if part))
    note = "；".join(parts)
    if retrieved_at:
        note = (note + "｜" if note else "") + "检索日期：" + retrieved_at[:10]
    return note or _summarize(value)


#: 列表型字段按行给出 src。报告正文投资人表最多 30 行，可比公司默认不超过 10 行。
_ROW_SRC_LIMITS: dict[str, int] = {
    "/data/peers": 10,
    "/data/candidates": 30,
}


def _row_srcs(
    evidence_id: str,
    pointer: str,
    value: object,
    tool: str,
) -> list[dict[str, str]]:
    """Per-row provenance so a table does not share one src across companies."""
    limit = _ROW_SRC_LIMITS.get(pointer.rstrip("/"))
    if limit is None or not isinstance(value, list):
        return []
    kind = _kind_for(tool)
    rows: list[dict[str, str]] = []
    for index, item in enumerate(value[:limit]):
        if not isinstance(item, dict):
            continue
        child = f"{pointer.rstrip('/')}/{index}"
        preview = _summarize(item, limit=160)
        rows.append(
            {
                "json_pointer": child,
                "preview": preview,
                "src": _src_marker(kind, tool, child, preview),
            }
        )
    return rows


def _normalize_pointers(pointers: list[str] | str | None) -> list[str]:
    """Accept a list, JSON-encoded list, or comma-separated pointer string."""
    if pointers is None:
        return []
    if isinstance(pointers, list):
        return [str(item).strip() for item in pointers if str(item).strip()]
    raw = str(pointers).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        raw = raw.strip("[]")
    return [part for part in re.split(r"[,，\s]+", raw) if part]


def _read_one_pointer(
    store: WorkspaceEvidenceStore,
    evidence_id: str,
    json_pointer: str,
    *,
    tool: str,
) -> dict[str, Any]:
    value = store.read_pointer(evidence_id, json_pointer)
    kind = _kind_for(tool)
    retrieved_at = ""
    note = _summarize(value)
    if tool == "search_company_web":
        retrieved_at = _retrieved_at(store, evidence_id)
        note = _web_note(value, retrieved_at)
    return {
        "evidence_id": evidence_id,
        "json_pointer": json_pointer,
        "tool": tool,
        "value": value,
        "retrieved_at": retrieved_at,
        "cite": f"<!-- cite: {evidence_id} -->",
        "src": _src_marker(kind, tool, json_pointer, note),
    }


class ReadEvidencePackArgs(BaseModel):
    evidence_id: str = Field(min_length=1, description="evidence_xxx")
    pointers: str | list[str] = Field(
        default="",
        description=(
            "要读取的 RFC 6901 指针列表；可传数组或逗号分隔字符串。"
            "留空则按该 evidence 对应 MCP 工具的默认包读取。"
        ),
    )


def build_evidence_tools(store: WorkspaceEvidenceStore) -> tuple[StructuredTool, ...]:
    def read_evidence_chunk(evidence_id: str, offset: int = 0, limit: int = 12000) -> str:
        return json.dumps(
            asdict(store.read_chunk(evidence_id, offset=offset, limit=limit)), ensure_ascii=False
        )

    def list_evidence_pointers(evidence_id: str, prefix: str = "/data", max_depth: int = 3) -> str:
        return json.dumps(
            store.list_pointers(evidence_id, prefix=prefix, max_depth=max_depth),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def read_evidence(evidence_id: str, json_pointer: str) -> str:
        # Return the ready-to-paste provenance marker with the value so the model
        # tags the sentence *while writing*. The marker carries kind/tool/pointer,
        # so the Word comment is generated from the same bytes — no post-hoc
        # match_text lookup that can miss or land on the wrong paragraph.
        try:
            tool = str(store.tool_for(evidence_id) or "")
        except Exception:  # noqa: BLE001 - index may be older than the store API
            tool = ""
        item = _read_one_pointer(store, evidence_id, json_pointer, tool=tool)
        item["usage"] = (
            "写入报告时，把 src 字段原样粘在引用该数据的句子末尾。"
            "src 里的 kind/tool/pointer 会直接生成 Word 批注，"
            "note 段可改写成更贴合语境的说明。"
            + (
                "网上来源的 note 必须保留发布机构、标题、链接和检索日期，"
                "否则读者无法复核。"
                if tool == "search_company_web"
                else ""
            )
        )
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    def read_evidence_pack(
        evidence_id: str, pointers: list[str] | str | None = None
    ) -> str:
        """Read several pointers once so the agent does not burn a model turn per field."""
        try:
            tool = str(store.tool_for(evidence_id) or "")
        except Exception:  # noqa: BLE001
            tool = ""
        requested = _normalize_pointers(pointers)
        if not requested:
            requested = list(DEFAULT_EVIDENCE_PACKS.get(tool) or ())
        if not requested:
            return json.dumps(
                {
                    "evidence_id": evidence_id,
                    "tool": tool,
                    "items": [],
                    "missing": [],
                    "error": (
                        "未指定 pointers，且该 evidence 没有默认包；"
                        "请传 pointers，或先 list_evidence_pointers。"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

        items: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        for pointer in requested:
            try:
                item = _read_one_pointer(store, evidence_id, pointer, tool=tool)
            except KeyError:
                missing.append({"json_pointer": pointer, "reason": "not_found"})
                continue
            except Exception as exc:  # noqa: BLE001 - keep other pointers usable
                missing.append(
                    {"json_pointer": pointer, "reason": type(exc).__name__}
                )
                continue
            rows = _row_srcs(evidence_id, pointer, item.get("value"), tool)
            if rows:
                item["row_srcs"] = rows
                item["row_src_note"] = (
                    "表格每一行使用对应 row_srcs.src，禁止整表共用本 item 的 src。"
                )
                value = item.get("value")
                if isinstance(value, list) and len(value) > len(rows):
                    item["row_srcs_omitted"] = len(value) - len(rows)
            items.append(item)

        return json.dumps(
            {
                "evidence_id": evidence_id,
                "tool": tool,
                "items": items,
                "missing": missing,
                "usage": (
                    "每个 item 含 value/cite/src。写报告时把对应 src 粘到句子末尾。"
                    "peers/candidates 若带 row_srcs，表格每一行必须用该行的 src。"
                    "missing 里的指针可再用 read_evidence 单独补读。"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def search_evidence(
        evidence_id: str, query: str, mode: str = "literal", limit: int = 20
    ) -> str:
        if mode not in {"literal", "regex"}:
            raise ValueError("mode must be literal or regex")
        return json.dumps(
            store.search(evidence_id, query, regex=mode == "regex", limit=limit),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return (
        StructuredTool.from_function(
            read_evidence_chunk,
            name="read_evidence_chunk",
            description=(
                "Read a bounded chunk of a stored evidence envelope. The returned content "
                "is serialized JSON for the complete envelope. Works for BOTH source materials "
                "(paths like /data/blocks/N/text) AND Data MCP tool returns (match_listed_peers, "
                "query_track_labels, query_comparable_valuation, match_investors) which are "
                "stored at /data/peers, /data/tags, /data/content, /data/candidates respectively. "
                "Prefer read_evidence_pack for the default fields needed to write the report. "
                "Use list_evidence_pointers first to discover valid paths."
            ),
        ),
        StructuredTool.from_function(
            list_evidence_pointers,
            name="list_evidence_pointers",
            description=(
                "List valid RFC 6901 pointers under an evidence prefix before citing facts. "
                "Usually unnecessary when using read_evidence_pack with the tool default pack. "
                "Example paths: /data/peers, /data/tags, /data/candidates, /data/content."
            ),
        ),
        StructuredTool.from_function(
            read_evidence_pack,
            name="read_evidence_pack",
            description=(
                "一次读取某 evidence 的多个字段，并带上可粘贴的 src/cite。"
                "每个成功的 Data MCP 调用后优先用本工具（留空 pointers 即用该工具默认包："
                "profile/tags/peers/content/candidates+counts/company）。"
                "摘要不是数据；empty/failed 的 eid 不要读。"
            ),
            args_schema=ReadEvidencePackArgs,
        ),
        StructuredTool.from_function(
            read_evidence,
            name="read_evidence",
            description=(
                "Read one exact value from complete Evidence by RFC 6901 JSON pointer. "
                "Prefer read_evidence_pack after each MCP call; use this for a single "
                "missing pointer or a deep path not in the default pack. Example: "
                "read_evidence(evidence_id='evidence_abc...', json_pointer='/data/peers/0')."
            ),
        ),
        StructuredTool.from_function(
            search_evidence,
            name="search_evidence",
            description=(
                "Search complete Evidence and return bounded pointer/value matches. "
                "Prefer read_evidence_pack or read_evidence for precise field access."
            ),
        ),
    )
