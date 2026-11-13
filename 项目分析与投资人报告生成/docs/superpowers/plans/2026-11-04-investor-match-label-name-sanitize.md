# Investor match label_name sanitize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip wrapping quotes from each track tag before DMP `label_name` is joined, so report match and workbook export always send `住宿业,餐饮业` instead of `"住宿业","餐饮业"`.

**Architecture:** Add a tiny shared helper `strip_wrapping_quotes` in `tag_normalize.py`. Call it from report `_normalize_tags`, workbook `normalize_track_tags`, and DMP join/export body builders so both entry and exit paths sanitize.

**Tech Stack:** Python 3, unittest/pytest in `apps/data_mcp`, existing investor_match modules.

**Spec:** `docs/superpowers/specs/2026-11-04-investor-match-label-name-sanitize-design.md`

## Global Constraints

- Auto-sanitize only; do not reject quoted tags.
- Strip only paired outer `"` or `'` (repeatable); never delete mid-tag quotes.
- DMP `label_name` remains English-comma-joined plain text; `label_type` stays `股权转让/增资`.
- Do not change listed_peer_match or DMP remote API contracts.
- Commit message style when committing: `English: 中文说明`.

## File Structure

| File | Responsibility |
|---|---|
| Create: `apps/data_mcp/src/data_mcp/features/investor_match/tag_normalize.py` | `strip_wrapping_quotes` |
| Create: `apps/data_mcp/tests/unit/features/investor_match/test_tag_normalize.py` | helper unit tests |
| Modify: `apps/data_mcp/src/data_mcp/features/investor_match/service.py` | `_normalize_tags` uses helper |
| Modify: `apps/data_mcp/src/data_mcp/features/investor_match/workbook.py` | `normalize_track_tags` uses helper |
| Modify: `apps/data_mcp/src/data_mcp/features/investor_match/dmp_client.py` | `_join_label_names` + export join use helper |
| Modify: `apps/data_mcp/tests/unit/features/investor_match/test_investor_match.py` | `_normalize_tags` / `_join_label_names` cases |
| Modify: `apps/data_mcp/tests/unit/features/investor_match/test_workbook.py` | quoted-tag normalize case |

---

### Task 1: Shared `strip_wrapping_quotes` helper

**Files:**
- Create: `apps/data_mcp/src/data_mcp/features/investor_match/tag_normalize.py`
- Test: `apps/data_mcp/tests/unit/features/investor_match/test_tag_normalize.py`

**Interfaces:**
- Produces: `strip_wrapping_quotes(tag: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# apps/data_mcp/tests/unit/features/investor_match/test_tag_normalize.py
from __future__ import annotations

import unittest


class StripWrappingQuotesTests(unittest.TestCase):
    def test_strips_paired_double_and_single_quotes(self) -> None:
        from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes

        self.assertEqual(strip_wrapping_quotes('"住宿业"'), "住宿业")
        self.assertEqual(strip_wrapping_quotes("'餐饮业'"), "餐饮业")
        self.assertEqual(strip_wrapping_quotes('  "物业管理"  '), "物业管理")
        self.assertEqual(strip_wrapping_quotes('""电信""'), "电信")

    def test_leaves_clean_and_internal_quotes(self) -> None:
        from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes

        self.assertEqual(strip_wrapping_quotes("集成电路制造"), "集成电路制造")
        self.assertEqual(strip_wrapping_quotes('含"内部"引号'), '含"内部"引号')
        self.assertEqual(strip_wrapping_quotes(""), "")
        self.assertEqual(strip_wrapping_quotes("   "), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `apps/data_mcp`):

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_tag_normalize.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `tag_normalize`.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/data_mcp/src/data_mcp/features/investor_match/tag_normalize.py
"""Shared track-tag string cleanup for investor match / DMP label_name."""

from __future__ import annotations


def strip_wrapping_quotes(tag: str) -> str:
    """Remove paired outer ASCII quotes; leave internal quotes untouched."""
    text = str(tag).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_tag_normalize.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_mcp/src/data_mcp/features/investor_match/tag_normalize.py apps/data_mcp/tests/unit/features/investor_match/test_tag_normalize.py
git commit -m "feat(investor-match): add strip_wrapping_quotes helper: 新增标签外层引号剥离工具函数"
```

