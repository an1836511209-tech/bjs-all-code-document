"""Runtime validation against the repository's canonical MCP contracts."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from data_mcp.shared.settings import DATA_MCP_ROOT

DEFAULT_CONTRACTS_DIR = DATA_MCP_ROOT.parent.parent / "contracts" / "mcp"


def contracts_dir() -> Path:
    override = os.getenv("DATA_MCP_CONTRACTS_DIR", "").strip()
    if not override:
        return DEFAULT_CONTRACTS_DIR
    path = Path(override)
    return path if path.is_absolute() else DATA_MCP_ROOT.parent.parent / path


@cache
def _load_contract_file(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_file():
        raise FileNotFoundError(f"未找到 MCP 契约: {path}")
    with path.open("r", encoding="utf-8") as stream:
        contract = json.load(stream)
    if not isinstance(contract, dict):
        raise ValueError(f"MCP 契约必须是 JSON 对象: {path}")
    return contract


def load_tool_contract(tool_name: str) -> dict[str, Any]:
    path = contracts_dir() / f"{tool_name}.json"
    return _load_contract_file(str(path))


def get_tool_schema(
    tool_name: str,
    *,
    kind: Literal["input", "output"],
) -> dict[str, Any]:
    contract = load_tool_contract(tool_name)
    key = f"{kind}_schema"
    schema = contract.get(key)
    if not isinstance(schema, dict):
        raise KeyError(f"MCP 契约缺少 {key}: {tool_name}")
    Draft202012Validator.check_schema(schema)
    return schema


def validate_tool_payload(
    tool_name: str,
    payload: Any,
    *,
    kind: Literal["input", "output"],
) -> None:
    validator = Draft202012Validator(get_tool_schema(tool_name, kind=kind))
    try:
        validator.validate(payload)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "(root)"
        raise ValueError(f"{tool_name} {kind} 不符合 schema: {location}: {exc.message}") from exc


def validate_tool_input(tool_name: str, payload: dict[str, Any]) -> None:
    validate_tool_payload(tool_name, payload, kind="input")


def validate_tool_output(tool_name: str, payload: Any) -> None:
    validate_tool_payload(tool_name, payload, kind="output")
