"""Normalize inbound user text before the Agent run starts."""

from __future__ import annotations

import re

# Low-code platforms often inject a summarize placeholder when the user uploads
# a file without typing text. Treat those as the default report request.
DEFAULT_REPORT_REQUEST = "请读取已上传材料，并生成投资人匹配报告。"
_PLATFORM_PLACEHOLDER_MESSAGES = frozenset(
    {
        "总结文档内容",
        "请总结文档内容",
        "总结一下文档内容",
        "总结文档",
        "请总结文档",
        "summarize the document",
        "summarize document",
        "summarize this document",
    }
)
_SUMMARIZE_ONLY = re.compile(
    r"^(请)?(帮我)?(对)?(该|此|这[个份])?(文档|文件|材料|附件)?(内容)?(进行|做)?(一下)?"
    r"(总结|摘要|概括|概述)(一下|下)?(文档|文件|材料|附件)?(内容)?[。.!！？?]*$",
    re.IGNORECASE,
)


def normalize_user_request(message: str, *, has_uploads: bool) -> str:
    """Map empty / platform-placeholder text to the canonical report request.

    When files are present, short summarize-only prompts from low-code UIs are
    rewritten so the agent generates an investment-matching report instead of
    a document summary. Explicit user instructions (anything beyond a bare
    summarize phrase) are left unchanged.
    """
    cleaned = message.strip()
    if not cleaned:
        return DEFAULT_REPORT_REQUEST
    if not has_uploads:
        return cleaned
    compact = cleaned.rstrip("。.!?！？").strip().casefold()
    if compact in _PLATFORM_PLACEHOLDER_MESSAGES or _SUMMARIZE_ONLY.fullmatch(cleaned):
        return DEFAULT_REPORT_REQUEST
    return cleaned
