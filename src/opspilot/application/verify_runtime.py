from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.application.document_pipeline import _utcnow_iso, _write_json
from opspilot.application.runtime_manifests import (
    _build_verify_run_id,
    _load_verify_run_manifest,
    _verify_run_detail_path,
    _write_verify_run_manifest,
)

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


def _build_verify_status_label(
    *,
    match_count: int,
    mismatch_count: int,
    insufficient_count: int,
) -> str:
    if mismatch_count > 0:
        return "存在分歧"
    if insufficient_count > 0:
        return "待补证"
    if match_count > 0:
        return "已一致"
    return "已完成"


def _persist_verify_run(
    service: Any,
    payload: dict[str, Any],
    *,
    user_role: str,
    report_title: str | None = None,
) -> dict[str, Any]:
    run_id = _build_verify_run_id(payload.get("company_name") or "company")
    detail_path = _verify_run_detail_path(service.settings, run_id)
    created_at = _utcnow_iso()
    _write_json(detail_path, {**payload, "run_id": run_id})

    claim_cards = payload.get("claim_cards", [])
    match_count = sum(1 for item in claim_cards if item.get("status") == "match")
    mismatch_count = sum(1 for item in claim_cards if item.get("status") == "mismatch")
    insufficient_count = sum(1 for item in claim_cards if item.get("status") == "insufficient_data")
    research_meta = payload.get("report_meta", {})
    command_surface = payload.get("verify_command_surface", {})
    manifest = _load_verify_run_manifest(service.settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    records.insert(
        0,
        {
            "run_id": run_id,
            "company_name": payload.get("company_name"),
            "report_period": payload.get("report_period"),
            "user_role": user_role,
            "report_title": research_meta.get("title") or report_title,
            "source_name": research_meta.get("source_name"),
            "publish_date": research_meta.get("publish_date"),
            "headline": command_surface.get("headline") or research_meta.get("title"),
            "status_label": _build_verify_status_label(
                match_count=match_count,
                mismatch_count=mismatch_count,
                insufficient_count=insufficient_count,
            ),
            "match_count": match_count,
            "mismatch_count": mismatch_count,
            "insufficient_count": insufficient_count,
            "detail_path": str(detail_path),
            "created_at": created_at,
        },
    )
    manifest["records"] = records[:200]
    _write_verify_run_manifest(service.settings, manifest)
    return {**payload, "run_id": run_id}


def _verify_runs(
    service: Any,
    *,
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    report_title: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    records = [
        item
        for item in _load_verify_run_manifest(service.settings)["records"]
        if item.get("user_role") == user_role
        and (company_name is None or item.get("company_name") == company_name)
        and (report_period is None or item.get("report_period") == report_period)
        and (report_title is None or item.get("report_title") == report_title)
    ]
    return {
        "company_name": company_name,
        "report_period": report_period,
        "user_role": user_role,
        "report_title": report_title,
        "total": len(records),
        "runs": records[:limit],
    }


def _verify_run_detail(service: Any, run_id: str) -> dict[str, Any]:
    record = next(
        (
            item
            for item in _load_verify_run_manifest(service.settings)["records"]
            if item.get("run_id") == run_id
        ),
        None,
    )
    if record is None:
        raise ValueError(f"未找到观点核验运行：{run_id}")
    detail_path = Path(record["detail_path"])
    if not detail_path.exists():
        raise ValueError(f"未找到观点核验详情：{run_id}")
    try:
        with detail_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"观点核验记录损坏：{run_id}") from exc
    payload["run_meta"] = {
        "run_id": run_id,
        "created_at": record.get("created_at"),
        "company_name": record.get("company_name"),
        "report_period": record.get("report_period"),
        "user_role": record.get("user_role"),
        "report_title": record.get("report_title"),
        "source_name": record.get("source_name"),
        "publish_date": record.get("publish_date"),
        "status_label": record.get("status_label"),
    }
    return payload
