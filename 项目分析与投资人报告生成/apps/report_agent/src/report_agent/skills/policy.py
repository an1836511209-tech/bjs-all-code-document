"""Runtime enforcement for a Skill's declared tool allowlist."""

from __future__ import annotations

from collections.abc import Iterable

from report_agent.skills.catalog import SkillDescriptor


class ToolPolicyError(PermissionError):
    """Raised when a skill requests an undeclared or unavailable tool."""


class ToolPolicy:
    def select(self, skill: SkillDescriptor, available_tools: Iterable[str]) -> tuple[str, ...]:
        available = frozenset(available_tools)
        missing = sorted(set(skill.allowed_tools) - available)
        if missing:
            raise ToolPolicyError(f"skill requires unavailable tools: {', '.join(missing)}")
        return skill.allowed_tools

    def authorize(self, skill: SkillDescriptor, tool_name: str) -> None:
        if tool_name not in skill.allowed_tools:
            raise ToolPolicyError(f"tool is not allowed by skill {skill.name}: {tool_name}")
