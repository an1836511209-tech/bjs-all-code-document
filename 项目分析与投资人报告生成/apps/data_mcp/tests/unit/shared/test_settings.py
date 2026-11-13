from __future__ import annotations

from pathlib import Path

import yaml

from data_mcp.shared import settings


def test_single_environment_deployment_config(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "data-mcp.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "current_env": "test",
                "historical_valuation": {
                    "path": "/chat",
                    "host": "https://example.test",
                    "token": "token",
                    "agent_id": "agent",
                    "timeout_seconds": 30,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    loaded = settings.load_historical_valuation_config()

    assert loaded["env"] == "test"
    assert loaded["host"] == "https://example.test"
    assert loaded["path"] == "/chat"


def test_legacy_multi_environment_config_remains_supported(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "data-mcp.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "current_env": "uat",
                "historical_valuation": {
                    "path": "/chat",
                    "dev": {
                        "host": "https://dev.example.test",
                        "token": "dev-token",
                        "agent_id": "dev-agent",
                    },
                    "uat": {
                        "host": "https://uat.example.test",
                        "token": "uat-token",
                        "agent_id": "uat-agent",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    loaded = settings.load_historical_valuation_config()

    assert loaded["env"] == "uat"
    assert loaded["host"] == "https://uat.example.test"


def test_track_labels_reads_rotating_token_from_env(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "data-mcp.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "current_env": "test",
                "track_labels": {
                    "api": {
                        "base_url": "http://10.254.95.199:9080",
                        "path": "/v1/API_LMS_LMS_BROPEN_InquirySingleEnterpriseTrackLabelsSrv",
                        "secret_key": {"env": "TRACK_LABELS_SECRET_KEY"},
                        "x_gw_token": {"env": "API_PLATFORM_TOKEN"},
                        "source": "2",
                    },
                    "retry": {"max_attempts": 2, "interval_seconds": 60},
                    "fallback": {"taxonomy_path": "taxonomy.xlsx"},
                    "hiagent": {
                        "path": "/chat",
                        "host": "https://example.test",
                        "token": "token",
                        "agent_id": "agent",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)
    monkeypatch.setenv("API_PLATFORM_TOKEN", "raw-token")
    monkeypatch.setenv("TRACK_LABELS_SECRET_KEY", "biz-secret")

    loaded = settings.load_track_labels_config()

    assert loaded["api"]["x_gw_token"] == "raw-token"
    assert loaded["api"]["secret_key"] == "biz-secret"
    assert loaded["api"]["source"] == "2"
    assert loaded["api"]["path"].endswith("InquirySingleEnterpriseTrackLabelsSrv")


def test_investor_match_keeps_dmp_page_settings(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "data-mcp.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "current_env": "prod",
                "investor_match": {
                    "dmp": {
                        "base_url": "http://10.3.1.71:30011",
                        "path": "/v3/match",
                        "institution_offset": 0,
                        "institution_limit": 30,
                        "individual_offset": 0,
                        "individual_limit": 500,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    dmp = settings.load_investor_match_config()["dmp"]

    assert dmp["institution_offset"] == 0
    assert dmp["institution_limit"] == 30
    assert dmp["individual_offset"] == 0
    assert dmp["individual_limit"] == 500
