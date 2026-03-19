from __future__ import annotations

from typing import Any


class HybridRepository:
    def __init__(self, official_repository: Any, sample_repository: Any) -> None:
        self._official_repository = official_repository
        self._sample_repository = sample_repository

    def list_companies(self, report_period: str | None = None) -> list[dict[str, Any]]:
        official_rows = self._official_repository.list_companies(report_period)
        if official_rows:
            return official_rows
        return self._sample_repository.list_companies(report_period)

    def list_company_names(self) -> list[str]:
        names = set(self._sample_repository.list_company_names())
        names.update(self._official_repository.list_company_names())
        return sorted(names)

    def list_company_periods(self, company_name: str) -> list[str]:
        periods = []
        if hasattr(self._official_repository, "list_company_periods"):
            periods.extend(self._official_repository.list_company_periods(company_name))
        if hasattr(self._sample_repository, "list_company_periods"):
            periods.extend(self._sample_repository.list_company_periods(company_name))
        deduped: list[str] = []
        for period in periods:
            if period not in deduped:
                deduped.append(period)
        return deduped

    def get_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any] | None:
        company = self._official_repository.get_company(company_name, report_period)
        if company is not None:
            return company
        return self._sample_repository.get_company(company_name, report_period)

    def find_company_from_query(
        self, query: str, report_period: str | None = None
    ) -> str | None:
        company_name = self._official_repository.find_company_from_query(query, report_period)
        if company_name is not None:
            return company_name
        return self._sample_repository.find_company_from_query(query, report_period)

    def preferred_period(self) -> str | None:
        return self._official_repository.preferred_period()

    def get_evidence(self, chunk_id: str) -> dict[str, Any] | None:
        evidence = self._official_repository.get_evidence(chunk_id)
        if evidence is not None:
            return evidence
        return self._sample_repository.get_evidence(chunk_id)

    def resolve_evidence(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        evidence = []
        for chunk_id in chunk_ids:
            item = self.get_evidence(chunk_id)
            if item is not None:
                evidence.append(item)
        return evidence
