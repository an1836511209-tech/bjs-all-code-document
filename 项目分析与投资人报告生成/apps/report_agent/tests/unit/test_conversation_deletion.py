"""Deleting sidebar conversations persists across recovery without deleting files."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from report_agent.api.app import create_app
from report_agent.application.runs import RunConflict, SynchronousRunService
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository


def service_at(root, executor=None):
    async def chat(identity, workspace, message, *, selected_skill=''):
        return {'messages': [AIMessage(content='完成')], 'skill_name': 'chat'}
    return SynchronousRunService(root, executor or chat, InMemoryRunRepository())


@pytest.mark.asyncio
async def test_delete_persists_after_restart_preserves_files_and_blocks_old_tab(tmp_path):
    service = service_at(tmp_path)
    first = await service.submit('要删除的会话', [])
    second = await service.submit('保留的会话', [])
    await service.drain()
    material = tmp_path / first.task_id / 'input' / 'original.txt'
    material.write_text('材料原文', encoding='utf-8')
    app = create_app(service, dev_ui_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete(f'/api/conversations/{first.task_id}')
        assert response.status_code == 200 and response.json()['deleted']
        assert (await client.delete(f'/api/conversations/{first.task_id}')).status_code == 200
        listing = (await client.get('/api/conversations?limit=1')).json()
        assert [item['task_id'] for item in listing['items']] == [second.task_id]
        assert first.task_id in listing['deleted_task_ids']
        response = await client.post('/api/dev/runs', data={'task_id': first.task_id, 'message': '旧标签页继续'})
        assert response.status_code == 409
    assert material.read_text(encoding='utf-8') == '材料原文'
    # Recovery uses filesystem metadata, independently of the old repository/process.
    restarted = create_app(service_at(tmp_path), dev_ui_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=restarted), base_url='http://test') as client:
        listing = (await client.get('/api/conversations')).json()
        assert [item['task_id'] for item in listing['items']] == [second.task_id]
        assert listing['deleted_task_ids'] == [first.task_id]


@pytest.mark.asyncio
async def test_running_conversation_cannot_be_deleted(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def execute(identity, workspace, message, *, selected_skill=''):
        started.set()
        await release.wait()
        return {'messages': [AIMessage(content='完成')], 'skill_name': 'chat'}

    service = service_at(tmp_path, execute)
    run = await service.submit('执行中', [])
    await started.wait()
    app = create_app(service, dev_ui_enabled=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.delete(f'/api/conversations/{run.task_id}')
            assert response.status_code == 409
            assert (await client.get('/api/conversations')).json()['items']
    finally:
        release.set()
        await service.drain()
    assert service.delete_conversation(run.task_id)
    with pytest.raises(RunConflict, match='已删除'):
        await service.submit('重新提交', [], task_id=run.task_id)


@pytest.mark.asyncio
async def test_delete_validation_and_disabled_api(tmp_path):
    service = service_at(tmp_path)
    app = create_app(service, dev_ui_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.delete('/api/conversations/not-a-task')).status_code == 422
        assert (await client.delete('/api/conversations/task_' + 'a'*32)).status_code == 404
    disabled = create_app(service, dev_ui_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=disabled), base_url='http://test') as client:
        assert (await client.delete('/api/conversations/task_' + 'a'*32)).status_code == 404
