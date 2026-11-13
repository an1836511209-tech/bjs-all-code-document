"""Offline syntax validation for a serialized ReportContent."""

from __future__ import annotations

import argparse
from pathlib import Path

from report_agent.domain.report_content import ReportContent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("content", type=Path)
    args = parser.parse_args()
    ReportContent.model_validate_json(args.content.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
