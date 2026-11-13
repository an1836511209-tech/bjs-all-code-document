"""Deterministic lifecycle for one report-production task."""

from __future__ import annotations

from enum import StrEnum


class WorkflowTransitionError(ValueError):
    pass


class WorkflowStatus(StrEnum):
    INGESTED = "ingested"
    MATERIALS_READY = "materials_ready"
    METADATA_PENDING_CONFIRMATION = "metadata_pending_confirmation"
    DATA_READY = "data_ready"
    DRAFT_READY = "draft_ready"
    DOCX_RENDERED = "docx_rendered"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
)

_ALLOWED_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.INGESTED: frozenset(
        {WorkflowStatus.MATERIALS_READY, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.MATERIALS_READY: frozenset(
        {
            WorkflowStatus.METADATA_PENDING_CONFIRMATION,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.METADATA_PENDING_CONFIRMATION: frozenset(
        {WorkflowStatus.DATA_READY, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.DATA_READY: frozenset(
        {WorkflowStatus.DRAFT_READY, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.DRAFT_READY: frozenset(
        {WorkflowStatus.DOCX_RENDERED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.DOCX_RENDERED: frozenset(
        {
            WorkflowStatus.DRAFT_READY,
            WorkflowStatus.VALIDATED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.VALIDATED: frozenset(
        {
            WorkflowStatus.DRAFT_READY,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
}


def require_transition(current: WorkflowStatus, target: WorkflowStatus) -> WorkflowStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise WorkflowTransitionError(f"invalid workflow transition: {current} -> {target}")
    return target
