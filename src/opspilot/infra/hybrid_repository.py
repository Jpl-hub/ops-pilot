from __future__ import annotations

from typing import Any


class HybridRepository:
    def __init__(
        self,
        official_repository: Any,
    ) -> None:
        self._official_repository = official_repository

    def list_companies(self, report_period: str | None = None) -> list[dict[str, Any]]:
        return self._official_repository.list_companies(report_period)

    def list_company_names(self) -> list[str]:
        return sorted(set(self._official_repository.list_company_names()))

    def list_company_periods(self, company_name: str) -> list[str]:
        periods = []
        if hasattr(self._official_repository, "list_company_periods"):
            periods.extend(self._official_repository.list_company_periods(company_name))
        deduped: list[str] = []
        for period in periods:
            if period not in deduped:
                deduped.append(period)
        return deduped

    def get_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any] | None:
        return self._official_repository.get_company(company_name, report_period)

    def find_company_from_query(
        self, query: str, report_period: str | None = None
    ) -> str | None:
        return self._official_repository.find_company_from_query(query, report_period)

    def preferred_period(self) -> str | None:
        return self._official_repository.preferred_period()

    def get_evidence(self, chunk_id: str) -> dict[str, Any] | None:
        return self._official_repository.get_evidence(chunk_id)

    def resolve_evidence(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        evidence = []
        for chunk_id in chunk_ids:
            item = self.get_evidence(chunk_id)
            if item is not None:
                evidence.append(item)
        return evidence

    def get_security_code(self, company_name: str) -> str | None:
        if hasattr(self._official_repository, "get_security_code"):
            return self._official_repository.get_security_code(company_name)
        return None

    async def hybrid_evidence_search(
        self,
        company_name: str,
        query: str,
        report_period: str | None,
        dsn: str,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Delegate to OfficialMetricsRepository's Hybrid RAG pipeline."""
        if hasattr(self._official_repository, "hybrid_evidence_search"):
            return await self._official_repository.hybrid_evidence_search(
                company_name, query, report_period, dsn, top_k
            )
        return []
