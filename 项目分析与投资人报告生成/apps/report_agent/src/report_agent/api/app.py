"""FastAPI application and developer conversation page (async submit + poll)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.resources import files
import tempfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from report_agent.application.bootstrap import SKILL_NAMES
from report_agent.application.conversation_store import WorkspaceConversationStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.institution_workbook.context import ContextUnavailable
from report_agent.application.institution_workbook.service import InstitutionWorkbookService
from report_agent.application.interactions import (
    question_payload,
    read_interaction,
    update_interaction,
)
from report_agent.application.one_pager_execution import execution_state
from report_agent.application.runs import RunConflict, SynchronousRunService, UploadedMaterial
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.infrastructure.artifacts import MinioArtifactService
from report_agent.infrastructure.artifacts.minio import DOCX_CONTENT_TYPE, XLSX_CONTENT_TYPE
from report_agent.runtime.workspace import TaskWorkspace

AGENT_LOG_RELATIVE = Path("logs") / "agent.ndjson"
# Nginx only proxies this opaque prefix. The ASGI middleware strips it before
# routing so /v1/ai-service/console/ and /api/ work under the prefix without
# dual mounts. Pages then rewrite the address bar to the public path.
INVESTMENT_PAGE_PREFIX = "/m4Kp9Qx2Lv7Nc1Rd8Ws3Tf6Yb0Hz"
INVESTMENT_PUBLIC_PATH = "/v1/ai-service/investment"
INVESTMENT_PAGE_PATH = f"{INVESTMENT_PAGE_PREFIX}{INVESTMENT_PUBLIC_PATH}"
CONSOLE_PUBLIC_PATH = "/v1/ai-service/console/"
CONSOLE_PAGE_PATH = f"{INVESTMENT_PAGE_PREFIX}{CONSOLE_PUBLIC_PATH}"
_SCOPE_ENCRYPTED_PREFIX = "bjs_encrypted_prefix"
logger = logging.getLogger(__name__)
TITLE_ENDPOINT_TIMEOUT_SECONDS = 60.0
TITLE_FAILURE_COOLDOWN_SECONDS = 300.0


def _content_disposition(filename: str) -> str:
    """Build a download header both modern and legacy browsers understand.

    ``filename*=UTF-8''`` (RFC 5987) is the only form that carries a Chinese
    name, but browsers that only know the plain ``filename`` parameter — and
    some proxy browsers — drop it and save a garbled name instead. Sending
    both is the interoperable answer: the ASCII fallback keeps the extension
    and whatever survives transliteration, the starred form keeps the real
    name for browsers that support it.
    """
    quoted = quote(filename)
    stem, dot, extension = filename.rpartition(".")
    ascii_stem = stem.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_stem:
        ascii_stem = "report"
    ascii_name = f"{ascii_stem}.{extension}" if dot else ascii_stem
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quoted}"
    )

#: Independent Run Console shipped in ``<repo>/frontend``.
#:
#: The console is deliberately outside the Python package: it is plain static
#: files with no build step, so it can be opened directly during design work
#: and served from this app in deployed environments. Override the location
#: with ``REPORT_AGENT_FRONTEND_DIR`` when the package is installed without
#: the repository checkout.
_FRONTEND_DIRNAME = "frontend"


class _EncryptedPrefixMiddleware:
    """Strip ``INVESTMENT_PAGE_PREFIX`` so one set of routes serves both local
    ``/v1/ai-service/console/`` and the nginx-proxied encrypted URL.
    """

    def __init__(self, app, prefix: str = INVESTMENT_PAGE_PREFIX) -> None:
        self.app = app
        self.prefix = prefix.rstrip("/") or "/"

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix) :] or "/"
                scope[_SCOPE_ENCRYPTED_PREFIX] = True
        await self.app(scope, receive, send)


def _came_via_encrypted_prefix(request: Request) -> bool:
    return bool(request.scope.get(_SCOPE_ENCRYPTED_PREFIX))


def _resolve_frontend_dir() -> Path | None:
    """Return the Run Console directory, or ``None`` when it is not installed.

    Resolution order:
    1. ``REPORT_AGENT_FRONTEND_DIR`` (explicit override, wins always).
    2. ``<repo>/frontend`` derived from this file's location.
    3. ``<cwd>/frontend`` — covers editable installs started from the repo
       root and containers that mount the checkout at a different depth.
    """
    override = os.environ.get("REPORT_AGENT_FRONTEND_DIR")
    if override:
        candidate = Path(override).expanduser()
        return candidate if (candidate / "index.html").is_file() else None
    # src/report_agent/api/app.py -> parents[5] is the repository root.
    candidates = [
        Path(__file__).resolve().parents[5] / _FRONTEND_DIRNAME,
        Path.cwd() / _FRONTEND_DIRNAME,
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


# Limits for URL-based material downloads.
_URL_DOWNLOAD_TIMEOUT = 30.0
_URL_DOWNLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100 MB per file


async def _download_url_material(url: str) -> UploadedMaterial:
    """Download a file from *url* and return an :class:`UploadedMaterial`."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=422,
            detail=f"unsupported URL scheme '{parsed.scheme}': only http/https are allowed",
        )
    filename = unquote(Path(parsed.path).name) or "url-download.bin"
    try:
        async with httpx.AsyncClient(timeout=_URL_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to download '{url}': HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to download '{url}': {exc.__class__.__name__}",
        ) from exc
    content = response.content
    if len(content) > _URL_DOWNLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file from '{url}' exceeds the {_URL_DOWNLOAD_MAX_BYTES // (1024 * 1024)} MB limit",
        )
    return UploadedMaterial(filename=filename, content=content)


