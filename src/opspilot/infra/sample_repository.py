from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class SampleRepository:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._companies = self._load_json("companies.json")
        self._evidence = self._load_json("evidence.json")
        self._evidence_by_id = {item["chunk_id"]: item for item in self._evidence}

    def list_companies(self, report_period: str | None = None) -> list[dict[str, Any]]:
        if report_period is None:
            return list(self._companies)
        return [
            company for company in self._companies if company["report_period"] == report_period
        ]

    def list_company_names(self) -> list[str]:
        return [company["company_name"] for company in self._companies]

    def list_company_periods(self, company_name: str) -> list[str]:
        periods = {
            company["report_period"]
            for company in self._companies
            if company["company_name"] == company_name
        }
        return sorted(periods, reverse=True)

    def get_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any] | None:
        for company in self._companies:
            if company["company_name"] != company_name:
                continue
            if report_period and company["report_period"] != report_period:
                continue
            return company
        return None

    def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
        for company in self._companies:
            if company["company_name"] in query and (
                report_period is None or company["report_period"] == report_period
            ):
                return company["company_name"]
        return None

    def get_evidence(self, chunk_id: str) -> dict[str, Any] | None:
        return self._evidence_by_id.get(chunk_id)

    def resolve_evidence(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        evidence = []
        for chunk_id in chunk_ids:
            item = self.get_evidence(chunk_id)
            if item:
                evidence.append(item)
        return evidence

    def _load_json(self, filename: str) -> list[dict[str, Any]]:
        path = self._data_dir / filename
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
