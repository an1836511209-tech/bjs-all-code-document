"""The evaluation framework must stay honest about what it measures.

Two responsibilities:

* every case file in ``scripts/eval/cases`` must be well formed, so a broken
  case fails in CI instead of silently passing;
* the analyzer must report the numbers the assertions are written against.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
EVAL_DIR = REPO_ROOT / "scripts" / "eval"
CASE_DIR = EVAL_DIR / "cases"

ALLOWED_ASSERTIONS = {
    "max_model_calls",
    "max_tool_calls",
    "max_wall_seconds",
    "max_edit_file_calls",
    "max_batch_edit_calls",
    "max_write_todos_calls",
    "max_context_peak",
    "min_model_calls",
    "min_edit_file_calls",
    "min_batch_edit_calls",
    "required_tools",
    "forbidden_tools",
}


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, EVAL_DIR / f"{module_name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analyze_log = _load("analyze_log")


def _case_files() -> list[Path]:
    assert CASE_DIR.is_dir(), "scripts/eval/cases must exist"
    return sorted(CASE_DIR.glob("*.json"))


def test_cases_exist():
    assert _case_files(), "at least one evaluation case must be committed"


@pytest.mark.parametrize("path", _case_files(), ids=lambda p: p.name)
def test_case_is_well_formed(path: Path):
    case = json.loads(path.read_text(encoding="utf-8"))
    assert case.get("id"), "case needs an id"
    assert case.get("description"), "case needs a description"
    assert case.get("skill"), "case needs a skill"
    assert isinstance(case.get("materials", []), list)
    assertions = case.get("assertions") or {}
    assert assertions, "case needs assertions"
    unknown = set(assertions) - ALLOWED_ASSERTIONS
    assert not unknown, f"unknown assertion keys: {sorted(unknown)}"
    for key in ("required_tools", "forbidden_tools"):
        if key in assertions:
            assert isinstance(assertions[key], list)


@pytest.mark.parametrize("path", _case_files(), ids=lambda p: p.name)
def test_case_materials_exist(path: Path):
    case = json.loads(path.read_text(encoding="utf-8"))
    for item in case.get("materials") or []:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        assert candidate.is_file(), f"material missing: {candidate}"


def _trace(tmp_path: Path) -> Path:
    rows = [
        {"kind": "session_start", "sequence": 1, "started_at": "2026-11-03T11:47:11+00:00"},
        {
            "kind": "model_call",
            "sequence": 2,
            "started_at": "2026-11-03T11:47:12+00:00",
            "elapsed_seconds": 8.0,
            "status": "completed",
            "input": {"messages_count": 1},
            "output": {"messages": [{"type": "ai", "content": "", "tool_calls": [{"name": "write_todos"}]}]},
        },
        {
            "kind": "tool_call",
            "sequence": 3,
            "started_at": "2026-11-03T11:47:20+00:00",
            "elapsed_seconds": 0.1,
            "status": "completed",
            "input": {"tool": "write_todos"},
            "output": {},
        },
    ]
    for index in range(4):
        rows.append(
            {
                "kind": "tool_call",
                "sequence": 10 + index,
                "started_at": f"2026-11-03T11:5{index}:00+00:00",
                "elapsed_seconds": 0.2,
                "status": "completed",
                "input": {"tool": "edit_file"},
                "output": {},
            }
        )
    rows.append(
        {
            "kind": "tool_call",
            "sequence": 30,
            "started_at": "2026-11-03T11:59:00+00:00",
            "elapsed_seconds": 1.0,
            "status": "completed",
            "input": {"tool": "batch_edit"},
            "output": {},
        }
    )
    path = tmp_path / "agent.ndjson"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def test_analyzer_counts_the_signals_assertions_rely_on(tmp_path):
    metrics = analyze_log.analyze_ndjson(_trace(tmp_path))
    assert metrics["model_calls"] == 1
    assert metrics["tool_calls"] == 6
    assert metrics["edit_file_calls"] == 4
    assert metrics["batch_edit_calls"] == 1
    assert metrics["write_todos_calls"] == 1
    assert metrics["tool_histogram"]["edit_file"] == 4


def test_assertions_evaluate_against_the_metrics(tmp_path):
    metrics = analyze_log.analyze_ndjson(_trace(tmp_path))

    passing = analyze_log.evaluate_assertions(
        metrics, {"max_edit_file_calls": 4, "min_batch_edit_calls": 1}
    )
    assert all(item["ok"] for item in passing)

    failing = analyze_log.evaluate_assertions(
        metrics, {"max_edit_file_calls": 3, "required_tools": ["render_one_pager"]}
    )
    assert not all(item["ok"] for item in failing)
    names = {item["name"] for item in failing}
    assert "max_edit_file_calls" in names
    assert "required_tool:render_one_pager" in names


def test_format_report_reports_a_verdict(tmp_path):
    metrics = analyze_log.analyze_ndjson(_trace(tmp_path))
    results = analyze_log.evaluate_assertions(metrics, {"max_edit_file_calls": 1})
    text = analyze_log.format_report(metrics, results)
    assert "RESULT: FAIL" in text
    assert "edit_file calls" in text
