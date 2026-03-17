from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.snapshot_silver import build_snapshot_rows


class SnapshotSilverTestCase(unittest.TestCase):
    def test_build_snapshot_rows_generates_missing_annual_records(self) -> None:
        record = {
            "source": "CNINFO_SNAPSHOT",
            "company_name": "测试公司",
            "security_code": "000001",
            "exchange": "SZSE",
            "subindustry": "储能",
            "source_url": "https://www.cninfo.com.cn/new/snapshot/companyDetailCn?code=000001",
            "local_path": "data/raw/official/company_snapshots/SZSE/000001/company_snapshot.json",
            "publish_date": "2026-03-17",
            "report_type": "公司快照",
            "is_summary": False,
            "title": "巨潮资讯公司快照",
        }
        payload = {
            "finance_data": {
                "assetsData": [
                    {"index": "货币资金", "2024": 1000, "2023": 800},
                    {"index": "流动资产", "2024": 3000, "2023": 2800},
                    {"index": "总资产", "2024": 9000, "2023": 8500},
                    {"index": "流动负债", "2024": 1500, "2023": 1400},
                    {"index": "总负债", "2024": 4500, "2023": 4300},
                    {"index": "所有者权益", "2024": 4500, "2023": 4200},
                ],
                "profitsData": [
                    {"index": "营业收入", "2024": 6000, "2023": 5000},
                    {"index": "营业成本", "2024": 4200, "2023": 3600},
                    {"index": "利润总额", "2024": 700, "2023": 500},
                    {"index": "净利润", "2024": 560, "2023": 410},
                ],
                "cashFlowData": [
                    {"index": "经营活动产生的现金流量净额", "2024": 620, "2023": 390},
                ],
            }
        }

        rows = build_snapshot_rows(record, payload, existing_periods=set())

        self.assertEqual(len(rows), 2)
        current = rows[-1]
        self.assertEqual(current["report_period"], "2024FY")
        self.assertEqual(current["derived_metrics"]["G1"], 20.0)
        self.assertEqual(current["derived_metrics"]["P1"], 30.0)
        self.assertEqual(current["derived_metrics"]["C1"], round(620 / 560, 4))
        self.assertEqual(current["derived_metrics"]["S1"], 2.0)

    def test_build_snapshot_rows_skips_existing_periods(self) -> None:
        record = {
            "source": "CNINFO_SNAPSHOT",
            "company_name": "测试公司",
            "security_code": "000001",
            "exchange": "SZSE",
            "subindustry": "储能",
            "source_url": "https://www.cninfo.com.cn/new/snapshot/companyDetailCn?code=000001",
            "local_path": "data/raw/official/company_snapshots/SZSE/000001/company_snapshot.json",
            "publish_date": "2026-03-17",
            "report_type": "公司快照",
            "is_summary": False,
            "title": "巨潮资讯公司快照",
        }
        payload = {
            "finance_data": {
                "assetsData": [{"index": "总资产", "2024": 9000, "2023": 8500}],
                "profitsData": [
                    {"index": "营业收入", "2024": 6000, "2023": 5000},
                    {"index": "营业成本", "2024": 4200, "2023": 3600},
                    {"index": "利润总额", "2024": 700, "2023": 500},
                    {"index": "净利润", "2024": 560, "2023": 410},
                ],
                "cashFlowData": [{"index": "经营活动产生的现金流量净额", "2024": 620, "2023": 390}],
            }
        }

        rows = build_snapshot_rows(record, payload, existing_periods={("000001", "2024FY")})

        self.assertEqual([row["report_period"] for row in rows], ["2023FY"])


if __name__ == "__main__":
    unittest.main()
