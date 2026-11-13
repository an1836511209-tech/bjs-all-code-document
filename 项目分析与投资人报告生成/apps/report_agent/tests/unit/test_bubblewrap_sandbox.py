"""Namespace recovery must preserve isolation and the workspace mapping."""

from __future__ import annotations

import subprocess

import pytest

from report_agent.runtime.sandbox import BubblewrapSandboxBackend, build_workspace_backend
from report_agent.runtime.workspace import TaskWorkspace


def _workspace(tmp_path):
    workspace = TaskWorkspace(tmp_path)
    workspace.initialize()
    return workspace


def test_build_argv_can_omit_unshare_cgroup(tmp_path):
    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path))
    with_cgroup = backend.build_argv("echo ok", unshare_cgroup=True)
    without = backend.build_argv("echo ok", unshare_cgroup=False)
    assert "--unshare-cgroup" in with_cgroup
    assert "--unshare-cgroup" not in without
    assert "--unshare-net" in without
    assert "--unshare-user" in without
    for argv in (with_cgroup, without):
        bind = argv.index("--bind")
        assert argv[bind + 1:bind + 3] == (str(backend._workspace.root), "/workspace")
        assert ("--ro-bind", "/", "/") == argv[argv.index("--ro-bind"):argv.index("--ro-bind") + 3]


def test_execute_retries_without_cgroup_ns_when_kernel_rejects(tmp_path):
    calls: list[tuple[str, ...]] = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        if argv and argv[0] == "bwrap" and "--unshare-cgroup" in argv:
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="",
                stderr="bwrap: Cannot create new cgroup namespace because the kernel does not support it\n",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="核心产品 240\n", stderr="")

    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path), runner=runner)
    first = backend.execute("python3 -c 'print(1)'")
    assert first.exit_code == 0
    assert "核心产品 240" in first.output
    assert len(calls) == 2
    assert calls[0][0] == "bwrap" and "--unshare-cgroup" in calls[0]
    assert calls[1][0] == "bwrap" and "--unshare-cgroup" not in calls[1]

    second = backend.execute("python3 -c 'print(2)'")
    assert second.exit_code == 0
    assert len(calls) == 3
    assert calls[2][0] == "bwrap" and "--unshare-cgroup" not in calls[2]


def test_execute_never_runs_unisolated_when_user_ns_rejected(tmp_path):
    calls: list[tuple[str, ...]] = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        if argv and argv[0] == "bwrap":
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="",
                stderr=(
                    "bwrap: Creating new namespace failed, likely because the kernel "
                    "does not support user namespaces.  bwrap must be installed setuid "
                    "on such systems.\n"
                ),
            )
        pytest.fail("a shell must never run without bubblewrap")

    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path), runner=runner)
    first = backend.execute("python3 -c 'print(42)'")
    assert first.exit_code == 126
    assert "Shell command was not executed" in first.output
    assert "read_file/write_file/edit_file" in first.output
    assert len(calls) == 1 and calls[0][0] == "bwrap"

    before = len(calls)
    second = backend.execute("python3 -c 'print(42)'")
    assert second.exit_code == 126
    assert len(calls) == before


def test_missing_bubblewrap_never_falls_back_to_shell(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        if argv[0] == "bwrap":
            raise FileNotFoundError("bwrap")
        pytest.fail("a shell must never run without bubblewrap")

    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path), runner=runner)
    assert backend.execute("echo unsafe").exit_code == 126
    assert len(calls) == 1


def test_command_failure_does_not_retry_or_disable_sandbox(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="missing input")

    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path), runner=runner)
    result = backend.execute("exit 2")
    assert result.exit_code == 2
    assert len(calls) == 1
    assert backend.execute("exit 2").exit_code == 2
    assert len(calls) == 2 and all(call[0] == "bwrap" for call in calls)


def test_workspace_files_remain_usable_after_shell_isolation_failure(tmp_path):
    workspace = _workspace(tmp_path)
    backend = build_workspace_backend("sbx", workspace, backend="bubblewrap")

    def runner(argv, **kwargs):
        assert argv[0] == "bwrap"
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Creating new namespace failed")

    backend.default._runner = runner
    assert backend.execute("echo unused").exit_code == 126
    path = "/workspace/report/one-pager.md"
    assert backend.write(path, "正文内容").error is None
    assert backend.edit(path, "正文内容", "修订正文").error is None
    result = backend.read(path)
    assert result.error is None
    assert workspace.read_text(path) == "修订正文"


def test_execute_keeps_cgroup_ns_when_supported(tmp_path):
    calls: list[tuple[str, ...]] = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    backend = BubblewrapSandboxBackend("sbx", _workspace(tmp_path), runner=runner)
    result = backend.execute("true")
    assert result.exit_code == 0
    assert result.output.strip() == "ok"
    assert len(calls) == 1
    assert "--unshare-cgroup" in calls[0]

    backend.execute("true")
    assert len(calls) == 2
    assert "--unshare-cgroup" in calls[1]
