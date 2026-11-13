"""Undecidable business types produce a deterministic card without a model asking."""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.application.interactions import (
    question_payload,
    read_interaction,
    update_interaction,
)
from report_agent.application.runs import RunConflict, SynchronousRunService
from report_agent.harness.ask_user_tools import build_ask_user_tools
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware
from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace


def tools_at(root):
    workspace = TaskWorkspace(root)
    workspace.initialize()
    workspace.write_text('/workspace/report/material.txt', '公司开发核心产品，为客户提供技术服务。')
    service = MagicMock()
    tools = {tool.name:tool for tool in build_one_pager_tools(workspace,service=service)}
    return workspace, service, tools


def test_ambiguous_detection_carries_fixed_question_and_ignores_model_guess(tmp_path):
    workspace, _, tools = tools_at(tmp_path)
    result = json.loads(tools['detect_one_pager_business_type'].invoke({
        'material_path':'/workspace/report/material.txt', 'user_hint':'增资'}))
    assert result['status'] == 'needs_user_input'
    card = question_payload('请确认', result['question_request'], 'run_test')
    assert card['kind'] == 'business_type'
    assert [o['value'] for o in card['options']] == ['产权','增资']
    assert read_interaction(workspace)['business_type_selection']['value'] is None


def test_screenshot_direct_ask_without_options_is_normalized_at_tool_boundary():
    output = json.loads(build_ask_user_tools()[0].invoke({
        'question':'本项目属于哪种业务类型？',
        'context':'材料是公司简介PPT，但没有明确说明是股权转让还是增资扩股。业务类型决定报告模板。',
        'options':[], 'allow_free_text':False,
    }))
    assert output['kind'] == 'business_type'
    assert output['gate'] == 'one_pager_business_type'
    assert [option['value'] for option in output['options']] == ['产权','增资']
    assert output['allow_free_text']
    assert '公司简介PPT' in output['context']


@pytest.mark.parametrize('question,context', [
    ('本项目属于哪种业务类型？',''),
    ('请选择交易类型',''),
    ('这个项目属于哪一类？','材料没有说明是股权转让还是增资扩股'),
])
def test_business_question_wording_variants(question,context):
    payload = question_payload(question,{'context':context,'options':[],'allow_free_text':False},'run_test')
    assert payload['kind'] == 'business_type'
    assert len(payload['options']) == 2


def test_unknown_closed_question_without_options_still_has_an_answer_channel():
    output = json.loads(build_ask_user_tools()[0].invoke({
        'question':'请补充项目简称','options':[],'allow_free_text':False,
    }))
    assert output['kind'] == 'text'
    assert output['allow_free_text']


@pytest.mark.asyncio
async def test_saved_screenshot_question_is_repaired_and_can_resume_same_task(tmp_path):
    async def executor(identity,workspace,message,*,selected_skill=''):
        return {'skill_name':'chat','messages':[AIMessage(content='已接收选择')]}
    workspace, _, _ = tools_at(tmp_path/('task_'+'a'*32))
    run_id = 'run_'+'b'*32
    old = {'question_id':'original-question-id','approval_id':'original-question-id','run_id':run_id,
           'kind':'text','question':'本项目属于哪种业务类型？','context':'没有说明是股权转让还是增资扩股',
           'options':[],'allow_free_text':False}
    workspace.write_text('/workspace/state/interaction.json',json.dumps({
        'run_id':run_id,'status':'needs_input','active_skill':'one-pager','pending_question':old,
    },ensure_ascii=False))
    repaired = read_interaction(workspace)['pending_question']
    assert repaired['question_id'] == old['question_id']
    assert repaired['kind'] == 'business_type'
    assert len(repaired['options']) == 2
    service = SynchronousRunService(tmp_path,executor,InMemoryRunRepository())
    accepted = await service.submit('保留公司介绍',[],task_id=workspace.root.name,
                                    question_id=old['question_id'],choice_value='增资')
    await service.drain()
    assert accepted.task_id == workspace.root.name
    assert read_interaction(workspace)['business_type_selection']['value'] == '增资'


def test_confirmed_choice_wins_over_new_model_guess_and_filename(tmp_path):
    workspace, _, tools = tools_at(tmp_path)
    update_interaction(workspace,business_type_selection={'value':'产权','source':'user'})
    result = json.loads(tools['detect_one_pager_business_type'].invoke({
        'material_path':'/workspace/report/material.txt','filename':'增资.docx','user_hint':'增资'}))
    assert result['business_type'] == '产权'
    assert result['confidence'] == 'user'
    assert 'question_request' not in result
    assert result['conflict']


def test_filename_from_material_path_when_arg_omitted(tmp_path):
    """UAT: resume often re-calls detect without filename; basename must still decide."""
    workspace, _, tools = tools_at(tmp_path)
    path = '/workspace/report/普天科创100%股权转让项目情况介绍.txt'
    workspace.write_text(path, '公司开发核心产品，为客户提供技术服务。')
    result = json.loads(tools['detect_one_pager_business_type'].invoke({'material_path': path}))
    assert result['status'] == 'ok'
    assert result['business_type'] == '产权'
    assert result['confidence'] == 'filename'
    assert 'question_request' not in result
    assert read_interaction(workspace)['business_type_selection']['value'] == '产权'


