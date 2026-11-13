"""单独调试 ``extract_project_profile`` 与 ``match_investors``。

这两个工具都依赖 HiAgent，超时时很难从 pytest 的输出里看出卡在哪。
这个脚本只做两件事，把请求参数、耗时、完整响应都打出来，方便与
HiAgent 平台后台的执行记录对齐时间线。

配合 Data MCP 前台启动使用效果最好（能看到每一步 HTTP 请求）::

    # 终端 A：前台起 Data MCP，日志直接打在屏幕上
    python -m data_mcp.entrypoints --transport streamable-http --host 127.0.0.1 --port 8001

    # 终端 B：只调画像
    python apps/report_agent/tests/unit/mcp_profile/debug_two_tools.py --tool profile --timeout 120

    # 只调投资人匹配
    python apps/report_agent/tests/unit/mcp_profile/debug_two_tools.py --tool investors --timeout 120

    # 两个都调（先画像，再投资人）
    python apps/report_agent/tests/unit/mcp_profile/debug_two_tools.py --tool both --timeout 60

    # 不走 MinIO，直接用文本
    python apps/report_agent/tests/unit/mcp_profile/debug_two_tools.py --tool profile --mode text

时间线对齐技巧：脚本会在发请求前打印本地时间，Data MCP 日志和 HiAgent
平台后台都能按这个时间点找到对应请求。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "apps" / "report_agent" / "src"))

import requests  # noqa: E402

from report_agent.infrastructure.artifacts.minio import MinioArtifactService  # noqa: E402
from report_agent.infrastructure.mcp.streamable_http import (  # noqa: E402
    StreamableHttpMcpTransport,
)
from report_agent.settings import load_settings  # noqa: E402

RUNTIME_ENV = REPO_ROOT / "deploy/environments/test/runtime.env"
AGENT_CONFIG = REPO_ROOT / "deploy/environments/test/report-agent.local.yaml"
DEFAULT_COMPANY = "毕节市新能源汽车投资运营有限公司"


def stamp(label: str) -> None:
    print(f"\n[{datetime.now():%H:%M:%S}] {label}")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        env[key.strip()] = value
    return env


def find_latest_material() -> Path | None:
    root = REPO_ROOT / ".runtime/report-agent-workspaces"
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob("*/working/materials/material_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def material_text(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = payload.get("blocks") or []
    return "\n\n".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if str(block.get("text") or "").strip()
    )


async def dump_call(
    transport: StreamableHttpMcpTransport,
    tool: str,
    arguments: dict,
    timeout: float,
) -> dict:
    print(f"  工具   : {tool}")
    print(f"  参数   : {json.dumps(arguments, ensure_ascii=False, default=str)[:600]}")
    stamp(f"发起请求（超时 {timeout:.0f}s）")
    started = time.monotonic()
    try:
        payload = await transport.call_tool(tool, arguments)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        stamp(f"失败，耗时 {elapsed:.1f}s")
        print(f"  异常   : {type(exc).__name__}: {str(exc)[:300]}")
        print("\n  建议查看：")
        print("    - Data MCP 终端里的 'project_profile POST transient error' / 'timeout'")
        print("    - HiAgent 平台对应 agent 的执行记录（同一条时间线）")
        return {}

    elapsed = time.monotonic() - started
    stamp(f"返回，耗时 {elapsed:.1f}s")
    print(f"  status : {payload.get('status')}")
    print(f"  summary: {str(payload.get('summary'))[:200]}")
    warnings = payload.get("warnings") or []
    if warnings:
        print(f"  warnings: {json.dumps(warnings, ensure_ascii=False)[:400]}")
    sources = payload.get("sources") or []
    if sources:
        print(f"  sources : {json.dumps(sources, ensure_ascii=False)[:300]}")

    data = payload.get("data") or {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                print(f"  data.{key}: list[{len(value)}]")
                if value and isinstance(value[0], dict):
                    print(f"    首条: {json.dumps(value[0], ensure_ascii=False)[:400]}")
            elif isinstance(value, dict):
                print(f"  data.{key}: keys={list(value.keys())[:12]}")
            elif isinstance(value, str) and value:
                print(f"  data.{key}: {value[:250]}")
    return payload


async def main() -> int:
    parser = argparse.ArgumentParser(description="单独调试画像与投资人匹配")
    parser.add_argument("--tool", choices=["profile", "investors", "both"], default="profile")
    parser.add_argument("--mode", choices=["url", "text"], default="url",
                        help="profile 用 material_url 还是 file_info")
    parser.add_argument("--material", help="材料 JSON 路径（默认取最近一次任务）")
    parser.add_argument("--company", default=DEFAULT_COMPANY)
    parser.add_argument("--timeout", type=float, default=120.0, help="单次调用超时秒数")
    parser.add_argument("--limit", type=int, default=0, help="只取材料前 N 字符")
    parser.add_argument("--keywords", nargs="*", default=["新能源汽车", "充电桩", "公交"])
    args = parser.parse_args()

    env = load_env(RUNTIME_ENV)
    settings = load_settings(AGENT_CONFIG)
    transport = StreamableHttpMcpTransport(
        settings.data_mcp.url or "", timeout_seconds=args.timeout
    )

    print("=" * 74)
    print(f"company : {args.company}")
    print(f"mcp url : {settings.data_mcp.url}")
    print(f"timeout : {args.timeout}s")
    print("=" * 74)

    # 材料 + material_url 只有 profile 需要
    url: str | None = None
    text: str | None = None
    if args.tool in {"profile", "both"}:
        material_path = Path(args.material) if args.material else find_latest_material()
        if material_path and material_path.is_file():
            text = material_text(material_path)
            if args.limit:
                text = text[: args.limit]
            print(f"\n材料   : {material_path.name}")
            print(f"字符   : {len(text)}")
            if args.mode == "url":
                stamp("上传 MinIO")
                minio = MinioArtifactService(settings.persistence.minio, env)
                url, expires = minio.upload_markdown(
                    f"exports/debug/{material_path.stem}.md", text
                )
                print(f"  过期 : {expires:%H:%M:%S}")
                print(f"  URL  : {url[:110]}")
                resp = requests.get(url, timeout=20)
                print(f"  回读 : {resp.status_code} {len(resp.content)} bytes")
        else:
            print("\n(没有材料，profile 将使用 file_info 空字符串测试 schema)")

    if args.tool in {"profile", "both"}:
        print("\n" + "-" * 74)
        print("extract_project_profile")
        print("-" * 74)
        if args.mode == "url" and url:
            arguments = {
                "company_name": args.company,
                "material_url": url,
                "search_keywords": args.keywords,
            }
        else:
            arguments = {
                "company_name": args.company,
                "file_info": text or "",
                "search_keywords": args.keywords,
            }
        await dump_call(transport, "extract_project_profile", arguments, args.timeout)

    if args.tool in {"investors", "both"}:
        print("\n" + "-" * 74)
        print("match_investors")
        print("-" * 74)
        arguments = {
            "company_name": args.company,
            "track_tags": args.keywords,
            "project_profile": {
                "company_name": args.company,
                "main_business": "新能源汽车投资运营与充电基础设施",
            },
        }
        await dump_call(transport, "match_investors", arguments, args.timeout)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
