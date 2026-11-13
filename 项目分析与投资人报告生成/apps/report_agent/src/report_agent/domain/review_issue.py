"""Report quality and AI-tell detection issue types.

Used by ReviewChecker + AITellDetector (application/review_checker.py)
and surfaced to agents via the check_report harness tool.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


IssueKind = Literal[
    # Quality dimensions (Task 2)
    "missing_section",
    "missing_citation",
    "orphaned_citation",
    "citation_mismatch",
    "uncited_fact",
    # 段落里出现敏感数字或政策表述却没有 cite（来源缺失），只作写作建议
    "uncited_sensitive",
    "missing_data_field",
    "empty_table_cell",
    "imbalanced_chapters",
    "truncated_section",
    "inconsistent_number_format",
    "missing_unit",
    "inconsistent_date_format",
    "placeholder_text",
    "fabricated_number",
    "inconsistent_terminology",
    "abbreviation_undefined",
    # AI-tell dimensions (Task 3)
    "template_transition",
    "conclusion_cliche",
    "bureaucratic_phrase",
    "list_overuse",
    "em_dash_overuse",
    "uniform_paragraph",
    "ai_vocabulary",
    "fake_specificity",
    "repeated_phrase",
    # One-pager dimensions (borrowed from the Lingda low-code workflow)
    "section_restatement",
    "unsupported_attribution",
    # A status word (已完成/进行中/验证…) that the cited evidence does not
    # carry. Materials draw progress matrices as shapes, so the text layer
    # often has no status at all — the report must say "not disclosed".
    "state_claim_without_source",
    # A web citation missing publisher / title / link / retrieval date.
    "web_source_incomplete",
    # 绝对化 / 夸大 / 承诺性表述。都不阻塞，但要求补出处或改成事实——
    # 没有出处的「唯一」「首个」「必然」是投资人最先质疑的地方。
    "absolute_claim",
    "exaggerated_claim",
    "promissory_claim",
]


class ReportIssue(BaseModel):
    """A single issue produced by quality or AI-tell detection.

    Block-severity issues must be repaired by the agent before proceeding
    to create_word_from_md. Warn-severity issues are advisory.

    The ``excerpt`` / ``terms`` / ``paragraph`` fields exist so the four-step
    review can hand the agent a *construction plan* (what to change and where)
    instead of only a count. Without them the model had to grep the report to
    locate each hit, which is what made the review loop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    section: str = ""
    kind: IssueKind
    severity: Literal["block", "warn"]
    locations: list[int] = Field(default_factory=list)
    count: int = 0
    message: str
    suggestion: str = ""
    # --- decision support ---
    excerpt: str = ""            # offending text, usable as edit_file match
    paragraph: int | None = None
    terms: list[str] = Field(default_factory=list)   # concrete matched words
    evidence_id: str = ""        # citation-related
    cited_tool: str = ""         # tool that produced the cited evidence
    expected_tool: str = ""      # tool the sentence topic implies
    fixable: bool = True


class CheckResult(BaseModel):
    """Aggregate result of one check_report call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issues: list[ReportIssue]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.issues:
            out[i.kind] = out.get(i.kind, 0) + 1
        return out

    def block_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "block")
