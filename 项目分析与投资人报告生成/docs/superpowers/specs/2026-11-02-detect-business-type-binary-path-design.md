# detect_one_pager_business_type binary path fallback

## Problem

`detect_one_pager_business_type` called `workspace.read_text(material_path)`. Agents often pass `/workspace/input/*.pdf` after `parse_materials`, which fails with a UTF-8 decode error. Wrong areas like `/workspace/materials/...` also fail.

## Approach

Keep the tool signature. Resolve text in this order:

1. `material_path` matching `material_[32hex]` → load `/workspace/working/materials/{id}.json` blocks
2. Path to a materials JSON (or JSON with `blocks`) → extract block texts
3. UTF-8 `read_text` succeeds → use that text
4. Binary / decode failure / unknown area → match `working/materials/*.json` by `source_name` / basename; require a unique hit
5. Otherwise return `status=failed` with a clear “parse first / pass material_id” error

Also update the tool description and one-pager skill prompt so agents know input paths and `material_id` are both valid.

## Out of scope

Sandbox / bubblewrap cgroup issues.
