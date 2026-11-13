"""Isolated browser-test API. All model responses and document bytes are synthetic."""
import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessage
from report_agent.api.app import create_app
from report_agent.application.context_store import WorkspaceContextStore
from report_agent.application.conversation_store import WorkspaceConversationStore
from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import SynchronousRunService
from report_agent.domain.events import EventType
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

bus = RunEventBus()
artifact = {'artifact_id':'artifact_'+'a'*32,'filename':'交互测试.docx','size':10,
 'sha256':'b'*64,'bucket':'qa','object_key':'qa.docx','download_url':'http://unused.test/qa.docx',
 'expires_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}

async def executor(identity, workspace, message, *, selected_skill=''):
    WorkspaceContextStore(workspace).initialize(identity,message)
    await asyncio.sleep(.35)
    bus.emit(identity, EventType.SKILL_ACTIVATED, {'skill':'one-pager','route':'conversation'})
    turns = WorkspaceConversationStore(workspace).turns()
    count = len([t for t in turns if t['role']=='user'])
    if count == 1:
        question = '当前项目是增资还是股权项目？'
    elif count == 2:
        question = '本项目是否为北交互联正在披露的项目？'
    else:
        bus.emit(identity, EventType.ARTIFACT_CREATED, {**artifact,'size_bytes':10,'kind':'docx'})
        return {'messages':[AIMessage(content='测试完成')],'skill_name':'one-pager','artifacts':[artifact]}
    return {'messages':[AIMessage(content=question)],'skill_name':'one-pager'}

class Artifacts:
    def refresh_download(self, record): return record
    def read_object(self, bucket, object_key): return b'fake-docx'

service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='ui-',dir='.runtime/diagnostics')),executor,InMemoryRunRepository(),event_bus=bus)
app = create_app(service,dev_ui_enabled=True,event_bus=bus,artifact_service=Artifacts())
uvicorn.run(app,host='127.0.0.1',port=8017,log_level='warning')
