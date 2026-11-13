"""Strict configuration schema shared by test, UAT and production."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STANDARD_DATA_MCP_TOOLS = frozenset(
    {
        "extract_project_profile",
        "query_track_labels",
        "query_comparable_valuation",
        "match_listed_peers",
        "match_investors",
    }
)

WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute_path(value: str) -> bool:
    """Accept container POSIX paths and host Windows drive paths."""
    return PurePosixPath(value).is_absolute() or bool(WINDOWS_ABSOLUTE.match(value))


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EnvRef(FrozenModel):
    env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")


class SecretRef(EnvRef):
    """Environment reference whose resolved value must never be logged."""


class ServiceSettings(FrozenModel):
    workspace_root: str
    skill_roots: tuple[str, ...]
    workspace_max_mb: int = Field(default=2048, ge=64, le=32768)
    dev_ui_enabled: bool = False
    max_upload_mb: int = Field(default=100, ge=1, le=1024)
    dev_trace_max_chars: int = Field(default=12000, ge=1000, le=100000)
    one_pager_checkpoints: bool = False
    one_pager_checkpoint_database_env: str = Field(default="REPORT_AGENT_CHECKPOINT_DATABASE", pattern=r"^[A-Z][A-Z0-9_]+$")
    default_skill: str = Field(
        default="auto",
        pattern=r"^(auto|investment-report|one-pager)$",
        description=(
            "Which Skill to activate when the request does not name one. "
            "'auto' routes by keyword (`one-pager` words → one-pager, else investment-report)."
        ),
    )

    @model_validator(mode="after")
    def validate_absolute_paths(self) -> ServiceSettings:
        paths = (self.workspace_root, *self.skill_roots)
        if any(not _is_absolute_path(path) for path in paths):
            raise ValueError("service paths must be absolute POSIX or Windows paths")
        return self


class ModelSettings(FrozenModel):
    provider: Literal["openai_compatible"] = "openai_compatible"
    base_url: SecretRef
    api_key: SecretRef
    model: SecretRef
    multimodal_model: SecretRef
    timeout_seconds: int = Field(default=120, ge=1, le=1200)
    max_retries: int = Field(default=2, ge=0, le=10)
    #: Which request shape the endpoint expects for reasoning. ``auto`` guesses
    #: from the model name; the value is one of qwen / deepseek / anthropic /
    #: openai / none.
    thinking_adapter: str = "auto"
    #: Comma-separated model names the console offers for debugging. Empty
    #: means "only the configured model".
    model_candidates: EnvRef | None = None


class HarnessSettings(FrozenModel):
    """运行期资源上限。

    ``max_model_calls`` 默认 200：超过后**软中断**——本轮暂停、状态保留，用户回
    一句话就开新一轮接着做（不是失败）。``max_tool_calls`` 默认 None = 不限。
    ``run_timeout_seconds`` 是"进程被挂住"的兜底，属于硬超限。
    """

    max_model_calls: int | None = Field(default=200, ge=1, le=2000)
    max_tool_calls: int | None = Field(default=None, ge=1, le=5000)
    run_timeout_seconds: int | None = Field(default=1800, ge=1, le=7200)
    tool_argument_repair_attempts: int = Field(default=2, ge=0, le=5)
    empty_tool_calls_retries: int = Field(default=2, ge=0, le=5)


class ContextSettings(FrozenModel):
    model_context_tokens: EnvRef
    hard_stop_ratio: float = Field(default=0.9, gt=0, lt=1)
    inline_tool_output_chars: int = Field(default=10000, ge=1000, le=100000)
    compression_trigger_ratio: float = Field(default=0.75, gt=0, lt=1)
    compression_keep_recent: int = Field(default=6, ge=2, le=20)


class SandboxSettings(FrozenModel):
    backend: Literal["bubblewrap", "filesystem"] = "bubblewrap"
    network_mode: Literal["isolated"] = "isolated"
    runtime_image: str
    cpu_limit: float = Field(default=1.0, gt=0, le=16)
    memory_mb: int = Field(default=2048, ge=256, le=32768)
    process_limit: int = Field(default=64, ge=8, le=1024)
    command_timeout_seconds: int = Field(default=120, ge=1, le=1800)


class McpSettings(FrozenModel):
    transport: Literal["stdio", "streamable-http"]
    url: str | None = None
    contracts_dir: str
    required: bool = True
    tool_timeout_seconds: int = Field(default=600, ge=1, le=600)
    enabled_tools: tuple[str, ...]

    @model_validator(mode="after")
    def validate_transport(self) -> McpSettings:
        if self.transport == "streamable-http" and not self.url:
            raise ValueError("streamable-http MCP requires url")
        if len(set(self.enabled_tools)) != len(self.enabled_tools):
            raise ValueError("enabled_tools contains duplicates")
        # 五个标准工具是必需的基线；主干合并进来的补充型工具（企查查工商、
        # 网页搜索、北交所挂牌财务）是可选的追加项，不要求恰好等于基线。
        missing = STANDARD_DATA_MCP_TOOLS - set(self.enabled_tools)
        if missing:
            raise ValueError(
                "enabled_tools is missing standard Data MCP tools: "
                + ", ".join(sorted(missing))
            )
        if not _is_absolute_path(self.contracts_dir):
            raise ValueError("MCP contracts_dir must be an absolute POSIX or Windows path")
        return self


class DocumentProcessingSettings(FrozenModel):
    paddle_ocr_url: EnvRef
    paddle_ocr_token: SecretRef
    gotenberg_url: EnvRef
    tika_url: EnvRef
    request_timeout_seconds: int = Field(default=300, ge=1, le=900)
    mixed_pdf_requires_explicit_routing: bool = True
    visual_review_required: bool = False
    vision_concurrency: int = Field(default=4, ge=1, le=16)


class MySQLSettings(FrozenModel):
    host: SecretRef
    port: SecretRef
    database: SecretRef
    user: SecretRef
    password: SecretRef
    charset: SecretRef


class RedisSettings(FrozenModel):
    host: SecretRef
    port: SecretRef
    password: SecretRef
    database: SecretRef


class MinioSettings(FrozenModel):
    endpoint: SecretRef
    access_key: SecretRef
    secret_key: SecretRef
    bucket: SecretRef
    secure: SecretRef
    object_prefix: str = Field(default="reports", pattern=r"^[A-Za-z0-9][A-Za-z0-9/_-]{0,127}$")
    presigned_url_expiry_seconds: int = Field(default=3600, ge=60, le=604800)


class PersistenceSettings(FrozenModel):
    mysql: MySQLSettings
    redis: RedisSettings
    minio: MinioSettings


class InstitutionSelectionSettings(FrozenModel):
    max_selected_tags: int = Field(default=5, ge=1, le=10)
    max_candidate_tags: int = Field(default=100, ge=1, le=100)
    max_material_chars: int = Field(default=24000, ge=1000, le=48000)
    max_model_attempts: Literal[1] = 1


class InstitutionWorkbookSettings(FrozenModel):
    enabled: bool = False
    auto_after_report: bool = True
    allowed_skills: tuple[Literal["investment-report", "one-pager"], ...] = ("investment-report", "one-pager")
    max_concurrent_jobs: Literal[1] = 1
    total_timeout_seconds: int = Field(default=120, ge=10, le=300)
    tag_refresh_timeout_seconds: int = Field(default=35, ge=1, le=60)
    selection_timeout_seconds: int = Field(default=25, ge=1, le=60)
    mcp_timeout_seconds: int = Field(default=45, ge=1, le=90)
    upload_timeout_seconds: int = Field(default=10, ge=1, le=30)
    context_validation_budget_seconds: int = Field(default=5, ge=1, le=15)
    max_workbook_bytes: int = Field(default=2097152, ge=1024, le=2097152)
    selection: InstitutionSelectionSettings = Field(default_factory=InstitutionSelectionSettings)


class ReportAgentSettings(FrozenModel):
    schema_version: Literal["1.0"]
    environment: Literal["test", "uat", "prod"]
    service: ServiceSettings
    model: ModelSettings
    harness: HarnessSettings
    context: ContextSettings
    sandbox: SandboxSettings
    data_mcp: McpSettings
    document_processing: DocumentProcessingSettings
    persistence: PersistenceSettings
    institution_workbook: InstitutionWorkbookSettings = Field(default_factory=InstitutionWorkbookSettings)

    @model_validator(mode="after")
    def validate_local_filesystem_backend(self) -> ReportAgentSettings:
        if self.sandbox.backend == "filesystem" and self.environment != "test":
            raise ValueError("filesystem sandbox backend is allowed only in test")
        return self
