from __future__ import annotations

from typing import Any

from opspilot.application.research_review import _format_target_price


def _build_research_compare_sort_options() -> dict[str, str]:
    return {
        "priority": "优先看分歧",
        "latest": "按时间最新",
        "target_price_desc": "目标价从高到低",
        "forecast_desc": "首年利润预测从高到低",
    }


def _build_research_compare_filter_options() -> dict[str, str]:
    return {
        "all": "全部研报",
        "supported": "仅报期已对齐",
        "target_price": "仅看含目标价",
        "forecast": "仅看含盈利预测",
        "divergence": "仅看分歧信号",
    }


def _label_research_compare_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labeled_rows = [dict(row) for row in rows]
    if not labeled_rows:
        return labeled_rows

    target_price_rows = [row for row in labeled_rows if row.get("target_price") is not None]
    if len(target_price_rows) >= 2:
        high_target = max(target_price_rows, key=lambda row: row["target_price"])
        low_target = min(target_price_rows, key=lambda row: row["target_price"])
        high_target.setdefault("signal_tags", []).append("目标价最高")
        low_target.setdefault("signal_tags", []).append("目标价最低")

    forecast_rows = [row for row in labeled_rows if row.get("headline_forecast_value") is not None]
    if len(forecast_rows) >= 2:
        high_forecast = max(forecast_rows, key=lambda row: row["headline_forecast_value"])
        low_forecast = min(forecast_rows, key=lambda row: row["headline_forecast_value"])
        high_forecast.setdefault("signal_tags", []).append("预测最乐观")
        low_forecast.setdefault("signal_tags", []).append("预测最谨慎")

    complete_rows = [row for row in labeled_rows if row.get("forecast_count")]
    if complete_rows:
        richest = max(
            complete_rows,
            key=lambda row: (
                row.get("forecast_count", 0),
                row.get("claim_signal_count", 0),
                row.get("target_price") is not None,
            ),
        )
        richest.setdefault("signal_tags", []).append("信息最完整")

    rating_values = {
        row["rating_text"]
        for row in labeled_rows
        if row.get("rating_text") and row["rating_text"] != "未披露"
    }
    rating_diverges = len(rating_values) > 1
    for row in labeled_rows:
        tags = row.setdefault("signal_tags", [])
        if row.get("is_period_supported"):
            tags.append("报期已对齐")
        else:
            tags.append("报期待核实")
        if row.get("target_price") is not None:
            tags.append("含目标价")
        if row.get("headline_forecast_value") is not None:
            tags.append("含盈利预测")
        if rating_diverges and row.get("rating_text") and row["rating_text"] != "未披露":
            tags.append(f"评级:{row['rating_text']}")

        row["signal_tags"] = list(dict.fromkeys(tags))
        row["divergence_score"] = _compute_research_divergence_score(row)
    return labeled_rows


def _compute_research_divergence_score(row: dict[str, Any]) -> int:
    score = 0
    for tag in row.get("signal_tags", []):
        if tag in {"目标价最高", "目标价最低", "预测最乐观", "预测最谨慎"}:
            score += 2
        elif tag.startswith("评级:"):
            score += 2
        elif tag in {"含目标价", "含盈利预测", "信息最完整"}:
            score += 1
    if not row.get("is_period_supported"):
        score -= 1
    return score


def _filter_research_compare_rows(
    rows: list[dict[str, Any]],
    filter_mode: str,
) -> list[dict[str, Any]]:
    if filter_mode == "supported":
        return [row for row in rows if row.get("is_period_supported")]
    if filter_mode == "target_price":
        return [row for row in rows if row.get("target_price") is not None]
    if filter_mode == "forecast":
        return [row for row in rows if row.get("headline_forecast_value") is not None]
    if filter_mode == "divergence":
        return [
            row
            for row in rows
            if any(
                tag in {"目标价最高", "目标价最低", "预测最乐观", "预测最谨慎"}
                or tag.startswith("评级:")
                for tag in row.get("signal_tags", [])
            )
        ]
    return rows


