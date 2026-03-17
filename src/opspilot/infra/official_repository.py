from __future__ import annotations

from collections import Counter, defaultdict
from math import ceil
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
    "RAW_PROFIT_TOTAL",
    "RAW_CREDIT_IMPAIRMENT_LOSS",
    "RAW_ASSET_IMPAIRMENT_LOSS",
    "RAW_TOTAL_ASSETS",
    "RAW_PARENT_EQUITY",
    "RAW_GOVERNMENT_GRANTS",
    "RAW_IMPAIRMENT_PRESSURE",
    "RAW_CASH_FUNDS",
    "RAW_CURRENT_ASSETS",
    "RAW_ACCOUNTS_RECEIVABLE",
    "RAW_ACCOUNTS_RECEIVABLE_YOY",
    "RAW_INVENTORY",
    "RAW_CURRENT_LIABILITIES",
    "RAW_TOTAL_LIABILITIES",
    "RAW_SHORT_TERM_BORROWINGS",
    "RAW_DUE_WITHIN_ONE_YEAR_NONCURRENT_LIABILITIES",
}
EVENT_METRIC_CODES = {"I1", "I2", "I3", "I4"}
LABEL_METRIC_MAP = {
    "R1": ("C1", "G2"),
    "R2": ("C3",),
    "R3": ("P4",),
    "R4": ("S4", "S1"),
    "R5": ("I1",),
    "R6": ("I2",),
    "R7": ("I3",),
    "R8": ("I4",),
    "O1": ("P1",),
    "O2": ("C1",),
    "O3": ("P4",),
    "O4": ("S4",),
    "O5": ("G3",),
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
        if not period_counts:
            return None
        coverage_threshold = max(2, ceil(max(period_counts.values()) * 0.6))
        eligible_periods = [
            period for period, count in period_counts.items() if count >= coverage_threshold
        ]
        if eligible_periods:
            return max(eligible_periods, key=_period_sort_key)
        if period_counts:
            return max(period_counts, key=lambda period: (period_counts[period], _period_sort_key(period)))
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
            sorted_records = sorted(records, key=lambda item: _period_sort_key(item["report_period"]))
            for index, record in enumerate(sorted_records):
                metrics = {
                    key: value
                    for key, value in record.get("derived_metrics", {}).items()
                    if key not in RAW_METRIC_CODES
                }
                metric_evidence = {
                    metric_code: [record["summary_chunk_id"]]
                    for metric_code in metrics
                    if metric_code not in EVENT_METRIC_CODES
                }
                metric_evidence.update(record.get("event_metric_evidence", {}))
                metric_evidence.update(build_formula_metric_evidence(record, sorted_records[:index]))
                formula_context = build_formula_context(record, sorted_records[:index])
                backfill_missing_event_metrics(
                    metrics,
                    metric_evidence,
                    sorted_records[:index],
                    report_period=record["report_period"],
                )
                companies.append(
                    {
                        "company_id": company_meta.get("security_code", record["security_code"]),
                        "company_name": company_name,
                        "ticker": company_meta.get("ticker", infer_ticker(record)),
                        "subindustry": record["subindustry"],
                        "report_period": record["report_period"],
                        "metrics": metrics,
                        "trends": {},
                        "history": history,
                        "metric_evidence": metric_evidence,
                        "formula_context": formula_context,
                        "label_evidence": build_label_evidence(metric_evidence),
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
            for field_name, item in record.get("field_evidence", {}).items():
                index[item["chunk_id"]] = {
                    "chunk_id": item["chunk_id"],
                    "company_name": record["company_name"],
                    "report_period": record["report_period"],
                    "source_title": record["title"],
                    "source_type": item.get("source_type", "official_statement_page"),
                    "page": item["page"],
                    "excerpt": item["excerpt"],
                    "fingerprint": f"{record['report_id']}-{field_name}-{item['page']}",
                    "source_url": record["source_url"],
                    "local_path": record["local_path"],
                }
            for item in record.get("event_evidence", []):
                index[item["chunk_id"]] = {
                    "chunk_id": item["chunk_id"],
                    "company_name": record["company_name"],
                    "report_period": record["report_period"],
                    "source_title": record["title"],
                    "source_type": item.get("source_type", "official_event_page"),
                    "page": item["page"],
                    "excerpt": item["excerpt"],
                    "fingerprint": f"{record['report_id']}-{item['metric_code']}-{item['page']}",
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


def backfill_missing_event_metrics(
    metrics: dict[str, Any],
    metric_evidence: dict[str, list[str]],
    prior_records: list[dict[str, Any]],
    *,
    report_period: str,
) -> None:
    report_year = report_period[:4]
    for metric_code in EVENT_METRIC_CODES:
        if metrics.get(metric_code) is not None:
            continue
        fallback_record = find_prior_event_record(prior_records, metric_code, report_year=report_year)
        if fallback_record is None:
            continue
        metrics[metric_code] = fallback_record["derived_metrics"][metric_code]
        if evidence_ids := fallback_record.get("event_metric_evidence", {}).get(metric_code):
            metric_evidence[metric_code] = evidence_ids


def find_prior_event_record(
    prior_records: list[dict[str, Any]],
    metric_code: str,
    *,
    report_year: str,
) -> dict[str, Any] | None:
    same_year = [
        record
        for record in prior_records
        if record["report_period"].startswith(report_year)
        and record.get("derived_metrics", {}).get(metric_code) is not None
    ]
    if same_year:
        return same_year[-1]
    historical = [
        record
        for record in prior_records
        if record.get("derived_metrics", {}).get(metric_code) is not None
    ]
    if historical:
        return historical[-1]
    return None


def build_label_evidence(metric_evidence: dict[str, list[str]]) -> dict[str, list[str]]:
    label_evidence: dict[str, list[str]] = {}
    for label_code, metric_codes in LABEL_METRIC_MAP.items():
        chunk_ids: list[str] = []
        for metric_code in metric_codes:
            chunk_ids.extend(metric_evidence.get(metric_code, []))
        if chunk_ids:
            label_evidence[label_code] = dedupe_chunk_ids(chunk_ids)
    return label_evidence


def dedupe_chunk_ids(chunk_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id not in deduped:
            deduped.append(chunk_id)
    return deduped


def build_formula_metric_evidence(
    record: dict[str, Any],
    prior_records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    field_evidence = record.get("field_evidence", {})

    s3_chunk_ids = []
    if profit_total_evidence := field_evidence.get("profit_total", {}).get("chunk_id"):
        s3_chunk_ids.append(profit_total_evidence)
    if interest_evidence := field_evidence.get("interest_expense", {}).get("chunk_id"):
        s3_chunk_ids.append(interest_evidence)
    if s3_chunk_ids:
        evidence["S3"] = dedupe_chunk_ids(s3_chunk_ids)

    prior_c3_record = find_prior_comparable_record(prior_records, record["report_period"])
    c3_chunk_ids = []
    if current_receivable := field_evidence.get("accounts_receivable", {}).get("chunk_id"):
        c3_chunk_ids.append(current_receivable)
    if record.get("summary_chunk_id"):
        c3_chunk_ids.append(record["summary_chunk_id"])
    if prior_c3_record is not None:
        prior_field_evidence = prior_c3_record.get("field_evidence", {})
        if prior_receivable := prior_field_evidence.get("accounts_receivable", {}).get("chunk_id"):
            c3_chunk_ids.append(prior_receivable)
        elif prior_c3_record.get("summary_chunk_id"):
            c3_chunk_ids.append(prior_c3_record["summary_chunk_id"])
    if len(c3_chunk_ids) >= 2:
        evidence["C3"] = dedupe_chunk_ids(c3_chunk_ids)

    return evidence


def find_prior_comparable_record(
    prior_records: list[dict[str, Any]],
    report_period: str,
) -> dict[str, Any] | None:
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|FY)", report_period)
    if not match:
        return None
    target_period = f"{int(match.group(1)) - 1}{match.group(2)}"
    for record in reversed(prior_records):
        if record["report_period"] == target_period:
            return record
    return None


def build_formula_context(
    record: dict[str, Any],
    prior_records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    derived_metrics = record.get("derived_metrics", {})
    context: dict[str, dict[str, Any]] = {}

    if derived_metrics.get("S3") is not None:
        context["S3"] = {
            "value": derived_metrics["S3"],
            "profit_total": derived_metrics.get("RAW_PROFIT_TOTAL"),
            "interest_expense": _interest_expense_from_record(record),
            "formula": "(利润总额 + 利息费用) / 利息费用",
        }

    prior_record = find_prior_comparable_record(prior_records, record["report_period"])
    if derived_metrics.get("C3") is not None and prior_record is not None:
        current_receivable = derived_metrics.get("RAW_ACCOUNTS_RECEIVABLE")
        prior_receivable = prior_record.get("derived_metrics", {}).get("RAW_ACCOUNTS_RECEIVABLE")
        receivable_yoy = derived_metrics.get("RAW_ACCOUNTS_RECEIVABLE_YOY")
        revenue_yoy = derived_metrics.get("G1")
        context["C3"] = {
            "value": derived_metrics["C3"],
            "current_receivable": current_receivable,
            "prior_receivable": prior_receivable,
            "prior_period": prior_record["report_period"],
            "receivable_yoy": receivable_yoy,
            "revenue_yoy": revenue_yoy,
            "formula": "应收账款同比 - 营业收入同比",
        }
    return context


def _interest_expense_from_record(record: dict[str, Any]) -> float | None:
    return record.get("facts", {}).get("interest_expense", {}).get("current")


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
