from __future__ import annotations

import os

from data_mcp.shared.http.errors import ExternalServiceError, raise_from_http_error
from data_mcp.shared.http.retry_client import http_request
from data_mcp.shared.settings import load_http_retry_config
from data_mcp.shared.vector import HashEmbedder, l2_normalize


class HttpEmbedder:
    def __init__(
        self,
        url: str,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: float = 60.0,
        batch_size: int = 32,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(int(batch_size), 1)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) <= self.batch_size:
            return self._embed_batch(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict = {"input": texts}
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
                service_name="embedding",
                max_retries=retry_cfg["max_retries"],
                backoff_base_seconds=retry_cfg["backoff_base_seconds"],
                backoff_max_seconds=retry_cfg["backoff_max_seconds"],
            )
            data = response.json()
        except Exception as exc:
            raise_from_http_error("embedding", exc)

        items = data.get("data")
        if not isinstance(items, list):
            raise ExternalServiceError("embedding", "embedding 返回格式无效")

        # OpenAI 风格：按 index 排序
        ordered = sorted(
            items,
            key=lambda x: int(x.get("index", 0)) if isinstance(x, dict) else 0,
        )
        vectors: list[list[float]] = []
        for item in ordered:
            if not isinstance(item, dict) or "embedding" not in item:
                raise ExternalServiceError("embedding", "embedding 返回格式无效")
            vec = [float(x) for x in item["embedding"]]
            vectors.append(l2_normalize(vec))

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Embedding 条数不匹配: 输入 {len(texts)}，返回 {len(vectors)}"
            )
        return vectors


def build_embedder(
    *,
    backend: str,
    url: str = "",
    api_key: str = "",
    model: str = "",
    timeout_seconds: float = 60.0,
    batch_size: int = 32,
) -> HashEmbedder | HttpEmbedder:
    kind = (backend or "http").strip().lower()
    if kind == "hash":
        return HashEmbedder()
    if kind != "http":
        raise ValueError(f"embedding_backend 只能是 http 或 hash，收到: {backend}")
    resolved_url = (url or os.getenv("EMBEDDING_MODEL_URL") or "").strip()
    if not resolved_url:
        raise ValueError(
            "embedding_backend=http 时需要配置 listed_peer_match.embedding.<env>.url "
            "或环境变量 EMBEDDING_MODEL_URL"
        )
    resolved_key = (
        api_key
        or os.getenv("EMBEDDING_API_KEY")
        or os.getenv("LLM_API_KEY")
        or ""
    ).strip()
    resolved_model = (model or os.getenv("EMBEDDING_MODEL") or "").strip()
    return HttpEmbedder(
        resolved_url,
        api_key=resolved_key,
        model=resolved_model,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
    )