#: Candidate encodings for multipart filenames, most likely first.
#
# RFC 7578 defines ``filename`` as raw bytes, so parsers map them through
# latin-1, which is lossless but preserves whatever the client actually sent.
# Clients vary: browsers and the dev UI send UTF-8, while curl under MSYS/Git
# Bash sends the filesystem name in the console code page (cp936/GBK on this
# machine). Recovering the real name therefore means walking the candidates —
# UTF-8 first so correctly-encoded clients round-trip untouched, then
# GB18030 (a superset of GBK) for the legacy Chinese locale.
_FILENAME_ENCODINGS: tuple[str, ...] = ("utf-8", "gb18030")


def decode_multipart_filename(filename: str | None) -> str | None:
    """Recover a filename that a multipart parser decoded as latin-1.

    Returns ``filename`` unchanged when it is already correct (ASCII, or any
    name containing characters outside latin-1, which could not have come
    from a latin-1 header decode).
    """
    if not filename:
        return filename
    try:
        raw = filename.encode("latin-1")
    except UnicodeEncodeError:
        return filename
    for encoding in _FILENAME_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return filename


async def _collect_uploads(
    files_: list[UploadFile] | None,
    urls: str,
) -> list[UploadedMaterial]:
    uploads: list[UploadedMaterial] = []
    for upload in files_ or []:
        uploads.append(
            UploadedMaterial(
                filename=decode_multipart_filename(upload.filename) or "upload.bin",
                content=await upload.read(),
            )
        )
    for raw_url in urls.splitlines():
        url = raw_url.strip()
        if not url:
            continue
        uploads.append(await _download_url_material(url))
    return uploads


#: LibreOffice 能转的格式——预览统一走「转 PDF」，比前端各自渲染稳得多。
_OFFICE_EXTENSIONS = (
    ".doc", ".docx", ".rtf", ".odt",
    ".ppt", ".pptx", ".odp",
    ".xls", ".xlsx", ".ods", ".csv",
)
#: 表格转 PDF 用横向，纵向会把宽表切得没法看。
_SPREADSHEET_EXTENSIONS = (".xls", ".xlsx", ".ods", ".csv")


def _preview_cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "report-agent-preview"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _office_to_pdf(filename: str, payload: bytes) -> bytes:
    """把 Office 文件转成 PDF，带磁盘缓存。

    转换一次要 5~18 秒（xlsx 更慢）。同一个产物会被反复打开，缓存按内容 sha256
    命中，避免每次点预览都等一遍。
    """
    suffix = Path(filename).suffix.lower()
    digest = hashlib.sha256(payload).hexdigest()[:32]
    cached = _preview_cache_dir() / f"{digest}{suffix}.pdf"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached.read_bytes()

    gotenberg = os.environ.get("GOTENBERG_URL", "").strip()
    if not gotenberg:
        raise RuntimeError("GOTENBERG_URL 未配置，无法转换预览")
    data = {"landscape": "true"} if suffix in _SPREADSHEET_EXTENSIONS else {}
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(
            f"{gotenberg.rstrip('/')}/forms/libreoffice/convert",
            files={"files": (filename, payload)},
            data=data,
        )
        response.raise_for_status()
        content = response.content
    try:
        cached.write_bytes(content)
    except OSError:
        pass
    return content

