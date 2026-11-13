from __future__ import annotations

import json
from typing import Any

from data_mcp.shared.http.errors import (
    ExternalServiceError,
    raise_from_http_error,
    raise_invalid_json_response,
)
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.integrations.hiagent import (
    extract_choice_content,
    strip_markdown_fence,
)
from data_mcp.shared.integrations.hiagent import (
    format_tags_for_state as normalize_tags,
)
from data_mcp.shared.integrations.hiagent import (
    parse_json_payload as _parse_json_payload,
)
from data_mcp.shared.integrations.hiagent import (
    serialize_profile as _profile_to_state_value,
)
from data_mcp.shared.settings import load_http_retry_config, load_investor_network_config


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def parse_network_investor_content(content: str) -> list[dict[str, Any]]:
    """从智能体 content 提取机构列表。"""
    if not isinstance(content, str) or not content.strip():
        return []

    cleaned = strip_markdown_fence(content.strip())
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                parsed = None
        if parsed is None:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None

    items: list[Any]
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        for key in ("investors", "institutions", "items", "results", "data"):
            if isinstance(parsed.get(key), list):
                items = parsed[key]
                break
        else:
            # 单对象
            items = [parsed]
    else:
        # 按行拆
        items = [line.strip(" -•\t") for line in cleaned.splitlines() if line.strip()]

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = ""
        reason = "网络搜索命中行业/标的类型意向"
        source_url = ""
        source_name = ""
        raw: dict[str, Any] = {}
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw = item
            name = str(
                item.get("name")
                or item.get("investor_name")
                or item.get("institution")
                or item.get("机构名称")
                or ""
            ).strip()
            reason = str(
                item.get("match_reason")
                or item.get("reason")
                or item.get("理由")
                or reason
            )
            source_url = _first_text(item, ("source_url", "url", "link", "href", "网页"))
            source_name = _first_text(item, ("source_name", "title", "来源", "source_title"))
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "name": name,
                "score": None,
                "match_reason": reason,
                "source_url": source_url,
                "source_name": source_name,
                "raw": raw,
                "usr_cgy_cd_dsc": "机构",
            }
        )
    return out


def invoke_network_investor_agent(
    project_profile: str | dict[str, Any],
    track_tags: str | list[Any] | None,
    env: str | None = None,
) -> list[dict[str, Any]]:
    """调用网络投资人低代码智能体，返回候选机构列表。"""
    cfg = load_investor_network_config(env)
    url = f"{cfg['host']}{cfg['path']}"
    payload = {
        "agentId": cfg["agent_id"],
        "chatId": cfg["chat_id"],
        "userChatInput": "",
        "state": {
            "project_profile": _profile_to_state_value(project_profile),
            "track_tags": normalize_tags(track_tags),
        },
        "buttonKey": cfg["button_key"],
        "debug": cfg["debug"],
    }
    headers = {
        "token": cfg["token"],
        "Content-Type": "application/json",
    }

    retry_cfg = load_http_retry_config()
    try:
        response = http_request(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=cfg["timeout_seconds"],
            service_name="investor_network",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("网络投资人智能体", exc)

    try:
        raw = response.json()
    except json.JSONDecodeError:
        raw = response.text
    try:
        data = _parse_json_payload(raw)
    except (json.JSONDecodeError, ValueError):
        raise_invalid_json_response(
            "网络投资人智能体",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    content = extract_choice_content(data)
    if content is None:
        raise ExternalServiceError("网络投资人智能体", "网络投资人智能体响应缺少有效内容")
    return parse_network_investor_content(content)
