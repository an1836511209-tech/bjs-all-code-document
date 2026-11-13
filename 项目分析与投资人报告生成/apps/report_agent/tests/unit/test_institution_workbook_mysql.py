"""Opt-in integration against a dedicated auxiliary schema, never business tables."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest
from pymysql.cursors import DictCursor

from report_agent.application.institution_workbook.context import fingerprint
from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.infrastructure.persistence.auxiliary_jobs import MySQLAuxiliaryRepository
from report_agent.infrastructure.persistence.mysql_runs import MySQLRunRepository
from report_agent.settings import load_settings

ROOT = Path(__file__).resolve().parents[4]
DATABASE = "bjs_institution_workbook_test"


@pytest.fixture
def database():
    if os.environ.get("BJS_WORKBOOK_INTEGRATION") != "1":
        pytest.skip("requires explicitly enabled dedicated MySQL test schema")
    env = dict(os.environ)
    for line in (
        (ROOT / "deploy/environments/test/runtime.env").read_text(encoding="utf-8-sig").splitlines()
    ):
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    cfg = load_settings(ROOT / "deploy/environments/test/report-agent.local.yaml").persistence.mysql
    kwargs = dict(
        host=env[cfg.host.env],
        port=int(env[cfg.port.env]),
        user=env[cfg.user.env],
        password=env[cfg.password.env],
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )
    admin = pymysql.connect(**kwargs, autocommit=True)
    with admin.cursor() as c:
        c.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE} CHARACTER SET utf8mb4")
    admin.close()

    def connect():
        return pymysql.connect(**kwargs, database=DATABASE, autocommit=False)

    connection = connect()
    with connection.cursor() as c:
        for name in ["001_task_run_artifact.sql", "003_institution_workbook.sql"]:
            for sql in (
                (ROOT / "apps/report_agent/migrations" / name)
                .read_text(encoding="utf-8")
                .split(";")
            ):
                if sql.strip():
                    c.execute(sql)
    connection.commit()
    connection.close()
    yield connect


def test_real_mysql_concurrent_claim_append_idempotency_and_late_result_guard(database):
    runs = MySQLRunRepository(database)
    jobs = MySQLAuxiliaryRepository(database)
    identity = RunIdentity.create()
    runs.create(identity, "original report")
    word = PublishedArtifact(
        artifact_id="artifact_" + uuid4().hex,
        filename="原报告.docx",
        sha256="a" * 64,
        size=5,
        bucket="test",
        object_key=f"{identity.task_id}/word.docx",
        download_url="https://unused.test",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    runs.finish(
        identity,
        status="completed",
        assistant_text="Word 已交付",
        trace=[{"tool": "parse_materials"}],
        artifacts=[word],
        skill_name="investment-report",
    )
    before = runs.get_run(identity.run_id)

    def make_job(suffix):
        return {
            "job_id": "aux_" + uuid4().hex,
            "task_id": identity.task_id,
            "origin_run_id": identity.run_id,
            "source_docx_artifact_id": word.artifact_id,
            "idempotency_key": fingerprint([identity.run_id, suffix]),
            "context_fingerprint": "b" * 64,
        }

    first = jobs.enqueue(make_job("first"))
    duplicate = jobs.enqueue(make_job("first"))
    assert first["job_id"] == duplicate["job_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: jobs.claim(120), range(2)))
    claimed = [r for r in results if r]
    assert len(claimed) == 1
    claimed = claimed[0]
    excel = word.model_copy(
        update={
            "artifact_id": "artifact_" + uuid4().hex,
            "filename": "投资机构匹配.xlsx",
            "object_key": f"{identity.task_id}/{claimed['job_id']}/excel.xlsx",
            "sha256": "c" * 64,
        }
    )
    claimed["preview"] = {"columns": ["机构"], "rows": []}
    jobs.append_auxiliary_artifact(claimed, excel)
    jobs.append_auxiliary_artifact(claimed, excel)
    after = runs.get_run(identity.run_id)
    assert after.status == "completed" and after.assistant_text == before.assistant_text
    assert (
        after.trace == before.trace
        and after.updated_at == before.updated_at
        and len(after.artifacts) == 2
    )
    assert jobs.for_artifact(excel.artifact_id)["status"] == "succeeded"
    # No remote result is registered after cancellation or expiry.
    second = jobs.enqueue(make_job("cancel"))
    claim = jobs.claim(120)
    assert jobs.cancel(identity.task_id, second["job_id"])
    with pytest.raises(ValueError, match="EXPIRED_JOB_CLAIM"):
        jobs.append_auxiliary_artifact(claim, excel)
    third = jobs.enqueue(make_job("interrupted"))
    claim = jobs.claim(120)
    claim["stage"] = "request_started"
    assert jobs.update(claim, stage="request_started")

    def expire(c):
        c.execute(
            "UPDATE report_agent_auxiliary_jobs SET deadline=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP(6)) WHERE job_id=%s",
            (third["job_id"],),
        )

    jobs._transaction(expire)
    # Fresh repository instance represents worker restart. Unknown DMP requests are not replayed.
    assert MySQLAuxiliaryRepository(database).claim(120) is None
    assert (
        next(j for j in jobs.list(identity.task_id) if j["job_id"] == third["job_id"])["status"]
        == "failed"
    )
    assert runs.get_run(identity.run_id).updated_at == before.updated_at
