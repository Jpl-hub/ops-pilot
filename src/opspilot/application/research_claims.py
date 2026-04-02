from __future__ import annotations

import re
from typing import Any


def _infer_report_period_from_text(text: str) -> str | None:
    year_match = re.search(r"(\d{4})年", text)
    if not year_match:
        return None
    year = year_match.group(1)
    if "半年度" in text or "半年报" in text or "中报" in text:
        return f"{year}H1"
    if "三季度" in text or "第三季度" in text or "三季报" in text:
        return f"{year}Q3"
    if "一季度" in text or "第一季度" in text or "一季报" in text:
        return f"{year}Q1"
    if "年度" in text or "年报" in text:
        return f"{year}FY"
    return None


def _build_claim_cards(
    company: dict[str, Any],
    report: dict[str, Any],
    report_body: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    patterns = [
        (
            "营收同比",
            "G1",
            "percent",
            re.compile(r"营收(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "营收规模",
            "RAW_REVENUE",
            "amount_100m",
            re.compile(r"营收(\d+(?:\.\d+)?)(?:/\d+(?:\.\d+)?)?亿元"),
        ),
        (
            "归母净利润同比",
            "NET_PROFIT_YOY",
            "percent",
            re.compile(r"归母净利润(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "归母净利润规模",
            "RAW_NET_PROFIT",
            "amount_100m",
            re.compile(r"归母净利润(\d+(?:\.\d+)?)(?:/\d+(?:\.\d+)?)?亿元"),
        ),
        (
            "扣非归母净利润同比",
            "G2",
            "percent",
            re.compile(r"扣非归母净利润(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "毛利率",
            "P1",
            "percent",
            re.compile(r"毛利率(\d+(?:\.\d+)?)%"),
        ),
    ]
    for index, (label, metric_key, value_type, pattern) in enumerate(patterns, start=1):
        match = pattern.search(report_body)
        if match is None:
            continue
        claimed_value = float(match.group(1))
        actual_value = _resolve_claim_actual_value(company, metric_key)
        status, delta = _compare_claim_values(claimed_value, actual_value, value_type=value_type)
        evidence_refs = _resolve_claim_evidence_refs(company, metric_key)
        cards.append(
            {
                "claim_id": f"{report['security_code']}-claim-{index}",
                "label": label,
                "metric_key": metric_key,
                "claimed_value": claimed_value,
                "actual_value": actual_value,
                "delta": delta,
                "status": status,
                "excerpt": _clip_claim_excerpt(report_body, match.group(0)),
                "research_chunk_id": f"research-{report['security_code']}-{index}",
                "evidence_refs": evidence_refs,
                "report_title": report["title"],
            }
        )
    return cards


def _resolve_claim_actual_value(company: dict[str, Any], metric_key: str) -> float | None:
    if metric_key in company.get("metrics", {}):
        return company["metrics"][metric_key]
    if metric_key in company.get("raw_metrics", {}):
        raw_value = company["raw_metrics"][metric_key]
        if raw_value is None:
            return None
        return round(raw_value / 1e8, 2)
    if metric_key == "NET_PROFIT_YOY":
        value = company.get("facts", {}).get("net_profit", {}).get("change_pct")
        return None if value is None else float(value)
    return None


def _compare_claim_values(
    claimed_value: float,
    actual_value: float | None,
    *,
    value_type: str,
) -> tuple[str, float | None]:
    if actual_value is None:
        return "insufficient_data", None
    delta = round(actual_value - claimed_value, 2)
    tolerance = 1.5 if value_type == "percent" else max(0.5, abs(claimed_value) * 0.05)
    if abs(delta) <= tolerance:
        return "match", delta
    return "mismatch", delta


def _resolve_claim_evidence_refs(company: dict[str, Any], metric_key: str) -> list[str]:
    metric_map = {
        "RAW_REVENUE": "G1",
        "RAW_NET_PROFIT": "G2",
        "NET_PROFIT_YOY": "G2",
    }
    evidence_metric = metric_map.get(metric_key, metric_key)
    refs = list(company.get("metric_evidence", {}).get(evidence_metric, []))
    if not refs and company.get("summary_chunk_id"):
        refs.append(company["summary_chunk_id"])
    return refs


def _clip_claim_excerpt(text: str, anchor: str, *, radius: int = 180) -> str:
    index = text.find(anchor)
    if index < 0:
        return text[: radius * 2]
    start = max(index - radius // 2, 0)
    end = min(index + len(anchor) + radius, len(text))
    return text[start:end]
