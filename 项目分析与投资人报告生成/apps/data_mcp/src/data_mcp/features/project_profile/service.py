from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import unquote, urlparse

from data_mcp.features.project_profile.zhipu_client import resolve_zhipu_info_for_portrait
from data_mcp.shared.http.errors import raise_from_http_error, raise_invalid_json_response
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.integrations.hiagent import (
    extract_choice_content,
    strip_markdown_fence,
)
from data_mcp.shared.integrations.hiagent import (
    parse_json_payload as _parse_json_payload,
)
from data_mcp.shared.integrations.qichacha_client import resolve_qichacha_info_for_portrait
from data_mcp.shared.settings import load_http_retry_config, load_project_profile_config

PROFILE_FIELDS: tuple[str, ...] = (
    "上市公司名称",
    "证券简称",
    "证券代码",
    "所在行业",
    "细分赛道",
    "自身在产业链上下游位置",
    "目标客户",
    "主要产品和服务",
    "盈利模式",
    "核心资源与能力",
    "资源依赖路径",
)

VALID_FIELD_STATUSES = frozenset({"supported", "inferred", "conflicted", "missing"})
VALID_EVIDENCE_SOURCE_TYPES = frozenset(
    {"project_document", "zhipu", "qichacha", "userChatInput"}
)

logger = logging.getLogger(__name__)

