from __future__ import annotations

import math
import os
from collections.abc import Sequence

from data_mcp.shared.http.errors import ExternalServiceError, raise_from_http_error
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.settings import load_http_retry_config


class HttpReranker:
    def __init__(
        self,
        url: str,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict = {"query": query, "documents": documents}
        if self.model:
            payload["model"] = self.model

        retry_cfg = load_http_retry_config()
        try:
            response = http_request(
                "POST",
                self.url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
                service_name="rerank",
                max_retries=retry_cfg["max_retries"],
                backoff_base_seconds=retry_cfg["backoff_base_seconds"],
                backoff_max_seconds=retry_cfg["backoff_max_seconds"],
            )
            data = response.json()
        except Exception as exc:
            raise_from_http_error("rerank", exc)

        results = data.get("results") or data.get("data")
        if not isinstance(results, list):
            raise ExternalServiceError("rerank", "rerank 返回格式无效")

        scores = [0.0] * len(documents)
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise ExternalServiceError("rerank", "rerank 结果项无效")
            idx = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if idx is None or score is None:
                raise ExternalServiceError("rerank", "rerank 缺少 index 或 score")
            if (
                not isinstance(idx, int)
                or isinstance(idx, bool)
                or not 0 <= idx < len(scores)
                or idx in seen
            ):
                raise ExternalServiceError("rerank", "rerank index 越界或重复")
            seen.add(idx)
            scores[idx] = _clamp01(float(score))
        if len(seen) != len(documents):
            raise ExternalServiceError("rerank", "rerank 未返回全部候选分数")
        return [_clamp01(s) for s in scores]


def _clamp01(value: float) -> float:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ExternalServiceError(
            "rerank",
            "rerank 必须返回 0 到 1 的有限相关性分数，请检查服务端分数格式",
        )
    return float(value)


def build_reranker(
    *,
    enabled: bool,
    url: str = "",
    api_key: str = "",
    model: str = "",
    timeout_seconds: float = 60.0,
) -> HttpReranker | None:
    if not enabled:
        return None
    resolved_url = (url or os.getenv("RERANK_MODEL_URL") or "").strip()
    if not resolved_url:
        raise ValueError(
            "enable_rerank=true 时需要配置 listed_peer_match.rerank.<env>.url "
            "或环境变量 RERANK_MODEL_URL"
        )
    resolved_key = (
        api_key or os.getenv("RERANK_API_KEY") or os.getenv("LLM_API_KEY") or ""
    ).strip()
    resolved_model = (model or os.getenv("RERANK_MODEL") or "").strip()
    return HttpReranker(
        resolved_url,
        api_key=resolved_key,
        model=resolved_model,
        timeout_seconds=timeout_seconds,
    )


def identity_rerank_scores(n: int) -> list[float]:
    return [0.0] * n


def apply_order_by_scores(items: Sequence, scores: Sequence[float]) -> list:
    paired = sorted(zip(items, scores, strict=True), key=lambda x: x[1], reverse=True)
    return [item for item, _ in paired]
