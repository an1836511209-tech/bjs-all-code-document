"""Shared paths and isolated configuration for the Data MCP test suite."""

from __future__ import annotations

import os
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = TESTS_ROOT / "fixtures"
CONFIG_FIXTURES = FIXTURES_ROOT / "config"
DATA_FIXTURES = FIXTURES_ROOT / "data"
RESPONSE_FIXTURES = FIXTURES_ROOT / "responses"
EXPECTED_FIXTURES = FIXTURES_ROOT / "expected"
DEFAULT_TEST_CONFIG = CONFIG_FIXTURES / "integration.yaml"

os.environ.setdefault("DATA_MCP_CONFIG", str(DEFAULT_TEST_CONFIG))
