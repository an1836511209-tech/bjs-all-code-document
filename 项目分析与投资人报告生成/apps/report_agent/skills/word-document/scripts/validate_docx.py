"""Validate DOCX ZIP, OOXML and Word comment structure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from report_agent.infrastructure.word import WordReportValidator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("--expected-comments", type=int, required=True)
    args = parser.parse_args()
    issues = WordReportValidator().validate(args.docx, expected_comments=args.expected_comments)
    print(json.dumps([issue.model_dump() for issue in issues], ensure_ascii=False))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