---

### Task 2: Sanitize report `_normalize_tags`

**Files:**
- Modify: `apps/data_mcp/src/data_mcp/features/investor_match/service.py` (`_normalize_tags`)
- Modify: `apps/data_mcp/tests/unit/features/investor_match/test_investor_match.py`

**Interfaces:**
- Consumes: `strip_wrapping_quotes(tag: str) -> str`
- Produces: `_normalize_tags` returns list without wrapping quotes

- [ ] **Step 1: Write the failing test**

Add to `test_investor_match.py`:

```python
class NormalizeTagsTests(unittest.TestCase):
    def test_strips_wrapping_quotes_from_string_and_list(self) -> None:
        from data_mcp.features.investor_match.service import _normalize_tags

        self.assertEqual(
            _normalize_tags('"住宿业","餐饮业","物业管理"'),
            ["住宿业", "餐饮业", "物业管理"],
        )
        self.assertEqual(
            _normalize_tags(['"集成电路制造"', '"特种电子"']),
            ["集成电路制造", "特种电子"],
        )
        self.assertEqual(
            _normalize_tags("集成电路制造,高可靠功率半导体"),
            ["集成电路制造", "高可靠功率半导体"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_investor_match.py::NormalizeTagsTests -v
```

Expected: FAIL — tags still contain `"` characters.

- [ ] **Step 3: Update `_normalize_tags`**

In `service.py`, import and apply:

```python
from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes


def _normalize_tags(track_tags: str | list[Any] | None) -> list[str]:
    if track_tags is None:
        return []
    if isinstance(track_tags, list):
        return [
            strip_wrapping_quotes(str(t))
            for t in track_tags
            if strip_wrapping_quotes(str(t))
        ]
    text = str(track_tags).strip()
    if not text:
        return []
    cleaned = text.strip("[]")
    parts = []
    for sep in ("，", ",", ";", "；", "|"):
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep)]
            break
    if not parts:
        parts = [cleaned]
    return [stripped for p in parts if (stripped := strip_wrapping_quotes(p))]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_investor_match.py::NormalizeTagsTests -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_mcp/src/data_mcp/features/investor_match/service.py apps/data_mcp/tests/unit/features/investor_match/test_investor_match.py
git commit -m "fix(investor-match): strip quotes in report track_tags: 报告匹配入参规范化时剥掉标签外层引号"
```

---

### Task 3: Sanitize workbook `normalize_track_tags`

**Files:**
- Modify: `apps/data_mcp/src/data_mcp/features/investor_match/workbook.py`
- Modify: `apps/data_mcp/tests/unit/features/investor_match/test_workbook.py`

**Interfaces:**
- Consumes: `strip_wrapping_quotes(tag: str) -> str`
- Produces: `normalize_track_tags` returns tags without wrapping quotes

- [ ] **Step 1: Write the failing test**

Extend `test_normalized_tags_reject_expansion_and_invalid_arrays` (or add sibling):

```python
def test_normalize_track_tags_strips_wrapping_quotes():
    assert normalize_track_tags('"住宿业","餐饮业"') == ["住宿业", "餐饮业"]
    assert normalize_track_tags(['"集成电路制造"', '"特种电子"']) == [
        "集成电路制造",
        "特种电子",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_workbook.py::test_normalize_track_tags_strips_wrapping_quotes -v
```

Expected: FAIL — results still quoted (or fail equality).

- [ ] **Step 3: Update `normalize_track_tags`**

```python
from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes


def normalize_track_tags(value: str | list[str]) -> list[str]:
    raw = _SEPARATORS.split(value) if isinstance(value, str) else value
    if not isinstance(raw, list) or not raw or any(not isinstance(t, str) for t in raw):
        raise ValueError("INVALID_TAGS")
    tags: dict[str, str] = {}
    for tag in raw:
        tag = strip_wrapping_quotes(" ".join(unicodedata.normalize("NFKC", tag).split()))
        if tag:
            if len(tag) > 160 or _SEPARATORS.search(tag) or _ILLEGAL.search(tag):
                raise ValueError("INVALID_TAGS")
            tags.setdefault(normalized(tag), tag)
    if not 1 <= len(tags) <= 10:
        raise ValueError("INVALID_TAG_COUNT")
    return list(tags.values())
```

