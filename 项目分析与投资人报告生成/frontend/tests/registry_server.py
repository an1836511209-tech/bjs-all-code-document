"""Isolated optional-registry browser fixture; no real company lookup or model."""
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from langchain_core.messages import ToolMessage
from report_agent.api.app import create_app
from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.events import EventType
from report_agent.domain.evidence import EvidenceView
from report_agent.harness.data_tools import _build_tool
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

bus = RunEventBus()
calls = []
EXACT = '精确登记名称科技有限公司'


class Gateway:
    contracts = SimpleNamespace(description=lambda _: '工商查询', input_schema=lambda _: {
        'type': 'object', 'properties': {'company_name': {'type': 'string'}}})

    async def call(self, name, arguments):
        calls.append(arguments['company_name'])
        return EvidenceView(evidence_id='evidence_' + 'a' * 32, tool=name,
                            status='success' if arguments['company_name'] == EXACT else 'empty',
                            summary='模拟工商结果', warnings=(), path='/workspace/evidence/test.json',
                            sha256='a' * 64, size_bytes=10, json_roots=('/data/company',))


async def executor(identity, workspace, message, *, selected_skill=''):
    WorkspaceContextStore(workspace).initialize(identity, message)
    bus.emit(identity, EventType.SKILL_ACTIVATED, {'skill': 'one-pager'})
    output = await _build_tool(Gateway(), 'query_company_registry', workspace).ainvoke({'company_name': '企业简称'})
    result = {'messages': [ToolMessage(name='query_company_registry', tool_call_id='r', content=output)],
              'skill_name': 'one-pager'}
    if not json.loads(output).get('question_request'):
        artifact = {'artifact_id': 'artifact_' + identity.run_id.removeprefix('run_'), 'filename': '继续后的报告.docx',
                    'sha256': 'b' * 64, 'size': 4, 'bucket': 'test', 'object_key': 'test.docx',
                    'download_url': 'http://unused.test/test.docx',
                    'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
        result['artifacts'] = [artifact]
        bus.emit(identity, EventType.ARTIFACT_CREATED, {**artifact, 'size_bytes': 4})
    return result


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='registry-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus)


@app.get('/test/registry_calls')
async def registry_calls():
    return calls


uvicorn.run(app, host='127.0.0.1', port=8019, log_level='warning')
