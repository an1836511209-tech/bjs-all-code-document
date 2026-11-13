"""Durable task interaction state and question presentation shared by all clients."""
from __future__ import annotations

import json
import threading
from typing import Any

from report_agent.domain.artifacts import PublishedArtifact
from report_agent.runtime.workspace import TaskWorkspace

PATH = "/workspace/state/interaction.json"

BUSINESS_TYPE_ALIASES = {
    "产权": "产权", "股权转让": "产权", "股权项目": "产权", "产权转让": "产权",
    "股权转让（产权）": "产权", "property": "产权",
    "增资": "增资", "增资扩股": "增资", "增资项目": "增资", "capital": "增资",
}


def business_type_question(context: str = "") -> dict[str, Any]:
    return {
        "status": "needs_user_input", "gate": "one_pager_business_type", "kind": "business_type",
        "question": "当前材料无法确定业务类型，请选择股权转让或增资扩股。",
        "context": context or "业务类型决定一页纸使用的模板。请选择一项，也可以补充说明；此步骤不能跳过。",
        "options": [
            {"value": "产权", "label": "股权转让（产权）"},
            {"value": "增资", "label": "增资扩股"},
        ],
        "allow_free_text": True,
    }


def business_type_answer(text: str, choice_value: str = "") -> tuple[str, dict[str, Any]]:
    raw = text.strip()
    value = BUSINESS_TYPE_ALIASES.get((choice_value or raw).strip().lower())
    if not value:
        raise ValueError("请明确选择股权转让（产权）或增资扩股，不能跳过业务类型判定")
    supplement = f"\n补充说明：{raw}" if choice_value and raw else ""
    return (f"用户已明确确认业务类型：{value}。后续沿用此类型，不要重复询问或自行改成另一种类型。{supplement}",
            {"value": value, "source": "user"})


def read_interaction(workspace: TaskWorkspace) -> dict[str, Any]:
    path = workspace.resolve(PATH)
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    pending = value.get("pending_question")
    if isinstance(pending, dict):
        run_id = str(pending.get("run_id") or value.get("run_id") or "")
        repaired = question_payload(str(pending.get("question") or ""), pending, run_id)
        # Keep the outstanding identity so already-open clients can still answer.
        for key in ("question_id", "approval_id"):
            if pending.get(key):
                repaired[key] = pending[key]
        value["pending_question"] = {**pending, **repaired}
    return value


#: ``update_interaction`` is a read-modify-write on one JSON file, called from
#: the event loop, from worker threads (sync tools) and from the API handlers.
#: Two of them interleaving silently drop one write — most visibly an answered
#: question coming back, or a published artifact disappearing from the list.
#: One process-wide lock is enough: writes are tiny and rare.
_INTERACTION_LOCK = threading.RLock()


def update_interaction(workspace: TaskWorkspace, **changes: Any) -> dict[str, Any]:
    with _INTERACTION_LOCK:
        value = {**read_interaction(workspace), **changes}
        workspace.write_text(PATH, json.dumps(value, ensure_ascii=False, indent=2))
        return value


def record_published_artifact(workspace: TaskWorkspace, artifact: PublishedArtifact) -> None:
    """Make the artifact discoverable as soon as its object is published."""
    with _INTERACTION_LOCK:
        artifacts = {item["artifact_id"]: item for item in read_interaction(workspace).get("artifacts", [])}
        artifacts[artifact.artifact_id] = artifact.model_dump(mode="json")
        update_interaction(workspace, artifacts=list(artifacts.values()))


def registry_name_question(company_name: str = "", context: str = "") -> dict[str, Any]:
    return {
        "status": "needs_user_input", "gate": "company_registry", "kind": "registry_name",
        "question": "当前公司名称无法获取企查查数据，请提供精确名称。",
        "queried_company_name": company_name,
        "context": context or "工商查询是可选补充。可以填写企业登记全称重试，也可以跳过，按已有材料继续。",
        "options": [
            {"value": "correct_name", "label": "填写精确名称"},
            {"value": "skip", "label": "跳过此步骤", "description": "不再查询企查查，按已有材料继续"},
        ],
        "allow_free_text": True,
    }


