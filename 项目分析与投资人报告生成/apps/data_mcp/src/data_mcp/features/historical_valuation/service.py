from __future__ import annotations

import json
from typing import Any

from data_mcp.shared.http.errors import raise_from_http_error, raise_invalid_json_response
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.integrations.hiagent import (
    format_tags_for_state as normalize_tags,
)
from data_mcp.shared.integrations.hiagent import (
    parse_json_payload as _parse_json_payload,
)
from data_mcp.shared.settings import load_historical_valuation_config, load_http_retry_config


def query_comparable_valuation(
    tags: str | list[Any],
    company_name: str = "",
    env: str | None = None,
) -> dict[str, Any]:
    """查询历史成交可比估值，只返回 choice 与 state。"""
    formatted_tags = normalize_tags(tags).strip()
    if not formatted_tags or formatted_tags in {"[]", "[ ]"}:
        raise ValueError("tags 不能为空")

    cfg = load_historical_valuation_config(env)
    url = f"{cfg['host']}{cfg['path']}"
    payload = {
        "agentId": cfg["agent_id"],
        "chatId": cfg["chat_id"],
        "userChatInput": "",
        "state": {
            "company_name": "" if company_name is None else str(company_name).strip(),
            "tags": formatted_tags,
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
            service_name="historical_valuation",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("hiagent", exc)

    try:
        raw = response.json()
    except json.JSONDecodeError:
        raw = response.text
    try:
        data = _parse_json_payload(raw)
    except (json.JSONDecodeError, ValueError):
        raise_invalid_json_response(
            "hiagent",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    return {
        "choice": data.get("choice", data.get("choices")),
        "state": data.get("state"),
    }
