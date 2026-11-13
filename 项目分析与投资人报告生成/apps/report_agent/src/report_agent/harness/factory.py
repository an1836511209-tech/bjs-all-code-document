"""The only module allowed to construct the third-party Agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

_PROFILE_LOCK = Lock()
_PROFILE_CONFIGURED = False


@dataclass(frozen=True, slots=True)
class AgentBuildSpec:
    model: Any
    backend: Any
    system_prompt: str
    tools: tuple[Any, ...] = field(default_factory=tuple)
    middleware: tuple[Any, ...] = field(default_factory=tuple)
    checkpointer: Any | None = None
    store: Any | None = None
    permissions: tuple[FilesystemPermission, ...] = field(default_factory=tuple)


def build_agent(spec: AgentBuildSpec) -> Any:
    """Build a Deep Agent behind a narrow project-owned adapter."""
    _configure_deepagents_profile()
    from deepagents import create_deep_agent

    kwargs: dict[str, Any] = {
        "model": spec.model,
        "backend": spec.backend,
        "system_prompt": spec.system_prompt,
        "tools": list(spec.tools),
        "middleware": list(spec.middleware),
        "permissions": list(spec.permissions),
    }
    if spec.checkpointer is not None:
        kwargs["checkpointer"] = spec.checkpointer
    if spec.store is not None:
        kwargs["store"] = spec.store
    return create_deep_agent(**kwargs)


def _configure_deepagents_profile() -> None:
    """Disable SDK behaviors that conflict with project-owned state control."""
    global _PROFILE_CONFIGURED
    with _PROFILE_LOCK:
        if _PROFILE_CONFIGURED:
            return
        register_harness_profile(
            "openai",
            HarnessProfile(
                excluded_middleware=frozenset({"SummarizationMiddleware"}),
                excluded_tools=frozenset({"task"}),
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            ),
        )
        _PROFILE_CONFIGURED = True
