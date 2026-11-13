"""Unit tests for the small MySQL connection pool."""

from __future__ import annotations

from typing import Any

import pytest

from report_agent.infrastructure.persistence.mysql_runs import MySQLConnectionPool


class _FakeConn:
    def __init__(self, *, fail_ping: bool = False) -> None:
        self.open = True
        self.closed = False
        self.rollbacks = 0
        self.pings = 0
        self._fail_ping = fail_ping

    def ping(self, reconnect: bool = False) -> None:
        self.pings += 1
        if self._fail_ping:
            self._fail_ping = False
            raise OSError("lost during handshake")

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True
        self.open = False


def test_close_returns_connection_to_pool() -> None:
    created: list[_FakeConn] = []

    def creator() -> _FakeConn:
        conn = _FakeConn()
        created.append(conn)
        return conn

    pool = MySQLConnectionPool(creator, maxsize=2)
    first = pool.acquire()
    first.close()
    second = pool.acquire()
    second.close()

    assert len(created) == 1
    assert created[0].pings == 2
    assert created[0].rollbacks == 2
    assert not created[0].closed


def test_dead_connection_is_replaced() -> None:
    created: list[_FakeConn] = []

    def creator() -> _FakeConn:
        conn = _FakeConn()
        created.append(conn)
        return conn

    pool = MySQLConnectionPool(creator, maxsize=2)
    first = pool.acquire()
    assert len(created) == 1
    first.close()

    created[0]._fail_ping = True
    second = pool.acquire()
    second.close()

    assert len(created) == 2
    assert created[0].closed
    assert not created[1].closed


def test_read_retries_when_mysql_connection_drops() -> None:
    import pymysql

    from report_agent.infrastructure.persistence.mysql_runs import MySQLRunRepository

    class _Cursor:
        def __init__(self, broken: bool) -> None:
            self._broken = broken

        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def execute(self, sql: str, args: object = None) -> None:
            if self._broken:
                raise pymysql.err.OperationalError(
                    2013, "Lost connection to MySQL server during query"
                )

        def fetchone(self) -> None:
            return None

        def fetchall(self) -> list[object]:
            return []

    class _Conn:
        def __init__(self, broken: bool) -> None:
            self.broken = broken
            self.closed = False

        def cursor(self) -> _Cursor:
            return _Cursor(self.broken)

        def close(self) -> None:
            self.closed = True

    opened: list[_Conn] = []

    def connect() -> _Conn:
        conn = _Conn(broken=len(opened) == 0)
        opened.append(conn)
        return conn

    assert MySQLRunRepository(connect).get_run("run_x") is None
    assert [conn.closed for conn in opened] == [True, True]


def test_read_does_not_retry_sql_errors() -> None:
    import pymysql

    from report_agent.infrastructure.persistence.mysql_runs import MySQLRunRepository

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def execute(self, sql: str, args: object = None) -> None:
            raise pymysql.err.OperationalError(1064, "syntax")

        def fetchone(self) -> None:
            return None

    class _Conn:
        def __init__(self) -> None:
            self.closed = False

        def cursor(self) -> _Cursor:
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    calls = 0

    def connect() -> _Conn:
        nonlocal calls
        calls += 1
        return _Conn()

    with pytest.raises(pymysql.err.OperationalError):
        MySQLRunRepository(connect).get_run("run_x")
    assert calls == 1


def test_pool_exhaustion_waits_then_errors() -> None:
    def creator() -> _FakeConn:
        return _FakeConn()

    pool = MySQLConnectionPool(creator, maxsize=1, checkout_timeout=0.05)
    held = pool.acquire()
    with pytest.raises(RuntimeError, match="exhausted"):
        pool.acquire()
    held.close()


def test_repository_style_close_is_idempotent() -> None:
    pool = MySQLConnectionPool(_FakeConn, maxsize=1)
    conn: Any = pool.acquire()
    conn.close()
    conn.close()
    reused = pool.acquire()
    reused.close()
