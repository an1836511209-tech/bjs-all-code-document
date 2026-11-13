"""事件落盘：服务重启后前端仍能回放，而不是拿到空流。"""

from __future__ import annotations

from pathlib import Path

import pytest

from report_agent.application.event_bus import RunEventBus
from report_agent.application.runs import RunIdentity, SynchronousRunService
from report_agent.runtime.workspace import TaskWorkspace

TASK_ID = "task_" + "c" * 32


def _identity() -> RunIdentity:
    return RunIdentity(
        task_id=TASK_ID,
        session_id="session_1",
        run_id="run_1",
        workspace_id="workspace_1",
    )


class _Repository:
    def get_run(self, run_id: str):  # noqa: ANN201
        return type("Record", (), {"task_id": TASK_ID})()


@pytest.fixture()
def service(tmp_path: Path) -> SynchronousRunService:
    TaskWorkspace(tmp_path / TASK_ID).initialize()
    return SynchronousRunService(
        workspace_root=tmp_path,
        executor=object(),  # type: ignore[arg-type]
        repository=_Repository(),  # type: ignore[arg-type]
        event_bus=RunEventBus(),
    )


def test_events_are_written_to_the_task_log(service):
    from report_agent.application.event_bus import EventType

    service._emit(_identity(), EventType.RUN_STARTED, {"skill": "one-pager"})
    service._emit(_identity(), EventType.RUN_COMPLETED, {"artifacts": ["a.docx"]})

    path = service.workspace_root / TASK_ID / "logs" / "events.ndjson"
    assert path.is_file()
    frames = service.replay_events(TASK_ID)
    assert [frame["type"] for frame in frames] == ["run.started", "run.completed"]
    assert [frame["seq"] for frame in frames] == [1, 2]
    assert frames[0]["payload"] == {"skill": "one-pager"}
    assert frames[0]["occurred_at"] and frames[0]["run_id"] == "run_1"


def test_replay_is_empty_before_anything_happens(service):
    assert service.replay_events(TASK_ID) == []


def test_replay_rejects_a_malformed_task_id(service):
    assert service.replay_events("../../etc") == []
    assert service.replay_events("") == []


def test_replay_survives_a_truncated_line(service):
    from report_agent.application.event_bus import EventType

    service._emit(_identity(), EventType.RUN_STARTED, {})
    path = service.workspace_root / TASK_ID / "logs" / "events.ndjson"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"broken": \n')

    frames = service.replay_events(TASK_ID)
    assert len(frames) == 1, "坏行应被跳过，不能整段回放失败"


def test_a_direct_bus_emit_is_persisted_too(service):
    """工具事件由 bootstrap 直接 emit 到总线，不经过 ``_emit``，也必须落盘。

    实测踩到过：第一版只在 ``_emit`` 里落盘，回放出来只有 run.started 和
    run.completed 两条，工具轨迹全丢。
    """
    from report_agent.application.event_bus import EventType

    service.event_bus.emit(_identity(), EventType.TOOL_STARTED, {"tool": "read_file"})
    service.event_bus.emit(_identity(), EventType.TOOL_COMPLETED, {"tool": "read_file"})

    frames = service.replay_events(TASK_ID)
    assert [frame["type"] for frame in frames] == ["tool.started", "tool.completed"]


def test_identity_change_does_not_write_into_the_wrong_task(service):
    """非法 task_id 直接跳过，避免路径穿越写坏别处。"""
    from report_agent.application.event_bus import EventType

    service.event_bus.emit(
        RunIdentity(task_id="../../evil", session_id="s", run_id="r", workspace_id="w"),
        EventType.RUN_STARTED,
        {},
    )
    assert service.replay_events(TASK_ID) == []


def test_sequence_is_monotonic_across_runs_of_the_same_task(service):
    """一个会话多轮 run 共用一个 events.ndjson，序号必须接着走。

    按 run 重置会让 SSE 的 after_seq 游标失效：重启后订阅新一轮，要么重发上一轮
    的 run.completed，要么把新一轮的前 N 条事件静默丢掉。
    """
    from report_agent.application.event_bus import EventType

    first = _identity()
    second = RunIdentity(
        task_id=TASK_ID, session_id="session_1", run_id="run_2", workspace_id="workspace_1"
    )
    service._emit(first, EventType.RUN_STARTED, {"round": 1})
    service._emit(first, EventType.RUN_COMPLETED, {"round": 1})
    service._emit(second, EventType.RUN_STARTED, {"round": 2})
    service._emit(second, EventType.RUN_COMPLETED, {"round": 2})

    frames = service.replay_events(TASK_ID)
    assert [frame["seq"] for frame in frames] == [1, 2, 3, 4]
    assert [frame["run_id"] for frame in frames] == ["run_1", "run_1", "run_2", "run_2"]


def test_a_new_service_instance_can_replay_what_the_old_one_wrote(tmp_path):
    """模拟重启：新进程只靠磁盘就能重建事件流。"""
    from report_agent.application.event_bus import EventType

    TaskWorkspace(tmp_path / TASK_ID).initialize()
    first = SynchronousRunService(
        workspace_root=tmp_path,
        executor=object(),  # type: ignore[arg-type]
        repository=_Repository(),  # type: ignore[arg-type]
        event_bus=RunEventBus(),
    )
    first._emit(_identity(), EventType.RUN_STARTED, {"skill": "investment-report"})

    restarted = SynchronousRunService(
        workspace_root=tmp_path,
        executor=object(),  # type: ignore[arg-type]
        repository=_Repository(),  # type: ignore[arg-type]
        event_bus=RunEventBus(),
    )
    assert restarted.event_bus.cursor("run_1") == 0, "新进程内存里当然是空的"
    frames = restarted.replay_events(TASK_ID)
    assert [frame["type"] for frame in frames] == ["run.started"]
