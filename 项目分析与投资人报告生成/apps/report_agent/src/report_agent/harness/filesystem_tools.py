"""Batch file editing: many exact replacements, one model round trip.

``edit_file`` replaces exactly one string per call. When a checker reports N
issues (for example ``check_citation`` listing every paragraph that needs a
``<!-- cite: -->`` marker), a model that repairs them one at a time spends N
model round trips — that is what exhausted the call budget in production.

``batch_edit`` performs the same replacements in order against the same
backend the filesystem middleware uses, so path resolution, uniqueness rules
and error messages stay identical to ``edit_file``. Every edit reports its own
status; a failure never aborts the remaining edits.
"""

from __future__ import annotations

import json
from typing import Any

from deepagents.backends.utils import validate_path
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

#: Upper bound on edits per call. Keeps one tool result small enough to stay
#: inside the inline tool-output budget and keeps a bad call from rewriting a
#: whole document by accident.
MAX_EDITS_PER_CALL = 50


class BatchEditItem(BaseModel):
    """One exact string replacement inside a single file."""

    old_string: str = Field(
        min_length=1,
        description="The exact text to find and replace. Must be unique in the file unless replace_all is true.",
    )
    new_string: str = Field(
        description="The text that replaces old_string. Must differ from old_string.",
    )
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence instead of requiring a unique match.",
    )


BATCH_EDIT_DESCRIPTION = """Apply several exact string replacements to one file in a single call.

Use this INSTEAD of calling edit_file repeatedly for the same file. When a
checker returns several issues for one document (for example check_citation
listing every paragraph that is missing a <!-- cite: --> marker), pass one
edit per issue here instead of one edit_file call per issue.

Rules:
- All edits target the same file_path.
- Each old_string must be unique in the file unless replace_all is true.
- Edits are applied in the order given, each against the file content
  produced by the previous edit.
- Every edit reports its own status. An edit whose old_string was not found
  does not abort the others; read the per-edit results and retry only what
  failed.
"""


def build_filesystem_tools(*, backend: Any) -> tuple[BaseTool, ...]:
    """Build workspace file tools bound to the agent's backend.

    The same ``backend`` instance the filesystem middleware uses is required so
    virtual path resolution matches ``edit_file`` exactly.
    """

    def batch_edit(file_path: str, edits: list[BatchEditItem]) -> str:
        if not isinstance(edits, list) or not edits:
            return json.dumps(
                {
                    "status": "error",
                    "error": "edits must be a non-empty list of {old_string, new_string}",
                    "usage": "call batch_edit(file_path, edits=[{old_string, new_string}])",
                },
                ensure_ascii=False,
            )
        if len(edits) > MAX_EDITS_PER_CALL:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"too many edits: {len(edits)} > {MAX_EDITS_PER_CALL}",
                    "hint": "split into several batch_edit calls",
                },
                ensure_ascii=False,
            )
        try:
            validated_path = validate_path(file_path)
        except ValueError as exc:
            return json.dumps(
                {"status": "error", "error": str(exc)}, ensure_ascii=False
            )

        results: list[dict[str, Any]] = []
        replaced = 0
        failed = 0
        for index, edit in enumerate(edits):
            outcome = backend.edit(
                validated_path,
                edit.old_string,
                edit.new_string,
                replace_all=edit.replace_all,
            )
            error = getattr(outcome, "error", None)
            if error:
                failed += 1
                results.append({"index": index, "status": "failed", "error": error})
                continue
            replaced += 1
            results.append(
                {
                    "index": index,
                    "status": "ok",
                    "occurrences": int(getattr(outcome, "occurrences", 0) or 0),
                }
            )

        payload: dict[str, Any] = {
            "status": "ok" if replaced else "error",
            "file_path": file_path,
            "requested": len(edits),
            "replaced": replaced,
            "failed": failed,
            "results": results,
        }
        if failed:
            payload["hint"] = (
                "failed edits were not applied; fix their old_string and retry only those"
            )
        return json.dumps(payload, ensure_ascii=False)

    return (
        StructuredTool.from_function(
            batch_edit,
            name="batch_edit",
            description=BATCH_EDIT_DESCRIPTION,
        ),
    )
