from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.infra.official_repository import OfficialMetricsRepository


class OfficialRepositoryTestCase(unittest.TestCase):
    def test_repository_prefers_latest_snapshot_and_exposes_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_root = root / "silver" / "official" / "manifests"
            silver_root.mkdir(parents=True, exist_ok=True)
            universe_path = root / "universe.json"

            universe_path.write_text(
                json.dumps(
                    [
                        {
                            "company_name": "测试公司",
                            "security_code": "000001",
                            "ticker": "000001.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            (silver_root / "financial_metrics_manifest.json").write_text(
                json.dumps(
                    {
                        "record_count": 2,
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2025年半年度报告",
                                "publish_date": "2025-08-20",
                                "report_period": "2025H1",
                                "report_id": "r1",
                                "summary_page": 8,
                                "summary_chunk_id": "r1-summary-page-008",
                                "summary_excerpt": "营业收入 100",
                                "source_url": "https://example.com/r1.pdf",
                                "local_path": "data/raw/r1.pdf",
                                "derived_metrics": {
                                    "G1": 25.0,
                                    "P2": 12.0,
                                    "C1": 1.2,
                                    "RAW_REVENUE": 10000000000.0,
                                    "RAW_NET_PROFIT": 1200000000.0,
                                },
                            },
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2025年三季度报告",
                                "publish_date": "2025-10-20",
                                "report_period": "2025Q3",
                                "report_id": "r2",
                                "summary_page": 9,
                                "summary_chunk_id": "r2-summary-page-009",
                                "summary_excerpt": "营业收入 180",
                                "source_url": "https://example.com/r2.pdf",
                                "local_path": "data/raw/r2.pdf",
                                "derived_metrics": {
                                    "G1": 40.0,
                                    "P2": 15.0,
                                    "C1": 1.4,
                                    "RAW_REVENUE": 18000000000.0,
                                    "RAW_NET_PROFIT": 2700000000.0,
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            repository = OfficialMetricsRepository(
                silver_root.parent,
                universe_path,
            )

            latest = repository.get_company("测试公司")
            self.assertIsNotNone(latest)
            self.assertEqual(latest["report_period"], "2025Q3")
            self.assertEqual(latest["metrics"]["G1"], 40.0)
            self.assertEqual(repository.preferred_period(), "2025Q3")

            evidence = repository.get_evidence("r2-summary-page-009")
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence["page"], 9)
            self.assertEqual(len(latest["history"]), 2)

    def test_repository_backfills_event_metrics_from_same_year_prior_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_root = root / "silver" / "official" / "manifests"
            silver_root.mkdir(parents=True, exist_ok=True)
            universe_path = root / "universe.json"

            universe_path.write_text(
                json.dumps(
                    [
                        {
                            "company_name": "测试公司",
                            "security_code": "000001",
                            "ticker": "000001.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                        {
                            "company_name": "对标公司",
                            "security_code": "000002",
                            "ticker": "000002.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            (silver_root / "financial_metrics_manifest.json").write_text(
                json.dumps(
                    {
                        "record_count": 3,
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2025年半年度报告",
                                "publish_date": "2025-08-20",
                                "report_period": "2025H1",
                                "report_id": "r1",
                                "summary_page": 8,
                                "summary_chunk_id": "r1-summary-page-008",
                                "summary_excerpt": "营业收入 100",
                                "source_url": "https://example.com/r1.pdf",
                                "local_path": "data/raw/r1.pdf",
                                "event_metric_evidence": {"I2": ["r1-event-i2-page-020"]},
                                "event_evidence": [
                                    {
                                        "chunk_id": "r1-event-i2-page-020",
                                        "metric_code": "I2",
                                        "page": 20,
                                        "excerpt": "半年报审计情况 □适用√不适用",
                                        "value": 0.0,
                                        "source_type": "official_event_page",
                                    }
                                ],
                                "derived_metrics": {
                                    "G1": 25.0,
                                    "I2": 0.0,
                                    "RAW_REVENUE": 10000000000.0,
                                    "RAW_NET_PROFIT": 1200000000.0,
                                },
                            },
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2025年三季度报告",
                                "publish_date": "2025-10-20",
                                "report_period": "2025Q3",
                                "report_id": "r2",
                                "summary_page": 9,
                                "summary_chunk_id": "r2-summary-page-009",
                                "summary_excerpt": "营业收入 180",
                                "source_url": "https://example.com/r2.pdf",
                                "local_path": "data/raw/r2.pdf",
                                "derived_metrics": {
                                    "G1": 40.0,
                                    "RAW_REVENUE": 18000000000.0,
                                    "RAW_NET_PROFIT": 2700000000.0,
                                },
                            },
                            {
                                "company_name": "对标公司",
                                "security_code": "000002",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "对标公司：2025年三季度报告",
                                "publish_date": "2025-10-20",
                                "report_period": "2025Q3",
                                "report_id": "r3",
                                "summary_page": 7,
                                "summary_chunk_id": "r3-summary-page-007",
                                "summary_excerpt": "营业收入 160",
                                "source_url": "https://example.com/r3.pdf",
                                "local_path": "data/raw/r3.pdf",
                                "derived_metrics": {
                                    "G1": 30.0,
                                    "I2": 0.0,
                                    "RAW_REVENUE": 16000000000.0,
                                    "RAW_NET_PROFIT": 2000000000.0,
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            repository = OfficialMetricsRepository(
                silver_root.parent,
                universe_path,
            )

            latest = repository.get_company("测试公司", "2025Q3")
            self.assertIsNotNone(latest)
            self.assertEqual(latest["metrics"]["I2"], 0.0)
            self.assertEqual(latest["metric_evidence"]["I2"], ["r1-event-i2-page-020"])
            self.assertEqual(latest["label_evidence"]["R6"], ["r1-event-i2-page-020"])
            evidence = repository.get_evidence("r1-event-i2-page-020")
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence["page"], 20)

    def test_repository_exposes_formula_metric_evidence_for_c3_and_s3(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_root = root / "silver" / "official" / "manifests"
            silver_root.mkdir(parents=True, exist_ok=True)
            universe_path = root / "universe.json"

            universe_path.write_text(
                json.dumps(
                    [
                        {
                            "company_name": "测试公司",
                            "security_code": "000001",
                            "ticker": "000001.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                        {
                            "company_name": "对标公司",
                            "security_code": "000002",
                            "ticker": "000002.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            (silver_root / "financial_metrics_manifest.json").write_text(
                json.dumps(
                    {
                        "record_count": 3,
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2024年三季度报告",
                                "publish_date": "2024-10-20",
                                "report_period": "2024Q3",
                                "report_id": "r1",
                                "summary_page": 9,
                                "summary_chunk_id": "r1-summary-page-009",
                                "summary_excerpt": "营业收入 150",
                                "source_url": "https://example.com/r1.pdf",
                                "local_path": "data/raw/r1.pdf",
                                "field_evidence": {
                                    "accounts_receivable": {
                                        "chunk_id": "r1-field-accounts_receivable-page-015",
                                        "field": "accounts_receivable",
                                        "page": 15,
                                        "excerpt": "应收账款 80.0",
                                        "source_type": "official_statement_page",
                                    }
                                },
                                "derived_metrics": {
                                    "G1": 12.0,
                                    "RAW_REVENUE": 150.0,
                                    "RAW_ACCOUNTS_RECEIVABLE": 80.0,
                                },
                            },
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "测试公司：2025年三季度报告",
                                "publish_date": "2025-10-20",
                                "report_period": "2025Q3",
                                "report_id": "r2",
                                "summary_page": 8,
                                "summary_chunk_id": "r2-summary-page-008",
                                "summary_excerpt": "营业收入 180",
                                "source_url": "https://example.com/r2.pdf",
                                "local_path": "data/raw/r2.pdf",
                                "field_evidence": {
                                    "accounts_receivable": {
                                        "chunk_id": "r2-field-accounts_receivable-page-016",
                                        "field": "accounts_receivable",
                                        "page": 16,
                                        "excerpt": "应收账款 100.0",
                                        "source_type": "official_statement_page",
                                    },
                                    "profit_total": {
                                        "chunk_id": "r2-field-profit_total-page-011",
                                        "field": "profit_total",
                                        "page": 11,
                                        "excerpt": "利润总额 300.0",
                                        "source_type": "official_statement_page",
                                    },
                                    "interest_expense": {
                                        "chunk_id": "r2-field-interest_expense-page-011",
                                        "field": "interest_expense",
                                        "page": 11,
                                        "excerpt": "利息费用 50.0",
                                        "source_type": "official_statement_page",
                                    },
                                },
                                "facts": {
                                    "interest_expense": {
                                        "current": 50.0,
                                        "previous": 40.0,
                                        "change_pct": None,
                                        "tokens": [],
                                    }
                                },
                                "derived_metrics": {
                                    "G1": 15.0,
                                    "C3": 10.0,
                                    "S3": 7.0,
                                    "RAW_REVENUE": 180.0,
                                    "RAW_ACCOUNTS_RECEIVABLE": 100.0,
                                },
                            },
                            {
                                "company_name": "对标公司",
                                "security_code": "000002",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "对标公司：2025年三季度报告",
                                "publish_date": "2025-10-20",
                                "report_period": "2025Q3",
                                "report_id": "r3",
                                "summary_page": 7,
                                "summary_chunk_id": "r3-summary-page-007",
                                "summary_excerpt": "营业收入 160",
                                "source_url": "https://example.com/r3.pdf",
                                "local_path": "data/raw/r3.pdf",
                                "derived_metrics": {
                                    "G1": 12.0,
                                    "C3": 0.0,
                                    "S3": 4.0,
                                    "RAW_REVENUE": 160.0,
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            repository = OfficialMetricsRepository(silver_root.parent, universe_path)
            latest = repository.get_company("测试公司", "2025Q3")
            self.assertEqual(
                latest["metric_evidence"]["C3"],
                [
                    "r2-field-accounts_receivable-page-016",
                    "r2-summary-page-008",
                    "r1-field-accounts_receivable-page-015",
                ],
            )
            self.assertEqual(
                latest["metric_evidence"]["S3"],
                [
                    "r2-field-profit_total-page-011",
                    "r2-field-interest_expense-page-011",
                ],
            )
            self.assertEqual(latest["formula_context"]["C3"]["prior_period"], "2024Q3")
            self.assertEqual(latest["formula_context"]["S3"]["interest_expense"], 50.0)
            c3_evidence = repository.get_evidence("r2-field-accounts_receivable-page-016")
            self.assertIsNotNone(c3_evidence)
            self.assertEqual(c3_evidence["page"], 16)

    def test_repository_preferred_period_skips_sparse_future_period(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            silver_root = root / "silver" / "official" / "manifests"
            silver_root.mkdir(parents=True, exist_ok=True)
            universe_path = root / "universe.json"

            universe_path.write_text(
                json.dumps(
                    [
                        {
                            "company_name": "甲公司",
                            "security_code": "000001",
                            "ticker": "000001.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                        {
                            "company_name": "乙公司",
                            "security_code": "000002",
                            "ticker": "000002.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                        {
                            "company_name": "丙公司",
                            "security_code": "000003",
                            "ticker": "000003.SZ",
                            "exchange": "SZSE",
                            "subindustry": "储能",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            records = [
                {
                    "company_name": "甲公司",
                    "security_code": "000001",
                    "exchange": "SZSE",
                    "subindustry": "储能",
                    "title": "甲公司：2025年年度报告",
                    "publish_date": "2026-03-01",
                    "report_period": "2025FY",
                    "report_id": "r1",
                    "summary_page": 1,
                    "summary_chunk_id": "r1-summary-page-001",
                    "summary_excerpt": "摘要",
                    "source_url": "https://example.com/r1.pdf",
                    "local_path": "data/raw/r1.pdf",
                    "derived_metrics": {"G1": 10.0, "RAW_REVENUE": 10.0, "RAW_NET_PROFIT": 1.0},
                },
                {
                    "company_name": "甲公司",
                    "security_code": "000001",
                    "exchange": "SZSE",
                    "subindustry": "储能",
                    "title": "甲公司：2025年三季度报告",
                    "publish_date": "2025-10-20",
                    "report_period": "2025Q3",
                    "report_id": "r2",
                    "summary_page": 1,
                    "summary_chunk_id": "r2-summary-page-001",
                    "summary_excerpt": "摘要",
                    "source_url": "https://example.com/r2.pdf",
                    "local_path": "data/raw/r2.pdf",
                    "derived_metrics": {"G1": 10.0, "RAW_REVENUE": 10.0, "RAW_NET_PROFIT": 1.0},
                },
                {
                    "company_name": "乙公司",
                    "security_code": "000002",
                    "exchange": "SZSE",
                    "subindustry": "储能",
                    "title": "乙公司：2025年三季度报告",
                    "publish_date": "2025-10-20",
                    "report_period": "2025Q3",
                    "report_id": "r3",
                    "summary_page": 1,
                    "summary_chunk_id": "r3-summary-page-001",
                    "summary_excerpt": "摘要",
                    "source_url": "https://example.com/r3.pdf",
                    "local_path": "data/raw/r3.pdf",
                    "derived_metrics": {"G1": 12.0, "RAW_REVENUE": 12.0, "RAW_NET_PROFIT": 1.2},
                },
                {
                    "company_name": "丙公司",
                    "security_code": "000003",
                    "exchange": "SZSE",
                    "subindustry": "储能",
                    "title": "丙公司：2025年三季度报告",
                    "publish_date": "2025-10-20",
                    "report_period": "2025Q3",
                    "report_id": "r4",
                    "summary_page": 1,
                    "summary_chunk_id": "r4-summary-page-001",
                    "summary_excerpt": "摘要",
                    "source_url": "https://example.com/r4.pdf",
                    "local_path": "data/raw/r4.pdf",
                    "derived_metrics": {"G1": 14.0, "RAW_REVENUE": 14.0, "RAW_NET_PROFIT": 1.4},
                },
            ]

            (silver_root / "financial_metrics_manifest.json").write_text(
                json.dumps({"record_count": len(records), "records": records}, ensure_ascii=False),
                encoding="utf-8",
            )

            repository = OfficialMetricsRepository(silver_root.parent, universe_path)
            self.assertEqual(repository.preferred_period(), "2025Q3")


if __name__ == "__main__":
    unittest.main()
