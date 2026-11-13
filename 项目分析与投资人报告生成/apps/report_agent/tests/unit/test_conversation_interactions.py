"""Question answers remain in the same task, including after a process restart."""
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from report_agent.api.app import create_app
from report_agent.application.bootstrap import _resolve_skill_name, _summarize_tool_output
from report_agent.application.conversation_store import WorkspaceConversationStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.interactions import question_payload, read_interaction
from report_agent.application.runs import RunConflict, SynchronousRunService, UploadedMaterial
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware
from report_agent.harness.one_pager_tools import _parse_user_hint
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace
from report_agent.settings import load_settings
from report_agent.skills import SkillCatalog


@pytest.mark.parametrize(('question', 'values'), [
    ('当前项目是增资还是股权项目？', ['产权', '增资']),
    ('本项目是否为北交互联正在披露的项目？', ['yes', 'no', 'unknown']),
    ('请补充公司全称', []),
])
def test_legacy_questions_have_meaningful_controls(question, values):
    payload = question_payload(question, None, 'run_test')
    assert [o['value'] for o in payload['options']] == values
    assert payload['kind'] == ('business_type' if values == ['产权', '增资'] else 'cbex_listing' if values else 'text')


def test_known_questions_override_inappropriate_generic_confirmation_options():
    for text, values in [('当前项目是增资还是股权项目？', ['产权','增资']),
                         ('是否为北交互联正在披露的项目？', ['yes','no','unknown'])]:
        payload = question_payload(text, {'options':[{'value':'confirm','label':'确认无误'}]}, 'run_test')
        assert [o['value'] for o in payload['options']] == values


@pytest.mark.asyncio
async def test_answer_and_supplement_preserve_task_skill_materials_and_memory(tmp_path):
    seen = []
    async def executor(identity, workspace, message, *, selected_skill=''):
        seen.append((identity.task_id, selected_skill, WorkspaceConversationStore(workspace).messages()))
        return {'messages': [AIMessage(content='当前项目是增资还是股权项目？')], 'skill_name':'one-pager'}
    bus = RunEventBus()
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository(), event_bus=bus)
    first = await service.submit('生成一页纸BP', [UploadedMaterial(filename='a.txt', content=b'original')])
    await service.drain()
    workspace = TaskWorkspace(tmp_path / first.task_id)
    question = read_interaction(workspace)['pending_question']
    second = await service.submit('请保留原有管理团队', [], task_id=first.task_id,
                                  question_id=question['question_id'], choice_value='增资')
    await service.drain()
    assert first.task_id == second.task_id
    assert first.run_id != second.run_id
    assert first.session_id == second.session_id
    assert seen[1][1] == 'one-pager'
    assert seen[1][2][0]['content'] == '生成一页纸BP'
    assert '增资' in seen[1][2][-1]['content']
    assert '请保留原有管理团队' in seen[1][2][-1]['content']
    assert workspace.read_bytes('/workspace/input/01-a.txt') == b'original'
    assert bus.is_terminal(first.run_id)
    with pytest.raises(RunConflict):
        await service.submit('重复点击', [], task_id=first.task_id, question_id=question['question_id'])


@pytest.mark.asyncio
async def test_resume_after_restart_keeps_workspace_and_question_context(tmp_path):
    async def executor(identity, workspace, message, *, selected_skill=''):
        return {'messages':[AIMessage(content='本项目是否为北交互联正在披露的项目？')], 'skill_name':'one-pager'}
    first_service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await first_service.submit('生成一页纸BP', [])
    await first_service.drain()
    restarted = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    question = read_interaction(TaskWorkspace(tmp_path / first.task_id))['pending_question']
    with pytest.raises(ValueError, match='项目全称'):
        await restarted.submit('', [], task_id=first.task_id, question_id=question['question_id'], choice_value='yes')
    resumed = await restarted.submit('某某有限公司100%股权转让', [], task_id=first.task_id,
                                     question_id=question['question_id'], choice_value='yes')
    await restarted.drain()
    assert resumed.task_id == first.task_id
    turns = WorkspaceConversationStore(TaskWorkspace(tmp_path / first.task_id)).turns()
    assert '北交互联' in turns[-2]['text'] and '某某有限公司100%股权转让' in turns[-2]['text']
    assert len([t for t in turns if t['role'] == 'user']) == 2


@pytest.mark.asyncio
async def test_duplicate_run_and_stale_task_are_rejected(tmp_path):
    import asyncio
    release = asyncio.Event()
    async def executor(identity, workspace, message, *, selected_skill=''):
        await release.wait()
        return {'messages':[AIMessage(content='问题')], 'skill_name':'one-pager'}
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('一页纸', [])
    with pytest.raises(RunConflict):
        await service.submit('补充', [], task_id=first.task_id)
    release.set()
    await service.drain()
    with pytest.raises(RunConflict):
        await service.submit('补充', [], task_id='task_' + 'a' * 32)


