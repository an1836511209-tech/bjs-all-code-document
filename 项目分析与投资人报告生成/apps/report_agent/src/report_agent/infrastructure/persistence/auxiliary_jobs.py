"""Separate auxiliary transactions: never finish, fail or resume a report run."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC
from typing import Any
from uuid import uuid4

from report_agent.domain.artifacts import PublishedArtifact


class MySQLAuxiliaryRepository:
    def __init__(self, connect: Callable[[], Any]):
        self.connect = connect

    def _transaction(self, operation):
        connection = self.connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                result = operation(cursor)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _job(row):
        if row is None:
            return None
        data = row["job_json"]
        data = json.loads(data) if isinstance(data, str) else data
        return {
            **data,
            **{
                k: row[k]
                for k in (
                    "job_id",
                    "task_id",
                    "origin_run_id",
                    "status",
                    "stage",
                    "claim_token",
                    "artifact_id",
                )
            },
            "created_at": row["created_at"].replace(tzinfo=UTC).isoformat(),
            "updated_at": row["updated_at"].replace(tzinfo=UTC).isoformat(),
        }

    def enqueue(self, job: dict) -> dict:
        def execute(c):
            c.execute(
                "SELECT task_id FROM report_agent_runs WHERE run_id=%s", (job["origin_run_id"],)
            )
            owner = c.fetchone()
            if not owner or owner["task_id"] != job["task_id"]:
                raise ValueError("INVALID_JOB_OWNER")
            c.execute(
                "INSERT INTO report_agent_auxiliary_jobs "
                "(job_id,task_id,origin_run_id,source_docx_artifact_id,idempotency_key,context_fingerprint,status,stage,job_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,'queued','context_resolved',%s) "
                "ON DUPLICATE KEY UPDATE idempotency_key=idempotency_key",
                (
                    job["job_id"],
                    job["task_id"],
                    job["origin_run_id"],
                    job.get("source_docx_artifact_id"),
                    job["idempotency_key"],
                    job["context_fingerprint"],
                    json.dumps(job, ensure_ascii=False),
                ),
            )
            c.execute(
                "SELECT * FROM report_agent_auxiliary_jobs WHERE idempotency_key=%s",
                (job["idempotency_key"],),
            )
            return self._job(c.fetchone())

        return self._transaction(execute)

    def list(self, task_id: str) -> list[dict]:
        def execute(c):
            c.execute(
                "SELECT * FROM report_agent_auxiliary_jobs WHERE task_id=%s ORDER BY created_at DESC LIMIT 50",
                (task_id,),
            )
            return [self._job(r) for r in c.fetchall()]

        return self._transaction(execute)

    def for_artifact(self, artifact_id: str) -> dict | None:
        def execute(c):
            c.execute(
                "SELECT * FROM report_agent_auxiliary_jobs WHERE artifact_id=%s AND status='succeeded'",
                (artifact_id,),
            )
            return self._job(c.fetchone())

        return self._transaction(execute)

    def cancel(self, task_id: str, job_id: str) -> bool:
        def execute(c):
            c.execute(
                "UPDATE report_agent_auxiliary_jobs SET status='cancelled',claim_token=NULL,"
                "job_json=JSON_SET(job_json,'$.reason','用户取消附件生成。'),updated_at=CURRENT_TIMESTAMP(6) "
                "WHERE task_id=%s AND job_id=%s AND status IN ('queued','running')",
                (task_id, job_id),
            )
            return c.rowcount == 1

        return self._transaction(execute)

    def mark_failed(self, task_id: str, job_id: str, job: dict) -> bool:
        """Mark a job failed without an active claim (worker timeout / lost claim)."""

        def execute(c):
            c.execute(
                "UPDATE report_agent_auxiliary_jobs SET status='failed', claim_token=NULL, "
                "stage=%s, job_json=%s, updated_at=CURRENT_TIMESTAMP(6) "
                "WHERE task_id=%s AND job_id=%s AND status IN ('queued','running')",
                (
                    job.get("stage"),
                    json.dumps(job, ensure_ascii=False),
                    task_id,
                    job_id,
                ),
            )
            return c.rowcount == 1

        return self._transaction(execute)

    def claim(self, timeout_seconds: int) -> dict | None:
        def execute(c):
            # A request whose response was not saved is never replayed automatically.
            c.execute(
                "SELECT * FROM report_agent_auxiliary_jobs WHERE status='running' AND deadline<CURRENT_TIMESTAMP(6) ORDER BY deadline LIMIT 20 FOR UPDATE SKIP LOCKED"
            )
            for row in c.fetchall():
                data = self._job(row)
                resumable = (
                    row["stage"]
                    in {"context_resolved", "tags_selected", "workbook_received", "uploaded"}
                    and data.get("recovery_count", 0) < 1
                )
                data["recovery_count"] = data.get("recovery_count", 0) + 1
                data["reason"] = "" if resumable else "执行中断，请重试附件；报告已保留。"
                c.execute(
                    "UPDATE report_agent_auxiliary_jobs SET status=%s,claim_token=NULL,job_json=%s WHERE job_id=%s",
                    (
                        "queued" if resumable else "failed",
                        json.dumps(data, ensure_ascii=False),
                        row["job_id"],
                    ),
                )
            c.execute(
                "SELECT j.* FROM report_agent_auxiliary_jobs j JOIN report_agent_tasks t ON t.task_id=j.task_id "
                "WHERE j.status='queued' AND t.status<>'running' ORDER BY j.created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
            row = c.fetchone()
            if not row:
                return None
            claim = uuid4().hex
            c.execute(
                "UPDATE report_agent_auxiliary_jobs SET status='running',claim_token=%s,deadline=TIMESTAMPADD(SECOND,%s,CURRENT_TIMESTAMP(6)),updated_at=CURRENT_TIMESTAMP(6) WHERE job_id=%s",
                (claim, timeout_seconds, row["job_id"]),
            )
            row.update(status="running", claim_token=claim)
            return self._job(row)

        return self._transaction(execute)

    def update(self, job: dict, *, status="running", stage: str | None = None) -> bool:
        def execute(c):
            c.execute(
                "UPDATE report_agent_auxiliary_jobs SET status=%s,stage=%s,job_json=%s,updated_at=CURRENT_TIMESTAMP(6) "
                "WHERE job_id=%s AND status='running' AND claim_token=%s AND deadline>=CURRENT_TIMESTAMP(6)",
                (
                    status,
                    stage or job["stage"],
                    json.dumps(job, ensure_ascii=False),
                    job["job_id"],
                    job["claim_token"],
                ),
            )
            return c.rowcount == 1

        return self._transaction(execute)

    def append_auxiliary_artifact(self, job: dict, artifact: PublishedArtifact) -> None:
        def execute(c):
            c.execute(
                "SELECT *,deadline>=CURRENT_TIMESTAMP(6) AS claim_valid FROM report_agent_auxiliary_jobs WHERE job_id=%s FOR UPDATE",
                (job["job_id"],),
            )
            row = c.fetchone()
            if row and row["status"] == "succeeded" and row["artifact_id"] == artifact.artifact_id:
                return
            if (
                not row
                or row["task_id"] != job["task_id"]
                or row["origin_run_id"] != job["origin_run_id"]
                or row["status"] != "running"
                or row["claim_token"] != job["claim_token"]
                or not row["claim_valid"]
            ):
                raise ValueError("EXPIRED_JOB_CLAIM")
            c.execute(
                "SELECT task_id,sha256,object_key FROM report_agent_artifacts WHERE artifact_id=%s",
                (artifact.artifact_id,),
            )
            existing = c.fetchone()
            if existing:
                if (existing["task_id"], existing["sha256"], existing["object_key"]) != (
                    job["task_id"],
                    artifact.sha256,
                    artifact.object_key,
                ):
                    raise ValueError("ARTIFACT_OWNER_MISMATCH")
            else:
                c.execute(
                    "INSERT INTO report_agent_artifacts (artifact_id,run_id,task_id,filename,sha256,size_bytes,bucket_name,object_key,download_url,expires_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        artifact.artifact_id,
                        job["origin_run_id"],
                        job["task_id"],
                        artifact.filename,
                        artifact.sha256,
                        artifact.size,
                        artifact.bucket,
                        artifact.object_key,
                        artifact.download_url,
                        artifact.expires_at.astimezone(UTC).replace(tzinfo=None),
                    ),
                )
            job["artifact_id"] = artifact.artifact_id
            c.execute(
                "UPDATE report_agent_auxiliary_jobs SET status='succeeded',stage='registered',artifact_id=%s,job_json=%s,updated_at=CURRENT_TIMESTAMP(6) "
                "WHERE job_id=%s AND status='running' AND claim_token=%s AND deadline>=CURRENT_TIMESTAMP(6)",
                (
                    artifact.artifact_id,
                    json.dumps(job, ensure_ascii=False),
                    job["job_id"],
                    job["claim_token"],
                ),
            )
            if c.rowcount != 1:
                raise ValueError("EXPIRED_JOB_CLAIM")

        self._transaction(execute)
