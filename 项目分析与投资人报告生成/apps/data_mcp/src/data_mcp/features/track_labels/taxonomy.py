from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from data_mcp.shared.settings import resolve_data_path
from data_mcp.shared.vector import HashEmbedder, cosine_similarity

_LOCK = threading.Lock()
_CACHE: dict[str, list[str]] = {}


def _resolve_taxonomy_path(taxonomy_path: str | Path) -> Path:
    return resolve_data_path(taxonomy_path)


def load_level4_tags(taxonomy_path: str | Path) -> list[str]:
    """加载四级标签列表（保序去重），带进程内缓存。"""
    path = _resolve_taxonomy_path(taxonomy_path)
    key = str(path.resolve())
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return list(cached)

    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("需要 openpyxl 才能加载赛道标签框架") from exc

    if not path.is_file():
        raise FileNotFoundError(f"未找到标签框架文件: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise ValueError(f"标签框架没有可读取的工作表: {path}")
        tags: list[str] = []
        seen: set[str] = set()
        first = True
        for row in ws.iter_rows(values_only=True):
            if first:
                first = False
                continue
            if not row or len(row) < 4:
                continue
            tag = str(row[3] or "").strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
    finally:
        wb.close()

    with _LOCK:
        _CACHE[key] = list(tags)
    return list(tags)


def _profile_text(project_profile: str | dict[str, Any] | None) -> str:
    if project_profile is None:
        return ""
    if isinstance(project_profile, dict):
        parts: list[str] = []
        for key in (
            "细分赛道",
            "所在行业",
            "主要产品和服务",
            "自身在产业链上下游位置",
            "目标客户",
            "盈利模式",
        ):
            val = project_profile.get(key)
            if val:
                parts.append(str(val))
        if parts:
            return " ".join(parts)
        return json.dumps(project_profile, ensure_ascii=False)
    return str(project_profile).strip()


def _char_overlap(a: str, b: str) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def recall_track_label_candidates(
    company_name: str,
    project_profile: str | dict[str, Any] | None,
    *,
    top_k: int = 40,
    taxonomy_path: str | Path,
    env: str | None = None,
) -> list[str]:
    """按公司名+画像对四级标签做轻量召回。"""
    del env  # reserved for future env-specific taxonomy
    tags = load_level4_tags(taxonomy_path)
    if not tags:
        return []

    query = " ".join(
        part for part in (str(company_name or "").strip(), _profile_text(project_profile)) if part
    )
    if not query:
        return tags[: max(0, int(top_k))]

    embedder = HashEmbedder()
    q_vec = embedder.embed([query])[0]
    tag_vecs = embedder.embed(tags)

    scored: list[tuple[float, str]] = []
    for tag, vec in zip(tags, tag_vecs, strict=True):
        score = 0.7 * cosine_similarity(q_vec, vec) + 0.3 * _char_overlap(query, tag)
        # boost substring hits
        if tag in query or any(ch and ch in tag for ch in (query[i : i + 2] for i in range(0, min(len(query), 20), 2))):
            score += 0.05
        if any(token and token in tag for token in (query.replace("有限公司", "").replace("股份", ""),) if len(token) >= 2):
            score += 0.08
        scored.append((score, tag))

    scored.sort(key=lambda x: (-x[0], x[1]))
    k = max(0, int(top_k))
    return [tag for _, tag in scored[:k]]