def project_profile_fields(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in PROFILE_FIELDS:
        value = raw.get(key)
        if value is None:
            out[key] = ""
        else:
            out[key] = str(value)
    return out


def _default_field_detail() -> dict[str, Any]:
    return {
        "status": "missing",
        "confidence": 0,
        "inference_basis": "",
        "evidence": [],
    }


def _normalize_evidence(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "").strip()
        if source_type not in VALID_EVIDENCE_SOURCE_TYPES:
            continue
        out.append(
            {
                "source_type": source_type,
                "source_name": str(item.get("source_name") or "").strip(),
                "source_url": str(item.get("source_url") or "").strip(),
                "quote": str(item.get("quote") or "").strip(),
            }
        )
    return out


def normalize_field_details(raw: Any) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for field in PROFILE_FIELDS:
        detail = source.get(field)
        if not isinstance(detail, dict):
            out[field] = _default_field_detail()
            continue

        status = str(detail.get("status") or "missing").strip()
        if status not in VALID_FIELD_STATUSES:
            status = "missing"

        confidence_raw = detail.get("confidence", 0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        out[field] = {
            "status": status,
            "confidence": confidence,
            "inference_basis": str(detail.get("inference_basis") or "").strip(),
            "evidence": _normalize_evidence(detail.get("evidence")),
        }
    return out


def normalize_conflicts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sources_raw = item.get("sources")
        sources: list[dict[str, str]] = []
        if isinstance(sources_raw, list):
            for source in sources_raw:
                if not isinstance(source, dict):
                    continue
                source_type = str(source.get("source_type") or "").strip()
                if source_type not in VALID_EVIDENCE_SOURCE_TYPES:
                    continue
                sources.append(
                    {
                        "source_type": source_type,
                        "source_name": str(source.get("source_name") or "").strip(),
                        "value": str(source.get("value") or "").strip(),
                        "quote": str(source.get("quote") or "").strip(),
                    }
                )
        out.append(
            {
                "field": str(item.get("field") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "sources": sources,
            }
        )
    return out


def _normalize_warnings(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def merge_warnings(*groups: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out


def _parse_info_payload(raw: str) -> Any:
    """将 state 用的 JSON 字符串还原为对象；空串返回 null。"""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def material_name_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    path = urlparse(raw).path
    name = unquote(path.rsplit("/", 1)[-1]).strip()
    return name


def _try_load_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
    return None


def parse_profile_content(content: str) -> dict[str, Any]:
    """将 choice.content 清洗为 profile / field_details / conflicts；失败返回 error 结构。"""
    if not isinstance(content, str):
        return {
            "profile": None,
            "error": f"choice.content 类型无效: {type(content).__name__}",
            "raw_content": "" if content is None else str(content)[:2000],
        }

    cleaned = strip_markdown_fence(content)
    parsed = _try_load_json_object(cleaned)
    if parsed is None:
        return {
            "profile": None,
            "error": "无法将 choice.content 解析为画像 JSON",
            "raw_content": content[:2000],
        }

    if isinstance(parsed.get("profile"), dict):
        profile_raw = parsed["profile"]
        agent_warnings = _normalize_warnings(parsed.get("warnings"))
        return {
            "profile": project_profile_fields(profile_raw),
            "field_details": normalize_field_details(parsed.get("field_details")),
            "conflicts": normalize_conflicts(parsed.get("conflicts")),
            "agent_warnings": agent_warnings,
        }

    return {
        "profile": project_profile_fields(parsed),
        "field_details": normalize_field_details(None),
        "conflicts": [],
        "agent_warnings": [],
    }


def extract_project_profile(
    company_name: str,
    file_info: str = "",
    material_url: str = "",
    user_chat_input: str = "",
    search_keywords: str | list[str] | None = None,
    env: str | None = None,
) -> dict[str, Any]:
    """调用项目画像智能体，返回清洗后的画像与溯源结构（或解析失败结构）。"""
    from data_mcp.features.project_profile.material_loader import download_markdown_from_url

    name = "" if company_name is None else str(company_name).strip()
    if not name:
        raise ValueError("company_name 不能为空")

    url = "" if material_url is None else str(material_url).strip()
    text = "" if file_info is None else str(file_info).strip()
    if url:
        text = download_markdown_from_url(url)
    if not text:
        raise ValueError("material_url 与 file_info 至少提供一个")

    # 企查查与智谱互不依赖，并行拉取后再调 HiAgent，缩短画像前置耗时。
    with ThreadPoolExecutor(max_workers=2) as pool:
        qichacha_future = pool.submit(resolve_qichacha_info_for_portrait, name, env)
        zhipu_future = pool.submit(
            resolve_zhipu_info_for_portrait,
            name,
            env,
            search_keywords=search_keywords,
        )
        qichacha_info, qichacha_warnings = qichacha_future.result()
        zhipu_info, zhipu_warnings = zhipu_future.result()
    if qichacha_warnings:
        logger.warning("project profile qichacha degraded: %s", "; ".join(qichacha_warnings))
    if zhipu_warnings:
        logger.warning("project profile zhipu degraded: %s", "; ".join(zhipu_warnings))
    warnings = merge_warnings(
        ["企查查数据暂不可用，画像可能不完整"] if qichacha_warnings else [],
        ["智谱公开信息暂不可用，画像可能不完整"] if zhipu_warnings else [],
    )

    state: dict[str, str] = {
        "file_info": text,
        "qichacha_info": qichacha_info,
        "zhipu_info": zhipu_info,
    }
    material_name = material_name_from_url(url)
    if material_name:
        state["material_source_name"] = material_name

    cfg = load_project_profile_config(env)
    endpoint = f"{cfg['host']}{cfg['path']}"
    payload = {
        "agentId": cfg["agent_id"],
        "chatId": cfg["chat_id"],
        "userChatInput": "" if user_chat_input is None else str(user_chat_input),
        "state": state,
        "buttonKey": cfg["button_key"],
        "debug": cfg["debug"],
    }
    headers = {
        "token": cfg["token"],
        "Content-Type": "application/json",
    }

    retry_cfg = load_http_retry_config()
    try:
        response = http_request(
            "POST",
            endpoint,
            headers=headers,
            json=payload,
            timeout=cfg["timeout_seconds"],
            service_name="project_profile",
            max_retries=retry_cfg["max_retries"],
            backoff_base_seconds=retry_cfg["backoff_base_seconds"],
            backoff_max_seconds=retry_cfg["backoff_max_seconds"],
        )
    except Exception as exc:
        raise_from_http_error("项目画像智能体", exc)

    try:
        raw = response.json()
    except json.JSONDecodeError:
        raw = response.text
    try:
        data = _parse_json_payload(raw)
    except (json.JSONDecodeError, ValueError):
        raise_invalid_json_response(
            "项目画像智能体",
            status_code=response.status_code,
            body=response.text if isinstance(response.text, str) else None,
        )

    qichacha_payload = _parse_info_payload(qichacha_info)
    zhipu_payload = _parse_info_payload(zhipu_info)

    content = extract_choice_content(data)
    if content is None:
        return {
            "profile": None,
            "error": "响应中缺少 choice.content",
            "raw_content": json.dumps(data, ensure_ascii=False)[:2000],
            "warnings": warnings,
            "qichacha_info": qichacha_payload,
            "zhipu_info": zhipu_payload,
        }

    parsed = parse_profile_content(content)
    agent_warnings = parsed.pop("agent_warnings", [])
    parsed["warnings"] = merge_warnings(warnings, agent_warnings)
    parsed["qichacha_info"] = qichacha_payload
    parsed["zhipu_info"] = zhipu_payload
    if parsed.get("profile") is None:
        if not parsed["warnings"]:
            parsed["warnings"] = []
        return parsed

    if "warnings" not in parsed or parsed["warnings"] is None:
        parsed["warnings"] = []
    return parsed
