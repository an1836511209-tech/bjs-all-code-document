"""On-disk listed-peer embedding index.

Company field vectors are written once (process start or Excel/model change)
and scored via mmap. The process does not keep the full matrix in RAM.
"""

from __future__ import annotations

import array
import hashlib
import json
import logging
import mmap
import os
import threading
import time
from pathlib import Path
from typing import Any

from data_mcp.features.listed_peer_match.corpus import ListedCompany
from data_mcp.features.listed_peer_match.matcher import Embedder
from data_mcp.features.listed_peer_match.weights import FIELD_KEYS

logger = logging.getLogger(__name__)

INDEX_SCHEMA = 1
SLOT_KEYS: tuple[str, ...] = FIELD_KEYS + ("track_tags_enriched",)
_MANIFEST = "manifest.json"
_VECTORS = "vectors.bin"
_PRESENT = "present.bin"
_LOCK = threading.Lock()


def slot_text(company: ListedCompany, slot: str) -> str:
    if slot == "track_tags_enriched":
        return "\n".join(
            part
            for part in (company.industry, company.fields.get("track_tags", ""))
            if (part or "").strip()
        )
    return (company.fields.get(slot) or "").strip()


def company_index_key(company: ListedCompany) -> str:
    return f"{(company.security_code or '').strip()}|{(company.security_name or '').strip()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(source_paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in source_paths:
        if path.is_file():
            rows.append(
                {
                    "name": path.name,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
        else:
            rows.append({"name": path.name, "sha256": "", "size": 0})
    rows.sort(key=lambda row: str(row["name"]))
    return rows


def embedding_fingerprint(embedding: dict[str, Any]) -> dict[str, str]:
    return {
        "backend": str(embedding.get("backend") or "").strip().lower(),
        "model": str(embedding.get("model") or "").strip(),
    }


def build_manifest(
    companies: list[ListedCompany],
    *,
    source_paths: list[Path],
    embedding: dict[str, Any],
    dim: int,
) -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "sources": source_fingerprint(source_paths),
        "embedding": embedding_fingerprint(embedding),
        "slot_keys": list(SLOT_KEYS),
        "company_keys": [company_index_key(company) for company in companies],
        "n_companies": len(companies),
        "dim": dim,
    }


class ListedPeerIndex:
    def __init__(
        self,
        *,
        manifest: dict[str, Any],
        vectors_path: Path,
        present_path: Path,
    ) -> None:
        self.manifest = manifest
        self.n_companies = int(manifest["n_companies"])
        self.dim = int(manifest["dim"])
        self.slot_keys = tuple(manifest["slot_keys"])
        self._slot_index = {key: i for i, key in enumerate(self.slot_keys)}
        self._vector_fh = vectors_path.open("rb")
        self._present_fh = present_path.open("rb")
        try:
            self._mmap = mmap.mmap(self._vector_fh.fileno(), 0, access=mmap.ACCESS_READ)
            self._floats = memoryview(self._mmap).cast("f")
            self._present = self._present_fh.read()
            expected_present = self.n_companies * len(self.slot_keys)
            if len(self._present) != expected_present:
                raise ValueError("listed peer index present.bin 尺寸不匹配，需要重建")
            if len(self._floats) != expected_present * self.dim:
                raise ValueError("listed peer index vectors.bin 尺寸不匹配，需要重建")
        except Exception:
            self.close()
            raise

    def lookup(self, company_idx: int, slot: str) -> tuple[float, ...] | None:
        slot_idx = self._slot_index.get(slot)
        if slot_idx is None:
            return None
        pos = company_idx * len(self.slot_keys) + slot_idx
        if pos < 0 or pos >= len(self._present) or self._present[pos] == 0:
            return None
        start = pos * self.dim
        view = self._floats[start : start + self.dim]
        return tuple(float(value) for value in view)

    def close(self) -> None:
        floats = getattr(self, "_floats", None)
        if floats is not None:
            try:
                floats.release()
            except Exception:
                pass
            self._floats = None
        mapped = getattr(self, "_mmap", None)
        if mapped is not None:
            try:
                mapped.close()
            except Exception:
                pass
            self._mmap = None
        for handle_name in ("_vector_fh", "_present_fh"):
            handle = getattr(self, handle_name, None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                setattr(self, handle_name, None)

    def __enter__(self) -> ListedPeerIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _read_manifest(index_dir: Path) -> dict[str, Any] | None:
    path = index_dir / _MANIFEST
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _index_matches(
    manifest: dict[str, Any],
    companies: list[ListedCompany],
    *,
    source_paths: list[Path],
    embedding: dict[str, Any],
    index_dir: Path,
) -> bool:
    expected = build_manifest(
        companies,
        source_paths=source_paths,
        embedding=embedding,
        dim=int(manifest.get("dim") or 0),
    )
    for key in ("schema", "sources", "embedding", "slot_keys", "company_keys", "n_companies"):
        if manifest.get(key) != expected.get(key):
            return False
    vectors = index_dir / _VECTORS
    present = index_dir / _PRESENT
    if not vectors.is_file() or not present.is_file():
        return False
    dim = int(manifest.get("dim") or 0)
    if dim <= 0:
        return False
    n_slots = len(SLOT_KEYS)
    try:
        if vectors.stat().st_size != len(companies) * n_slots * dim * 4:
            return False
        if present.stat().st_size != len(companies) * n_slots:
            return False
    except OSError:
        return False
    return True


def _embed_unique(
    texts: list[str],
    embedder: Embedder,
    batch_size: int,
) -> dict[str, list[float]]:
    if not texts:
        return {}
    size = max(int(batch_size), 1)
    vectors: list[list[float]] = []
    total = len(texts)
    for start in range(0, total, size):
        chunk = texts[start : start + size]
        logger.info(
            "listed peer index embedding batch %s-%s / %s",
            start + 1,
            start + len(chunk),
            total,
        )
        part = embedder.embed(chunk)
        if len(part) != len(chunk):
            raise RuntimeError("Embedding 返回数量与请求不一致")
        vectors.extend(part)
    return dict(zip(texts, vectors, strict=True))


def _atomic_replace(src: Path, dst: Path, *, retries: int = 5, delay: float = 0.5) -> None:
    """os.replace with retry for Windows file-handle release lag."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _write_index(
    index_dir: Path,
    companies: list[ListedCompany],
    *,
    source_paths: list[Path],
    embedder: Embedder,
    embedding: dict[str, Any],
    batch_size: int,
) -> None:
    unique: list[str] = []
    seen: set[str] = set()
    for company in companies:
        for slot in SLOT_KEYS:
            text = slot_text(company, slot)
            if text and text not in seen:
                seen.add(text)
                unique.append(text)
    if not unique:
        raise ValueError("上市公司画像语料没有可嵌入的字段文本")

    by_text = _embed_unique(unique, embedder, batch_size)
    try:
        dim = len(next(iter(by_text.values())))
        if dim <= 0:
            raise RuntimeError("Embedding 向量维度无效")

        index_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = index_dir / f".tmp-{os.getpid()}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        vectors_tmp = tmp_dir / _VECTORS
        present_tmp = tmp_dir / _PRESENT
        manifest_tmp = tmp_dir / _MANIFEST
        present = bytearray()
        zero = b"\x00" * (dim * 4)
        try:
            with vectors_tmp.open("wb") as vec_fh:
                for company in companies:
                    for slot in SLOT_KEYS:
                        text = slot_text(company, slot)
                        if not text:
                            present.append(0)
                            vec_fh.write(zero)
                            continue
                        vector = by_text[text]
                        if len(vector) != dim:
                            raise RuntimeError("Embedding 向量维度不一致")
                        packed = array.array("f", (float(x) for x in vector))
                        packed.tofile(vec_fh)
                        present.append(1)
            present_tmp.write_bytes(bytes(present))
            manifest = build_manifest(
                companies,
                source_paths=source_paths,
                embedding=embedding,
                dim=dim,
            )
            manifest_tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _atomic_replace(vectors_tmp, index_dir / _VECTORS)
            _atomic_replace(present_tmp, index_dir / _PRESENT)
            _atomic_replace(manifest_tmp, index_dir / _MANIFEST)
            # All files moved successfully; clean up the now-empty temp dir.
            try:
                tmp_dir.rmdir()
            except OSError:
                pass
        except Exception:
            # On failure, preserve temp files for potential recovery
            # instead of deleting them (Windows may still hold locks).
            try:
                tmp_dir.rmdir()
            except OSError:
                pass
            raise
    finally:
        by_text.clear()


def open_or_build_index(
    index_dir: Path | str,
    companies: list[ListedCompany],
    *,
    source_paths: list[Path] | list[str] | None = None,
    embedder: Embedder,
    embedding: dict[str, Any],
    batch_size: int = 32,
) -> ListedPeerIndex:
    if not companies:
        raise ValueError("上市公司画像语料为空，无法构建 embedding 索引")
    dest = Path(index_dir)
    paths = [Path(p) for p in (source_paths or [])]
    with _LOCK:
        manifest = _read_manifest(dest)
        if manifest is None or not _index_matches(
            manifest,
            companies,
            source_paths=paths,
            embedding=embedding,
            index_dir=dest,
        ):
            logger.info(
                "building listed peer embedding index at %s (%s companies)",
                dest,
                len(companies),
            )
            _write_index(
                dest,
                companies,
                source_paths=paths,
                embedder=embedder,
                embedding=embedding,
                batch_size=batch_size,
            )
            manifest = _read_manifest(dest)
            if manifest is None:
                raise RuntimeError("listed peer index 写入后无法读取 manifest")
        else:
            logger.info("reusing listed peer embedding index at %s", dest)
        return ListedPeerIndex(
            manifest=manifest,
            vectors_path=dest / _VECTORS,
            present_path=dest / _PRESENT,
        )
