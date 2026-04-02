from __future__ import annotations

from html import unescape
from pathlib import Path
from typing import Any
import json
import re

from opspilot.application.research_claims import (
    _clip_claim_excerpt,
    _infer_report_period_from_text,
)
from opspilot.application.research_forecast import (
    extract_forecast_metric_map,
    extract_forecast_profit_map,
    find_forecast_sentence,
    infer_anchor_year,
)


def _select_research_report(
    reports: list[dict[str, Any]],
    *,
    company_name: str,
    report_period: str | None,
    report_title: str | None,
    available_periods: set[str] | None = None,
) -> dict[str, Any] | None:
    matches = [report for report in reports if report.get("company_name") == company_name]
    title_matches = matches
    if report_title:
        title_matches = [report for report in matches if report_title in report.get("title", "")]
        matches = title_matches
    if report_period:
        period_matches = [
            report
            for report in matches
            if _infer_report_period_from_text(report.get("title", "")) == report_period
        ]
        if not period_matches:
            if report_title and title_matches:
                matches = title_matches
            else:
                return None
        else:
            matches = period_matches
    matches.sort(key=lambda item: item.get("publish_date", ""), reverse=True)
    if report_period is None:
        matches.sort(key=lambda item: _research_report_content_score(item), reverse=True)
        matches.sort(key=lambda item: _research_report_bucket(item, available_periods))
    return matches[0] if matches else None


