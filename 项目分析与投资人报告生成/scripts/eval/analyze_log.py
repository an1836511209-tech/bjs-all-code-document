"""Turn an ``agent.ndjson`` trace into a metric report.

Pure standard library on purpose: this file must run on a laptop, in CI, or
inside a container without installing anything.

Usage::

    python scripts/eval/analyze_log.py path/to/agent.ndjson
    python scripts/eval/analyze_log.py path/to/agent.ndjson --json out.json

The report is the machine-readable half of the evaluation scheme: the numbers
that can be asserted deterministically (call counts, context growth, budget
exhaustion). Content quality is deliberately out of scope here — it needs a
human or an LLM judge, not a counter.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

#: Tool names whose call count is worth asserting on directly: they are the
#: ones that burn a model round trip each.
COUNTED_TOOLS = (
    "edit_file",
    "batch_edit",
    "write_file",
    "write_todos",
    "read_file",
    "read_evidence",
    "check_citation",
    "check_data_field",
    "check_report",
    "check_ai_tells",
    "render_one_pager",
    "create_word_from_md",
    "add_report_comments",
    "validate_and_publish_word",
)


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def read_decision_log(workspace: Path) -> dict[str, Any]:
    """Summarize the reasoning captures of a task workspace.

    ``state/decision-log.jsonl`` is written by ``ReasoningStore``: one line per
    captured chain of thought. The agent trace cannot show reasoning (the
    client drops the field), so this is the only place the capture is visible.
    """
    path = Path(workspace) / "state" / "decision-log.jsonl"
    entries: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    total = sum(int(item.get("chars") or 0) for item in entries)
    return {
        "reasoning_calls": len(entries),
        "reasoning_chars_total": total,
        "reasoning_chars_avg": round(total / len(entries), 1) if entries else 0.0,
        "reasoning_last_path": (entries[-1].get("path") if entries else ""),
    }


def analyze_ndjson(path: Path) -> dict[str, Any]:
    """Summarize one agent trace.

    The trace may hold several sessions (a run plus its follow-ups); each is
    reported separately and the totals are summed.
    """
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record["_line"] = number
            rows.append(record)

    sessions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for record in rows:
        kind = record.get("kind")
        if kind == "session_start":
            current = {"start": record.get("started_at"), "records": []}
            sessions.append(current)
            continue
        if current is None:
            current = {"start": record.get("started_at"), "records": []}
            sessions.append(current)
        current["records"].append(record)

    detail: list[dict[str, Any]] = []
    total_model = total_tool = 0
    total_model_seconds = total_tool_seconds = 0.0
    total_wall = 0.0
    tool_histogram: Counter[str] = Counter()
    tool_seconds: dict[str, float] = {}
    context_peak = 0
    longest_model: list[dict[str, Any]] = []

    for index, session in enumerate(sessions):
        records = session["records"]
        models = [r for r in records if r.get("kind") == "model_call"]
        tools = [r for r in records if r.get("kind") == "tool_call"]
        model_seconds = sum(float(r.get("elapsed_seconds") or 0.0) for r in models)
        tool_seconds_total = sum(float(r.get("elapsed_seconds") or 0.0) for r in tools)

        stamps = [_parse_time(r.get("started_at") or "") for r in records]
        stamps = [s for s in stamps if s is not None]
        wall = (max(stamps) - min(stamps)).total_seconds() if len(stamps) > 1 else 0.0

        session_tools: Counter[str] = Counter()
        for record in tools:
            name = str((record.get("input") or {}).get("tool") or "?")
            session_tools[name] += 1
            tool_histogram[name] += 1
            tool_seconds[name] = tool_seconds.get(name, 0.0) + float(
                record.get("elapsed_seconds") or 0.0
            )

        peak = 0
        for record in models:
            peak = max(peak, int((record.get("input") or {}).get("messages_count") or 0))
            elapsed = float(record.get("elapsed_seconds") or 0.0)
            if elapsed >= 30.0:
                names = []
                for message in (record.get("output") or {}).get("messages") or []:
                    for call in message.get("tool_calls") or []:
                        names.append(call.get("name"))
                longest_model.append(
                    {
                        "session": index + 1,
                        "sequence": record.get("sequence"),
                        "seconds": round(elapsed, 2),
                        "tools": names,
                    }
                )

        statuses = Counter(str(r.get("status")) for r in records if r.get("status"))
        detail.append(
            {
                "session": index + 1,
                "model_calls": len(models),
                "tool_calls": len(tools),
                "wall_seconds": round(wall, 1),
                "model_seconds": round(model_seconds, 1),
                "tool_seconds": round(tool_seconds_total, 1),
                "context_peak": peak,
                "tool_histogram": dict(session_tools.most_common()),
                "statuses": dict(statuses),
            }
        )
        total_model += len(models)
        total_tool += len(tools)
        total_model_seconds += model_seconds
        total_tool_seconds += tool_seconds_total
        total_wall += wall
        context_peak = max(context_peak, peak)

    longest_model.sort(key=lambda item: -float(item["seconds"]))

    metrics: dict[str, Any] = {
        "sessions": len(sessions),
        "model_calls": total_model,
        "tool_calls": total_tool,
        "wall_seconds": round(total_wall, 1),
        "model_seconds": round(total_model_seconds, 1),
        "tool_seconds": round(total_tool_seconds, 1),
        "tool_seconds_by_name": {
            name: round(value, 1) for name, value in sorted(tool_seconds.items(), key=lambda kv: -kv[1])
        },
        "context_peak": context_peak,
        "tool_histogram": dict(tool_histogram.most_common()),
        "session_detail": detail,
        "longest_model_calls": longest_model[:10],
    }
    for name in COUNTED_TOOLS:
        metrics[f"{name}_calls"] = tool_histogram.get(name, 0)
    metrics["edit_file_calls"] = tool_histogram.get("edit_file", 0)
    metrics["batch_edit_calls"] = tool_histogram.get("batch_edit", 0)
    metrics["write_todos_calls"] = tool_histogram.get("write_todos", 0)
    return metrics


def evaluate_assertions(metrics: dict[str, Any], assertions: dict[str, Any]) -> list[dict[str, Any]]:
    """Check a metric report against declarative assertions.

    Supported keys::

        max_model_calls / max_tool_calls / max_wall_seconds
        max_edit_file_calls / max_batch_edit_calls / max_write_todos_calls
        max_context_peak
        min_batch_edit_calls / min_edit_file_calls / min_model_calls
        required_tools: [...]        # must appear at least once
        forbidden_tools: [...]      # must never appear
    """
    results: list[dict[str, Any]] = []

    def number(name: str, metric: str, comparison, threshold):
        actual = metrics.get(metric)
        if not isinstance(actual, (int, float)):
            results.append(
                {
                    "name": name,
                    "metric": metric,
                    "ok": False,
                    "actual": actual,
                    "expected": f"{comparison} {threshold}",
                }
            )
            return
        ok = actual <= threshold if comparison == "<=" else actual >= threshold
        results.append(
            {
                "name": name,
                "metric": metric,
                "ok": ok,
                "actual": actual,
                "expected": f"{comparison} {threshold}",
            }
        )

    limits = (
        ("max_model_calls", "model_calls"),
        ("max_tool_calls", "tool_calls"),
        ("max_wall_seconds", "wall_seconds"),
        ("max_edit_file_calls", "edit_file_calls"),
        ("max_batch_edit_calls", "batch_edit_calls"),
        ("max_write_todos_calls", "write_todos_calls"),
        ("max_context_peak", "context_peak"),
    )
    for key, metric in limits:
        if key in assertions:
            number(key, metric, "<=", assertions[key])

    minimums = (
        ("min_model_calls", "model_calls"),
        ("min_batch_edit_calls", "batch_edit_calls"),
        ("min_edit_file_calls", "edit_file_calls"),
    )
    for key, metric in minimums:
        if key in assertions:
            number(key, metric, ">=", assertions[key])

    histogram = metrics.get("tool_histogram") or {}
    for name in assertions.get("required_tools") or []:
        actual = int(histogram.get(name, 0))
        results.append(
            {
                "name": f"required_tool:{name}",
                "ok": actual >= 1,
                "actual": actual,
                "expected": ">= 1",
            }
        )
    for name in assertions.get("forbidden_tools") or []:
        actual = int(histogram.get(name, 0))
        results.append(
            {
                "name": f"forbidden_tool:{name}",
                "ok": actual == 0,
                "actual": actual,
                "expected": "== 0",
            }
        )
    return results


def format_report(metrics: dict[str, Any], results: list[dict[str, Any]] | None = None) -> str:
    lines = [
        "=" * 62,
        "agent trace report",
        "=" * 62,
        f"sessions          : {metrics['sessions']}",
        f"model calls       : {metrics['model_calls']}",
        f"tool calls        : {metrics['tool_calls']}",
        f"wall seconds      : {metrics['wall_seconds']}",
        f"model seconds     : {metrics['model_seconds']}",
        f"tool seconds      : {metrics['tool_seconds']}",
        f"context peak      : {metrics['context_peak']} messages",
        f"edit_file calls   : {metrics['edit_file_calls']}",
        f"batch_edit calls  : {metrics['batch_edit_calls']}",
        f"write_todos calls : {metrics['write_todos_calls']}",
    ]
    if "reasoning_calls" in metrics:
        lines.append(
            f"reasoning captured: {metrics['reasoning_calls']} 次 "
            f"共 {metrics['reasoning_chars_total']:,} 字 "
            f"(均 {metrics['reasoning_chars_avg']} 字)"
        )
    lines += [
        "",
        "tool histogram:",
    ]
    for name, count in (metrics.get("tool_histogram") or {}).items():
        seconds = (metrics.get("tool_seconds_by_name") or {}).get(name, 0.0)
        lines.append(f"  {name:<32} {count:>4}  {seconds:>8.1f}s")
    if metrics.get("longest_model_calls"):
        lines.append("")
        lines.append("slowest model calls:")
        for item in metrics["longest_model_calls"][:5]:
            lines.append(
                f"  seq {item['sequence']:<6} {item['seconds']:>8.1f}s  {item['tools']}"
            )
    if results:
        lines.append("")
        lines.append("assertions:")
        for item in results:
            mark = "PASS" if item["ok"] else "FAIL"
            lines.append(
                f"  [{mark}] {item['name']:<32} actual={item['actual']} expected={item['expected']}"
            )
        failed = [item for item in results if not item["ok"]]
        lines.append("")
        lines.append(f"RESULT: {'PASS' if not failed else 'FAIL'} ({len(failed)} failed)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize an agent.ndjson trace.")
    parser.add_argument("log", type=Path, help="path to agent.ndjson")
    parser.add_argument("--json", type=Path, help="write the metric report as JSON")
    parser.add_argument(
        "--assert",
        dest="assert_file",
        type=Path,
        help="case file whose assertions should be checked against this trace",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="task workspace; adds the reasoning capture written by ReasoningStore",
    )
    args = parser.parse_args(argv)

    if not args.log.is_file():
        print(f"log not found: {args.log}", file=sys.stderr)
        return 2

    metrics = analyze_ndjson(args.log)
    if args.workspace:
        metrics.update(read_decision_log(args.workspace))
    results = None
    if args.assert_file and args.assert_file.is_file():
        case = json.loads(args.assert_file.read_text(encoding="utf-8"))
        results = evaluate_assertions(metrics, case.get("assertions") or {})

    print(format_report(metrics, results))
    if args.json:
        payload = {"metrics": metrics, "assertions": results}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if results is not None:
        return 0 if all(item["ok"] for item in results) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
