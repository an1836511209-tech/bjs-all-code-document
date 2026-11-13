"""Workspace manifest updates stay one JSON document under concurrent writes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor


def test_concurrent_writes_keep_every_file_in_one_manifest(tmp_path):
    from report_agent.runtime.workspace import TaskWorkspace

    workspace = TaskWorkspace(tmp_path / "task")
    workspace.initialize()

    def write(index: int) -> None:
        workspace.write_text(f"/workspace/output/file-{index}.txt", f"body-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(40)))

    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    recorded = {path for path in manifest["files"] if "/workspace/output/" in path}
    assert recorded == {f"/workspace/output/file-{index}.txt" for index in range(40)}


def test_next_write_repairs_a_manifest_with_a_duplicated_tail(tmp_path):
    from report_agent.runtime.workspace import TaskWorkspace

    workspace = TaskWorkspace(tmp_path / "task")
    workspace.initialize()
    workspace.write_text("/workspace/output/a.txt", "a")
    original = workspace.manifest_path.read_text(encoding="utf-8")
    assert original.rstrip().endswith("}")
    workspace.manifest_path.write_text(
        original.rstrip() + "}\n  },\n  \"trash\": {}\n}\n",
        encoding="utf-8",
    )

    workspace.write_text("/workspace/output/b.txt", "b")

    text = workspace.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert "/workspace/output/a.txt" in manifest["files"]
    assert "/workspace/output/b.txt" in manifest["files"]
    assert text.count('"trash"') == 1
