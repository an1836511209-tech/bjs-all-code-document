"""Synthetic browser fixture: real Deep Agent interrupts, no remote services."""
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from report_agent.api.app import create_app
from report_agent.application.bootstrap import ConfiguredAgentExecutor
from report_agent.application.event_bus import RunEventBus
from report_agent.application.one_pager_execution import (
    COMMAND_PATH,
    execution_state,
    read_json,
)
from report_agent.application.runs import SynchronousRunService
from report_agent.harness.one_pager_checkpoint import run_checkpointed_agent
from report_agent.infrastructure.persistence.checkpoints import AsyncCheckpointAdapter
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.settings import load_settings

from apps.report_agent.tests.unit.test_one_pager_checkpoints import make_graph

bus = RunEventBus()
counts = Counter()
saver = AsyncCheckpointAdapter(InMemorySaver())
artifact = {"artifact_id": "artifact_" + "c" * 32, "filename": "checkpoint-test.docx", "size": 8,
            "sha256": "b" * 64, "bucket": "test", "object_key": "test.docx", "download_url": "https://example.invalid/download",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}


class Executor:
    def __init__(self):
        self.core = ConfiguredAgentExecutor(load_settings(Path("deploy/environments/test/report-agent.local.yaml")),
            artifact_service=SimpleNamespace(), event_bus=bus, one_pager_checkpointer=saver)

    def prepare_submission(self, *args, **kwargs):
        return self.core.prepare_submission(*args, **kwargs)

    async def __call__(self, identity, workspace, message, *, selected_skill=""):
        if not execution_state(workspace):
            return {"messages": [AIMessage(content="投资报告测试完成")], "skill_name": "investment-report", "artifacts": [artifact]}
        graph, _ = make_graph(saver, counts, workspace, deep=True, planning=True)
        command = read_json(workspace, COMMAND_PATH)
        todos = [{"content": text, "status": "completed" if i < 2 else "pending"}
                 for i, text in enumerate(["初始化", "解析材料", "补数", "投资人匹配", "写作审查", "发布"])]
        result = await run_checkpointed_agent(graph, workspace, identity,
            {"messages": [HumanMessage(id=command["id"], content=message)], "todos": todos}, self.core._run_agent)
        result["skill_name"] = "one-pager"
        result["artifacts"] = [artifact] if result["execution_status"] == "completed" else []
        return result


class Artifacts:
    def refresh_download(self, record): return record
    def read_object(self, bucket, key): return b"test-docx"


root = Path(tempfile.mkdtemp(prefix="checkpoint-ui-", dir=".runtime/diagnostics"))
service = SynchronousRunService(root, Executor(), InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus, artifact_service=Artifacts())


@app.get("/api/testing/counts")
async def diagnostics():
    return dict(counts)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8023, log_level="warning")
