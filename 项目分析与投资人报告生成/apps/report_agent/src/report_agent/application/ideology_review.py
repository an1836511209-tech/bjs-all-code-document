"""Ideology review: rule loader and matcher.

Loads the YAML dictionary (R1-R80 of 表述勘误表 2025.12.docx) and matches a
plain-text body against every rule. The matcher performs only string or
regex matching; it never judges or rewrites the text. The caller (the agent)
decides what to do with each match.

Public API:
    IdeologyReviewer(Path) -> reviewer
    reviewer.review(text, *, path) -> tuple[IdeologyMatch, ...]

Per SPEC ADR-0003:
- Tool signature follows project style: `(text: str) -> str`.
- Strict error policy: file missing / schema invalid / regex compile fail
  all raise and propagate to the Agent (no silent fallback).
- Context window: 15 characters on each side of the hit, clamped to text bounds.
- Hit location fields: `offset` (0-based) and `length` (hit char count).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

CONTEXT_HALF_WIDTH: Final[int] = 15


def _default_rule_path() -> Path:
    """Resolve the shipped dictionary relative to this file.

    Source layout: apps/report_agent/src/report_agent/application/ideology_review.py
        -> apps/report_agent/resources/reference_data/report_agent/ideology/ideology-2025.12.yaml
    Installed layout (container): .venv/.../site-packages/report_agent/application/ideology_review.py
        -> /app/apps/report_agent/resources/reference_data/report_agent/ideology/ideology-2025.12.yaml
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = (
            parent
            / "apps"
            / "report_agent"
            / "resources"
            / "reference_data"
            / "report_agent"
            / "ideology"
            / "ideology-2025.12.yaml"
        )
        if candidate.is_file():
            return candidate
    # Fallback: relative to repo root, matching the original relative layout.
    return Path("apps/report_agent/resources/reference_data/report_agent/ideology/ideology-2025.12.yaml")


DEFAULT_RULE_PATH: Final[Path] = _default_rule_path()

_REGEX_META: Final[frozenset[str]] = frozenset(
    r"\.*+?()[]{}|^$"
)


@dataclass(frozen=True, slots=True)
class IdeologyRule:
    """A single loaded rule from the dictionary."""

    rule_id: str
    category_id: str
    category_label: str
    pattern: str
    suggestion: str
    severity: str
    notes: str
    is_regex: bool


@dataclass(frozen=True, slots=True)
class IdeologyMatch:
    """A single occurrence produced by ``IdeologyReviewer.review``."""

    rule_id: str
    category_label: str
    severity: str
    original: str
    suggestion: str
    context: str
    path: str
    offset: int
    length: int


