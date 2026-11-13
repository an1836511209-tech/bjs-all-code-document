"""上市公司可比匹配：权重校验与基础计分单元测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

import tests.support  # noqa: F401
from data_mcp.features.listed_peer_match.corpus import (
    ListedCompany,
    load_listed_corpus,
    load_listed_corpus_dir,
)
from data_mcp.features.listed_peer_match.matcher import (
    ScoredPeer,
    build_query_text,
    peer_to_dict,
    score_companies,
)
from data_mcp.features.listed_peer_match.weights import (
    DEFAULT_FIELD_WEIGHTS,
    validate_field_weights,
)
from data_mcp.shared.settings import DATA_MCP_ROOT, load_listed_peer_match_config
from data_mcp.shared.vector import HashEmbedder, cosine_similarity
from tests.support import DATA_FIXTURES


class WeightValidationTests(unittest.TestCase):
    def test_default_weights_ok(self) -> None:
        w = validate_field_weights(DEFAULT_FIELD_WEIGHTS)
        self.assertAlmostEqual(
            w["industry_chain_position"] + w["products_services"],
            0.75,
        )
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_rejects_chain_below_75(self) -> None:
        bad = {
            "industry_chain_position": 0.30,
            "products_services": 0.30,
            "track_tags": 0.20,
            "target_customers": 0.10,
            "profit_model": 0.10,
        }
        with self.assertRaises(ValueError) as ctx:
            validate_field_weights(bad)
        self.assertIn("0.75", str(ctx.exception))

    def test_config_loads(self) -> None:
        cfg = load_listed_peer_match_config()
        self.assertIn(cfg["env"], ("dev", "uat", "prod"))
        self.assertEqual(cfg["embedding"]["backend"], "hash")
        self.assertEqual(cfg["data_dir"], "tests/fixtures/data/listed_peers")
        self.assertTrue(cfg["index_dir"])
        self.assertIn("listed_peer_index", Path(cfg["index_dir"]).as_posix())
        self.assertEqual(cfg["embedding"]["batch_size"], 32)
        self.assertAlmostEqual(
            cfg["field_weights"]["industry_chain_position"]
            + cfg["field_weights"]["products_services"],
            0.75,
        )

    def test_embedding_env_blocks(self) -> None:
        dev = load_listed_peer_match_config("dev")
        uat = load_listed_peer_match_config("uat")
        self.assertEqual(
            dev["embedding"]["url"],
            "https://qwen3emb.agentspro.cn/v1/embeddings",
        )
        self.assertEqual(uat["embedding"]["url"], "http://10.224.98.172/v1/embeddings")
        self.assertEqual(
            dev["rerank"]["url"],
            "https://qwen3rerank.agentspro.cn/v1/rerank",
        )
        self.assertEqual(uat["rerank"]["url"], "http://10.224.98.172/v1/rerank")
        self.assertTrue(dev["embedding"]["api_key"])
        self.assertTrue(dev["rerank"]["api_key"])
        self.assertFalse(dev["embedding"]["api_key"].startswith("Bearer"))


class CorpusAndMatchTests(unittest.TestCase):
    def test_load_dir_skips_subfolders_and_loads_root_xlsx(self) -> None:
        data_dir = DATA_MCP_ROOT.parent.parent / "resources/reference_data/data_mcp/listed_peers"
        companies, sources = load_listed_corpus_dir(data_dir, display_dir="reference_data")
        self.assertGreaterEqual(len(companies), 1)
        self.assertTrue(sources)
        self.assertTrue(all("/" not in s and "\\" not in s for s in sources))
        self.assertEqual(sources, ["companies.xlsx"])

    def test_load_real_sample_from_dir(self) -> None:
        companies, _ = load_listed_corpus_dir(
            DATA_MCP_ROOT.parent.parent / "resources/reference_data/data_mcp/listed_peers",
            display_dir="reference_data",
        )
        self.assertGreaterEqual(len(companies), 1)
        # 新语料首行应为北交所样本
        codes = {c.security_code for c in companies}
        self.assertTrue(any(c.endswith(".BJ") or c.endswith(".SZ") or c.endswith(".SH") for c in codes))

    def test_load_single_mock_file(self) -> None:
        path = DATA_FIXTURES / "listed_peers" / "companies.xlsx"
        companies = load_listed_corpus(path)
        self.assertEqual(len(companies), 3)
        self.assertIn("平安银行", {c.security_name for c in companies})
        self.assertTrue(all(c.source_file == "companies.xlsx" for c in companies))

    def test_missing_dir_message_is_actionable(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            load_listed_corpus_dir(
                DATA_FIXTURES / "listed_peers" / "no_such_dir",
                display_dir="fixtures/no_such_dir",
            )
        msg = str(ctx.exception)
        self.assertIn("上市公司画像目录不存在", msg)
        self.assertIn("listed_peer_match.data_dir", msg)

    def test_query_builder(self) -> None:
        self.assertEqual(build_query_text(["科技金融"], ""), "科技金融")
        self.assertIn("摘要", build_query_text(["科技金融"], "摘要内容"))

    def test_score_with_hash_embedder(self) -> None:
        company = ListedCompany(
            security_code="000001.SZ",
            security_name="平安银行",
            industry="金融业",
            track_tags_raw="银行业、科技金融",
            fields={
                "track_tags": "银行业、科技金融",
                "industry_chain_position": "金融产业链核心环节，服务实体经济",
                "products_services": "贷款、存款、财富管理、科技金融产品",
                "target_customers": "个人与小微企业",
                "profit_model": "净息差与手续费",
            },
        )
        weights = validate_field_weights(DEFAULT_FIELD_WEIGHTS)
        peers = score_companies(
            "科技金融 普惠信贷",
            [company],
            weights,
            HashEmbedder(),
        )
        self.assertEqual(len(peers), 1)
        self.assertIn("industry_chain_position", peers[0].field_scores)
        self.assertIn("products_services", peers[0].evidence)
        self.assertGreaterEqual(peers[0].score, 0.0)
        self.assertLessEqual(peers[0].score, 1.0)

    def test_cosine_range(self) -> None:
        a = HashEmbedder().embed(["abc"])[0]
        b = HashEmbedder().embed(["abc"])[0]
        self.assertAlmostEqual(cosine_similarity(a, b), 1.0, places=5)


class PeerToDictChineseKeysTests(unittest.TestCase):
    def test_peer_to_dict_flattens_chinese_business_keys(self) -> None:
        company = ListedCompany(
            security_code="000001.SZ",
            security_name="平安银行",
            company_name_cn="平安银行股份有限公司",
            industry="金融业",
            track_tags_raw="银行业",
            fields={"products_services": "贷款"},
            valuation={
                "pe_ttm": 5.1291,
                "pb_lf": 0.5227,
                "ps_ttm": 1.5969,
                "revenue": 131442000000.0,
                "net_profit": 42633000000.0,
            },
        )
        peer = ScoredPeer(
            company=company,
            score=0.5,
            field_scores={"products_services": 0.5},
            missing_fields=[],
            evidence={"products_services": "贷款"},
        )
        row = peer_to_dict(peer, high=0.8, medium=0.4)
        self.assertEqual(row["证券代码"], "000001.SZ")
        self.assertEqual(row["证券名称"], "平安银行")
        self.assertEqual(row["公司中文名称"], "平安银行股份有限公司")
        self.assertEqual(row["PE"], 5.1291)
        self.assertEqual(row["PB(LF)"], 0.5227)
        self.assertEqual(row["PS(TTM)"], 1.5969)
        self.assertEqual(row["营业收入"], 131442000000.0)
        self.assertEqual(row["净利润"], 42633000000.0)
        self.assertNotIn("security_code", row)
        self.assertNotIn("security_name", row)
        self.assertNotIn("company_name_cn", row)
        self.assertNotIn("valuation", row)
        self.assertEqual(row["industry"], "金融业")
        self.assertEqual(row["score"], 0.5)
        self.assertEqual(row["citations"][0]["source_type"], "listed_peer_corpus")
        self.assertEqual(row["citations"][0]["source_name"], "上市公司画像语料")
        self.assertEqual(row["citations"][0]["source_url"], "")
        self.assertIn("000001.SZ", row["citations"][0]["quote"])
        self.assertIn("平安银行", row["citations"][0]["quote"])
        self.assertIn("5.1291", row["citations"][0]["quote"])
        self.assertIn("贷款", row["citations"][0]["quote"])

    def test_peer_to_dict_uses_excel_filename_as_citation_source(self) -> None:
        company = ListedCompany(
            security_code="300750.SZ",
            security_name="宁德时代",
            fields={"products_services": "动力电池"},
            source_file="companies.xlsx",
        )
        peer = ScoredPeer(
            company=company,
            score=0.4,
            field_scores={},
            missing_fields=[],
            evidence={"products_services": "动力电池"},
        )
        row = peer_to_dict(peer, high=0.8, medium=0.4)
        self.assertEqual(len(row["citations"]), 1)
        self.assertEqual(row["citations"][0]["source_name"], "companies.xlsx")
        self.assertIn("动力电池", row["citations"][0]["quote"])

    def test_peer_to_dict_null_valuation_when_missing(self) -> None:
        company = ListedCompany(security_code="1", security_name="X", valuation={})
        peer = ScoredPeer(
            company=company,
            score=0.1,
            field_scores={},
            missing_fields=[],
            evidence={},
        )
        row = peer_to_dict(peer, high=0.8, medium=0.4)
        self.assertIsNone(row["PE"])
        self.assertIsNone(row["PB(LF)"])
        self.assertIsNone(row["PS(TTM)"])
        self.assertIsNone(row["营业收入"])
        self.assertIsNone(row["净利润"])


if __name__ == "__main__":
    unittest.main()