def _extract_research_payload(report_html: str) -> dict[str, Any]:
    match = re.search(r"var\s+zwinfo\s*=\s*(\{.*?\});", report_html, re.S)
    if match is None:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_research_meta(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    report_body = payload.get("notice_content", "")
    rating_info = _extract_research_rating(report_body, payload)
    target_price_info = _extract_target_price(report_body)
    publish_date = payload.get("notice_date") or report.get("publish_date", "")
    return {
        "title": payload.get("notice_title") or report["title"],
        "publish_date": publish_date.split(" ")[0] if publish_date else "",
        "source_url": report.get("detail_url") or report.get("source_url") or "",
        "attachment_url": payload.get("attach_url"),
        "source_name": payload.get("source_sample_name"),
        "researcher": payload.get("researcher"),
        "rating_code": payload.get("rating"),
        "rating_label": rating_info.get("label"),
        "rating_action": rating_info.get("action"),
        "rating_change": _classify_rating_action(rating_info.get("action")),
        "target_price": target_price_info.get("value"),
        "target_price_excerpt": target_price_info.get("excerpt"),
    }


def _extract_research_body(report_html: str, payload: dict[str, Any] | None = None) -> str:
    if payload and payload.get("notice_content"):
        return _normalize_research_text(str(payload["notice_content"]))
    match = re.search(r'<div id="ctx-content"[^>]*>(.*?)</div>', report_html, re.S)
    body = match.group(1) if match else report_html
    cleaned = re.sub(r"<br\s*/?>", "\n", body)
    cleaned = re.sub(r"</p>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return _normalize_research_text(cleaned)


def _build_forecast_cards(
    report: dict[str, Any],
    report_body: str,
    report_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    sentence = find_forecast_sentence(report_body)
    if sentence is None:
        return []
    anchor_year = infer_anchor_year(report_meta)
    profit_map = extract_forecast_profit_map(sentence, anchor_year=anchor_year)
    if not profit_map:
        return []
    years = sorted(profit_map.keys())
    yoy_map = extract_forecast_metric_map(
        sentence,
        pattern=re.compile(
            r"(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年归母净利(?:润)?(?:同增|同比增长|同比)([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"
        ),
        default_years=years,
        anchor_year=anchor_year,
        fallback_pattern=re.compile(r"同比([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"),
        suffix="%",
    )
    pe_map = extract_forecast_metric_map(
        sentence,
        pattern=re.compile(
            r"(?:对应)?(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年(?:PE|市盈率)(?:为)?([0-9.xX倍、/,，]+)"
        ),
        default_years=years,
        anchor_year=anchor_year,
        fallback_pattern=re.compile(r"(?:对应)?(?:PE|市盈率)(?:为)?([0-9.xX倍、/,，]+)"),
        suffix="x",
    )

    cards: list[dict[str, Any]] = []
    security_code = report.get("security_code") or report.get("company_name") or "research"
    for year in years:
        cards.append(
            {
                "forecast_id": f"{security_code}-forecast-{year}",
                "label": f"{year}年归母净利润预测",
                "report_period": f"{year}FY",
                "forecast_value": profit_map.get(year),
                "yoy_value": yoy_map.get(year),
                "pe_value": pe_map.get(year),
                "rating_label": report_meta.get("rating_label"),
                "rating_action": report_meta.get("rating_action"),
                "excerpt": _clip_claim_excerpt(report_body, sentence, radius=240),
                "research_chunk_id": f"research-{security_code}-forecast-{year}",
            }
        )
    return cards


def _research_report_bucket(report: dict[str, Any], available_periods: set[str] | None) -> int:
    inferred_period = _infer_report_period_from_text(report.get("title", ""))
    if inferred_period and (not available_periods or inferred_period in available_periods):
        return 0
    if inferred_period is None:
        return 1
    return 2


def _build_research_report_insight(report: dict[str, Any]) -> dict[str, Any] | None:
    local_path = _resolve_report_local_path(report.get("local_path"))
    if local_path is None or not local_path.exists():
        return None
    report_html = local_path.read_text(encoding="utf-8", errors="ignore")
    payload = _extract_research_payload(report_html)
    report_meta = _build_research_meta(report, payload)
    report_body = _extract_research_body(report_html, payload)
    forecast_cards = _build_forecast_cards(report, report_body, report_meta)
    claim_signal_count = sum(
        1
        for pattern in (
            r"营收(?:同比|\d)",
            r"归母净利润(?:同比|\d)",
            r"扣非归母净利润(?:同比|\d)",
            r"毛利率\d",
        )
        if re.search(pattern, report_body)
    )
    return {
        "report_meta": report_meta,
        "report_body": report_body,
        "forecast_cards": forecast_cards,
        "claim_signal_count": claim_signal_count,
    }


def _resolve_report_local_path(raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    normalized = Path(str(raw_path).replace("\\", "/"))
    if normalized.is_absolute():
        return normalized
    return (Path.cwd() / normalized).resolve()


def _research_report_content_score(report: dict[str, Any]) -> tuple[int, int]:
    insight = _build_research_report_insight(report)
    if insight is None:
        return (0, 0)
    return (len(insight["forecast_cards"]), insight["claim_signal_count"])


def _extract_research_rating(report_body: str, payload: dict[str, Any]) -> dict[str, str]:
    match = re.search(
        r'(维持|上调至|上调为|下调至|下调为|首次覆盖给予|首次给予|给予)?[“”"]([^“”"，。]{2,8})[“”"]?评级',
        report_body,
    )
    if match and "投资" not in match.group(2):
        return {
            "action": (match.group(1) or "").strip(),
            "label": match.group(2).strip(),
        }
    rating_code = payload.get("rating")
    if isinstance(rating_code, str) and re.fullmatch(r"[A-Z]{1,3}", rating_code):
        return {}
    if rating_code:
        return {"action": "", "label": str(rating_code)}
    return {}


def _classify_rating_action(action: str | None) -> str | None:
    if not action:
        return None
    if action.startswith("上调"):
        return "上调"
    if action.startswith("下调"):
        return "下调"
    if action.startswith("首次"):
        return "首次覆盖"
    if action.startswith("给予"):
        return "首次给出"
    if action.startswith("维持"):
        return "维持"
    return action


def _extract_target_price(report_body: str) -> dict[str, Any]:
    match = re.search(r"目标价(?:为|至)?\s*([0-9]+(?:\.[0-9]+)?)元", report_body)
    if match is None:
        return {}
    return {
        "value": float(match.group(1)),
        "excerpt": _clip_claim_excerpt(report_body, match.group(0), radius=180),
    }


def _normalize_research_text(text: str) -> str:
    cleaned = unescape(text).replace("&nbsp;", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", cleaned).strip()
