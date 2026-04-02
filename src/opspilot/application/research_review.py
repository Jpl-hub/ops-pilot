from __future__ import annotations

from typing import Any
import re

from opspilot.application.research_claims import _infer_report_period_from_text


def _build_claim_evidence(
    repository: Any,
    report: dict[str, Any],
    report_meta: dict[str, Any],
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for card in claim_cards:
        evidence.append(
            {
                "chunk_id": card["research_chunk_id"],
                "company_name": report["company_name"],
                "report_period": _infer_report_period_from_text(report_meta["title"]) or report_meta["publish_date"],
                "source_title": report_meta["title"],
                "source_type": "research_report_excerpt",
                "page": 1,
                "excerpt": card["excerpt"],
                "fingerprint": f"{report['security_code']}-{card['claim_id']}",
                "source_url": report_meta["source_url"],
                "local_path": report["local_path"],
            }
        )
        evidence.extend(repository.resolve_evidence(card["evidence_refs"]))
    for card in forecast_cards or []:
        evidence.append(
            {
                "chunk_id": card["research_chunk_id"],
                "company_name": report["company_name"],
                "report_period": card["report_period"],
                "source_title": report_meta["title"],
                "source_type": "research_forecast_excerpt",
                "page": 1,
                "excerpt": card["excerpt"],
                "fingerprint": f"{report['security_code']}-{card['forecast_id']}",
                "source_url": report_meta["source_url"],
                "local_path": report["local_path"],
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in evidence:
        if item["chunk_id"] in seen_ids:
            continue
        seen_ids.add(item["chunk_id"])
        deduped.append(item)
    return deduped


def _build_claim_evidence_groups(
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_by_id = {item["chunk_id"]: item for item in evidence}
    groups: list[dict[str, Any]] = []
    for card in claim_cards:
        refs = [card["research_chunk_id"], *card.get("evidence_refs", [])]
        items = [evidence_by_id[chunk_id] for chunk_id in refs if chunk_id in evidence_by_id]
        groups.append(
            {
                "code": card["claim_id"],
                "title": card["label"],
                "subtitle": f"核验结果：{card['status']}",
                "items": items,
                "anchor_terms": [card["label"]],
            }
        )
    for card in forecast_cards:
        refs = [card["research_chunk_id"]]
        items = [evidence_by_id[chunk_id] for chunk_id in refs if chunk_id in evidence_by_id]
        groups.append(
            {
                "code": card["forecast_id"],
                "title": f"{card['report_period']} 盈利预测",
                "subtitle": f"预测利润 {card['forecast_value']:.2f} 亿元",
                "items": items,
                "anchor_terms": [card["report_period"], "归母净利润"],
            }
        )
    return groups


def _render_claim_answer(
    report_meta: dict[str, Any],
    report_period: str,
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> str:
    matched = sum(1 for item in claim_cards if item["status"] == "match")
    mismatched = sum(1 for item in claim_cards if item["status"] == "mismatch")
    insufficient = sum(1 for item in claim_cards if item["status"] == "insufficient_data")
    rating_text = _format_rating_text(report_meta)
    return (
        f"### 研报观点核验\n"
        f"- 研报：**{report_meta['title']}**\n"
        f"- 核验报期：**{report_period}**\n"
        f"- 投资评级：**{rating_text}**\n"
        f"- 评级动作：**{report_meta.get('rating_change') or '未披露'}**\n"
        f"- 目标价：**{_format_target_price(report_meta.get('target_price'))}**\n"
        f"- 匹配：**{matched}** 条\n"
        f"- 偏差：**{mismatched}** 条\n"
        f"- 待补充：**{insufficient}** 条\n"
        f"- 盈利预测：**{len(forecast_cards)}** 个年度"
    )


def _build_claim_chart(claim_cards: list[dict[str, Any]]) -> dict[str, Any]:
    labels = ["match", "mismatch", "insufficient_data"]
    return {
        "type": "bar",
        "title": "研报观点核验结果",
        "options": {
            "xAxis": {"type": "category", "data": ["匹配", "偏差", "待补充"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [sum(1 for item in claim_cards if item["status"] == label) for label in labels],
                }
            ],
        },
    }


def _summarize_forecast_cards(forecast_cards: list[dict[str, Any]]) -> dict[str, Any]:
    if not forecast_cards:
        return {}
    headline = min(
        forecast_cards,
        key=lambda item: item.get("report_period", "9999FY"),
    )
    headline_year = headline.get("report_period", "").replace("FY", "") or None
    return {
        "headline_year": headline_year,
        "headline_value": headline.get("forecast_value"),
        "headline_pe": headline.get("pe_value"),
    }


def _build_research_compare_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [item["source_name"] or item["title"] for item in rows]
    return {
        "type": "bar",
        "title": "研报目标价与首年利润预测对比",
        "options": {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["目标价", "首年利润预测"]},
            "xAxis": {"type": "category", "data": labels},
            "yAxis": [
                {"type": "value", "name": "目标价(元)"},
                {"type": "value", "name": "利润预测(亿元)"},
            ],
            "series": [
                {
                    "name": "目标价",
                    "type": "bar",
                    "data": [item.get("target_price") for item in rows],
                },
                {
                    "name": "首年利润预测",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [item.get("headline_forecast_value") for item in rows],
                },
            ],
        },
    }


def _format_rating_text(report_meta: dict[str, Any]) -> str:
    rating_parts = [
        part for part in (report_meta.get("rating_action"), report_meta.get("rating_label")) if part
    ]
    if rating_parts:
        return "".join(rating_parts)
    rating_code = report_meta.get("rating_code")
    if isinstance(rating_code, str) and re.fullmatch(r"[A-Z]{1,3}", rating_code):
        return "未披露"
    return rating_code or "未披露"


def _format_target_price(value: float | None) -> str:
    if value is None:
        return "未披露"
    return f"{value:.2f} 元"
