"""MySQL repository for task/session/run/artifact metadata."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from report_agent.domain.artifacts import PublishedArtifact
from report_agent.domain.identifiers import RunIdentity
from report_agent.domain.tasks import StoredRun, StoredTask
from report_agent.settings.models import MySQLSettings

_DEFAULT_POOL_SIZE = 5
_DEFAULT_CONNECT_TIMEOUT = 10
_READ_ATTEMPTS = 3
_LOST_CONNECTION = {2006, 2013, 2055}
logger = logging.getLogger(__name__)


class _PooledConnection:
    """Thin proxy so repository ``close()`` returns the socket to the pool."""

    __slots__ = ("_pool", "_conn", "_closed")

    def __init__(self, pool: MySQLConnectionPool, conn: Any) -> None:
        self._pool = pool
        self._conn = conn
        self._closed = False

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        self._conn.commit()

    def begin(self) -> None:
        self._conn.begin()

    def rollback(self) -> None:
        self._conn.rollback()

    def ping(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.ping(*args, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.release(self._conn)

    @property
    def open(self) -> bool:
        return bool(getattr(self._conn, "open", False)) and not self._closed


class MySQLConnectionPool:
    """Small fixed-size pool of PyMySQL connections for sync repository calls."""

    def __init__(
        self,
        creator: Callable[[], Any],
        *,
        maxsize: int = _DEFAULT_POOL_SIZE,
        checkout_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._creator = creator
        self._maxsize = maxsize
        self._checkout_timeout = checkout_timeout
        self._pool: Queue[Any] = Queue(maxsize=maxsize)
        self._created = 0
        self._lock = threading.Lock()

    def acquire(self) -> _PooledConnection:
        conn = self._checkout()
        try:
            conn.ping(reconnect=True)
        except Exception:
            self._discard(conn)
            conn = self._new_connection()
        return _PooledConnection(self, conn)

    def release(self, conn: Any) -> None:
        try:
            if not getattr(conn, "open", False):
                self._discard(conn)
                return
            # Reset transactional state before reuse.
            conn.rollback()
        except Exception:
            self._discard(conn)
            return
        try:
            self._pool.put_nowait(conn)
        except Full:
            self._discard(conn)

    def _checkout(self) -> Any:
        try:
            return self._pool.get_nowait()
        except Empty:
            pass
        with self._lock:
            can_create = self._created < self._maxsize
            if can_create:
                self._created += 1
        if can_create:
            try:
                return self._creator()
            except Exception:
                with self._lock:
                    self._created -= 1
                raise
        try:
            return self._pool.get(timeout=self._checkout_timeout)
        except Empty as exc:
            raise RuntimeError("MySQL connection pool exhausted") from exc

    def _new_connection(self) -> Any:
        with self._lock:
            self._created += 1
        try:
            return self._creator()
        except Exception:
            with self._lock:
                self._created -= 1
            raise

    def _discard(self, conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            pass
        with self._lock:
            if self._created > 0:
                self._created -= 1


def mysql_connection_factory(
    settings: MySQLSettings,
    environ: Mapping[str, str],
    *,
    pool_size: int = _DEFAULT_POOL_SIZE,
    autocommit: bool = False,
) -> Callable[[], Any]:
    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise ValueError(f"required environment variable is missing: {name}")
        return value

    port = required(settings.port.env)
    if not port.isdigit():
        raise ValueError(f"MySQL port must be numeric: {settings.port.env}")
    host = required(settings.host.env)
    database = required(settings.database.env)
    user = required(settings.user.env)
    password = required(settings.password.env)
    charset = required(settings.charset.env)

    def creator() -> Any:
        return pymysql.connect(
            host=host,
            port=int(port),
            database=database,
            user=user,
            password=password,
            charset=charset,
            cursorclass=DictCursor,
            autocommit=autocommit,
            connect_timeout=_DEFAULT_CONNECT_TIMEOUT,
            read_timeout=60,
            write_timeout=60,
        )

    pool = MySQLConnectionPool(creator, maxsize=pool_size)
    return pool.acquire


class MySQLRunRepository:
    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def _read_with_retry(self, operation: Callable[[], Any]) -> Any:
        """Retry a read when MySQL drops the socket. Writes are not retried."""
        for attempt in range(1, _READ_ATTEMPTS + 1):
            try:
                return operation()
            except pymysql.err.OperationalError as exc:
                code = exc.args[0] if exc.args else None
                if code not in _LOST_CONNECTION or attempt == _READ_ATTEMPTS:
                    raise
                logger.warning(
                    "MySQL connection lost during read, retrying (%s/%s)",
                    attempt,
                    _READ_ATTEMPTS,
                )
        raise AssertionError("unreachable")

    def create(self, identity: RunIdentity, user_message: str) -> None:
        """Persist a new run; reuse task/session rows when continuing a conversation."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                # 同一 task 的第二轮对话会带原 task_id 回来，必须容忍已有行：
                # 任务状态拉回 running，session 行保持唯一。
                cursor.execute(
                    "INSERT INTO report_agent_tasks (task_id, workspace_id, status) "
                    "VALUES (%s,%s,'running') "
                    "ON DUPLICATE KEY UPDATE workspace_id=VALUES(workspace_id), status='running', "
                    "updated_at=CURRENT_TIMESTAMP(6)",
                    (identity.task_id, identity.workspace_id),
                )
                cursor.execute(
                    "INSERT INTO report_agent_sessions (session_id, task_id) VALUES (%s,%s) "
                    "ON DUPLICATE KEY UPDATE task_id=VALUES(task_id)",
                    (identity.session_id, identity.task_id),
                )
                cursor.execute(
                    "INSERT INTO report_agent_runs (run_id, session_id, task_id, workspace_id, status, user_message) "
                    "VALUES (%s,%s,%s,%s,'running',%s)",
                    (
                        identity.run_id,
                        identity.session_id,
                        identity.task_id,
                        identity.workspace_id,
                        user_message,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish(
        self,
        identity: RunIdentity,
        *,
        status: str,
        assistant_text: str,
        trace: list[dict],
        artifacts: list[PublishedArtifact],
        skill_name: str | None = None,
        skill_route: str | None = None,
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                # ``skill_name`` / ``skill_route`` are nullable and added by
                # migrations/002_run_skill_columns.sql.
                cursor.execute(
                    "UPDATE report_agent_runs SET status=%s, assistant_text=%s, trace_json=%s, "
                    "skill_name=%s, skill_route=%s, updated_at=CURRENT_TIMESTAMP(6) WHERE run_id=%s",
                    (
                        status,
                        assistant_text,
                        json.dumps(trace, ensure_ascii=False),
                        skill_name,
                        skill_route,
                        identity.run_id,
                    ),
                )
                cursor.execute(
                    "UPDATE report_agent_tasks SET status=%s, updated_at=CURRENT_TIMESTAMP(6) WHERE task_id=%s",
                    (status, identity.task_id),
                )
                for artifact in artifacts:
                    cursor.execute(
                        "INSERT INTO report_agent_artifacts (artifact_id, run_id, task_id, filename, sha256, size_bytes, bucket_name, object_key, download_url, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            artifact.artifact_id,
                            identity.run_id,
                            identity.task_id,
                            artifact.filename,
                            artifact.sha256,
                            artifact.size,
                            artifact.bucket,
                            artifact.object_key,
                            artifact.download_url,
                            artifact.expires_at.astimezone(UTC).replace(tzinfo=None),
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_checkpointed(self, identity: RunIdentity, **fields: Any) -> None:
        """Idempotent one-pager finalization; legacy finish keeps its contract."""
        owned = self.get_task(identity.task_id)
        owned_ids = set(owned.artifact_ids if owned else ())
        pending = []
        for artifact in fields.get("artifacts", []):
            existing = self.get_artifact(artifact.artifact_id)
            if existing is None:
                pending.append(artifact)
            elif (artifact.artifact_id not in owned_ids or existing.sha256 != artifact.sha256
                  or existing.object_key != artifact.object_key or existing.bucket != artifact.bucket):
                raise ValueError("已发布产物的任务归属或内容不一致")
        self.finish(identity, **{**fields, "artifacts": pending})

    def fail(self, identity: RunIdentity, error_type: str) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE report_agent_runs SET status='failed', error_type=%s, updated_at=CURRENT_TIMESTAMP(6) WHERE run_id=%s",
                    (error_type, identity.run_id),
                )
                cursor.execute(
                    "UPDATE report_agent_tasks SET status='failed', updated_at=CURRENT_TIMESTAMP(6) WHERE task_id=%s",
                    (identity.task_id,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_run(self, run_id: str) -> StoredRun | None:
        return self._read_with_retry(lambda: self._get_run_once(run_id))

    def _get_run_once(self, run_id: str) -> StoredRun | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM report_agent_runs WHERE run_id=%s", (run_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    "SELECT * FROM report_agent_artifacts WHERE run_id=%s ORDER BY created_at",
                    (run_id,),
                )
                artifacts = [self._artifact(item) for item in cursor.fetchall()]
            return StoredRun(
                task_id=row["task_id"],
                session_id=row["session_id"],
                run_id=row["run_id"],
                workspace_id=row["workspace_id"],
                status=row["status"],
                user_message=row["user_message"],
                assistant_text=row["assistant_text"] or "",
                trace=self._json(row["trace_json"]),
                artifacts=artifacts,
                error_type=row["error_type"],
                skill_name=row.get("skill_name"),
                skill_route=row.get("skill_route"),
                created_at=self._utc(row["created_at"]),
                updated_at=self._utc(row["updated_at"]),
            )
        finally:
            connection.close()

    def get_task(self, task_id: str) -> StoredTask | None:
        return self._read_with_retry(lambda: self._get_task_once(task_id))

    def _get_task_once(self, task_id: str) -> StoredTask | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM report_agent_tasks WHERE task_id=%s", (task_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    "SELECT session_id FROM report_agent_sessions WHERE task_id=%s ORDER BY created_at",
                    (task_id,),
                )
                sessions = [item["session_id"] for item in cursor.fetchall()]
                cursor.execute(
                    "SELECT run_id FROM report_agent_runs WHERE task_id=%s ORDER BY created_at",
                    (task_id,),
                )
                runs = [item["run_id"] for item in cursor.fetchall()]
                cursor.execute(
                    "SELECT artifact_id FROM report_agent_artifacts WHERE task_id=%s ORDER BY created_at",
                    (task_id,),
                )
                artifacts = [item["artifact_id"] for item in cursor.fetchall()]
            return StoredTask(
                task_id=row["task_id"],
                workspace_id=row["workspace_id"],
                status=row["status"],
                session_ids=sessions,
                run_ids=runs,
                artifact_ids=artifacts,
                created_at=self._utc(row["created_at"]),
                updated_at=self._utc(row["updated_at"]),
            )
        finally:
            connection.close()

    def get_artifact(self, artifact_id: str) -> PublishedArtifact | None:
        return self._read_with_retry(lambda: self._get_artifact_once(artifact_id))

    def _get_artifact_once(self, artifact_id: str) -> PublishedArtifact | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM report_agent_artifacts WHERE artifact_id=%s", (artifact_id,)
                )
                row = cursor.fetchone()
            return None if row is None else self._artifact(row)
        finally:
            connection.close()

    @staticmethod
    def _json(value: Any) -> list[dict]:
        if value is None:
            return []
        return json.loads(value) if isinstance(value, str) else value

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _artifact(self, row: dict[str, Any]) -> PublishedArtifact:
        return PublishedArtifact(
            artifact_id=row["artifact_id"],
            filename=row["filename"],
            sha256=row["sha256"],
            size=row["size_bytes"],
            bucket=row["bucket_name"],
            object_key=row["object_key"],
            download_url=row["download_url"],
            expires_at=self._utc(row["expires_at"]),
        )
