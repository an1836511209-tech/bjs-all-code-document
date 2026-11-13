"""Every label provenance path must satisfy the contract consumed by both skills."""
from unittest.mock import patch

import pytest

import tests.support  # noqa: F401
from data_mcp.mcp.responses import adapt_track_labels
from data_mcp.mcp.schemas import validate_tool_output


@pytest.mark.parametrize('source', ['api', 'fallback', 'local_recall'])
@pytest.mark.parametrize('has_tags', [True, False])
def test_public_data_contains_tags_only_and_preserves_warnings_and_provenance(source, has_tags):
    tags = ['通信设备制造', '应用软件开发'] if has_tags else []
    response = adapt_track_labels({
        'tags': tags, 'source': source,
        'meta': {'local_recall_used': source == 'local_recall'},
        'warnings': ['上游数据不足'] if source != 'api' else [],
    })
    validate_tool_output('query_track_labels', response)
    assert response['data'] == {'tags': tags}
    assert response['status'] == ('empty' if not has_tags else 'success' if source == 'api' else 'partial')
    provenance = {item['name']: item['status'] for item in response['sources']}
    assert provenance['lms'] == ('used' if source == 'api' else 'unavailable')
    assert provenance['hiagent'] == ('used' if source == 'fallback' else 'not_used')
    assert provenance['local_recall'] == ('used' if source == 'local_recall' else 'not_used')
    if source != 'api':
        assert response['warnings'][0]['message'] == '上游数据不足'


@pytest.mark.parametrize('source', ['api', 'fallback', 'local_recall'])
@pytest.mark.parametrize('profile', [{'主营业务':'通信设备和软件开发'}, '主营业务为通信设备和软件开发'])
def test_mcp_server_preserves_available_tags_instead_of_returning_validation_failure(source, profile):
    from data_mcp.mcp.server import query_track_labels
    tags = ['通信设备制造', '新型计算机及信息终端设备制造', '应用软件开发', '信息系统集成和物联网技术服务']
    with patch('data_mcp.mcp.server.call_query_track_labels', return_value={
        'tags':tags, 'source':source, 'meta':{'local_recall_used':source=='local_recall'},
        'warnings':[],
    }) as call:
        result = query_track_labels(company_name='示例公司',project_profile=profile)
    assert result['status'] == 'success'
    assert result['data'] == {'tags':tags}
    call.assert_called_once_with(company_name='示例公司',project_profile=profile,env=None)


def test_response_is_accepted_by_report_agent_contract_registry():
    from data_mcp.mcp.schemas import contracts_dir
    contracts = pytest.importorskip('report_agent.infrastructure.mcp.contracts')
    registry = contracts.McpContractRegistry(contracts_dir(), ('query_track_labels',))
    response = adapt_track_labels({'tags':['通信设备制造'],'source':'fallback','warnings':[]})
    registry.validate_output('query_track_labels',response)
