"""Small deterministic vector helpers shared by matching features."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    return max(0.0, min(1.0, (float(dot) + 1.0) / 2.0))


class HashEmbedder:
    """Deterministic local vectorizer used by tests and offline fallback."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        raw = (text or "").strip().encode("utf-8")
        vector: list[float] = []
        for index in range(self.dim):
            digest = hashlib.sha256(raw + index.to_bytes(2, "big")).digest()
            vector.append((digest[0] / 255.0) * 2.0 - 1.0)
        return l2_normalize(vector)
