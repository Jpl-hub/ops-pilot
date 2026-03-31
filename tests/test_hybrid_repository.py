from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.infra.hybrid_repository import HybridRepository


class _StubOfficialRepository:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def list_companies(self, report_period: str | None = None) -> list[dict]:
        return list(self._rows)

    def list_company_names(self) -> list[str]:
        return [row["company_name"] for row in self._rows]

    def list_company_periods(self, company_name: str) -> list[str]:
        return [row["report_period"] for row in self._rows if row["company_name"] == company_name]

    def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
        for row in self._rows:
            if row["company_name"] == company_name and (
                report_period is None or row["report_period"] == report_period
            ):
                return row
        return None

    def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
        for row in self._rows:
            if row["company_name"] in query:
                return row["company_name"]
        return None

    def preferred_period(self) -> str | None:
        return self._rows[0]["report_period"] if self._rows else None

    def get_evidence(self, chunk_id: str) -> dict | None:
        if chunk_id != "official-1":
            return None
        return {"chunk_id": "official-1", "company_name": "正式公司"}


class HybridRepositoryTestCase(unittest.TestCase):
    def test_repository_delegates_to_official_repository(self) -> None:
        repository = HybridRepository(
            official_repository=_StubOfficialRepository(
                rows=[{"company_name": "正式公司", "report_period": "2025Q3"}]
            ),
        )

        self.assertEqual(repository.list_companies()[0]["company_name"], "正式公司")
        self.assertEqual(repository.list_company_names(), ["正式公司"])
        self.assertEqual(repository.get_company("正式公司")["report_period"], "2025Q3")
        self.assertEqual(repository.find_company_from_query("帮我分析正式公司"), "正式公司")
        self.assertEqual(repository.get_evidence("official-1")["chunk_id"], "official-1")

    def test_repository_deduplicates_periods(self) -> None:
        repository = HybridRepository(
            official_repository=_StubOfficialRepository(
                rows=[
                    {"company_name": "正式公司", "report_period": "2025Q3"},
                    {"company_name": "正式公司", "report_period": "2025Q3"},
                    {"company_name": "正式公司", "report_period": "2024FY"},
                ]
            ),
        )

        self.assertEqual(repository.list_company_periods("正式公司"), ["2025Q3", "2024FY"])


if __name__ == "__main__":
    unittest.main()
