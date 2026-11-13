"""Production dependency assembly for one synchronous Report Agent run."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.conversation_store import WorkspaceConversationStore
from report_agent.application.data_gateway import DataMcpGateway
from report_agent.application.interactions import (
    read_interaction,
    record_published_artifact,
    update_interaction,
)
from report_agent.application.materials import MaterialIngestionService
from report_agent.application.one_pager_execution import (
    COMMAND_PATH,
    STATE_PATH,
    VERSION,
    execution_state,
    read_json,
    write_json,
)
from report_agent.application.one_pager_reports import OnePagerReportService
from report_agent.application.review_checker import QualityChecker
from report_agent.application.user_request import normalize_user_request
from report_agent.domain.artifacts import artifact_download_path
from report_agent.domain.identifiers import RunIdentity
from report_agent.domain.outline import outline_loader
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.audit import WorkspaceAuditLog
from report_agent.harness.budget import BudgetSnapshot, RunBudget
from report_agent.harness.context import ToolOutputOffloader, build_context_middleware_stack
from report_agent.harness.context_tools import build_context_tools
from report_agent.harness.data_tools import build_data_mcp_tools
from report_agent.harness.evidence_tools import build_evidence_tools
from report_agent.harness.factory import AgentBuildSpec, build_agent
from report_agent.harness.filesystem_tools import build_filesystem_tools
from report_agent.harness.ideology_tools import build_ideology_tools
from report_agent.harness.investment_report_tools import build_investment_report_tools
from report_agent.harness.material_tools import build_material_tools
from report_agent.harness.reasoning import ReasoningChatOpenAI, ReasoningStore
from report_agent.harness.thinking import resolve_adapter
from report_agent.harness.thinking_control import (
    ThinkingPolicyMiddleware,
    build_thinking_tools,
    control_from_run_mode,
)
from report_agent.harness.middleware.agent_logger import AgentCallLoggerMiddleware
from report_agent.harness.middleware.budget import BudgetMiddleware
from report_agent.harness.middleware.context import ToolOutputOffloadMiddleware
from report_agent.harness.middleware.empty_tool_calls_guard import (
    EmptyToolCallsGuardMiddleware,
)
from report_agent.harness.middleware.message_integrity_guard import (
    MessageIntegrityGuardMiddleware,
)
from report_agent.harness.middleware.one_pager_cache import OnePagerResultCacheMiddleware
from report_agent.harness.middleware.persistent_questions import (
    PersistentQuestionBoundaryMiddleware,
)
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware
from report_agent.harness.middleware.tool_recovery import (
    ToolArgumentRecoveryMiddleware,
    ToolFailureEnvelopeMiddleware,
)
from report_agent.harness.middleware.workspace_context import WorkspaceContextMiddleware
from report_agent.harness.one_pager_checkpoint import run_checkpointed_agent
from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.harness.review_tools import build_review_tools
from report_agent.infrastructure.artifacts import MinioArtifactService
from report_agent.infrastructure.evidence import WorkspaceEvidenceStore
from report_agent.infrastructure.materials.conversion import (
    GotenbergConverter,
    TikaTextExtractor,
)
from report_agent.infrastructure.materials.http_recognition import (
    OpenAICompatibleVisionAdapter,
    PaddleLayoutAdapter,
)
from report_agent.infrastructure.materials.parser import MaterialParser
from report_agent.infrastructure.mcp import McpContractRegistry, StreamableHttpMcpTransport
from report_agent.runtime.sandbox import BubblewrapPolicy, build_workspace_backend
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings.ideology_settings import resolve_ideology_dictionary_path
from report_agent.settings.models import ReportAgentSettings
from report_agent.skills import SkillCatalog, SkillDescriptor, ToolPolicy

logger = logging.getLogger(__name__)

TITLE_MODEL_TIMEOUT_SECONDS = 60.0


ONE_PAGER_KEYWORDS: tuple[str, ...] = (
    "一页纸",
    "推介文档",
    "推介材料",
    "one-pager",
    "one pager",
    "onepager",
    "单页bp",
    "单页 bp",
    " BP",
)

# Allowed values of ``selected_skill`` per-call from the API; ``""`` means
# "fall through to deployment default / auto-routing".
SKILL_NAMES: frozenset[str] = frozenset({"investment-report", "one-pager", "chat"})


def continuation_brief(workspace: Any, *, checkpointed: bool) -> str:
    """把上一轮的进度压成一小段提示，避免每次回复都从头重跑。

    每轮对话都会重新 ``build_agent``，SKILL.md 也从第一步讲起；模型因此容
    易把「用户补充一句」当成新任务，重新 load_skill_reference、重读 evidence、
    重写草稿。这里把已完成的事实直接摆到系统提示里。
    """
    try:
        state = read_json(workspace, "/workspace/state/run-state.json") or {}
    except Exception:
        state = {}
    try:
        interaction = read_interaction(workspace)
    except Exception:
        interaction = {}

    completed = [str(item) for item in (state.get("completed_tools") or []) if item]
    references = [str(item) for item in (state.get("loaded_skill_references") or []) if item]
    material_id = str(state.get("material_id") or "")
    source_name = str(state.get("source_name") or "")
    phase = str(state.get("phase") or "")
    artifacts = [item for item in (interaction.get("artifacts") or []) if isinstance(item, dict)]
    pending = interaction.get("pending_question") or {}

    started = bool(completed or material_id or artifacts or references)
    if not started:
        return ""

    lines = ["", "", "# 续跑简报（本任务上一轮的进度，优先于 SKILL 的首次执行说明）"]
    if material_id:
        lines.append(
            f"- 材料已解析：material_id={material_id}"
            + (f"（来源 {source_name}）" if source_name else "")
            + "。**不要再次调用 parse_materials / read_material_chunk**。"
        )
    if references:
        lines.append(
            "- 技能参考文档已加载：" + "、".join(references)
            + "。**不要重复调用 load_skill_reference**。"
        )
    if completed:
        lines.append(
            "- 已完成的步骤：" + "、".join(completed) + "。这些直接沿用，不要重跑。"
        )
    if artifacts:
        names = [
            str(item.get("filename") or item.get("name") or "")
            for item in artifacts[:3]
        ]
        names = [name for name in names if name]
        if names:
            lines.append("- 已产出的文件：" + "、".join(names) + "。")
    if phase:
        lines.append(f"- 上一轮所处阶段：{phase}。")
    if isinstance(pending, dict) and pending.get("question"):
        lines.append(f"- 上一轮等待用户回答的问题：{pending.get('question')}。")

    lines.append(
        "- 用户这条消息是对上一步的补充、确认或新指令。先判断它影响哪一步，"
        "**只重做受影响的部分**；不要重新初始化整个流程，不要在已有计划时重建全部 todo，"
        "不要重写已经通过审查的章节，也不要重新读取已经读过的 evidence。"
    )
    if checkpointed:
        lines.append(
            "- 本任务有执行检查点：恢复后从上次中断处继续，已完成事项一律保留。"
        )
    return "\n".join(lines)


class UnknownSkillRequested(ValueError):
    """Caller asked for a Skill name that is not installed in this deployment."""


#: 推理型模型把思维链当正文返回时的特征词。命中这些词的行不可能是标题。
_TITLE_NOISE = (
    "thinking process",
    "chain of thought",
    "reasoning",
    "analyze the request",
    "analysis:",
    "let me ",
    "we need ",
    "the user ",
    "思考过程",
    "分析请求",
    "推理过程",
    "让我先",
    "首先，",
    "my role",
    "title assistant",
    "对话标题助手",
    "conversation title",
)

_TITLE_STRIP = "\"'“”‘’「」『』《》〈〉 \t\r\n-—·:：,，.。;；!！?？#*`>"


#: 句首客套/指令词，推导本地标题时逐层剥离，保留业务对象。
_TITLE_LEADING = (
    "请帮我", "帮我", "麻烦", "请", "帮忙", "给我", "我要", "我想", "需要",
    "根据材料", "根据附件", "基于材料", "按照材料", "基于附件",
    "生成", "写一份", "写个", "做一个", "做个", "出一份", "出个", "整理一份",
)


#: 模型回显模板或糊弄时的高频值，一律判为无效。
_TITLE_PLACEHOLDERS = frozenset(
    {"标题", "题目", "主题", "名称", "title", "未命名", "无标题", "新对话", "对话标题", "实际标题"}
)


def acceptable_title(title: str) -> bool:
    """标题必须像真的：有汉字、不是模板占位符、不是空壳。"""
    value = str(title or "").strip()
    if len(value) < 2:
        return False
    if value.lower() in _TITLE_PLACEHOLDERS:
        return False
    if any(mark in value for mark in "<>{}「」"):
        return False
    if re.fullmatch(r"[\W_]+", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _title_from_json(raw: str) -> str:
    """从模型输出里取 {"title": "..."} 的标题；不是 JSON 就返回空串。"""
    candidate = str(raw or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"^```(?:json)?|```$", "", candidate, flags=re.M).strip()
    try:
        value = json.loads(candidate)
    except ValueError:
        match = re.search(r'"title"\s*:\s*"([^"]{1,80})"', candidate)
        return match.group(1).strip() if match else ""
    if isinstance(value, dict):
        return str(value.get("title") or "").strip()
    return ""


def derive_title_from_message(message: str, *, max_chars: int = 16) -> str:
    """不依赖模型的标题兜底：从用户第一句话里剥出业务对象。

    模型不可用、被截断或只会输出思维链时用它，避免侧边栏出现
    「Here's a thinking process: ...」这类内容。
    """
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return ""
    text = re.split(r"[。！？!?\n]", text)[0].strip()
    changed = True
    while changed:
        changed = False
        for prefix in _TITLE_LEADING:
            if text.startswith(prefix):
                text = text[len(prefix):].strip(" ，,：:、")
                changed = True
    text = text.strip(" ，,：:、。.!?！？")
    if not text:
        return ""
    return text[:max_chars]


def clean_conversation_title(raw: str, *, max_chars: int = 24) -> str:
    """把模型输出收拾成一个能进侧边栏的标题。

    推理模型常把 ``Here's a thinking process: 1. **Analyze ...`` 这类思维链当作
    正文返回，直接截断会得到一串英文推理。这里按行过滤：先去掉代码块和
    markdown 强调，再丢弃命中推理特征词的行，优先取「标题：」之后的内容，
    否则取最后一个像标题的短句；一个都挑不出来就返回空串，让控制台回落到
    用户第一句话，而不是把垃圾写进标题。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*#`>]+", " ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    # 「标题：xxx」/「Title: xxx」优先
    for line in lines:
        match = re.search(r"(?:标题|题目|title)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(_TITLE_STRIP)
            if candidate:
                return candidate[:max_chars]

    def usable(line: str) -> bool:
        low = line.lower()
        if any(noise in low for noise in _TITLE_NOISE):
            return False
        # 纯英文长句基本是推理过程，中文标题不会这样
        if re.fullmatch(r"[A-Za-z0-9 ,.'\"()\-:;]+", line) and len(line) > 12:
            return False
        return True

    candidates = [line for line in lines if usable(line)]
    if not candidates:
        return ""
    title = candidates[0] if len(candidates) == 1 else candidates[-1]
    title = title.strip(_TITLE_STRIP)
    title = re.sub(r"^\d+[.、)\]]\s*", "", title)  # 去掉 "1. " 这类编号
    title = title.strip(_TITLE_STRIP)
    if not title:
        return ""
    # 最终闸门：要求的是中文标题。模型偶尔会把 system prompt 回显成
    # 「My role: “对话标题助手” (Conversation title assistant)」，这类内容
    # 一个汉字都没有，直接判为失败，让控制台回落到用户原话。
    if not re.search(r"[\u4e00-\u9fff]", title):
        return ""
    return title[:max_chars]


def _title_response_text(content: Any) -> str:
    """Flatten model content and drop reasoning/thinking blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict) or block.get("type") in {"reasoning", "thinking"}:
                continue
            piece = block.get("text") or block.get("content") or ""
            if isinstance(piece, str):
                parts.append(piece)
        return "\n".join(parts)
    return str(content or "")


async def suggest_conversation_title(
    settings: ReportAgentSettings,
    environ: Mapping[str, str] | None = None,
    message: str = "",
) -> str:
    """Ask the configured model for a short Chinese conversation title.

    Thinking stays off: this call has only 64 output tokens, and a reasoning
    trace would otherwise become the title. Returns an empty string when the
    model is unavailable, the call fails, or the reply has no Chinese; the
    console then falls back to a truncated first message.
    """
    text = (message or "").strip()
    if not text:
        return ""
    env = dict(environ or os.environ)
    model_name = env.get(settings.model.model.env, "").strip()
    base_url = env.get(settings.model.base_url.env, "").strip()
    api_key = env.get(settings.model.api_key.env, "").strip()
    if not (model_name and base_url and api_key):
        return ""
    try:
        model = ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=SecretStr(api_key),
            timeout=TITLE_MODEL_TIMEOUT_SECONDS,
            max_retries=0,
            # 推理型模型会先输出一段思维链再给答案，64 token 会在分析阶段就被截断，
            # 导致从来没产出过标题。留足头部空间，但仍然只做一次调用。
            max_tokens=512,  # type: ignore[call-arg]  # Provider-compatible Pydantic alias.
            temperature=0,
            extra_body={"enable_thinking": False},
        )
        response = await asyncio.wait_for(model.ainvoke(
            [
                {
                    "role": "system",
                    "content": (
                        "你是对话标题助手。根据用户的第一条消息，用不超过 16 个汉字概括"
                        "任务对象和材料类型。只输出一个 json 对象，格式为"
                        ' {"title": "实际标题"}，把 实际标题 换成真实内容，'
                        "绝对不要原样回显这个模板。不要输出任何分析、思考过程、"
                        "英文说明或代码块。标题本身不要带引号、标点或句号。"
                    ),
                },
                {"role": "user", "content": text[:800]},
            ]
        ), timeout=TITLE_MODEL_TIMEOUT_SECONDS)
        raw = _title_response_text(getattr(response, "content", "")).strip()
        raw = _title_from_json(raw) or raw
        cleaned = clean_conversation_title(raw)
        return cleaned if acceptable_title(cleaned) else ""
    except Exception as exc:
        logger.info("conversation title unavailable (%s); using message title", type(exc).__name__)
        return ""


def _summarize_tool_output(output: Any) -> tuple[str, str]:
    """Best-effort status + one-line summary from a tool result."""
    if getattr(output, "type", None) == "tool":
        output = output.content
    if output is None:
        return "success", "完成"
    if isinstance(output, str):
        text = output
    elif isinstance(output, dict):
        text = ""
        for key in ("summary", "message", "status", "result"):
            value = output.get(key)
            if isinstance(value, str) and value:
                text = value
                break
        if not text:
            text = json.dumps(output, ensure_ascii=False, default=str)
    else:
        text = str(output)
    lowered = text.lower()
    try:
        payload = output if isinstance(output, dict) else json.loads(text)
    except (ValueError, TypeError):
        payload = {}
    structured_status = payload.get("status") if isinstance(payload, dict) else None
    if structured_status:
        # Unknown statuses must NOT default to "success": the console then shows
        # a green tick for a call that already failed, and nobody investigates.
        # Anything we do not recognise is surfaced as "unknown" so it stands out.
        status = {
            "ok": "success", "published": "success", "success": "success",
            "needs_user_input": "waiting", "needs_input": "waiting",
            "partial": "partial", "empty": "empty", "failed": "failed",
            "invalid_outline": "failed", "invalid_content": "failed",
            "invalid_arguments": "failed", "error": "failed",
            "skipped": "skipped", "staged_only": "partial", "blocked": "partial",
        }.get(str(structured_status), "unknown")
    elif "error" in lowered or "failed" in lowered or "exception" in lowered:
        status = "failed"
    elif "partial" in lowered:
        status = "partial"
    elif "empty" in lowered:
        status = "empty"
    else:
        status = "success"
    return status, text[:160]


def _resolve_skill_name(
    settings: ReportAgentSettings,
    message: str,
    *,
    available: tuple[SkillDescriptor, ...],
    selected_skill: str = "",
) -> tuple[str, str]:
    """Pick a Skill and explain why.

    Returns ``(name, route)`` where ``route`` is one of ``explicit_call``,
    ``default_skill``, ``keyword``, ``fallback``. Resolution order:

    1. ``selected_skill`` from the API call wins; an unknown value raises
       :class:`UnknownSkillRequested` so the call fails before model boot.
    2. ``service.default_skill`` pins the deployment to one product line.
    3. Keyword scan in the user message picks ``one-pager`` over
       ``investment-report`` when its vocabulary is present.
    4. Otherwise default to ``investment-report``.
    """
    requested = (selected_skill or "").strip()
    if requested:
        if requested not in SKILL_NAMES:
            raise UnknownSkillRequested(
                f"selected_skill {requested!r} is not a known skill "
                f"(allowed: {sorted(SKILL_NAMES)})"
            )
        if not any(descriptor.name == requested for descriptor in available):
            raise UnknownSkillRequested(
                f"selected_skill {requested!r} requested but not installed"
            )
        return requested, "explicit_call"

    explicit = settings.service.default_skill
    if explicit != "auto":
        if explicit not in SKILL_NAMES:
            raise UnknownSkillRequested(
                f"service.default_skill {explicit!r} is not a known skill"
            )
        if not any(descriptor.name == explicit for descriptor in available):
            raise UnknownSkillRequested(
                f"service.default_skill {explicit!r} not installed"
            )
        return explicit, "default_skill"

    text = (message or "").lower()
    has_one_pager = any(descriptor.name == "one-pager" for descriptor in available)
    if has_one_pager and any(marker.lower() in text for marker in ONE_PAGER_KEYWORDS):
        return "one-pager", "keyword"
    return "investment-report", "fallback"


class ConfiguredAgentExecutor:
    """Build a fresh bounded Agent for each run while keeping service secrets outside tools."""

    def __init__(
        self,
        settings: ReportAgentSettings,
        environ: Mapping[str, str] | None = None,
        *,
        artifact_service: MinioArtifactService | None = None,
        event_bus: Any | None = None,
        one_pager_checkpointer: Any | None = None,
    ):
        self._settings = settings
        self._environ = dict(environ or os.environ)
        self._artifact_service = artifact_service or MinioArtifactService(
            settings.persistence.minio, self._environ
        )
        self._event_bus = event_bus
        self._one_pager_checkpointer = one_pager_checkpointer
        # LangChain run ids are globally unique, so one map is safe across
        # concurrent runs. Only used to compute per-tool durations.
        self._tool_starts: dict[str, float] = {}

    def prepare_submission(self, identity: RunIdentity, workspace: TaskWorkspace,
                           message: str, *, selected_skill: str = "",
                           question: dict[str, Any] | None = None, has_uploads: bool = False,
                           model_name: str = "", thinking: str = "") -> None:
        """Persist the one-pager command before accepting its HTTP submission."""
        state = execution_state(workspace)
        if not state:
            previous = read_interaction(workspace)
            if previous.get("run_id") or not self._settings.service.one_pager_checkpoints:
                return  # Legacy tasks and reports are never silently migrated.
            catalog = SkillCatalog([Path(root) for root in self._settings.service.skill_roots])
            skill, _ = _resolve_skill_name(self._settings, message, available=catalog.discover(),
                                            selected_skill=selected_skill)
            if skill != "one-pager":
                return
            state = {"version": VERSION, "thread_id": f"one-pager:{identity.task_id}",
                     "task_id": identity.task_id, "status": "new"}
            if self._one_pager_checkpointer is None:
                database = self._environ.get(self._settings.service.one_pager_checkpoint_database_env, "").strip()
                if not database or database == self._environ.get(self._settings.persistence.mysql.database.env, "").strip():
                    raise ValueError("请先配置独立 REPORT_AGENT_CHECKPOINT_DATABASE 并执行 --checkpoints --apply")
                state["checkpoint_database"] = database
        if selected_skill and selected_skill != "one-pager":
            raise ValueError("当前任务已绑定一页纸执行检查点，请在新对话中切换业务")
        pending = state.get("pending_question")
        old_command = read_json(workspace, COMMAND_PATH)
        if old_command.get("status") == "pending" and state.get("status") != "completed":
            # A response may have been lost after the durable acceptance. Keep
            # its original answer; a retry must not replace it with new text.
            command = old_command
        elif pending:
            if not question or question.get("question_id") != pending["question_id"]:
                raise ValueError("请回答当前检查点的问题后继续")
            text = message
            if has_uploads:
                paths = sorted(str(p.relative_to(workspace.root)).replace("\\", "/")
                               for p in (workspace.root / "input").rglob("*") if p.is_file())
                text += "\n本轮已附加材料，请按需读取新增内容：\n" + "\n".join(paths)
            command = {"id": "user_" + identity.run_id, "kind": "resume", "status": "pending",
                       "question_id": pending["question_id"],
                       "model_name": model_name, "thinking": thinking,
                       "answer": {"question_id": pending["question_id"], "text": text}}
        else:
            command = {"id": "user_" + identity.run_id, "kind": "message", "text": message,
                       "status": "pending",
                       "model_name": model_name, "thinking": thinking}
            if state.get("status") == "completed":
                state.pop("budget", None)  # Explicit new request after delivery.
                state.pop("published_artifacts", None)
        command["run_id"] = identity.run_id
        write_json(workspace, COMMAND_PATH, command)
        write_json(workspace, STATE_PATH, {**state, "run_id": identity.run_id})

    def _get_one_pager_checkpointer(self) -> Any:
        if self._one_pager_checkpointer is None:
            from report_agent.infrastructure.persistence.checkpoints import (
                build_one_pager_checkpointer,
            )
            self._one_pager_checkpointer = build_one_pager_checkpointer(
                self._settings.persistence.mysql, self._environ,
                self._settings.service.one_pager_checkpoint_database_env,
            )
        return self._one_pager_checkpointer

    async def __call__(
        self,
        identity: RunIdentity,
        workspace: TaskWorkspace,
        message: str,
        *,
        selected_skill: str = "",
        model_name: str = "",
        thinking: str = "",
    ) -> dict[str, Any]:
        settings = self._settings
        resolved_model = (model_name or "").strip() or self._required(settings.model.model.env)
        # ``LLM_THINKING_ADAPTER`` wins over the YAML value so an operator can
        # change the request shape without editing the deployment file.
        adapter = resolve_adapter(
            self._environ.get("LLM_THINKING_ADAPTER", "").strip()
            or settings.model.thinking_adapter,
            resolved_model,
        )
        # Reasoning level is owned by ``ThinkingPolicyMiddleware``: the model can
        # ask for more reasoning via ``set_thinking``, and the middleware
        # translates that into provider parameters per call. Nothing is fixed here.
        reasoning_control = control_from_run_mode(thinking)
        reasoning_store = ReasoningStore(workspace, identity.run_id)
        model = ReasoningChatOpenAI(
            model=resolved_model,
            base_url=self._required(settings.model.base_url.env),
            api_key=SecretStr(self._required(settings.model.api_key.env)),
            timeout=settings.model.timeout_seconds,
            max_retries=settings.model.max_retries,
            store=reasoning_store,
        )
        backend = build_workspace_backend(
            identity.workspace_id,
            workspace,
            backend=settings.sandbox.backend,
            policy=BubblewrapPolicy(
                default_timeout_seconds=settings.sandbox.command_timeout_seconds,
                max_output_chars=settings.context.inline_tool_output_chars,
            ),
        )
        evidence_store = WorkspaceEvidenceStore(workspace)
        context_store = WorkspaceContextStore(workspace)
        uploaded = [
            record.path
            for record in workspace.snapshot().files.values()
            if record.path.startswith("/workspace/input/")
        ]
        request = normalize_user_request(message, has_uploads=bool(uploaded))
        context_store.initialize(identity, request)
        transport = StreamableHttpMcpTransport(
            settings.data_mcp.url or "", timeout_seconds=settings.data_mcp.tool_timeout_seconds
        )
        evidence_observer = None
        if settings.institution_workbook.enabled and read_interaction(workspace).get("institution_workbook"):
            from report_agent.application.institution_workbook.context import recorder
            side_recorder = recorder()
            def evidence_observer(tool, arguments, record):
                side_recorder.observe(workspace, identity.run_id, tool, arguments, record)
        gateway = DataMcpGateway(
            transport,
            McpContractRegistry(
                Path(settings.data_mcp.contracts_dir), settings.data_mcp.enabled_tools
            ),
            evidence_store,
            required=settings.data_mcp.required,
            audit=WorkspaceAuditLog(workspace),
            identity=identity,
            context_store=context_store,
            evidence_observer=evidence_observer,
        )
        catalog = SkillCatalog([Path(root) for root in settings.service.skill_roots])
        available_skills = catalog.discover()
        previous_skill = str(read_interaction(workspace).get("active_skill") or "")
        skill_name, skill_route = _resolve_skill_name(
            settings, message, available=available_skills, selected_skill=selected_skill or previous_skill
        )
        if previous_skill and skill_name == previous_skill:
            skill_route = "conversation"
        update_interaction(workspace, active_skill=skill_name, skill_route=skill_route)
        checkpointed = skill_name == "one-pager" and bool(execution_state(workspace))
        if checkpointed:
            saved_database = execution_state(workspace).get("checkpoint_database")
            current_database = self._environ.get(settings.service.one_pager_checkpoint_database_env, "").strip()
            if saved_database and saved_database != current_database:
                raise ValueError("当前检查点 schema 与任务创建时不同，请恢复原配置，不能从头重跑")
        logger.warning(
            "skill routed: run_id=%s skill=%s route=%s msg_first_60=%r",
            identity.run_id,
            skill_name,
            skill_route,
            (message or "")[:60],
        )
        if self._event_bus is not None:
            from report_agent.domain.events import EventType

            self._event_bus.emit(
                identity,
                EventType.SKILL_ACTIVATED,
                {
                    "skill": skill_name,
                    "route": skill_route,
                    "resuming": checkpointed and execution_state(workspace).get("status") not in {"new", "completed"},
                    "plan": execution_state(workspace).get("plan", []) if checkpointed else [],
                    "description": (
                        "单页 Word 推介文档：画像 → 投资人匹配 → 模板渲染"
                        if skill_name == "one-pager"
                        else "投资匹配报告：材料解析 → 五项数据 → 报告 → Word"
                    ),
                },
            )
        skill, prompt = catalog.activate(skill_name)
        # 每次回复都会重建 agent，SKILL 又从第一步讲起；把已完成的进度摆进提示，
        # 否则模型会把「补充一句」当成新任务，重新加载 skill、重解析材料、重写草稿。
        prompt += continuation_brief(workspace, checkpointed=checkpointed)
        if checkpointed:
            prompt += (
                "\n\n# 持久执行规则（优先于首次初始化指令）\n"
                "系统保留完整工具调用和计划。只有没有历史步骤的首次执行才初始化六步计划；"
                "已有计划时不要用 write_todos 重建整份计划，最多用它更新单步状态。"
                "用户回答卡片后，继续刚才工具之后的步骤，保留已完成事项；"
                "不得重新解析相同材料、重新规划全部步骤或重复成功的补数。"
                "回答和附加说明已进入本任务消息，必须用于后续写作。"
                "工具结果复用时原 evidence 仍有效，按引用读取，不必重新获取。"
                "需要用户补充材料或做决定时必须调用 ask_user，不能只发一个问题便结束图。"
            )
        if skill.name != "chat" and (not checkpointed or execution_state(workspace).get("status") == "new"):
            required_tools = frozenset(skill.allowed_tools) & gateway.contracts.enabled_tools
            await gateway.readiness(required_tools - {"query_company_registry"})
        if skill.name == "investment-report":
            prompt += (
                "\n\nWord 交付只使用 report_id/artifact_id；创建后调用 validate_and_publish_word。"
                "\n本 Agent 唯一交付物是投资人匹配报告。即使用户消息是「总结/摘要文档」类表述，"
                "只要存在上传材料，仍必须按本 skill 完整流程产出并发布报告，不得仅输出文档摘要。"
            )
        reference_names = SkillCatalog.stage_references(skill, workspace)
        published_artifacts: list[Any] = []

        def publish_report(path: str):
            if checkpointed:
                artifact = self._artifact_service.publish(identity, workspace, path, idempotent=True)
            else:
                artifact = self._artifact_service.publish(identity, workspace, path)
            published_artifacts.append(artifact)
            if checkpointed:
                current = execution_state(workspace)
                published = {a["artifact_id"]: a for a in current.get("published_artifacts", [])}
                published[artifact.artifact_id] = artifact.model_dump(mode="json")
                write_json(workspace, STATE_PATH, {**current, "published_artifacts": list(published.values())})
            context_store.record_artifact(
                artifact.artifact_id,
                kind="published_docx",
                path=path,
                status="published",
                sha256=artifact.sha256,
                details={"object_key": artifact.object_key},
            )
            record_published_artifact(workspace, artifact)
            if self._event_bus is not None:
                from report_agent.domain.events import EventType

                self._event_bus.emit(
                    identity,
                    EventType.ARTIFACT_CREATED,
                    {
                        "artifact_id": artifact.artifact_id,
                        "filename": artifact.filename,
                        "size_bytes": artifact.size,
                        "kind": "docx",
                        "version": len(published_artifacts),
                        "download_url": artifact_download_path(artifact.artifact_id),
                        "sha256": artifact.sha256,
                    },
                )
            return artifact

        def upload_material_md(object_key: str, text: str):
            uploader = getattr(self._artifact_service, "upload_markdown", None)
            if uploader is None:
                raise RuntimeError("对象存储未配置，请改用 export_material_text")
            return uploader(object_key, text)

        tools: tuple[Any, ...]
        if skill.name == "chat":
            # Plain conversation: no report pipeline, no publish tools.
            tools = (
                *build_context_tools(context_store, workspace, reference_names),
                *build_material_tools(
                    MaterialIngestionService(
                        workspace,
                        parser=self._build_material_parser(settings),
                        evidence_store=evidence_store,
                    ),
                    context_store,
                ),
            )
        elif skill.name == "one-pager":
            evidence_store = WorkspaceEvidenceStore(workspace)
            tool_context_store = context_store or WorkspaceContextStore(workspace)
            one_pager_service = OnePagerReportService(
                workspace, skill_version=skill.version, restore_persisted=checkpointed,
            )
            resolved_ideology_path = resolve_ideology_dictionary_path()
            available = (
                *build_context_tools(tool_context_store, workspace, reference_names),
                *build_material_tools(
                    MaterialIngestionService(
                        workspace, parser=self._build_material_parser(settings),
                        evidence_store=evidence_store,
                    ),
                    tool_context_store,
                    upload_markdown=upload_material_md,
                    task_id=identity.task_id,
                ),
                *build_data_mcp_tools(gateway, workspace=workspace),
                *build_evidence_tools(evidence_store),
                *build_ask_user_tools(resumable=checkpointed, workspace=workspace),
                *build_ideology_tools(resolved_ideology_path),
                *build_review_tools(
                    QualityChecker(
                        required_sections=outline_loader(
                            str(
                                Path(
                                    "apps/report_agent/skills/one-pager/references/"
                                    "report-outline.md"
                                )
                            )
                        )
                        or None,
                        outline_path=str(
                            Path(
                                "apps/report_agent/skills/one-pager/references/"
                                "report-outline.md"
                            )
                        ),
                        workspace=workspace,
                    ),
                    workspace=workspace,
                ),
                *build_one_pager_tools(
                    workspace,
                    service=one_pager_service,
                    publish=publish_report,
                ),
                *build_filesystem_tools(backend=backend),
            )
            by_name = {tool.name: tool for tool in available}
            if len(by_name) != len(available):
                raise ValueError("duplicate tool names in one-pager toolset")
            selected_names = ToolPolicy().select(skill, by_name)
            tools = tuple(by_name[name] for name in selected_names)
        else:

            def upload_material_md(object_key: str, text: str):
                """Upload the parsed material so the MCP can fetch it by URL."""
                uploader = getattr(self._artifact_service, "upload_markdown", None)
                if uploader is None:
                    raise RuntimeError(
                        "对象存储未配置，无法生成 material_url；请改用 export_material_text"
                    )
                return uploader(object_key, text)

            tools = build_investment_report_tools(
                skill=skill,
                gateway=gateway,
                workspace=workspace,
                backend=backend,
                publish=publish_report,
                context_store=context_store,
                skill_reference_names=reference_names,
                visual_review_required=settings.document_processing.visual_review_required,
                word_workspace=workspace,
                material_parser=self._build_material_parser(settings),
                upload_material_md=upload_material_md,
                task_id=identity.task_id,
            )
        # Optional capability: the skill states when reasoning is worth spending,
        # the model decides whether to ask for it. Absent, the skill still works.
        tools = (*tools, *build_thinking_tools(reasoning_control))
        # 预算按 **本次 run** 计，不跨 run 累计。
        #
        # 之前用 `initial=上一轮的快照` 累计：一页纸要问用户 2-3 轮（业务类型、
        # 工商名称、北交所披露），每轮都接着上次的计数跑，第 3 轮一提交就
        # BudgetExceeded，任务被永久锁死——用户只能删掉重建。
        # 而配置项本身叫 `max_model_calls`（一次 run 的调用上限），累计本来就与
        # 其语义不符。快照仍然持久化，只是用于观测，不再作为下一次的起点。
        previous_budget = execution_state(workspace).get("budget") if checkpointed else None

        def persist_budget(snapshot: BudgetSnapshot) -> None:
            current = execution_state(workspace)
            write_json(workspace, STATE_PATH, {**current, "budget": {
                "model_calls": snapshot.model_calls, "tool_calls": snapshot.tool_calls,
                "elapsed_seconds": snapshot.elapsed_seconds}})

        budget = RunBudget(
            max_model_calls=settings.harness.max_model_calls,
            max_tool_calls=settings.harness.max_tool_calls,
            timeout_seconds=settings.harness.run_timeout_seconds,
            persist=persist_budget if checkpointed else None,
        )
        if previous_budget:
            logger.info(
                "previous run used %s model calls / %s tool calls (informational only)",
                previous_budget.get("model_calls"), previous_budget.get("tool_calls"),
            )
        _, context_middleware = build_context_middleware_stack(
            settings.context,
            self._environ,
            model=model,
            workspace=workspace,
        )
        middleware = (
            PersistentQuestionBoundaryMiddleware() if checkpointed else QuestionBoundaryMiddleware(),
            ToolArgumentRecoveryMiddleware(
                max_repair_attempts=settings.harness.tool_argument_repair_attempts
            ),
            EmptyToolCallsGuardMiddleware(max_retries=settings.harness.empty_tool_calls_retries),
            BudgetMiddleware(budget),
            # Applies whatever reasoning level the model last asked for. Sits
            # outside the context middleware so the payload it edits is the one
            # that actually leaves the process.
            ThinkingPolicyMiddleware(reasoning_control, adapter),
            ToolFailureEnvelopeMiddleware(),
            ToolOutputOffloadMiddleware(
                ToolOutputOffloader(
                    workspace,
                    inline_chars=settings.context.inline_tool_output_chars,
                    context_store=context_store,
                ),
                exempt_tools=frozenset({"ask_user", "query_company_registry", "query_cbex_listing_financials", "detect_one_pager_business_type", "check_one_pager_outline", "render_one_pager"}) if checkpointed else frozenset({"query_cbex_listing_financials", "check_one_pager_outline", "render_one_pager"}),
            ),
            *context_middleware,
            WorkspaceContextMiddleware(context_store, workspace, reference_names),
            MessageIntegrityGuardMiddleware(),
            # Keep this innermost so it records the request after every
            # project-owned request transformer has run.
            AgentCallLoggerMiddleware(workspace, run_id=identity.run_id, task_id=identity.task_id),
            *((OnePagerResultCacheMiddleware(workspace, skill.version),) if checkpointed else ()),
        )
        agent = build_agent(
            AgentBuildSpec(
                model=model,
                backend=backend,
                system_prompt=prompt,
                tools=tools,
                middleware=middleware,
                checkpointer=self._get_one_pager_checkpointer() if checkpointed else None,
            )
        )
        if uploaded:
            request += (
                "\n已上传材料（DOCX/PDF 等二进制文件必须先调用 parse_materials，"
                "不得用 read_file 直接读取）：\n" + "\n".join(f"- {path}" for path in uploaded)
            )
        # `create_deep_agent` already attaches `recursion_limit: 9999` via
        # `.with_config()`. `agent.ainvoke()` inherits it, but the config used
        # by `astream_events()` falls back to the LangGraph default (25), which
        # aborts legitimate multi-page runs with GraphRecursionError. Pass the
        # same ceiling explicitly so both paths behave identically; the real
        # cost guard stays RunBudget (max_model_calls / max_tool_calls).
        # 把同一沙箱的历史往返一并塞回模型，否则它不知道上一轮自己问过
        # 什么。不做截断：流程轮数有限，真超上下文时模型侧会报错。
        history = WorkspaceConversationStore(workspace).messages()
        # submit() already records this user turn. Replace it with the request
        # carrying file instructions rather than feeding the same turn twice.
        if history and history[-1]["role"] == "user" and history[-1]["content"] == message:
            history = history[:-1]
        if checkpointed:
            from langchain_core.messages import HumanMessage
            command = read_json(workspace, COMMAND_PATH)
            try:
                result = await run_checkpointed_agent(
                    agent, workspace, identity,
                    {"messages": [HumanMessage(id=command["id"], content=request)]},
                    self._run_agent,
                )
            finally:
                persist_budget(budget.snapshot(check_limits=False))
        else:
            result = await self._run_agent(
                agent,
                {"messages": [*history, {"role": "user", "content": request}]},
                {
                    "configurable": {"thread_id": identity.session_id},
                    "recursion_limit": 9_999,
                },
                identity,
            )
        result["artifacts"] = [artifact.model_dump(mode="json") for artifact in published_artifacts]
        if checkpointed and not published_artifacts and result.get("execution_status") == "completed":
            # A crash can happen after publish's checkpoint but before the run
            # repository finishes. Reconcile the persisted publish manifests.
            result["artifacts"] = execution_state(workspace).get("published_artifacts", [])
        result["skill_name"] = skill_name
        result["skill_route"] = skill_route
        return result

    async def _run_agent(
        self, agent: Any, inputs: Any, config: dict[str, Any], identity: RunIdentity,
        *, checkpointed: bool = False,
    ) -> dict[str, Any]:
        """Execute the agent, mirroring tool activity onto the event bus.

        Without an event bus this is exactly ``agent.ainvoke``. With one we use
        ``astream_events`` and derive the final state from the last chain end; a
        streaming failure is surfaced instead of silently re-running the agent.
        """
        if self._event_bus is None or not hasattr(agent, "astream_events"):
            if checkpointed:
                return await agent.ainvoke(inputs, config=config, durability="sync")
            return await agent.ainvoke(inputs, config=config)

        final: dict[str, Any] | None = None
        try:
            kwargs = {"durability": "sync"} if checkpointed else {}
            async for event in agent.astream_events(inputs, config=config, version="v2", **kwargs):
                self._handle_stream_event(identity, event)
                if event.get("event") == "on_chain_end":
                    output = (event.get("data") or {}).get("output")
                    if isinstance(output, dict) and output.get("messages"):
                        final = output
        except Exception:
            logger.exception("agent streaming failed: run_id=%s", identity.run_id)
            raise
        if checkpointed:
            return dict((await agent.aget_state(config)).values or {})
        if final is None:
            raise RuntimeError("agent stream ended without a final message state")
        return final

    def _handle_stream_event(self, identity: RunIdentity, event: dict[str, Any]) -> None:
        import time

        from report_agent.domain.events import EventType

        if self._event_bus is None:
            return

        kind = event.get("event")
        if kind not in ("on_tool_start", "on_tool_end", "on_tool_error"):
            return
        call_id = str(event.get("run_id") or "")
        name = str(event.get("name") or "tool")
        data = event.get("data") or {}

        if kind == "on_tool_start":
            if name == "write_todos":
                arguments = data.get("input")
                items = arguments.get("todos", []) if isinstance(arguments, dict) else []
                self._event_bus.emit(identity, EventType.PLAN_UPDATED, {"items": items})
            self._tool_starts[call_id] = time.monotonic()
            self._event_bus.emit(
                identity,
                EventType.TOOL_STARTED,
                {"call_id": call_id, "tool": name, "provider": "agent"},
            )
            return

        if kind == "on_tool_end":
            started = self._tool_starts.pop(call_id, None)
            duration = int((time.monotonic() - started) * 1000) if started else None
            status, summary = _summarize_tool_output(data.get("output"))
            self._event_bus.emit(
                identity,
                EventType.TOOL_COMPLETED,
                {
                    "call_id": call_id,
                    "tool": name,
                    "status": status,
                    "duration_ms": duration,
                    "summary": summary,
                },
            )
            return

        self._tool_starts.pop(call_id, None)
        self._event_bus.emit(
            identity,
            EventType.TOOL_FAILED,
            {
                "call_id": call_id,
                "tool": name,
                "error": str(data.get("error") or "tool failed")[:300],
            },
        )

    def _required(self, name: str) -> str:
        value = self._environ.get(name, "").strip()
        if not value:
            raise ValueError(f"required environment variable is missing: {name}")
        return value

    def _build_material_parser(self, settings: ReportAgentSettings) -> MaterialParser:
        doc = settings.document_processing
        timeout = doc.request_timeout_seconds
        gotenberg = GotenbergConverter(
            self._required(doc.gotenberg_url.env), timeout_seconds=timeout
        )
        tika = TikaTextExtractor(self._required(doc.tika_url.env), timeout_seconds=timeout)
        paddle = PaddleLayoutAdapter(
            endpoint=self._required(doc.paddle_ocr_url.env),
            token=self._required(doc.paddle_ocr_token.env),
            timeout_seconds=timeout,
        )
        vision = OpenAICompatibleVisionAdapter(
            base_url=self._required(settings.model.base_url.env),
            api_key=self._required(settings.model.api_key.env),
            model=self._required(settings.model.multimodal_model.env),
            timeout_seconds=settings.model.timeout_seconds,
        )
        return MaterialParser(
            gotenberg=gotenberg,
            tika=tika,
            paddle=paddle,
            vision=vision,
            vision_concurrency=doc.vision_concurrency,
        )
