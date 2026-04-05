from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.application.document_pipeline import _utcnow_iso, _write_json
from opspilot.application.runtime_manifests import (
    _build_score_run_id,
    _load_score_run_manifest,
    _score_run_detail_path,
    _write_score_run_manifest,
)


def _build_score_status_label(*, total_score: float, risk_count: int) -> str:
    if total_score < 60 or risk_count >= 4:
        return "重点盯防"
    if total_score < 75 or risk_count >= 2:
        return "持续跟踪"
    if total_score >= 85 and risk_count == 0:
        return "状态稳健"
    return "继续观察"


def _persist_score_run(
    service: Any,
    payload: dict[str, Any],
    *,
    user_role: str,
) -> dict[str, Any]:
    run_id = _build_score_run_id(payload.get("company_name") or "company")
    detail_path = _score_run_detail_path(service.settings, run_id)
    created_at = _utcnow_iso()
    scorecard = payload.get("scorecard", {})
    total_score = float(scorecard.get("total_score") or 0)
    risk_count = len(scorecard.get("risk_labels", []))
    opportunity_count = len(scorecard.get("opportunity_labels", []))
    command_surface = payload.get("score_command_surface", {})

    detail_payload = {
        **payload,
        "run_id": run_id,
        "created_at": created_at,
        "user_role": user_role,
    }
    _write_json(detail_path, detail_payload)

    manifest = _load_score_run_manifest(service.settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    records.insert(
        0,
        {
            "run_id": run_id,
            "company_name": payload.get("company_name"),
            "report_period": payload.get("report_period"),
            "user_role": user_role,
            "headline": command_surface.get("headline") or payload.get("company_name"),
            "title": command_surface.get("title") or f"{payload.get('company_name')} 经营体检",
            "grade": scorecard.get("grade"),
            "total_score": total_score,
            "risk_count": risk_count,
            "opportunity_count": opportunity_count,
            "status_label": _build_score_status_label(
                total_score=total_score,
                risk_count=risk_count,
            ),
            "detail_path": str(detail_path),
            "created_at": created_at,
        },
    )
    manifest["records"] = records[:200]
    _write_score_run_manifest(service.settings, manifest)
    return detail_payload


def _score_runs(
    service: Any,
    *,
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
) -> dict[str, Any]:
    records = [
        item
        for item in _load_score_run_manifest(service.settings)["records"]
        if item.get("user_role") == user_role
        and (company_name is None or item.get("company_name") == company_name)
        and (report_period is None or item.get("report_period") == report_period)
    ]
    return {
        "company_name": company_name,
        "report_period": report_period,
        "user_role": user_role,
        "total": len(records),
        "runs": records[:limit],
    }


def _score_run_detail(service: Any, run_id: str) -> dict[str, Any]:
    record = next(
        (
            item
            for item in _load_score_run_manifest(service.settings)["records"]
            if item.get("run_id") == run_id
        ),
        None,
    )
    if record is None:
        raise ValueError(f"未找到经营诊断运行：{run_id}")
    detail_path = Path(record["detail_path"])
    if not detail_path.exists():
        raise ValueError(f"未找到经营诊断详情：{run_id}")
    try:
        with detail_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"经营诊断记录损坏：{run_id}") from exc
    payload["run_meta"] = {
        "run_id": run_id,
        "created_at": record.get("created_at"),
        "company_name": record.get("company_name"),
        "report_period": record.get("report_period"),
        "user_role": record.get("user_role"),
        "headline": record.get("headline"),
        "grade": record.get("grade"),
        "total_score": record.get("total_score"),
        "risk_count": record.get("risk_count"),
        "opportunity_count": record.get("opportunity_count"),
        "status_label": record.get("status_label"),
    }
    return payload