def registry_answer(text: str, choice_value: str = "") -> tuple[str, dict[str, Any]]:
    raw = text.strip()
    if choice_value == "skip" or (not choice_value and raw in {"skip", "跳过", "跳过此步骤"}):
        return ("用户选择跳过企查查工商查询。按已有材料继续后续流程；不要重复查询或要求补充名称。"
                + (f"\n补充说明：{raw}" if raw and raw not in {"skip", "跳过", "跳过此步骤"} else ""),
                {"status": "skipped"})
    if choice_value not in {"", "correct_name"}:
        raise ValueError("请选择填写精确名称或跳过此步骤")
    if not raw or raw == "correct_name":
        raise ValueError("请输入企业登记的精确名称，或选择跳过此步骤")
    return (f"用户补充的精确公司名称：{raw}。请使用此名称重试企查查工商查询；本次查询仍可跳过，不得将缺失工商数据作为报告失败原因。",
            {"status": "retry", "company_name": raw})


def risk_disclosure_question(risk_items: list[str], *, question: str = "", context: str = "") -> dict[str, Any]:
    return {
        "status": "needs_user_input", "gate": "one_pager_risk", "kind": "risk_disclosure",
        "question": question or ("材料中识别到非优质项目信息（" + "；".join(risk_items)
                                 + "），要放进报告的风险提示吗？"),
        "context": context, "risk_items": risk_items,
        "options": [{"value": "show", "label": "展示"}, {"value": "hide", "label": "不展示"}],
        "allow_free_text": True,
    }


def risk_disclosure_answer(question: dict[str, Any], text: str, choice_value: str) -> tuple[str, dict[str, Any]]:
    choice = {"show": "show", "展示": "show", "hide": "hide", "不展示": "hide"}.get(choice_value or text.strip())
    if not choice:
        raise ValueError("请选择展示或不展示，可同时补充说明。")
    supplement = f"补充说明：{text.strip()}" if choice_value and text.strip() else ""
    instruction = ("把已确认的风险事实填入 risk_facts，由渲染层放到第二页末尾的小字里；"
                   "介绍的第 3 个标题照常写项目内容，不要用「风险提示」。" if choice == "show"
                   else "不在报告中展示这些非优质项目信息，不生成“风险提示”段落，也不要在其他段落变相加入这些内容。")
    return (f"用户选择{('展示' if choice == 'show' else '不展示')}非优质项目信息。{instruction}{supplement}",
            {"value": choice, "risk_items": question.get("risk_items", []), "supplement": text.strip()})


def cbex_listing_question() -> dict[str, Any]:
    return {
        "status": "needs_user_input", "gate": "cbex_listing", "kind": "cbex_listing",
        "question": "本项目是否为北交互联正在披露的项目？",
        "options": [{"value": "yes", "label": "是，正在北交互联披露"},
                    {"value": "no", "label": "不是"},
                    {"value": "unknown", "label": "不确定，按材料继续"}],
        "allow_free_text": True,
    }


def cbex_project_question(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "needs_user_input", "gate": "cbex_project", "kind": "cbex_project",
        "question": "找到多个候选或搜索尚未完整，请选择需要获取财务的北交互联项目。",
        "options": [{"value": str(i), "label": item["project_name"],
                     "project_type": item.get("project_type", ""),
                     "disclosure_end_date": item.get("disclosure_end_date", ""),
                     "detail_url": item["detail_url"]} for i, item in enumerate(candidates)],
        "allow_free_text": False,
    }


def cbex_answer(question: dict[str, Any], text: str, choice_value: str) -> tuple[str, dict[str, Any]]:
    options = question.get("options", [])
    option = next((o for o in options if o["value"] == choice_value), None)
    if not option:
        raise ValueError("请选择当前卡片中的项目或披露状态")
    if question.get("gate") == "cbex_project":
        lookup = {"status": "selected", "project_name": option["label"],
                  "detail_url": option["detail_url"]}
        return (f"用户选定的北交互联项目：{option['label']}；项目类型：{option.get('project_type') or '未披露'}；"
                f"信息披露截止日期：{option.get('disclosure_end_date') or '未披露'}。请获取该项目披露财务。", lookup)
    if choice_value != "yes":
        return ("用户未确认北交互联披露，跳过挂牌财务查询，按已有材料继续。",
                {"status": "skipped"})
    name = text.strip()
    if not name or name == "yes":
        raise ValueError("请输入北交互联正在挂牌的项目全称")
    return (f"用户确认正在北交互联披露，输入的挂牌项目全称：{name}。请按该全称获取披露财务。",
            {"status": "confirmed", "project_name": name})


