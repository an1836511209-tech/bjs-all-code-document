"""Optional export exercises real provenance, XLSX, API and failure boundaries."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from openpyxl import load_workbook

from report_agent.api.app import create_app
from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.institution_workbook.context import (
    ROOT,
    ContextRecorder,
    ContextUnavailable,
    load_context,
    report_tags,
    request_options,
    resolve_context,
)
from report_agent.application.institution_workbook.files import (
    ExportFailure,
    call_export,
    validate_file,
)
from report_agent.application.institution_workbook.selection import select_tags
from report_agent.application.institution_workbook.service import InstitutionWorkbookService
from report_agent.application.interactions import read_interaction
from report_agent.application.one_pager_execution import read_json
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.infrastructure.artifacts.minio import XLSX_CONTENT_TYPE, MinioArtifactService
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings import load_settings
from report_agent.settings.models import InstitutionWorkbookSettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def settings():
    config = load_settings(REPOSITORY_ROOT / "deploy/environments/test/report-agent.local.yaml")
    return config.model_copy(
        update={"institution_workbook": InstitutionWorkbookSettings(enabled=True)}
    )


def workbook_payload(tags, *, empty=False):
    from data_mcp.features.investor_match.workbook import (
        build_institution_workbook,
        slim_institution_rows,
    )

    items = (
        []
        if empty
        else [
            {
                "investor_name": "测试机构",
                "match_label_weight_sum": 90,
                "match_label_num": len(tags),
                "label_name_list": ",".join(tags),
            }
        ]
    )
    content = build_institution_workbook(slim_institution_rows(items, tags))
    return {
        "schema_version": "1.0",
        "tool": "export_matched_institutions",
        "status": "empty" if empty else "success",
        "summary": "导出完成",
        "sources": [],
        "warnings": [],
        "data": dict(
            filename="投资机构匹配.xlsx",
            content_base64=base64.b64encode(content).decode(),
            sha256=hashlib.sha256(content).hexdigest(),
            row_count=len(items),
            query_tags=tags,
            unverified_row_count=0,
            count_mismatch_row_count=0,
        ),
    }


def build_context(
    root,
    identity=None,
    tags=None,
    *,
    low_trust=False,
    profile=None,
    company_name="测试食品有限公司",
    tag_company_name=None,
    tag_profile=None,
    matched_tags=None,
    match_status="success",
):
    identity = identity or RunIdentity.create()
    workspace = TaskWorkspace(root / identity.task_id)
    workspace.initialize()
    source = workspace.import_artifact("input", "项目.docx", b"original-source")
    material_id = "material_" + uuid4().hex
    text = "公司主营速冻食品制造，产品为冷冻食品，客户为餐饮企业。"
    parsed = {
        "material_id": material_id,
        "source_name": "项目.docx",
        "source_sha256": source.sha256,
        "blocks": [{"block_id": "p1", "text": text, "locator": {"page": 1}}],
    }
    from report_agent.application.one_pager_execution import write_json

    write_json(workspace, f"/workspace/working/materials/{material_id}.json", parsed)
    request_options(workspace, identity.run_id, True)
    context_store = WorkspaceContextStore(workspace)
    context_store.initialize(identity, "生成报告")
    evidence = WorkspaceEvidenceStore(workspace)
    profile = profile or {"主营业务": "速冻食品制造"}

    def record(tool, data, args, status="success"):
        payload = {
            "schema_version": "1.0",
            "tool": tool,
            "status": status,
            "summary": "完成",
            "data": data,
            "sources": [{"name": "local_recall" if low_trust else "lms", "status": "used"}],
            "warnings": [],
        }
        entry = evidence.put(tool, payload)
        context_store.record_evidence(entry, json_roots=("/data",))
        ContextRecorder._record(workspace, identity.run_id, tool, args, entry)
        return entry

    record(
        "extract_project_profile",
        {"profile": profile},
        {
            "company_name": company_name,
            "material_url": f"https://objects.test/exports/{identity.task_id}/{material_id}.md",
        },
    )
    tag_record = record(
        "query_track_labels",
        {"tags": tags or ["速冻食品制造"]},
        {
            "company_name": tag_company_name or company_name,
            "project_profile": profile if tag_profile is None else tag_profile,
        },
    )
    if matched_tags is not None:
        record(
            "match_investors",
            {},
            {
                "company_name": tag_company_name or company_name,
                "project_profile": profile if tag_profile is None else tag_profile,
                "track_tags": matched_tags,
            },
            match_status,
        )
    return identity, workspace, resolve_context(workspace, [identity.run_id]), tag_record


@pytest.mark.parametrize("as_text", [False, True])
def test_investment_report_accepts_corrected_company_and_profile_summary(tmp_path, as_text):
    import json

    profile = {
        "上市公司名称": "测试食品股份有限公司",
        "证券代码": "833932",
        "主营业务": "速冻食品制造",
        "资源依赖路径": "客户渠道",
    }
    supplied = (
        "公司主营速冻食品制造。"
        if as_text
        else json.dumps({k: v for k, v in profile.items() if k != "资源依赖路径"})
    )
    identity, workspace, context, _ = build_context(
        tmp_path,
        profile=profile,
        company_name="测试食品",
        tag_company_name="测试食品股份有限公司",
        tag_profile=supplied,
    )
    assert context["company_name"] == profile["上市公司名称"]
    assert context["candidate_tags"] == ["速冻食品制造"]
    assert context["label_profile_binding"] == "same_run_company" and context["low_trust"]
    # Reopening uses durable evidence/context files, independent of graph checkpoints.
    assert (
        resolve_context(TaskWorkspace(workspace.root), [identity.run_id])["context_fingerprint"]
        == context["context_fingerprint"]
    )


def test_summary_binding_rejects_conflicting_security_identity(tmp_path):
    with pytest.raises(ContextUnavailable, match="缺少"):
        build_context(
            tmp_path,
            profile={"上市公司名称": "测试食品有限公司", "证券代码": "833932"},
            tag_profile={"上市公司名称": "测试食品有限公司", "证券代码": "000001"},
        )


class MemoryJobs:
    def __init__(self, runs):
        self.rows = {}
        self.runs = runs

    def enqueue(self, job):
        previous = next(
            (j for j in self.rows.values() if j["idempotency_key"] == job["idempotency_key"]), None
        )
        if previous:
            return copy.deepcopy(previous)
        now = datetime.now(UTC).isoformat()
        job = copy.deepcopy(
            {
                **job,
                "status": "queued",
                "stage": "context_resolved",
                "claim_token": None,
                "artifact_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        self.rows[job["job_id"]] = job
        return copy.deepcopy(job)

    def list(self, task_id):
        return [
            copy.deepcopy(j) for j in reversed(list(self.rows.values())) if j["task_id"] == task_id
        ]

    def claim(self, timeout):
        job = next(
            (
                j
                for j in self.rows.values()
                if j["status"] == "queued" and self.runs.get_task(j["task_id"]).status != "running"
            ),
            None,
        )
        if not job:
            return None
        job.update(status="running", claim_token=uuid4().hex)
        return copy.deepcopy(job)

    def update(self, job, *, status="running", stage=None):
        row = self.rows[job["job_id"]]
        if row["status"] != "running" or row["claim_token"] != job["claim_token"]:
            return False
        self.rows[job["job_id"]] = copy.deepcopy(
            {**job, "status": status, "stage": stage or job["stage"]}
        )
        return True

    def append_auxiliary_artifact(self, job, artifact):
        row = self.rows[job["job_id"]]
        if row["status"] == "succeeded":
            return
        assert row["status"] == "running" and row["claim_token"] == job["claim_token"]
        run = self.runs.get_run(job["origin_run_id"])
        self.runs._runs[run.run_id] = run.model_copy(
            update={"artifacts": [*run.artifacts, artifact]}
        )
        self.rows[job["job_id"]] = copy.deepcopy(
            {
                **job,
                "status": "succeeded",
                "stage": "registered",
                "artifact_id": artifact.artifact_id,
            }
        )

    def for_artifact(self, artifact_id):
        return next((j for j in self.rows.values() if j.get("artifact_id") == artifact_id), None)


class Publisher:
    def __init__(self):
        self.objects = {}

    def workbook_object_key(self, task_id, job_id):
        return f"{task_id}/{job_id}/投资机构匹配.xlsx"

    def publish_workbook(self, task_id, job_id, content, *, object_key):
        self.objects[object_key] = content
        return PublishedArtifact(
            artifact_id="artifact_"
            + hashlib.sha256(f"{task_id}:{job_id}".encode()).hexdigest()[:32],
            filename="投资机构匹配.xlsx",
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            bucket="test",
            object_key=object_key,
            download_url="https://unused.test/download",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    def read_object(self, bucket, key):
        return self.objects[key]

    def refresh_download(self, artifact):
        return artifact


def completed_run(runs, identity):
    runs.create(identity, "报告请求")
    word = PublishedArtifact(
        artifact_id="artifact_" + uuid4().hex,
        filename="原报告.docx",
        sha256="a" * 64,
        size=4,
        bucket="test",
        object_key=f"{identity.task_id}/word.docx",
        download_url="https://unused.test/word",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    runs.finish(
        identity,
        status="completed",
        assistant_text="Word 已交付",
        trace=[{"tool": "parse_materials"}],
        artifacts=[word],
        skill_name="one-pager",
    )
    runs._runs[identity.run_id] = runs.get_run(identity.run_id).model_copy(
        update={"updated_at": datetime.now(UTC) - timedelta(seconds=20)}
    )
    return word


@pytest.mark.asyncio
async def test_investment_report_summary_context_exports_without_resuming_report(tmp_path):
    identity, _, context, _ = build_context(
        tmp_path,
        profile={"上市公司名称": "测试食品股份有限公司", "主营业务": "速冻食品制造"},
        company_name="测试食品",
        tag_company_name="测试食品股份有限公司",
        tag_profile="公司主营速冻食品制造。",
    )
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    runs._runs[identity.run_id] = runs.get_run(identity.run_id).model_copy(
        update={"skill_name": "investment-report"}
    )
    original = runs.get_run(identity.run_id)
    calls = []

    async def choose(request):
        calls.append("material-review")
        return {
            "selected": [
                {
                    "id": 0,
                    "ref": context["snippets"][0]["ref"],
                    "quote": "速冻食品制造",
                    "reason": "材料主营",
                }
            ]
        }

    class Transport:
        async def call_tool(self, name, arguments):
            calls.append(name)
            return workbook_payload(arguments["track_tags"])

    jobs = MemoryJobs(runs)
    service = InstitutionWorkbookService(
        settings(),
        tmp_path,
        runs,
        jobs,
        transport=Transport(),
        publisher=Publisher(),
        model_call=choose,
    )
    job = await service.enqueue_manual(
        identity.task_id, {"client_request_id": "investment-report-retry"}
    )
    await service.execute(jobs.claim(120))
    current = runs.get_run(identity.run_id)
    assert jobs.rows[job["job_id"]]["status"] == "succeeded"
    assert current.status == "completed" and current.assistant_text == original.assistant_text
    assert current.updated_at == original.updated_at and current.trace == original.trace
    assert runs.get_task(identity.task_id).run_ids == [identity.run_id]
    assert calls == ["material-review", "export_matched_institutions"]


def test_provenance_rejects_modified_sources_failed_evidence_and_other_companies(tmp_path):
    identity, workspace, context, record = build_context(tmp_path)
    original_fp = context["context_fingerprint"]
    assert len(context["snippets"]) == 1 and not context["low_trust"]
    # Exact tags for another company cannot attach to this profile.
    ContextRecorder._record(
        workspace,
        identity.run_id,
        "query_track_labels",
        {"company_name": "其他公司", "project_profile": context["profile"]},
        record,
    )
    assert resolve_context(workspace, [identity.run_id])["context_fingerprint"] == original_fp
    workspace.resolve("/workspace/input/项目.docx").write_bytes(b"changed-without-manifest")
    with pytest.raises(ContextUnavailable, match="校验失败"):
        resolve_context(workspace, [identity.run_id])
    # Already pinned input continues from immutable parsed/evidence references.
    assert (
        load_context(
            workspace,
            {
                k: v
                for k, v in context.items()
                if k not in {"profile", "snippets", "candidate_tags", "low_trust"}
            },
        )["context_fingerprint"]
        == original_fp
    )


def test_context_pins_user_clarifications_and_rejects_stale_company_tags(tmp_path):
    from report_agent.application.conversation_store import WorkspaceConversationStore

    identity, workspace, context, _ = build_context(tmp_path)
    history = WorkspaceConversationStore(workspace)
    history.append("user", "主营是速冻食品，请排除伙伴的软件业务。", run_id=identity.run_id)
    snapshot = resolve_context(workspace, [identity.run_id])
    assert snapshot["context_fingerprint"] != context["context_fingerprint"]
    assert snapshot["user_notes"][0]["text"].startswith("主营是速冻食品")
    history.append("user", "后续补充", run_id=identity.run_id)
    pinned = {
        k: v
        for k, v in snapshot.items()
        if k not in {"profile", "snippets", "candidate_tags", "low_trust"}
    }
    assert len(load_context(workspace, pinned)["user_notes"]) == 1

    # Same upload can describe another company in a subsequent run. Old tags are inapplicable.
    next_run = "run_" + uuid4().hex
    request_options(workspace, next_run, True)
    payload = {
        "schema_version": "1.0",
        "tool": "extract_project_profile",
        "status": "success",
        "summary": "完成",
        "data": {"profile": {"主营业务": "软件开发"}},
        "sources": [],
        "warnings": [],
    }
    entry = WorkspaceEvidenceStore(workspace).put("extract_project_profile", payload)
    WorkspaceContextStore(workspace).record_evidence(entry, json_roots=("/data",))
    material_id = context["materials"][0]["material_id"]
    ContextRecorder._record(
        workspace,
        next_run,
        "extract_project_profile",
        {
            "company_name": "另一家软件有限公司",
            "material_url": f"https://objects.test/exports/{identity.task_id}/{material_id}.md",
        },
        entry,
    )
    with pytest.raises(ContextUnavailable, match="缺少"):
        resolve_context(workspace, [identity.run_id, next_run])
    refreshed = resolve_context(workspace, [identity.run_id, next_run], allow_refresh=True)
    assert refreshed["company_name"] == "另一家软件有限公司" and refreshed["candidate_tags"] == []


@pytest.mark.asyncio
async def test_selection_reuses_small_trusted_set_and_limits_model_to_one(tmp_path):
    _, _, context, _ = build_context(tmp_path, tags=["甲", "乙", "丙", "丁", "戊", "己"])
    calls = []

    async def choose(request):
        calls.append(request)
        return {
            "selected": [
                {
                    "id": 1,
                    "ref": context["snippets"][0]["ref"],
                    "quote": "速冻食品制造",
                    "reason": "材料主营",
                }
            ]
        }

    result = await select_tags(context, settings().institution_workbook.selection, choose)
    assert result["tags"] == ["乙"] and len(calls) == 1
    context["candidate_tags"] = ["乙"]
    result = await select_tags(context, settings().institution_workbook.selection, choose)
    assert result["strategy"] == "reuse" and len(calls) == 1
    context["low_trust"] = True

    async def hallucinate(request):
        return {"selected": [{"id": 0, "ref": "foreign", "quote": "伪造原文", "reason": "test"}]}

    with pytest.raises(ContextUnavailable):
        await select_tags(context, settings().institution_workbook.selection, hallucinate)
    with pytest.raises(ContextUnavailable):
        await select_tags(context, settings().institution_workbook.selection, choose, ["新造标签"])


@pytest.mark.parametrize("tamper", ["sha", "formula", "base64", "headers", "rows", "tags"])
def test_workbook_file_boundary_rejects_untrusted_content(tamper):
    payload = workbook_payload(["甲"])
    if tamper == "sha":
        payload["data"]["sha256"] = "b" * 64
    elif tamper == "base64":
        payload["data"]["content_base64"] += "!"
    elif tamper == "tags":
        payload["data"]["query_tags"] = ["乙"]
    else:
        book = load_workbook(io.BytesIO(base64.b64decode(payload["data"]["content_base64"])))
        if tamper == "formula":
            book.active["A2"] = '=HYPERLINK("https://bad.test")'
        elif tamper == "headers":
            book.active["D1"] = "错误表头"
        else:
            book.active["A400"] = "过多行"
        stream = io.BytesIO()
        book.save(stream)
        content = stream.getvalue()
        payload["data"].update(
            content_base64=base64.b64encode(content).decode(),
            sha256=hashlib.sha256(content).hexdigest(),
        )
    with pytest.raises(ExportFailure):
        validate_file(payload, ["甲"], 2097152)


@pytest.mark.asyncio
async def test_large_contract_error_never_leaks_base64_or_exception_chain(caplog):
    marker = "PRIVATE_BASE64_DO_NOT_LOG"

    class Transport:
        async def call_tool(self, *args):
            return {"data": {"content_base64": marker * 10000}}

    with pytest.raises(ExportFailure) as caught:
        await call_export(Transport(), REPOSITORY_ROOT / "contracts/mcp", ["甲"])
    assert (
        marker not in str(caught.value)
        and marker not in caplog.text
        and caught.value.__suppress_context__
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "dmp", "upload", "file", "register"])
async def test_optional_job_failure_never_changes_report_and_success_only_appends(
    tmp_path, failure
):
    identity, workspace, context, _ = build_context(tmp_path)
    runs = InMemoryRunRepository()
    word = completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    jobs = MemoryJobs(runs)
    publisher = Publisher()
    calls = []

    class Transport:
        async def call_tool(self, name, arguments):
            calls.append(name)
            if failure == "dmp":
                raise RuntimeError("private-body")
            payload = workbook_payload(arguments["track_tags"])
            if failure == "file":
                payload["data"]["sha256"] = "b" * 64
            return payload

    if failure == "upload":

        def fail(*args, **kwargs):
            raise RuntimeError("private-upload")

        publisher.publish_workbook = fail
    if failure == "register":

        def fail_registration(*args):
            raise RuntimeError("registration unavailable")

        jobs.append_auxiliary_artifact = fail_registration
    service = InstitutionWorkbookService(
        settings(), tmp_path, runs, jobs, transport=Transport(), publisher=publisher
    )
    # Word has completed independently, before the export worker receives a job.
    job = await service.enqueue_manual(identity.task_id, {"client_request_id": "manual-test"})
    assert (
        runs.get_run(identity.run_id) == original and jobs.rows[job["job_id"]]["status"] == "queued"
    )
    await service.execute(jobs.claim(120))
    current = runs.get_run(identity.run_id)
    assert current.status == "completed" and current.assistant_text == original.assistant_text
    assert current.trace == original.trace and current.updated_at == original.updated_at
    assert current.artifacts[0] == word and calls == ["export_matched_institutions"]
    saved = jobs.rows[job["job_id"]]
    assert saved["status"] == ("failed" if failure else "succeeded")
    if not failure:
        assert (
            len(current.artifacts) == 2
            and service.preview(saved["artifact_id"])["rows"][0][-1] == "速冻食品制造"
        )
        app = create_app(
            SynchronousRunService(tmp_path, lambda: None, runs),
            dev_ui_enabled=True,
            artifact_service=publisher,
            institution_workbook_service=service,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            downloaded = await client.get(f"/api/artifacts/{saved['artifact_id']}/content")
            assert (
                downloaded.status_code == 200
                and downloaded.headers["content-type"] == XLSX_CONTENT_TYPE
            )
            assert hashlib.sha256(downloaded.content).hexdigest() == current.artifacts[-1].sha256
            assert (await client.get(f"/api/tasks/{identity.task_id}/auxiliary-jobs")).json()[
                "jobs"
            ][0]["status"] == "succeeded"
            assert (await client.get(f"/api/artifacts/{saved['artifact_id']}/preview")).json()[
                "row_count"
            ] == 1


@pytest.mark.asyncio
async def test_opt_in_persists_across_card_replies_without_becoming_a_model_message(tmp_path):
    runs = InMemoryRunRepository()
    seen = []

    async def execute(identity, workspace, message, **kwargs):
        seen.append(message)
        return {"messages": [AIMessage(content="需要补充")], "skill_name": "one-pager"}

    service = SynchronousRunService(tmp_path, execute, runs)
    first = await service.submit("生成报告", [], institution_workbook=True)
    await service.drain()
    second = await service.submit("补充材料", [], task_id=first.task_id)
    await service.drain()
    workspace = TaskWorkspace(tmp_path / first.task_id)
    assert read_interaction(workspace)["institution_workbook"] is True
    assert read_json(workspace, f"{ROOT}/requests/{second.run_id}.json")["enabled"]
    assert seen[0] == "生成报告" and seen[1].endswith("补充材料")
    assert all("institution_workbook" not in text and "附带投资机构" not in text for text in seen)
    third = await service.submit("再生成", [], task_id=first.task_id, institution_workbook=False)
    await service.drain()
    assert not workspace.resolve(f"{ROOT}/requests/{third.run_id}.json").exists()


@pytest.mark.asyncio
async def test_upload_retry_reuses_saved_selection_and_workbook_without_model_or_dmp(tmp_path):
    identity, _, context, _ = build_context(tmp_path, low_trust=True)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    jobs = MemoryJobs(runs)
    calls = []

    class Transport:
        async def call_tool(self, name, arguments):
            calls.append(name)
            return workbook_payload(arguments["track_tags"])

    async def choose(request):
        calls.append("selector")
        return {
            "selected": [
                {
                    "id": 0,
                    "ref": context["snippets"][0]["ref"],
                    "quote": "速冻食品制造",
                    "reason": "材料主营",
                }
            ]
        }

    class FailOnce(Publisher):
        attempts = 0

        def publish_workbook(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("upload unavailable")
            return super().publish_workbook(*args, **kwargs)

    service = InstitutionWorkbookService(
        settings(),
        tmp_path,
        runs,
        jobs,
        transport=Transport(),
        publisher=FailOnce(),
        model_call=choose,
    )
    first = await service.enqueue_manual(identity.task_id, {"client_request_id": "first-attempt"})
    await service.execute(jobs.claim(120))
    assert jobs.rows[first["job_id"]]["status"] == "failed"
    retry = await service.enqueue_manual(identity.task_id, {"client_request_id": "retry-attempt"})
    await service.execute(jobs.claim(120))
    assert jobs.rows[retry["job_id"]]["status"] == "succeeded"
    assert calls == ["selector", "export_matched_institutions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_selector_failure_or_timeout_preserves_completed_report(tmp_path, timeout):
    import asyncio

    identity, _, _, _ = build_context(tmp_path, low_trust=True)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    config = settings()
    config = config.model_copy(
        update={
            "institution_workbook": config.institution_workbook.model_copy(
                update={"selection_timeout_seconds": 1}
            )
        }
    )
    calls = []

    async def choose(request):
        calls.append("selector")
        if timeout:
            await asyncio.sleep(10)
        return {"selected": []}

    jobs = MemoryJobs(runs)
    service = InstitutionWorkbookService(config, tmp_path, runs, jobs, model_call=choose)
    job = await service.enqueue_manual(identity.task_id, {"client_request_id": "selector-failure"})
    await service.execute(jobs.claim(120))
    assert jobs.rows[job["job_id"]]["status"] == "failed"
    assert runs.get_run(identity.run_id) == original and calls == ["selector"]


@pytest.mark.asyncio
async def test_discovery_is_idempotent_and_does_not_duplicate_manual_export(tmp_path):
    identity, workspace, _, _ = build_context(tmp_path)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    jobs = MemoryJobs(runs)
    service = InstitutionWorkbookService(settings(), tmp_path, runs, jobs)
    await service.enqueue_manual(identity.task_id, {"client_request_id": "manual-before-auto"})
    service.discover()
    service.discover()
    assert len(jobs.list(identity.task_id)) == 1
    assert read_json(workspace, f"{ROOT}/requests/{identity.run_id}.json")["discovered"]


@pytest.mark.asyncio
async def test_missing_auxiliary_table_only_degrades_module_endpoint(tmp_path):
    identity, workspace, _, _ = build_context(tmp_path)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)

    class Broken:
        def list(self, task_id):
            raise RuntimeError("no table")

    optional = InstitutionWorkbookService(settings(), tmp_path, runs, Broken())
    app = create_app(
        SynchronousRunService(tmp_path, lambda: None, runs),
        dev_ui_enabled=True,
        institution_workbook_service=optional,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/tasks/{identity.task_id}/state")).status_code == 200
        result = (await client.get(f"/api/tasks/{identity.task_id}/auxiliary-jobs")).json()
        assert result["unavailable"] and runs.get_run(identity.run_id).status == "completed"


def test_minio_same_bytes_are_owned_by_task_and_job_not_global_sha():
    calls = []
    client = SimpleNamespace(
        put_object=lambda *a, **kw: calls.append((a, kw)),
        presigned_get_object=lambda *a, **kw: "https://test/download",
    )
    config = settings().persistence.minio
    env = {config.bucket.env: "test"}
    service = MinioArtifactService(config, env, client=client)
    first = RunIdentity.create()
    second = RunIdentity.create()
    job = "aux_" + uuid4().hex
    a = service.publish_workbook(
        first.task_id, job, b"bytes", object_key=service.workbook_object_key(first.task_id, job)
    )
    b = service.publish_workbook(
        second.task_id, job, b"bytes", object_key=service.workbook_object_key(second.task_id, job)
    )
    assert a.sha256 == b.sha256 and a.artifact_id != b.artifact_id and a.object_key != b.object_key
    assert all(kw["content_type"] == XLSX_CONTENT_TYPE for _, kw in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [["甲"], ["甲", "乙"], list("甲乙丙丁戊己")])
@pytest.mark.parametrize("match_status", ["success", "empty", "failed"])
async def test_automatic_export_reuses_actual_report_tags_without_selector(
    tmp_path, tags, match_status
):
    identity, workspace, context, query = build_context(
        tmp_path,
        tags=["其他候选"],
        low_trust=True,
        matched_tags=",".join(tags),
        match_status=match_status,
    )
    # A later label query in the same report must not replace the tags actually used for matching.
    ContextRecorder._record(
        workspace,
        identity.run_id,
        "query_track_labels",
        {
            "company_name": context["company_name"],
            "project_profile": context["profile"],
        },
        query,
    )
    assert resolve_context(workspace, [identity.run_id])["report_tags"] == tags
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    jobs = MemoryJobs(runs)
    calls = []

    class Transport:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return workbook_payload(arguments["track_tags"])

    async def no_model(_):
        pytest.fail("automatic export must not call a selector")

    service = InstitutionWorkbookService(
        settings(),
        tmp_path,
        runs,
        jobs,
        transport=Transport(),
        publisher=Publisher(),
        model_call=no_model,
    )
    service.discover()
    assert runs.get_run(identity.run_id) == original
    await service.execute(jobs.claim(120))
    saved = jobs.list(identity.task_id)[0]
    assert saved["status"] == "succeeded" and saved["selection"]["strategy"] == "report"
    assert calls == [("export_matched_institutions", {"track_tags": tags})]
    assert runs.get_run(identity.run_id).status == "completed"


@pytest.mark.asyncio
async def test_missing_report_tags_skip_automatic_selector_and_keep_manual_choices(tmp_path):
    identity, _, _, _ = build_context(tmp_path, low_trust=True)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    jobs = MemoryJobs(runs)
    service = InstitutionWorkbookService(settings(), tmp_path, runs, jobs)
    service.discover()
    await service.execute(jobs.claim(120))
    job = jobs.list(identity.task_id)[0]
    assert job["status"] == "skipped" and job["candidate_tags"] == ["速冻食品制造"]
    assert "实际使用" in job["reason"] and runs.get_run(identity.run_id) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_only", [False, True])
async def test_refreshed_group_manual_retry_and_upload_retry_reuse_same_version(
    tmp_path, profile_only
):
    identity, workspace, _, _ = build_context(tmp_path, matched_tags=["旧标签"])
    if profile_only:
        # An older report can have a valid profile but no recorded tag context.
        for path in workspace.resolve(f"{ROOT}/contexts").glob("*.json"):
            path.unlink()
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    jobs = MemoryJobs(runs)
    calls = []

    class Transport:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if name == "query_track_labels":
                return {
                    "schema_version": "1.0",
                    "tool": name,
                    "status": "partial",
                    "summary": "更新完成",
                    "data": {"tags": ["新标签甲", "新标签乙"]},
                    "sources": [],
                    "warnings": [],
                }
            return workbook_payload(arguments["track_tags"])

    async def invalid_selector(_):
        return "not valid JSON"

    class FailOnce(Publisher):
        attempts = 0

        def publish_workbook(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("private upload failure")
            return super().publish_workbook(*args, **kwargs)

    service = InstitutionWorkbookService(
        settings(),
        tmp_path,
        runs,
        jobs,
        transport=Transport(),
        publisher=FailOnce(),
        model_call=invalid_selector,
    )
    first = await service.enqueue_manual(
        identity.task_id, {"client_request_id": "refresh-group", "refresh_tags": True}
    )
    await service.execute(jobs.claim(120))
    refreshed = service.list_jobs(identity.task_id)[0]
    assert refreshed["status"] == "failed" and refreshed["candidate_tags"] == [
        "新标签甲",
        "新标签乙",
    ]
    assert "JSON" in refreshed["reason"]
    assert runs.get_run(identity.run_id) == original
    body = {
        "client_request_id": "select-new-group",
        "source_job_id": first["job_id"],
        "expected_context_fingerprint": refreshed["context_fingerprint"],
        "expected_tag_group_fingerprint": refreshed["tag_group_fingerprint"],
        "selected_tags": ["新标签乙"],
    }
    with pytest.raises(ContextUnavailable, match="标签组已变化"):
        await service.enqueue_manual(
            identity.task_id, {**body, "expected_tag_group_fingerprint": "stale"}
        )
    with pytest.raises(ContextUnavailable, match="材料或标签已变化"):
        await service.enqueue_manual(identity.task_id, {**body, "source_job_id": "aux_" + "a" * 32})
    manual = await service.enqueue_manual(identity.task_id, body)
    await service.execute(jobs.claim(120))
    saved = jobs.rows[manual["job_id"]]
    assert saved["status"] == "failed" and "附件上传" in saved["reason"]
    assert saved["selection"]["tags"] == ["新标签乙"]
    retry_body = {
        "client_request_id": "retry-new-group",
        "source_job_id": manual["job_id"],
        "expected_context_fingerprint": saved["context_fingerprint"],
        "expected_tag_group_fingerprint": saved["tag_group_fingerprint"],
    }
    retried = await service.enqueue_manual(identity.task_id, retry_body)
    # Replaying a request is idempotent even after a saved selection is available.
    assert (await service.enqueue_manual(identity.task_id, retry_body))["job_id"] == retried[
        "job_id"
    ]
    await service.execute(jobs.claim(120))
    assert jobs.rows[retried["job_id"]]["status"] == "succeeded"
    assert [name for name, _ in calls] == ["query_track_labels", "export_matched_institutions"]
    assert calls[-1][1] == {"track_tags": ["新标签乙"]}
    assert runs.get_run(identity.run_id).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("fenced", [False, True])
async def test_selector_accepts_json_and_fenced_json_with_original_evidence(tmp_path, fenced):
    import json

    _, _, context, _ = build_context(tmp_path, low_trust=True)
    selected = {
        "selected": [
            {
                "id": 0,
                "ref": context["snippets"][0]["ref"],
                "quote": "速冻食品制造",
                "reason": "主营",
            }
        ]
    }

    async def choose(_):
        text = json.dumps(selected, ensure_ascii=False)
        return f"```json\n{text}\n```" if fenced else text

    assert (await select_tags(context, settings().institution_workbook.selection, choose))[
        "tags"
    ] == ["速冻食品制造"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["DMP_EXPORT_NOT_CONFIGURED", "DMP_EXPORT_UNAVAILABLE", "DMP_EXPORT_INVALID_RESPONSE"]
)
async def test_dmp_failure_code_is_preserved_without_changing_report(tmp_path, code):
    identity, _, _, _ = build_context(tmp_path, matched_tags=["甲"])
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    jobs = MemoryJobs(runs)

    class Transport:
        async def call_tool(self, name, arguments):
            return {
                "schema_version": "1.0",
                "tool": name,
                "status": "failed",
                "summary": "失败",
                "data": {},
                "sources": [],
                "warnings": [{"code": code, "message": "failure", "retryable": True}],
            }

    service = InstitutionWorkbookService(settings(), tmp_path, runs, jobs, transport=Transport())
    job = await service.enqueue_manual(identity.task_id, {"client_request_id": "offline-dmp"})
    await service.execute(jobs.claim(120))
    saved = jobs.rows[job["job_id"]]
    assert saved["status"] == "failed" and saved["error_code"] == code
    assert saved["stage"] == "request_started" and "DMP" in saved["reason"]
    assert runs.get_run(identity.run_id) == original


@pytest.mark.asyncio
async def test_too_many_actual_report_tags_require_manual_selection_without_truncation(tmp_path):
    tags = [f"标签{i}" for i in range(11)]
    identity, _, _, _ = build_context(tmp_path, matched_tags=tags)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    jobs = MemoryJobs(runs)
    service = InstitutionWorkbookService(settings(), tmp_path, runs, jobs)
    service.discover()
    await service.execute(jobs.claim(120))
    saved = jobs.list(identity.task_id)[0]
    assert saved["status"] == "failed" and saved["candidate_tags"] == tags
    assert "10 个" in saved["reason"] and "selection" not in saved


@pytest.mark.asyncio
async def test_enqueue_internal_error_does_not_claim_database_migration_failed(tmp_path, caplog):
    identity, _, _, _ = build_context(tmp_path)
    runs = InMemoryRunRepository()
    completed_run(runs, identity)
    original = runs.get_run(identity.run_id)
    service = InstitutionWorkbookService(settings(), tmp_path, runs, MemoryJobs(runs))

    async def fail(*args):
        raise RuntimeError("private context details")

    service.enqueue_manual = fail
    app = create_app(
        SynchronousRunService(tmp_path, lambda: None, runs),
        dev_ui_enabled=True,
        institution_workbook_service=service,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/tasks/{identity.task_id}/institution-workbook",
            json={"client_request_id": "error-test"},
        )
    assert response.status_code == 503
    assert "迁移" not in response.json()["detail"] and "原报告不受影响" in response.json()["detail"]
    assert "private context details" not in caplog.text
    assert runs.get_run(identity.run_id) == original


@pytest.mark.parametrize(
    "raw", [["甲", "乙"], "甲,乙", "[甲,乙]", "甲，乙", "甲;乙", "甲；乙", "甲|乙"]
)
def test_report_tag_input_matches_investor_tool_forms(raw):
    assert report_tags(raw) == ["甲", "乙"]
    assert report_tags(["甲", "甲"]) == ["甲"]
    assert report_tags(["甲", "bad,tag"]) == []


@pytest.mark.parametrize("conflict", [None, "company", "security"])
def test_actual_matching_tags_bind_corrected_name_but_reject_other_identity(tmp_path, conflict):
    profile = {"上市公司名称": "测试食品股份有限公司", "证券代码": "833932", "主营业务": "食品制造"}
    identity, workspace, context, _ = build_context(
        tmp_path,
        company_name="测试食品",
        profile=profile,
        tag_company_name="测试食品股份有限公司",
    )
    payload = {
        "schema_version": "1.0",
        "tool": "match_investors",
        "status": "partial",
        "summary": "匹配完成",
        "data": {},
        "sources": [],
        "warnings": [],
    }
    record = WorkspaceEvidenceStore(workspace).put("match_investors", payload)
    WorkspaceContextStore(workspace).record_evidence(record, json_roots=("/data",))
    ContextRecorder._record(
        workspace,
        identity.run_id,
        "match_investors",
        {
            "company_name": "其他公司" if conflict == "company" else "测试食品",
            "project_profile": {**profile, "证券代码": "000001"}
            if conflict == "security"
            else "主营食品制造。",
            "track_tags": ["食品制造"],
        },
        record,
    )
    resolved = resolve_context(workspace, [identity.run_id])
    if conflict:
        assert resolved["context_fingerprint"] == context["context_fingerprint"]
    else:
        assert resolved["report_tags"] == ["食品制造"]
        assert resolved["company_name"] == profile["上市公司名称"]
