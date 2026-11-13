"""Bubblewrap-backed Deep Agents sandbox boundary."""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from report_agent.runtime.workspace import (
    TaskWorkspace,
    WorkspacePolicyError,
    WorkspaceQuotaExceeded,
)

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
logger = logging.getLogger(__name__)

ExecuteMode = Literal["bwrap", "bwrap_no_cgroup"]

# Cgroup limits are also enforced by the runtime container. Only that optional
# namespace may be omitted; filesystem and network isolation remain mandatory.
_CGROUP_NS_UNSUPPORTED = "Cannot create new cgroup namespace"
_USER_NS_UNSUPPORTED_MARKERS = (
    "Creating new namespace failed",
    "kernel does not support user namespaces",
    "bwrap must be installed setuid",
)


def build_workspace_backend(
    sandbox_id: str,
    workspace: TaskWorkspace,
    *,
    backend: Literal["bubblewrap", "filesystem"],
    policy: BubblewrapPolicy | None = None,
) -> Any:
    """Build the configured backend while preserving ``/workspace`` paths."""
    if backend == "bubblewrap":
        # File operations (read/write/edit/ls/glob/grep) route to direct
        # workspace I/O; only `execute` is routed to the bwrap sandbox.
        # deepagents' BaseSandbox implements the file protocol by running an
        # internal Python script through execute() and parsing stdout as ONE
        # JSON document. Our bounded execute() output appends a truncation
        # marker for payloads over max_output_chars, which corrupts that
        # protocol ("unexpected server response") for any file larger than
        # the inline cap. The /workspace directory is bind-mounted into the
        # sandbox, so direct I/O sees exactly the same files.
        sandbox = BubblewrapSandboxBackend(sandbox_id, workspace, policy=policy)
        filesystem = FilesystemBackend(workspace.root, virtual_mode=True)
        return CompositeBackend(
            default=sandbox,
            routes={"/workspace/": filesystem},
            artifacts_root="/workspace",
        )
    filesystem = FilesystemBackend(workspace.root, virtual_mode=True)
    return CompositeBackend(
        default=filesystem,
        routes={"/workspace/": filesystem},
        artifacts_root="/workspace",
    )


@dataclass(frozen=True, slots=True)
class BubblewrapPolicy:
    executable: str = "bwrap"
    shell: str = "/bin/sh"
    default_timeout_seconds: int = 120
    max_output_chars: int = 12_000

    def __post_init__(self) -> None:
        if self.default_timeout_seconds < 1:
            raise ValueError("default_timeout_seconds must be positive")
        if self.max_output_chars < 1_000:
            raise ValueError("max_output_chars must be at least 1000")


