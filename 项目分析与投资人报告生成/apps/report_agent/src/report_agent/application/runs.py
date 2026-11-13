"""Task submission and execution for the Report Agent HTTP API.

Scheme A: ``submit`` accepts a run immediately (status=running) and finishes in
a background asyncio task. Callers poll ``GET /api/runs/{run_id}`` / tasks.
``run`` remains a synchronous await-until-done helper for tests and local tools.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import threading
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from report_agent.application.conversation_store import WorkspaceConversationStore
from report_agent.harness.budget import BudgetPaused
from report_agent.application.event_bus import RunEventBus
from report_agent.application.interactions import (
    answer_text,
    business_type_answer,
    cbex_answer,
    question_payload,
    read_interaction,
    registry_answer,
    risk_disclosure_answer,
    update_interaction,
)
from report_agent.application.one_pager_execution import (
    COMMAND_PATH,
    execution_lock,
    execution_state,
    read_json,
    write_json,
)
from report_agent.application.repositories import RunRepository
from report_agent.domain.artifacts import PublishedArtifact, artifact_download_path
from report_agent.domain.events import EventType
from report_agent.domain.identifiers import RunIdentity
from report_agent.runtime.workspace import TaskWorkspace

SECRET_KEY = re.compile(r"(authorization|api.?key|password|secret|token|credential)", re.I)
logger = logging.getLogger(__name__)


class UploadedMaterial(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    content: bytes


class ToolTrace(BaseModel):
    sequence: int
    tool: str
    status: str
    input: Any = None
    output: Any = None


class ArtifactResult(BaseModel):
    artifact_id: str
    filename: str
    sha256: str
    size: int
    download_url: str
    bucket: str
    object_key: str
    expires_at: str


class RunResult(BaseModel):
    task_id: str
    session_id: str
    run_id: str
    status: str
    assistant_text: str
    trace: list[ToolTrace] = Field(default_factory=list)
    artifacts: list[ArtifactResult] = Field(default_factory=list)
    skill_name: str | None = None
    skill_route: str | None = None


class AcceptedRun(BaseModel):
    """Immediate acknowledgment returned by async submit."""

    task_id: str
    session_id: str
    run_id: str
    status: Literal["running"] = "running"


class RunConflict(ValueError):
    """A stale answer or a concurrent run cannot change an existing task."""


class AgentExecutor(Protocol):
    async def __call__(
        self,
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
    ) -> dict[str, Any]: ...


def _optional_kwargs(fn: Callable[..., Any], **candidates: Any) -> dict[str, Any]:
    """Keep only the keyword arguments ``fn`` actually accepts.

    ``selected_skill`` predates the debug knobs (``model_name``, ``thinking``),
    and executors are pluggable — test doubles and alternate harnesses do not
    all grow the new parameters. Offering what is supported, instead of forcing
    every implementation to change, keeps the older ones working.
    """
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {"selected_skill": candidates.get("selected_skill", "")}
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return dict(candidates)
    return {key: value for key, value in candidates.items() if key in parameters}


@dataclass(slots=True)
class SynchronousRunService:
    workspace_root: Path
    executor: AgentExecutor
    repository: RunRepository
    workspace_max_bytes: int = 2 * 1024 * 1024 * 1024
    max_upload_bytes: int = 100 * 1024 * 1024
    trace_max_chars: int = 12_000
    #: Optional fan-out for the Run Console. When omitted, behaviour is
    #: identical to the pre-console synchronous service.
    event_bus: RunEventBus | None = None
    _background_tasks: set[asyncio.Task[RunResult]] = field(
        default_factory=set, init=False, repr=False
    )
    #: Live background tasks keyed by run id, so the console can cancel a run.
    _run_tasks: dict[str, asyncio.Task[RunResult]] = field(
        default_factory=dict, init=False, repr=False
    )
    _active_tasks: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    #: Per-task event sequence, seeded from the persisted log on first write.
    _task_seq: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _seq_lock: Any = field(default_factory=threading.Lock, init=False, repr=False)

    def delete_conversation(self, task_id: str) -> bool:
        """Persist a sidebar tombstone; keep materials and published artifacts."""
        if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
            raise ValueError("invalid task_id")
        root = self.workspace_root / task_id
        if not root.is_dir() or root.resolve().parent != self.workspace_root.resolve():
            return False
        workspace = TaskWorkspace(root)
        try:
            with execution_lock(workspace, "submission"), execution_lock(workspace):
                if task_id in self._active_tasks:
                    raise RunConflict("会话正在执行，请先中止任务再删除。")
                meta = read_json(workspace, "/workspace/state/conversation-meta.json")
                if not meta.get("deleted_at"):
                    write_json(workspace, "/workspace/state/conversation-meta.json",
                               {**meta, "deleted_at": datetime.now(UTC).isoformat()})
        except ValueError as exc:
            raise RunConflict(str(exc)) from exc
        return True

    def _emit(
        self, identity: RunIdentity, event_type: EventType, payload: dict[str, Any] | None = None
    ) -> None:
        if self.event_bus is not None:
            # Publishing goes through the bus's durability sink, so events that
            # guards emit directly (agent tool stream) are persisted the same way.
            self.event_bus.emit(identity, event_type, payload)

    def _guard_task(
        self, task: asyncio.Task[Any], identity: RunIdentity, workspace: TaskWorkspace
    ) -> None:
        """Guarantee a terminal event even when the *tail* of a run raises.

        ``_execute`` only wraps the executor call. Status computation, artifact
        validation, the conversation append and the DB ``finish`` all run after
        it, outside that ``try``. Any of them raising means **no terminal event
        is emitted**, and the console's SSE stream then waits forever — the run
        looks alive while it is actually dead.

        Doing this in the task callback (rather than re-indenting the whole
        tail) keeps one place responsible for "a run always ends somewhere".
        """
        run_id = identity.run_id

        def _on_done(done: asyncio.Task[Any]) -> None:
            self._run_tasks.pop(run_id, None)
            self._active_tasks.pop(identity.task_id, None)
            if done.cancelled():
                return  # cancellation already reported where it happened
            exc = done.exception()
            if exc is None:
                return
            logger.error(
                "run finished with an unhandled error: run=%s error=%s",
                run_id,
                type(exc).__name__,
                exc_info=exc,
            )
            try:
                self.repository.fail(identity, type(exc).__name__)
            except Exception:  # noqa: BLE001 - reporting must not raise again
                logger.warning("failed to record run failure", exc_info=True)
            try:
                update_interaction(workspace, status="failed", pending_question=None)
            except Exception:  # noqa: BLE001
                logger.warning("failed to record interaction failure", exc_info=True)
            self._emit(
                identity,
                EventType.RUN_FAILED,
                {
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                    "status": "failed",
                },
            )

        task.add_done_callback(_on_done)

    #: Append-only event log next to the other run logs.
    EVENTS_PATH = "logs/events.ndjson"

    def __post_init__(self) -> None:
        if self.event_bus is not None:
            self.event_bus.set_sink(self._persist_event)

    def _persist_event(self, event: Any) -> None:
        """Write the event to disk so a restart does not erase the run's history.

        The bus is in-memory only: after a restart the console could neither
        replay a finished run nor learn its terminal state, and an SSE client
        that reconnected got an empty stream. The log is the source of truth for
        replay; the bus stays for live tailing.

        The sequence is **per task**, not per run: a conversation reuses one
        file across rounds, so a run-scoped sequence restarts at 1 and the
        replay cursor then either re-sends the previous round or silently drops
        the first N events of this one.
        """
        try:
            task_id = str(getattr(event, "task_id", "") or "")
            if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
                return
            path = self.workspace_root / task_id / self.EVENTS_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._seq_lock:
                seq = self._task_seq.get(task_id)
                if seq is None:
                    try:
                        seq = sum(
                            1
                            for line in path.read_text(encoding="utf-8").splitlines()
                            if line.strip()
                        )
                    except FileNotFoundError:
                        seq = 0
                seq += 1
                self._task_seq[task_id] = seq
            frame = {
                "schema_version": event.schema_version,
                "seq": seq,
                "type": event.type.value,
                "occurred_at": event.occurred_at.isoformat(),
                "task_id": event.task_id,
                "session_id": event.session_id,
                "run_id": event.run_id,
                "payload": event.payload,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(frame, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - persistence must never break a run
            logger.warning("failed to persist run event", exc_info=True)

    def replay_events(self, task_id: str) -> list[dict[str, Any]]:
        """Read a task's persisted events (empty when the log is missing)."""
        if not re.fullmatch(r"task_[a-f0-9]{32}", task_id or ""):
            return []
        path = self.workspace_root / task_id / self.EVENTS_PATH
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except Exception:  # noqa: BLE001
            logger.warning("failed to read persisted run events", exc_info=True)
            return []
        frames: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return frames

    async def submit(
        self, message: str, uploads: Sequence[UploadedMaterial], *, selected_skill: str = "",
        task_id: str = "", question_id: str = "", choice_value: str = "",
        institution_workbook: bool | None = None,
        model_name: str = "", thinking: str = "",
    ) -> AcceptedRun:
        root = self.workspace_root / task_id
        if re.fullmatch(r"task_[a-f0-9]{32}", task_id) and (root / "state").is_dir():
            with ExitStack() as locks:
                try:
                    locks.enter_context(execution_lock(TaskWorkspace(root), "submission"))
                except ValueError as exc:
                    raise RunConflict(str(exc)) from exc
                return await self._submit(message, uploads, selected_skill=selected_skill,
                                          task_id=task_id, question_id=question_id, choice_value=choice_value,
                                          institution_workbook=institution_workbook,
                                          model_name=model_name, thinking=thinking)
        return await self._submit(message, uploads, selected_skill=selected_skill,
                                  task_id=task_id, question_id=question_id, choice_value=choice_value,
                                  institution_workbook=institution_workbook,
                                  model_name=model_name, thinking=thinking)

    async def _submit(
        self,
        message: str,
        uploads: Sequence[UploadedMaterial],
        *,
        selected_skill: str = "",
        task_id: str = "",
        question_id: str = "",
        choice_value: str = "",
        institution_workbook: bool | None = None,
        model_name: str = "",
        thinking: str = "",
    ) -> AcceptedRun:
        if task_id in self._active_tasks:
            raise RunConflict("当前对话仍在执行，请等待结束后补充")
        if question_id:
            if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
                raise RunConflict("回答必须关联当前对话")
            question = read_interaction(TaskWorkspace(self.workspace_root / task_id)).get("pending_question")
            if not question or question.get("question_id") != question_id:
                raise RunConflict("这个问题已经回答或已更新，请刷新当前对话")
            answer_text(question, message, choice_value)
        identity, workspace, cleaned = self._prepare(
            message or choice_value, uploads, selected_skill, task_id=task_id
        )
        interaction = read_interaction(workspace)
        question = interaction.get("pending_question")
        if question_id and (not question or question.get("question_id") != question_id):
            raise RunConflict("这个问题已经回答或已更新，请刷新当前对话")
        if question:
            cleaned = answer_text(question, message, choice_value)
            if question.get("gate") == "one_pager_risk":
                update_interaction(workspace, risk_disclosure=risk_disclosure_answer(question, message, choice_value)[1])
            if question.get("gate") == "one_pager_business_type":
                update_interaction(workspace, business_type_selection=business_type_answer(message, choice_value)[1])
            if question.get("gate") in {"cbex_listing", "cbex_project"}:
                update_interaction(workspace, cbex_lookup=cbex_answer(question, message, choice_value)[1])
            if question.get("gate") == "company_registry":
                update_interaction(workspace, registry_lookup=registry_answer(message, choice_value)[1])
            # A clarification always belongs to the skill which asked it.
            selected_skill = str(interaction.get("active_skill") or selected_skill)
            self._emit(identity, EventType.APPROVAL_RESOLVED, {
                "question_id": question.get("question_id"), "answer": message,
            })
        else:
            selected_skill = selected_skill or str(interaction.get("active_skill") or "")
        # The model and the reasoning mode belong to the conversation, not to
        # one message: a follow-up must not silently switch model mid-report.
        model_name = (model_name or "").strip() or str(interaction.get("model_name") or "")
        thinking = (thinking or "").strip() or str(interaction.get("thinking") or "")
        prepare = getattr(self.executor, "prepare_submission", None)
        if prepare is not None:
            prepare(identity, workspace, cleaned,
                    **_optional_kwargs(
                        prepare,
                        selected_skill=selected_skill,
                        question=question,
                        has_uploads=bool(uploads),
                        model_name=model_name,
                        thinking=thinking,
                    ))
        update_interaction(workspace, run_id=identity.run_id, status="running",
                           pending_question=None, continued_from_run_id=interaction.get("run_id"),
                           session_id=identity.session_id, workspace_id=identity.workspace_id,
                           active_skill=selected_skill or interaction.get("active_skill", ""),
                           model_name=model_name, thinking=thinking)
        self.repository.create(identity, cleaned)
        if institution_workbook is not None:
            update_interaction(workspace, institution_workbook=institution_workbook)
        if read_interaction(workspace).get("institution_workbook"):
            try:
                from report_agent.application.institution_workbook.context import request_options
                request_options(workspace, identity.run_id, True)
            except Exception as exc:
                logger.warning("optional workbook request unavailable: %s", type(exc).__name__)
        # Keep an inspectable request snapshot; resumable questions and answers
        # live in interaction.json and conversation.json, never in upload bytes in RAM.
        try:
            workspace.write_text(
                "/workspace/state/pending.json",
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_id": identity.task_id,
                        "run_id": identity.run_id,
                        "message": cleaned,
                        "skill": selected_skill,
                        "upload_names": [upload.filename for upload in uploads],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception:  # noqa: BLE001 - a failed snapshot must not block the run
            pass
        # 记录这一轮用户说了什么，下一次 run 会连同历史一起喂回模型。
        try:
            WorkspaceConversationStore(workspace).append(
                "user", cleaned, run_id=identity.run_id
            )
        except Exception:  # noqa: BLE001 - history must not block the run
            pass
        # 首轮写下对话标题：清掉 localStorage 后，侧栏仍能从沙箱恢复出可读的名字。
        try:
            meta_path = workspace.resolve("/workspace/state/conversation-meta.json")
            if not meta_path.is_file():
                workspace.write_text(
                    "/workspace/state/conversation-meta.json",
                    json.dumps(
                        {
                            "title": cleaned[:60],
                            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        except Exception:  # noqa: BLE001 - metadata must not block the run
            pass
        self._emit(
            identity,
            EventType.RUN_STARTED,
            {
                "run_id": identity.run_id,
                "task_id": identity.task_id,
                "session_id": identity.session_id,
                "skill_hint": selected_skill or "",
            },
        )
        task = asyncio.create_task(
            self._execute(identity, workspace, cleaned, selected_skill=selected_skill,
                          model_name=model_name, thinking=thinking),
            name=f"report-agent-run:{identity.run_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        self._run_tasks[identity.run_id] = task
        self._active_tasks[identity.task_id] = identity.run_id
        self._guard_task(task, identity, workspace)
        return AcceptedRun(
            task_id=identity.task_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
        )

    def cancel(self, run_id: str) -> bool:
        """Cancel an in-flight run. Returns False when it already finished."""
        task = self._run_tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def cancel_task(self, task_id: str) -> bool:
        """Abandon a task that is paused waiting for input.

        A run stopped on an ``ask_user`` question has already finished, so
        :meth:`cancel` returns False for it. Without this the pending question
        survives on disk and every reload re-renders the same card — the user
        presses 中止 and the question comes back.
        """
        root = self.workspace_root / task_id
        if not (root / "state").is_dir():
            return False
        workspace = TaskWorkspace(root)
        interaction = read_interaction(workspace)
        if interaction.get("status") not in {"running", "needs_input", "waiting"}:
            return False
        update_interaction(workspace, status="cancelled", pending_question=None)
        self.repository.fail(  # best effort: the console reads the workspace state
            RunIdentity(
                task_id=task_id,
                session_id=str(interaction.get("session_id") or ""),
                run_id=str(interaction.get("run_id") or ""),
                workspace_id=str(interaction.get("workspace_id") or ""),
            ),
            "CancelledError",
        )
        return True

    async def resume(self, run_id: str, answer: str, question_id: str = "") -> AcceptedRun:
        """Append an answer to the same durable task, including after server restart."""
        record = self.repository.get_run(run_id)
        candidates = ([self.workspace_root / record.task_id] if record else self.workspace_root.glob("task_*"))
        for root in candidates:
            workspace = TaskWorkspace(root, max_bytes=self.workspace_max_bytes)
            question = read_interaction(workspace).get("pending_question")
            if question and question.get("run_id") == run_id:
                return await self.submit(answer, [], task_id=root.name,
                                         question_id=question_id or question["question_id"])
        raise RunConflict("这个问题已经回答或当前没有等待补充的问题")

    async def drain(self) -> None:
        """Await all in-flight background runs (tests / graceful shutdown)."""
        pending = list(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def recover_one_pager_runs(self) -> int:
        """Requeue only opted-in, durably accepted runs after process restart.

        Deployment is single-host/shared-volume; an OS execution lock prevents
        a still-live old worker from entering the same graph concurrently.
        Investment-report workspaces are never inspected or requeued here.
        """
        recovered = 0
        for marker in self.workspace_root.glob("task_*/state/one-pager-execution.json"):
            workspace = TaskWorkspace(marker.parents[1], max_bytes=self.workspace_max_bytes)
            task_id = marker.parents[1].name
            if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
                continue
            try:
                state = execution_state(workspace)
                interaction = read_interaction(workspace)
                pending = read_json(workspace, "/workspace/state/pending.json")
                if not pending:
                    command = read_json(workspace, COMMAND_PATH)
                    pending = {"run_id": command.get("run_id"),
                               "message": command.get("text") or command.get("answer", {}).get("text", "")}
                if not interaction.get("session_id") or not interaction.get("workspace_id"):
                    continue
            except (ValueError, OSError) as exc:
                logger.warning("one-pager recovery skipped: task=%s error=%s", task_id, type(exc).__name__)
                continue  # A broken one-pager must never prevent API/report startup.
            if (interaction.get("status") != "running" or task_id in self._active_tasks
                    or pending.get("run_id") != interaction.get("run_id") or not state):
                continue
            identity = RunIdentity(task_id=task_id, run_id=interaction["run_id"],
                                   session_id=interaction["session_id"], workspace_id=interaction["workspace_id"])
            # A shared-volume deployment must not take over a live process.
            try:
                with execution_lock(workspace):
                    pass
            except ValueError:
                continue
            task = asyncio.create_task(self._execute(identity, workspace, pending.get("message", ""),
                                                      selected_skill="one-pager"))
            self._background_tasks.add(task)
            self._run_tasks[identity.run_id] = task
            self._active_tasks[task_id] = identity.run_id
            task.add_done_callback(self._background_tasks.discard)
            self._guard_task(task, identity, workspace)
            recovered += 1
        return recovered

    def reconcile_interrupted_runs(self) -> int:
        """Mark runs left ``running`` by a process restart as failed.

        One-pager runs are *requeued* by :meth:`recover_one_pager_runs`, so they
        are skipped here. Everything else (investment report, chat) has no
        durable checkpoint to resume from — but leaving it ``running`` forever is
        worse than failing it: the console shows a spinner that never ends and
        ``cancel`` cannot touch a coroutine that no longer exists.
        """
        reconciled = 0
        for marker in self.workspace_root.glob("task_*/state/interaction.json"):
            root = marker.parents[1]
            task_id = root.name
            if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
                continue
            if (root / "state" / "one-pager-execution.json").is_file():
                continue  # handled by recover_one_pager_runs
            if task_id in self._active_tasks:
                continue  # this process owns it
            workspace = TaskWorkspace(root, max_bytes=self.workspace_max_bytes)
            try:
                interaction = read_interaction(workspace)
            except (ValueError, OSError) as exc:
                logger.warning(
                    "interrupted-run reconciliation skipped: task=%s error=%s",
                    task_id, type(exc).__name__,
                )
                continue
            if interaction.get("status") != "running":
                continue
            identity = RunIdentity(
                task_id=task_id,
                run_id=str(interaction.get("run_id") or ""),
                session_id=str(interaction.get("session_id") or ""),
                workspace_id=str(interaction.get("workspace_id") or ""),
            )
            try:
                with execution_lock(workspace):
                    pass
            except ValueError:
                continue  # an old live worker still holds it
            try:
                self.repository.fail(identity, "InterruptedByRestart")
                update_interaction(
                    workspace,
                    status="failed",
                    pending_question=None,
                    assistant_text="服务重启，本轮执行已中断，请重新提交。",
                )
            except Exception:  # noqa: BLE001 - startup must not fail on one task
                logger.warning("failed to reconcile interrupted run: task=%s", task_id, exc_info=True)
                continue
            self._emit(
                identity,
                EventType.RUN_FAILED,
                {
                    "error": "InterruptedByRestart",
                    "message": "服务重启，本轮执行已中断",
                    "status": "failed",
                },
            )
            reconciled += 1
        return reconciled

    async def run(
        self,
        message: str,
        uploads: Sequence[UploadedMaterial],
        *,
        selected_skill: str = "",
    ) -> RunResult:
        identity, workspace, cleaned = self._prepare(message, uploads, selected_skill)
        prepare = getattr(self.executor, "prepare_submission", None)
        if prepare is not None:
            prepare(identity, workspace, cleaned, selected_skill=selected_skill, has_uploads=bool(uploads))
        self.repository.create(identity, cleaned)
        return await self._execute(identity, workspace, cleaned, selected_skill=selected_skill, reraise=True)

    def _prepare(
        self,
        message: str,
        uploads: Sequence[UploadedMaterial],
        selected_skill: str = "",
        *,
        task_id: str = "",
    ) -> tuple[RunIdentity, TaskWorkspace, str]:
        if not message.strip() and not uploads:
            raise ValueError("message or at least one file is required")
        total = sum(len(upload.content) for upload in uploads)
        if total > self.max_upload_bytes:
            raise ValueError(f"upload limit exceeded: {total} > {self.max_upload_bytes}")

        if task_id and not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
            raise ValueError("invalid task_id")
        reused = bool(task_id) and (self.workspace_root / task_id).is_dir()
        if task_id and not reused:
            raise RunConflict("当前对话工作区不存在，请恢复对话后重试")
        if reused:
            # 会话追问：沿用同一个沙箱（材料、证据、报告都还在），只换 run_id。
            identity = RunIdentity.for_task(task_id)
        else:
            identity = RunIdentity.create()
        workspace = TaskWorkspace(
            self.workspace_root / identity.task_id, max_bytes=self.workspace_max_bytes
        )
        if reused:
            if read_json(workspace, "/workspace/state/conversation-meta.json").get("deleted_at"):
                raise RunConflict("该会话已删除，请新建会话。")
            previous = read_interaction(workspace)
            state_path = workspace.resolve("/workspace/state/run-state.json")
            if not previous.get("session_id") and state_path.is_file():
                previous = json.loads(state_path.read_text(encoding="utf-8")).get("identifiers", {})
            identity = RunIdentity(task_id=identity.task_id, run_id=identity.run_id,
                                   session_id=previous.get("session_id") or identity.session_id,
                                   workspace_id=previous.get("workspace_id") or identity.workspace_id)
        # initialize() 幂等：已存在的目录/文件不会被覆盖。
        workspace.initialize()
        start = len(list(workspace.resolve("/workspace/input").iterdir())) + 1
        for index, upload in enumerate(uploads, start=start):
            filename = _safe_filename(upload.filename, index)
            workspace.import_artifact("input", filename, upload.content)
        return identity, workspace, message.strip()

    async def _execute(
        self,
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
        reraise: bool = False,
        model_name: str = "",
        thinking: str = "",
    ) -> RunResult:
        import time

        started = time.monotonic()
        try:
            result = await self.executor(
                identity, workspace, message,
                **_optional_kwargs(
                    self.executor,
                    selected_skill=selected_skill,
                    model_name=model_name,
                    thinking=thinking,
                ),
            )
        except asyncio.CancelledError:
            # The console's stop button cancels the task; report it as a
            # terminal event instead of leaving subscribers hanging.
            self.repository.fail(identity, "CancelledError")
            update_interaction(workspace, status="cancelled", pending_question=None)
            self._run_tasks.pop(identity.run_id, None)
            self._emit(
                identity,
                EventType.RUN_FAILED,
                {"error": "CancelledError", "message": "任务已中止", "status": "cancelled"},
            )
            raise
        except BudgetPaused as exc:
            # 软中断，不是失败：本轮调用次数用完，workspace 原样保留。
            # 用户回一句话就开新一轮，接着当前进度往下做。
            pending = _budget_pause_question(str(exc), identity.run_id)
            update_interaction(
                workspace,
                status="needs_input",
                pending_question=pending,
                assistant_text=pending["question"],
            )
            try:
                WorkspaceConversationStore(workspace).append(
                    "assistant", pending["question"], run_id=identity.run_id
                )
            except Exception:  # noqa: BLE001 - 历史写不进去不影响暂停
                logger.warning("failed to append pause notice", exc_info=True)
            logger.info(
                "METRIC run status=paused reason=budget run_id=%s", identity.run_id
            )
            self._emit(identity, EventType.APPROVAL_REQUIRED, pending)
            if reraise:
                raise
            return RunResult(
                task_id=identity.task_id,
                session_id=identity.session_id,
                run_id=identity.run_id,
                status="needs_input",
                assistant_text=pending["question"],
            )
        except Exception as exc:
            self.repository.fail(identity, type(exc).__name__)
            update_interaction(workspace, status="failed", pending_question=None)
            self._emit(
                identity,
                EventType.RUN_FAILED,
                {
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                    "status": "failed",
                },
            )
            if reraise:
                raise
            logger.exception("background agent run failed: %s", identity.run_id)
            return RunResult(
                task_id=identity.task_id,
                session_id=identity.session_id,
                run_id=identity.run_id,
                status="failed",
                assistant_text="",
            )
        messages = list(result.get("messages") or [])
        model_text = _last_assistant_text(messages)
        trace = _extract_trace(result.get("trace_messages", messages), self.trace_max_chars)
        artifacts = [ArtifactResult.model_validate(item) for item in result.get("artifacts", [])]
        run_skill = str(result.get("skill_name") or selected_skill or "")
        if artifacts:
            status = "completed"
        elif result.get("execution_status"):
            status = "needs_input" if result["execution_status"] == "needs_input" else "failed"
        elif run_skill == "chat":
            # Plain conversation has no deliverable, so finishing the reply is
            # success — it must not turn into an approval card.
            status = "completed"
        elif _has_unresolved_tool_failure(trace):
            status = "failed"
        else:
            status = "needs_input"
        assistant_text = _authoritative_response(
            status=status,
            model_text=model_text,
            artifacts=artifacts,
            trace=trace,
            skill_name=run_skill,
        )
        skill_name = result.get("skill_name")
        skill_route = result.get("skill_route")
        pending_question = (result.get("pending_question") or question_payload(model_text, _extract_ask_user(messages), identity.run_id)) if status == "needs_input" else None
        if pending_question:
            assistant_text = pending_question["question"]
        all_artifacts = {item["artifact_id"]: item for item in read_interaction(workspace).get("artifacts", [])}
        all_artifacts.update({item.artifact_id: item.model_dump(mode="json") for item in artifacts})
        interaction_changes = dict(status=status, active_skill=skill_name or selected_skill,
                                   skill_route=skill_route, pending_question=pending_question,
                                   assistant_text=assistant_text, artifacts=list(all_artifacts.values()))
        checkpointed = bool(execution_state(workspace))
        if not checkpointed:
            update_interaction(workspace, **interaction_changes)
        response = RunResult(
            task_id=identity.task_id,
            session_id=identity.session_id,
            run_id=identity.run_id,
            status=status,
            assistant_text=assistant_text,
            trace=trace,
            artifacts=artifacts,
            skill_name=skill_name,
            skill_route=skill_route,
        )
        finish = (getattr(self.repository, "finish_checkpointed", self.repository.finish)
                  if checkpointed else self.repository.finish)
        finish(
            identity,
            status=response.status,
            assistant_text=response.assistant_text,
            trace=[item.model_dump(mode="json") for item in response.trace],
            artifacts=[PublishedArtifact.model_validate(item.model_dump()) for item in artifacts],
            skill_name=skill_name,
            skill_route=skill_route,
        )
        if checkpointed:
            # Leave an accepted run running until metadata finalization commits;
            # after a crash the graph result can then be reconciled without replay.
            update_interaction(workspace, **interaction_changes)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # 一行可被采集的结构化指标。没有 Prometheus/OTel 时，这是唯一能不靠人
        # 翻日志就统计"成功率 / 耗时 / 失败工具"的东西：grep `METRIC ` 即可。
        logger.info(
            "METRIC run status=%s skill=%s duration_ms=%s artifacts=%s "
            "model_calls=%s failed_tools=%s run_id=%s",
            status,
            run_skill or selected_skill or "-",
            elapsed_ms,
            len(artifacts),
            execution_state(workspace).get("budget", {}).get("model_calls", "-"),
            ",".join(_failed_tool_names(trace)) or "-",
            identity.run_id,
        )
        # 把这一轮模型的最终回复记进对话历史，下一次 run 会连同历史喂回模型。
        # needs_input 时回复本身就是问题文本，同样要记，否则下一轮模型不知道
        # 自己问过什么。
        if status in ("completed", "needs_input"):
            try:
                WorkspaceConversationStore(workspace).append(
                    "assistant", response.assistant_text, run_id=identity.run_id
                )
            except Exception:  # noqa: BLE001 - history must not block the run
                pass
        if status == "completed":
            self._emit(
                identity,
                EventType.RUN_COMPLETED,
                {
                    "status": status,
                    "duration_ms": elapsed_ms,
                    "artifact_count": len(artifacts),
                    "assistant_text": response.assistant_text[:2000],
                },
            )
        elif status == "needs_input":
            self._emit(
                identity,
                EventType.APPROVAL_REQUIRED,
                pending_question,
            )
        else:
            self._emit(
                identity,
                EventType.RUN_FAILED,
                {
                    "status": status,
                    "error": response.assistant_text[:1000],
                    "failed_tools": _failed_tool_names(trace),
                    "duration_ms": elapsed_ms,
                },
            )
            logger.warning(
                "run ended failed: run=%s tools=%s",
                identity.run_id,
                ",".join(_failed_tool_names(trace)) or "（无工具失败，按产物缺失判定）",
            )
        return response


_UPLOAD_PROMPT_HINTS = (
    "请上传",
    "上传您",
    "上传需要",
    "请先上传",
    "上传材料",
    "上传文件",
    "材料文件",
    "支持的格式",
)


def _extract_ask_user(messages: Sequence[Any]) -> dict[str, Any] | None:
    """Return the last ``ask_user`` payload from the tool messages, if any.

    ``ask_user`` carries the question, options and free-text flag the console
    needs to render a question card. It is read from the raw tool content rather
    than the bounded trace so a long option list is never truncated.
    """
    for message in reversed(list(messages)):
        if getattr(message, "type", None) != "tool":
            continue
        tool_name = str(getattr(message, "name", ""))
        if tool_name not in {"ask_user", "query_company_registry", "query_cbex_listing_financials", "detect_one_pager_business_type", "check_one_pager_outline", "render_one_pager"}:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                return None
        elif isinstance(content, dict):
            payload = content
        else:
            return None
        if tool_name != "ask_user" and isinstance(payload, dict):
            payload = payload.get("question_request")
        if isinstance(payload, dict) and payload.get("status") == "needs_user_input":
            return payload
        return None
    return None


def _classify_needs_input(text: str) -> str:
    """Split ``needs_input`` into a plain upload request vs. a real decision.

    An upload prompt is just conversation: the user answers by attaching files
    in the composer. Blocking the composer behind an approval card would make
    the flow unusable, so it is rendered as a normal reply instead.
    """
    normalized = (text or "").strip()
    if not normalized:
        return "confirm"
    if any(hint in normalized for hint in _UPLOAD_PROMPT_HINTS):
        return "upload_prompt"
    return "confirm"


def _safe_filename(value: str, index: int) -> str:
    name = PurePath(value.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        name = f"upload-{index}.bin"
    return f"{index:02d}-{name}"


def _last_assistant_text(messages: Sequence[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
            return json.dumps(content, ensure_ascii=False)
    return ""


def _extract_trace(messages: Sequence[Any], max_chars: int) -> list[ToolTrace]:
    calls: dict[str, ToolTrace] = {}
    ordered: list[ToolTrace] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            trace = ToolTrace(
                sequence=len(ordered) + 1,
                tool=str(call.get("name", "unknown")),
                status="started",
                input=_bounded(_redact(call.get("args", {})), max_chars),
            )
            calls[str(call.get("id", ""))] = trace
            ordered.append(trace)
        if getattr(message, "type", None) == "tool":
            call_id = str(getattr(message, "tool_call_id", ""))
            matched_trace = calls.get(call_id)
            if matched_trace is None:
                matched_trace = ToolTrace(
                    sequence=len(ordered) + 1,
                    tool=str(getattr(message, "name", "unknown")),
                    status="completed",
                )
                ordered.append(matched_trace)
            matched_trace.status = (
                "error" if getattr(message, "status", None) == "error" else "completed"
            )
            matched_trace.output = _bounded(_redact(getattr(message, "content", None)), max_chars)
    return ordered


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


#: Business-level failure statuses a tool can return **inside a successful
#: ToolMessage**. ``ToolMessage.status == "error"`` only covers tools that
#: *raised*; a tool that catches its own error and answers ``{"status":"error"}``
#: looks like a normal completion, and the run then ends as ``needs_input`` —
#: the user gets a question card for what was actually a failure.
_FAILED_TOOL_STATUSES = frozenset(
    {"error", "failed", "invalid_arguments", "invalid_outline", "invalid_content", "rejected"}
)

#: 工商查询失败或为空是可选闸门，应由名称卡片承接。工具正常返回时不把整轮判失败；
#: 工具自己抛错（status == error）仍然算失败。
_OPTIONAL_GATE_TOOLS = frozenset({"query_company_registry"})


def _payload_status(output: Any) -> str:
    """The ``status`` a tool reported in its own JSON body, if any."""
    payload = output
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped.startswith("{"):
            return ""
        try:
            payload = json.loads(stripped)
        except (ValueError, TypeError):
            return ""
    if isinstance(payload, dict):
        return str(payload.get("status") or "")
    return ""


def _is_blocking_tool_failure(item: ToolTrace) -> bool:
    if item.tool in _OPTIONAL_GATE_TOOLS and item.status != "error":
        return False
    if item.status == "error":
        return True
    return _payload_status(item.output) in _FAILED_TOOL_STATUSES


def _latest_tool_traces(trace: Sequence[ToolTrace]) -> dict[str, ToolTrace]:
    latest_by_tool: dict[str, ToolTrace] = {}
    for item in trace:
        latest_by_tool[item.tool] = item
    return latest_by_tool


def _has_unresolved_tool_failure(trace: Sequence[ToolTrace]) -> bool:
    return any(_is_blocking_tool_failure(item) for item in _latest_tool_traces(trace).values())


def _failed_tool_names(trace: Sequence[ToolTrace]) -> list[str]:
    """Tools whose **latest** call failed, for the failure event and the log."""
    return sorted(
        name
        for name, item in _latest_tool_traces(trace).items()
        if _is_blocking_tool_failure(item)
    )


def _authoritative_response(
    *,
    status: str,
    model_text: str,
    artifacts: Sequence[ArtifactResult],
    trace: Sequence[ToolTrace],
    skill_name: str = "",
) -> str:
    """Build delivery claims only from service-owned publication records."""
    if status == "completed":
        if skill_name == "chat" and not artifacts:
            # Plain conversation: the model reply *is* the deliverable.
            return model_text
        lines = ["报告已成功发布。"]
        for artifact in artifacts:
            lines.extend(
                [
                    f"文件名：{artifact.filename}",
                    f"Artifact ID：{artifact.artifact_id}",
                    f"下载链接：{artifact_download_path(artifact.artifact_id)}",
                    f"SHA-256：{artifact.sha256}",
                ]
            )
        return "\n".join(lines)
    if status == "failed":
        latest: dict[str, str] = {}
        for item in trace:
            latest[item.tool] = item.status
        failed_tools = [tool for tool, tool_status in latest.items() if tool_status == "error"]
        suffix = f"失败环节：{', '.join(failed_tools)}。" if failed_tools else ""
        return f"报告未发布，当前没有有效下载产物。{suffix}请根据真实失败信息修复后重试。"
    return model_text


def _bounded(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "…[truncated]"
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(serialized) <= max_chars else serialized[:max_chars] + "…[truncated]"


def _budget_pause_question(reason: str, run_id: str) -> dict[str, Any]:
    """本轮调用次数用完时的续跑提示。

    做成 ``needs_input`` 形状，前端会渲染成一张卡片；用户回一句话就开新一轮，
    带着 workspace 里已有的材料与进度继续，不会重来。
    """
    return {
        "status": "needs_user_input",
        "gate": "turn_limit",
        "kind": "text",
        "question": "本轮已用完模型调用额度，任务已暂停。回复任意内容（例如「继续」）即可接着执行。",
        "context": (
            "材料、证据和已经写好的内容都保留在工作区，继续时从当前进度往下做，"
            "不会重新开始。"
        ),
        "options": [],
        "allow_free_text": True,
        "run_id": run_id,
        "reason": reason,
    }