"""MinIO publisher for validated, staged report artifacts."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from minio import Minio

from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.runtime.workspace import TaskWorkspace, WorkspacePolicyError
from report_agent.settings.models import MinioSettings

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MinioArtifactService:
    def __init__(
        self,
        settings: MinioSettings,
        environ: Mapping[str, str],
        *,
        client: Any | None = None,
        clock: Any = None,
    ) -> None:
        self._bucket = self._required(environ, settings.bucket.env)
        self._prefix = settings.object_prefix.strip("/")
        self._expiry = settings.presigned_url_expiry_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._published_by_sha: dict[str, PublishedArtifact] = {}
        self._client = client or Minio(
            self._required(environ, settings.endpoint.env),
            access_key=self._required(environ, settings.access_key.env),
            secret_key=self._required(environ, settings.secret_key.env),
            secure=self._as_bool(self._required(environ, settings.secure.env)),
        )

    def publish(
        self, identity: RunIdentity, workspace: TaskWorkspace, virtual_path: str,
        *, idempotent: bool = False,
    ) -> PublishedArtifact:
        source = workspace.resolve(virtual_path)
        staging_root = (workspace.root / "staging").resolve()
        if (
            source.parent != staging_root
            or source.suffix.lower() != ".docx"
            or not source.is_file()
        ):
            raise WorkspacePolicyError("only a root-level staged DOCX can be published")
        record = workspace.snapshot().files.get(virtual_path)
        if record is None or not record.staged:
            raise WorkspacePolicyError("artifact must be recorded as staged")
        cache_key = f"{identity.task_id}:{record.sha256}:{source.name}" if idempotent else record.sha256
        if cache_key in self._published_by_sha:
            return self._published_by_sha[cache_key]

        artifact_id = "artifact_" + (hashlib.sha256(cache_key.encode()).hexdigest()[:32] if idempotent else uuid4().hex)
        safe_name = PurePosixPath(source.name).name
        object_key = f"{self._prefix}/{identity.task_id}/{artifact_id}/{safe_name}"
        content = source.read_bytes()
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=DOCX_CONTENT_TYPE,
        )
        now = self._clock()
        expires = now + timedelta(seconds=self._expiry)
        url = self._client.presigned_get_object(
            self._bucket, object_key, expires=timedelta(seconds=self._expiry)
        )
        artifact = PublishedArtifact(
            artifact_id=artifact_id,
            filename=safe_name,
            sha256=record.sha256,
            size=record.size,
            bucket=self._bucket,
            object_key=object_key,
            download_url=url,
            expires_at=expires,
        )
        self._published_by_sha[cache_key] = artifact
        return artifact

    def upload_markdown(self, object_key: str, text: str) -> tuple[str, datetime]:
        """Upload a markdown payload and return ``(presigned_url, expires_at)``.

        Used by ``export_parsed_md`` so the Data MCP can download the full
        parsed material instead of receiving a truncated ``file_info`` string.
        """
        content = text.encode("utf-8")
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type="text/markdown; charset=utf-8",
        )
        now = self._clock()
        expires = now + timedelta(seconds=self._expiry)
        url = self._client.presigned_get_object(
            self._bucket, object_key, expires=timedelta(seconds=self._expiry)
        )
        return url, expires

    def refresh_download(self, artifact: PublishedArtifact) -> PublishedArtifact:
        now = self._clock()
        expires = now + timedelta(seconds=self._expiry)
        url = self._client.presigned_get_object(
            artifact.bucket,
            artifact.object_key,
            expires=timedelta(seconds=self._expiry),
        )
        return artifact.model_copy(update={"download_url": url, "expires_at": expires})

    def read_object(self, bucket: str, object_key: str) -> bytes:
        response = self._client.get_object(bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    @classmethod
    def for_workbook(cls, settings: MinioSettings, environ: Mapping[str, str], *, timeout_seconds: int = 10):
        """Independent finite-I/O client; never reconfigure the report publisher."""
        import urllib3
        client = Minio(cls._required(environ,settings.endpoint.env),
                       access_key=cls._required(environ,settings.access_key.env),
                       secret_key=cls._required(environ,settings.secret_key.env),
                       secure=cls._as_bool(cls._required(environ,settings.secure.env)),
                       http_client=urllib3.PoolManager(num_pools=1,maxsize=1,
                           timeout=urllib3.Timeout(connect=min(3,timeout_seconds),read=timeout_seconds),retries=False))
        return cls(settings,environ,client=client)

    def workbook_object_key(self, task_id: str, job_id: str) -> str:
        import re
        if not re.fullmatch(r"task_[a-f0-9]{32}",task_id) or not re.fullmatch(r"aux_[a-f0-9]{32}",job_id):
            raise ValueError("INVALID_WORKBOOK_OWNER")
        return f"{self._prefix}/{task_id}/{job_id}/投资机构匹配.xlsx"

    def publish_workbook(self, task_id: str, job_id: str, content: bytes, *, object_key: str) -> PublishedArtifact:
        expected = self.workbook_object_key(task_id,job_id)
        if object_key != expected or not 0<len(content)<=2*1024*1024:
            raise ValueError("INVALID_WORKBOOK_UPLOAD")
        self._client.put_object(self._bucket,object_key,io.BytesIO(content),length=len(content),content_type=XLSX_CONTENT_TYPE)
        expires = self._clock()+timedelta(seconds=self._expiry)
        return PublishedArtifact(artifact_id="artifact_"+hashlib.sha256(f"{task_id}:{job_id}".encode()).hexdigest()[:32],
            filename="投资机构匹配.xlsx",sha256=hashlib.sha256(content).hexdigest(),size=len(content),bucket=self._bucket,
            object_key=object_key,download_url=self._client.presigned_get_object(self._bucket,object_key,expires=timedelta(seconds=self._expiry)),expires_at=expires)

    @staticmethod
    def _required(environ: Mapping[str, str], name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise ValueError(f"required environment variable is missing: {name}")
        return value

    @staticmethod
    def _as_bool(value: str) -> bool:
        normalized = value.lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        raise ValueError("MINIO_SECURE must be a boolean")
