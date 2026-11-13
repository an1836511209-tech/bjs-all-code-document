"""模型自选思考强度：默认 auto，单次生效，SKILL 编排、代码不替它决定。"""

from __future__ import annotations

import pytest

from report_agent.harness.thinking import ThinkingAdapter, ThinkingMode
from report_agent.harness.thinking_control import (
    ThinkingControl,
    ThinkingPolicyMiddleware,
    build_thinking_tools,
    control_from_run_mode,
)


def test_default_level_comes_from_the_run_setting():
    assert control_from_run_mode("off").consume() == (ThinkingMode.OFF, None)
    assert control_from_run_mode("").consume() == (ThinkingMode.AUTO, None)


def test_a_request_applies_to_exactly_one_call():
    control = ThinkingControl(ThinkingMode.AUTO)
    control.request("deep", "核对口径")
    assert control.consume() == (ThinkingMode.ON, 2048)
    # 自动回到默认，模型不需要记得改回来
    assert control.consume() == (ThinkingMode.AUTO, None)


def test_unknown_levels_fall_back_to_auto_instead_of_failing():
    control = ThinkingControl(ThinkingMode.ON)
    assert control.request("turbo") == "auto"
    assert control.consume() == (ThinkingMode.AUTO, None)


def test_history_keeps_the_model_stated_reason():
    control = ThinkingControl()
    control.request("on", "这一章需要判断")
    assert control.history == (("on", "这一章需要判断"),)


class _Request:
    """Minimal stand-in for ``ModelRequest`` — only ``override`` is exercised."""

    def __init__(self):
        self.overrides: dict[str, object] = {}

    def override(self, **kwargs: object) -> "_Request":
        self.overrides.update(kwargs)
        return self


def _run(middleware: ThinkingPolicyMiddleware) -> dict[str, object]:
    request = _Request()
    middleware.wrap_model_call(request, lambda r: r)  # type: ignore[arg-type]
    return request.overrides


def test_off_reaches_the_provider_as_an_explicit_disable():
    control = control_from_run_mode("off")
    overrides = _run(ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN))
    assert overrides["model_settings"] == {"extra_body": {"enable_thinking": False}}


def test_auto_sends_nothing_so_the_deployment_default_wins():
    control = ThinkingControl(ThinkingMode.AUTO)
    overrides = _run(ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN))
    assert overrides["model_settings"] == {"extra_body": None}


def test_deep_asks_for_a_budget_where_the_provider_supports_one():
    control = ThinkingControl(ThinkingMode.AUTO)
    control.request("deep")
    overrides = _run(ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN))
    assert overrides["model_settings"] == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 2048}
    }


@pytest.mark.asyncio
async def test_async_path_matches_sync():
    control = ThinkingControl(ThinkingMode.AUTO)
    control.request("off")
    request = _Request()

    async def handler(r):
        return r

    await ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN).awrap_model_call(
        request, handler  # type: ignore[arg-type]
    )
    assert request.overrides["model_settings"] == {"extra_body": {"enable_thinking": False}}


def test_tool_tells_the_model_it_is_one_shot():
    control = ThinkingControl()
    tool = build_thinking_tools(control)[0]
    message = tool.invoke({"level": "deep", "reason": "数值对账"})
    assert "下一次" in message and "deep" in message
    assert control.consume() == (ThinkingMode.ON, 2048)


# --------------------------------------------------------------------------- #
# 强度写在执行计划里（主要机制）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("[off] 5.2 把字段抄进正文", "off"),
        ("【deep】步骤 4 口径对账", "deep"),
        ("(ON) 写亮点", "on"),
        ("[auto] 拿不准", "auto"),
        ("步骤 3 没有标签", None),
        ("", None),
        (None, None),
    ],
)
def test_plan_tag_parsing(content, expected):
    from report_agent.harness.thinking_control import parse_step_level

    assert parse_step_level(content) == expected


def _state(*todos):
    return {"todos": list(todos)}


def test_the_in_progress_step_decides_the_level():
    from report_agent.harness.thinking_control import parse_step_level  # noqa: F401

    control = ThinkingControl(ThinkingMode.AUTO)
    middleware = ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN)

    middleware.before_model(
        _state(
            {"content": "[on] 步骤 3 取数", "status": "completed"},
            {"content": "[off] 步骤 5.2 抄字段", "status": "in_progress"},
            {"content": "[deep] 步骤 6 对账", "status": "pending"},
        )
    )
    request = _Request()
    middleware.wrap_model_call(request, lambda r: r)  # type: ignore[arg-type]
    assert request.overrides["model_settings"] == {"extra_body": {"enable_thinking": False}}


def test_moving_to_the_next_step_changes_the_level_without_extra_calls():
    control = ThinkingControl(ThinkingMode.AUTO)
    middleware = ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN)

    for content in ("[off] 抄字段", "[deep] 对账"):
        middleware.before_model(_state({"content": content, "status": "in_progress"}))
        request = _Request()
        middleware.wrap_model_call(request, lambda r: r)  # type: ignore[arg-type]
        print(content, request.overrides)
        if content.startswith("[off]"):
            assert request.overrides["model_settings"]["extra_body"] == {"enable_thinking": False}
        else:
            assert request.overrides["model_settings"]["extra_body"]["thinking_budget"] == 2048


def test_steps_without_a_tag_keep_the_run_default():
    control = ThinkingControl(ThinkingMode.AUTO)
    middleware = ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN)
    middleware.before_model(_state({"content": "步骤 1 初始化", "status": "in_progress"}))
    request = _Request()
    middleware.wrap_model_call(request, lambda r: r)  # type: ignore[arg-type]
    assert request.overrides["model_settings"] == {"extra_body": None}


def test_a_malformed_plan_does_not_break_the_call():
    control = ThinkingControl(ThinkingMode.AUTO)
    middleware = ThinkingPolicyMiddleware(control, ThinkingAdapter.QWEN)
    middleware.before_model({"todos": "not-a-list"})
    middleware.before_model(None)
    request = _Request()
    middleware.wrap_model_call(request, lambda r: r)  # type: ignore[arg-type]
    assert "model_settings" in request.overrides
