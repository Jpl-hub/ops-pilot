from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opspilot.config import Settings
from opspilot.application.document_pipeline import (
    _document_pipeline_artifact_path,
    _normalize_report_period,
    _utcnow_iso,
    _write_json,
)


def _load_task_board_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_task_board.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": {}}
        _write_json(manifest_path, payload)
        return payload

    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    payload.setdefault("generated_at", _utcnow_iso())
    payload.setdefault("records", {})
    payload["record_count"] = len(payload["records"])
    return payload


def _write_task_board_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", {}))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_task_board.json"
    _write_json(manifest_path, payload)


def _load_industry_brain_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_industry_brain.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
    }


def _write_industry_brain_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_industry_brain.json"
    _write_json(manifest_path, payload)


def _append_industry_brain_snapshot(settings: Settings, payload: dict[str, Any]) -> None:
    manifest = _load_industry_brain_manifest(settings)
    records = list(manifest.get("records", []))
    records.append(
        {
            "refreshed_at": payload.get("stream", {}).get("refreshed_at"),
            "report_period": payload.get("report_period"),
            "user_role": payload.get("user_role"),
            "role_label": payload.get("role_label"),
            "focus_title": payload.get("focus_title"),
            "stream": payload.get("stream", {}),
            "sequence": payload.get("stream", {}).get("sequence"),
            "sector_tags": payload.get("sector_tags", []),
            "metrics": payload.get("metrics", []),
            "charts": payload.get("charts", []),
            "market_tape": payload.get("market_tape", []),
            "brain_command_surface": payload.get("brain_command_surface", {}),
            "brain_signal_tape": payload.get("brain_signal_tape", []),
            "radar_events": payload.get("radar_events", []),
            "live_events": payload.get("live_events", []),
            "external_signal_stream": payload.get("external_signal_stream", {}),
            "streaming_snapshot": payload.get("streaming_snapshot", {}),
            "streaming_timeline": payload.get("streaming_timeline", {}),
            "streaming_heatmap": payload.get("streaming_heatmap", {}),
            "streaming_anomalies": payload.get("streaming_anomalies", {}),
            "attention_matrix": payload.get("attention_matrix", []),
            "execution_flash": payload.get("execution_flash", []),
            "top_risk_companies": payload.get("top_risk_companies", []),
            "document_pipeline": payload.get("document_pipeline", {}),
        }
    )
    manifest["records"] = records[-36:]
    _write_industry_brain_manifest(settings, manifest)


def _load_watchboard_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
    }


def _write_watchboard_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard.json"
    _write_json(manifest_path, payload)


def _find_watchboard_record(
    settings: Settings,
    *,
    company_name: str,
    user_role: str,
    report_period: str,
) -> dict[str, Any] | None:
    manifest = _load_watchboard_manifest(settings)
    return next(
        (
            item
            for item in manifest["records"]
            if item.get("company_name") == company_name
            and item.get("user_role") == user_role
            and item.get("report_period") == report_period
        ),
        None,
    )


def _load_watchboard_runs_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard_runs.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
    }


def _write_watchboard_runs_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard_runs.json"
    _write_json(manifest_path, payload)


