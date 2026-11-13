from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from data_mcp.shared.http.errors import public_message_for_exception

FetchApiFn = Callable[..., list[str]]
InvokeAgentFn = Callable[..., list[str]]
SleepFn = Callable[[float], None]
ConfiguredFn = Callable[[dict[str, Any]], bool]

logger = logging.getLogger(__name__)


def _ensure_profile(project_profile: str | dict[str, Any] | None) -> str | dict[str, Any]:
    if project_profile is None:
        raise ValueError("project_profile 不能为空")
    if isinstance(project_profile, dict):
        if not project_profile:
            raise ValueError("project_profile 不能为空")
        return project_profile
    text = str(project_profile).strip()
    if not text:
        raise ValueError("project_profile 不能为空")
    return text


def _profile_kind(project_profile: str | dict[str, Any]) -> str:
    return "object" if isinstance(project_profile, dict) else "string"


def _dedupe(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        item = str(tag or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _filter_allowed(
    tags: list[str],
    allowed: frozenset[str] | set[str] | None,
    warnings: list[str],
) -> list[str]:
    if allowed is None:
        return _dedupe(tags)
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        item = str(tag or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        if item in allowed:
            kept.append(item)
        else:
            dropped.append(item)
    if dropped:
        preview = "、".join(dropped[:5])
        more = f" 等{len(dropped)}个" if len(dropped) > 5 else ""
        warnings.append(f"丢弃框架外标签: {preview}{more}")
    return kept


def query_track_labels(
    company_name: str,
    project_profile: str | dict[str, Any],
    env: str | None = None,
    *,
    fetch_api: FetchApiFn | None = None,
    invoke_agent: InvokeAgentFn | None = None,
    sleep_fn: SleepFn | None = None,
    is_api_configured: ConfiguredFn | None = None,
    config: dict[str, Any] | None = None,
    allowed_tags: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """查询企业赛道标签：API 平台优先，失败或空标签重试后 HiAgent 兜底。"""
    company = str(company_name or "").strip().replace("(", "（").replace(")", "）")
    if not company:
        raise ValueError("company_name 不能为空")
    profile = _ensure_profile(project_profile)

    from data_mcp.shared.settings import load_track_labels_config, resolve_env

    cfg = config or load_track_labels_config(env)
    selected_env = str(cfg.get("env") or resolve_env(env))
    retry_value = cfg.get("retry")
    retry_cfg = retry_value if isinstance(retry_value, dict) else {}
    # 首次失败或空列表后只再调用一次，间隔 20 秒；第二次仍为空则走兜底。
    max_attempts = int(retry_cfg.get("max_attempts") or 2)
    interval_seconds = float(retry_cfg.get("interval_seconds") or 20)
    fallback_value = cfg.get("fallback")
    fallback_cfg = fallback_value if isinstance(fallback_value, dict) else {}
    taxonomy_path = str(fallback_cfg.get("taxonomy_path") or "").strip()
    if not taxonomy_path:
        raise ValueError("track_labels.fallback.taxonomy_path 不能为空")

    if fetch_api is None:
        from data_mcp.features.track_labels.lms_client import query_lms_track_labels as fetch_api
    if invoke_agent is None:
        from data_mcp.features.track_labels.hiagent_client import (
            invoke_track_label_agent as invoke_agent,
        )
    if sleep_fn is None:
        sleep_fn = time.sleep
    if is_api_configured is None:
        from data_mcp.features.track_labels.lms_client import (
            is_lms_track_labels_configured as is_api_configured,
        )

    assert fetch_api is not None
    assert invoke_agent is not None
    assert sleep_fn is not None
    assert is_api_configured is not None

    warnings: list[str] = []
    profile_kind = _profile_kind(profile)
    api_attempts = 0

    configured = bool(is_api_configured(cfg))
    if not configured:
        warnings.append("API平台赛道标签未配置，跳过调用并直接兜底")
    else:
        last_error = ""
        for attempt in range(1, max(1, max_attempts) + 1):
            api_attempts = attempt
            try:
                tags = _dedupe(fetch_api(company, env, config=cfg))
                if tags:
                    return {
                        "tags": tags,
                        "source": "api",
                        "warnings": warnings,
                        "meta": {
                            "company_name": company,
                            "api_attempts": api_attempts,
                            "fallback_used": False,
                            "project_profile_kind": profile_kind,
                            "env": selected_env,
                        },
                    }
                last_error = "赛道标签为空"
                warnings.append(f"API平台第 {attempt} 次返回空标签")
            except Exception as exc:  # noqa: BLE001 - soft fail into retry/fallback
                last_error = public_message_for_exception(exc)
                logger.warning("API platform track label attempt %d failed: %s", attempt, last_error)
                warnings.append(f"API平台第 {attempt} 次未返回可用数据")

            if attempt < max_attempts:
                sleep_fn(interval_seconds)

        if last_error and not any("失败" in w or "空标签" in w for w in warnings):
            warnings.append(f"API平台最终失败: {last_error}")

    # --- fallback: HiAgent only（不再做本地标签召回）---
    selected: list[str] = []
    try:
        selected = invoke_agent(
            company,
            profile,
            env,
            config=cfg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("track label fallback failed: %s", public_message_for_exception(exc))
        warnings.append("赛道标签兜底未返回可用数据")
        selected = []

    allow = allowed_tags
    if allow is None:
        try:
            from data_mcp.features.track_labels.taxonomy import load_level4_tags

            allow = frozenset(load_level4_tags(taxonomy_path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("track label taxonomy load failed: %s", public_message_for_exception(exc))
            warnings.append("标签框架暂不可用，本次结果未执行框架校验")
            allow = None

    tags = _filter_allowed(selected, allow, warnings)

    # 第三级兜底：HiAgent 也没给出标签时，用本地 taxonomy 做一次轻量召回
    # （公司名 + 画像 → 四级标签）。这是「原有本地生成逻辑」，只在前两级都空时
    # 才启用，避免覆盖更好的上游结果。
    local_used = False
    if not tags:
        try:
            from data_mcp.features.track_labels.taxonomy import (
                recall_track_label_candidates,
            )

            candidates = recall_track_label_candidates(
                company,
                profile,
                top_k=int(cfg.get("local_recall_top_k") or 5),
                taxonomy_path=taxonomy_path,
                env=env,
            )
            recalled = _filter_allowed(candidates, allow, warnings)
            if recalled:
                tags = recalled
                local_used = True
                warnings.append(
                    f"上游未返回标签，已用本地标签库召回 {len(tags)} 个候选（需人工复核）"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "track label local recall failed: %s", public_message_for_exception(exc)
            )
            warnings.append("本地标签召回失败")

    if not tags:
        warnings.append("兜底未得到有效赛道标签")

    return {
        "tags": tags,
        "source": "local_recall" if local_used else "fallback",
        "warnings": warnings,
        "meta": {
            "company_name": company,
            "api_attempts": api_attempts,
            "fallback_used": True,
            "local_recall_used": local_used,
            "project_profile_kind": profile_kind,
            "env": selected_env,
        },
    }
