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
        return None


class _StubSampleRepository:
    def __init__(self) -> None:
        self._row = {"company_name": "样本公司", "report_period": "2024Q3"}

    def list_companies(self, report_period: str | None = None) -> list[dict]:
        return [self._row]

    def list_company_names(self) -> list[str]:
        return [self._row["company_name"]]

    def list_company_periods(self, company_name: str) -> list[str]:
        return [self._row["report_period"]] if company_name == self._row["company_name"] else []

    def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
        if company_name != self._row["company_name"]:
            return None
        return self._row

    def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
        return self._row["company_name"] if self._row["company_name"] in query else None

    def get_evidence(self, chunk_id: str) -> dict | None:
        if chunk_id != "sample-1":
            return None
        return {"chunk_id": "sample-1", "company_name": self._row["company_name"]}


class HybridRepositoryTestCase(unittest.TestCase):
    def test_repository_does_not_fallback_to_sample_by_default(self) -> None:
        repository = HybridRepository(
            official_repository=_StubOfficialRepository(rows=[]),
            sample_repository=_StubSampleRepository(),
            fallback_enabled=False,
        )

        self.assertEqual(repository.list_companies(), [])
        self.assertEqual(repository.list_company_names(), [])
        self.assertIsNone(repository.get_company("样本公司"))
        self.assertIsNone(repository.find_company_from_query("帮我分析样本公司"))
        self.assertIsNone(repository.get_evidence("sample-1"))

    def test_repository_can_explicitly_fallback_to_sample(self) -> None:
        repository = HybridRepository(
            official_repository=_StubOfficialRepository(rows=[]),
            sample_repository=_StubSampleRepository(),
            fallback_enabled=True,
        )

        self.assertEqual(repository.list_companies()[0]["company_name"], "样本公司")
        self.assertIn("样本公司", repository.list_company_names())
        self.assertEqual(repository.get_company("样本公司")["report_period"], "2024Q3")
        self.assertEqual(repository.find_company_from_query("帮我分析样本公司"), "样本公司")
        self.assertEqual(repository.get_evidence("sample-1")["chunk_id"], "sample-1")


if __name__ == "__main__":
    unittest.main()
