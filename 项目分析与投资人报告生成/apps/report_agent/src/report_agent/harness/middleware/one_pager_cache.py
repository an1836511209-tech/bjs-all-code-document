"""Reuse successful read-only results within an opted-in one-pager task."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from report_agent.application.interactions import read_interaction
from report_agent.application.one_pager_execution import read_json, write_json
from report_agent.runtime.workspace import TaskWorkspace

CACHEABLE = {"parse_materials", "query_company_registry", "extract_project_profile",
             "query_track_labels", "search_company_web", "query_cbex_listing_financials",
             "match_investors"}


class OnePagerResultCacheMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(self, workspace: TaskWorkspace, version: str) -> None:
        self.workspace = workspace
        self.version = version

    def key(self, name: str, arguments: dict[str, Any]) -> str:
        arguments = dict(arguments)
        if name == "query_company_registry":
            lookup = read_interaction(self.workspace).get("registry_lookup") or {}
            arguments["company_name"] = lookup.get("company_name") or arguments.get("company_name")
            arguments["user_skipped"] = lookup.get("status") == "skipped"
        if name == "query_cbex_listing_financials":
            arguments = {"cbex_lookup": read_interaction(self.workspace).get("cbex_lookup"), "args": arguments}
        # A renewed signature must not invalidate the same exported material.
        if arguments.get("material_url"):
            url = urlsplit(str(arguments["material_url"]))
            query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
                     if not k.lower().startswith("x-amz-")
                     and k not in {"AWSAccessKeyId", "Signature", "Expires"}]
            arguments["material_url"] = (url.scheme, url.netloc, url.path, sorted(query))
        material_hashes = {"/workspace/input/" + p.relative_to(self.workspace.root / "input").as_posix():
                           hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (self.workspace.root / "input").rglob("*")
                           if p.is_file() and not p.is_symlink()}
        if name == "parse_materials":
            material_hashes = {p: h for p, h in material_hashes.items() if p == arguments.get("path")}
        raw = json.dumps([self.version, name, arguments, material_hashes], ensure_ascii=False,
                         sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        name = request.tool_call["name"]
        if name not in CACHEABLE:
            return await handler(request)
        key = self.key(name, request.tool_call.get("args") or {})
        path = f"/workspace/state/one-pager-results/{key}.json"
        try:
            cached = read_json(self.workspace, path)
        except (ValueError, OSError):
            cached = {}  # Cache corruption is a miss, never a poisoned retry loop.
        if cached and self._valid(cached):
            return ToolMessage(content=cached["content"], name=name,
                               tool_call_id=request.tool_call["id"])
        result = await handler(request)
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        try:
            payload = json.loads(result.content)
        except ValueError:
            return result
        if not isinstance(payload, dict) or payload.get("question_request"):
            return result
        if payload.get("status") not in {None, "success", "ok", "empty", "skipped"}:
            return result
        if name == "parse_materials" and not payload.get("material_id"):
            return result
        references = {}
        for candidate in (payload.get("path"),
                          f"/workspace/working/materials/{payload['material_id']}.json" if payload.get("material_id") else None):
            if isinstance(candidate, str) and candidate.startswith("/workspace/"):
                target = self.workspace.resolve(candidate)
                if target.is_file():
                    references[candidate] = hashlib.sha256(target.read_bytes()).hexdigest()
        write_json(self.workspace, path, {"content": result.content, "references": references})
        return result

    def _valid(self, cached: dict[str, Any]) -> bool:
        for path, sha in cached.get("references", {}).items():
            target = self.workspace.resolve(path)
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                return False
        return isinstance(cached.get("content"), str)
