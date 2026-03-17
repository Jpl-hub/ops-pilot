from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re


NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
WHITESPACE_RE = re.compile(r"\s+")

FIELD_LABELS = {
    "revenue": ("营业收入",),
    "profit_total": ("利润总额",),
    "net_profit": ("归属于上市公司股东的净利润",),
    "deducted_net_profit": ("归属于上市公司股东的扣除非经常性损益的净利润",),
    "operating_cash_flow": ("经营活动产生的现金流量净额",),
    "basic_eps": ("基本每股收益",),
    "diluted_eps": ("稀释每股收益",),
    "roe": ("加权平均净资产收益率",),
    "assets": ("总资产", "资产总额"),
    "equity_parent": ("归属于上市公司股东的净资产", "归属于上市公司股东的所有者权益"),
}
BALANCE_FIELD_LABELS = {
    "cash_funds": ("货币资金",),
    "current_assets": ("流动资产合计",),
    "accounts_receivable": ("应收账款",),
    "inventory": ("存货",),
    "current_liabilities": ("流动负债合计",),
    "total_liabilities": ("负债合计",),
    "short_term_borrowings": ("短期借款",),
    "due_within_one_year_noncurrent_liabilities": ("一年内到期的非流动负债",),
}
PROFIT_FIELD_LABELS = {
    "operating_total_revenue": ("营业总收入",),
    "operating_revenue": ("营业收入",),
    "operating_total_cost": ("营业总成本",),
    "operating_cost": ("营业成本",),
    "sales_expense": ("销售费用",),
    "admin_expense": ("管理费用",),
    "rd_expense": ("研发费用",),
    "finance_expense": ("财务费用",),
    "interest_expense": ("利息费用",),
    "interest_income": ("利息收入",),
}

FIELD_ORDER = list(FIELD_LABELS)
CORE_SUMMARY_LABELS = (
    "营业收入",
    "归属于上市公司股东的净利润",
    "经营活动产生的现金流量净额",
    "总资产",
    "归属于上市公司股东的净资产",
)
MONETARY_FIELDS = {
    "revenue",
    "profit_total",
    "net_profit",
    "deducted_net_profit",
    "operating_cash_flow",
    "operating_total_revenue",
    "operating_revenue",
    "operating_total_cost",
    "operating_cost",
    "sales_expense",
    "admin_expense",
    "rd_expense",
    "finance_expense",
    "interest_expense",
    "interest_income",
    "assets",
    "equity_parent",
    "cash_funds",
    "current_assets",
    "accounts_receivable",
    "inventory",
    "current_liabilities",
    "total_liabilities",
    "short_term_borrowings",
    "due_within_one_year_noncurrent_liabilities",
}
Q3_CUMULATIVE_FIELDS = {
    "revenue",
    "net_profit",
    "deducted_net_profit",
    "basic_eps",
    "diluted_eps",
    "roe",
}
ASSET_PAGE_ANCHORS = ("流动资产合计", "合并资产负债表", "资产负债表", "流动资产：")
LIABILITY_PAGE_ANCHORS = ("流动负债合计", "负债合计", "所有者权益合计", "流动负债：")
PROFIT_PAGE_ANCHORS = ("合并利润表", "营业总成本", "销售费用", "管理费用", "研发费用")
UNIT_SCALE_BY_TEXT = {
    "单位：元": 1.0,
    "单位：千元": 1_000.0,
    "单位：万元": 10_000.0,
    "单位：百万元": 1_000_000.0,
    "（元）": 1.0,
    "(元)": 1.0,
    "（千元）": 1_000.0,
    "(千元)": 1_000.0,
    "（万元）": 10_000.0,
    "(万元)": 10_000.0,
    "（百万元）": 1_000_000.0,
    "(百万元)": 1_000_000.0,
}


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Extract silver financial metrics from bronze page text.")
    parser.add_argument(
        "--manifest",
        default="data/bronze/official/manifests/parsed_periodic_reports_manifest.json",
        help="Path to the bronze periodic reports manifest JSON.",
    )
    parser.add_argument(
        "--output-root",
        default="data/silver/official",
        help="Directory to store silver outputs.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated security codes to limit execution.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of reports to process.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Scan only the first N pages when locating the summary page.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = payload.get("records", [])

    selected_codes = {item.strip() for item in args.codes.split(",") if item.strip()}
    if selected_codes:
        records = [item for item in records if item["security_code"] in selected_codes]
    if args.limit > 0:
        records = records[: args.limit]

    silver_rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        row = extract_record(record, max_pages=args.max_pages)
        silver_rows.append(row)
        print(
            f"[{index}/{len(records)}] silver {record['security_code']} "
            f"{row['report_period']} metrics={len(row['derived_metrics'])}"
        )

    output_root = Path(args.output_root)
    manifests_root = output_root / "manifests"
    manifests_root.mkdir(parents=True, exist_ok=True)

    manifest_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "record_count": len(silver_rows),
        "period_counts": dict(Counter(row["report_period"] for row in silver_rows)),
        "records": silver_rows,
    }
    (manifests_root / "financial_metrics_manifest.json").write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"silver_reports={len(silver_rows)}")


