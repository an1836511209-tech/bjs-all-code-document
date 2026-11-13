"""手动执行：观察项目画像 MCP 工具的完整调用过程。

每一步都打印耗时，卡在哪一步一眼能看出来：

    1. 读材料          本地文件
    2. 上传 MinIO      产出 presigned material_url
    3. 回读 MinIO      确认 URL 可下载
    4. 调 MCP 画像      观察 Data MCP / HiAgent 的响应

用法（在仓库根目录执行）::

    # 默认：用最近一次任务的材料，走 material_url
    python apps/report_agent/tests/unit/mcp_profile/manual_probe.py

    # 指定材料与公司名
    python apps/report_agent/tests/unit/mcp_profile/manual_probe.py \
        --material .runtime/report-agent-workspaces/task_xxx/working/materials/material_xxx.json \
        --company "惠然科技有限公司"

    # 只测内联文本（不走 MinIO）
    python apps/report_agent/tests/unit/mcp_profile/manual_probe.py --mode text

    # 把超时降到 30 秒，快速判断是否卡在 HiAgent
    python apps/report_agent/tests/unit/mcp_profile/manual_probe.py --timeout 30

退出码：0 = 拿到 success/partial，1 = empty，2 = 调用失败
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
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


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"找不到 {path}")
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


def read_material(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = str(payload.get("source_name") or path.stem)
    blocks = payload.get("blocks") or []
    text = "\n\n".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if str(block.get("text") or "").strip()
    )
    return source, text


def step(index: int, title: str) -> None:
    print(f"\n[{index}] {title}")


def ok(message: str) -> None:
    print(f"    OK   {message}")


def fail(message: str) -> None:
    print(f"    FAIL {message}")


async def run(args: argparse.Namespace) -> int:
    env = load_env(RUNTIME_ENV)
    settings = load_settings(AGENT_CONFIG)

    material_path = Path(args.material) if args.material else find_latest_material()
    if material_path is None or not material_path.is_file():
        fail("没有可用的材料 JSON，请用 --material 指定")
        return 2

    step(1, "读材料")
    source, text = read_material(material_path)
    print(f"    file : {material_path}")
    print(f"    name : {source}")
    print(f"    chars: {len(text)}")
    if not text:
        fail("材料没有正文")
        return 2
    ok("材料就绪")

    snippet = text[: args.limit] if args.limit else text

    step(2, "上传 MinIO")
    started = time.monotonic()
    try:
        minio = MinioArtifactService(settings.persistence.minio, env)
        url, expires = minio.upload_markdown(
            f"exports/manual/{material_path.stem}.md", snippet
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"MinIO 上传失败 {type(exc).__name__}: {exc}")
        return 2
    ok(f"{time.monotonic() - started:.2f}s  expires={expires:%Y-%m-%d %H:%M:%S}")
    print(f"    url  : {url[:110]}...")

    step(3, "回读 MinIO（验证 presigned URL 可下载）")
    started = time.monotonic()
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        fail(f"下载失败 {type(exc).__name__}: {exc}")
        return 2
    ok(f"{time.monotonic() - started:.2f}s  status={resp.status_code}  bytes={len(resp.content)}")
    if resp.text != snippet:
        fail("下载内容与上传内容不一致")
        return 2

    step(4, f"调 MCP extract_project_profile（timeout={args.timeout}s, mode={args.mode}）")
    transport = StreamableHttpMcpTransport(
        settings.data_mcp.url or "", timeout_seconds=args.timeout
    )

    if args.mode == "url":
        arguments = {
            "company_name": args.company,
            "material_url": url,
            "search_keywords": args.keywords,
        }
    elif args.mode == "text":
        arguments = {
            "company_name": args.company,
            "file_info": snippet,
            "search_keywords": args.keywords,
        }
    else:  # both
        arguments = {
            "company_name": args.company,
            "material_url": url,
            "file_info": snippet,
            "search_keywords": args.keywords,
        }
    print(f"    state: material_url={'yes' if 'material_url' in arguments else 'no'}, "
          f"file_info={'yes' if 'file_info' in arguments else 'no'}")

    started = time.monotonic()
    try:
        payload = await transport.call_tool("extract_project_profile", arguments)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - started
        fail(f"{elapsed:.1f}s 后超时/断开：{type(exc).__name__}: {str(exc)[:160]}")
        print()
        print("    判断：MinIO 与 URL 都正常（步骤 2/3 通过），")
        print("          超时发生在 Data MCP 内部 —— 大概率是 HiAgent 的")
        print("          project_profile agent 不返回模型响应。")
        return 2

    elapsed = time.monotonic() - started
    status = payload.get("status")
    print(f"    耗时   : {elapsed:.1f}s")
    print(f"    status : {status}")
    print(f"    summary: {str(payload.get('summary'))[:160]}")
    warnings = payload.get("warnings") or []
    if warnings:
        print(f"    warn   : {json.dumps(warnings, ensure_ascii=False)[:240]}")
    profile = (payload.get("data") or {}).get("profile")
    if isinstance(profile, dict) and profile:
        print(f"    profile: {len(profile)} 个字段 -> {list(profile.keys())[:12]}")
    else:
        print("    profile: 空")

    print()
    if status in {"success", "partial"}:
        ok("画像生成成功")
        return 0
    if status == "empty":
        print("    判断：链路通（MinIO/企查查/智谱），但画像为空。")
        print("          检查 warnings 里的上游降级原因。")
        return 1
    fail("调用失败，看上面的 summary")
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description="手动执行项目画像 MCP 调用并观察每一步",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--material", help="材料 JSON 路径（默认取最近一次任务）")
    parser.add_argument("--company", default="惠然科技有限公司", help="企业全称")
    parser.add_argument(
        "--mode", choices=["url", "text", "both"], default="url",
        help="material_url / file_info / 两者都给（默认 url）",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只取材料前 N 个字符（0 = 全部）",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="MCP 调用超时秒数")
    parser.add_argument(
        "--keywords", nargs="*", default=["电子束", "扫描电镜"], help="智谱搜索补充关键词"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
