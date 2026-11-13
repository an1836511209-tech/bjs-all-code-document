"""Expose the contract-safe Data MCP gateway as Agent tools."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import StructuredTool

from report_agent.application.data_gateway import DataMcpGateway
from report_agent.application.interactions import (
    cbex_listing_question,
    cbex_project_question,
    read_interaction,
    registry_name_question,
    update_interaction,
)
from report_agent.runtime.workspace import TaskWorkspace

#: 临时覆盖开关：部署环境连不上赛道标签的一级接口时，直接跳过整次查询。
#:
#: 为什么放在 report_agent 而不是 data_mcp：那部分是同事的模块，而连不上内网
#: 地址是**部署环境**的问题（测试机不在 10.254.x 网段），不是业务逻辑问题。
#: 放在这里可以随环境开关，网络打通或换机器后直接取消环境变量即可，不用改代码。
#:
#: 代价要说清楚：跳过后本次不会返回赛道标签（data_mcp 内部的 HiAgent / 本地
#: 标签库兜底也一并跳过），投资人匹配会退化为按项目画像文本匹配。所以默认关闭，
#: 只有在"接口必然不可达"的环境里才打开。
SHORTCUT_ENV = "REPORT_AGENT_TRACK_LABELS_PROBE_URL"
SHORTCUT_TIMEOUT_ENV = "REPORT_AGENT_TRACK_LABELS_PROBE_TIMEOUT"
DEFAULT_PROBE_TIMEOUT = 3.0

# 查到登记全称后，用它覆盖这些工具里模型传入的化名或文件名。
_COMPANY_NAME_TOOLS = frozenset({
    "extract_project_profile",
    "query_track_labels",
    "match_investors",
    "search_company_web",
    "query_comparable_valuation",
})


def _probe_sync(url: str, timeout: float) -> str:
    """返回不可达原因；可达返回空串。"""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ""
    except OSError as exc:
        return f"{host}:{port} 不可达（{type(exc).__name__}）"


def _shortcut_reason() -> str:
    """环境开关打开且地址不可达时，返回跳过原因。"""
    url = (os.environ.get(SHORTCUT_ENV) or "").strip()
    if not url:
        return ""
    try:
        timeout = float(os.environ.get(SHORTCUT_TIMEOUT_ENV) or DEFAULT_PROBE_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_PROBE_TIMEOUT
    return _probe_sync(url, timeout)


def _shortcut_payload(reason: str) -> str:
    return json.dumps(
        {
            "status": "partial",
            "tags": [],
            "summary": (
                "赛道标签接口在本次部署环境不可达，已按临时覆盖跳过本次查询。"
                "请改用材料里的业务与产品描述判断赛道方向，并在批注中说明"
                "「按材料推断」，不要编造标签代码。"
            ),
            "warnings": [{"code": "TRACK_LABELS_SHORTCUT", "message": reason}],
            "meta": {"shortcut": True},
        },
        ensure_ascii=False,
    )



def build_data_mcp_tools(gateway: DataMcpGateway, *, workspace: TaskWorkspace | None = None) -> tuple[StructuredTool, ...]:
    return tuple(_build_tool(gateway, name, workspace) for name in sorted(gateway.contracts.enabled_tools))


def _investment_registry_hold(name: str, interaction: dict[str, Any]) -> str | None:
    """投资报告在工商查询有结果或用户跳过之前，不调用其他数据工具。"""
    if interaction.get("active_skill") != "investment-report" or name == "query_company_registry":
        return None
    if (interaction.get("registry_lookup") or {}).get("status") in {"found", "skipped"}:
        return None
    return json.dumps(
        {
            "status": "blocked",
            "summary": (
                "投资报告须先完成工商查询。请调用 query_company_registry，"
                "公司名称用材料正文里写明的企业名，不要用上传文件名。"
                "查不到、名称不精确或接口失败时，使用返回的问题卡片："
                "用户可填写登记全称后重试，也可以跳过此步骤，按已有材料继续。"
            ),
            "next_actions": ["query_company_registry"],
        },
        ensure_ascii=False,
    )


def _build_tool(gateway: DataMcpGateway, name: str, workspace: TaskWorkspace | None = None) -> StructuredTool:
    async def invoke(**arguments: Any) -> str:
        interaction = read_interaction(workspace) if workspace is not None else {}
        held = _investment_registry_hold(name, interaction)
        if held is not None:
            return held
        confirmed = str((interaction.get("registry_lookup") or {}).get("company_name") or "").strip()
        if (
            interaction.get("active_skill") == "investment-report"
            and (interaction.get("registry_lookup") or {}).get("status") == "found"
            and name in _COMPANY_NAME_TOOLS
            and confirmed
        ):
            arguments = {**arguments, "company_name": confirmed}
        cbex = name == "query_cbex_listing_financials" and workspace is not None
        if cbex:
            lookup = read_interaction(workspace).get("cbex_lookup") or {}
            if lookup.get("status") == "skipped":
                return json.dumps({"status": "skipped", "summary": "按用户选择跳过挂牌财务查询。"}, ensure_ascii=False)
            if not lookup.get("project_name"):
                return json.dumps({"status": "needs_user_input", "question_request": cbex_listing_question()}, ensure_ascii=False)
            # User input and the server-held candidate URL are authoritative.
            arguments = {"project_name": lookup["project_name"]}
            if lookup.get("detail_url"):
                arguments["detail_url"] = lookup["detail_url"]
        optional_registry = name == "query_company_registry" and workspace is not None
        if optional_registry:
            lookup = read_interaction(workspace).get("registry_lookup") or {}
            if lookup.get("status") == "skipped":
                return json.dumps({"status": "skipped", "summary": "用户已跳过工商查询，按已有材料继续，不要重复询问。"}, ensure_ascii=False)
            if lookup.get("company_name"):
                arguments = {**arguments, "company_name": lookup["company_name"]}
        try:
            if name == "query_track_labels":
                reason = await asyncio.to_thread(_shortcut_reason)
                if reason:
                    return _shortcut_payload(reason)
            view = await gateway.call(name, arguments)
            output = asdict(view)
        except Exception:
            if not optional_registry:
                raise
            output = {"status": "failed", "summary": "企查查工商查询暂不可用"}
        if cbex:
            payload = json.loads(workspace.resolve(view.path).read_text(encoding="utf-8"))
            candidates = payload.get("data", {}).get("candidates") or []
            if candidates:
                output.update(status="needs_user_input", question_request=cbex_project_question(candidates))
        if optional_registry:
            company_name = str(arguments.get("company_name") or "")
            warnings = output.get("warnings") or []
            needs_name = output["status"] in {"empty", "failed"} or any(
                warning.get("code") in {"COMPANY_NAME_NOT_EXACT", "COMPANY_NOT_FOUND"}
                or any(word in str(warning.get("message") or "") for word in ("精确", "全称", "名称不匹配"))
                for warning in warnings if isinstance(warning, dict)
            )
            if needs_name:
                output.update(status="needs_user_input", question_request=registry_name_question(company_name))
                update_interaction(workspace, registry_lookup={"status": "needs_correction", "company_name": company_name})
            else:
                update_interaction(workspace, registry_lookup={"status": "found", "company_name": company_name})
        return json.dumps(output, ensure_ascii=False, separators=(",", ":"))

    return StructuredTool(
        name=name,
        description=gateway.contracts.description(name),
        args_schema=gateway.contracts.input_schema(name),
        coroutine=invoke,
        metadata={"provider": "data_mcp", "evidence_backed": True},
    )