class BubblewrapSandboxBackend(BaseSandbox):
    """Run commands in a task-scoped Bubblewrap namespace.

    The runtime container supplies the read-only root filesystem and cgroup
    limits. This backend adds per-task namespaces, a writable `/workspace`, an
    empty `/tmp`, a clean environment and bounded inline command output.

    A host that rejects user namespaces cannot run shell commands safely.
    Workspace file tools and service-owned rendering remain available through
    the composite backend; they do not require shell execution.
    """

    def __init__(
        self,
        sandbox_id: str,
        workspace: TaskWorkspace,
        *,
        policy: BubblewrapPolicy | None = None,
        environment: Mapping[str, str] | None = None,
        runner: ProcessRunner = subprocess.run,
    ) -> None:
        self._id = sandbox_id
        self._workspace = workspace
        self._policy = policy or BubblewrapPolicy()
        self._environment = dict(environment or {})
        self._runner = runner
        # Remember the first mode that worked for this backend instance.
        self._mode: ExecuteMode | None = None
        self._unavailable: str | None = None

    @property
    def id(self) -> str:
        return self._id

    def build_argv(self, command: str, *, unshare_cgroup: bool = True) -> tuple[str, ...]:
        if not command.strip():
            raise ValueError("command must not be empty")
        workspace = str(self._workspace.root)
        argv = [
            self._policy.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
        ]
        if unshare_cgroup:
            argv.append("--unshare-cgroup")
        # The model-controlled shell never receives direct network access.
        # Data MCP and artifact storage are reached by service-owned adapters.
        argv.append("--unshare-net")
        argv.extend(
            [
                "--ro-bind",
                "/",
                "/",
                "--bind",
                workspace,
                "/workspace",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--clearenv",
                "--setenv",
                "HOME",
                "/workspace",
                "--setenv",
                "PATH",
                "/usr/local/bin:/usr/bin:/bin",
            ]
        )
        for name, value in sorted(self._environment.items()):
            if not name.isidentifier() or name.upper() != name:
                raise ValueError(f"invalid sandbox environment name: {name}")
            if any(
                marker in name for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
            ):
                raise ValueError(f"secret environment variables cannot enter the sandbox: {name}")
            argv.extend(("--setenv", name, value))
        argv.extend(("--chdir", "/workspace/working", self._policy.shell, "-lc", command))
        return tuple(argv)

    def _run_bwrap(
        self, command: str, *, timeout: int, unshare_cgroup: bool
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            self.build_argv(command, unshare_cgroup=unshare_cgroup),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={"PATH": os.environ.get("PATH", "")},
        )

    @staticmethod
    def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
        return f"{result.stdout or ''}\n{result.stderr or ''}"

    @classmethod
    def _cgroup_ns_rejected(cls, result: subprocess.CompletedProcess[str]) -> bool:
        if result.returncode == 0:
            return False
        return _CGROUP_NS_UNSUPPORTED in cls._combined_output(result)

    @classmethod
    def _user_ns_rejected(cls, result: subprocess.CompletedProcess[str]) -> bool:
        if result.returncode == 0:
            return False
        text = cls._combined_output(result)
        return any(marker in text for marker in _USER_NS_UNSUPPORTED_MARKERS)

    def _isolation_unavailable(self, reason: str) -> ExecuteResponse:
        self._unavailable = reason
        return ExecuteResponse(
            output=(f"sandbox isolation unavailable: {reason}. Shell command was not executed. "
                    "Do not retry execute. Continue with read_file/write_file/edit_file; "
                    "render_one_pager reports body character counts and required adjustments."),
            exit_code=126,
        )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._policy.default_timeout_seconds
        if effective_timeout < 1 or effective_timeout > self._policy.default_timeout_seconds:
            return ExecuteResponse(
                output=f"timeout must be between 1 and {self._policy.default_timeout_seconds} seconds",
                exit_code=2,
            )

        if self._unavailable:
            return self._isolation_unavailable(self._unavailable)
        modes: list[ExecuteMode] = (
            ["bwrap_no_cgroup"] if self._mode == "bwrap_no_cgroup"
            else ["bwrap", "bwrap_no_cgroup"]
        )

        result: subprocess.CompletedProcess[str] | None = None
        try:
            for mode in modes:
                try:
                    candidate = self._run_bwrap(
                        command, timeout=effective_timeout, unshare_cgroup=mode == "bwrap"
                    )
                except FileNotFoundError:
                    return self._isolation_unavailable("bubblewrap executable is unavailable")
                result = candidate
                if candidate.returncode == 0:
                    if self._mode != mode and mode != "bwrap":
                        logger.warning(
                            "sandbox execute recovered via mode=%s sandbox_id=%s",
                            mode,
                            self._id,
                        )
                    self._mode = mode
                    break
                if mode == "bwrap" and self._cgroup_ns_rejected(candidate):
                    continue
                if mode in {"bwrap", "bwrap_no_cgroup"} and self._user_ns_rejected(candidate):
                    return self._isolation_unavailable("host rejected user namespaces")
                # Real command failure under a working launcher: stick with it.
                self._mode = mode
                break
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"command timed out after {effective_timeout} seconds",
                exit_code=124,
            )

        assert result is not None
        output = result.stdout or ""
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if len(output) <= self._policy.max_output_chars:
            return ExecuteResponse(output=output, exit_code=result.returncode, truncated=False)

        reference = f"/workspace/logs/tool-results/{self._id}.log"
        self._workspace.write_text(reference, output)
        preview = output[: self._policy.max_output_chars]
        return ExecuteResponse(
            output=f"{preview}\n[output truncated; full output: {reference}]",
            exit_code=result.returncode,
            truncated=True,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                self._workspace.write_bytes(path, content)
                responses.append(FileUploadResponse(path=path))
            except WorkspacePolicyError:
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except WorkspaceQuotaExceeded:
                # Deep Agents exposes a closed error vocabulary for transfers.
                # Preserve protocol compatibility; the workspace exception/audit
                # layer retains the more specific quota reason.
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except OSError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                responses.append(
                    FileDownloadResponse(path=path, content=self._workspace.read_bytes(path))
                )
            except FileNotFoundError:
                responses.append(FileDownloadResponse(path=path, error="file_not_found"))
            except WorkspacePolicyError:
                responses.append(FileDownloadResponse(path=path, error="permission_denied"))
            except OSError:
                responses.append(FileDownloadResponse(path=path, error="invalid_path"))
        return responses
