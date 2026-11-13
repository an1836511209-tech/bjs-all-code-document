"""Repeatable Linux runtime smoke test for the Bubblewrap security boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from report_agent.runtime import BubblewrapSandboxBackend, TaskWorkspace


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Bubblewrap runtime boundary")
    parser.add_argument("--workspace-root", type=Path, required=True)
    args = parser.parse_args()

    smoke_id = f"sandbox-smoke-{uuid4().hex}"
    workspace = TaskWorkspace(args.workspace_root / smoke_id)
    workspace.initialize()
    backend = BubblewrapSandboxBackend(smoke_id, workspace)
    allowed = backend.execute("printf sandboxed > /workspace/working/result.txt")
    denied = backend.execute("printf escaped > /usr/local/report-agent-escaped.txt")
    passed = (
        allowed.exit_code == 0
        and denied.exit_code not in {None, 0}
        and workspace.read_text("/workspace/working/result.txt") == "sandboxed"
    )
    print(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "sandbox_id": smoke_id,
                "workspace_write_exit_code": allowed.exit_code,
                "root_write_exit_code": denied.exit_code,
            }
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
