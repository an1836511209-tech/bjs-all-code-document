"""Immutable deployment settings."""

from report_agent.settings.loader import load_settings
from report_agent.settings.models import ReportAgentSettings

__all__ = ["ReportAgentSettings", "load_settings"]
