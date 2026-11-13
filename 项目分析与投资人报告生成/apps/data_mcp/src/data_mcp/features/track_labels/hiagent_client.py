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
    parse_json_payload as _parse_json_payload,
)
from data_mcp.shared.integrations.hiagent import (
    serialize_profile as _profile_to_state_value,
)
from data_mcp.shared.settings import load_http_retry_config, load_track_labels_config


def _split_tag_text(text: str) -> list[str]:
    cleaned = str(text or "").strip().strip("[]")
    if not cleaned:
        return []
    parts: list[str] = []
    for sep in ("，", ",", ";", "；", "|", "\n"):
        if sep in cleaned:
            parts = [p.strip(" -•\t\"'") for p in cleaned.split(sep)]
            break
    if not parts:
        parts = [cleaned.strip(" -•\t\"'")]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        out.append(part)
    return out


def _tags_from_result_object(parsed: dict[str, Any]) -> list[str]:
    """从智能体结果对象提取标签：优先「赛道标签」，其次 tag1/tag2/tag3…。"""
    for key in ("赛道标签", "tags", "class4Tag", "track_tags", "labels"):
        val = parsed.get(key)
        if isinstance(val, list):
            return list(dict.fromkeys(str(x).strip() for x in val if str(x).strip()))
        if isinstance(val, str) and val.strip():
            return _split_tag_text(val)

    numbered: list[tuple[int, str]] = []
    for key, value in parsed.items():
        key_text = str(key or "").strip().lower()
        if not key_text.startswith("tag"):
            continue
        suffix = key_text[3:]
        if not suffix.isdigit():
            continue
        tag = str(value or "").strip()
        if tag:
            numbered.append((int(suffix), tag))
    if numbered:
        numbered.sort(key=lambda x: x[0])
        return list(dict.fromkeys(tag for _, tag in numbered))
    return []


def _parse_tags_from_content(content: str) -> list[str]:
    if not isinstance(content, str) or not content.strip():
        return []
    cleaned = strip_markdown_fence(content.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None
        obj_start = cleaned.find("{")
        obj_end = cleaned.rfind("}")
        if obj_start >= 0 and obj_end > obj_start:
            try:
                parsed = json.loads(cleaned[obj_start : obj_end + 1])
            except json.JSONDecodeError:
                parsed = None
        if parsed is None:
            arr_start = cleaned.find("[")
            arr_end = cleaned.rfind("]")
            if arr_start >= 0 and arr_end > arr_start:
                try:
                    parsed = json.loads(cleaned[arr_start : arr_end + 1])
                except json.JSONDecodeError:
                    parsed = None

    if isinstance(parsed, dict):
        return _tags_from_result_object(parsed)
    if isinstance(parsed, list):
        out: list[str] = []
        for item in parsed:
            if isinstance(item, dict):
                out.extend(_tags_from_result_object(item))
            elif isinstance(item, str):
                nested = _parse_tags_from_content(item)
                if nested:
                    out.extend(nested)
                else:
                    tag = item.strip()
                    if tag and not tag.startswith("{") and not tag.startswith("**"):
                        out.append(tag)
        return list(dict.fromkeys(out))
    return []


def _pick_choice_contents(payload: dict[str, Any]) -> list[str]:
    """优先取 choices[-1].content，再依次回退到其他 choice。"""
    choice = payload.get("choices", payload.get("choice"))
    items: list[Any]
    if isinstance(choice, list):
        items = choice
    elif isinstance(choice, dict):
        items = [choice]
    else:
        return []

    contents: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("content")
        if isinstance(raw, str) and raw.strip():
            contents.append(raw)

    if len(contents) > 1:
        # 最后一条通常是「确定回复」终选结果
        return [contents[-1]] + contents[:-1]
    return contents


def parse_selected_tags(payload: dict[str, Any]) -> list[str]:
    """从 HiAgent 响应解析终选标签。

    优先 choices[-1].content 中的「赛道标签」列表；
    不优先回传的 state.tags。
    """
    for content in _pick_choice_contents(payload):
        tags = _parse_tags_from_content(content)
        if tags:
            return tags

    fallback_content = extract_choice_content(payload)
    if fallback_content:
        tags = _parse_tags_from_content(fallback_content)
        if tags:
            return tags

    state = payload.get("state")
    if isinstance(state, dict):
        raw = state.get("tags")
        if isinstance(raw, list):
            tags = [str(x).strip() for x in raw if str(x).strip()]
            if tags:
                return list(dict.fromkeys(tags))
        if isinstance(raw, str) and raw.strip():
            tags = _parse_tags_from_content(raw)
            if tags:
                return tags
            tags = _split_tag_text(raw)
            if tags:
                return tags
    return []


def invoke_track_label_agent(
    company_name: str,
    project_profile: str | dict[str, Any],
    env: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """调用打标签 HiAgent（公司名 + 项目画像），返回解析后的标签列表。"""
    company = str(company_name or "").strip()
    if not company:
        raise ValueError("company_name 不能为空")
    if project_profile is None or project_profile == "" or project_profile == {}:
        raise ValueError("project_profile 不能为空")

    full = config or load_track_labels_config(env)
    hi = full.get("hiagent") if isinstance(full.get("hiagent"), dict) else None
    if not isinstance(hi, dict):
        raise RuntimeError("track_labels.hiagent 未配置")

    host = str(hi.get("host") or "").strip().rstrip("/")
    token = str(hi.get("token") or "").strip()
    agent_id = str(hi.get("agent_id") or "").strip()
    path = str(hi.get("path") or "").strip()
    if not host or not path or not token or not agent_id:
        raise RuntimeError("track_labels.hiagent host/path/token/agent_id 未配置完整")

    profile_value = _profile_to_state_value(project_profile)

    url = f"{host}{path}"
    payload = {
        "agentId": agent_id,
        "chatId": hi.get("chat_id"),
        "userChatInput": "",
        "state": {
            "company_name": company,
            "project_profile": profile_value,
        },
        "buttonKey": hi.get("button_key"),
        "debug": bool(hi.get("debug", False)),
    }
    headers = {
        "token": token,
        "Content-Type": "application/json",
    }
    timeout = float(hi.get("timeout_seconds") or 120)
    retry_cfg = load_http_retry_config()

    try:
        response = http_request(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            service_name="track_labels_hiagent",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("赛道标签智能体", exc)

    try:
        raw = response.json()
    except json.JSONDecodeError:
        raw = response.text
    try:
        data = _parse_json_payload(raw)
    except (json.JSONDecodeError, ValueError):
        raise_invalid_json_response(
            "赛道标签智能体",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    tags = parse_selected_tags(data)
    if not tags:
        raise ExternalServiceError("赛道标签智能体", "赛道标签智能体未返回有效标签")
    return tags
