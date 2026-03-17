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


if __name__ == "__main__":
    unittest.main()
