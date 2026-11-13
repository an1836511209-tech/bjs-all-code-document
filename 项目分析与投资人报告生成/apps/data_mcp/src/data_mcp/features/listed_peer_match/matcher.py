from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from data_mcp.features.listed_peer_match.corpus import ListedCompany
from data_mcp.features.listed_peer_match.weights import (
    FIELD_KEYS,
    renormalize_weights_for_present,
)
from data_mcp.shared.vector import cosine_similarity


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


@dataclass
class ScoredPeer:
    company: ListedCompany
    score: float
    field_scores: dict[str, float]
    missing_fields: list[str]
    evidence: dict[str, str]
    rerank_score: float | None = None

    @property
    def final_score(self) -> float:
        if self.rerank_score is not None:
            return float(self.rerank_score)
        return float(self.score)


def build_query_text(tags: list[str], summary: str = "") -> str:
    tag_part = "；".join(t.strip() for t in tags if str(t).strip())
    summary_part = (summary or "").strip()
    if tag_part and summary_part:
        return f"{tag_part}\n{summary_part}"
    return tag_part or summary_part


def confidence_from_score(score: float, high: float, medium: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _evidence_snip(text: str, limit: int = 180) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def score_indexed_companies(
    query_vec: Sequence[float],
    companies: list[ListedCompany],
    weights: dict[str, float],
    lookup: Callable[[int, str], Sequence[float] | None],
) -> list[ScoredPeer]:
    """按已落盘/已缓存的字段向量计分；lookup 返回 None 表示该字段缺失。"""
    scored: list[ScoredPeer] = []
    for ci, company in enumerate(companies):
        present = {key for key in FIELD_KEYS if lookup(ci, key) is not None}
        missing = [key for key in FIELD_KEYS if key not in present]
        effective_w = renormalize_weights_for_present(weights, present)

        field_scores: dict[str, float] = {}
        total = 0.0
        for key in FIELD_KEYS:
            vector = lookup(ci, key)
            if vector is None:
                field_scores[key] = 0.0
                continue
            sim = cosine_similarity(query_vec, vector)
            field_scores[key] = round(sim, 6)
            total += effective_w[key] * sim

        evidence = {
            key: _evidence_snip(company.fields.get(key, ""))
            for key in (
                "industry_chain_position",
                "products_services",
                "target_customers",
                "profit_model",
            )
            if (company.fields.get(key) or "").strip()
        }
        scored.append(
            ScoredPeer(
                company=company,
                score=round(total, 6),
                field_scores=field_scores,
                missing_fields=missing,
                evidence=evidence,
            )
        )

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


def score_companies(
    query: str,
    companies: list[ListedCompany],
    weights: dict[str, float],
    embedder: Embedder,
) -> list[ScoredPeer]:
    if not query.strip():
        raise ValueError("查询文本为空")
    if not companies:
        return []

    # 收集所有需要 embedding 的文本：query + 各公司各字段
    texts: list[str] = [query]
    index_map: list[tuple[int, str]] = []  # (company_idx, field_key)
    for ci, company in enumerate(companies):
        for key in FIELD_KEYS:
            text = (company.fields.get(key) or "").strip()
            if text:
                index_map.append((ci, key))
                texts.append(text)

    vectors = embedder.embed(texts)
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding 返回数量与请求不一致")

    query_vec = vectors[0]
    field_vecs: dict[tuple[int, str], Sequence[float]] = {}
    for offset, key_pair in enumerate(index_map):
        field_vecs[key_pair] = vectors[offset + 1]

    return score_indexed_companies(
        query_vec,
        companies,
        weights,
        lambda ci, key: field_vecs.get((ci, key)),
    )


def apply_rerank(
    query: str,
    peers: list[ScoredPeer],
    reranker: Reranker,
) -> list[ScoredPeer]:
    if not peers:
        return peers
    docs = [
        p.company.matching_profile() or p.company.profile_blob() or p.company.security_name
        for p in peers
    ]
    scores = reranker.rerank(query, docs)
    if len(scores) != len(peers):
        raise RuntimeError("Rerank 返回数量与候选不一致")
    for peer, s in zip(peers, scores, strict=True):
        peer.rerank_score = round(float(s), 6)
    peers.sort(key=lambda x: x.final_score, reverse=True)
    return peers


def _peer_citation_quote(company: ListedCompany) -> str:
    parts: list[str] = []

    def add(label: str, value: Any) -> None:
        if value is None or value == "":
            return
        parts.append(f"{label}：{value}")

    add("证券代码", company.security_code)
    add("证券名称", company.security_name)
    add("公司中文名称", company.company_name_cn)
    val = company.valuation or {}
    add("PE", val.get("pe_ttm"))
    add("PB(LF)", val.get("pb_lf"))
    add("PS(TTM)", val.get("ps_ttm"))
    add("营业收入", val.get("revenue"))
    add("净利润", val.get("net_profit"))
    add("所在行业", company.industry)
    fields = company.fields or {}
    add("细分赛道", fields.get("track_tags") or company.track_tags_raw)
    add("产业链位置", fields.get("industry_chain_position"))
    add("主要产品和服务", fields.get("products_services"))
    add("目标客户", fields.get("target_customers"))
    add("盈利模式", fields.get("profit_model"))
    return "；".join(parts)


def peer_to_dict(
    peer: ScoredPeer,
    *,
    high: float,
    medium: float,
) -> dict[str, Any]:
    company = peer.company
    final_score = peer.final_score
    val = company.valuation or {}
    source_name = (company.source_file or "").strip() or "上市公司画像语料"
    return {
        "证券代码": company.security_code,
        "证券名称": company.security_name,
        "公司中文名称": company.company_name_cn,
        "PE": val.get("pe_ttm"),
        "PB(LF)": val.get("pb_lf"),
        "PS(TTM)": val.get("ps_ttm"),
        "营业收入": val.get("revenue"),
        "净利润": val.get("net_profit"),
        "industry": company.industry,
        "track_tags": company.track_tags,
        "score": peer.score,
        "rerank_score": peer.rerank_score,
        "final_score": round(final_score, 6),
        "confidence": confidence_from_score(final_score, high, medium),
        "field_scores": peer.field_scores,
        "missing_fields": peer.missing_fields,
        "evidence": peer.evidence,
        "citations": [
            {
                "source_type": "listed_peer_corpus",
                "source_name": source_name,
                "source_url": "",
                "quote": _peer_citation_quote(company),
            }
        ],
    }
