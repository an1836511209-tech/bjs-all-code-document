"""MySQLRunRepository.create must support follow-up runs on an existing task."""

from __future__ import annotations

from report_agent.domain.identifiers import RunIdentity
from report_agent.infrastructure.persistence.mysql_runs import MySQLRunRepository


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def execute(self, sql: str, args: object = None) -> None:
        self.statements.append((sql.strip(), args if isinstance(args, tuple) else None))

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[object]:
        return []


class _RecordingConn:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self.cursor_obj = cursor
        self.committed = False
        self.closed = False

    def cursor(self) -> _RecordingCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_create_uses_upsert_for_task_and_session_then_inserts_run() -> None:
    cursor = _RecordingCursor()
    conn = _RecordingConn(cursor)
    identity = RunIdentity.create()
    MySQLRunRepository(lambda: conn).create(identity, "hello")
    sqls = [sql for sql, _ in cursor.statements]
    assert any("INSERT INTO report_agent_tasks" in sql and "ON DUPLICATE KEY UPDATE" in sql for sql in sqls)
    assert any("INSERT INTO report_agent_sessions" in sql and "ON DUPLICATE KEY UPDATE" in sql for sql in sqls)
    assert sum(1 for sql in sqls if "INSERT INTO report_agent_runs" in sql) == 1
    assert conn.committed and conn.closed
