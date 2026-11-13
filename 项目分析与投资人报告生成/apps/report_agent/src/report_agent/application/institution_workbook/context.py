"""Opt-in, bounded provenance recorder and immutable export context resolution."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from queue import Full, Queue
from typing import Any
from urllib.parse import urlsplit

from report_agent.application.one_pager_execution import read_json, write_json
from report_agent.domain.evidence import EvidenceRecord
from report_agent.runtime.workspace import TaskWorkspace

ROOT = "/workspace/state/institution-workbook"
VERSION = "institution-workbook-v1"
logger = logging.getLogger(__name__)


class ContextUnavailable(ValueError):
    pass


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def canonical_profile(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    return value


def profile_company(profile: object, fallback: str) -> str:
    if isinstance(profile, dict):
        for key in ("上市公司名称", "公司名称", "企业名称", "company_name"):
            name = profile.get(key)
            if isinstance(name, str) and name.strip() not in {"", "未知", "未披露", "不详", "-"}:
                return name.strip()
    return fallback


def compatible_identity(original: object, supplied: object) -> bool:
    if not isinstance(original, dict) or not isinstance(supplied, dict):
        return True
    for key in ("证券代码", "统一社会信用代码", "credit_code"):
        left, right = original.get(key), supplied.get(key)
        if left and right and str(left).strip() != str(right).strip():
            return False
    return True


def clean_tags(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    tags: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str):
            continue
        text = " ".join(unicodedata.normalize("NFKC", value).split())
        if text and len(text) <= 160 and not re.search(r"[,，;；|\n\r、]", text):
            tags.setdefault(text.casefold(), text)
    return list(tags.values())


def report_tags(values: object) -> list[str]:
    """Accept the same comma/string-list input as match_investors, without guessing tags."""
    if isinstance(values, str):
        text = values.strip().strip("[]")
        values = [text]
        for separator in ("，", ",", ";", "；", "|"):
            if separator in text:
                values = text.split(separator)
                break
    if not isinstance(values, list) or any(not clean_tags([value]) for value in values):
        return []
    return clean_tags(values)


def request_options(workspace: TaskWorkspace, run_id: str, enabled: bool) -> None:
    """Only metadata already computed during upload; no file hashing on the main path."""
    if not enabled:
        return
    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    inputs = {
        p: r["sha256"]
        for p, r in manifest.get("files", {}).items()
        if p.startswith("/workspace/input/")
    }
    write_json(
        workspace,
        f"{ROOT}/requests/{run_id}.json",
        {"enabled": True, "run_id": run_id, "inputs": inputs, "version": VERSION},
    )


def _payload(workspace: TaskWorkspace, evidence_id: str, sha: str, tool: str) -> dict:
    if not re.fullmatch(r"evidence_[a-f0-9]{32}", evidence_id):
        raise ContextUnavailable("证据标识无效")
    path = workspace.resolve(f"/workspace/evidence/{evidence_id}.json")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ContextUnavailable("证据超出模块大小限制")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != sha:
        raise ContextUnavailable("证据内容已变化")
    value = json.loads(content)
    index = (
        read_json(workspace, "/workspace/evidence/index.json")
        .get("evidence", {})
        .get(evidence_id, {})
    )
    statuses = (
        {"success", "partial", "empty", "failed"}
        if tool == "match_investors"
        else {"success", "partial"}
    )
    if (
        value.get("tool") != tool
        or value.get("status") not in statuses
        or index.get("tool") != tool
        or index.get("sha256") != sha
        or index.get("status") not in statuses
    ):
        raise ContextUnavailable("证据状态或来源无效")
    return value


def _materials(workspace: TaskWorkspace, inputs: dict) -> list[dict]:
    materials = []
    for path in sorted((workspace.root / "working/materials").glob("material_*.json")):
        if path.stat().st_size > 16 * 1024 * 1024:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        source = f"/workspace/input/{data.get('source_name')}"
        if inputs.get(source) == data.get("source_sha256"):
            materials.append(
                {
                    "material_id": data["material_id"],
                    "source_name": data["source_name"],
                    "source_sha256": data["source_sha256"],
                    "parsed_sha256": fingerprint(data),
                }
            )
    # Multiple parser runs of an identical source are interchangeable only when pinned by ID.
    return materials


class ContextRecorder:
    """One daemon thread; queue overflow/IO failure never propagates to MCP tools."""

    def __init__(self):
        self.queue: Queue = Queue(maxsize=32)
        self.thread = threading.Thread(target=self._drain, name="institution-context", daemon=True)
        self.thread.start()

    def observe(
        self,
        workspace: TaskWorkspace,
        run_id: str,
        tool: str,
        arguments: dict,
        record: EvidenceRecord,
    ) -> None:
        if tool not in {"extract_project_profile", "query_track_labels", "match_investors"}:
            return
        try:
            self.queue.put_nowait((workspace, run_id, tool, arguments, record))
        except Full:
            logger.warning("institution context queue full; optional export may be skipped")

    def _drain(self):
        while True:
            item = self.queue.get()
            try:
                self._record(*item)
            except Exception as exc:
                logger.warning("institution context unavailable: %s", type(exc).__name__)
            finally:
                self.queue.task_done()

    @staticmethod
    def _record(workspace, run_id, tool, arguments, record):
        options = read_json(workspace, f"{ROOT}/requests/{run_id}.json")
        if not options.get("enabled"):
            return
        payload = _payload(workspace, record.evidence_id, record.sha256, tool)
        company = str(arguments.get("company_name") or "").strip()
        if not company:
            return
        if tool == "extract_project_profile":
            profile = payload["data"].get("profile")
            materials = _materials(workspace, options["inputs"])
            relevant = []
            for material in materials:
                parsed = read_json(
                    workspace, f"/workspace/working/materials/{material['material_id']}.json"
                )
                markdown = "\n\n".join(
                    [
                        f"# {parsed['source_name']}",
                        *[
                            str(b.get("text") or "").strip()
                            for b in parsed.get("blocks", [])
                            if str(b.get("text") or "").strip()
                        ],
                    ]
                )
                url_path = urlsplit(str(arguments.get("material_url") or "")).path
                from_url = f"/{workspace.root.name}/{material['material_id']}.md" in url_path
                from_text = str(arguments.get("file_info") or "").strip() == markdown.strip()
                if from_url or from_text:
                    relevant.append(material)
            if not relevant or not profile:
                return
            value = {
                "company_name": profile_company(profile, company),
                "profile_request_company_name": company,
                "profile_evidence_id": record.evidence_id,
                "profile_sha256": record.sha256,
                "profile_fingerprint": fingerprint(profile),
                "inputs": options["inputs"],
                "materials": relevant,
                "origin_run_id": run_id,
                "observed_at_ns": time.time_ns(),
            }
            write_json(workspace, f"{ROOT}/profiles/{record.evidence_id}.json", value)
        else:
            matches = []
            supplied = canonical_profile(arguments.get("project_profile"))
            profile_fp = fingerprint(supplied)
            candidates = []
            for p in (workspace.root / "state/institution-workbook/profiles").glob(
                "evidence_*.json"
            ):
                profile = json.loads(p.read_text(encoding="utf-8"))
                original = _payload(
                    workspace,
                    profile["profile_evidence_id"],
                    profile["profile_sha256"],
                    "extract_project_profile",
                )["data"].get("profile")
                canonical_company = profile_company(original, profile["company_name"])
                same_request_name = (
                    tool == "match_investors"
                    and profile["origin_run_id"] == run_id
                    and profile.get("profile_request_company_name") == company
                    and profile_company(supplied, canonical_company) == canonical_company
                )
                if (
                    (canonical_company == company or same_request_name)
                    and profile["inputs"] == options["inputs"]
                    and compatible_identity(original, supplied)
                ):
                    bound = {**profile, "company_name": canonical_company}
                    if profile["profile_fingerprint"] == profile_fp:
                        matches.append(bound)
                    elif (
                        profile["origin_run_id"] == run_id
                        and profile_company(supplied, canonical_company) == canonical_company
                    ):
                        candidates.append(bound)
            binding = "exact_profile"
            if not matches and len({p["profile_fingerprint"] for p in candidates}) == 1:
                matches = candidates
                binding = "same_run_company"
            tags = (
                report_tags(arguments.get("track_tags"))
                if tool == "match_investors"
                else clean_tags(payload["data"].get("tags"))
            )
            if not matches or not tags:
                return
            # Same input/profile content, never a global/latest nonempty tag lookup.
            value = {
                **matches[0],
                "origin_run_id": run_id,
                "label_profile_binding": binding,
                "label_input_fingerprint": profile_fp,
                "version": VERSION,
                "observed_at_ns": time.time_ns(),
            }
            if tool == "match_investors":
                value.update(
                    report_tags=tags,
                    match_evidence_id=record.evidence_id,
                    match_sha256=record.sha256,
                )
            else:
                value.update(
                    track_label_evidence_id=record.evidence_id, track_label_sha256=record.sha256
                )
            value["context_fingerprint"] = fingerprint(value)
            write_json(workspace, f"{ROOT}/contexts/{record.evidence_id}.json", value)


_recorder: ContextRecorder | None = None
_recorder_lock = threading.Lock()


def recorder() -> ContextRecorder:
    global _recorder
    with _recorder_lock:
        if _recorder is None:
            _recorder = ContextRecorder()
        return _recorder


def resolve_context(
    workspace: TaskWorkspace, run_ids: list[str], *, verify_inputs=True, allow_refresh=False
) -> dict:
    profiles = []
    for path in (workspace.root / "state/institution-workbook/profiles").glob("evidence_*.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))
        if profile.get("origin_run_id") in run_ids:
            payload = _payload(
                workspace,
                profile["profile_evidence_id"],
                profile["profile_sha256"],
                "extract_project_profile",
            )
            profile["company_name"] = profile_company(
                payload["data"].get("profile"), profile["company_name"]
            )
            profiles.append(profile)
    profiles.sort(
        key=lambda p: (run_ids.index(p["origin_run_id"]), p.get("observed_at_ns", 0)),
        reverse=True,
    )
    newest_profiles = (
        [p for p in profiles if p["origin_run_id"] == profiles[0]["origin_run_id"]]
        if profiles
        else []
    )
    if len({(p["company_name"], p["profile_fingerprint"]) for p in newest_profiles}) > 1:
        raise ContextUnavailable("本轮存在不同主体或画像，请明确当前项目后重试附件。")
    contexts = []
    for path in (workspace.root / "state/institution-workbook/contexts").glob("evidence_*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("origin_run_id") in run_ids and value.get("version") == VERSION:
            contexts.append(value)
    if newest_profiles:
        current = newest_profiles[0]
        contexts = [
            c
            for c in contexts
            if (c["company_name"], c["profile_fingerprint"], c["inputs"])
            == (current["company_name"], current["profile_fingerprint"], current["inputs"])
        ]
    if not contexts and allow_refresh and newest_profiles:
        return _resolve_snapshot(
            workspace,
            {**newest_profiles[0], "version": VERSION},
            run_ids,
            verify_inputs=verify_inputs,
        )
    if not contexts:
        raise ContextUnavailable(
            "缺少与当前材料关联的标签。请开启附件后生成报告，或提供有效画像更新标签。"
        )
    contexts.sort(key=lambda c: run_ids.index(c["origin_run_id"]), reverse=True)
    latest = [c for c in contexts if c["origin_run_id"] == contexts[0]["origin_run_id"]]
    # Multiple differing profiles/companies in one run require explicit disambiguation.
    if len({(c["company_name"], c["profile_fingerprint"]) for c in latest}) != 1:
        raise ContextUnavailable("本轮存在不同主体或画像，请明确当前项目后重试附件。")
    # Among already verified same-company/same-input calls, use the final observed call.
    # This is not an evidence-index ordering heuristic.
    latest.sort(
        key=lambda c: (bool(c.get("report_tags")), c.get("observed_at_ns", 0)), reverse=True
    )
    return _resolve_snapshot(workspace, latest[0], run_ids, verify_inputs=verify_inputs)


def _resolve_snapshot(workspace, value, run_ids, *, verify_inputs):
    """Pin user clarifications too; later chat edits cannot change an enqueued selection."""
    original_fp = value.get("context_fingerprint")
    if (
        original_fp
        and fingerprint({k: v for k, v in value.items() if k != "context_fingerprint"})
        != original_fp
    ):
        raise ContextUnavailable("上下文引用校验失败")
    notes: list[dict[str, Any]] = []
    size = 0
    for index, turn in enumerate(
        read_json(workspace, "/workspace/state/conversation.json").get("turns", [])
    ):
        if turn.get("role") != "user" or turn.get("run_id") not in run_ids:
            continue
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        size += len(text)
        if size > 16000 or len(notes) >= 100:
            raise ContextUnavailable("用户补充超出附件上下文上限，请明确本次标签后重试附件。")
        notes.append(
            {"ref": f"{turn['run_id']}:user:{index}", "text": text, "sha256": fingerprint(text)}
        )
    snapshot = {k: v for k, v in value.items() if k != "context_fingerprint"}
    snapshot["user_notes"] = notes
    snapshot["context_fingerprint"] = fingerprint(snapshot)
    return load_context(workspace, snapshot, verify_inputs=verify_inputs)


def load_context(workspace: TaskWorkspace, value: dict, *, verify_inputs=False) -> dict:
    expected_fp = value["context_fingerprint"]
    if fingerprint({k: v for k, v in value.items() if k != "context_fingerprint"}) != expected_fp:
        raise ContextUnavailable("上下文引用校验失败")
    if value.get("match_evidence_id"):
        _payload(workspace, value["match_evidence_id"], value["match_sha256"], "match_investors")
    labels: dict[str, Any] = (
        _payload(
            workspace,
            value["track_label_evidence_id"],
            value["track_label_sha256"],
            "query_track_labels",
        )
        if value.get("track_label_evidence_id")
        else {"data": {}, "sources": [], "status": "empty"}
    )
    profile = _payload(
        workspace, value["profile_evidence_id"], value["profile_sha256"], "extract_project_profile"
    )
    if fingerprint(profile["data"].get("profile")) != value["profile_fingerprint"]:
        raise ContextUnavailable("画像已变化")
    if verify_inputs:
        manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
        current = {
            p: r["sha256"]
            for p, r in manifest.get("files", {}).items()
            if p.startswith("/workspace/input/")
        }
        if current != value["inputs"]:
            raise ContextUnavailable("材料版本已变化，请更新标签后重试附件。")
        for name, sha in current.items():
            path = workspace.resolve(name)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != sha:
                raise ContextUnavailable("源材料校验失败")
    snippets = []
    for material in value["materials"]:
        parsed = read_json(
            workspace, f"/workspace/working/materials/{material['material_id']}.json"
        )
        if fingerprint(parsed) != material["parsed_sha256"]:
            raise ContextUnavailable("解析材料版本已变化")
        for block in parsed.get("blocks", []):
            text = str(block.get("text") or "").strip()
            if text:
                snippets.append(
                    {
                        "ref": f"{material['material_id']}:{block['block_id']}",
                        "text": text,
                        "locator": block.get("locator", {}),
                    }
                )
    return {
        **value,
        "candidate_tags": value.get("report_tags") or clean_tags(labels["data"].get("tags")),
        "low_trust": value.get("label_profile_binding") == "same_run_company"
        or labels["status"] == "partial"
        or not any(
            s.get("name") == "lms" and s.get("status") == "used" for s in labels.get("sources", [])
        ),
        "profile": profile["data"]["profile"],
        "snippets": snippets,
    }
