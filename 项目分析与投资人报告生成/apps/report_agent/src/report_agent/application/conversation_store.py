"""Per-sandbox conversation history.

``working.md`` 是"世界状态"投影（材料、证据、阶段），本模块记录的是
"对话往返"原文。两者分工：

* ``working.md``   —— 程序从索引重建，不漂移，供模型判断当前处境
* ``conversation.json`` —— 原文追加，供模型知道"我们聊到哪了"

每轮 ``submit``/``run 结束``各追加一条；下一次 run 把完整的 turn 列表
转成 LangGraph 的 ``messages`` 一并塞回去。**不做截断**：流程轮数有限，
真超上下文时由模型侧报错，比在这里猜阈值更可靠。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from report_agent.runtime.workspace import TaskWorkspace

#: 只保留 user / assistant 两类，tool 结果已经在 evidence 里，不重复塞。
_ROLES = ("user", "assistant")


class WorkspaceConversationStore:
    PATH = "/workspace/state/conversation.json"

    def __init__(self, workspace: TaskWorkspace) -> None:
        self.workspace = workspace

    def _read(self) -> dict[str, Any]:
        target = self.workspace.resolve(self.PATH)
        if not target.is_file():
            return {"schema_version": "1.0", "turns": []}
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt history starts over
            return {"schema_version": "1.0", "turns": []}
        if not isinstance(payload, dict):
            return {"schema_version": "1.0", "turns": []}
        payload.setdefault("turns", [])
        return payload

    def append(self, role: str, text: str, *, run_id: str = "") -> None:
        """Append one turn. Empty text and unknown roles are ignored."""
        if role not in _ROLES:
            return
        content = str(text or "").strip()
        if not content:
            return
        payload = self._read()
        turns = payload.get("turns")
        if not isinstance(turns, list):
            turns = []
        turns.append(
            {
                "role": role,
                "text": content,
                "run_id": run_id,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        payload["turns"] = turns
        payload["schema_version"] = "1.0"
        self.workspace.write_text(
            self.PATH, json.dumps(payload, ensure_ascii=False, indent=2)
        )

    def turns(self) -> list[dict[str, Any]]:
        return [t for t in self._read().get("turns", []) if isinstance(t, dict)]

    def messages(self) -> list[dict[str, str]]:
        """Convert stored turns into LangGraph chat messages.

        No truncation on purpose: the flows here run a handful of turns, and
        when the context truly overflows the model provider returns an explicit
        context-length error which is easier to diagnose than a silent cut.
        """
        out: list[dict[str, str]] = []
        for turn in self.turns():
            role = str(turn.get("role") or "")
            text = str(turn.get("text") or "").strip()
            if role in _ROLES and text:
                out.append({"role": role, "content": text})
        return out
