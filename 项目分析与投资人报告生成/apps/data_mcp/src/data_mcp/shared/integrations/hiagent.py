"""Protocol helpers shared by HiAgent-backed business features."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def format_tags_for_state(tags: str | list[Any] | None) -> str:
    if tags is None:
        return ""
    if isinstance(tags, list):
        return "[" + "，".join(str(item) for item in tags) + "]"
    return str(tags)


def parse_json_payload(raw: Any) -> dict[str, Any]:
    data = raw
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("hiagent平台返回不是 JSON 对象")

    nested = data.get("data")
    if isinstance(nested, str):
        try:
            parsed = json.loads(nested)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    elif isinstance(nested, dict) and (
        "choice" in nested or "choices" in nested or "state" in nested
    ):
        data = nested
    return data


def strip_markdown_fence(text: str) -> str:
    raw = text.strip()
    match = _FENCE_RE.match(raw)
    return match.group(1).strip() if match else raw


def extract_choice_content(payload: dict[str, Any]) -> str | None:
    choice = payload.get("choice", payload.get("choices"))
    if isinstance(choice, list):
        if not choice:
            return None
        first = choice[0]
        if isinstance(first, dict):
            content = first.get("content")
            return content if isinstance(content, str) else None
        return None
    if isinstance(choice, dict):
        content = choice.get("content")
        return content if isinstance(content, str) else None
    return None


def serialize_profile(project_profile: str | dict[str, Any]) -> str:
    if isinstance(project_profile, dict):
        return json.dumps(project_profile, ensure_ascii=False)
    return str(project_profile)
