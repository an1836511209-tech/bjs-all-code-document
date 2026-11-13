"""Run an evaluation case against a live agent API and judge the trace.

Usage::

    python scripts/eval/run_eval.py --list
    python scripts/eval/run_eval.py --case investment-report-cites
    python scripts/eval/run_eval.py --all
    python scripts/eval/run_eval.py --case investment-report-cites --log old-agent.ndjson

The last form is offline: it judges a trace you already have and never
touches the network. That is the fast loop while developing.

Case files live in ``scripts/eval/cases/*.json``::

    {
      "id": "investment-report-cites",
      "description": "补 cite 必须批量改，不得逐段 edit_file",
      "skill": "investment-report",
      "message": "帮我根据当前材料，生成投资人匹配报告",
      "materials": ["materials/01-北京中科新微特公司介绍-20250221.pdf"],
      "timeout_seconds": 2400,
      "assertions": {
        "max_model_calls": 45,
        "max_edit_file_calls": 3,
        "min_batch_edit_calls": 1,
        "max_write_todos_calls": 3,
        "max_context_peak": 70
      }
    }
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_log import analyze_ndjson, evaluate_assertions, format_report  # noqa: E402

CASE_DIR = Path(__file__).resolve().parent / "cases"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_OUT = REPO_ROOT / "artifacts" / "eval"


# --------------------------------------------------------------------------- #
# cases
# --------------------------------------------------------------------------- #

def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    if not CASE_DIR.is_dir():
        return cases
    for path in sorted(CASE_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case["_path"] = str(path)
        cases.append(case)
    return cases


def find_case(case_id: str) -> dict[str, Any] | None:
    for case in load_cases():
        if case.get("id") == case_id:
            return case
    return None


# --------------------------------------------------------------------------- #
# http helpers
# --------------------------------------------------------------------------- #

def _multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----dsheval{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        chunks.append(f"{value}\r\n".encode())
    for name, path in files:
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request(url: str, *, data: bytes | None = None, content_type: str | None = None,
             method: str = "GET", timeout: int = 60) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, method=method)
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _get_json(url: str, timeout: int = 60) -> tuple[int, Any]:
    status, body = _request(url, timeout=timeout)
    try:
        return status, json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, body.decode("utf-8", errors="replace")


def submit_run(api: str, case: dict[str, Any], materials: list[Path]) -> dict[str, Any]:
    fields = {
        "message": case.get("message", ""),
        "selected_skill": case.get("skill", ""),
    }
    body, content_type = _multipart(fields, [("files_", path) for path in materials])
    status, raw = _request(
        f"{api.rstrip('/')}/api/dev/runs", data=body, content_type=content_type, method="POST",
        timeout=120,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {"raw": raw.decode("utf-8", errors="replace")}
    if status >= 400:
        raise RuntimeError(f"submit failed with HTTP {status}: {payload}")
    return payload


def wait_for_run(api: str, run_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: Any = {}
    while time.monotonic() < deadline:
        status, last = _get_json(f"{api.rstrip('/')}/api/runs/{run_id}", timeout=30)
        if isinstance(last, dict):
            state = str(last.get("status") or "")
            if state in {"completed", "failed", "cancelled", "error"}:
                return last
        time.sleep(5.0)
    return {"status": "timeout", "detail": last}


def fetch_trace(api: str, task_id: str) -> list[dict[str, Any]]:
    status, payload = _get_json(f"{api.rstrip('/')}/api/dev/runs/{task_id}/logs", timeout=120)
    if status != 200:
        return []
    if isinstance(payload, dict):
        entries = payload.get("entries") or []
        return [entry for entry in entries if isinstance(entry, dict)]
    return []


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #

def analyze_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze trace entries that came over HTTP instead of from a file."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "agent.ndjson"
        path.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )
        return analyze_ndjson(path)


def evaluate_case(case: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    results = evaluate_assertions(metrics, case.get("assertions") or {})
    return {
        "case": case.get("id"),
        "description": case.get("description", ""),
        "ok": all(item["ok"] for item in results),
        "metrics": metrics,
        "assertions": results,
    }


def resolve_materials(case: dict[str, Any]) -> list[Path]:
    resolved: list[Path] = []
    for item in case.get("materials") or []:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if not candidate.is_file():
            raise FileNotFoundError(f"material not found: {candidate}")
        resolved.append(candidate)
    return resolved


def run_case(case: dict[str, Any], api: str, out_dir: Path) -> dict[str, Any]:
    materials = resolve_materials(case)
    accepted = submit_run(api, case, materials)
    run_id = accepted.get("run_id", "")
    task_id = accepted.get("task_id", "")
    print(f"[{case.get('id')}] submitted run={run_id} task={task_id}")
    timeout = int(case.get("timeout_seconds", 2400))
    final = wait_for_run(api, run_id, timeout)
    print(f"[{case.get('id')}] run status = {final.get('status')}")
    entries = fetch_trace(api, task_id)
    metrics = analyze_entries(entries)
    report = evaluate_case(case, metrics)
    report["run"] = {"run_id": run_id, "task_id": task_id, "final": final}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{case.get('id')}.eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{case.get('id')}.ndjson").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run agent evaluation cases.")
    parser.add_argument("--case", action="append", default=[], help="case id (repeatable)")
    parser.add_argument("--all", action="store_true", help="run every case")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    parser.add_argument("--api", default=DEFAULT_API, help="agent API base URL")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="artifact directory")
    parser.add_argument(
        "--log", type=Path, help="judge this trace offline instead of running the agent"
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.list or not (args.case or args.all or args.log):
        print("available cases:")
        for case in cases:
            print(f"  {case.get('id'):<34} {case.get('description', '')}")
        if not args.log:
            return 0

    selected: list[dict[str, Any]] = []
    if args.all:
        selected = cases
    else:
        for case_id in args.case:
            case = find_case(case_id)
            if case is None:
                print(f"unknown case: {case_id}", file=sys.stderr)
                return 2
            selected.append(case)

    reports: list[dict[str, Any]] = []
    if args.log:
        metrics = analyze_ndjson(args.log)
        for case in selected or [{"id": "offline", "assertions": {}}]:
            report = evaluate_case(case, metrics)
            print(format_report(metrics, report["assertions"]))
            reports.append(report)
    else:
        for case in selected:
            try:
                reports.append(run_case(case, args.api, args.out))
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"[{case.get('id')}] ERROR {exc}", file=sys.stderr)
                reports.append({"case": case.get("id"), "ok": False, "error": str(exc)})

    print()
    print("=" * 62)
    failed = 0
    for report in reports:
        status = "PASS" if report.get("ok") else "FAIL"
        if not report.get("ok"):
            failed += 1
        print(f"[{status}] {report.get('case')}")
        for item in report.get("assertions") or []:
            if not item.get("ok"):
                print(
                    f"        {item['name']}: actual={item['actual']} expected={item['expected']}"
                )
    print("=" * 62)
    print(f"{len(reports) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
