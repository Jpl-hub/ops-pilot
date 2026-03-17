from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import json
import re


PERIOD_SUFFIX_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
RAW_METRIC_CODES = {
    "RAW_REVENUE",
    "RAW_NET_PROFIT",
    "RAW_DEDUCTED_NET_PROFIT",
    "RAW_OPERATING_CASH_FLOW",
    "RAW_OPERATING_COST",
    "RAW_SALES_EXPENSE",
    "RAW_ADMIN_EXPENSE",
    "RAW_RD_EXPENSE",
    "RAW_FINANCE_EXPENSE",
    "RAW_TOTAL_ASSETS",
    "RAW_PARENT_EQUITY",
    "RAW_CASH_FUNDS",
    "RAW_CURRENT_ASSETS",
    "RAW_CURRENT_LIABILITIES",
    "RAW_TOTAL_LIABILITIES",
    "RAW_SHORT_TERM_BORROWINGS",
    "RAW_DUE_WITHIN_ONE_YEAR_NONCURRENT_LIABILITIES",
}


class OfficialMetricsRepository:
    def __init__(self, silver_root: Path, universe_path: Path) -> None:
        self._manifest_path = silver_root / "manifests" / "financial_metrics_manifest.json"
        self._pool_by_name = _load_company_pool(universe_path)
        self._records = _load_manifest_records(self._manifest_path)
        self._companies = self._build_companies()
        self._evidence_by_id = self._build_evidence_index()

    def list_companies(self, report_period: str | None = None) -> list[dict[str, Any]]:
        if report_period is None:
            return self._latest_company_snapshots()
        return [
            company
            for company in self._companies
            if company["report_period"] == report_period
        ]

    def list_company_names(self) -> list[str]:
        return sorted({company["company_name"] for company in self._companies})

    def get_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any] | None:
        matches = [
            company
            for company in self._companies
            if company["company_name"] == company_name
            and (report_period is None or company["report_period"] == report_period)
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: _period_sort_key(item["report_period"]), reverse=True)
        return matches[0]

    def find_company_from_query(
        self, query: str, report_period: str | None = None
    ) -> str | None:
        for company_name in self.list_company_names():
            if company_name not in query:
                continue
            if report_period is None or self.get_company(company_name, report_period) is not None:
                return company_name
        return None

    def preferred_period(self) -> str | None:
        period_counts = Counter(company["report_period"] for company in self._companies)
        eligible_periods = [period for period, count in period_counts.items() if count >= 2]
        if eligible_periods:
            return max(eligible_periods, key=_period_sort_key)
        if period_counts:
            return max(period_counts, key=_period_sort_key)
        return None

    def get_evidence(self, chunk_id: str) -> dict[str, Any] | None:
        return self._evidence_by_id.get(chunk_id)

    def resolve_evidence(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        return [
            evidence
            for chunk_id in chunk_ids
            if (evidence := self.get_evidence(chunk_id)) is not None
        ]

    def _latest_company_snapshots(self) -> list[dict[str, Any]]:
        latest_by_company: dict[str, dict[str, Any]] = {}
        for company in self._companies:
            current = latest_by_company.get(company["company_name"])
            if current is None or _period_sort_key(company["report_period"]) > _period_sort_key(
                current["report_period"]
            ):
                latest_by_company[company["company_name"]] = company
        return sorted(latest_by_company.values(), key=lambda item: item["company_name"])

    def _build_companies(self) -> list[dict[str, Any]]:
        grouped_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in self._records:
            grouped_records[record["company_name"]].append(record)

        companies: list[dict[str, Any]] = []
        for company_name, records in grouped_records.items():
            company_meta = self._pool_by_name.get(company_name, {})
            history = build_history_rows(records)
            for record in records:
                metric_evidence = {
                    metric_code: [record["summary_chunk_id"]]
                    for metric_code in record.get("derived_metrics", {})
                    if metric_code not in RAW_METRIC_CODES
                }
                companies.append(
                    {
                        "company_id": company_meta.get("security_code", record["security_code"]),
                        "company_name": company_name,
                        "ticker": company_meta.get("ticker", infer_ticker(record)),
                        "subindustry": record["subindustry"],
                        "report_period": record["report_period"],
                        "metrics": {
                            key: value
                            for key, value in record.get("derived_metrics", {}).items()
                            if key not in RAW_METRIC_CODES
                        },
                        "trends": {},
                        "history": history,
                        "metric_evidence": metric_evidence,
                        "label_evidence": {},
                    }
                )
        return companies

    def _build_evidence_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for record in self._records:
            index[record["summary_chunk_id"]] = {
                "chunk_id": record["summary_chunk_id"],
                "company_name": record["company_name"],
                "report_period": record["report_period"],
                "source_title": record["title"],
                "source_type": "official_summary_page",
                "page": record["summary_page"],
                "excerpt": record["summary_excerpt"],
                "fingerprint": f"{record['report_id']}-{record['summary_page']}",
                "source_url": record["source_url"],
                "local_path": record["local_path"],
            }
        return index


def build_history_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    sorted_records = sorted(records, key=lambda item: _period_sort_key(item["report_period"]))
    for record in sorted_records:
        metrics = record.get("derived_metrics", {})
        revenue = metrics.get("RAW_REVENUE")
        net_profit = metrics.get("RAW_NET_PROFIT")
        if revenue is None and net_profit is None:
            continue
        rows.append(
            {
                "period": record["report_period"],
                "revenue": round((revenue or 0.0) / 1e8, 2),
                "net_profit": round((net_profit or 0.0) / 1e8, 2),
            }
        )
    return rows


def infer_ticker(record: dict[str, Any]) -> str:
    suffix = ".SH" if record["exchange"] == "SSE" else ".SZ"
    return f"{record['security_code']}{suffix}"


def _load_company_pool(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    pool = json.loads(path.read_text(encoding="utf-8"))
    return {item["company_name"]: item for item in pool}


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("records", [])


def _period_sort_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|FY)", period)
    if not match:
        return (0, 0)
    return (int(match.group(1)), PERIOD_SUFFIX_ORDER[match.group(2)])
