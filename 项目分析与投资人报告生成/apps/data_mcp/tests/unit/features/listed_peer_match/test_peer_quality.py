from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import tests.support  # noqa: F401
from data_mcp.features.listed_peer_match.corpus import ListedCompany
from data_mcp.features.listed_peer_match.lexical import business_hits, query_terms
from data_mcp.features.listed_peer_match.rerank import HttpReranker, _clamp01
from data_mcp.features.listed_peer_match.service import match_listed_peers
from data_mcp.features.listed_peer_match.weights import DEFAULT_FIELD_WEIGHTS
from data_mcp.shared.http.errors import ExternalServiceError
from data_mcp.shared.settings import load_listed_peer_match_config
from data_mcp.shared.vector import HashEmbedder


class PeerQualityTests(unittest.TestCase):
    def test_business_evidence_ignores_wrong_tags(self) -> None:
        terms = query_terms("面向小微的数字化信贷")
        bank = ListedCompany("bank", "银行", fields={"target_customers": "小微企业"})
        other = ListedCompany(
            "other",
            "招标",
            fields={"track_tags": "小微信贷", "products_services": "数字化招标服务"},
        )
        self.assertEqual(business_hits(bank, terms), {"小微"})
        self.assertFalse(business_hits(other, terms))
        self.assertFalse(query_terms("数字化服务平台"))

    def test_conflicting_channels_remain_unverified_candidates(self) -> None:
        cfg = load_listed_peer_match_config()
        companies = [
            ListedCompany("bank", "银行", fields={"products_services": "小微贷款"}),
            ListedCompany("other", "包装", fields={"products_services": "创意包装"}),
        ]
        embedder = Mock()
        # 索引构建只 embed 字段；检索再 embed 摘要/标签查询。
        embedder.embed.side_effect = [
            [[1.0, 0.0], [0.0, 1.0]],
            [[1.0, 0.0]],
            [[0.0, 1.0]],
        ]
        base = "data_mcp.features.listed_peer_match.service."
        with TemporaryDirectory() as tmp:
            cfg.update(require_business_overlap=True, enable_rerank=False, top_k_recall=1)
            cfg["index_dir"] = tmp
            with (
                patch(base + "load_listed_peer_match_config", return_value=cfg),
                patch(base + "load_listed_corpus_dir", return_value=(companies, ["sample.xlsx"])),
                patch(base + "build_embedder", return_value=embedder),
            ):
                result = match_listed_peers(["包装"], "小微信贷", top_n=5)
        self.assertEqual({p["证券代码"] for p in result["peers"]}, {"bank", "other"})
        self.assertTrue(
            all(
                p["assessment_status"] == "not_assessed" and p["confidence"] == "low"
                for p in result["peers"]
            )
        )

    def test_no_overlap_does_not_delete_semantic_candidates(self) -> None:
        from data_mcp.features.listed_peer_match.index import open_or_build_index
        from data_mcp.features.listed_peer_match.retrieval import retrieve

        embedder = HashEmbedder()
        companies = [
            ListedCompany("1", "银行", industry="银行业", fields={"products_services": "融资贷款"}),
            ListedCompany("2", "芯片", industry="半导体", fields={"products_services": "集成电路"}),
        ]
        with TemporaryDirectory() as tmp:
            with open_or_build_index(
                Path(tmp),
                companies,
                source_paths=[],
                embedder=embedder,
                embedding={"backend": "hash", "url": "", "model": "hash-64"},
            ) as index:
                for summary in ["", "该公司开发火箭", "面向小微的数字化信贷", "为客户提供服务" * 100]:
                    rows = retrieve(
                        ["半导体"],
                        summary,
                        companies,
                        DEFAULT_FIELD_WEIGHTS,
                        embedder,
                        2,
                        index=index,
                    )
                    self.assertEqual(len(rows), 2)
                    self.assertTrue(all("tags" in row[2] for row in rows))
                    self.assertEqual(
                        rows,
                        retrieve(
                            ["半导体"],
                            summary,
                            companies,
                            DEFAULT_FIELD_WEIGHTS,
                            embedder,
                            2,
                            index=index,
                        ),
                    )
        self.assertNotIn("开发", query_terms("该公司开发火箭"))

    def test_reranker_response_indices_and_validation(self) -> None:
        response = Mock()
        reranker = HttpReranker("http://unused")
        target = "data_mcp.features.listed_peer_match.rerank.http_request"
        response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.2},
                {"index": 0, "relevance_score": 0.8},
            ]
        }
        with patch(target, return_value=response):
            self.assertEqual(reranker.rerank("query", ["a", "b"]), [0.8, 0.2])
            response.json.return_value = {"results": [{"index": 0, "relevance_score": 0.8}]}
            with self.assertRaises(ExternalServiceError):
                reranker.rerank("query", ["a", "b"])
            response.json.return_value = {
                "results": [
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }
            with self.assertRaises(ExternalServiceError):
                reranker.rerank("query", ["a", "b"])
        for value in [float("nan"), float("inf"), -1, 2]:
            with self.assertRaises(ExternalServiceError):
                _clamp01(value)


if __name__ == "__main__":
    unittest.main()