def test_prior_filename_decision_survives_undecidable_re_detect(tmp_path):
    """UAT: a later undecidable detect must not wipe or re-ask after filename decided."""
    workspace, _, tools = tools_at(tmp_path)
    first = json.loads(tools['detect_one_pager_business_type'].invoke({
        'material_path': '/workspace/report/material.txt',
        'filename': '普天科创股权转让项目.pdf',
    }))
    assert first['status'] == 'ok' and first['business_type'] == '产权'
    assert read_interaction(workspace)['business_type_selection']['source'] == 'filename'

    second = json.loads(tools['detect_one_pager_business_type'].invoke({
        'material_path': '/workspace/report/material.txt',
        # No transferable filename cue; material text alone is ambiguous.
        'filename': '材料.pdf',
    }))
    assert second['status'] == 'ok'
    assert second['business_type'] == '产权'
    assert 'question_request' not in second
    stored = read_interaction(workspace)['business_type_selection']
    assert stored['value'] == '产权'
    assert stored['source'] == 'filename'


def test_unreadable_material_is_an_error_not_a_business_type_question(tmp_path):
    _, _, tools = tools_at(tmp_path)
    result = json.loads(tools['detect_one_pager_business_type'].invoke({'material_path':'/workspace/report/missing.txt'}))
    assert result['status'] == 'failed'
    assert 'question_request' not in result


def test_render_cannot_bypass_detection_or_change_confirmed_template(tmp_path):
    workspace, service, tools = tools_at(tmp_path)
    arguments = {'md_path':'/workspace/report/bp.md','business_type':'产权','report_id':'test','filename':'bp.docx'}
    result = json.loads(tools['render_one_pager'].invoke(arguments))
    assert result['question_request']['gate'] == 'one_pager_business_type'
    service.render.assert_not_called()
    update_interaction(workspace,business_type_selection={'value':'增资','source':'user'})
    result = json.loads(tools['render_one_pager'].invoke(arguments))
    assert result['status'] == 'invalid_arguments' and result['allowed'] == ['增资']
    service.render.assert_not_called()


@pytest.mark.asyncio
async def test_detection_ends_real_graph_before_model_can_guess_or_publish(tmp_path):
    from langchain.agents import create_agent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import StructuredTool
    _, _, tools = tools_at(tmp_path)
    calls = []
    class Model(BaseChatModel):
        @property
        def _llm_type(self): return 'type-test'
        def bind_tools(self,tools,**kwargs): return self
        def _generate(self,messages,stop=None,run_manager=None,**kwargs):
            calls.append('model')
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[
                {'id':'d','name':'detect_one_pager_business_type','args':{'material_path':'/workspace/report/material.txt'}},
                {'id':'p','name':'publish_test','args':{}},
            ]))])
    def publish_test() -> str:
        """This side effect must wait until the user chooses a business type."""
        calls.append('published')
        return 'published'
    agent = create_agent(Model(), tools=[tools['detect_one_pager_business_type'],StructuredTool.from_function(publish_test)],
                         middleware=[QuestionBoundaryMiddleware()])
    result = await agent.ainvoke({'messages':[{'role':'user','content':'一页纸'}]}, {'recursion_limit':10})
    assert calls == ['model']
    assert json.loads(result['messages'][-1].content)['question_request']['kind'] == 'business_type'


@pytest.mark.asyncio
async def test_answer_persists_and_continues_same_task_after_restart(tmp_path):
    async def executor(identity,workspace,message,*,selected_skill=''):
        _, _, tools = tools_at(workspace.root)
        output = tools['detect_one_pager_business_type'].invoke({'material_path':'/workspace/report/material.txt','user_hint':'产权'})
        data = json.loads(output)
        result = {'messages':[ToolMessage(name='detect_one_pager_business_type',tool_call_id='d',content=output)],'skill_name':'one-pager'}
        if data['status'] == 'ok':
            result['artifacts'] = [{'artifact_id':'artifact_'+'a'*32,'filename':data['business_type']+'.docx',
                'sha256':'b'*64,'size':10,'bucket':'test','object_key':'test.docx','download_url':'http://unused.test/bp.docx',
                'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}]
        return result
    service = SynchronousRunService(tmp_path,executor,InMemoryRunRepository())
    first = await service.submit('一页纸',[])
    await service.drain()
    workspace = TaskWorkspace(tmp_path/first.task_id)
    question = read_interaction(workspace)['pending_question']
    for invalid in ['继续','skip','增资或产权都可以']:
        with pytest.raises(ValueError,match='明确选择'):
            await service.submit(invalid,[],task_id=first.task_id,question_id=question['question_id'])
    restarted = SynchronousRunService(tmp_path,executor,InMemoryRunRepository())
    second = await restarted.resume(first.run_id,'增资扩股')
    await restarted.drain()
    assert second.task_id == first.task_id and second.session_id == first.session_id
    state = read_interaction(workspace)
    assert state['business_type_selection']['value'] == '增资'
    assert state['pending_question'] is None
    assert state['status'] == 'completed'
    with pytest.raises(RunConflict):
        await restarted.resume(first.run_id,'产权')
