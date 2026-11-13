"""LangChain tool adapter for the ideology review dictionary.

Exposes one tool, ``review_ideological_text(text: str) -> str``. The tool
performs only string / regex matching against the YAML dictionary; it does
not judge, rewrite, or auto-correct. The Agent decides what to do with each
match in ``matches``.

Serialization follows the existing project style used by
``harness/report_tools._ack``:

    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from langchain_core.tools import StructuredTool

from report_agent.application.ideology_review import IdeologyMatch, IdeologyReviewer

TOOL_NAME = "review_ideological_text"

#: Ideology is the only blocking review step; cap the loop so a stubborn
#: finding cannot consume the whole run budget.
MAX_IDEOLOGY_ROUNDS = 5

#: Process-local per-run round counter.
_rounds: dict[str, int] = {}


def build_ideology_tools(
    dictionary_path: Path,
    *,
    run_key: str = "",
) -> tuple[StructuredTool, ...]:
    """Construct the ideology review tool from a YAML dictionary.

    The dictionary is loaded eagerly so that any path / schema / regex error
    surfaces at construction time and propagates to the Agent per SPEC §4.2
    M-1 — the tool is never silently omitted.
    """
    reviewer = IdeologyReviewer(dictionary_path)

    def review_ideological_text(text: str) -> str:
        """Scan ``text`` against the ideology dictionary and return matches.

        The tool performs only string / regex matching; it does not judge,
        rewrite, or auto-correct the text. The caller (model) decides what
        to do with each match. Returns a compact JSON string with shape:
          {"matches":[{rule_id,category_label,severity,original,suggestion,
                       context,path,offset,length}],
           "summary":{"total":int,"by_category":{label:count},
                       "by_severity":{sev:count}}}.
        """
        matches = reviewer.review(text)
        key = run_key or "default"
        round_no = _rounds.get(key, 0) + 1
        _rounds[key] = round_no

        if not matches:
            return json.dumps(
                {
                    "step": "ideology",
                    "blocking": False,
                    "round": round_no,
                    "matches": [],
                    "summary": {"total": 0},
                    "next_action": "proceed",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

        forced = round_no >= MAX_IDEOLOGY_ROUNDS
        payload = json.loads(_serialize(matches))
        payload.update(
            {
                "step": "ideology",
                "blocking": True,
                "forced": forced,
                "round": round_no,
                "max_rounds": MAX_IDEOLOGY_ROUNDS,
                "next_action": "manual_review" if forced else "fix_and_recheck",
                "note": (
                    "意识形态是唯一必须清零的审查项"
                    + ("；已达最大轮次，请人工复核后再发布" if forced else "；修完请重新调用本工具")
                ),
            }
        )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    return (
        StructuredTool.from_function(
            review_ideological_text,
            name=TOOL_NAME,
            description=(
                "扫描 text 文本中的意识形态、政治表述、政治用语固定搭配、"
                "行政区划 / 部委简称、法律法规名称等表述规范问题；"
                "返回结构化 matches 清单（含原文片段、建议、规则编号、"
                "类别、严重度、上下文、文件路径、字符偏移、命中长度）。"
                "工具不做评判，不修改原文，只做规则匹配。"
                "判断「是否要改、改成什么」由调用方（模型）自决。"
            ),
        ),
    )


def _serialize(matches: tuple[IdeologyMatch, ...]) -> str:
    payload: dict[str, object] = {
        "matches": [
            {
                "rule_id": m.rule_id,
                "category_label": m.category_label,
                "severity": m.severity,
                "original": m.original,
                "suggestion": m.suggestion,
                "context": m.context,
                "path": m.path,
                "offset": m.offset,
                "length": m.length,
            }
            for m in matches
        ],
        "summary": {
            "total": len(matches),
            "by_category": dict(Counter(m.category_label for m in matches)),
            "by_severity": dict(Counter(m.severity for m in matches)),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))