def extract_record(record: dict[str, Any], *, max_pages: int = 20) -> dict[str, Any]:
    page_payload = json.loads(Path(record["page_json_path"]).read_text(encoding="utf-8"))
    pages = page_payload.get("pages", [])
    summary_page = select_summary_page(pages, max_pages=max_pages)
    summary_text = normalize_page_text(summary_page)
    row_values = extract_row_values(summary_text)
    report_period = infer_report_period(record["title"], record["publish_date"])
    row_values = apply_period_selection(row_values, report_period)
    unit_text, unit_scale = detect_unit_scale(summary_text)
    row_values = apply_unit_scale(row_values, unit_scale)
    balance_row_values = extract_balance_sheet_values(pages, fallback_unit_text=unit_text, fallback_unit_scale=unit_scale)
    profit_row_values = extract_profit_statement_values(pages, fallback_unit_text=unit_text, fallback_unit_scale=unit_scale)
    merged_row_values = {
        **row_values,
        **balance_row_values,
        **profit_row_values,
        "_meta": {"report_period": report_period},
    }
    derived_metrics = derive_metric_codes(merged_row_values)
    summary_chunk_id = f"{record['report_id']}-summary-page-{summary_page['page']:03d}"

    return {
        **record,
        "report_period": report_period,
        "summary_page": summary_page["page"],
        "summary_chunk_id": summary_chunk_id,
        "summary_unit": unit_text,
        "unit_scale": unit_scale,
        "summary_excerpt": summary_text[:1500],
        "facts": {
            key: {
                "current": value["current"],
                "previous": value["previous"],
                "change_pct": value["change_pct"],
                "tokens": value["tokens"],
            }
            for key, value in merged_row_values.items()
            if key != "_meta"
        },
        "derived_metrics": derived_metrics,
    }


def select_summary_page(pages: list[dict[str, Any]], *, max_pages: int) -> dict[str, Any]:
    best_page: dict[str, Any] | None = None
    best_score = -1
    for page in pages[:max_pages]:
        text = compact_text(normalize_page_text(page))
        score = sum(1 for label in CORE_SUMMARY_LABELS if label in text)
        if score > best_score:
            best_score = score
            best_page = page
    if best_page is None:
        raise ValueError("未找到可用的摘要页。")
    return best_page


def normalize_page_text(page: dict[str, Any]) -> str:
    return WHITESPACE_RE.sub(
        " ",
        " ".join(block["text"] for block in page.get("blocks", []))
        .replace("\u3000", " ")
        .replace("\xa0", " "),
    ).strip()


def compact_text(text: str) -> str:
    return WHITESPACE_RE.sub("", text.replace("\u3000", " ").replace("\xa0", " "))


