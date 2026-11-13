from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FIELD_KEYS = (
    "industry_chain_position",
    "products_services",
    "track_tags",
    "target_customers",
    "profit_model",
)

DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
    "industry_chain_position": 0.375,
    "products_services": 0.375,
    "track_tags": 0.12,
    "target_customers": 0.08,
    "profit_model": 0.05,
}


def validate_field_weights(
    weights: Mapping[str, Any],
    *,
    require_sum_approx: float = 1.0,
    sum_tolerance: float = 0.001,
    require_chain_plus_products_min: float | None = 0.75,
) -> dict[str, float]:
    """校验并规范化字段权重；不满足约束则抛 ValueError。"""
    if not isinstance(weights, Mapping):
        raise ValueError("field_weights 必须是对象")

    unknown = set(weights) - set(FIELD_KEYS)
    if unknown:
        raise ValueError(f"field_weights 含未知键: {sorted(unknown)}；允许: {list(FIELD_KEYS)}")

    missing = [k for k in FIELD_KEYS if k not in weights]
    if missing:
        raise ValueError(f"field_weights 缺少键: {missing}")

    parsed: dict[str, float] = {}
    for key in FIELD_KEYS:
        try:
            value = float(weights[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"field_weights.{key} 必须是数字") from exc
        if value < 0:
            raise ValueError(f"field_weights.{key} 不能为负: {value}")
        parsed[key] = value

    total = sum(parsed.values())
    if abs(total - float(require_sum_approx)) > float(sum_tolerance):
        raise ValueError(
            f"field_weights 之和应为 {require_sum_approx}±{sum_tolerance}，实际为 {total}"
        )

    if require_chain_plus_products_min is not None:
        chain_sum = parsed["industry_chain_position"] + parsed["products_services"]
        minimum = float(require_chain_plus_products_min)
        if chain_sum + 1e-12 < minimum:
            raise ValueError(
                "industry_chain_position + products_services 必须 ≥ "
                f"{minimum}，实际为 {chain_sum}"
            )

    return parsed


def merge_field_weights(
    base: Mapping[str, float],
    override: Mapping[str, Any] | None,
) -> dict[str, float]:
    merged = dict(base)
    if override:
        for key, value in override.items():
            merged[str(key)] = value
    return merged


def renormalize_weights_for_present(
    weights: Mapping[str, float],
    present_fields: set[str],
) -> dict[str, float]:
    """缺字段时对剩余非空字段权重等比归一。"""
    active = {k: float(weights[k]) for k in FIELD_KEYS if k in present_fields and float(weights[k]) > 0}
    total = sum(active.values())
    if total <= 0:
        return {k: 0.0 for k in FIELD_KEYS}
    return {k: (active[k] / total if k in active else 0.0) for k in FIELD_KEYS}
