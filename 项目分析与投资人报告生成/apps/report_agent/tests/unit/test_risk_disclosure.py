"""Risk identification requires a user disclosure decision before writing."""
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from report_agent.application.interactions import (
    answer_text,
    question_payload,
    read_interaction,
    risk_disclosure_answer,
    update_interaction,
)
from report_agent.application.runs import SynchronousRunService
from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.runtime.workspace import TaskWorkspace


def outline(risk=True, title=None):
    titles = ['核心产品', '业务构成', title or ('风险提示' if risk else '项目布局')]
    def slot(i, title, kind="intro"):
        return {'index': i, 'title': title, 'kind': kind, 'key_points': ['关联方担保', '未决诉讼'] if i == 3 and risk else ['材料事实'],
                'source_quote': '材料披露关联方担保及未决诉讼。'}
    return {'report_id': 'risk-test', 'business_type': '产权', 'has_risk_facts': risk,
            'intro_sections': [slot(i, t) for i, t in enumerate(titles, 1)],
            'highlight_sections': [slot(i, t, 'highlight') for i, t in enumerate(['技术研发优势', '市场资源优势', '团队管理优势'], 1)]}


def tools_at(root):
    workspace = TaskWorkspace(root)
    workspace.initialize()
    service = MagicMock()
    tools = {t.name: t for t in build_one_pager_tools(workspace, service=service)}
    return workspace, service, tools


def test_detected_risks_return_fixed_card_without_defaulting_to_show(tmp_path):
    workspace, _, tools = tools_at(tmp_path)
    output = json.loads(tools['check_one_pager_outline'].invoke({'outline': outline()}))
    assert output['status'] == 'needs_user_input'
    question = question_payload('', output['question_request'], 'r')
    assert question['gate'] == 'one_pager_risk'
    assert [o['label'] for o in question['options']] == ['展示', '不展示']
    assert '关联方担保' in question['question'] and '未决诉讼' in question['question']
    assert not read_interaction(workspace).get('risk_disclosure')
    with pytest.raises(ValueError, match='请选择'):
        answer_text(question, '请保留原文', '')


# 风险提示已改为第二页末尾小字，不再占用介绍槽位；
# 用户选择展示时，第三个介绍标题仍由模型自拟（不能用「风险提示」）。
@pytest.mark.parametrize('choice,title', [('show', '团队背景'), ('hide', '项目布局')])
def test_user_choice_controls_title_and_survives_rebuilding_tools(tmp_path, choice, title):
    # 「风险提示」不再占用介绍槽位（改到第二页末尾小字），所以用户选择展示时
    # 介绍的第三个标题仍由模型自拟，不能是「风险提示」。
    workspace, _, tools = tools_at(tmp_path)
    output = json.loads(tools['check_one_pager_outline'].invoke({'outline': outline()}))
    answer, selection = risk_disclosure_answer(output['question_request'], '请按材料写', choice)
    assert '请按材料写' in answer
    update_interaction(workspace, risk_disclosure=selection)
    tools = {t.name: t for t in build_one_pager_tools(TaskWorkspace(tmp_path), service=MagicMock())}
    data = outline(title=title)
    data['include_risk_facts'] = choice != 'show'  # Model cannot override user selection.
    result = json.loads(tools['check_one_pager_outline'].invoke({'outline': data}))
    assert result['status'] == 'ok'
    assert result['intro_titles'][2] == title
    assert read_interaction(workspace)['risk_review']['risk_items'] == ['关联方担保', '未决诉讼']
    # 无论用户选展示还是不展示，「风险提示」都不能再当介绍标题（它已改到第二页小字）
    wrong = json.loads(tools['check_one_pager_outline'].invoke({'outline': outline(title='风险提示')}))
    assert wrong['status'] == 'invalid_outline'


def test_no_risk_facts_skip_confirmation(tmp_path):
    _, _, tools = tools_at(tmp_path)
    assert json.loads(tools['check_one_pager_outline'].invoke({'outline': outline(False)}))['status'] == 'ok'


