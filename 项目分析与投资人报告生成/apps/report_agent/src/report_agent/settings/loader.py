"""Single entrypoint for loading and fingerprinting Report Agent settings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from report_agent.settings.models import ReportAgentSettings

REPOSITORY_ROOT_TOKEN = "${REPO_ROOT}"


def load_settings(path: Path) -> ReportAgentSettings:
    config_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    if _contains_repository_root_token(raw):
        raw = _expand_repository_root(raw, _find_repository_root(config_path))
    return ReportAgentSettings.model_validate(raw)


def _contains_repository_root_token(value: object) -> bool:
    if isinstance(value, str):
        return REPOSITORY_ROOT_TOKEN in value
    if isinstance(value, dict):
        return any(_contains_repository_root_token(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_repository_root_token(item) for item in value)
    return False


def _find_repository_root(config_path: Path) -> Path:
    for candidate in config_path.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "apps" / "report_agent"
        ).is_dir():
            return candidate
    raise ValueError(
        f"cannot resolve {REPOSITORY_ROOT_TOKEN}: repository root not found for {config_path}"
    )


def _expand_repository_root(value: object, repository_root: Path) -> object:
    if isinstance(value, str):
        return value.replace(REPOSITORY_ROOT_TOKEN, repository_root.as_posix())
    if isinstance(value, dict):
        return {
            key: _expand_repository_root(item, repository_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_expand_repository_root(item, repository_root) for item in value]
    return value


def config_fingerprint(settings: ReportAgentSettings) -> str:
    canonical = json.dumps(
        settings.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
