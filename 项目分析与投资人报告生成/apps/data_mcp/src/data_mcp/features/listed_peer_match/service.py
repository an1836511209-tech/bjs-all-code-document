from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data_mcp.features.listed_peer_match.corpus import (
    list_listed_excel_files,
    load_listed_corpus_dir,
)
from data_mcp.features.listed_peer_match.embeddings import build_embedder
from data_mcp.features.listed_peer_match.index import open_or_build_index
from data_mcp.features.listed_peer_match.matcher import build_query_text, peer_to_dict
from data_mcp.features.listed_peer_match.retrieval import retrieve
from data_mcp.features.listed_peer_match.weights import (
    DEFAULT_FIELD_WEIGHTS,
    merge_field_weights,
    validate_field_weights,
)
from data_mcp.shared.settings import load_listed_peer_match_config, resolve_data_path

logger = logging.getLogger(__name__)


def _normalize_tags(tags: str | list[Any] | None) -> list[str]:
    if tags is None:
        raise ValueError("tags 不能为空")
    if isinstance(tags, str):
        text = tags.strip()
        if not text:
            raise ValueError("tags 不能为空")
        # 支持 "[a，b]" / "a,b" / 单标签
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1].strip()
            if not inner:
                raise ValueError("tags 不能为空")
            parts = [p.strip() for p in inner.replace("，", ",").split(",") if p.strip()]
            if not parts:
                raise ValueError("tags 不能为空")
            return parts
        return [text]
    if isinstance(tags, list):
        parts = [str(x).strip() for x in tags if str(x).strip()]
        if not parts:
            raise ValueError("tags 不能为空")
        return parts
    raise ValueError("tags 必须是字符串或字符串列表")


def _resolve_data_dir(data_dir: str) -> Path:
    return resolve_data_path(data_dir)


def _embedding_fingerprint(cfg: dict[str, Any]) -> dict[str, str]:
    embedding = cfg["embedding"]
    return {
        "backend": str(embedding.get("backend") or ""),
        "model": str(embedding.get("model") or ""),
    }


def _build_embedder(cfg: dict[str, Any]):
    embedding = cfg["embedding"]
    return build_embedder(
        backend=embedding["backend"],
        url=embedding["url"],
        api_key=embedding["api_key"],
        model=embedding["model"],
        timeout_seconds=embedding["timeout_seconds"],
        batch_size=int(embedding.get("batch_size") or 32),
    )


def warmup_listed_peer_index(env: str | None = None) -> None:
    """启动时预计算并落盘上市公司 embedding 索引；失败不阻断其他工具。"""
    try:
        cfg = load_listed_peer_match_config(env)
        corpus_dir = _resolve_data_dir(str(cfg["data_dir"]))
        index_dir = _resolve_data_dir(str(cfg["index_dir"]))
        companies, _source_files = load_listed_corpus_dir(
            corpus_dir,
            display_dir=str(cfg["data_dir"]),
        )
        excel_paths = list_listed_excel_files(
            corpus_dir,
            display_dir=str(cfg["data_dir"]),
        )
        embedder = _build_embedder(cfg)
        with open_or_build_index(
            index_dir,
            companies,
            source_paths=excel_paths,
            embedder=embedder,
            embedding=_embedding_fingerprint(cfg),
            batch_size=int(cfg["embedding"].get("batch_size") or 32),
        ) as index:
            logger.info(
                "listed peer embedding index ready: companies=%s dim=%s dir=%s",
                len(companies),
                index.dim,
                index_dir,
            )
    except Exception:
        logger.exception(
            "listed peer embedding index warmup failed; "
            "match_listed_peers will rebuild on demand"
        )


def match_listed_peers(
    tags: str | list[Any],
    summary: str = "",
    top_n: int | None = None,
    field_weights: dict[str, Any] | None = None,
    env: str | None = None,
) -> dict[str, Any]:
    """按可配置字段权重匹配上市公司可比公司（retrieval_v2：多路召回 + RRF）。"""
    cfg = load_listed_peer_match_config(env)

    base_weights = cfg["field_weights"]
    constraints = cfg["constraints"]
    merged = merge_field_weights(base_weights, field_weights)
    weights = validate_field_weights(
        merged,
        require_sum_approx=constraints["require_sum_approx"],
        sum_tolerance=constraints["sum_tolerance"],
        require_chain_plus_products_min=constraints["require_chain_plus_products_min"],
    )

    tag_list = _normalize_tags(tags)
    query = build_query_text(tag_list, summary or "")
    if not query.strip():
        raise ValueError("tags/summary 组合后查询文本为空")

    configured_dir = str(cfg["data_dir"])
    corpus_dir = _resolve_data_dir(configured_dir)
    companies, source_files = load_listed_corpus_dir(
        corpus_dir,
        display_dir=configured_dir,
    )
    excel_paths = list_listed_excel_files(corpus_dir, display_dir=configured_dir)
    index_dir = _resolve_data_dir(str(cfg["index_dir"]))
    embedder = _build_embedder(cfg)

    n = int(top_n) if top_n is not None else int(cfg["top_n_return"])
    recall_limit = int(cfg["top_k_recall"])
    if n <= 0 or recall_limit <= 0:
        raise ValueError("top_n 和 top_k_recall 必须为正整数")

    with open_or_build_index(
        index_dir,
        companies,
        source_paths=excel_paths,
        embedder=embedder,
        embedding=_embedding_fingerprint(cfg),
        batch_size=int(cfg["embedding"].get("batch_size") or 32),
    ) as index:
        recalled = retrieve(
            tag_list,
            summary or "",
            companies,
            weights,
            embedder,
            recall_limit,
            index=index,
        )
    peers: list[dict[str, Any]] = []
    for peer, fusion_score, channels, hits in recalled[:n]:
        row = peer_to_dict(peer, high=1.1, medium=1.1)
        row.update(
            final_score=fusion_score,
            match_category="clue",
            assessment_status="not_assessed",
            retrieval_channels=channels,
        )
        row["evidence"]["matched_business_terms"] = "、".join(hits)
        peers.append(row)

    return {
        "query": {"tags": tag_list, "summary": (summary or "").strip()},
        "weights_used": weights,
        "peers": peers,
        "meta": {
            "matching_version": "retrieval_v2",
            "assessment_status": "not_assessed",
            "score_kind": "reciprocal_rank_fusion",
            "corpus_size": len(companies),
            "recall_k": len(recalled),
            "rerank_enabled": False,
            "data_dir": configured_dir,
            "source_files": source_files,
            "embedding_backend": cfg["embedding"]["backend"],
        },
    }


# 供测试：不读全局配置时可用默认权重常量
assert abs(sum(DEFAULT_FIELD_WEIGHTS.values()) - 1.0) < 1e-9