def _sort_research_compare_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "latest":
        return sorted(
            rows,
            key=lambda row: (
                row.get("publish_date") or "",
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    if sort_by == "target_price_desc":
        return sorted(
            rows,
            key=lambda row: (
                row.get("target_price") is not None,
                row.get("target_price") or -1,
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    if sort_by == "forecast_desc":
        return sorted(
            rows,
            key=lambda row: (
                row.get("headline_forecast_value") is not None,
                row.get("headline_forecast_value") or -1,
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    return sorted(
        rows,
        key=lambda row: (
            row.get("divergence_score", 0),
            row.get("forecast_count", 0),
            row.get("claim_signal_count", 0),
            row.get("publish_date") or "",
        ),
        reverse=True,
    )


def _build_research_compare_insights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    rated_rows = [row for row in rows if row.get("rating_text") and row["rating_text"] != "未披露"]
    rating_values = sorted({row["rating_text"] for row in rated_rows})
    if len(rating_values) == 1 and rating_values:
        insights.append(
            {
                "kind": "consensus",
                "title": "评级观点一致",
                "detail": f"{len(rated_rows)} 篇研报均给出 {rating_values[0]}。",
            }
        )
    elif len(rating_values) > 1:
        insights.append(
            {
                "kind": "divergence",
                "title": "评级存在分歧",
                "detail": f"当前覆盖研报出现 {', '.join(rating_values)} 等不同评级。",
            }
        )

    target_price_rows = [row for row in rows if row.get("target_price") is not None]
    if len(target_price_rows) >= 2:
        high = max(target_price_rows, key=lambda row: row["target_price"])
        low = min(target_price_rows, key=lambda row: row["target_price"])
        spread = round(high["target_price"] - low["target_price"], 2)
        kind = "divergence" if spread >= 10 else "consensus"
        title = "目标价分歧明显" if spread >= 10 else "目标价较为集中"
        insights.append(
            {
                "kind": kind,
                "title": title,
                "detail": (
                    f"最高为 {high['source_name'] or high['title']} 的 {_format_target_price(high['target_price'])}，"
                    f"最低为 {low['source_name'] or low['title']} 的 {_format_target_price(low['target_price'])}，"
                    f"差值 {spread:.2f} 元。"
                ),
            }
        )

    forecast_rows = [row for row in rows if row.get("headline_forecast_value") is not None]
    if len(forecast_rows) >= 2:
        high = max(forecast_rows, key=lambda row: row["headline_forecast_value"])
        low = min(forecast_rows, key=lambda row: row["headline_forecast_value"])
        spread = round(high["headline_forecast_value"] - low["headline_forecast_value"], 2)
        kind = "divergence" if spread >= 3 else "consensus"
        title = "首年利润预测差异较大" if spread >= 3 else "首年利润预测接近"
        insights.append(
            {
                "kind": kind,
                "title": title,
                "detail": (
                    f"最高预测来自 {high['source_name'] or high['title']}，为 {high['headline_forecast_value']:.2f} 亿元；"
                    f"最低预测为 {low['headline_forecast_value']:.2f} 亿元，区间 {spread:.2f} 亿元。"
                ),
            }
        )

    return insights


def _build_research_timeline_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        institution = row.get("source_name") or "机构未披露"
        groups.setdefault(institution, []).append(dict(row))

    timeline_groups: list[dict[str, Any]] = []
    for institution, items in groups.items():
        ordered_items = sorted(items, key=lambda item: item.get("publish_date") or "")
        transitions = []
        same_rating_pairs = 0
        comparable_pairs = 0
        for previous, current in zip(ordered_items, ordered_items[1:]):
            transition = _build_research_transition(previous, current)
            transitions.append(transition)
            if (
                transition["is_rating_comparable"]
                and transition["rating_from"] != "未披露"
                and transition["rating_to"] != "未披露"
            ):
                comparable_pairs += 1
                if transition["rating_from"] == transition["rating_to"]:
                    same_rating_pairs += 1
        latest_item = ordered_items[-1]
        latest_transition = transitions[-1] if transitions else None
        timeline_groups.append(
            {
                "institution": institution,
                "report_count": len(ordered_items),
                "latest_rating": latest_item.get("rating_text") or "未披露",
                "latest_target_price": latest_item.get("target_price"),
                "latest_forecast_value": latest_item.get("headline_forecast_value"),
                "latest_transition": latest_transition,
                "rating_stability": (
                    round(same_rating_pairs / comparable_pairs * 100, 2)
                    if comparable_pairs > 0
                    else None
                ),
                "items": ordered_items,
                "transitions": transitions,
            }
        )
    return sorted(
        timeline_groups,
        key=lambda item: (
            item["report_count"],
            item.get("latest_transition", {}).get("publish_date") if item.get("latest_transition") else "",
            item["institution"],
        ),
        reverse=True,
    )


def _build_research_transition(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    is_same_period = (
        previous.get("report_period")
        and previous.get("report_period") == current.get("report_period")
    )
    is_same_forecast_year = (
        previous.get("headline_forecast_year")
        and previous.get("headline_forecast_year") == current.get("headline_forecast_year")
    )
    rating_from = previous.get("rating_text") or "未披露"
    rating_to = current.get("rating_text") or "未披露"
    if not is_same_period:
        transition_kind = "not_comparable"
        summary = "报期不同，不直接比较评级和目标价"
    elif rating_from != "未披露" and rating_to != "未披露" and rating_from != rating_to:
        transition_kind = "rating_changed"
        summary = f"评级由 {rating_from} 调整为 {rating_to}"
    else:
        transition_kind = "stable"
        summary = f"评级维持 {rating_to}"

    target_delta = None
    if (
        is_same_period
        and previous.get("target_price") is not None
        and current.get("target_price") is not None
    ):
        target_delta = round(current["target_price"] - previous["target_price"], 2)
        if target_delta != 0:
            transition_kind = "target_changed"
            direction = "上调" if target_delta > 0 else "下调"
            summary = f"目标价{direction} {abs(target_delta):.2f} 元"

    forecast_delta = None
    if (
        is_same_forecast_year
        and previous.get("headline_forecast_value") is not None
        and current.get("headline_forecast_value") is not None
    ):
        forecast_delta = round(
            current["headline_forecast_value"] - previous["headline_forecast_value"],
            2,
        )

    return {
        "publish_date": current.get("publish_date"),
        "title": current.get("title"),
        "report_period": current.get("report_period"),
        "previous_report_period": previous.get("report_period"),
        "source_url": current.get("source_url"),
        "attachment_url": current.get("attachment_url"),
        "rating_from": rating_from,
        "rating_to": rating_to,
        "target_delta": target_delta,
        "forecast_delta": forecast_delta,
        "transition_kind": transition_kind,
        "summary": summary,
        "is_rating_comparable": bool(is_same_period),
        "is_forecast_comparable": bool(is_same_forecast_year),
        "forecast_year": current.get("headline_forecast_year"),
    }