def test_render_cannot_bypass_risk_confirmation_or_hide_selection(tmp_path):
    workspace, service, tools = tools_at(tmp_path)
    update_interaction(workspace, business_type_selection={'value': '产权', 'source': 'user'})
    workspace.write_text('/workspace/report/bp.md', '## 项目介绍\n### 风险提示\n材料披露关联方担保。')
    args = {'md_path': '/workspace/report/bp.md', 'business_type': '产权', 'report_id': 'r', 'filename': 'r.docx'}
    assert json.loads(tools['render_one_pager'].invoke(args))['question_request']['gate'] == 'one_pager_risk'
    update_interaction(workspace, risk_disclosure={'value': 'hide'})
    assert json.loads(tools['render_one_pager'].invoke(args))['status'] == 'invalid_content'
    service.render.assert_not_called()


@pytest.mark.asyncio
async def test_answer_persists_in_same_task_without_repeating_question(tmp_path):
    async def executor(identity, workspace, message, *, selected_skill=''):
        tools = {t.name: t for t in build_one_pager_tools(workspace, service=MagicMock())}
        choice = read_interaction(workspace).get('risk_disclosure') or {}
        data = outline(title='项目布局' if choice.get('value') == 'hide' else '风险提示')
        output = tools['check_one_pager_outline'].invoke({'outline': data})
        return {'skill_name': 'one-pager', 'messages': [ToolMessage(
            name='check_one_pager_outline', tool_call_id='risk', content=output)]}
    service = SynchronousRunService(tmp_path, executor, InMemoryRunRepository())
    first = await service.submit('一页纸BP', [])
    await service.drain()
    workspace = TaskWorkspace(tmp_path / first.task_id)
    question = read_interaction(workspace)['pending_question']
    second = await service.submit('暂不展示', [], task_id=first.task_id,
                                  question_id=question['question_id'], choice_value='hide')
    await service.drain()
    assert first.task_id == second.task_id
    assert read_interaction(workspace)['risk_disclosure']['value'] == 'hide'
    assert '展示' not in [o['label'] for o in (read_interaction(workspace).get('pending_question') or {}).get('options', [])]


@pytest.mark.asyncio
@pytest.mark.parametrize('checkpointed', [False, True])
async def test_outline_question_stops_dependent_work_until_user_answers(tmp_path, checkpointed):
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

    workspace, _, tools = tools_at(tmp_path)
    calls = []

    class Model(BaseChatModel):
        @property
        def _llm_type(self):
            return 'risk-test'

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            calls.append('model')
            if any(isinstance(m, ToolMessage) for m in messages):
                message = AIMessage(content='按用户选择重新定大纲')
            else:
                message = AIMessage(content='', tool_calls=[
                    {'id': 'outline', 'name': 'check_one_pager_outline', 'args': {'outline': outline()}},
                    {'id': 'write', 'name': 'write_body', 'args': {}}])
            return ChatResult(generations=[ChatGeneration(message=message)])

    def write_body() -> str:
        """Writing must wait for the user."""
        calls.append('write')
        return 'written'

    agent = create_agent(Model(), tools=[tools['check_one_pager_outline'], StructuredTool.from_function(write_body)],
                         middleware=[PersistentQuestionBoundaryMiddleware() if checkpointed else QuestionBoundaryMiddleware()],
                         checkpointer=InMemorySaver() if checkpointed else None)
    config = {'configurable': {'thread_id': 'risk'}, 'recursion_limit': 10}
    result = await agent.ainvoke({'messages': [{'role': 'user', 'content': '一页纸BP'}]}, config)
    assert calls == ['model']
    if checkpointed:
        question = result['__interrupt__'][0].value
        assert question['gate'] == 'one_pager_risk'
        answer, selection = risk_disclosure_answer(question, '', 'hide')
        update_interaction(workspace, risk_disclosure=selection)
        await agent.ainvoke(Command(resume={'question_id': question['question_id'], 'text': answer}), config)
        assert calls == ['model', 'model']
