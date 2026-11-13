"""Synthetic multi-task publication API for download-link browser regression."""
import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessage
from report_agent.api.app import create_app
from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.events import EventType
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

bus = RunEventBus()


async def executor(identity, workspace, message, *, selected_skill=''):
    WorkspaceContextStore(workspace).initialize(identity, message)
    await asyncio.sleep(.1)
    artifact_id = 'artifact_' + identity.run_id.removeprefix('run_')
    filename = message + '.docx'
    artifact = {
        'artifact_id': artifact_id, 'filename': filename, 'size': 100, 'sha256': 'a' * 64,
        'bucket': 'qa', 'object_key': f'{identity.task_id}/{artifact_id}/{filename}',
        'download_url': 'http://unused.test/expired.docx?X-Amz-Signature=stale',
        'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    bus.emit(identity, EventType.SKILL_ACTIVATED, {'skill': 'one-pager'})
    bus.emit(identity, EventType.ARTIFACT_CREATED, {**artifact, 'size_bytes': 100, 'kind': 'docx'})
    return {'messages': [AIMessage(content='测试发布')], 'skill_name': 'one-pager', 'artifacts': [artifact]}


class Artifacts:
    def refresh_download(self, record):
        return record

    def read_object(self, bucket, key):
        return key.encode('utf-8')


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='downloads-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus, artifact_service=Artifacts())
uvicorn.run(app, host='127.0.0.1', port=8018, log_level='warning')