class IdeologyReviewer:
    """Load a YAML dictionary once, then run ``review`` against any text."""

    def __init__(self, dictionary_path: Path) -> None:
        if not dictionary_path.exists():
            raise FileNotFoundError(
                f"ideology dictionary not found: {dictionary_path}"
            )
        if not dictionary_path.is_file():
            raise ValueError(
                f"ideology dictionary path is not a file: {dictionary_path}"
            )
        try:
            raw = yaml.safe_load(dictionary_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(
                f"ideology dictionary YAML parse failed ({dictionary_path}): {exc}"
            ) from exc
        self._rules: tuple[IdeologyRule, ...] = _validate_and_build(raw, dictionary_path)

    @property
    def rules(self) -> tuple[IdeologyRule, ...]:
        return self._rules

    def review(
        self,
        text: str,
        *,
        path: str = "/workspace/report/report.md",
    ) -> tuple[IdeologyMatch, ...]:
        """Scan ``text`` against every rule; return every occurrence.

        Per SPEC M-3, strings without regex meta chars use
        ``re.escape(pattern) + re.finditer``; otherwise regex is used directly.
        """
        if not text:
            return ()
        matches: list[IdeologyMatch] = []
        for rule in self._rules:
            flags = re.UNICODE
            pattern = (
                rule.pattern
                if rule.is_regex
                else re.escape(rule.pattern)
            )
            for hit in re.finditer(pattern, text, flags):
                start = hit.start()
                end = hit.end()
                matches.append(
                    IdeologyMatch(
                        rule_id=rule.rule_id,
                        category_label=rule.category_label,
                        severity=rule.severity,
                        original=text[start:end],
                        suggestion=rule.suggestion,
                        context=_clip(text, start, end),
                        path=path,
                        offset=start,
                        length=end - start,
                    )
                )
        return tuple(matches)


def _clip(text: str, start: int, end: int) -> str:
    """Return ``text[max(0, start-N):min(len(text), end+N)]``."""
    left = max(0, start - CONTEXT_HALF_WIDTH)
    right = min(len(text), end + CONTEXT_HALF_WIDTH)
    return text[left:right]


def _is_regex(pattern: str) -> bool:
    return any(ch in pattern for ch in _REGEX_META)


def _validate_and_build(
    raw: object,
    dictionary_path: Path,
) -> tuple[IdeologyRule, ...]:
    """Validate the loaded YAML structure and return immutable rules.

    Raises ``ValueError`` with a path-style error message that points to the
    offending field so the Agent can show it to the user.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"ideology dictionary ({dictionary_path}): top-level must be a mapping"
        )
    version = raw.get("version")
    if not isinstance(version, str):
        raise ValueError(
            f"ideology dictionary ({dictionary_path}): 'version' must be a string"
        )
    categories = raw.get("categories")
    if not isinstance(categories, list):
        raise ValueError(
            f"ideology dictionary ({dictionary_path}): 'categories' must be a list"
        )

    rules: list[IdeologyRule] = []
    seen_rule_ids: set[str] = set()
    for cat_idx, category in enumerate(categories):
        cat_path = f"categories[{cat_idx}]"
        if not isinstance(category, dict):
            raise ValueError(
                f"ideology dictionary ({dictionary_path}): {cat_path} must be a mapping"
            )
        cat_id = category.get("id")
        cat_label = category.get("label")
        items = category.get("items")
        if not isinstance(cat_id, str) or not cat_id:
            raise ValueError(
                f"ideology dictionary ({dictionary_path}): {cat_path}.id must be a non-empty string"
            )
        if not isinstance(cat_label, str) or not cat_label:
            raise ValueError(
                f"ideology dictionary ({dictionary_path}): {cat_path}.label must be a non-empty string"
            )
        if not isinstance(items, list):
            raise ValueError(
                f"ideology dictionary ({dictionary_path}): {cat_path}.items must be a list"
            )

        for item_idx, item in enumerate(items):
            item_path = f"{cat_path}.items[{item_idx}]"
            if not isinstance(item, dict):
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path} must be a mapping"
                )
            rule_id = item.get("rule_id")
            pattern = item.get("pattern")
            suggestion = item.get("suggestion")
            severity = item.get("severity")
            notes = item.get("notes", "")
            if not isinstance(rule_id, str) or not rule_id:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}.rule_id must be a non-empty string"
                )
            if rule_id in seen_rule_ids:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): duplicate rule_id '{rule_id}'"
                )
            seen_rule_ids.add(rule_id)
            if not isinstance(pattern, str) or not pattern:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}({rule_id}).pattern must be a non-empty string"
                )
            if not isinstance(suggestion, str) or not suggestion:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}({rule_id}).suggestion must be a non-empty string"
                )
            if severity not in {"block", "warn"}:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}({rule_id}).severity must be 'block' or 'warn'"
                )
            if not isinstance(notes, str):
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}({rule_id}).notes must be a string"
                )

            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"ideology dictionary ({dictionary_path}): {item_path}({rule_id}).pattern failed to compile: {exc}"
                ) from exc

            rules.append(
                IdeologyRule(
                    rule_id=rule_id,
                    category_id=cat_id,
                    category_label=cat_label,
                    pattern=pattern,
                    suggestion=suggestion,
                    severity=severity,
                    notes=notes,
                    is_regex=_is_regex(pattern),
                )
            )
    return tuple(rules)