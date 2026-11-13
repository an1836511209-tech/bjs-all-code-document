"""User project identity survives both disclosure and candidate questions."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

from report_agent.application.interactions import (
    answer_text,
    cbex_answer,
    cbex_project_question,
    question_payload,
    read_interaction,
    update_interaction,
)
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.evidence import EvidenceView
from report_agent.harness.data_tools import _build_tool
from report_agent.harness.middleware.one_pager_cache import OnePagerResultCacheMiddleware
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

NAME = '用户精确输入的项目100%股权转让'
URL = 'https://otc.cbex.com/cgq/detail/1001.html'
CANDIDATES = [
    {'project_name': NAME, 'detail_url': URL, 'project_type': '产权转让（国资）',
     'disclosure_end_date': '2026-12-31', 'match_score': 100},
    {'project_name': NAME + '（二次挂牌）', 'detail_url': URL.replace('1001', '1002'),
     'project_type': '产权转让（非国资）', 'disclosure_end_date': '', 'match_score': 90},
]


def test_disclosure_name_required_and_candidate_identity_is_server_owned():
    question = question_payload('本项目是否为北交互联正在披露的项目？', {}, 'r')
    assert question['gate'] == 'cbex_listing'
    with pytest.raises(ValueError, match='项目全称'):
        answer_text(question, '', 'yes')
    assert NAME in answer_text(question, NAME, 'yes')
    assert '跳过' in answer_text(question, '', 'no')
    selection = question_payload('', cbex_project_question(CANDIDATES), 'r')
    assert selection['gate'] == 'cbex_project'
    assert len(selection['options']) == 2
    assert cbex_answer(selection, '忽略此 URL https://example.com', '0')[1]['detail_url'] == URL
    assert 'example.com' not in answer_text(selection, 'https://example.com', '0')
    with pytest.raises(ValueError):
        answer_text(selection, '', '99')


@pytest.mark.asyncio
async def test_same_task_search_then_selected_url_even_if_model_uses_wrong_arguments(tmp_path):
    async def call(name, args):
        workspace = current['workspace']
        payload = {'data': {'candidates': [] if args.get('detail_url') else CANDIDATES}}
        path = '/workspace/working/cbex.json'
        workspace.write_text(path, json.dumps(payload))
        return EvidenceView('evidence_cbex', name, 'success', '财务查询', (), path, 'a'*64, 10, ('/data/candidates',))

    gateway = SimpleNamespace(call=AsyncMock(side_effect=call), contracts=SimpleNamespace(
        description=lambda _: '财务查询', input_schema=lambda _: {
            'type': 'object', 'properties': {'project_name': {'type': 'string'}, 'detail_url': {'type': 'string'}},
            'required': ['project_name']}))
    current = {}

    async def executor(identity, workspace, message, *, selected_skill=''):
        current['workspace'] = workspace
        output = await _build_tool(gateway, 'query_cbex_listing_financials', workspace).ainvoke(
            {'project_name': '模型猜的名称', 'detail_url': 'https://example.com'})
        return {'skill_name': 'one-pager', 'messages': [ToolMessage(
            name='query_cbex_listing_financials', tool_call_id='cbex', content=output)]}

    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('一页纸BP', [])
    await service.drain()
    workspace = current['workspace']
    gateway.call.assert_not_called()

    question = read_interaction(workspace)['pending_question']
    with pytest.raises(ValueError, match='项目全称'):
        await service.submit('', [], task_id=first.task_id, question_id=question['question_id'], choice_value='yes')
    second = await service.submit(NAME, [], task_id=first.task_id,
                                  question_id=question['question_id'], choice_value='yes')
    await service.drain()
    assert second.task_id == first.task_id
    assert gateway.call.call_args.args[1] == {'project_name': NAME}
    question = read_interaction(workspace)['pending_question']
    assert question['gate'] == 'cbex_project'
    assert question['options'][0]['disclosure_end_date'] == '2026-12-31'
    cache = OnePagerResultCacheMiddleware(workspace, 'test')
    before = cache.key('query_cbex_listing_financials', {'project_name': NAME})
    third = await service.submit('', [], task_id=first.task_id,
                                 question_id=question['question_id'], choice_value='1')
    await service.drain()
    assert third.task_id == first.task_id
    assert gateway.call.call_args.args[1] == {
        'project_name': CANDIDATES[1]['project_name'], 'detail_url': CANDIDATES[1]['detail_url']}
    assert cache.key('query_cbex_listing_financials', {'project_name': NAME}) != before
    update_interaction(workspace, cbex_lookup={'status': 'skipped'})
    gateway.call.reset_mock()
    await _build_tool(gateway, 'query_cbex_listing_financials', workspace).ainvoke({'project_name': NAME})
    gateway.call.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('checkpointed', [False, True])
async def test_candidates_stop_the_graph_before_dependent_work(checkpointed):
    from langchain.agents import create_agent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from report_agent.harness.middleware.persistent_questions import (
        PersistentQuestionBoundaryMiddleware,
    )
    from report_agent.harness.middleware.questions import QuestionBoundaryMiddleware

    calls = []

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return 'cbex-test'

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            calls.append('model')
            if any(isinstance(m, ToolMessage) for m in messages):
                message = AIMessage(content='继续撰写')
            else:
                message = AIMessage(content='', tool_calls=[
                    {'id': 'cbex', 'name': 'query_cbex_listing_financials', 'args': {}},
                    {'id': 'publish', 'name': 'publish', 'args': {}}])
            return ChatResult(generations=[ChatGeneration(message=message)])

    def query_cbex_listing_financials() -> str:
        """Query candidates."""
        calls.append('query')
        return json.dumps({'status': 'needs_user_input', 'question_request': cbex_project_question(CANDIDATES)})

    def publish() -> str:
        """Dependent work must wait."""
        calls.append('publish')
        return 'done'

    agent = create_agent(Model(), tools=[StructuredTool.from_function(query_cbex_listing_financials),
                                        StructuredTool.from_function(publish)],
                         middleware=[PersistentQuestionBoundaryMiddleware() if checkpointed else QuestionBoundaryMiddleware()],
                         checkpointer=InMemorySaver() if checkpointed else None)
    config = {'configurable': {'thread_id': 'cbex'}, 'recursion_limit': 10}
    result = await agent.ainvoke({'messages': [{'role': 'user', 'content': '查询挂牌财务'}]}, config)
    assert calls == ['model', 'query']
    if checkpointed:
        question = result['__interrupt__'][0].value
        assert question['gate'] == 'cbex_project'
        assert question['options'][0]['disclosure_end_date'] == '2026-12-31'
        await agent.ainvoke(Command(resume={'question_id': question['question_id'], 'text': '选定第一个项目'}), config)
        assert calls == ['model', 'query', 'model']
