"""Published user text must use the same artifact route as the document preview."""
from datetime import UTC, datetime, timedelta

from report_agent.application.runs import ArtifactResult, _authoritative_response
from report_agent.domain.artifacts import artifact_download_path


def test_published_response_uses_artifact_route_instead_of_expiring_storage_url():
    artifact = ArtifactResult(
        artifact_id='artifact_' + 'a' * 32, filename='海康智联_一页纸BP_增资.docx',
        sha256='b' * 64, size=32, bucket='reports', object_key='task-a/bp.docx',
        download_url='https://storage.test/bp.docx?X-Amz-Signature=old',
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    response = _authoritative_response(status='completed', model_text='', artifacts=[artifact], trace=[])
    assert f'下载链接：{artifact_download_path(artifact.artifact_id)}' in response
    assert artifact.download_url not in response
    assert '链接到期时间' not in response
    assert artifact.sha256 in response


def test_multiple_artifacts_each_keep_their_own_download_identity():
    artifacts = [ArtifactResult(
        artifact_id='artifact_' + c * 32, filename=f'{c}.docx', sha256=c * 64,
        size=32, bucket='reports', object_key=f'{c}.docx', download_url='https://unused.test',
        expires_at=datetime.now(UTC).isoformat(),
    ) for c in ['a', 'b']]
    response = _authoritative_response(status='completed', model_text='', artifacts=artifacts, trace=[])
    assert response.count('下载链接：') == 2
    for artifact in artifacts:
        assert artifact_download_path(artifact.artifact_id) in response
