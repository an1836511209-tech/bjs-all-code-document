"""``ask_user`` — 让模型在流程中向用户提问并给出可选项。

流程图里的三个闸门（补充公司名称 / 材料支撑度 / 是否北交互联挂牌）都需要
用户回答。这个工具把"提问"变成结构化输出，前端据此渲染问题卡片：

    {
      "status": "needs_user_input",
      "question": "本项目是否为北交互联正在挂牌的项目？",
      "context": "判断依据：材料未提及挂牌状态",
      "options": [
        {"value": "yes", "label": "是，在北交互联挂牌", "description": "将查询挂牌财务数据"},
        {"value": "no",  "label": "不是，普通股权转让", "description": "跳过财务数据查询"}
      ],
      "allow_free_text": true
    }

用户回答后，回答内容作为**新消息**回到对话，模型带着这个答案继续执行。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from report_agent.application.interactions import question_payload, read_interaction
from report_agent.runtime.workspace import TaskWorkspace


class AskOption(BaseModel):
    value: str = Field(min_length=1, description="选项标识，回答时原样回传")
    label: str = Field(min_length=1, description="按钮上显示的文案，12 字以内")
    description: str = Field(default="", description="一行说明，告诉用户选了这个会怎样")


class AskUserArgs(BaseModel):
    question: str = Field(min_length=1, description="要问用户的问题，一句话说清")
    context: str = Field(default="", description="为什么问、判断依据、影响是什么")
    options: list[AskOption] = Field(
        default_factory=list,
        description="2-5 个可选项。不给选项时退化为纯文本提问，用户自由输入",
    )
    allow_free_text: bool = Field(
        default=True,
        description="是否允许用户不用选项、直接输入文本回答",
    )


def build_ask_user_tools(
    *, resumable: bool = False, workspace: TaskWorkspace | None = None
) -> tuple[StructuredTool, ...]:
    def ask_user(
        question: str,
        context: str = "",
        options: list[dict[str, Any]] | None = None,
        allow_free_text: bool = True,
    ) -> str:
        """Ask the user a question and stop the current turn until they answer."""
        cleaned: list[dict[str, str]] = []
        for item in options or []:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            label = str(item.get("label") or "").strip()
            if not value or not label:
                continue
            cleaned.append(
                {
                    "value": value,
                    "label": label,
                    "description": str(item.get("description") or "").strip(),
                }
            )
        payload = {
                "status": "needs_user_input",
                "question": str(question).strip(),
                "context": str(context or "").strip(),
                "options": cleaned,
                "allow_free_text": bool(allow_free_text),
                "usage": (
                    "本轮到此暂停。用户的选择或输入会作为新消息回到对话，"
                    "你带着这个答案继续执行剩余步骤；不要重复提问。"
                ),
            }
        normalized = question_payload(question, payload, "")
        if workspace is not None and normalized.get("gate") == "cbex_listing":
            lookup = read_interaction(workspace).get("cbex_lookup") or {}
            if lookup.get("status") == "skipped" or (
                lookup.get("status") in {"confirmed", "selected"} and lookup.get("project_name")
            ):
                return json.dumps({
                    "status": "already_answered",
                    "gate": "cbex_listing",
                    "answer": lookup,
                    "usage": ("用户已选择跳过挂牌财务查询，按已有材料继续。"
                              if lookup["status"] == "skipped" else
                              "用户已确认披露项目，使用 answer 中的项目名称和已选 detail_url 查询财务。")
                             + "不要重复询问披露状态。",
                }, ensure_ascii=False)
        for key in ("question_id", "approval_id", "run_id"):
            normalized.pop(key, None)
        return json.dumps(
            {**payload, **normalized},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return (
        StructuredTool.from_function(
            func=ask_user,
            name="ask_user",
            description=(
                "向用户提一个必须回答才能继续的问题，可带 2-5 个选项。"
                "用于：企查查查不到公司要用户补全称、材料支撑度不足问是否用公开搜索补充、"
                "确认项目是否为北交互联挂牌项目。调用后本轮暂停，用户回答作为新消息继续。"
            ),
            args_schema=AskUserArgs,
            # Workspace-aware calls may return an existing answer. The question
            # boundary pauses only genuine questions and lets those answers run on.
            return_direct=not resumable and workspace is None,
        ),
    )
