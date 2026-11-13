from __future__ import annotations

from pathlib import Path

from report_agent.settings import load_settings


def test_local_settings_expand_repository_root() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    config_path = repository_root / "deploy/environments/test/report-agent.local.yaml"

    settings = load_settings(config_path)

    assert settings.service.workspace_root == (
        repository_root / ".runtime/report-agent-workspaces"
    ).as_posix()
    assert settings.service.skill_roots == (
        (repository_root / "apps/report_agent/skills").as_posix(),
    )
    assert settings.data_mcp.contracts_dir == (
        repository_root / "contracts/mcp"
    ).as_posix()
