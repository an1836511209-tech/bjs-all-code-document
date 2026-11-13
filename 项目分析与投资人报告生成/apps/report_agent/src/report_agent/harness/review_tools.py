"""Harness tools for the second review.

Preferred investment-report path:

1. ``run_writing_review`` – one call that merges data_field / citation / ai_tells
   (decision support only; not blocking).
2. ``review_ideological_text`` – the ONLY blocking gate; looped until clean.
3. ``check_report(checks=['quality'])`` – final credential check.

The three individual check_* tools remain for one-pager / ad-hoc use.
"""

from __future__ import annotations

import json
import re

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

#: Hard ceiling for the ideology loop, so a stubborn finding cannot burn the
#: whole run budget. The agent is expected to converge well before this.
MAX_IDEOLOGY_ROUNDS = 5

#: Per-run ideology round counter (process-local, acceptable for the console).
_ideology_rounds: dict[str, int] = {}


def _normalize_checks(checks: list[str] | str | None) -> list[str]:
    """Accept a list, a JSON-encoded list, or a comma-separated string.

    The model frequently emits ``checks='["quality"]'`` instead of a real
    array; pydantic then rejects the call and the agent retries the same
    malformed input until the budget runs out.
    """
    if checks is None:
        return ["quality"]
    if isinstance(checks, list):
        return [str(c).strip() for c in checks if str(c).strip()]
    raw = str(checks).strip()
    if not raw:
        return ["quality"]
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(c).strip() for c in parsed if str(c).strip()]
        raw = raw.strip("[]")
    return [part for part in re.split(r"[,，\s]+", raw) if part]


class CheckReportArgs(BaseModel):
    """``checks`` 允许字符串或数组：模型常把 JSON 数组当字符串传。"""

    md_path: str = Field(min_length=1, description="报告 markdown 的虚拟路径")
    checks: str | list[str] = Field(
        default="['quality','ai_tells']",
        description="要跑的检查项，取值 quality / ai_tells，可传数组或逗号分隔字符串",
    )


def build_review_tools(checker, *, workspace=None, run_key: str = "") -> tuple[StructuredTool, ...]:
    from report_agent.application.review_checker import AITellDetector

    ai_tell = AITellDetector()

    def _read(md_path: str) -> str:
        if workspace is not None:
            return workspace.resolve(md_path).read_text(encoding="utf-8")
        from pathlib import Path

        path = Path(md_path)
        if not path.is_file():
            raise ValueError(f"check_report: file not found: {md_path}")
        return path.read_text(encoding="utf-8")

    def _payload(step: str, issues, note: str, **extra) -> str:
        body = {
            "step": step,
            "blocking": False,
            "issues": [issue.model_dump() for issue in issues],
            "count": len(issues),
            "note": note,
        }
        body.update(extra)
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def check_data_field(md_path: str) -> str:
        issues = checker.check_data_field(_read(md_path))
        return _payload(
            "data_field",
            issues,
            "章节完整性参考：材料有则补写，材料无则写『材料未披露』。不阻塞发布。",
        )

    def check_citation(md_path: str) -> str:
        issues = checker.check_citation(_read(md_path))
        orphans = [i for i in issues if i.kind == "orphaned_citation"]
        mismatched = [i for i in issues if i.kind == "citation_mismatch"]
        return _payload(
            "citation",
            issues,
            "验证已有引用：证据是否存在、引用的数字是否真的在该证据里。不阻塞发布。",
            orphan_count=len(orphans),
            mismatch_count=len(mismatched),
        )

    def check_ai_tells(md_path: str) -> str:
        issues = ai_tell.check(_read(md_path))
        return _payload(
            "ai_tells",
            issues,
            "AI 用语建议：按 excerpt 直接定位改写，判断为必要表达可保留。不阻塞发布。",
        )

    def check_report(md_path: str, checks: list[str] | str | None = None) -> str:
        """Legacy combined check, kept for the one-pager skill."""
        text = _read(md_path)
        # 模型有时把数组当字符串传（'["quality"]'），直接走 pydantic 会抛
        # "Input should be a valid list" 并让它反复重试。这里容错解析一次。
        requested = _normalize_checks(checks)
        requested = [c for c in requested if c in ("quality", "ai_tells")]
        if not requested:
            requested = ["quality"]
        issues = []
        if "quality" in requested:
            issues += checker.check(text)
        if "ai_tells" in requested:
            issues += ai_tell.check(text)
        blocking = [i for i in issues if i.severity == "block"]
        warnings = [i for i in issues if i.severity != "block"]
        return json.dumps(
            {
                "step": "legacy_check_report",
                "blocking": bool(blocking),
                "issues": [i.model_dump() for i in blocking],
                "warnings": [i.model_dump() for i in warnings],
                "block_count": len(blocking),
                "warning_count": len(warnings),
                "hint": "block_count=0 即通过；warnings 不需要修。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def run_writing_review(md_path: str) -> str:
        """One non-blocking pass: data_field + citation + ai_tells."""
        text = _read(md_path)
        data_field = checker.check_data_field(text)
        citation = checker.check_citation(text)
        tells = ai_tell.check(text)
        orphans = [i for i in citation if i.kind == "orphaned_citation"]
        mismatched = [i for i in citation if i.kind == "citation_mismatch"]
        issues = list(data_field) + list(citation) + list(tells)
        return json.dumps(
            {
                "step": "writing_review",
                "blocking": False,
                "issues": [issue.model_dump() for issue in issues],
                "count": len(issues),
                "by_step": {
                    "data_field": len(data_field),
                    "citation": len(citation),
                    "ai_tells": len(tells),
                },
                "orphan_count": len(orphans),
                "mismatch_count": len(mismatched),
                "note": (
                    "章节/引用/AI 用语一次返回，不阻塞发布。"
                    "有可修项时用一次 batch_edit 清完，再进 review_ideological_text。"
                ),
                "hint": (
                    "意识形态修完后调用 check_report(checks=['quality','ai_tells']) 作为完成凭据；"
                    "不要再分别连调 check_data_field / check_citation / check_ai_tells。"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return (
        StructuredTool.from_function(
            check_report,
            name="check_report",
            description=(
                "兼容入口（一页纸 skill / 投资报告完成凭据）：checks 接受 "
                "['quality','ai_tells'] 的子集；传字符串或数组都可。"
                "返回 block 级 issues 与不阻塞的 warnings。"
            ),
            args_schema=CheckReportArgs,
        ),
        StructuredTool.from_function(
            run_writing_review,
            name="run_writing_review",
            description=(
                "投资报告二次审查首选入口：一次合并章节完整性、引用校验与 AI 用语建议。"
                "blocking=false。有问题用一次 batch_edit 修完，再调 review_ideological_text。"
            ),
        ),
        StructuredTool.from_function(
            check_data_field,
            name="check_data_field",
            description=(
                "单独检查章节编排与关键点完整性。"
                "投资报告请优先用 run_writing_review。属于决策数据，不阻塞发布。"
            ),
        ),
        StructuredTool.from_function(
            check_citation,
            name="check_citation",
            description=(
                "单独验证已有 <!-- cite -->。"
                "投资报告请优先用 run_writing_review。属于决策数据，不阻塞发布。"
            ),
        ),
        StructuredTool.from_function(
            check_ai_tells,
            name="check_ai_tells",
            description=(
                "单独列出 AI 用语命中项。"
                "投资报告请优先用 run_writing_review。属于决策数据，不阻塞发布。"
            ),
        ),
    )
