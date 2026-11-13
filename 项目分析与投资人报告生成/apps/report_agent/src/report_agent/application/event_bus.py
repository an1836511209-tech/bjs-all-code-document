"""In-process event bus for the Run Console SSE stream.

One run is short-lived and executes inside a single worker process, so an
in-memory buffer is enough: the SSE endpoint replays from ``since`` and then
follows new events until the run reaches a terminal state.

This module deliberately owns no external dependencies. It only stores
``AgentEvent`` values created by the domain model.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any

from report_agent.domain.events import AgentEvent, EventType
from report_agent.domain.identifiers import RunIdentity

#: Event types after which the console stops following the stream.
TERMINAL_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.APPROVAL_REQUIRED}
)


class RunEventBus:
    """Append-only, per-run event buffer with an async wake-up signal.

    Thread-safe on purpose: the agent guard publishes from the event loop, but
    ``publish_report`` is a *synchronous* tool that LangChain runs in a worker
    thread, and its events must not corrupt the buffer or lose their sequence.
    """

    def __init__(self, sink: Callable[[AgentEvent], None] | None = None) -> None:
        self._events: dict[str, list[AgentEvent]] = defaultdict(list)
        self._signals: dict[str, asyncio.Event] = {}
        self._loops: dict[str, asyncio.AbstractEventLoop] = {}
        # Re-entrant: ``publish`` holds the lock while invoking the durability
        # sink, and that sink asks for the event's sequence via ``cursor``.
        self._lock = threading.RLock()
        #: Optional durability hook. Guards that emit straight into the bus
        #: (the agent stream handler in ``bootstrap``) must be persisted too,
        #: otherwise a replay only contains run.started / run.completed.
        self._sink = sink

    def set_sink(self, sink: Callable[[AgentEvent], None] | None) -> None:
        self._sink = sink

    # -- producer ---------------------------------------------------------
    def publish(self, event: AgentEvent) -> None:
        # Append + sink under one lock: the sink records the event's sequence,
        # and computing it outside the lock lets two threads take the same one.
        with self._lock:
            self._events[event.run_id].append(event)
            if self._sink is not None:
                self._sink(event)
        signal = self._signals.get(event.run_id)
        if signal is None:
            return
        loop = self._loops.get(event.run_id)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            # Publishing from a worker thread: asyncio objects belong to one loop.
            loop.call_soon_threadsafe(signal.set)
        else:
            signal.set()

    def emit(
        self,
        identity: RunIdentity,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        event = AgentEvent.create(event_type, identity, payload)
        self.publish(event)
        return event

    # -- consumer ---------------------------------------------------------
    def events(self, run_id: str) -> list[AgentEvent]:
        with self._lock:
            return list(self._events.get(run_id, ()))

    def since(self, run_id: str, cursor: int) -> list[AgentEvent]:
        """Return events strictly after ``cursor`` (0-based index)."""
        with self._lock:
            return self._events.get(run_id, ())[cursor:]

    def cursor(self, run_id: str) -> int:
        with self._lock:
            return len(self._events.get(run_id, ()))

    def is_terminal(self, run_id: str) -> bool:
        with self._lock:
            snapshot = list(self._events.get(run_id, ()))
        return any(event.type in TERMINAL_EVENT_TYPES for event in snapshot)

    def signal_for(self, run_id: str) -> asyncio.Event:
        signal = self._signals.get(run_id)
        if signal is None:
            signal = asyncio.Event()
            self._signals[run_id] = signal
        try:
            self._loops[run_id] = asyncio.get_running_loop()
        except RuntimeError:
            pass  # created outside a loop: publish() falls back to signal.set()
        return signal

    def iter_events(self, run_id: str) -> Iterator[AgentEvent]:
        return iter(self.events(run_id))

    def forget(self, run_id: str) -> None:
        """Drop a run's buffer once it is finished and nobody is reading it."""
        with self._lock:
            self._events.pop(run_id, None)
        self._signals.pop(run_id, None)
        self._loops.pop(run_id, None)