Note: apply `strip_wrapping_quotes` after NFKC/whitespace collapse and before length/separator/illegal checks.

- [ ] **Step 4: Run related workbook tests**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_workbook.py::test_normalize_track_tags_strips_wrapping_quotes tests/unit/features/investor_match/test_workbook.py::test_normalized_tags_reject_expansion_and_invalid_arrays -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/data_mcp/src/data_mcp/features/investor_match/workbook.py apps/data_mcp/tests/unit/features/investor_match/test_workbook.py
git commit -m "fix(investor-match): strip quotes in workbook track tags: 匹配表导出标签规范化时剥掉外层引号"
```

---

### Task 4: DMP join / export exit sanitization

**Files:**
- Modify: `apps/data_mcp/src/data_mcp/features/investor_match/dmp_client.py` (`_join_label_names`, `query_dmp_institutions_for_export` body)
- Modify: `apps/data_mcp/tests/unit/features/investor_match/test_investor_match.py`

**Interfaces:**
- Consumes: `strip_wrapping_quotes(tag: str) -> str`
- Produces: `_join_label_names(list[str]) -> str` with no wrapping quotes in joined value

- [ ] **Step 1: Write the failing test**

```python
class JoinLabelNamesTests(unittest.TestCase):
    def test_join_strips_wrapping_quotes(self) -> None:
        from data_mcp.features.investor_match.dmp_client import _join_label_names

        self.assertEqual(
            _join_label_names(['"住宿业"', '"餐饮业"', "物业管理"]),
            "住宿业,餐饮业,物业管理",
        )
        self.assertEqual(
            _join_label_names(["集成电路制造", "高可靠功率半导体"]),
            "集成电路制造,高可靠功率半导体",
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_investor_match.py::JoinLabelNamesTests -v
```

Expected: FAIL — joined string still contains `"`.

- [ ] **Step 3: Update `_join_label_names` and export join**

```python
from data_mcp.features.investor_match.tag_normalize import strip_wrapping_quotes


def _join_label_names(label_names: list[str]) -> str:
    return ",".join(
        stripped
        for x in label_names
        if (stripped := strip_wrapping_quotes(str(x)))
    )
```

In `query_dmp_institutions_for_export`, replace:

```python
label_name=",".join(selected_tags),
```

with:

```python
label_name=_join_label_names(selected_tags),
```

so export and report share the same join path.

- [ ] **Step 4: Run DMP-related unit tests**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match/test_investor_match.py::JoinLabelNamesTests tests/unit/features/investor_match/test_investor_match.py::DmpClientTests tests/unit/features/investor_match/test_workbook.py -v
```

Expected: PASS (existing `label_name == "金融,机械设备"` / `"甲,乙"` assertions still hold).

- [ ] **Step 5: Commit**

```bash
git add apps/data_mcp/src/data_mcp/features/investor_match/dmp_client.py apps/data_mcp/tests/unit/features/investor_match/test_investor_match.py
git commit -m "fix(dmp): sanitize label_name join for report and export: DMP label_name 拼接前统一剥离标签外层引号"
```

---

### Task 5: Full investor_match regression + spec/plan check-in

**Files:**
- Verify only (no code unless a test fails)
- Optionally add: already-written spec/plan under `docs/superpowers/`

- [ ] **Step 1: Run full investor_match unit suite**

```bash
.venv310/Scripts/python.exe -m pytest tests/unit/features/investor_match -v
```

Expected: all PASS

- [ ] **Step 2: Commit docs if not already tracked**

```bash
git add docs/superpowers/specs/2026-11-04-investor-match-label-name-sanitize-design.md docs/superpowers/plans/2026-11-04-investor-match-label-name-sanitize.md
git commit -m "docs: investor-match label_name sanitize spec and plan: 补充标签引号清洗设计与实现计划"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| Shared `strip_wrapping_quotes` in `tag_normalize.py` | Task 1 |
| `service._normalize_tags` | Task 2 |
| `workbook.normalize_track_tags` | Task 3 |
| `_join_label_names` + export join | Task 4 |
| Unit tests for dirty + clean inputs | Tasks 1–4 |
| No real DMP integration / listed_peer out of scope | honored |
