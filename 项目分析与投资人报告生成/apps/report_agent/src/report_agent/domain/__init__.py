"""Core domain models independent from web and infrastructure frameworks."""

from report_agent.domain.identifiers import RunIdentity
from report_agent.domain.workflow import WorkflowStatus, require_transition

__all__ = ["RunIdentity", "WorkflowStatus", "require_transition"]
