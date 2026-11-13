"""Data MCP command-line and server entrypoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="data_mcp 工具入口")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="启动 MCP Server；stdio 用于本地 Host，streamable-http 用于独立服务",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=8001, help="HTTP 监听端口")
    parser.add_argument(
        "--env",
        default=None,
        choices=["dev", "test", "uat", "prod"],
        help="兼容旧多环境配置；单环境部署通常无需传入",
    )
    parser.add_argument(
        "--company-name",
        default="",
        help="公司名（可比估值 / 项目画像 / 赛道标签 / 投资人匹配）",
    )
    parser.add_argument(
        "--tags",
        action="append",
        default=None,
        help="可重复传入 tags，例如 --tags 科技金融 --tags 普惠金融",
    )
    parser.add_argument(
        "--tags-str",
        default=None,
        help='直接传 tags 字符串，例如 --tags-str "[科技金融，普惠金融]"',
    )
    parser.add_argument(
        "--match-peers",
        action="store_true",
        help="调用 match_listed_peers（上市公司可比匹配）",
    )
    parser.add_argument("--summary", default="", help="match_listed_peers: 可选业务摘要")
    parser.add_argument("--top-n", type=int, default=0, help="match_listed_peers: 返回条数")
    parser.add_argument(
        "--extract-profile",
        action="store_true",
        help="调用 extract_project_profile（项目画像）",
    )
    parser.add_argument(
        "--file-info",
        default="",
        help="extract_project_profile: 材料文本（与 --material-url 至少其一）",
    )
    parser.add_argument(
        "--material-url",
        default="",
        help="extract_project_profile: MinIO 等 markdown 材料 URL（优先于 --file-info）",
    )
    parser.add_argument(
        "--user-chat-input",
        default="",
        help="extract_project_profile: 可选用户说明",
    )
    parser.add_argument(
        "--search-keywords",
        nargs="*",
        default=[],
        help="extract_project_profile: 可选额外智谱搜索关键词",
    )
    parser.add_argument(
        "--query-track-labels",
        action="store_true",
        help="调用 query_track_labels（查询企业赛道标签）",
    )
    parser.add_argument(
        "--match-investors",
        action="store_true",
        help="调用 match_investors（潜在投资人匹配）",
    )
    parser.add_argument(
        "--project-profile",
        default="",
        help="项目画像 JSON 或纯文本（query_track_labels / match_investors 必填）；PowerShell 建议 --project-profile-file",
    )
    parser.add_argument(
        "--project-profile-file",
        default="",
        help="从 UTF-8 文件读取项目画像（JSON 或纯文本）",
    )
    parser.add_argument(
        "--label-type",
        default="",
        help="match_investors: 可选 DMP 业务品类；空则跳过 DMP",
    )
    return parser.parse_args()


def _resolve_tags(args: argparse.Namespace) -> str | list[str]:
    if args.tags_str is not None:
        return args.tags_str
    if args.tags:
        return args.tags
    return ""


def _load_project_profile_text(args: argparse.Namespace) -> str:
    file_path = str(getattr(args, "project_profile_file", "") or "").strip()
    raw = str(getattr(args, "project_profile", "") or "")
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"--project-profile-file 不存在: {path}")
        return path.read_text(encoding="utf-8")
    return raw


def _parse_project_profile(raw: str, *, required: bool) -> str | dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        if required:
            raise ValueError("需要 --project-profile 或 --project-profile-file")
        return None
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"--project-profile JSON 无效: {exc}；"
                "PowerShell 请用 --project-profile-file，或传纯文本（不要以 {{ 开头）"
            ) from exc
        if isinstance(parsed, (dict, str)):
            return parsed
        raise ValueError("--project-profile JSON 须为对象或字符串")
    return text


def main() -> int:
    args = _parse_args()
    if args.transport:
        from data_mcp.mcp.server import run_server

        run_server(args.transport, host=args.host, port=args.port)
        return 0

    if args.extract_profile:
        from data_mcp.features.project_profile import extract_project_profile

        if not str(args.material_url).strip() and not str(args.file_info).strip():
            raise ValueError("extract_project_profile 需要 --material-url 或 --file-info")
        if not str(args.company_name).strip():
            raise ValueError("extract_project_profile 需要 --company-name")
        result = extract_project_profile(
            company_name=args.company_name,
            file_info=args.file_info,
            material_url=args.material_url,
            user_chat_input=args.user_chat_input,
            search_keywords=args.search_keywords or None,
            env=args.env,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.query_track_labels:
        from data_mcp.features.track_labels import query_track_labels

        if not str(args.company_name).strip():
            raise ValueError("query_track_labels 需要 --company-name")
        profile = _parse_project_profile(
            _load_project_profile_text(args),
            required=True,
        )
        assert profile is not None
        result = query_track_labels(
            company_name=args.company_name,
            project_profile=profile,
            env=args.env,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.match_peers:
        from data_mcp.features.listed_peer_match import match_listed_peers

        tags = _resolve_tags(args)
        if not tags:
            raise ValueError("match_listed_peers 需要 --tags 或 --tags-str")
        result = match_listed_peers(
            tags=tags,
            summary=args.summary,
            top_n=args.top_n if args.top_n > 0 else None,
            env=args.env,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.match_investors:
        from data_mcp.features.investor_match import match_investors

        if not str(args.company_name).strip():
            raise ValueError("match_investors 需要 --company-name")
        tags = _resolve_tags(args)
        if not tags:
            raise ValueError("match_investors 需要 --tags 或 --tags-str")
        profile = _parse_project_profile(_load_project_profile_text(args), required=True)
        assert profile is not None
        result = match_investors(
            company_name=args.company_name,
            track_tags=tags,
            project_profile=profile,
            label_type=args.label_type,
            env=args.env,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    from data_mcp.features.historical_valuation import query_comparable_valuation

    tags = _resolve_tags(args)
    if not (isinstance(tags, list) and tags) and not str(tags).strip():
        raise ValueError("query_comparable_valuation 需要 --tags 或 --tags-str")
    result = query_comparable_valuation(
        tags=tags,
        company_name=args.company_name,
        env=args.env,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
