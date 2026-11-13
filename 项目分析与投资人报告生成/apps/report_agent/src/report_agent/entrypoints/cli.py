"""Offline Phase 0 smoke command; it never calls a remote model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from report_agent.domain.identifiers import RunIdentity
from report_agent.runtime.workspace import TaskWorkspace


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Report Agent Phase 0 runtime")
    parser.add_argument("--workspace-root", type=Path, required=True)
    args = parser.parse_args()

    identity = RunIdentity.create()
    workspace = TaskWorkspace(args.workspace_root / identity.workspace_id)
    workspace.initialize()
    record = workspace.write_text("/workspace/working/hello.txt", "report-agent-ready\n")
    print(
        json.dumps(
            {
                "status": "ok",
                "task_id": identity.task_id,
                "session_id": identity.session_id,
                "run_id": identity.run_id,
                "workspace_id": identity.workspace_id,
                "file": record.path,
                "sha256": record.sha256,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
