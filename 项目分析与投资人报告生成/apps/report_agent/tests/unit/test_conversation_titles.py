"""Optional title suggestions must not duplicate requests or delay the report task."""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from report_agent.api.app import create_app
from report_agent.application.bootstrap import suggest_conversation_title
from report_agent.application.runs import SynchronousRunService
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository
from report_agent.settings import load_settings


def title_settings():
    settings = load_settings(Path('deploy/environments/test/report-agent.local.yaml'))
    env = {settings.model.model.env:'test-model',settings.model.base_url.env:'https://model.test/v1',
           settings.model.api_key.env:'test-key'}
    return settings, env


@pytest.mark.asyncio
async def test_title_request_is_short_and_does_not_retry(monkeypatch):
    settings, env = title_settings()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='“示例企业一页纸”')))
    factory = MagicMock(return_value=model)
    monkeypatch.setattr('report_agent.application.bootstrap.ChatOpenAI',factory)
    assert await suggest_conversation_title(settings,env,'生成示例企业的一页纸') == '示例企业一页纸'
    assert factory.call_args.kwargs['max_retries'] == 0
    # 推理型模型会先吐一段思维链，64 token 在分析阶段就被截断、标题从未产出；仍只调用一次。
    assert factory.call_args.kwargs['max_tokens'] == 512
    assert factory.call_args.kwargs['timeout'] == 60
    assert factory.call_args.kwargs['extra_body'] == {'enable_thinking': False}


@pytest.mark.asyncio
async def test_title_keeps_chinese_answer_and_drops_reasoning(monkeypatch):
    settings, env = title_settings()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=[
        {'type': 'reasoning', 'reasoning': 'The user wants a short English title.'},
        {'type': 'text', 'text': '示例企业一页纸'},
    ])))
    monkeypatch.setattr('report_agent.application.bootstrap.ChatOpenAI', MagicMock(return_value=model))
    assert await suggest_conversation_title(settings, env, '生成示例企业的一页纸') == '示例企业一页纸'


@pytest.mark.asyncio
async def test_english_only_title_is_discarded(monkeypatch):
    settings, env = title_settings()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
        content='The user wants a concise title for the one-pager.')))
    monkeypatch.setattr('report_agent.application.bootstrap.ChatOpenAI', MagicMock(return_value=model))
    assert await suggest_conversation_title(settings, env, '生成示例企业的一页纸') == ''


@pytest.mark.asyncio
async def test_title_timeout_has_total_deadline_and_no_traceback(monkeypatch,caplog):
    settings, env = title_settings()
    cancelled = asyncio.Event()
    async def never_returns(*args,**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr('report_agent.application.bootstrap.TITLE_MODEL_TIMEOUT_SECONDS',.01)
    monkeypatch.setattr('report_agent.application.bootstrap.ChatOpenAI',MagicMock(return_value=SimpleNamespace(ainvoke=never_returns)))
    with caplog.at_level(logging.INFO):
        assert await asyncio.wait_for(suggest_conversation_title(settings,env,'一页纸'),1) == ''
    assert cancelled.is_set()
    records=[r for r in caplog.records if 'conversation title' in r.getMessage()]
    assert records and all(r.exc_info is None for r in records)


@pytest.mark.asyncio
async def test_title_failure_log_excludes_sensitive_error_body(monkeypatch,caplog):
    settings, env = title_settings()
    monkeypatch.setattr('report_agent.application.bootstrap.ChatOpenAI',MagicMock(return_value=SimpleNamespace(
        ainvoke=AsyncMock(side_effect=RuntimeError('private token response body')))))
    with caplog.at_level(logging.INFO):
        assert await suggest_conversation_title(settings,env,'一页纸') == ''
    assert 'RuntimeError' in caplog.text
    assert 'private token' not in caplog.text


def service_at(tmp_path):
    async def executor(identity,workspace,message,*,selected_skill=''):
        return {'messages':[AIMessage(content='主流程已完成')],'skill_name':'chat'}
    return SynchronousRunService(tmp_path,executor,InMemoryRunRepository())


@pytest.mark.asyncio
async def test_one_title_in_flight_does_not_hold_up_run_submission(tmp_path):
    service = service_at(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def slow_title(message):
        calls.append(message)
        started.set()
        await release.wait()
        return '智能标题'
    app = create_app(service,dev_ui_enabled=True,title_suggester=slow_title)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        title_task = asyncio.create_task(client.post('/api/conversations/title',json={'message':'第一条消息'}))
        await asyncio.wait_for(started.wait(),1)
        try:
            duplicate = await client.post('/api/conversations/title',json={'message':'第二条消息'})
            assert duplicate.json() == {'title':''}
            response = await client.post('/api/dev/runs',data={'message':'主流程任务'})
            assert response.status_code == 202
            await service.drain()
            assert service.repository.get_run(response.json()['run_id']).status == 'completed'
            assert calls == ['第一条消息']
        finally:
            release.set()
            assert (await title_task).json() == {'title':'智能标题'}


@pytest.mark.asyncio
async def test_failed_title_cools_down_then_allows_recovery(tmp_path,monkeypatch):
    monkeypatch.setattr('report_agent.api.app.TITLE_FAILURE_COOLDOWN_SECONDS',.02)
    suggester = AsyncMock(side_effect=['','恢复后的标题'])
    app = create_app(service_at(tmp_path),dev_ui_enabled=True,title_suggester=suggester)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post('/api/conversations/title',json={'message':'第一条'})).json() == {'title':''}
        assert (await client.post('/api/conversations/title',json={'message':'第二条'})).json() == {'title':''}
        assert suggester.await_count == 1
        await asyncio.sleep(.03)
        assert (await client.post('/api/conversations/title',json={'message':'第三条'})).json() == {'title':'恢复后的标题'}
        assert suggester.await_count == 2


@pytest.mark.asyncio
async def test_endpoint_timeout_is_bounded_and_cools_down(tmp_path,monkeypatch,caplog):
    monkeypatch.setattr('report_agent.api.app.TITLE_ENDPOINT_TIMEOUT_SECONDS',.01)
    calls = []
    async def never_returns(message):
        calls.append(message)
        await asyncio.Event().wait()
    app = create_app(service_at(tmp_path),dev_ui_enabled=True,title_suggester=never_returns)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        with caplog.at_level(logging.INFO):
            response = await asyncio.wait_for(client.post('/api/conversations/title',json={'message':'一页纸'}),1)
        assert response.status_code == 200 and response.json() == {'title':''}
        await client.post('/api/conversations/title',json={'message':'又一条'})
        assert len(calls) == 1
    assert all(r.exc_info is None for r in caplog.records)
