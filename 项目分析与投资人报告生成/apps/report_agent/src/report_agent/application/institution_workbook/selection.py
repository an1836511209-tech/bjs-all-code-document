"""At most one constrained selector call; original report agent is never resumed."""

from __future__ import annotations

import json
import re

from report_agent.application.institution_workbook.context import ContextUnavailable, fingerprint


def material_snippets(context: dict, max_chars: int) -> list[dict]:
    snippets = context.get("snippets", [])
    # Bounded, source-addressable product/business passages. No blind leading-page truncation.
    hints = re.compile(
        r"主营|产品|业务|技术|研发|制造|服务|客户|营收|收入|business|product|technology", re.I
    )
    ranked = sorted(enumerate(snippets), key=lambda p: (not bool(hints.search(p[1]["text"])), p[0]))
    result = []
    size = 0
    for _, snippet in ranked:
        text = snippet["text"]
        if len(text) > max_chars:
            # Split oversize blocks into attributable passages, not an arbitrary prefix.
            passages = re.split(r"(?<=[。；\n])", text)
            relevant = [s for s in passages if hints.search(s)]
            text = "".join(relevant)
        if not text or len(text) > max_chars - size:
            continue
        result.append({**snippet, "text": text})
        size += len(text)
    if not result or not any(hints.search(s["text"]) for s in result):
        raise ContextUnavailable("缺少可用于精选标签的主营业务原文，请手动选标签。")
    return result


async def select_tags(context, settings, model_call, explicit=None):
    candidates = context["candidate_tags"]
    if explicit is not None:
        if (
            not explicit
            or len(explicit) > settings.max_selected_tags
            or len(set(explicit)) != len(explicit)
            or not set(explicit) <= set(candidates)
        ):
            raise ContextUnavailable("所选标签必须来自当前候选集合，且不超过精选上限。")
        return {
            "tags": explicit,
            "strategy": "user",
            "evidence": [],
            "fingerprint": fingerprint([context["context_fingerprint"], explicit]),
        }
    if context.get("report_tags"):
        tags = context["report_tags"]
        if len(tags) > 10:
            raise ContextUnavailable("报告使用的标签超过附件上限（10 个），请手动选择后重试附件。")
        return {
            "tags": tags,
            "strategy": "report",
            "evidence": [],
            "fingerprint": fingerprint([context["context_fingerprint"], tags]),
        }
    if not candidates or len(candidates) > settings.max_candidate_tags:
        raise ContextUnavailable("候选标签为空或超过上限，请缩小候选范围后重试附件。")
    if len(candidates) <= settings.max_selected_tags and not context["low_trust"]:
        return {
            "tags": candidates,
            "strategy": "reuse",
            "evidence": [],
            "fingerprint": fingerprint([context["context_fingerprint"], candidates]),
        }
    snippets = material_snippets(context, settings.max_material_chars)
    request = {
        "company_name": context["company_name"],
        "candidates": [{"id": i, "tag": t} for i, t in enumerate(candidates)],
        "materials": snippets,
        "user_notes": context.get("user_notes", []),
        "max_selected_tags": settings.max_selected_tags,
    }
    if model_call is None:
        raise ContextUnavailable("请手动选择标签后重试附件。")
    response = await model_call(request)
    if isinstance(response, str):
        text = response.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, re.S | re.I)
        try:
            response = json.loads(fenced.group(1) if fenced else text)
        except (ValueError, TypeError):
            raise ContextUnavailable(
                "标签精选返回的 JSON 格式无效，请手动选择后重试附件。"
            ) from None
    selected = response.get("selected", []) if isinstance(response, dict) else []
    if not isinstance(selected, list) or not 1 <= len(selected) <= settings.max_selected_tags:
        raise ContextUnavailable("标签精选结果无效，请手动选择后重试附件。")
    evidence = []
    refs = {s["ref"]: s["text"] for s in snippets}
    ids = []
    for item in selected:
        if not isinstance(item, dict):
            raise ContextUnavailable("标签精选结果无效")
        index, ref, quote = item.get("id"), item.get("ref"), item.get("quote")
        if (
            type(index) is not int
            or not 0 <= index < len(candidates)
            or index in ids
            or not isinstance(ref, str)
            or ref not in refs
            or not isinstance(quote, str)
            or len(quote.strip()) < 4
            or quote not in refs[ref]
            or not isinstance(item.get("reason"), str)
            or not item["reason"].strip()
        ):
            raise ContextUnavailable("标签精选缺少有效原文依据，请手动选择后重试附件。")
        ids.append(index)
        evidence.append(
            {
                "tag": candidates[index],
                "ref": ref,
                "quote": quote[:500],
                "reason": item["reason"][:500],
            }
        )
    tags = [candidates[i] for i in ids]
    return {
        "tags": tags,
        "strategy": "model",
        "evidence": evidence,
        "fingerprint": fingerprint([context["context_fingerprint"], tags]),
    }
