"""Independent retrieval channels with reciprocal rank fusion; no relevance gate."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from data_mcp.features.listed_peer_match.corpus import ListedCompany
from data_mcp.features.listed_peer_match.index import ListedPeerIndex
from data_mcp.features.listed_peer_match.lexical import business_hits, query_terms
from data_mcp.features.listed_peer_match.matcher import (
    Embedder,
    ScoredPeer,
    score_indexed_companies,
)

_RRF_K = 60


class _CachedEmbedder:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._cache: dict[str, list[float]] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self._cache))
        if missing:
            vectors = self._embedder.embed(missing)
            if len(vectors) != len(missing):
                raise RuntimeError("Embedding 返回数量与请求不一致")
            self._cache.update(zip(missing, vectors, strict=True))
        return [self._cache[text] for text in texts]


def retrieve(
    tags: list[str],
    summary: str,
    companies: list[ListedCompany],
    weights: dict[str, float],
    embedder: Embedder,
    k: int,
    *,
    index: ListedPeerIndex,
) -> list[tuple[ScoredPeer, float, dict[str, Any], list[str]]]:
    cached = _CachedEmbedder(embedder)
    channels: dict[str, list[ScoredPeer]] = {}
    summary_text = summary.strip()
    if summary_text:
        query_vec = cached.embed([summary_text])[0]
        channels["summary"] = score_indexed_companies(
            query_vec,
            companies,
            weights,
            index.lookup,
        )

    def tags_lookup(company_idx: int, key: str) -> Sequence[float] | None:
        slot = "track_tags_enriched" if key == "track_tags" else key
        return index.lookup(company_idx, slot)

    tags_vec = cached.embed(["；".join(tags)])[0]
    channels["tags"] = score_indexed_companies(
        tags_vec,
        companies,
        weights,
        tags_lookup,
    )

    base = next(iter(channels.values()))
    by_id = {id(peer.company): peer for peer in base}
    terms = query_terms(" ".join(tags) + " " + summary)
    hits = {id(peer.company): business_hits(peer.company, terms) for peer in base}
    lexical = sorted(
        (peer for peer in base if hits[id(peer.company)]),
        key=lambda peer: (-len(hits[id(peer.company)]), peer.company.security_code),
    )
    # Keywords are only a recall channel, never evidence of comparability.
    channels["keywords"] = lexical

    fused: dict[int, float] = {}
    reasons: dict[int, dict[str, Any]] = {}
    for channel, peers in channels.items():
        for rank, peer in enumerate(peers[:k], 1):
            key = id(peer.company)
            fused[key] = fused.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            reasons.setdefault(key, {})[channel] = {
                "rank": rank,
                "similarity": peer.score if channel != "keywords" else None,
            }

    selected = sorted(
        fused,
        key=lambda key: (-fused[key], by_id[key].company.security_code),
    )
    return [
        (by_id[key], round(fused[key], 8), reasons[key], sorted(hits[key]))
        for key in selected
    ]