def extract_row_values(text: str) -> dict[str, dict[str, Any]]:
    positions: list[tuple[int, int, str]] = []
    for field in FIELD_ORDER:
        match = None
        for label in FIELD_LABELS[field]:
            match = build_label_pattern(label).search(text)
            if match is not None:
                break
        if match is not None:
            positions.append((match.start(), match.end(), field))
    positions.sort(key=lambda item: item[0])

    values: dict[str, dict[str, Any]] = {}
    for index, (_, label_end, field) in enumerate(positions):
        start = label_end
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        values[field] = parse_value_segment(text[start:end])
    return values


def build_label_pattern(label: str) -> re.Pattern[str]:
    body = r"\s*".join(re.escape(char) for char in label)
    return re.compile(rf"(?<![\u4e00-\u9fffA-Za-z0-9]){body}(?![\u4e00-\u9fffA-Za-z0-9])")


def parse_value_segment(segment: str) -> dict[str, Any]:
    parsed_tokens = []
    for raw in NUMBER_RE.findall(segment):
        cleaned = raw.replace(",", "").replace("%", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        parsed_tokens.append({"raw": raw, "value": value, "is_percent": raw.endswith("%")})

    current = parsed_tokens[0]["value"] if parsed_tokens else None
    previous = parsed_tokens[1]["value"] if len(parsed_tokens) >= 2 else None

    percent_tokens = [token["value"] for token in parsed_tokens if token["is_percent"]]
    change_pct = percent_tokens[-1] if percent_tokens else None
    if change_pct is None and len(parsed_tokens) >= 3 and abs(parsed_tokens[-1]["value"]) <= 1000:
        change_pct = parsed_tokens[-1]["value"]

    return {
        "current": current,
        "previous": previous,
        "change_pct": change_pct,
        "tokens": [token["raw"] for token in parsed_tokens[:8]],
    }


def extract_balance_sheet_values(
    pages: list[dict[str, Any]],
    *,
    fallback_unit_text: str,
    fallback_unit_scale: float,
) -> dict[str, dict[str, Any]]:
    asset_pages = select_candidate_pages(pages, ASSET_PAGE_ANCHORS)
    liability_pages = select_candidate_pages(pages, LIABILITY_PAGE_ANCHORS)

    values: dict[str, dict[str, Any]] = {}
    for field in ("cash_funds", "accounts_receivable", "inventory", "current_assets"):
        if result := locate_balance_field(
            field,
            asset_pages or pages,
            BALANCE_FIELD_LABELS[field],
            fallback_unit_text=fallback_unit_text,
            fallback_unit_scale=fallback_unit_scale,
        ):
            values[field] = result
    for field in (
        "current_liabilities",
        "total_liabilities",
        "short_term_borrowings",
        "due_within_one_year_noncurrent_liabilities",
    ):
        if result := locate_balance_field(
            field,
            liability_pages or pages,
            BALANCE_FIELD_LABELS[field],
            fallback_unit_text=fallback_unit_text,
            fallback_unit_scale=fallback_unit_scale,
        ):
            values[field] = result
    return values


def extract_profit_statement_values(
    pages: list[dict[str, Any]],
    *,
    fallback_unit_text: str,
    fallback_unit_scale: float,
) -> dict[str, dict[str, Any]]:
    profit_pages = select_candidate_pages(pages, PROFIT_PAGE_ANCHORS)
    values: dict[str, dict[str, Any]] = {}
    for field, labels in PROFIT_FIELD_LABELS.items():
        if result := locate_balance_field(
            field,
            profit_pages or pages,
            labels,
            fallback_unit_text=fallback_unit_text,
            fallback_unit_scale=fallback_unit_scale,
        ):
            values[field] = result
    return values


def select_candidate_pages(
    pages: list[dict[str, Any]], anchors: tuple[str, ...]
) -> list[dict[str, Any]]:
    candidates = []
    for page in pages:
        text = normalize_page_text(page)
        if any(anchor in text for anchor in anchors):
            candidates.append(page)
    return candidates


def locate_balance_field(
    field_name: str,
    pages: list[dict[str, Any]],
    labels: tuple[str, ...],
    *,
    fallback_unit_text: str,
    fallback_unit_scale: float,
) -> dict[str, Any] | None:
    for page in pages:
        text = normalize_page_text(page)
        unit_text, unit_scale = detect_unit_scale(text)
        if unit_scale == 1.0 and fallback_unit_scale != 1.0:
            unit_text = fallback_unit_text
            unit_scale = fallback_unit_scale
        for label in labels:
            extracted = extract_balance_field(text, label)
            if extracted is None:
                continue
            extracted["page"] = page["page"]
            extracted["unit_text"] = unit_text
            if unit_scale != 1.0:
                extracted = apply_unit_scale({field_name: extracted}, unit_scale)[field_name]
                extracted["page"] = page["page"]
                extracted["unit_text"] = unit_text
            return extracted
    return None


def extract_balance_field(text: str, label: str) -> dict[str, Any] | None:
    match = build_label_pattern(label).search(text)
    if match is None:
        return None

    segment = text[match.end() : match.end() + 180]
    parsed_tokens = []
    for raw in NUMBER_RE.findall(segment):
        if raw.endswith("%"):
            continue
        value = parse_numeric_token(raw)
        if not is_plausible_balance_number(raw, value):
            continue
        parsed_tokens.append({"raw": raw, "value": value})

    if not parsed_tokens:
        return None
    return {
        "current": parsed_tokens[0]["value"],
        "previous": parsed_tokens[1]["value"] if len(parsed_tokens) >= 2 else None,
        "change_pct": None,
        "tokens": [token["raw"] for token in parsed_tokens[:6]],
    }


def is_plausible_balance_number(raw: str, value: float) -> bool:
    digits = re.sub(r"\D", "", raw)
    return "," in raw or len(digits) >= 5 or abs(value) >= 10000


def apply_period_selection(
    row_values: dict[str, dict[str, Any]], report_period: str
) -> dict[str, dict[str, Any]]:
    adjusted = {
        field: {
            "current": value["current"],
            "previous": value["previous"],
            "change_pct": value["change_pct"],
            "tokens": list(value["tokens"]),
        }
        for field, value in row_values.items()
    }
    if not report_period.endswith("Q3"):
        return adjusted

    for field in Q3_CUMULATIVE_FIELDS:
        value = adjusted.get(field)
        if value is None:
            continue
        tokens = value["tokens"]
        if len(tokens) >= 4 and tokens[1].endswith("%") and not tokens[2].endswith("%") and tokens[3].endswith("%"):
            value["current"] = parse_numeric_token(tokens[2])
            value["previous"] = None
            value["change_pct"] = parse_numeric_token(tokens[3])
    return adjusted


def detect_unit_scale(text: str) -> tuple[str, float]:
    for unit_text, unit_scale in UNIT_SCALE_BY_TEXT.items():
        if unit_text in text:
            return unit_text, unit_scale
    return "单位：元", 1.0


def apply_unit_scale(
    row_values: dict[str, dict[str, Any]], unit_scale: float
) -> dict[str, dict[str, Any]]:
    if unit_scale == 1.0:
        return row_values

    adjusted = {
        field: {
            "current": value["current"],
            "previous": value["previous"],
            "change_pct": value["change_pct"],
            "tokens": list(value["tokens"]),
        }
        for field, value in row_values.items()
    }
    for field in MONETARY_FIELDS:
        if field not in adjusted:
            continue
        if adjusted[field]["current"] is not None:
            adjusted[field]["current"] = round(adjusted[field]["current"] * unit_scale, 2)
        if adjusted[field]["previous"] is not None:
            adjusted[field]["previous"] = round(adjusted[field]["previous"] * unit_scale, 2)
    return adjusted


def parse_numeric_token(raw: str) -> float:
    return float(raw.replace(",", "").replace("%", ""))


def derive_metric_codes(row_values: dict[str, dict[str, Any]]) -> dict[str, float]:
    derived: dict[str, float] = {}

    revenue = current_value(row_values, "revenue")
    net_profit = current_value(row_values, "net_profit")
    deducted_net_profit = current_value(row_values, "deducted_net_profit")
    operating_cash_flow = current_value(row_values, "operating_cash_flow")
    operating_revenue = current_value(row_values, "operating_revenue") or revenue
    operating_cost = current_value(row_values, "operating_cost")
    sales_expense = current_value(row_values, "sales_expense")
    admin_expense = current_value(row_values, "admin_expense")
    rd_expense = current_value(row_values, "rd_expense")
    finance_expense = current_value(row_values, "finance_expense")

    revenue_yoy = change_value(row_values, "revenue")
    if revenue_yoy is not None:
        derived["G1"] = round(revenue_yoy, 2)

    profit_yoy = change_value(row_values, "deducted_net_profit")
    if profit_yoy is None:
        profit_yoy = change_value(row_values, "net_profit")
    if profit_yoy is not None:
        derived["G2"] = round(profit_yoy, 2)

    if revenue is not None and net_profit is not None and revenue != 0:
        derived["P2"] = round(net_profit / revenue * 100.0, 2)

    if operating_revenue not in (None, 0) and rd_expense is not None:
        derived["G3"] = round(rd_expense / operating_revenue * 100.0, 2)

    if operating_revenue not in (None, 0) and operating_cost is not None:
        derived["P1"] = round((operating_revenue - operating_cost) / operating_revenue * 100.0, 2)

    if operating_revenue not in (None, 0):
        period_expenses = [
            value
            for value in [sales_expense, admin_expense, rd_expense, finance_expense]
            if value is not None
        ]
        if len(period_expenses) >= 3:
            derived["P3"] = round(sum(period_expenses) / operating_revenue * 100.0, 2)

    if net_profit not in (None, 0) and operating_cash_flow is not None:
        derived["C1"] = round(operating_cash_flow / net_profit, 4)

    if revenue not in (None, 0) and operating_cash_flow is not None:
        derived["C2"] = round(operating_cash_flow / revenue, 4)

    if revenue is not None:
        derived["RAW_REVENUE"] = round(revenue, 2)
    if net_profit is not None:
        derived["RAW_NET_PROFIT"] = round(net_profit, 2)
    if deducted_net_profit is not None:
        derived["RAW_DEDUCTED_NET_PROFIT"] = round(deducted_net_profit, 2)
    if operating_cash_flow is not None:
        derived["RAW_OPERATING_CASH_FLOW"] = round(operating_cash_flow, 2)
    if operating_cost is not None:
        derived["RAW_OPERATING_COST"] = round(operating_cost, 2)
    if sales_expense is not None:
        derived["RAW_SALES_EXPENSE"] = round(sales_expense, 2)
    if admin_expense is not None:
        derived["RAW_ADMIN_EXPENSE"] = round(admin_expense, 2)
    if rd_expense is not None:
        derived["RAW_RD_EXPENSE"] = round(rd_expense, 2)
    if finance_expense is not None:
        derived["RAW_FINANCE_EXPENSE"] = round(finance_expense, 2)

    assets = current_value(row_values, "assets")
    equity_parent = current_value(row_values, "equity_parent")
    cash_funds = current_value(row_values, "cash_funds")
    current_assets = current_value(row_values, "current_assets")
    current_liabilities = current_value(row_values, "current_liabilities")
    total_liabilities = current_value(row_values, "total_liabilities")
    short_term_borrowings = current_value(row_values, "short_term_borrowings") or 0.0
    due_within_one_year = (
        current_value(row_values, "due_within_one_year_noncurrent_liabilities") or 0.0
    )
    accounts_receivable = current_value(row_values, "accounts_receivable")
    inventory = current_value(row_values, "inventory")

    if current_assets not in (None, 0) and current_liabilities not in (None, 0):
        derived["S1"] = round(current_assets / current_liabilities, 4)
    if assets not in (None, 0) and total_liabilities is not None:
        derived["S2"] = round(total_liabilities / assets * 100.0, 2)
    short_debt = short_term_borrowings + due_within_one_year
    if cash_funds is not None and short_debt > 0:
        derived["S4"] = round(cash_funds / short_debt, 4)

    period_days = report_period_days(row_values)
    if operating_cost not in (None, 0) and inventory is not None:
        average_inventory = average_period_balance(row_values, "inventory")
        if average_inventory is not None:
            derived["P4"] = round(average_inventory / operating_cost * period_days, 2)
    if operating_revenue not in (None, 0) and accounts_receivable is not None:
        average_receivable = average_period_balance(row_values, "accounts_receivable")
        if average_receivable is not None:
            derived["P5"] = round(average_receivable / operating_revenue * period_days, 2)

    if assets is not None:
        derived["RAW_TOTAL_ASSETS"] = round(assets, 2)
    if equity_parent is not None:
        derived["RAW_PARENT_EQUITY"] = round(equity_parent, 2)
    if cash_funds is not None:
        derived["RAW_CASH_FUNDS"] = round(cash_funds, 2)
    if current_assets is not None:
        derived["RAW_CURRENT_ASSETS"] = round(current_assets, 2)
    if accounts_receivable is not None:
        derived["RAW_ACCOUNTS_RECEIVABLE"] = round(accounts_receivable, 2)
    if inventory is not None:
        derived["RAW_INVENTORY"] = round(inventory, 2)
    if current_liabilities is not None:
        derived["RAW_CURRENT_LIABILITIES"] = round(current_liabilities, 2)
    if total_liabilities is not None:
        derived["RAW_TOTAL_LIABILITIES"] = round(total_liabilities, 2)
    if short_term_borrowings > 0:
        derived["RAW_SHORT_TERM_BORROWINGS"] = round(short_term_borrowings, 2)
    if due_within_one_year > 0:
        derived["RAW_DUE_WITHIN_ONE_YEAR_NONCURRENT_LIABILITIES"] = round(
            due_within_one_year, 2
        )

    return derived


def average_period_balance(row_values: dict[str, dict[str, Any]], field: str) -> float | None:
    current = current_value(row_values, field)
    previous = row_values.get(field, {}).get("previous")
    if current is None:
        return None
    if previous is None:
        return current
    return (current + float(previous)) / 2.0


def report_period_days(row_values: dict[str, dict[str, Any]]) -> int:
    report_period = row_values.get("_meta", {}).get("report_period")
    if report_period is None:
        return 365
    if report_period.endswith("Q1"):
        return 90
    if report_period.endswith("H1"):
        return 181
    if report_period.endswith("Q3"):
        return 273
    if report_period.endswith("FY"):
        return 365
    return 365


def current_value(row_values: dict[str, dict[str, Any]], field: str) -> float | None:
    value = row_values.get(field, {}).get("current")
    return None if value is None else float(value)


def change_value(row_values: dict[str, dict[str, Any]], field: str) -> float | None:
    value = row_values.get(field, {}).get("change_pct")
    return None if value is None else float(value)


def infer_report_period(title: str, publish_date: str) -> str:
    year_match = re.search(r"(\d{4})年", title)
    year = year_match.group(1) if year_match else publish_date[:4]
    if "半年度报告" in title:
        return f"{year}H1"
    if "三季度报告" in title or "第三季度报告" in title:
        return f"{year}Q3"
    if "一季度报告" in title or "第一季度报告" in title:
        return f"{year}Q1"
    if "年度报告" in title:
        return f"{year}FY"
    return publish_date


if __name__ == "__main__":
    main()
