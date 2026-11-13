"""本地 mock 冒烟：打印三个 MCP 工具的调用结果（不依赖外网）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from tests.support import DATA_FIXTURES, RESPONSE_FIXTURES

PEER_FIXTURES = DATA_FIXTURES / "listed_peers"


def _print(title: str, obj) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def run_comparable_valuation() -> dict:
    payload = json.loads(
        (RESPONSE_FIXTURES / "historical_valuation.json").read_text(encoding="utf-8")
    )
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload, ensure_ascii=False)

    with patch("data_mcp.features.historical_valuation.service.http_request", return_value=mock_response):
        from data_mcp.mcp.server import query_comparable_valuation

        return query_comparable_valuation(
            tags=["科技金融", "普惠金融"],
            company_name="星河智贷科技",
        )


def run_project_profile() -> dict:
    payload = json.loads(
        (RESPONSE_FIXTURES / "project_profile.json").read_text(encoding="utf-8")
    )
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = payload
    mock_response.text = json.dumps(payload, ensure_ascii=False)

    with patch("data_mcp.features.project_profile.service.http_request", return_value=mock_response):
        with patch(
            "data_mcp.features.project_profile.service.resolve_qichacha_info_for_portrait",
            return_value=('{"Name":"星河智贷科技有限公司"}', []),
        ):
            from data_mcp.mcp.server import extract_project_profile

            return extract_project_profile(
                file_info="这是解析后的材料文本",
                company_name="星河智贷科技有限公司",
                user_chat_input="补充：聚焦科技金融",
            )


def run_match_peers() -> dict:
    from data_mcp.shared.settings import load_listed_peer_match_config

    def _cfg():
        cfg = load_listed_peer_match_config()
        cfg = dict(cfg)
        cfg["data_dir"] = str(PEER_FIXTURES)
        cfg["embedding"] = dict(cfg["embedding"])
        cfg["embedding"]["backend"] = "hash"
        cfg["enable_rerank"] = False
        return cfg

    with patch(
        "data_mcp.features.listed_peer_match.service.load_listed_peer_match_config",
        side_effect=_cfg,
    ):
        from data_mcp.mcp.server import match_listed_peers

        return match_listed_peers(
            tags=["动力电池", "储能"],
            summary="新能源中游电芯制造与储能系统",
            top_n=3,
        )


def main() -> int:
    comparable = run_comparable_valuation()
    _print(
        "MCP query_comparable_valuation (mock HTTP)",
        {
            "state": comparable.get("state"),
            "choice_preview": (comparable.get("choice") or [{}])[0].get("content", "")[:240],
        },
    )

    portrait = run_project_profile()
    _print("MCP extract_project_profile (mock HTTP)", portrait)

    peers = run_match_peers()
    _print(
        "MCP match_listed_peers (mock Excel + hash embedding)",
        {
            "query": peers.get("data", {}).get("query"),
            "weights_used": peers.get("data", {}).get("weights_used"),
            "meta": peers.get("data", {}).get("meta"),
            "top_peers": [
                {
                    "证券代码": p["证券代码"],
                    "证券名称": p["证券名称"],
                    "final_score": p["final_score"],
                    "confidence": p["confidence"],
                    "assessment_status": p.get("assessment_status"),
                }
                for p in peers.get("data", {}).get("peers", [])
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
