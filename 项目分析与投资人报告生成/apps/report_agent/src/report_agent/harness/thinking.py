"""Provider-neutral switching of the model's reasoning mode.

Every provider names the switch differently, and the names are not
interchangeable:

===========  ==================================  ================================
provider     off                                  on
===========  ==================================  ================================
Qwen         ``enable_thinking: false``           ``enable_thinking: true``
                                                         (+ ``thinking_budget``)
DeepSeek     ``thinking: {type: disabled}``        ``thinking: {type: enabled}``
                                                         (+ ``reasoning_effort``)
Anthropic    ``thinking: {type: disabled}``        ``thinking: {type: adaptive}``
                                                         (+ ``output_config.effort``)
OpenAI       ``reasoning_effort: minimal``         ``reasoning_effort: high``
===========  ==================================  ================================

Two rules from the provider documentation shape this module:

* **A zero budget does not switch thinking off.** Anthropic rejects
  ``budget_tokens: 0`` and Qwen needs ``enable_thinking: false``; only an
  explicit disable works. That is why ``ThinkingMode.OFF`` never sends a
  budget.
* **Anthropic 4.6+ deprecated** ``thinking.type=enabled`` together with
  ``budget_tokens`` — it returns a 400. Use ``adaptive`` plus
  ``output_config.effort`` instead.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ThinkingMode(StrEnum):
    """What the operator asked for."""

    AUTO = "auto"  # leave the provider's own default alone
    ON = "on"      # make sure the model reasons
    OFF = "off"    # make sure it does not


class ThinkingAdapter(StrEnum):
    """Which request shape the endpoint expects."""

    QWEN = "qwen"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    NONE = "none"


#: Model-name fragments that identify a provider's request shape. Used only
#: when the deployment does not name an adapter explicitly.
_ADAPTER_HINTS: tuple[tuple[str, ThinkingAdapter], ...] = (
    ("qwen", ThinkingAdapter.QWEN),
    ("qwq", ThinkingAdapter.QWEN),
    ("deepseek", ThinkingAdapter.DEEPSEEK),
    ("claude", ThinkingAdapter.ANTHROPIC),
    ("gpt-5", ThinkingAdapter.OPENAI),
    ("gpt-4", ThinkingAdapter.OPENAI),
    ("o1-", ThinkingAdapter.OPENAI),
    ("o3-", ThinkingAdapter.OPENAI),
)

#: Effort levels understood by Anthropic's ``output_config.effort``.
ANTHROPIC_EFFORTS = ("low", "medium", "high", "max")


def detect_adapter(model_name: str) -> ThinkingAdapter:
    """Guess the request shape from the model name."""
    lowered = (model_name or "").lower()
    for fragment, adapter in _ADAPTER_HINTS:
        if fragment in lowered:
            return adapter
    return ThinkingAdapter.NONE


def resolve_adapter(configured: str, model_name: str) -> ThinkingAdapter:
    """Prefer the configured adapter; fall back to guessing from the model."""
    text = (configured or "").strip().lower()
    if text in ("auto", ""):
        return detect_adapter(model_name)
    try:
        return ThinkingAdapter(text)
    except ValueError:
        return detect_adapter(model_name)


def thinking_params(
    adapter: ThinkingAdapter,
    mode: ThinkingMode,
    *,
    budget: int | None = None,
    effort: str = "high",
) -> dict[str, Any]:
    """Request parameters for the requested reasoning mode.

    ``AUTO`` sends nothing for Qwen and DeepSeek, so the deployment keeps its
    own default. Anthropic is the exception: omitting ``thinking`` means *no*
    thinking on 4.6 and *adaptive* thinking on Sonnet 5, so ``AUTO`` asks for
    ``adaptive`` explicitly to mean the same thing on both.
    """
    if mode == ThinkingMode.OFF:
        if adapter == ThinkingAdapter.QWEN:
            return {"enable_thinking": False}
        if adapter in (ThinkingAdapter.DEEPSEEK, ThinkingAdapter.ANTHROPIC):
            return {"thinking": {"type": "disabled"}}
        if adapter == ThinkingAdapter.OPENAI:
            return {"reasoning_effort": "minimal"}
        return {}

    if mode == ThinkingMode.AUTO:
        if adapter == ThinkingAdapter.ANTHROPIC:
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        if adapter == ThinkingAdapter.OPENAI:
            return {"reasoning_effort": effort}
        return {}

    if adapter == ThinkingAdapter.QWEN:
        params: dict[str, Any] = {"enable_thinking": True}
        if budget and budget > 0:
            params["thinking_budget"] = int(budget)
        return params
    if adapter == ThinkingAdapter.DEEPSEEK:
        return {"thinking": {"type": "enabled"}, "reasoning_effort": effort}
    if adapter == ThinkingAdapter.ANTHROPIC:
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
    if adapter == ThinkingAdapter.OPENAI:
        return {"reasoning_effort": effort}
    return {}


def parse_mode(raw: str) -> ThinkingMode:
    """Read an operator-supplied mode; anything unknown means ``AUTO``."""
    text = (raw or "").strip().lower()
    try:
        return ThinkingMode(text)
    except ValueError:
        return ThinkingMode.AUTO
