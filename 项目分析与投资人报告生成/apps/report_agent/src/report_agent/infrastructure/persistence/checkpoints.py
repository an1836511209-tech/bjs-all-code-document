"""MySQL-backed LangGraph checkpoint lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote_plus

from langgraph.checkpoint.base import BaseCheckpointSaver

from report_agent.settings.models import MySQLSettings


class AsyncCheckpointAdapter(BaseCheckpointSaver):
    """Expose the locked sync saver to async graphs without blocking the loop.

    The wrapped saver owns its thread lock; connection acquisition/release also
    happens in that thread. No connection or transaction is held while waiting
    for a user, and no schema DDL is executed by this adapter.
    """

    def __init__(self, saver: Any) -> None:
        super().__init__(serde=saver.serde)
        self.saver = saver

    def get_next_version(self, current: Any, channel: Any) -> Any:
        return self.saver.get_next_version(current, channel)

    async def _call(self, method: Any, *args: Any) -> Any:
        # Cancellation cannot stop a DB thread. Drain its commit/rollback
        # before the caller releases the workflow's OS execution lock.
        task = asyncio.create_task(asyncio.to_thread(method, *args))
        cancelled = False
        while True:
            try:
                value = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return value

    async def aget_tuple(self, config: Any) -> Any:
        return await self._call(self.saver.get_tuple, config)

    async def alist(self, config: Any, *, filter: Any = None, before: Any = None,
                    limit: int | None = None):
        rows = await self._call(lambda: list(self.saver.list(
            config, filter=filter, before=before, limit=limit)))
        for row in rows:
            yield row

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        return await self._call(self.saver.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: Any, writes: Any, task_id: str,
                         task_path: str = "") -> None:
        await self._call(self.saver.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await self._call(self.saver.delete_thread, thread_id)


def build_one_pager_checkpointer(settings: MySQLSettings, environ: Mapping[str, str],
                                database_env: str) -> AsyncCheckpointAdapter:
    """Lazily opened, dedicated-schema connections, isolated from report metadata."""
    from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver

    from report_agent.infrastructure.persistence.mysql_runs import mysql_connection_factory
    from report_agent.settings.models import SecretRef

    database = environ.get(database_env, "").strip()
    if not database or database == environ.get(settings.database.env, "").strip():
        raise ValueError(f"{database_env} 必须配置为独立检查点 schema，不能使用业务元数据库")
    dedicated = settings.model_copy(update={"database": SecretRef(env=database_env)})
    connect = mysql_connection_factory(dedicated, environ, autocommit=True)
    return AsyncCheckpointAdapter(PyMySQLSaver(connect))


def resolve_mysql_dsn(settings: MySQLSettings, environ: Mapping[str, str]) -> str:
    """Resolve a DSN from existing MYSQL_* variables without logging secrets."""

    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise ValueError(f"required environment variable is missing: {name}")
        return value

    host = required(settings.host.env)
    port = required(settings.port.env)
    if not port.isdigit():
        raise ValueError(f"MySQL port must be numeric: {settings.port.env}")
    database = quote_plus(required(settings.database.env))
    user = quote_plus(required(settings.user.env))
    password = quote_plus(required(settings.password.env))
    charset = quote_plus(required(settings.charset.env))
    return f"mysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"


@contextmanager
def open_mysql_checkpointer(dsn: str, *, setup: bool = False) -> Iterator[Any]:
    """Open the MySQL saver behind a project-owned lifecycle boundary.

    ``setup`` performs database DDL and is reserved for an explicit deployment
    migration job. Application workers must not run it during normal startup.
    """
    from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver

    with PyMySQLSaver.from_conn_string(dsn) as saver:
        if setup:
            saver.setup()
        yield saver
