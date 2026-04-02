from __future__ import annotations

import re
from typing import Any


def find_forecast_sentence(report_body: str) -> str | None:
    sentences = [
        item.strip()
        for item in re.split(r"[。\n]", report_body)
        if item.strip()
    ]
    for sentence in sentences:
        if "归母净利" not in sentence and "归母净利润" not in sentence:
            continue
        if "评级" not in sentence:
            continue
        if "预计" not in sentence and "盈利预测" not in sentence:
            continue
        return sentence
    return None


def infer_anchor_year(report_meta: dict[str, Any]) -> int | None:
    text = f"{report_meta.get('title', '')} {report_meta.get('publish_date', '')}"
    match = re.search(r"(20\d{2})", text)
    if match is None:
        return None
    return int(match.group(1))


def extract_forecast_profit_map(sentence: str, *, anchor_year: int | None) -> dict[str, float]:
    profit_map: dict[str, float] = {}
    patterns = [
        re.compile(
            r"(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年(?:(?!\d{2,4}(?:[/、,，~\-—至]\d{2,4})*年)[^。；]){0,40}?归母净利(?:润)?(?:分别)?(?:同增)?(?:为|至)?([+\-]?\d+(?:\.\d+)?(?:[/、,，][+\-]?\d+(?:\.\d+)?)*?)亿元"
        ),
        re.compile(
            r"归母净利(?:润)?(?:分别)?(?:为|至)([+\-]?\d+(?:\.\d+)?(?:[/、,，][+\-]?\d+(?:\.\d+)?)+)亿元"
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(sentence):
            year_text = match.group(1) if match.lastindex and match.lastindex > 1 else ""
            values_text = match.group(match.lastindex)
            years = (
                expand_forecast_year_group(year_text, anchor_year=anchor_year)
                if year_text
                else []
            )
            values = split_forecast_metric_values(values_text, suffix="")
            if not years:
                continue
            if len(years) != len(values):
                continue
            for year, value in zip(years, values):
                profit_map[year] = value
        if profit_map:
            break
    return profit_map


def extract_forecast_metric_map(
    sentence: str,
    *,
    pattern: re.Pattern[str],
    default_years: list[str],
    anchor_year: int | None,
    fallback_pattern: re.Pattern[str] | None,
    suffix: str,
) -> dict[str, float]:
    for match in pattern.finditer(sentence):
        years = expand_forecast_year_group(match.group(1), anchor_year=anchor_year)
        values = split_forecast_metric_values(match.group(2), suffix=suffix)
        if len(years) != len(values):
            continue
        return dict(zip(years, values))
    if fallback_pattern is None:
        return {}
    fallback = fallback_pattern.search(sentence)
    if fallback is None:
        return {}
    values = split_forecast_metric_values(fallback.group(1), suffix=suffix)
    if len(values) != len(default_years):
        return {}
    return dict(zip(default_years, values))


def expand_forecast_year_group(year_text: str, *, anchor_year: int | None) -> list[str]:
    normalized = year_text.replace("—", "-").replace("至", "-").replace("~", "-")
    if "-" in normalized and normalized.count("-") == 1 and "/" not in normalized:
        start_text, end_text = normalized.split("-", 1)
        start_year = normalize_forecast_year(start_text, anchor_year=anchor_year)
        end_year = normalize_forecast_year(end_text, anchor_year=anchor_year)
        if start_year is None or end_year is None or end_year < start_year:
            return []
        return [str(year) for year in range(start_year, end_year + 1)]
    years: list[str] = []
    for token in re.split(r"[/、,，]", normalized):
        year = normalize_forecast_year(token, anchor_year=anchor_year)
        if year is not None:
            years.append(str(year))
    return years


def normalize_forecast_year(year_text: str, *, anchor_year: int | None) -> int | None:
    token = year_text.strip()
    if not token.isdigit():
        return None
    if len(token) == 4:
        return int(token)
    if len(token) == 2:
        base_year = anchor_year or 2000
        century = base_year // 100 * 100
        return century + int(token)
    return None


def split_forecast_metric_values(values_text: str, *, suffix: str) -> list[float]:
    cleaned = values_text.replace(suffix, "")
    if suffix == "x":
        cleaned = cleaned.replace("倍", "").replace("X", "x").replace("x", "")
    cleaned = cleaned.replace("%", "").replace(" ", "")
    return [
        float(item)
        for item in re.split(r"[/、,，]", cleaned)
        if item
    ]
