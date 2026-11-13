"""Isolated disclosure/candidate interaction fixture; no external data calls."""
import json
import tempfile
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
PROJECT = '某某科技有限公司100%股权转让'
URL = 'https://otc.cbex.com/cgq/detail/1001.html'


class Gateway:
    contracts = SimpleNamespace(description=lambda _: '挂牌财务', input_schema=lambda _: {
        'type': 'object', 'properties': {'project_name': {'type': 'string'}, 'detail_url': {'type': 'string'}}})

    def __init__(self, workspace):
        self.workspace = workspace

    async def call(self, name, arguments):
        calls.append(arguments)
        candidates = [] if arguments.get('detail_url') else [
            {'project_name': PROJECT, 'detail_url': URL, 'project_type': '产权转让（国资）',
             'disclosure_end_date': '2026-12-31', 'match_score': 100},
            {'project_name': PROJECT + '（二次挂牌）', 'detail_url': URL.replace('1001', '1002'),
             'project_type': '产权转让（非国资）', 'disclosure_end_date': '', 'match_score': 90}]
        path = '/workspace/working/cbex-test.json'
        self.workspace.write_text(path, json.dumps({'data': {'candidates': candidates}}))
        return EvidenceView('evidence_' + 'a'*32, name, 'success', '模拟财务查询', (), path, 'b'*64, 10, ())


async def executor(identity, workspace, message, *, selected_skill=''):
    WorkspaceContextStore(workspace).initialize(identity, message)
    bus.emit(identity, EventType.SKILL_ACTIVATED, {'skill': 'one-pager'})
    output = await _build_tool(Gateway(workspace), 'query_cbex_listing_financials', workspace).ainvoke(
        {'project_name': '模型错误简称'})
    result = {'skill_name': 'one-pager', 'messages': [ToolMessage(
        name='query_cbex_listing_financials', tool_call_id='cbex', content=output)]}
    if not json.loads(output).get('question_request'):
        result['skill_name'] = 'chat'
    return result


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='cbex-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus)


@app.get('/test/cbex_calls')
async def cbex_calls():
    return calls


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8026, log_level='warning')
