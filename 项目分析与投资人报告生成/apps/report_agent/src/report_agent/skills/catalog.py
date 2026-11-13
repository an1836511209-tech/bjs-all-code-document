"""Skill discovery and explicit full-body activation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    name: str
    description: str
    path: Path
    allowed_tools: tuple[str, ...]
    version: str


class SkillCatalog:
    """Expose metadata first and load full instructions only on activation."""

    def __init__(self, roots: list[Path]) -> None:
        self._roots = [Path(root).resolve() for root in roots]

    def discover(self) -> tuple[SkillDescriptor, ...]:
        found: dict[str, SkillDescriptor] = {}
        for root in self._roots:
            if not root.exists():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                descriptor, _ = self._parse(skill_file)
                if descriptor.name in found:
                    raise ValueError(f"duplicate skill name: {descriptor.name}")
                found[descriptor.name] = descriptor
        return tuple(found[name] for name in sorted(found))

    def activate(self, name: str) -> tuple[SkillDescriptor, str]:
        for descriptor in self.discover():
            if descriptor.name == name:
                parsed, body = self._parse(descriptor.path)
                return parsed, body
        raise KeyError(f"skill not found: {name}")

    @staticmethod
    def stage_references(descriptor: SkillDescriptor, workspace: Any) -> tuple[str, ...]:
        reference_root = descriptor.path.parent / "references"
        if not reference_root.is_dir():
            return ()
        names: list[str] = []
        for source in sorted(reference_root.glob("*.md")):
            workspace.import_artifact("references", source.name, source.read_bytes())
            names.append(source.stem)
        return tuple(names)

    @staticmethod
    def read_staged_reference(workspace: Any, name: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            raise ValueError("invalid skill reference name")
        return workspace.read_text(f"/workspace/references/{name}.md")

    @staticmethod
    def _parse(path: Path) -> tuple[SkillDescriptor, str]:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            raise ValueError(f"skill frontmatter missing: {path}")
        try:
            frontmatter, body = raw[4:].split("\n---\n", maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"skill frontmatter is not closed: {path}") from exc
        metadata: dict[str, Any] = yaml.safe_load(frontmatter) or {}
        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        if not name or not description:
            raise ValueError(f"skill name and description are required: {path}")
        tools = metadata.get("allowed-tools", [])
        if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
            raise ValueError(f"allowed-tools must be a string list: {path}")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return (
            SkillDescriptor(
                name=name,
                description=description,
                path=path.resolve(),
                allowed_tools=tuple(tools),
                version=digest,
            ),
            body.strip(),
        )
