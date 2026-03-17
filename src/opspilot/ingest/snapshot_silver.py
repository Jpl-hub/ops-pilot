from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from opspilot.ingest.manifest_utils import load_manifest_records
from opspilot.ingest.silver_metrics import derive_metric_codes

SNAPSHOT_FIELD_MAP = {
    "营业收入": "revenue",
    "营业成本": "operating_cost",
    "利润总额": "profit_total",
    "净利润": "net_profit",
    "经营活动产生的现金流量净额": "operating_cash_flow",
    "货币资金": "cash_funds",
    "流动资产": "current_assets",
    "总资产": "assets",
    "流动负债": "current_liabilities",
    "总负债": "total_liabilities",
    "所有者权益": "equity_parent",
}
SNAPSHOT_FIELD_LABELS = {value: key for key, value in SNAPSHOT_FIELD_MAP.items()}
YEAR_START = 2019


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Build annual silver rows from CNInfo snapshot payloads.")
    parser.add_argument(
        "--manifest",
        default="data/raw/official/manifests/company_snapshots_manifest.json",
        help="Path to the company snapshot manifest JSON.",
    )
    parser.add_argument(
        "--silver-manifest",
        default="data/silver/official/manifests/financial_metrics_manifest.json",
        help="Path to the silver manifest JSON.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated security codes to limit execution.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest)
    snapshot_records = load_manifest_records(manifest_path)
    selected_codes = {item.strip() for item in args.codes.split(",") if item.strip()}
    if selected_codes:
        snapshot_records = [
            item for item in snapshot_records if item.get("security_code") in selected_codes
        ]

    silver_manifest_path = Path(args.silver_manifest)
    existing_rows = load_manifest_records(silver_manifest_path)
    existing_periods = {
        (row.get("security_code"), row.get("report_period"))
        for row in existing_rows
    }

    generated_rows: list[dict[str, Any]] = []
    for record in snapshot_records:
        payload = json.loads(Path(record["local_path"]).read_text(encoding="utf-8"))
        rows = build_snapshot_rows(record, payload, existing_periods)
        generated_rows.extend(rows)
        print(f"snapshot {record['security_code']} annual_rows={len(rows)}")

    target_codes = {record["security_code"] for record in snapshot_records}
    preserved_rows = [
        row
        for row in existing_rows
        if not (
            row.get("source") == "CNINFO_SNAPSHOT"
            and row.get("security_code") in target_codes
        )
    ]
    merged_rows = preserved_rows + generated_rows
    merged_rows.sort(
        key=lambda item: (
            item.get("security_code", ""),
            item.get("report_period", ""),
            item.get("source", ""),
            item.get("report_id", ""),
        )
    )

    silver_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    silver_manifest_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "record_count": len(merged_rows),
                "period_counts": _period_counts(merged_rows),
                "records": merged_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"snapshot_silver_rows={len(generated_rows)}")
    print(f"silver_reports={len(merged_rows)}")


def build_snapshot_rows(
    record: dict[str, Any],
    payload: dict[str, Any],
    existing_periods: set[tuple[str | None, str | None]],
) -> list[dict[str, Any]]:
    annual_tables = build_annual_tables(payload)
    years = sorted(
        {
            year
            for values in annual_tables.values()
            for year, value in values.items()
            if year >= YEAR_START and value is not None
        }
    )
    rows: list[dict[str, Any]] = []
    for year in years:
        report_period = f"{year}FY"
        if (record.get("security_code"), report_period) in existing_periods:
            continue
        facts = build_snapshot_facts(annual_tables, year)
        if "revenue" not in facts or "net_profit" not in facts:
            continue
        row_values = {**facts, "_meta": {"report_period": report_period}}
        derived_metrics = derive_metric_codes(row_values)
        if not derived_metrics:
            continue
        report_id = f"cninfo-snapshot-{record['security_code']}-{report_period}"
        summary_excerpt = build_summary_excerpt(record["company_name"], report_period, facts)
        rows.append(
            {
                **record,
                "report_id": report_id,
                "report_period": report_period,
                "summary_page": 1,
                "summary_chunk_id": f"{report_id}-summary-page-001",
                "summary_unit": "单位：百万元",
                "unit_scale": 1_000_000.0,
                "summary_excerpt": summary_excerpt,
                "title": f"巨潮资讯公司快照 {report_period}",
                "facts": {
                    field: {
                        "current": value["current"],
                        "previous": value["previous"],
                        "change_pct": value["change_pct"],
                        "tokens": value["tokens"],
                    }
                    for field, value in facts.items()
                },
                "field_evidence": build_field_evidence(report_id, report_period, facts),
                "event_metric_evidence": {},
                "event_evidence": [],
                "derived_metrics": derived_metrics,
            }
        )
    return rows


def build_annual_tables(payload: dict[str, Any]) -> dict[str, dict[int, float | None]]:
    finance_data = payload.get("finance_data", {})
    tables = (
        finance_data.get("assetsData", [])
        + finance_data.get("profitsData", [])
        + finance_data.get("cashFlowData", [])
    )
    annual_tables: dict[str, dict[int, float | None]] = {}
    for row in tables:
        index_name = row.get("index")
        field_name = SNAPSHOT_FIELD_MAP.get(index_name)
        if field_name is None:
            continue
        annual_tables[field_name] = {
            int(key): _to_amount(row.get(key))
            for key in row.keys()
            if key.isdigit()
        }
    return annual_tables


def build_snapshot_facts(
    annual_tables: dict[str, dict[int, float | None]], year: int
) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for field_name, values in annual_tables.items():
        current = values.get(year)
        if current is None:
            continue
        previous = values.get(year - 1)
        facts[field_name] = {
            "current": current,
            "previous": previous,
            "change_pct": _change_pct(current, previous),
            "tokens": [str(int(current / 1_000_000))],
        }
    return facts


def build_summary_excerpt(
    company_name: str,
    report_period: str,
    facts: dict[str, dict[str, Any]],
) -> str:
    pieces = [f"{company_name} {report_period} 官方公司快照。"]
    for field in (
        "revenue",
        "net_profit",
        "operating_cash_flow",
        "assets",
        "total_liabilities",
    ):
        value = facts.get(field, {}).get("current")
        if value is None:
            continue
        pieces.append(f"{SNAPSHOT_FIELD_LABELS[field]} {value / 1_000_000:.0f} 百万元。")
    return " ".join(pieces)


def build_field_evidence(
    report_id: str,
    report_period: str,
    facts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    field_evidence: dict[str, dict[str, Any]] = {}
    for field, payload in facts.items():
        label = SNAPSHOT_FIELD_LABELS.get(field, field)
        field_evidence[field] = {
            "chunk_id": f"{report_id}-field-{field}-page-001",
            "field": field,
            "page": 1,
            "excerpt": f"{report_period} {label}：{payload['current'] / 1_000_000:.0f} 百万元",
            "source_type": "official_snapshot_page",
        }
    return field_evidence


def _change_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / abs(previous) * 100.0, 2)


def _to_amount(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    return round(float(value) * 1_000_000.0, 2)


def _period_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        period = row.get("report_period")
        if not period:
            continue
        counts[period] = counts.get(period, 0) + 1
    return counts


if __name__ == "__main__":
    main()
