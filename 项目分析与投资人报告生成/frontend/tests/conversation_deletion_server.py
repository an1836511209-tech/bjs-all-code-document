"""Isolated conversation deletion browser fixture; no real models or databases."""
import asyncio
import tempfile
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessage
from report_agent.api.app import create_app
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository


async def executor(identity, workspace, message, *, selected_skill=''):
    if message == '持续运行':
        await asyncio.sleep(3600)
    return {'messages': [AIMessage(content='会话已完成')], 'skill_name': 'chat'}


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
bus = RunEventBus()
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='conversation-delete-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)


async def seed():
    tasks = []
    for title in ['待删除会话', '保留会话']:
        run = await service.submit(title, [])
        await service.drain()
        tasks.append(run.task_id)
    return tasks


tasks = asyncio.run(seed())
app = create_app(service, dev_ui_enabled=True, event_bus=bus)


@app.get('/test/tasks')
async def test_tasks():
    return tasks


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8027, log_level='warning')
