"""Program-owned workspace state and model recovery projection."""

from __future__ import annotations

import json
from threading import RLock
from typing import Any

from report_agent.domain.identifiers import RunIdentity
from report_agent.runtime.workspace import TaskWorkspace

REQUIRED_EVIDENCE_TOOLS = frozenset(
    {
        "extract_project_profile",
        "query_track_labels",
        "query_comparable_valuation",
        "match_listed_peers",
        "match_investors",
    }
)


class WorkspaceContextStore:
    RUN_STATE = "/workspace/state/run-state.json"
    DATA_INDEX = "/workspace/evidence/index.json"
    REPORT_STATE = "/workspace/report/report-content.json"
    ARTIFACT_INDEX = "/workspace/artifacts/index.json"
    RESULT_INDEX = "/workspace/state/result-index.json"
    WORKING_MEMORY = "/workspace/memory/working.md"

    def __init__(self, workspace: TaskWorkspace) -> None:
        self.workspace = workspace
        self._lock = RLock()

    def initialize(self, identity: RunIdentity, objective: str) -> None:
        """Create or *continue* the run state for this workspace.

        同一沙箱的第二次 run（用户回答 ``ask_user``、追加材料）不能把
        ``objective`` 覆盖成"不记得了"这类回答，也不能清空已有的
        ``completed_tools`` 与证据索引。按 ``RUN_STATE`` 是否存在决定
        全新初始化还是增量续写。
        """
        with self._lock:
            previous: dict[str, Any] | None
            try:
                previous = self._read_json(self.RUN_STATE)
            except Exception:  # noqa: BLE001 - missing/unreadable means fresh
                previous = None

            if isinstance(previous, dict) and previous.get("identifiers"):
                runs = list(previous.get("runs") or [])
                if identity.run_id not in runs:
                    runs.append(identity.run_id)
                merged = dict(previous)
                merged["identifiers"] = {
                    "task_id": identity.task_id,
                    "session_id": identity.session_id,
                    "run_id": identity.run_id,
                    "workspace_id": identity.workspace_id,
                }
                merged["runs"] = runs
                merged["last_message"] = objective
                # 首次 run 的 objective 才代表任务目标；后续回答只进 last_message。
                merged.setdefault("objective", objective)
                self._write_json(self.RUN_STATE, merged)
                self._refresh_working_memory()
                return

            self._write_json(
                self.RUN_STATE,
                {
                    "schema_version": "1.0",
                    "objective": objective,
                    "phase": "ingested",
                    "identifiers": {
                        "task_id": identity.task_id,
                        "session_id": identity.session_id,
                        "run_id": identity.run_id,
                        "workspace_id": identity.workspace_id,
                    },
                    "runs": [identity.run_id],
                    "completed_tools": [],
                    "failed_tools": [],
                    "loaded_skill_references": [],
                    "next_action": "parse_materials",
                },
            )
            self._write_json(self.DATA_INDEX, {"schema_version": "1.0", "evidence": {}})
            self._write_json(self.REPORT_STATE, {"schema_version": "1.0", "reports": {}})
            self._write_json(self.ARTIFACT_INDEX, {"schema_version": "1.0", "artifacts": {}})
            self._write_json(self.RESULT_INDEX, {"schema_version": "1.0", "results": {}})
            self._refresh_working_memory()

    def record_material(self, material_id: str, source_name: str) -> None:
        self._advance(
            "materials_ready",
            "extract_project_profile",
            completed_tool="parse_materials",
            extra={"material_id": material_id, "source_name": source_name},
        )

    def record_evidence(self, record: Any, *, json_roots: tuple[str, ...]) -> None:
        with self._lock:
            index = self._read_json(self.DATA_INDEX)
            index["evidence"][record.evidence_id] = {
                "tool": record.tool,
                "status": record.status,
                "summary": record.summary,
                "path": record.path,
                "sha256": record.sha256,
                "size_bytes": record.size,
                "json_roots": list(json_roots),
            }
            self._write_json(self.DATA_INDEX, index)
            run = self._read_json(self.RUN_STATE)
            completed = list(run["completed_tools"])
            if record.tool not in completed:
                completed.append(record.tool)
            run["completed_tools"] = completed
            collected_tools = {item["tool"] for item in index["evidence"].values()}
            if REQUIRED_EVIDENCE_TOOLS.issubset(collected_tools):
                run["phase"] = "data_ready"
                run["next_action"] = "create_report_content"
            else:
                run["phase"] = "collecting_data"
                run["next_action"] = "continue_data_collection"
            self._write_json(self.RUN_STATE, run)
            self._refresh_working_memory()

    def record_report(self, action: str, report: Any) -> None:
        with self._lock:
            state = self._read_json(self.REPORT_STATE)
            state["reports"][report.report_id] = {
                "status": report.status.value,
                "section_ids": [section.section_id for section in report.sections],
                "section_count": len(report.sections),
                "missing_item_count": len(report.missing_items),
                "path": f"/workspace/report/{report.report_id}.json",
                "validation_status": "passed" if action == "validate_report_content" else "pending",
            }
            self._write_json(self.REPORT_STATE, state)
            phase = "report_ready" if report.status.value == "ready" else "writing"
            next_action = (
                "create_word_document"
                if phase == "report_ready"
                else "upsert_next_section_or_validate"
            )
            self._advance(phase, next_action, completed_tool=action, refresh=False)
            self._refresh_working_memory()

    def record_artifact(
        self,
        artifact_id: str,
        *,
        kind: str,
        path: str,
        status: str,
        sha256: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            index = self._read_json(self.ARTIFACT_INDEX)
            index["artifacts"][artifact_id] = {
                "kind": kind,
                "path": path,
                "status": status,
                "sha256": sha256,
                "details": details or {},
            }
            self._write_json(self.ARTIFACT_INDEX, index)
            phase_next = {
                "created": ("word_created", "validate_and_publish_word"),
                "published": ("completed", "return_final_answer"),
            }
            phase, next_action = phase_next.get(status, ("drafting", "inspect_failure"))
            self._advance(phase, next_action, completed_tool=f"artifact_{status}", refresh=False)
            self._refresh_working_memory()

    def record_result(
        self, result_id: str, *, path: str, sha256: str, size_chars: int, tool: str
    ) -> None:
        with self._lock:
            index = self._read_json(self.RESULT_INDEX)
            index["results"][result_id] = {
                "tool": tool,
                "path": path,
                "sha256": sha256,
                "size_chars": size_chars,
            }
            self._write_json(self.RESULT_INDEX, index)
            self._refresh_working_memory()

    def mark_reference_loaded(self, name: str) -> None:
        with self._lock:
            run = self._read_json(self.RUN_STATE)
            loaded = list(run["loaded_skill_references"])
            if name not in loaded:
                loaded.append(name)
            run["loaded_skill_references"] = loaded
            self._write_json(self.RUN_STATE, run)
            self._refresh_working_memory()

    def working_memory(self) -> str:
        try:
            return self.workspace.read_text(self.WORKING_MEMORY)
        except FileNotFoundError:
            return "# Current objective\nNot initialized"

    def phase(self) -> str:
        return str(self._read_json(self.RUN_STATE).get("phase", "ingested"))

    def result_record(self, result_id: str) -> dict[str, Any]:
        if not result_id or any(marker in result_id for marker in ("/", "\\", "..")):
            raise ValueError("invalid result_id")
        results = self._read_json(self.RESULT_INDEX).get("results", {})
        if result_id not in results:
            raise KeyError(f"unknown result_id: {result_id}")
        return dict(results[result_id])

    def _advance(
        self,
        phase: str,
        next_action: str,
        *,
        completed_tool: str | None = None,
        extra: dict[str, Any] | None = None,
        refresh: bool = True,
    ) -> None:
        with self._lock:
            run = self._read_json(self.RUN_STATE)
            run["phase"] = phase
            run["next_action"] = next_action
            if completed_tool:
                completed = list(run["completed_tools"])
                if completed_tool not in completed:
                    completed.append(completed_tool)
                run["completed_tools"] = completed
            if extra:
                run.update(extra)
            self._write_json(self.RUN_STATE, run)
            if refresh:
                self._refresh_working_memory()

    def _refresh_working_memory(self) -> None:
        run = self._read_json(self.RUN_STATE)
        data = self._read_json(self.DATA_INDEX)
        reports = self._read_json(self.REPORT_STATE)
        artifacts = self._read_json(self.ARTIFACT_INDEX)
        lines = [
            "# Current objective",
            str(run.get("objective", "")),
            "",
            "# Current phase",
            str(run.get("phase", "ingested")),
            "",
            "# Stable identifiers",
        ]
        lines.extend(f"- {key}: {value}" for key, value in run.get("identifiers", {}).items())
        lines.extend(["", "# Data availability"])
        for evidence_id, item in data.get("evidence", {}).items():
            lines.append(f"- {item['tool']}: {item['status']} ({evidence_id}) - {item['summary']}")
        if not data.get("evidence"):
            lines.append("- none")
        # 上传的材料在 input/ 里，但还没解析成 evidence 时上面会显示 none，
        # 容易让模型误判"没有材料"。这里单独列出输入文件。
        lines.extend(["", "# Input files"])
        try:
            input_dir = self.workspace.resolve("/workspace/input")
            input_names = (
                sorted(p.name for p in input_dir.iterdir() if p.is_file())
                if input_dir.is_dir()
                else []
            )
        except Exception:  # noqa: BLE001 - memory refresh must not raise
            input_names = []
        if input_names:
            lines.extend(f"- {name}" for name in input_names)
        else:
            lines.append("- none")
        lines.extend(["", "# Reports"])
        for report_id, item in reports.get("reports", {}).items():
            lines.append(
                f"- {report_id}: {item['status']}; sections={item['section_count']}; "
                f"validation={item['validation_status']}"
            )
        if not reports.get("reports"):
            lines.append("- none")
        lines.extend(["", "# Artifacts"])
        for artifact_id, item in artifacts.get("artifacts", {}).items():
            lines.append(f"- {artifact_id}: {item['kind']} {item['status']} {item['path']}")
        if not artifacts.get("artifacts"):
            lines.append("- none")
        lines.extend(
            [
                "",
                "# Loaded skill references",
                *[f"- {name}" for name in run.get("loaded_skill_references", [])],
                "",
                "# Next action",
                str(run.get("next_action", "")),
                "",
            ]
        )
        self.workspace.write_text(self.WORKING_MEMORY, "\n".join(lines))

    def _read_json(self, path: str) -> dict[str, Any] | None:
        """Read a JSON state file; return ``None`` when it does not exist yet."""
        try:
            if path.startswith("/workspace/evidence/"):
                relative = path.removeprefix("/workspace/evidence/")
                target = self.workspace.resolve(f"/workspace/evidence/{relative}")
            else:
                target = self.workspace.resolve(path)
        except Exception:  # noqa: BLE001 - policy error means "not ours"
            return None
        if not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt state falls back to fresh
            return None
        return payload if isinstance(payload, dict) else None

    def _write_json(self, path: str, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        if path.startswith("/workspace/evidence/"):
            self.workspace.import_artifact(
                "evidence", path.removeprefix("/workspace/evidence/"), content.encode("utf-8")
            )
        else:
            self.workspace.write_text(path, content)