@pytest.mark.asyncio
async def test_api_choice_plus_free_text_and_snapshot_and_sse_cursor(tmp_path):
    async def executor(identity, workspace, message, *, selected_skill=''):
        return {'messages':[AIMessage(content='当前项目是增资还是股权项目？')], 'skill_name':'one-pager'}
    bus = RunEventBus()
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository(), event_bus=bus)
    async with AsyncClient(transport=ASGITransport(app=create_app(service, dev_ui_enabled=True, event_bus=bus)), base_url='http://test') as client:
        first = (await client.post('/api/dev/runs', data={'message':'一页纸BP'})).json()
        await service.drain()
        state = (await client.get(f"/api/tasks/{first['task_id']}/state")).json()
        assert state['active_skill'] == 'one-pager'
        qid = state['pending_question']['question_id']
        second_response = await client.post('/api/dev/runs', data={
            'task_id':first['task_id'], 'question_id':qid, 'choice_value':'产权', 'message':'转让比例为30%'
        })
        assert second_response.status_code == 202
        assert second_response.json()['task_id'] == first['task_id']
        await service.drain()
        state = (await client.get(f"/api/tasks/{first['task_id']}/state")).json()
        assert '转让比例为30%' in state['turns'][-2]['text']
        stale = await client.post('/api/dev/runs', data={'task_id':first['task_id'], 'question_id':qid, 'message':'再回答'})
        assert stale.status_code == 409
        stream = await client.get(f"/api/runs/{first['run_id']}/events", headers={'Last-Event-ID':'1'})
        assert 'id: 1\n' not in stream.text
        assert 'approval.required' in stream.text


@pytest.mark.asyncio
async def test_ask_user_stops_graph_and_filters_mixed_tool_calls():
    message = AIMessage(id='model-message', content='', tool_calls=[
        {'id':'q', 'name':'ask_user', 'args':{'question':'项目类型？'}},
        {'id':'publish', 'name':'render_one_pager', 'args':{}},
    ])
    result = await QuestionBoundaryMiddleware().aafter_model({'messages':[message]}, None)
    assert [c['name'] for c in result['messages'][0].tool_calls] == ['ask_user']
    assert result['messages'][0].id == message.id
    tool = build_ask_user_tools()[0]
    assert tool.return_direct
    data = json.loads(await tool.ainvoke({'question':'项目类型？'}))
    assert data['status'] == 'needs_user_input'


@pytest.mark.parametrize('hint', ['股权转让', '股权转让（产权）', '产权'])
def test_property_answers_are_normalized(hint):
    assert _parse_user_hint(hint).value == '产权'


def test_keywords_and_structured_status():
    settings = load_settings(Path('deploy/environments/test/report-agent.local.yaml'))
    available = SkillCatalog([Path('apps/report_agent/skills')]).discover()
    assert _resolve_skill_name(settings, '单页BP', available=available)[0] == 'one-pager'
    assert _summarize_tool_output('{"status":"ok","errors":[]}')[0] == 'success'
    assert _summarize_tool_output('{"status":"needs_user_input"}')[0] == 'waiting'


@pytest.mark.asyncio
async def test_agent_graph_exits_on_question_before_other_tools_can_run():
    from langchain.agents import create_agent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import StructuredTool

    called = []
    class QuestionModel(BaseChatModel):
        @property
        def _llm_type(self):
            return 'question-test'

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            called.append('model')
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[
                {'id':'ask', 'name':'ask_user', 'args':{'question':'当前项目是增资还是股权项目？'}},
                {'id':'publish', 'name':'publish_test', 'args':{}},
            ]))])

    def publish_test() -> str:
        """A side effect which must never run while asking a question."""
        called.append('published')
        return 'published'

    agent = create_agent(model=QuestionModel(), tools=[*build_ask_user_tools(), StructuredTool.from_function(publish_test)],
                         middleware=[QuestionBoundaryMiddleware()])
    result = await agent.ainvoke({'messages':[{'role':'user','content':'生成一页纸'}]}, {'recursion_limit':5})
    assert called == ['model']
    assert result['messages'][-1].name == 'ask_user'


@pytest.mark.asyncio
async def test_restart_can_download_previous_artifact_after_more_questions(tmp_path):
    from datetime import UTC, datetime, timedelta
    artifact = {'artifact_id':'artifact_'+'a'*32, 'filename':'bp.docx', 'size':4,
                'sha256':'b'*64, 'bucket':'reports', 'object_key':'bp.docx',
                'download_url':'https://example.test/signed', 'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}
    async def executor(identity, workspace, message, *, selected_skill=''):
        return {'messages':[], 'skill_name':'one-pager', 'artifacts':[artifact]}
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('一页纸', [])
    await service.drain()
    async def question_executor(identity, workspace, message, *, selected_skill=''):
        return {'messages':[AIMessage(content='请补充公司全称')], 'skill_name':'one-pager'}
    restarted = SynchronousRunService(tmp_path, question_executor, InMemoryRunRepository())
    await restarted.submit('补充另一个版本', [], task_id=first.task_id)
    await restarted.drain()
    class Artifacts:
        def read_object(self, bucket, key):
            return b'docx'
    client_app = create_app(restarted, dev_ui_enabled=True, artifact_service=Artifacts())
    async with AsyncClient(transport=ASGITransport(app=client_app), base_url='http://test') as client:
        response = await client.get(f"/api/artifacts/{artifact['artifact_id']}/content")
        assert response.status_code == 200
        assert response.content == b'docx'
