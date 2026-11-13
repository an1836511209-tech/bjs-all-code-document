"""Browser fixture: real type detector and task state, synthetic published document."""
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import uvicorn
from langchain_core.messages import ToolMessage
from report_agent.api.app import create_app
from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.events import EventType
from report_agent.domain.identifiers import RunIdentity
from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace

bus = RunEventBus()
legacy_question = {'kind':'text','question':'本项目属于哪种业务类型？',
                   'context':'材料是公司简介PPT，但没有明确说明是股权转让还是增资扩股。业务类型决定模板。',
                   'options':[], 'allow_free_text':False}


async def executor(identity, workspace, message, *, selected_skill=''):
    WorkspaceContextStore(workspace).initialize(identity, message)
    workspace.write_text('/workspace/report/material.txt', '公司提供核心产品和技术服务。')
    bus.emit(identity, EventType.SKILL_ACTIVATED, {'skill': 'one-pager'})
    if message == '__legacy_empty_business_card__':
        return {'skill_name':'one-pager','messages':[ToolMessage(name='ask_user',tool_call_id='ask',
                content=json.dumps({'status':'needs_user_input',**legacy_question},ensure_ascii=False))]}
    tools = {tool.name: tool for tool in build_one_pager_tools(workspace, service=MagicMock())}
    output = tools['detect_one_pager_business_type'].invoke({'material_path': '/workspace/report/material.txt',
                                                          'user_hint': '产权'})
    data = json.loads(output)
    result = {'skill_name': 'one-pager', 'messages': [ToolMessage(
        name='detect_one_pager_business_type', tool_call_id='detect', content=output)]}
    if data['status'] == 'ok':
        artifact = {'artifact_id': 'artifact_' + identity.run_id.removeprefix('run_'),
                    'filename': data['business_type'] + '_一页纸.docx', 'size': 10, 'sha256': 'a' * 64,
                    'bucket': 'test', 'object_key': 'test.docx', 'download_url': 'http://unused.test/test.docx',
                    'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
        result['artifacts'] = [artifact]
        bus.emit(identity, EventType.ARTIFACT_CREATED, {**artifact, 'size_bytes': 10})
    return result


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='business-type-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus)


@app.post('/test/legacy-question')
async def seed_legacy_question():
    accepted = await service.submit('__legacy_empty_business_card__',[])
    await service.drain()
    workspace = TaskWorkspace(service.workspace_root/accepted.task_id)
    state = json.loads(workspace.read_text('/workspace/state/interaction.json'))
    pending = state['pending_question']
    pending.update(legacy_question)
    pending.pop('gate',None)
    workspace.write_text('/workspace/state/interaction.json',json.dumps(state,ensure_ascii=False))
    identity = RunIdentity(task_id=accepted.task_id,run_id=accepted.run_id,
                           session_id=accepted.session_id,workspace_id=state['workspace_id'])
    bus.forget(accepted.run_id)
    event = bus.emit(identity,EventType.APPROVAL_REQUIRED,pending)
    return {**accepted.model_dump(), 'pending':pending,'event':{
        'type':event.type.value,'run_id':accepted.run_id,'task_id':accepted.task_id,'seq':1,'payload':pending}}


uvicorn.run(app, host='127.0.0.1', port=8020, log_level='warning')
