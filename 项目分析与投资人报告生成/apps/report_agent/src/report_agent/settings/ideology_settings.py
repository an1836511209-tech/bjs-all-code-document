"""Stand-alone configuration entry point for the ideology review tool.

Per SPEC ADR-0003 §决策 8, the YAML dictionary path is read from an
environment variable, with a built-in default that ships inside the image.
The strict ``ReportAgentSettings`` schema intentionally has no
``ideology_dictionary_path`` field because the dictionary is a workspace
artifact, not a deployment secret.
"""

from __future__ import annotations

import os
from pathlib import Path

from report_agent.application.ideology_review import DEFAULT_RULE_PATH

ENV_VAR = "IDEOLOGY_DICTIONARY_PATH"


def resolve_ideology_dictionary_path(
    *,
    explicit: Path | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the ideology dictionary path from the most specific source.

    Precedence (highest first):

    1. ``explicit`` (caller-supplied absolute path)
    2. ``$IDEOLOGY_DICTIONARY_PATH`` environment variable
    3. ``DEFAULT_RULE_PATH`` shipped inside the repo (resolved via
       ``Path(__file__).resolve()`` in ``ideology_review._default_rule_path``)
    """
    if explicit is not None:
        return explicit
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return Path(env_value)
    return Path(DEFAULT_RULE_PATH)