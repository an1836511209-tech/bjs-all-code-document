"""Read and validate the shared Data MCP JSON contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


class McpContractError(ValueError):
    """Raised when a shared MCP contract or payload is invalid."""


class McpContractRegistry:
    def __init__(self, root: Path, enabled_tools: tuple[str, ...]) -> None:
        self._root = Path(root).resolve()
        self._enabled_tools = frozenset(enabled_tools)
        self._contracts = {name: self._load(name) for name in enabled_tools}

    @property
    def enabled_tools(self) -> frozenset[str]:
        return self._enabled_tools

    def validate_input(self, tool: str, payload: dict[str, Any]) -> None:
        self._validate(tool, "input_schema", payload)

    def validate_output(self, tool: str, payload: dict[str, Any]) -> None:
        self._validate(tool, "output_schema", payload)

    def input_schema(self, tool: str) -> dict[str, Any]:
        return deepcopy(self._contract(tool)["input_schema"])

    def description(self, tool: str) -> str:
        description = self._contract(tool).get("description")
        return description if isinstance(description, str) and description else tool

    def _validate(self, tool: str, schema_name: str, payload: dict[str, Any]) -> None:
        contract = self._contract(tool)
        try:
            Draft202012Validator(contract[schema_name]).validate(payload)
        except ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            raise McpContractError(
                f"{tool} {schema_name} validation failed at {location}: {exc.message}"
            ) from exc

    def _contract(self, tool: str) -> dict[str, Any]:
        if tool not in self._enabled_tools:
            raise McpContractError(f"MCP tool is not enabled: {tool}")
        return self._contracts[tool]

    def _load(self, tool: str) -> dict[str, Any]:
        path = (self._root / f"{tool}.json").resolve()
        if path.parent != self._root or not path.is_file():
            raise McpContractError(f"MCP contract is missing: {tool}")
        try:
            contract = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise McpContractError(f"MCP contract cannot be read: {tool}") from exc
        if contract.get("tool") != tool:
            raise McpContractError(f"MCP contract tool mismatch: {tool}")
        if not isinstance(contract.get("input_schema"), dict) or not isinstance(
            contract.get("output_schema"), dict
        ):
            raise McpContractError(f"MCP contract schemas are missing: {tool}")
        Draft202012Validator.check_schema(contract["input_schema"])
        Draft202012Validator.check_schema(contract["output_schema"])
        return contract
