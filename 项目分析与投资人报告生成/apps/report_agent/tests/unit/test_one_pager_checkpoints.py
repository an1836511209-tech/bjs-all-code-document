"""Actual graph interrupts, resume cursor, cache and investment isolation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from report_agent.api.app import create_app
from report_agent.application.bootstrap import ConfiguredAgentExecutor
from report_agent.application.event_bus import RunEventBus
from report_agent.application.interactions import read_interaction, update_interaction
from report_agent.application.one_pager_execution import (
    COMMAND_PATH,
    STATE_PATH,
    VERSION,
    execution_state,
    write_json,
)
from report_agent.application.one_pager_reports import OnePagerReportService
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.documents import DocumentArtifact
from report_agent.domain.events import EventType
from report_agent.domain.identifiers import RunIdentity
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.budget import BudgetExceeded, BudgetPaused, RunBudget
from report_agent.harness.middleware.one_pager_cache import OnePagerResultCacheMiddleware
from report_agent.harness.middleware.persistent_questions import (
    PersistentQuestionBoundaryMiddleware,
)
from report_agent.harness.one_pager_checkpoint import run_checkpointed_agent
from report_agent.infrastructure.artifacts import MinioArtifactService
from report_agent.infrastructure.persistence.checkpoints import (
    AsyncCheckpointAdapter,
    build_one_pager_checkpointer,
)
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.infrastructure.persistence.mysql_runs import MySQLRunRepository
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings import load_settings


def mysql_test_saver():
    if os.environ.get("BJS_CHECKPOINT_INTEGRATION") != "1":
        pytest.skip("requires explicitly enabled dedicated test MySQL schema")
    settings = load_settings(Path("deploy/environments/test/report-agent.local.yaml"))
    environ = dict(os.environ)
    for line in Path("deploy/environments/test/runtime.env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    environ["REPORT_AGENT_CHECKPOINT_DATABASE"] = "bjs_report_agent_checkpoints_test"
    return build_one_pager_checkpointer(settings.persistence.mysql, environ, "REPORT_AGENT_CHECKPOINT_DATABASE")


class WorkflowModel(BaseChatModel):
    calls: list = []
    with_plan: bool = False

    @property
    def _llm_type(self):
        return "checkpoint-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append([getattr(m, "type", "?") for m in messages])
        results = [m for m in messages if isinstance(m, ToolMessage)]
        names = {m.name for m in results}
        if self.with_plan and "write_todos" not in names:
            name, args = "write_todos", {"todos": [
                {"content": text, "status": "completed" if i < 2 else "pending"}
                for i, text in enumerate(["初始化", "解析材料", "补数", "投资人匹配", "写作审查", "发布"])
            ]}
        elif "parse_materials" not in names:
            name, args = "parse_materials", {"path": "/workspace/input/material.txt"}
        elif "detect_one_pager_business_type" not in names:
            name, args = "detect_one_pager_business_type", {}
        elif "query_track_labels" not in names:
            name, args = "query_track_labels", {"company_name": "精确公司"}
        elif "ask_user" not in names:
            name, args = "ask_user", {"question": "本项目是否为北交互联正在披露的项目？"}
        else:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="完成"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": "call-" + name}
        ]))])


def make_graph(saver, calls, workspace, *, deep=False, planning=False):
    def parse_materials(path: str) -> str:
        """Parse materials once."""
        calls["parse"] += 1
        return json.dumps({"material_id": "material_test"})

    def detect_one_pager_business_type() -> str:
        """Ask a typed business question."""
        calls["detect"] += 1
        return json.dumps({"question_request": {"gate": "one_pager_business_type"}})

    def query_track_labels(company_name: str) -> str:
        """Read labels once."""
        calls["labels"] += 1
        return json.dumps({"status": "success", "tags": ["软件"]})

    tools = [StructuredTool.from_function(fn) for fn in
             (parse_materials, detect_one_pager_business_type, query_track_labels)]
    tools.extend(build_ask_user_tools(resumable=True))
    middleware = [PersistentQuestionBoundaryMiddleware(), OnePagerResultCacheMiddleware(workspace, "test-v1")]
    model = WorkflowModel(calls=[], with_plan=planning)
    if deep:
        from deepagents.backends import FilesystemBackend

        from report_agent.harness.factory import AgentBuildSpec, build_agent
        graph = build_agent(AgentBuildSpec(model=model,
            backend=FilesystemBackend(root_dir=str(workspace.root), virtual_mode=True),
            system_prompt="按顺序执行测试工具。", tools=tuple(tools),
            middleware=tuple(middleware), checkpointer=saver))
    else:
        graph = create_agent(model=model, tools=tools, middleware=middleware, checkpointer=saver)
    return graph, model


async def invoke(agent, inputs, config, identity, *, checkpointed=False):
    return await agent.ainvoke(inputs, config=config, durability="sync")


def initialize(tmp_path):
    identity = RunIdentity.create()
    workspace = TaskWorkspace(tmp_path / identity.task_id)
    workspace.initialize()
    workspace.import_artifact("input", "material.txt", "公司业务材料".encode())
    write_json(workspace, STATE_PATH, {"version": VERSION, "thread_id": "one-pager:" + identity.task_id,
                                     "status": "new"})
    write_json(workspace, COMMAND_PATH, {"id": "user_first", "kind": "message", "text": "一页纸", "status": "pending"})
    return identity, workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("deep", [False, True])
async def test_rebuilt_graph_resumes_exact_wait_with_full_tool_context(tmp_path, deep):
    identity, workspace = initialize(tmp_path)
    # The async bridge is exercised with a real saver, not an async stub.
    saver = AsyncCheckpointAdapter(InMemorySaver())
    calls = Counter()
    graph, model = make_graph(saver, calls, workspace, deep=deep)
    first = await run_checkpointed_agent(graph, workspace, identity,
        {"messages": [HumanMessage(id="user_first", content="一页纸")]}, invoke)
    assert first["execution_status"] == "needs_input"
    q = first["pending_question"]
    assert [o["value"] for o in q["options"]] == ["产权", "增资"]
    assert q["checkpointed"] and first["execution"]["next"]
    assert calls == {"parse": 1, "detect": 1}
    # Rebuild model/graph (no Python call stack survives); same saved graph state.
    graph, resumed_model = make_graph(saver, calls, workspace, deep=deep)
    write_json(workspace, COMMAND_PATH, {"kind": "resume", "status": "pending",
        "question_id": q["question_id"], "answer": {"question_id": q["question_id"], "text": "增资；融资5000万元"}})
    second = await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
    assert second["execution_status"] == "needs_input"
    assert [o["value"] for o in second["pending_question"]["options"]] == ["yes", "no", "unknown"]
    assert calls == {"parse": 1, "detect": 1, "labels": 1}
    assert any(isinstance(m, HumanMessage) and "5000" in m.content for m in second["messages"])
    assert len(resumed_model.calls) == 2
    # Merely reopening a waiting task performs no model/tool calls.
    before = len(resumed_model.calls)
    await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
    assert len(resumed_model.calls) == before
    q2 = second["pending_question"]
    write_json(workspace, COMMAND_PATH, {"kind": "resume", "status": "pending",
        "question_id": q2["question_id"], "answer": {"question_id": q2["question_id"], "text": "不是；财务以材料为准"}})
    third = await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
    assert third["execution_status"] == "completed"
    assert calls == {"parse": 1, "detect": 1, "labels": 1}
    # Lost response after completion: the same command never executes again.
    before = len(resumed_model.calls)
    await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
    assert len(resumed_model.calls) == before


@pytest.mark.asyncio
async def test_cache_reuses_read_and_invalidates_material_change_but_not_failures(tmp_path):
    _, workspace = initialize(tmp_path)
    cache = OnePagerResultCacheMiddleware(workspace, "v1")
    count = 0
    request = SimpleNamespace(tool_call={"name": "query_track_labels", "args": {"company_name": "A"}, "id": "one"})
    async def handler(req):
        nonlocal count
        count += 1
        return ToolMessage(name="query_track_labels", tool_call_id=req.tool_call["id"],
                           content=json.dumps({"status": "success", "tags": ["A"]}))
    await cache.awrap_tool_call(request, handler)
    request.tool_call["id"] = "two"
    result = await cache.awrap_tool_call(request, handler)
    assert result.tool_call_id == "two" and count == 1
    request.tool_call["args"]["company_name"] = "B"
    await cache.awrap_tool_call(request, handler)
    assert count == 2
    workspace.import_artifact("input", "material.txt", "更正材料".encode())
    await cache.awrap_tool_call(request, handler)
    assert count == 3
    request.tool_call["args"]["company_name"] = "failed"
    async def failure(req):
        nonlocal count
        count += 1
        return ToolMessage(content='{"status":"failed"}', name="query_track_labels", tool_call_id="x")
    await cache.awrap_tool_call(request, failure)
    await cache.awrap_tool_call(request, failure)
    assert count == 5


def configured_executor():
    settings = load_settings(Path("deploy/environments/test/report-agent.local.yaml"))
    return ConfiguredAgentExecutor(settings, artifact_service=SimpleNamespace(), one_pager_checkpointer=InMemorySaver())


def test_submission_opt_in_isolates_investment_and_legacy_tasks(tmp_path):
    executor = configured_executor()
    for skill, legacy, checkpointed in [("investment-report", False, False),
                                       ("one-pager", True, False), ("one-pager", False, True)]:
        identity = RunIdentity.create()
        workspace = TaskWorkspace(tmp_path / identity.task_id)
        workspace.initialize()
        if legacy:
            update_interaction(workspace, run_id="run_legacy", active_skill=skill)
        executor.prepare_submission(identity, workspace, "生成报告", selected_skill=skill)
        assert bool(execution_state(workspace)) is checkpointed
        if not checkpointed:
            assert not workspace.resolve(COMMAND_PATH).exists()
    assert build_ask_user_tools()[0].return_direct is True
    assert build_ask_user_tools(resumable=True)[0].return_direct is False


def test_restored_budget_pauses_instead_of_failing():
    saved = []
    first = RunBudget(max_model_calls=2, max_tool_calls=5, timeout_seconds=100, persist=saved.append)
    first.consume_model_call()
    restored = RunBudget(max_model_calls=2, max_tool_calls=5, timeout_seconds=100, initial=saved[-1])
    restored.consume_model_call()
    with pytest.raises(BudgetPaused):
        restored.consume_model_call()
    assert restored.snapshot().model_calls == 2


@pytest.mark.asyncio
async def test_recovery_only_requeues_opted_in_accepted_run(tmp_path):
    identity, workspace = initialize(tmp_path)
    write_json(workspace, "/workspace/state/pending.json", {"run_id": identity.run_id, "message": "一页纸"})
    update_interaction(workspace, status="running", run_id=identity.run_id, session_id=identity.session_id,
                       workspace_id=identity.workspace_id, active_skill="one-pager")
    seen = []
    async def executor(identity, workspace, message, *, selected_skill=""):
        seen.append((identity.run_id, selected_skill))
        return {"messages": [AIMessage(content="完成")], "skill_name": "chat"}
    repository = InMemoryRunRepository()
    repository.create(identity, "一页纸")
    service = SynchronousRunService(tmp_path, executor, repository)
    legacy = TaskWorkspace(tmp_path / RunIdentity.create().task_id)
    legacy.initialize()
    update_interaction(legacy, status="running", active_skill="investment-report")
    assert await service.recover_one_pager_runs() == 1
    await service.drain()
    assert seen == [(identity.run_id, "one-pager")]
    assert read_interaction(legacy)["status"] == "running"


@pytest.mark.asyncio
async def test_mysql_process_restart_restores_interrupt_and_tool_messages(tmp_path):
    saver = mysql_test_saver()
    identity, workspace = initialize(tmp_path)
    thread_config = {"configurable": {"thread_id": execution_state(workspace)["thread_id"]}}
    try:
        graph, _ = make_graph(saver, Counter(), workspace, deep=True)
        first = await run_checkpointed_agent(graph, workspace, identity,
            {"messages": [HumanMessage(id="user_first", content="一页纸")]}, invoke)
        q = first["pending_question"]
        write_json(workspace, COMMAND_PATH, {"kind": "resume", "status": "pending",
            "question_id": q["question_id"], "answer": {"question_id": q["question_id"], "text": "增资；融资5000万元"}})
        # New Python process, new saver connections, new graph and new model.
        script = r'''
import asyncio,json,runpy,sys
from collections import Counter
ns=runpy.run_path('apps/report_agent/tests/unit/test_one_pager_checkpoints.py')
async def main():
    workspace=ns['TaskWorkspace'](ns['Path'](sys.argv[1]))
    identity=ns['RunIdentity'].for_task(workspace.root.name)
    calls=Counter()
    graph,model=ns['make_graph'](ns['mysql_test_saver'](),calls,workspace,deep=True)
    result=await ns['run_checkpointed_agent'](graph,workspace,identity,{},ns['invoke'])
    print(json.dumps({'calls':dict(calls),'question_id':result['pending_question']['question_id'],'options':[o['value'] for o in result['pending_question']['options']],'model_calls':len(model.calls)}))
asyncio.run(main())
'''
        proc = await __import__("asyncio").to_thread(subprocess.run,
            [sys.executable, "-c", script, str(workspace.root)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=45)
        assert proc.returncode == 0, proc.stderr[-3000:]
        summary = json.loads(proc.stdout.strip().splitlines()[-1])
        assert summary["calls"] == {"labels": 1}
        assert summary["options"] == ["yes", "no", "unknown"]
        assert summary["model_calls"] == 2
        # Reopen in this process and finish the second gate without replay.
        q2 = execution_state(workspace)["pending_question"]
        write_json(workspace, COMMAND_PATH, {"kind": "resume", "status": "pending",
            "question_id": q2["question_id"], "answer": {"question_id": q2["question_id"], "text": "不是"}})
        calls = Counter()
        graph, _ = make_graph(mysql_test_saver(), calls, workspace, deep=True)
        result = await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
        assert result["execution_status"] == "completed"
        assert calls == {}
    finally:
        await saver.adelete_thread(thread_config["configurable"]["thread_id"])


@pytest.mark.asyncio
async def test_configured_investment_executor_never_opens_checkpoint_backend(tmp_path, monkeypatch):
    import report_agent.application.bootstrap as assembly
    executor = configured_executor()
    executor._environ.update(LLM_MODEL="test", LLM_BASE_URL="https://example.invalid", LLM_API_KEY="test")
    identity = RunIdentity.create()
    workspace = TaskWorkspace(tmp_path / identity.task_id)
    workspace.initialize()
    captured = []
    publishers = []
    artifact = PublishedArtifact(
        artifact_id="artifact_" + "b" * 32, filename="投资报告.docx",
        sha256="c" * 64, size=4, bucket="test", object_key="report.docx",
        download_url="https://example.invalid/report",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    repository = InMemoryRunRepository()
    executor._artifact_service = SimpleNamespace(
        publish=lambda *_: artifact,
        read_object=lambda *_: b"docx",
    )
    executor._event_bus = RunEventBus()
    app = create_app(
        SynchronousRunService(tmp_path, executor, repository),
        dev_ui_enabled=True,
        artifact_service=executor._artifact_service,
    )

    async def ready(*args, **kwargs):
        pass

    async def run(*args, **kwargs):
        publishers[0]("/workspace/staging/report.docx")
        assert executor._event_bus.events(identity.run_id)[-1].type == EventType.ARTIFACT_CREATED
        assert repository.get_artifact(artifact.artifact_id) is None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/artifacts/{artifact.artifact_id}/content")
        assert response.status_code == 200
        assert response.content == b"docx"
        return {"messages": [AIMessage(content="投资报告完成")]}

    def tools(**kwargs):
        publishers.append(kwargs["publish"])
        return ()
    def no_checkpoint():
        raise AssertionError("investment report must not open a checkpoint connection")
    monkeypatch.setattr(assembly, "ReasoningChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr(assembly, "build_workspace_backend", lambda *args, **kwargs: object())
    monkeypatch.setattr(assembly, "build_context_middleware_stack", lambda *args, **kwargs: (None, ()))
    monkeypatch.setattr(assembly, "build_investment_report_tools", tools)
    monkeypatch.setattr(assembly, "build_agent", lambda spec: captured.append(spec) or object())
    monkeypatch.setattr(assembly.DataMcpGateway, "readiness", ready)
    monkeypatch.setattr(executor, "_build_material_parser", lambda settings: None)
    monkeypatch.setattr(executor, "_run_agent", run)
    monkeypatch.setattr(executor, "_get_one_pager_checkpointer", no_checkpoint)
    result = await executor(identity, workspace, "生成投资报告", selected_skill="investment-report")
    assert result["skill_name"] == "investment-report" and len(publishers) == 1
    assert captured[0].checkpointer is None
    assert type(captured[0].middleware[0]).__name__ == "QuestionBoundaryMiddleware"
    assert all(not isinstance(m, OnePagerResultCacheMiddleware) for m in captured[0].middleware)
    assert not execution_state(workspace)


@pytest.mark.asyncio
async def test_async_db_adapter_drains_write_before_cancellation_returns():
    started = threading.Event()
    finished = threading.Event()
    saver = InMemorySaver()
    def slow_write(*args):
        started.set()
        time.sleep(0.12)
        finished.set()
    saver.put_writes = slow_write
    adapter = AsyncCheckpointAdapter(saver)
    task = asyncio.create_task(adapter.aput_writes({}, [], "task"))
    while not started.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_corrupt_one_pager_does_not_block_report_service_startup(tmp_path):
    identity, workspace = initialize(tmp_path)
    workspace.resolve(STATE_PATH).write_text("broken json", encoding="utf-8")
    service = SynchronousRunService(tmp_path, SimpleNamespace(), InMemoryRunRepository())
    assert await service.recover_one_pager_runs() == 0


def test_render_and_publish_manifest_survives_service_reconstruction(tmp_path):
    _, workspace = initialize(tmp_path)
    content = b"rendered-docx-test"
    source = "/workspace/output/bp.docx"
    sha = hashlib.sha256(content).hexdigest()
    artifact_id = "artifact_" + sha[:32]
    workspace.write_bytes(source, content)
    document = DocumentArtifact(artifact_id=artifact_id, path=source, sha256=sha,
                                skill_version="a" * 64, comment_count=0, valid=True)
    write_json(workspace, source + ".render.json", {
        "artifact_id": artifact_id, "path": source, "sha256": sha, "business_type": "增资",
        "issues": [], "notes": [], "document_artifact": document.model_dump(mode="json")})
    calls = []
    def publish(path):
        calls.append(path)
        return PublishedArtifact(artifact_id=artifact_id, filename="bp.docx", sha256=sha,
            size=len(content), bucket="reports", object_key="test/bp.docx", download_url="https://example.invalid/bp",
            expires_at=datetime.now(UTC) + timedelta(hours=1))
    first = OnePagerReportService(workspace, restore_persisted=True)
    first.publish(artifact_id, publish)
    restarted = OnePagerReportService(workspace, restore_persisted=True)
    result = restarted.publish(artifact_id, publish)
    assert len(calls) == 1 and result.published.artifact_id == artifact_id
    workspace.write_bytes(source, b"changed")
    with pytest.raises(ValueError, match="变化"):
        OnePagerReportService(workspace, restore_persisted=True).artifact(artifact_id)


def test_idempotent_one_pager_publish_keeps_legacy_report_default(tmp_path):
    identity, workspace = initialize(tmp_path)
    workspace.write_bytes("/workspace/output/test.docx", b"fake-test-docx")
    staged = workspace.stage("/workspace/output/test.docx")
    settings = load_settings(Path("deploy/environments/test/report-agent.local.yaml")).persistence.minio
    env = {settings.bucket.env: "test", settings.endpoint.env: "localhost:9000", settings.access_key.env: "test",
           settings.secret_key.env: "test", settings.secure.env: "false"}
    keys = []
    client = SimpleNamespace(put_object=lambda bucket, key, *args, **kwargs: keys.append(key),
                             presigned_get_object=lambda *args, **kwargs: "https://example.invalid/download")
    a = MinioArtifactService(settings, env, client=client).publish(identity, workspace, staged.path, idempotent=True)
    b = MinioArtifactService(settings, env, client=client).publish(identity, workspace, staged.path, idempotent=True)
    assert a.artifact_id == b.artifact_id and keys[0] == keys[1]
    c = MinioArtifactService(settings, env, client=client).publish(identity, workspace, staged.path)
    d = MinioArtifactService(settings, env, client=client).publish(identity, workspace, staged.path)
    assert c.artifact_id != d.artifact_id  # The legacy investment path is unchanged.


def test_checkpointed_metadata_finalize_deduplicates_owned_artifact_only(tmp_path, monkeypatch):
    identity, _ = initialize(tmp_path)
    artifact = PublishedArtifact(artifact_id="artifact_" + "a" * 32, filename="bp.docx", sha256="b" * 64,
        size=10, bucket="reports", object_key="bp.docx", download_url="https://example.invalid/download",
        expires_at=datetime.now(UTC) + timedelta(hours=1))
    repository = MySQLRunRepository(lambda: None)
    recorded = []
    monkeypatch.setattr(repository, "get_task", lambda key: SimpleNamespace(artifact_ids=[artifact.artifact_id]))
    monkeypatch.setattr(repository, "get_artifact", lambda key: artifact)
    monkeypatch.setattr(repository, "finish", lambda *args, **fields: recorded.append(fields))
    repository.finish_checkpointed(identity, status="completed", artifacts=[artifact])
    assert recorded[-1]["artifacts"] == []
    monkeypatch.setattr(repository, "get_task", lambda key: SimpleNamespace(artifact_ids=[]))
    with pytest.raises(ValueError, match="归属"):
        repository.finish_checkpointed(identity, status="completed", artifacts=[artifact])


@pytest.mark.asyncio
async def test_configured_one_pager_full_middleware_stack_resumes_without_readiness_or_reparse(tmp_path, monkeypatch):
    import report_agent.application.bootstrap as assembly
    from report_agent.domain.evidence import EvidenceView
    identity = RunIdentity.create()
    workspace = TaskWorkspace(tmp_path / identity.task_id)
    workspace.initialize()
    workspace.import_artifact("input", "material.txt", b"test-material")
    calls = Counter()
    models = []
    def model(**kwargs):
        instance = WorkflowModel(calls=[], with_plan=True)
        models.append(instance)
        return instance
    original_material_tools = assembly.build_material_tools
    original_one_pager_tools = assembly.build_one_pager_tools
    def parse_materials(path: str) -> str:
        """Synthetic parser with an observable call count."""
        calls["parse"] += 1
        return json.dumps({"material_id": "material_test"})
    def detect_one_pager_business_type() -> str:
        """Synthetic uncertain business type."""
        return json.dumps({"question_request": {"gate": "one_pager_business_type"}})
    def materials(*args, **kwargs):
        return tuple(StructuredTool.from_function(parse_materials) if t.name == "parse_materials" else t
                     for t in original_material_tools(*args, **kwargs))
    def one_pager(*args, **kwargs):
        return tuple(StructuredTool.from_function(detect_one_pager_business_type) if t.name == "detect_one_pager_business_type" else t
                     for t in original_one_pager_tools(*args, **kwargs))
    async def ready(*args, **kwargs):
        calls["ready"] += 1
    async def query(*args, **kwargs):
        calls["labels"] += 1
        return EvidenceView(evidence_id="evidence_test", tool="query_track_labels", status="success", summary="test",
                            warnings=(), path="/workspace/evidence/test.json", sha256="a" * 64, size_bytes=10,
                            json_roots=("/data/tags",))
    monkeypatch.setattr(assembly, "ReasoningChatOpenAI", model)
    monkeypatch.setattr(assembly, "build_material_tools", materials)
    monkeypatch.setattr(assembly, "build_one_pager_tools", one_pager)
    monkeypatch.setattr(assembly.DataMcpGateway, "readiness", ready)
    monkeypatch.setattr(assembly.DataMcpGateway, "call", query)
    monkeypatch.setattr(ConfiguredAgentExecutor, "_build_material_parser", lambda *args: None)
    saver = AsyncCheckpointAdapter(InMemorySaver())
    settings = load_settings(Path("deploy/environments/test/report-agent.local.yaml"))
    env = {settings.model.model.env: "test", settings.model.base_url.env: "https://example.invalid",
           settings.model.api_key.env: "test", settings.context.model_context_tokens.env: "1000000"}
    core = ConfiguredAgentExecutor(settings, env, artifact_service=SimpleNamespace(), one_pager_checkpointer=saver)
    core.prepare_submission(identity, workspace, "一页纸", selected_skill="one-pager")
    first = await core(identity, workspace, "一页纸", selected_skill="one-pager")
    q = first["pending_question"]
    assert q["checkpointed"] and calls == {"parse": 1, "ready": 1}
    resumed = ConfiguredAgentExecutor(settings, env, artifact_service=SimpleNamespace(), one_pager_checkpointer=saver)
    resumed.prepare_submission(RunIdentity.for_task(identity.task_id), workspace, "用户选择增资，融资5000万元",
                               selected_skill="one-pager", question=q)
    second = await resumed(identity, workspace, "用户选择增资，融资5000万元", selected_skill="one-pager")
    assert second["execution_status"] == "needs_input"
    assert "北交互联" in second["pending_question"]["question"]
    assert calls == {"parse": 1, "ready": 1, "labels": 1}
    # 预算按本次 run 计（不跨 run 累计）：快照里应是第二轮自己的调用数。
    # 累计会让"问 2-3 轮再继续"的一页纸在第 3 轮一提交就 BudgetExceeded。
    assert execution_state(workspace)["budget"]["model_calls"] == len(models[-1].calls)
    assert not any(getattr(m, "name", None) == "parse_materials" for m in second["trace_messages"])


@pytest.mark.asyncio
async def test_missing_checkpoint_never_silently_starts_over(tmp_path):
    identity, workspace = initialize(tmp_path)
    state = execution_state(workspace)
    write_json(workspace, STATE_PATH, {**state, "status": "waiting", "checkpoint_id": "old"})
    calls = Counter()
    graph, _ = make_graph(InMemorySaver(), calls, workspace)
    with pytest.raises(ValueError, match="不能从头重跑"):
        await run_checkpointed_agent(graph, workspace, identity, {"messages": [HumanMessage(content="old answer")]}, invoke)
    assert calls == {}


@pytest.mark.asyncio
async def test_crash_after_answer_commit_recovers_new_question_without_old_card_or_model_replay(tmp_path):
    identity, workspace = initialize(tmp_path)
    saver = InMemorySaver()
    calls = Counter()
    graph, model = make_graph(saver, calls, workspace)
    first = await run_checkpointed_agent(graph, workspace, identity,
        {"messages": [HumanMessage(id="user_first", content="一页纸")]}, invoke)
    q = first["pending_question"]
    write_json(workspace, COMMAND_PATH, {"kind": "resume", "status": "pending", "question_id": q["question_id"],
        "answer": {"question_id": q["question_id"], "text": "增资"}})
    async def crash_after_checkpoint(*args, **kwargs):
        await invoke(*args, **kwargs)
        raise RuntimeError("process died before projection")
    with pytest.raises(RuntimeError):
        await run_checkpointed_agent(graph, workspace, identity, {}, crash_after_checkpoint)
    assert execution_state(workspace)["pending_question"] is None
    before = len(model.calls)
    recovered = await run_checkpointed_agent(graph, workspace, identity, {}, invoke)
    assert "北交互联" in recovered["pending_question"]["question"]
    assert recovered["pending_question"]["question_id"] != q["question_id"]
    assert len(model.calls) == before and calls == {"parse": 1, "detect": 1, "labels": 1}