def create_app(
    run_service: SynchronousRunService,
    *,
    dev_ui_enabled: bool,
    artifact_service: MinioArtifactService | None = None,
    event_bus: RunEventBus | None = None,
    title_suggester: Callable[[str], Awaitable[str]] | None = None,
    institution_workbook_service: InstitutionWorkbookService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_service.recover_one_pager_runs()
        # Runs without a durable checkpoint cannot be resumed; marking them
        # failed at startup is the only way out of a "running" state that no
        # coroutine owns any more.
        reconcile = getattr(run_service, "reconcile_interrupted_runs", None)
        if callable(reconcile):
            orphaned = reconcile()
            if orphaned:
                logger.warning("reconciled %d interrupted run(s) as failed", orphaned)
        yield
        closing = []
        for task_id, run_id in tuple(run_service._active_tasks.items()):
            if (run_service.workspace_root / task_id / "state/one-pager-execution.json").is_file():
                task = run_service._run_tasks.get(run_id)
                if task is not None:
                    task.cancel()
                    closing.append(task)
        if closing:
            await asyncio.gather(*closing, return_exceptions=True)

    app = FastAPI(title="BJS Report Agent", version="0.1.0", lifespan=lifespan)
    title_in_progress = False
    event_stream_id = uuid4().hex
    title_retry_after = 0.0
    if dev_ui_enabled:
        # The developer page may be opened directly as file:// during local
        # testing. Keep this narrow and only enable it for the dev API.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["null", "http://127.0.0.1:8000", "http://localhost:8000"],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        # Surface console availability so a stale process or a missing
        # frontend directory is diagnosable without reading the source.
        resolved = _resolve_frontend_dir()
        return {
            "status": "ok",
            "console": "ok" if resolved is not None else "missing",
            "console_dir": str(resolved) if resolved is not None else "",
        }

    def _developer_page_html() -> str:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer UI is disabled")
        return files("report_agent.api.static").joinpath("dev.html").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Run Console — independent static UI served on the same port.
    #
    # Entry is CONSOLE_PAGE_PATH (opaque prefix + public path). Middleware
    # strips the prefix before routing. The HTML page then replaceState's the
    # address bar to the bare public path — same trick as the old investment
    # page — so a copied address-bar URL cannot re-enter. Assets stay on the
    # public path so relative CSS/JS still load after replaceState.
    # Not gated by ``dev_ui_enabled``.
    # ------------------------------------------------------------------
    frontend_dir = _resolve_frontend_dir()
    if frontend_dir is not None and (frontend_dir / "assets").is_dir():
        app.mount(
            f"{CONSOLE_PUBLIC_PATH.rstrip('/')}/assets",
            StaticFiles(directory=frontend_dir / "assets"),
            name="console-assets",
        )

    def _console_index_html() -> str:
        resolved = _resolve_frontend_dir()
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Run Console not installed: set REPORT_AGENT_FRONTEND_DIR "
                    "to the repository's frontend/ directory"
                ),
            )
        return (resolved / "index.html").read_text(encoding="utf-8")

    def _require_encrypted_prefix(request: Request) -> None:
        # Bare /v1/ai-service/console/ (and /console/) must 404 so a copied
        # address-bar URL after replaceState cannot reopen the workbench.
        if not _came_via_encrypted_prefix(request):
            raise HTTPException(status_code=404, detail="not found")

    def _prefixed_redirect(request: Request, public_path: str) -> RedirectResponse:
        target = (
            f"{INVESTMENT_PAGE_PREFIX}{public_path}"
            if _came_via_encrypted_prefix(request)
            else public_path
        )
        return RedirectResponse(url=target, status_code=307)

    @app.get("/v1/ai-service/console")
    async def console_root(request: Request) -> RedirectResponse:
        _require_encrypted_prefix(request)
        return _prefixed_redirect(request, CONSOLE_PUBLIC_PATH)

    @app.get("/v1/ai-service/console/", response_class=HTMLResponse)
    async def console_page(request: Request) -> str:
        _require_encrypted_prefix(request)
        return _console_index_html()

    @app.get("/console")
    @app.get("/console/")
    async def console_legacy(request: Request) -> RedirectResponse:
        _require_encrypted_prefix(request)
        return _prefixed_redirect(request, CONSOLE_PUBLIC_PATH)

    @app.get("/dev", response_class=HTMLResponse)
    async def developer_page() -> str:
        return _developer_page_html()

    @app.get(INVESTMENT_PUBLIC_PATH)
    async def investment_page(request: Request) -> RedirectResponse:
        # Old encrypted bookmark → console. Bare public path (no prefix) 404s
        # so a copied address bar URL still cannot re-enter.
        if not _came_via_encrypted_prefix(request):
            raise HTTPException(status_code=404, detail="not found")
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer UI is disabled")
        return _prefixed_redirect(request, CONSOLE_PUBLIC_PATH)

    @app.post("/api/dev/runs")
    async def create_run(
        message: Annotated[str, Form()] = "",
        files_: Annotated[list[UploadFile] | None, File()] = None,
        urls: Annotated[str, Form()] = "",
        selected_skill: Annotated[str, Form()] = "",
        task_id: Annotated[str, Form()] = "",
        question_id: Annotated[str, Form()] = "",
        choice_value: Annotated[str, Form()] = "",
        institution_workbook: Annotated[bool | None, Form()] = None,
        model_name: Annotated[str, Form()] = "",
        thinking: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer API is disabled")
        cleaned_skill = (selected_skill or "").strip()
        if cleaned_skill and cleaned_skill not in SKILL_NAMES:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "UNKNOWN_SKILL",
                    "message": f"selected_skill {cleaned_skill!r} is not a known skill",
                    "allowed": sorted(SKILL_NAMES),
                },
            )
        uploads = await _collect_uploads(files_, urls)
        try:
            accepted = await run_service.submit(
                message, uploads, selected_skill=cleaned_skill,
                task_id=(task_id or "").strip(),
                question_id=question_id.strip(),
                choice_value=choice_value.strip(),
                institution_workbook=(institution_workbook if institution_workbook_service is not None
                    and institution_workbook_service.settings.institution_workbook.enabled else False),
                # Debug-only overrides. An unknown model name falls back to the
                # configured default inside the executor rather than failing
                # the submission.
                model_name=(model_name or "").strip(),
                thinking=(thinking or "").strip(),
            )
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Agent run submit failed")
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "AGENT_RUN_SUBMIT_FAILED",
                    "message": "Failed to accept agent run; inspect the server log.",
                    "error_type": type(exc).__name__,
                },
            ) from exc
        return JSONResponse(status_code=202, content=accepted.model_dump(mode="json"))

    @app.get("/api/models")
    async def list_models() -> dict:
        """Models and reasoning modes the console may offer.

        Debugging aid: an operator can compare a model with and without
        reasoning without redeploying. ``LLM_MODEL_CANDIDATES`` is a
        comma-separated list; the configured ``LLM_MODEL`` always comes first
        so the default is never missing from the dropdown.
        """
        default = os.environ.get("LLM_MODEL", "").strip()
        raw = os.environ.get("LLM_MODEL_CANDIDATES", "").strip()
        candidates = [item.strip() for item in raw.split(",") if item.strip()]
        if default and default not in candidates:
            candidates.insert(0, default)
        return {
            "default": default,
            "models": [
                {"id": name, "label": name, "is_default": name == default}
                for name in candidates
            ],
            "thinking_modes": ["auto", "on", "off"],
            "default_thinking": os.environ.get("LLM_THINKING_MODE", "auto").strip() or "auto",
            "thinking_adapter": os.environ.get("LLM_THINKING_ADAPTER", "auto").strip() or "auto",
        }

    @app.get("/api/features")
    async def features() -> dict:
        enabled = bool(institution_workbook_service and institution_workbook_service.settings.institution_workbook.enabled)
        online = False
        if enabled:
            try:
                path = Path(run_service.workspace_root)/".institution-worker/state/heartbeat.json"
                timestamp = json.loads(path.read_text(encoding="utf-8"))["at"]
                online = (datetime.now(UTC)-datetime.fromisoformat(timestamp)).total_seconds()<20
            except Exception:
                pass
        return {"institution_workbook":{"enabled":enabled,"worker_online":online}}

    @app.get("/api/tasks/{task_id}/auxiliary-jobs")
    async def auxiliary_jobs(task_id: str) -> dict:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404)
        if institution_workbook_service is None or not institution_workbook_service.settings.institution_workbook.enabled:
            return {"enabled":False,"jobs":[],"artifacts":[]}
        try:
            jobs = await asyncio.to_thread(institution_workbook_service.list_jobs,task_id)
            artifacts = []
            for job in jobs:
                if job.get("artifact_id"):
                    artifact = await asyncio.to_thread(run_service.repository.get_artifact,job["artifact_id"])
                    if artifact:
                        artifacts.append(artifact.model_dump(mode="json"))
            return {"enabled":True,"jobs":jobs,"artifacts":artifacts}
        except Exception:
            return {"enabled":True,"unavailable":True,"reason":"附件服务暂不可用，原报告不受影响。","jobs":[],"artifacts":[]}

    @app.post("/api/tasks/{task_id}/institution-workbook")
    async def institution_workbook_job(task_id: str, body: dict) -> JSONResponse:
        if not dev_ui_enabled or institution_workbook_service is None:
            raise HTTPException(status_code=404)
        try:
            result = await institution_workbook_service.enqueue_manual(task_id,body)
        except ContextUnavailable as exc:
            raise HTTPException(status_code=422,detail=str(exc)) from None
        except TimeoutError:
            raise HTTPException(status_code=503,detail="附件上下文校验超时，请稍后重试。") from None
        except Exception as exc:
            logger.warning("institution workbook enqueue failed: task=%s type=%s", task_id, type(exc).__name__)
            raise HTTPException(status_code=503,detail="附件请求暂不可用，请稍后重试；原报告不受影响。") from None
        return JSONResponse(status_code=202,content=result)

    @app.post("/api/tasks/{task_id}/auxiliary-jobs/{job_id}/cancel")
    async def cancel_auxiliary_job(task_id: str, job_id: str) -> dict:
        if not dev_ui_enabled or institution_workbook_service is None:
            raise HTTPException(status_code=404)
        try:
            cancelled = await asyncio.to_thread(institution_workbook_service.jobs.cancel,task_id,job_id)
            jobs = await asyncio.to_thread(institution_workbook_service.list_jobs, task_id)
        except Exception:
            raise HTTPException(status_code=503,detail="附件取消暂不可用") from None
        return {"cancelled":cancelled,"jobs":jobs}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        record = run_service.repository.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        if artifact_service is not None:
            record = record.model_copy(
                update={
                    "artifacts": [
                        artifact_service.refresh_download(artifact) for artifact in record.artifacts
                    ]
                }
            )
        return record.model_dump(mode="json")

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        record = run_service.repository.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="task not found")
        return record.model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/state")
    async def get_task_state(task_id: str) -> dict:
        import re
        if not re.fullmatch(r"task_[a-f0-9]{32}", task_id):
            raise HTTPException(status_code=404, detail="task not found")
        root = Path(run_service.workspace_root) / task_id
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="task not found")
        workspace = TaskWorkspace(root)
        snapshot = read_interaction(workspace)
        # 上下文占用：轮次限制移除后，这是唯一的自动管理依据，界面要能看到
        # "离压缩还有多远"。
        try:
            usage = json.loads(
                workspace.resolve("/workspace/state/context-usage.json").read_text(encoding="utf-8")
            )
            if isinstance(usage, dict):
                snapshot["context_usage"] = usage
        except Exception:  # noqa: BLE001 - 没有占用记录是正常的（首轮/旧任务）
            pass
        execution = execution_state(workspace)
        if execution:
            execution["event_stream_id"] = event_stream_id
            snapshot["execution"] = execution
            if execution.get("pending_question") and snapshot.get("status") != "running":
                snapshot.update(status="needs_input", pending_question=execution["pending_question"])
        if not snapshot:
            task = run_service.repository.get_task(task_id)
            record = run_service.repository.get_run(task.run_ids[-1]) if task and task.run_ids else None
            if record:
                snapshot = {"run_id": record.run_id, "status": record.status,
                            "active_skill": record.skill_name, "assistant_text": record.assistant_text,
                            "artifacts": [a.model_dump(mode="json") for a in record.artifacts],
                            "pending_question": question_payload(record.assistant_text, None, record.run_id)
                            if record.status == "needs_input" else None}
                update_interaction(workspace, **snapshot)
        if snapshot.get("status") == "running" and task_id not in run_service._active_tasks:
            if execution:
                await run_service.recover_one_pager_runs()
            if task_id not in run_service._active_tasks:
                snapshot.update(status="failed", assistant_text="服务已重启，请在当前对话中重试以继续。")
        # Legacy task snapshots may contain only their latest run's artifacts.
        # Include every published artifact owned by this task, never a global preview.
        artifacts = {item["artifact_id"]: item for item in snapshot.get("artifacts", [])}
        stored_task = run_service.repository.get_task(task_id)
        for artifact_id in stored_task.artifact_ids if stored_task else []:
            artifact = run_service.repository.get_artifact(artifact_id)
            if artifact is not None:
                artifacts[artifact_id] = artifact.model_dump(mode="json")
        snapshot["artifacts"] = list(artifacts.values())
        return {**snapshot, "task_id": task_id,
                "turns": WorkspaceConversationStore(workspace).turns(),
                "last_seq": event_bus.cursor(snapshot.get("run_id", "")) if event_bus else 0}

    @app.get("/api/dev/runs/{task_id}/logs")
    async def get_run_logs(task_id: str) -> dict:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer API is disabled")
        log_path = Path(run_service.workspace_root) / task_id / AGENT_LOG_RELATIVE
        if not log_path.is_file():
            raise HTTPException(status_code=404, detail="agent log not found")
        entries: list[dict] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"_unparsed": line})
        return {"task_id": task_id, "path": str(log_path), "entries": entries}

    @app.get("/api/runs/{run_id}/events")
    async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
        """Server-sent events for the Run Console.

        Replays the in-memory buffer from the start, then follows new events
        until the run reaches a terminal state or the client disconnects.

        When the buffer is empty — the usual case after a server restart, since
        the bus is in-memory — the persisted event log is replayed instead. The
        console then still shows what happened, and a lapsed client can resume.
        """
        if event_bus is None:
            raise HTTPException(status_code=404, detail="event stream is not enabled")

        if event_bus.cursor(run_id) == 0:
            record = run_service.repository.get_run(run_id)
            replayer = getattr(run_service, "replay_events", None)
            frames = replayer(record.task_id) if record is not None and callable(replayer) else []
            # A task's log holds every round of the conversation: replaying it
            # without this filter sends the *previous* run's `run.completed`
            # (and its assistant text) to a client that just started a new run.
            frames = [frame for frame in frames if frame.get("run_id") == run_id]
            if frames:
                try:
                    cursor = max(
                        0,
                        int(
                            request.headers.get("last-event-id")
                            or request.query_params.get("after_seq")
                            or 0
                        ),
                    )
                except ValueError:
                    cursor = 0
                highest = max(int(frame.get("seq") or 0) for frame in frames)
                if cursor >= highest:
                    # The client's cursor came from a different sequence base
                    # (live stream indexes the in-memory buffer). Replaying from
                    # zero is safer than silently returning nothing.
                    cursor = 0

                async def replay():
                    for frame in frames:
                        if int(frame.get("seq") or 0) <= cursor:
                            continue
                        yield f"id: {frame.get('seq')}\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n"

                return StreamingResponse(
                    replay(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache, no-transform",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

        async def generate():
            try:
                cursor = max(0, int(request.headers.get("last-event-id") or request.query_params.get("after_seq") or 0))
            except ValueError:
                cursor = 0
            heartbeat = asyncio.get_running_loop().time()
            try:
                while True:
                    signal = event_bus.signal_for(run_id)
                    signal.clear()
                    for event in event_bus.since(run_id, cursor):
                        cursor += 1
                        frame = {
                            "schema_version": event.schema_version,
                            "seq": cursor,
                            "type": event.type.value,
                            "occurred_at": event.occurred_at.isoformat(),
                            "task_id": event.task_id,
                            "session_id": event.session_id,
                            "run_id": event.run_id,
                            "payload": event.payload,
                        }
                        yield f"id: {cursor}\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n"
                    if event_bus.is_terminal(run_id):
                        break
                    if await request.is_disconnected():
                        return
                    if asyncio.get_running_loop().time() - heartbeat >= 15:
                        yield ": heartbeat\n\n"
                        heartbeat = asyncio.get_running_loop().time()
                    try:
                        await asyncio.wait_for(signal.wait(), timeout=1.0)
                    except TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str, body: dict) -> JSONResponse:
        """Replay a ``needs_input`` run with the user's answer.

        The synchronous main chain has no durable checkpoint yet, so this
        starts a *new* run carrying the original request plus the answer and
        returns its identifiers. Subscribe to the new run id for events.
        """
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer API is disabled")
        answer = str(body.get("answer") or "").strip()
        if not answer:
            raise HTTPException(status_code=422, detail="answer is required")
        try:
            accepted = await run_service.resume(run_id, answer, str(body.get("question_id") or body.get("approval_id") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(status_code=202, content=accepted.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> JSONResponse:
        """Cancel an in-flight run, or abandon a task paused on a question."""
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer API is disabled")
        cancelled = False
        cancel = getattr(run_service, "cancel", None)
        if callable(cancel):
            cancelled = bool(cancel(run_id))
        if not cancelled:
            # A run stopped on ``ask_user`` has already finished, so ``cancel``
            # returns False. Drop the pending question instead — otherwise the
            # console reloads the card the user just dismissed.
            record = run_service.repository.get_run(run_id)
            abandon = getattr(run_service, "cancel_task", None)
            if record is not None and callable(abandon):
                cancelled = bool(abandon(record.task_id))
        return JSONResponse(status_code=200, content={"cancelled": cancelled})

    @app.post("/api/conversations/title")
    async def suggest_conversation_title_endpoint(body: dict) -> dict:
        """Generate a short title for a new conversation from its first message."""
        nonlocal title_in_progress, title_retry_after
        message = str(body.get("message") or "").strip()
        clock = asyncio.get_running_loop()
        if title_suggester is None or not message or title_in_progress or clock.time() < title_retry_after:
            return {"title": ""}
        title_in_progress = True
        try:
            title = await asyncio.wait_for(title_suggester(message), timeout=TITLE_ENDPOINT_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.info("conversation title unavailable (%s); using message title", type(exc).__name__)
            title = ""
        finally:
            title_in_progress = False
        if not title:
            title_retry_after = clock.time() + TITLE_FAILURE_COOLDOWN_SECONDS
        return {"title": title or ""}

    def _resolve_task_input(task_id: str, filename: str) -> Path:
        """Resolve an uploaded file under ``{workspace}/task/input``."""
        workspace_root = getattr(run_service, "workspace_root", None)
        if workspace_root is None:
            raise HTTPException(status_code=404, detail="workspace unavailable")
        input_dir = Path(workspace_root) / task_id / "input"
        path = input_dir / filename
        if not path.is_file() and input_dir.is_dir():
            # The runner stores uploads with a numeric prefix (``01-<name>``),
            # while the console only knows the original filename.
            matches = [p for p in input_dir.iterdir() if p.is_file() and p.name.endswith(filename)]
            if not matches:
                matches = [p for p in input_dir.iterdir() if p.is_file() and filename in p.name]
            if matches:
                path = sorted(matches)[0]
        if not path.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return path

    @app.get("/api/tasks/{task_id}/files/{filename}")
    async def download_task_file(task_id: str, filename: str):
        """Serve the original uploaded file.

        The console used ``URL.createObjectURL`` before the run was accepted;
        those blob URLs die on reload. Re-pointing the attachment chip at this
        route makes uploaded material readable after a restart.
        """
        return FileResponse(_resolve_task_input(task_id, filename))

    @app.get("/api/tasks/{task_id}/files/{filename}/preview")
    async def preview_task_file(task_id: str, filename: str):
        """Serve an uploaded input file for inline preview.

        Browsers render neither Office documents nor (reliably) spreadsheets, so
        everything LibreOffice understands is converted to PDF first. PDFs pass
        through untouched.
        """
        path = _resolve_task_input(task_id, filename)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return FileResponse(path)
        if suffix in _OFFICE_EXTENSIONS:
            try:
                pdf = await _office_to_pdf(path.name, path.read_bytes())
                return Response(content=pdf, media_type="application/pdf")
            except Exception:
                logger.warning(
                    "office preview conversion failed for %s; serving original",
                    path, exc_info=True,
                )
        return FileResponse(path)

    @app.delete("/api/conversations/{task_id}")
    async def delete_conversation(task_id: str) -> dict:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer API is disabled")
        try:
            deleted = run_service.delete_conversation(task_id)
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError:
            logger.exception("conversation deletion failed")
            raise HTTPException(status_code=503, detail="删除未成功，请稍后重试。") from None
        if not deleted:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {"deleted": True, "task_id": task_id}

    @app.get("/api/conversations")
    async def list_conversations(limit: int = 100) -> dict:
        """List recoverable sandboxes so the console can rebuild its sidebar.

        The console kept its whole conversation list in ``localStorage``, so
        clearing browser data lost every entry even though the sandbox folders
        were still on disk. This endpoint reads them back from
        ``{workspace_root}/task_*`` so a fresh browser can still see the work.
        """
        workspace_root = getattr(run_service, "workspace_root", None)
        if workspace_root is None:
            return {"items": []}
        root = Path(workspace_root)
        if not root.is_dir():
            return {"items": []}

        def _read_json(path: Path) -> dict:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - skip unreadable state
                return {}
            return payload if isinstance(payload, dict) else {}

        task_dirs = sorted(
            (p for p in root.glob("task_*") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        items: list[dict] = []
        deleted_task_ids: list[str] = []
        for task_dir in task_dirs:
            meta = _read_json(task_dir / "state" / "conversation-meta.json")
            if meta.get("deleted_at"):
                deleted_task_ids.append(task_dir.name)
                continue
            if len(items) >= max(1, min(limit, 500)):
                continue
            state = _read_json(task_dir / "state" / "run-state.json")
            interaction = _read_json(task_dir / "state" / "interaction.json")
            if not state and not interaction:
                continue
            conversation = _read_json(task_dir / "state" / "conversation.json")
            raw_turns = conversation.get("turns")
            turns = raw_turns if isinstance(raw_turns, list) else []
            input_dir = task_dir / "input"
            files = (
                sorted(p.name for p in input_dir.iterdir() if p.is_file())
                if input_dir.is_dir()
                else []
            )
            identifiers = state.get("identifiers") or interaction
            items.append(
                {
                    "task_id": task_dir.name,
                    "run_id": identifiers.get("run_id", ""),
                    "title": (
                        str(meta.get("title") or "").strip()
                        or str(state.get("objective") or "").strip()[:60]
                        or task_dir.name
                    ),
                    "workspace_name": str(meta.get("workspace_name") or ""),
                    "phase": interaction.get("status") or state.get("phase", ""),
                    "next_action": state.get("next_action", ""),
                    "objective": state.get("objective", ""),
                    "last_message": state.get("last_message", ""),
                    "turn_count": len(turns),
                    "files": files,
                    "updated_at": datetime.fromtimestamp(
                        task_dir.stat().st_mtime, tz=UTC
                    ).isoformat(timespec="seconds"),
                    "turns": [
                        {"role": t.get("role", ""), "text": str(t.get("text") or "")[:4000], "run_id": t.get("run_id", "")}
                        for t in turns[-40:]
                        if isinstance(t, dict)
                    ],
                }
            )
        return {"items": items, "deleted_task_ids": deleted_task_ids}


    def find_artifact(artifact_id: str) -> PublishedArtifact | None:
        record = run_service.repository.get_artifact(artifact_id)
        if record is not None:
            return record
        # A published file can be requested before the run's repository transaction commits.
        for root in Path(run_service.workspace_root).glob("task_*"):
            for item in read_interaction(TaskWorkspace(root)).get("artifacts", []):
                if item.get("artifact_id") == artifact_id:
                    return PublishedArtifact.model_validate(item)
        return None

    @app.get("/api/artifacts/{artifact_id}/content")
    async def download_investment_artifact(artifact_id: str) -> Response:
        if not dev_ui_enabled:
            raise HTTPException(status_code=404, detail="developer UI is disabled")
        record = find_artifact(artifact_id)
        if record is None or artifact_service is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        is_workbook = record.filename.lower().endswith(".xlsx")
        try:
            async with asyncio.timeout(15 if is_workbook else None):
                payload = await asyncio.to_thread(artifact_service.read_object, record.bucket, record.object_key)
        except Exception as exc:
            logger.exception("artifact download failed")
            raise HTTPException(status_code=502, detail="failed to read artifact") from exc
        return Response(
            content=payload,
            media_type=XLSX_CONTENT_TYPE if is_workbook else DOCX_CONTENT_TYPE,
            headers={"Content-Disposition": _content_disposition(record.filename)},
        )

    @app.get("/api/artifacts/{artifact_id}/preview.pdf")
    async def preview_artifact_pdf(artifact_id: str) -> Response:
        """Render any Office artifact as PDF so the console can show it inline.

        Previously only ``.doc``/``.docx`` were converted, so clicking an Excel
        or PowerPoint artifact fell through to "预览暂不可用" — which is exactly
        what the reviewer saw. PDFs are streamed as-is now.
        """
        record = find_artifact(artifact_id)
        if record is None or artifact_service is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        try:
            payload = artifact_service.read_object(record.bucket, record.object_key)
        except Exception as exc:
            logger.exception("artifact preview read failed")
            raise HTTPException(status_code=502, detail="failed to read artifact") from exc
        suffix = Path(record.filename).suffix.lower()
        if suffix == ".pdf":
            return Response(content=payload, media_type="application/pdf")
        if suffix not in _OFFICE_EXTENSIONS:
            raise HTTPException(status_code=415, detail="该格式暂不支持在线预览，请下载后查看。")
        try:
            content = await _office_to_pdf(record.filename, payload)
        except Exception:
            logger.warning("gotenberg conversion failed for artifact %s", artifact_id, exc_info=True)
            raise HTTPException(status_code=503, detail="预览暂不可用，请下载后查看。") from None
        return Response(content=content, media_type="application/pdf")

    @app.get("/api/artifacts/{artifact_id}/preview")
    async def preview_artifact(artifact_id: str) -> dict:
        if not dev_ui_enabled or institution_workbook_service is None:
            raise HTTPException(status_code=404)
        try:
            preview = await asyncio.to_thread(institution_workbook_service.preview,artifact_id)
        except Exception:
            raise HTTPException(status_code=503,detail="附件预览暂不可用，请下载查看。") from None
        if preview is None:
            raise HTTPException(status_code=404)
        return preview

    @app.get("/api/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str) -> dict:
        record = find_artifact(artifact_id)
        if record is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        if artifact_service is not None:
            record = artifact_service.refresh_download(record)
        return record.model_dump(mode="json")

    # Outermost: nginx keeps proxying only the opaque prefix; routes stay plain.
    app.add_middleware(_EncryptedPrefixMiddleware, prefix=INVESTMENT_PAGE_PREFIX)
    return app
