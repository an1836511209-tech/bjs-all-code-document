"""Stable recognition contracts for page-level document recognition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from report_agent.domain.materials import PageImage


@dataclass(frozen=True, slots=True)
class PageRecognition:
    text: str
    confidence: float | None = None


class PageRecognizer(Protocol):
    """Per-page recognizer (e.g. multimodal vision model)."""

    def recognize(self, page: PageImage) -> PageRecognition: ...
