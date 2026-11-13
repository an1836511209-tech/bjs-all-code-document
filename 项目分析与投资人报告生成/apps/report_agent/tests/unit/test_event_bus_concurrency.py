"""事件总线要能承受工具线程的并发 publish：序号不能重、事件不能丢。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from report_agent.application.event_bus import RunEventBus
from report_agent.domain.events import EventType
from report_agent.domain.identifiers import RunIdentity

IDENTITY = RunIdentity(
    task_id="task_" + "d" * 32, session_id="s1", run_id="run_1", workspace_id="w1"
)


def test_concurrent_publishers_from_threads_keep_every_event():
    """`publish_report` 是同步工具，LangChain 把它丢到线程池执行。"""
    bus = RunEventBus()
    seen: list[int] = []
    bus.set_sink(lambda event: seen.append(bus.cursor(event.run_id)))

    def worker(index: int) -> None:
        for _ in range(50):
            bus.emit(IDENTITY, EventType.TOOL_STARTED, {"worker": index})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert bus.cursor("run_1") == 400, "并发写入不能丢事件"
    # 序号必须两两不同；重复意味着两条事件共用一个 seq，回放时会丢帧。
    assert len(set(seen)) == 400
    assert sorted(seen) == list(range(1, 401))


def test_sink_runs_under_the_same_lock_as_the_append():
    """sink 在锁内取 cursor，必须是"我刚追加的那一条"的序号。"""
    bus = RunEventBus()
    captured: list[tuple[int, int]] = []
    bus.set_sink(lambda event: captured.append((bus.cursor(event.run_id), len(captured) + 1)))

    for _ in range(5):
        bus.emit(IDENTITY, EventType.PLAN_UPDATED, {})

    assert [seq for seq, _ in captured] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_publishing_from_a_worker_thread_wakes_the_waiter():
    """跨线程 publish 必须用 call_soon_threadsafe，否则等待方永远收不到通知。"""
    bus = RunEventBus()
    signal = bus.signal_for("run_1")

    def worker() -> None:
        bus.emit(IDENTITY, EventType.RUN_COMPLETED, {})

    thread = threading.Thread(target=worker)
    thread.start()
    await asyncio.wait_for(signal.wait(), timeout=2.0)
    thread.join()

    assert signal.is_set()
    assert bus.is_terminal("run_1")


def test_forget_releases_the_buffer():
    bus = RunEventBus()
    bus.emit(IDENTITY, EventType.RUN_STARTED, {})
    assert bus.cursor("run_1") == 1
    bus.forget("run_1")
    assert bus.cursor("run_1") == 0