def _build_watchboard_run_id(user_role: str, report_period: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{user_role}-{report_period.lower()}"


def _build_task_id(report_period: str, company_name: str, priority: str, title: str) -> str:
    normalized_title = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", title).strip("-").lower()
    normalized_company = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{report_period}-{normalized_company}-{priority.lower()}-{normalized_title}"[:160]


def _load_alert_board_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_alert_board.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": {}}
        _write_json(manifest_path, payload)
        return payload

    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    payload.setdefault("generated_at", _utcnow_iso())
    payload.setdefault("records", {})
    payload["record_count"] = len(payload["records"])
    return payload


def _write_alert_board_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", {}))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_alert_board.json"
    _write_json(manifest_path, payload)


def _build_alert_id(alert: dict[str, Any]) -> str:
    normalized_company = re.sub(
        r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", alert["company_name"]
    ).strip("-").lower()
    return (
        f"{alert['report_period']}-{normalized_company}-"
        f"{alert.get('previous_period') or 'na'}-{alert['risk_count']}-{alert['risk_delta']}"
    )[:160]


def _load_document_pipeline_job_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_jobs.json"
    parsed_reports = _load_manifest_records(
        settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    )
    desired_jobs: dict[tuple[str, str], dict[str, Any]] = {}
    for record in parsed_reports:
        report_id = record.get("report_id")
        if not report_id:
            continue
        for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
            artifact_path = _document_pipeline_artifact_path(settings, stage, record)
            status = "pending"
            if artifact_path.exists():
                status = "completed"
            desired_jobs[(report_id, stage)] = {
                "stage": stage,
                "report_id": report_id,
                "company_name": record.get("company_name"),
                "security_code": record.get("security_code"),
                "report_period": _normalize_report_period(record.get("title", "")),
                "page_json_path": record.get("page_json_path"),
                "artifact_path": str(artifact_path),
                "status": status,
            }

    existing_records: dict[tuple[str, str], dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError:
            payload = {"records": []}
        for record in payload.get("records", []):
            existing_records[(record.get("report_id"), record.get("stage"))] = record

    merged_records: list[dict[str, Any]] = []
    for key, desired in desired_jobs.items():
        existing = existing_records.get(key, {})
        merged = {**desired, **existing}
        if desired["status"] == "completed":
            merged["status"] = "completed"
        elif existing.get("status") == "blocked":
            merged["status"] = "blocked"
        else:
            merged["status"] = "pending"
        merged_records.append(merged)

    merged_records.sort(
        key=lambda item: (
            item["status"] == "completed",
            item["company_name"] or "",
            item["report_id"] or "",
            item["stage"],
        )
    )
    payload = {
        "generated_at": _utcnow_iso(),
        "record_count": len(merged_records),
        "records": merged_records,
    }
    _write_json(manifest_path, payload)
    return payload


def _write_document_pipeline_job_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_jobs.json"
    _write_json(manifest_path, payload)


def _load_workspace_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "workspace_runs.json")


def _write_workspace_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "workspace_runs.json", payload)


def _load_document_pipeline_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "document_pipeline_runs.json")


def _write_document_pipeline_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "document_pipeline_runs.json", payload)


def _build_document_pipeline_run_id(stage: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{stage}-document-run"


def _document_pipeline_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "document_pipeline_runs" / f"{run_id}.json"


def _build_workspace_run_id(company_name: str, query_type: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    query_slug = re.sub(r"[^a-zA-Z0-9_]+", "-", query_type).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-{query_slug}"


def _workspace_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "runs" / f"{run_id}.json"


def _load_score_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "score_runs.json")


def _write_score_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "score_runs.json", payload)


def _build_score_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-score"


def _score_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "score_runs" / f"{run_id}.json"


def _load_stress_test_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "stress_test_runs.json")


def _write_stress_test_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "stress_test_runs.json", payload)


def _build_stress_test_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-stress"


def _stress_test_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "stress_runs" / f"{run_id}.json"


def _load_graph_query_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "graph_query_runs.json")


def _write_graph_query_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "graph_query_runs.json", payload)


def _build_graph_query_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-graph"


def _graph_query_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "graph_runs" / f"{run_id}.json"


def _load_vision_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "vision_analyze_runs.json")


def _write_vision_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "vision_analyze_runs.json", payload)


def _build_vision_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-vision"


def _vision_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "vision_runs" / f"{run_id}.json"


def _load_verify_run_manifest(settings: Settings) -> dict[str, Any]:
    return _load_simple_run_manifest(settings.bronze_data_path / "manifests" / "claim_verify_runs.json")


def _write_verify_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    _write_simple_run_manifest(settings.bronze_data_path / "manifests" / "claim_verify_runs.json", payload)


def _build_verify_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-verify"


def _verify_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "verify_runs" / f"{run_id}.json"


def _load_simple_run_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
    }


def _write_simple_run_manifest(path: Path, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    _write_json(path, payload)


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return []
    records = payload.get("records", []) if isinstance(payload, dict) else []
    return records if isinstance(records, list) else []


def _load_json_if_possible(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
