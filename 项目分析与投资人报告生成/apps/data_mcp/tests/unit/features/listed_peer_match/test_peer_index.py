"""上市公司语料 embedding 索引：启动/Excel 变更时落盘，检索不再全量重算。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tests.support  # noqa: F401
from data_mcp.features.listed_peer_match.corpus import ListedCompany
from data_mcp.features.listed_peer_match.index import open_or_build_index
from data_mcp.features.listed_peer_match.retrieval import retrieve
from data_mcp.features.listed_peer_match.service import (
    match_listed_peers,
    warmup_listed_peer_index,
)
from data_mcp.features.listed_peer_match.weights import DEFAULT_FIELD_WEIGHTS
from data_mcp.shared.settings import load_listed_peer_match_config
from data_mcp.shared.vector import HashEmbedder

_EMBEDDING = {"backend": "hash", "url": "", "model": "hash-64"}


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._inner = HashEmbedder()

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return self._inner.embed(texts)

    @property
    def texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


class ListedPeerIndexTests(unittest.TestCase):
    def test_second_open_reuses_disk_and_skips_corpus_embed(self) -> None:
        companies = [
            ListedCompany("1", "宁德时代", fields={"products_services": "动力电池"}),
            ListedCompany("2", "平安银行", fields={"products_services": "对公贷款"}),
        ]
        embedder = _RecordingEmbedder()
        with TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            first = open_or_build_index(
                index_dir,
                companies,
                source_paths=[],
                embedder=embedder,
                embedding=_EMBEDDING,
            )
            first.close()
            built = list(embedder.texts)
            self.assertIn("动力电池", built)
            self.assertIn("对公贷款", built)

            reused = open_or_build_index(
                index_dir,
                companies,
                source_paths=[],
                embedder=embedder,
                embedding=_EMBEDDING,
            )
            try:
                self.assertEqual(embedder.texts, built)
                vec = reused.lookup(0, "products_services")
                self.assertIsNotNone(vec)
                self.assertEqual(len(vec), 64)
            finally:
                reused.close()

    def test_rebuilds_when_source_file_hash_changes(self) -> None:
        companies = [
            ListedCompany("1", "A", fields={"products_services": "动力电池"}),
        ]
        embedder = _RecordingEmbedder()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = root / "companies.xlsx"
            excel.write_bytes(b"version-one")
            index_dir = root / "index"
            first = open_or_build_index(
                index_dir,
                companies,
                source_paths=[excel],
                embedder=embedder,
                embedding=_EMBEDDING,
            )
            first.close()
            after_build = len(embedder.texts)

            excel.write_bytes(b"version-two")
            second = open_or_build_index(
                index_dir,
                companies,
                source_paths=[excel],
                embedder=embedder,
                embedding=_EMBEDDING,
            )
            second.close()
            self.assertGreater(len(embedder.texts), after_build)

    def test_rebuilds_when_embedding_model_changes(self) -> None:
        companies = [
            ListedCompany("1", "A", fields={"products_services": "动力电池"}),
        ]
        embedder = _RecordingEmbedder()
        with TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            first = open_or_build_index(
                index_dir,
                companies,
                source_paths=[],
                embedder=embedder,
                embedding=_EMBEDDING,
            )
            first.close()
            after_build = len(embedder.texts)
            second = open_or_build_index(
                index_dir,
                companies,
                source_paths=[],
                embedder=embedder,
                embedding={**_EMBEDDING, "model": "other-model"},
            )
            second.close()
            self.assertGreater(len(embedder.texts), after_build)

    def test_retrieve_embeds_queries_only_after_index_exists(self) -> None:
        companies = [
            ListedCompany(
                "1",
                "银行",
                industry="银行业",
                fields={"products_services": "融资贷款"},
            ),
            ListedCompany(
                "2",
                "芯片",
                industry="半导体",
                fields={"products_services": "集成电路"},
            ),
        ]
        embedder = _RecordingEmbedder()
        with TemporaryDirectory() as tmp:
            with open_or_build_index(
                Path(tmp),
                companies,
                source_paths=[],
                embedder=embedder,
                embedding=_EMBEDDING,
            ) as index:
                corpus_n = len(embedder.texts)
                rows = retrieve(
                    ["半导体"],
                    "面向小微的数字化信贷",
                    companies,
                    DEFAULT_FIELD_WEIGHTS,
                    embedder,
                    2,
                    index=index,
                )
                self.assertEqual(len(rows), 2)
                query_texts = embedder.texts[corpus_n:]
                self.assertTrue(query_texts)
                self.assertNotIn("融资贷款", query_texts)
                self.assertNotIn("集成电路", query_texts)
                self.assertIn("面向小微的数字化信贷", query_texts)

    def test_match_reuses_index_across_calls(self) -> None:
        companies = [
            ListedCompany("bank", "银行", fields={"products_services": "小微贷款"}),
            ListedCompany("other", "包装", fields={"products_services": "创意包装"}),
        ]
        embedder = _RecordingEmbedder()
        with TemporaryDirectory() as tmp:
            cfg = load_listed_peer_match_config()
            cfg = dict(cfg)
            cfg.update(enable_rerank=False, top_k_recall=2, index_dir=tmp)
            cfg["embedding"] = dict(cfg["embedding"])
            cfg["embedding"]["backend"] = "hash"
            base = "data_mcp.features.listed_peer_match.service."
            with (
                patch(base + "load_listed_peer_match_config", return_value=cfg),
                patch(
                    base + "load_listed_corpus_dir",
                    return_value=(companies, ["sample.xlsx"]),
                ),
                patch(base + "build_embedder", return_value=embedder),
            ):
                first = match_listed_peers(["包装"], "小微信贷", top_n=5)
                after_first = len(embedder.texts)
                second = match_listed_peers(["包装"], "小微信贷", top_n=5)
            self.assertEqual(
                {p["证券代码"] for p in first["peers"]},
                {"bank", "other"},
            )
            self.assertEqual(
                {p["证券代码"] for p in second["peers"]},
                {"bank", "other"},
            )
            extra = embedder.texts[after_first:]
            self.assertTrue(extra)
            self.assertNotIn("小微贷款", extra)
            self.assertNotIn("创意包装", extra)

    def test_warmup_does_not_raise_when_corpus_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            cfg = load_listed_peer_match_config()
            cfg = dict(cfg)
            cfg["data_dir"] = str(Path(tmp) / "missing-corpus")
            cfg["index_dir"] = str(Path(tmp) / "index")
            with patch(
                "data_mcp.features.listed_peer_match.service.load_listed_peer_match_config",
                return_value=cfg,
            ):
                warmup_listed_peer_index()


if __name__ == "__main__":
    unittest.main()
