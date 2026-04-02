from __future__ import annotations

from typing import Any

def _build_verify_command_surface(
    *,
    company: dict[str, Any],
    research_meta: dict[str, Any],
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    match_count = sum(1 for item in claim_cards if item["status"] == "match")
    mismatch_count = sum(1 for item in claim_cards if item["status"] == "mismatch")
    dominant = next((item for item in claim_cards if item["status"] != "match"), None) or (claim_cards[0] if claim_cards else None)
    return {
        "title": f"{company['company_name']} 研报核验",
        "headline": dominant["label"] if dominant else research_meta["title"],
        "metric": f"{match_count} 匹配 / {mismatch_count} 偏差",
        "intensity": min(100, 34 + mismatch_count * 22 + match_count * 8),
        "institution": research_meta.get("source_name") or "未披露",
        "watch_items": [
            {"label": "匹配", "value": str(match_count)},
            {"label": "偏差", "value": str(mismatch_count)},
            {"label": "预测", "value": str(len(forecast_cards))},
        ],
        "dominant_signal": {
            "label": "当前核验焦点",
            "value": dominant["status"] if dominant else "等待核验",
            "tone": "risk" if dominant and dominant["status"] == "mismatch" else "success",
        },
    }


def _build_verify_delta_tape(
    *,
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, card in enumerate(claim_cards[:4]):
        status = card["status"]
        tone = "success" if status == "match" else "risk" if status == "mismatch" else "warning"
        intensity = 30 if status == "match" else 86 if status == "mismatch" else 58
        tape.append(
            {
                "step": index + 1,
                "label": card["metric_key"],
                "value": card["label"],
                "tone": tone,
                "intensity": intensity,
            }
        )
    if forecast_cards:
        tape.append(
            {
                "step": len(tape) + 1,
                "label": "预测",
                "value": f"{len(forecast_cards)} 个年度",
                "tone": "accent",
                "intensity": 44,
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待核验",
                "value": "暂无观点卡",
                "tone": "accent",
                "intensity": 0,
            }
        )
    return tape