def question_payload(text: str, ask: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    """Recognize legacy prose questions too; never present an arbitrary question as approval."""
    ask = ask or {}
    question = str(ask.get("question") or text or "请补充信息后继续。")
    context = str(ask.get("context") or "")
    if ask.get("gate") == "one_pager_risk" or (
        "非优质" in question and any(word in question for word in ("展示", "放进", "风险提示", "纳入"))
    ):
        return {**risk_disclosure_question(ask.get("risk_items") or [], question=question, context=context),
                "approval_id": f"approval_{run_id}", "question_id": f"approval_{run_id}", "run_id": run_id}
    if ask.get("gate") == "cbex_project":
        return {**ask, "approval_id": f"approval_{run_id}",
                "question_id": f"approval_{run_id}", "run_id": run_id}
    if ask.get("gate") == "cbex_listing" or (
        "北交互联" in question and any(w in question for w in ("是否", "是不是", "挂牌", "披露"))
    ):
        return {**cbex_listing_question(), "context": context, "approval_id": f"approval_{run_id}",
                "question_id": f"approval_{run_id}", "run_id": run_id}
    if ask.get("gate") == "one_pager_business_type":
        return {**business_type_question(context), "approval_id": f"approval_{run_id}",
                "question_id": f"approval_{run_id}", "run_id": run_id}
    if ask.get("gate") == "company_registry" or (
        any(word in question for word in ("企查查", "工商"))
        and any(word in question for word in ("精确名称", "公司全称", "企业全称", "查不到", "没查到"))
    ):
        payload = registry_name_question(str(ask.get("queried_company_name") or ""), str(ask.get("context") or ""))
        return {**payload, "approval_id": f"approval_{run_id}", "question_id": f"approval_{run_id}", "run_id": run_id}
    options = [o for o in (ask.get("options") or []) if isinstance(o, dict) and o.get("value") and o.get("label")]
    kind = "choice" if options else "text"
    # Older model replies often omit ask_user or provide no structured options.
    business_question = any(word in question for word in ("业务类型", "交易类型", "交易方式")) or (
        "增资" in question + context and any(word in question + context for word in ("产权", "股权", "转让"))
        and any(word in question for word in ("类型", "属于", "还是", "选择股权", "选择增资"))
    )
    if "北交互联" not in question and business_question:
        return {**business_type_question(context), "approval_id": f"approval_{run_id}",
                "question_id": f"approval_{run_id}", "run_id": run_id}
    elif not options and any(w in question for w in ("请上传", "请先上传", "上传材料", "重新上传")):
        kind = "upload_prompt"
    return {
        "approval_id": f"approval_{run_id}", "question_id": f"approval_{run_id}",
        "run_id": run_id, "kind": kind, "question": question,
        "context": str(ask.get("context") or ""), "options": options,
        # A question must expose at least one usable answer channel.
        "allow_free_text": bool(ask.get("allow_free_text", True)) or not options,
    }


def answer_text(question: dict[str, Any], text: str, choice_value: str = "") -> str:
    if question.get("gate") == "one_pager_risk":
        return risk_disclosure_answer(question, text, choice_value)[0]
    if question.get("gate") in {"cbex_listing", "cbex_project"}:
        return cbex_answer(question, text, choice_value)[0]
    if question.get("gate") == "one_pager_business_type":
        return business_type_answer(text, choice_value)[0]
    if question.get("gate") == "company_registry":
        return registry_answer(text, choice_value)[0]
    raw = text.strip()
    if choice_value and not any(o["value"] == choice_value for o in question.get("options", [])):
        raise ValueError("所选答案不属于当前问题")
    for option in question.get("options", []):
        if choice_value == option["value"] or raw == option["value"]:
            supplement = f"\n补充说明：{raw}" if choice_value and raw and raw != choice_value else ""
            return f"针对问题「{question['question']}」，我的选择：{option['label']}（{option['value']}）。{supplement}"
    if not raw:
        return "已补充上传材料，请结合当前对话继续。"
    if not question.get("allow_free_text", True):
        raise ValueError("请从当前问题的选项中选择")
    return f"针对问题「{question['question']}」，我的补充：{raw}"
