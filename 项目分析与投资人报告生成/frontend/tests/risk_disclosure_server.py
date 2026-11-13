"""Risk confirmation UI fixture without model, rendering or external services."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import uvicorn
from langchain_core.messages import AIMessage, ToolMessage
from report_agent.api.app import create_app
from report_agent.application.event_bus import RunEventBus
from report_agent.application.interactions import read_interaction
from report_agent.application.runs import SynchronousRunService
from report_agent.harness.one_pager_tools import build_one_pager_tools
from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

results = []


async def executor(identity, workspace, message, *, selected_skill=''):
    choice = read_interaction(workspace).get('risk_disclosure') or {}
    risk = message != '无风险'
    titles = ['核心产品', '业务构成', '风险提示' if risk and choice.get('value') != 'hide' else '项目布局']
    def slot(i, title, kind):
        return {'index': i, 'title': title, 'kind': kind,
                'key_points': ['关联方担保', '未决诉讼'] if risk and i == 3 else ['材料事实'],
                'source_quote': '材料披露关联方担保及未决诉讼。'}
    outline = {'report_id': 'risk', 'business_type': '产权', 'has_risk_facts': risk,
               'intro_sections': [slot(i, t, 'intro') for i, t in enumerate(titles, 1)],
               'highlight_sections': [slot(i, t, 'highlight') for i, t in enumerate(['技术研发优势', '市场资源优势', '团队管理优势'], 1)]}
    tools = {t.name: t for t in build_one_pager_tools(workspace, service=MagicMock())}
    output = tools['check_one_pager_outline'].invoke({'outline': outline})
    if json.loads(output)['status'] == 'ok':
        results.append({'task_id': identity.task_id, 'choice': choice, 'result': json.loads(output)})
        return {'skill_name': 'chat', 'messages': [AIMessage(content='已按确认结果继续生成报告。')]}
    return {'skill_name': 'one-pager', 'messages': [ToolMessage(
        name='check_one_pager_outline', tool_call_id='risk', content=output)]}


root = Path('.runtime/diagnostics')
root.mkdir(parents=True, exist_ok=True)
bus = RunEventBus()
service = SynchronousRunService(Path(tempfile.mkdtemp(prefix='risk-disclosure-', dir=root)), executor,
                                InMemoryRunRepository(), event_bus=bus)
app = create_app(service, dev_ui_enabled=True, event_bus=bus)


@app.get('/test/results')
async def test_results():
    return results


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8028, log_level='warning')
