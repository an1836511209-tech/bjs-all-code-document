"""An optional company lookup becomes a correct-name-or-skip notice, never a failed BP."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.application.bootstrap import _summarize_tool_output
from report_agent.application.interactions import (
    question_payload,
    read_interaction,
    update_interaction,
)
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.evidence import EvidenceView
from report_agent.harness.data_tools import _build_tool
from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace


def gateway_for(status='empty', warnings=()):
    view = EvidenceView(evidence_id='evidence_'+'a'*32, tool='query_company_registry', status=status,
                        summary='工商查询结果', warnings=warnings, path='/workspace/evidence/test.json',
                        sha256='a'*64, size_bytes=10, json_roots=('/data/company',))
    contracts = SimpleNamespace(description=lambda _: '工商查询', input_schema=lambda _: {
        'type':'object', 'required':['company_name'], 'properties':{'company_name':{'type':'string'}}})
    return SimpleNamespace(call=AsyncMock(return_value=view), contracts=contracts)


def workspace_at(root):
    workspace = TaskWorkspace(root)
    workspace.initialize()
    return workspace


def test_registry_notice_is_warning_not_a_failed_tool_line():
    output = ToolMessage(name='query_company_registry', tool_call_id='r',
                         content=json.dumps({'status':'needs_user_input','summary':'工商数据暂不可用'}))
    assert _summarize_tool_output(output)[0] == 'waiting'
    assert _summarize_tool_output({'status':'needs_user_input','summary':'工商数据暂不可用'})[0] == 'waiting'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,warnings', [
    ('empty', ()), ('failed', ()),
    ('partial', ({'code':'COMPANY_NAME_NOT_EXACT','message':'名称未精确匹配','retryable':True},)),
])
async def test_missing_or_nonexact_company_shows_optional_card(tmp_path, status, warnings):
    workspace = workspace_at(tmp_path)
    gateway = gateway_for(status, warnings)
    result = json.loads(await _build_tool(gateway, 'query_company_registry', workspace).ainvoke({'company_name':'简称'}))
    question = question_payload('', result['question_request'], 'run_test')
    assert question['kind'] == 'registry_name'
    assert question['question'] == '当前公司名称无法获取企查查数据，请提供精确名称。'
    assert [option['value'] for option in question['options']] == ['correct_name','skip']
    assert result['status'] == 'needs_user_input'


@pytest.mark.asyncio
async def test_upstream_exception_is_optional_and_does_not_expose_private_details(tmp_path):
    gateway = gateway_for()
    gateway.call.side_effect = RuntimeError('private token and upstream response')
    result = await _build_tool(gateway, 'query_company_registry', workspace_at(tmp_path)).ainvoke({'company_name':'简称'})
    assert 'private token' not in result
    assert json.loads(result)['question_request']['options'][-1]['value'] == 'skip'


@pytest.mark.asyncio
async def test_precise_name_is_used_verbatim_and_skip_never_calls_gateway(tmp_path):
    workspace = workspace_at(tmp_path)
    gateway = gateway_for('success')
    tool = _build_tool(gateway, 'query_company_registry', workspace)
    exact = '某某科技（北京）有限公司'
    update_interaction(workspace, registry_lookup={'status':'retry','company_name':exact})
    await tool.ainvoke({'company_name':'模型仍然给出的简称'})
    assert gateway.call.call_args.args[1]['company_name'] == exact
    update_interaction(workspace, registry_lookup={'status':'skipped'})
    gateway.call.reset_mock()
    result = json.loads(await tool.ainvoke({'company_name':'另一个简称'}))
    assert result['status'] == 'skipped'
    gateway.call.assert_not_called()


@pytest.mark.asyncio
async def test_registry_warning_ends_graph_before_model_or_dependent_publish(tmp_path):
    from langchain.agents import create_agent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import StructuredTool

    called = []
    class RegistryModel(BaseChatModel):
        @property
        def _llm_type(self):
            return 'registry-test'
        def bind_tools(self, tools, **kwargs):
            return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            called.append('model')
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[
                {'id':'registry','name':'query_company_registry','args':{'company_name':'简称'}},
                {'id':'publish','name':'publish_test','args':{}},
            ]))])
    def publish_test() -> str:
        """A dependent step which must wait for the optional lookup choice."""
        called.append('publish')
        return 'published'
    tool = _build_tool(gateway_for(), 'query_company_registry', workspace_at(tmp_path))
    agent = create_agent(RegistryModel(), tools=[tool, StructuredTool.from_function(publish_test)],
                         middleware=[QuestionBoundaryMiddleware()])
    result = await agent.ainvoke({'messages':[{'role':'user','content':'生成一页纸'}]}, {'recursion_limit':10})
    assert called == ['model']
    assert json.loads(result['messages'][-1].content)['question_request']['gate'] == 'company_registry'


@pytest.mark.asyncio
async def test_investment_report_registry_failure_opens_name_card(tmp_path):
    """数据源返回 failed 后，模型提问不能被收成「报告未发布」。"""
    async def executor(identity, workspace, message, *, selected_skill=''):
        return {'skill_name': 'investment-report', 'messages': [
            ToolMessage(
                name='query_company_registry', tool_call_id='registry',
                content=json.dumps({
                    'status': 'failed',
                    'summary': '数据源暂不可用，本次未获取到合适数据',
                    'warnings': [{'code': 'UPSTREAM', 'message': '数据源暂不可用', 'retryable': False}],
                }, ensure_ascii=False),
            ),
            ToolMessage(
                name='ask_user', tool_call_id='ask',
                content=json.dumps({
                    'status': 'needs_user_input',
                    'gate': 'company_registry',
                    'kind': 'registry_name',
                    'question': '当前公司名称无法获取企查查数据，请提供精确名称。',
                    'queried_company_name': '华润置地',
                    'context': '材料未写明持有主体工商全称。',
                    'options': [
                        {'value': 'correct_name', 'label': '填写精确名称'},
                        {'value': 'skip', 'label': '跳过此步骤'},
                    ],
                    'allow_free_text': True,
                }, ensure_ascii=False),
            ),
        ]}
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('生成投资人匹配报告', [])
    await service.drain()
    assert service.repository.get_run(first.run_id).status == 'needs_input'
    question = read_interaction(TaskWorkspace(tmp_path / first.task_id))['pending_question']
    assert question['kind'] == 'registry_name'
    assert [option['value'] for option in question['options']] == ['correct_name', 'skip']


@pytest.mark.asyncio
async def test_optional_question_answer_stays_in_task_and_does_not_repeat_lookup(tmp_path):
    gateway = gateway_for()
    async def executor(identity, workspace, message, *, selected_skill=''):
        tool = _build_tool(gateway, 'query_company_registry', workspace)
        output = await tool.ainvoke({'company_name':'简称'})
        return {'skill_name':'one-pager','messages':[
            ToolMessage(name='query_company_registry', tool_call_id='registry', content=output),
        ]}
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('生成一页纸BP', [])
    await service.drain()
    workspace = TaskWorkspace(tmp_path / first.task_id)
    question = read_interaction(workspace)['pending_question']
    assert service.repository.get_run(first.run_id).status == 'needs_input'
    with pytest.raises(ValueError, match='请输入'):
        await service.submit('', [], task_id=first.task_id, question_id=question['question_id'], choice_value='correct_name')
    exact = '某某有限责任公司'
    second = await service.submit(exact, [], task_id=first.task_id,
                                  question_id=question['question_id'], choice_value='correct_name')
    await service.drain()
    assert gateway.call.call_args.args[1]['company_name'] == exact
    assert second.task_id == first.task_id
    question = read_interaction(workspace)['pending_question']
    third = await service.submit('', [], task_id=first.task_id,
                                 question_id=question['question_id'], choice_value='skip')
    await service.drain()
    assert third.task_id == first.task_id
    assert gateway.call.await_count == 2
    assert read_interaction(workspace)['registry_lookup']['status'] == 'skipped'


@pytest.mark.asyncio
async def test_investment_report_blocks_later_tools_until_registry_is_resolved(tmp_path):
    workspace = workspace_at(tmp_path)
    update_interaction(workspace, active_skill='investment-report')
    gateway = gateway_for('success')
    blocked = json.loads(await _build_tool(gateway, 'extract_project_profile', workspace).ainvoke(
        {'company_name': '某头部未上市锂电隔膜企业'}))
    assert blocked['status'] == 'blocked'
    assert blocked['next_actions'] == ['query_company_registry']
    assert _summarize_tool_output(blocked)[0] == 'partial'
    gateway.call.assert_not_called()

    exact = '某某新能源科技股份有限公司'
    update_interaction(workspace, registry_lookup={'status': 'retry', 'company_name': exact})
    still_blocked = json.loads(await _build_tool(gateway, 'query_track_labels', workspace).ainvoke(
        {'company_name': '某头部未上市锂电隔膜企业'}))
    assert still_blocked['status'] == 'blocked'
    gateway.call.assert_not_called()

    await _build_tool(gateway, 'query_company_registry', workspace).ainvoke({'company_name': '文件名里的化名'})
    assert gateway.call.call_args.args[1]['company_name'] == exact


@pytest.mark.asyncio
async def test_found_registry_name_replaces_alias_and_skip_keeps_material_name(tmp_path):
    workspace = workspace_at(tmp_path)
    exact = '某某新能源科技股份有限公司'
    update_interaction(
        workspace,
        active_skill='investment-report',
        registry_lookup={'status': 'found', 'company_name': exact},
    )
    gateway = gateway_for('success')
    await _build_tool(gateway, 'extract_project_profile', workspace).ainvoke(
        {'company_name': '某头部未上市锂电隔膜企业', 'material_url': 'http://example/a.md'})
    assert gateway.call.call_args.args[1]['company_name'] == exact

    update_interaction(workspace, registry_lookup={'status': 'skipped'})
    gateway.call.reset_mock()
    alias = '某新能源隔膜科技公司'
    await _build_tool(gateway, 'match_investors', workspace).ainvoke(
        {'company_name': alias, 'track_tags': ['锂电隔膜'], 'project_profile': {}})
    assert gateway.call.call_args.args[1]['company_name'] == alias


@pytest.mark.asyncio
async def test_one_pager_is_not_held_for_the_investment_report_registry_step(tmp_path):
    workspace = workspace_at(tmp_path)
    update_interaction(workspace, active_skill='one-pager')
    gateway = gateway_for('success')
    await _build_tool(gateway, 'extract_project_profile', workspace).ainvoke({'company_name': '简称'})
    gateway.call.assert_awaited()
