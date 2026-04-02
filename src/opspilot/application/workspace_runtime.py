from __future__ import annotations

from typing import Any

from opspilot.application.document_pipeline import _utcnow_iso, _write_json
from opspilot.application.runtime_manifests import (
    _build_workspace_run_id,
    _load_workspace_run_manifest,
    _workspace_run_detail_path,
    _write_workspace_run_manifest,
)


def _workspace_history(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 30,
    source_limit: int = 200,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    analysis_runs = [
        {
            "history_type": "analysis_run",
            "id": item["run_id"],
            "title": item.get("query") or "分析执行",
            "company_name": item.get("company_name"),
            "report_period": item.get("report_period"),
            "user_role": item.get("user_role"),
            "status": "completed",
            "created_at": item.get("created_at"),
            "meta": {
                "query_type": item.get("query_type"),
                "detail_path": item.get("detail_path"),
                "route": {
                    "path": f"/api/v1/workspace/runs/{item['run_id']}",
                },
            },
        }
        for item in service.workspace_runs(limit=source_limit)["runs"]
        if item.get("user_role") == user_role and item.get("report_period") == period
    ]
    watch_runs = [
        {
            "history_type": "watchboard_scan",
            "id": item["run_id"],
            "title": f"监测扫描 {item['report_period']}",
            "company_name": "、".join(item.get("companies", [])[:3]) or None,
            "report_period": item.get("report_period"),
            "user_role": item.get("user_role"),
            "status": "completed",
            "created_at": item.get("created_at"),
            "meta": {
                "tracked_companies": item.get("summary", {}).get("tracked_companies"),
                "companies_with_new_alerts": item.get("summary", {}).get("companies_with_new_alerts"),
                "route": {
                    "path": f"/api/v1/watchboard/runs/{item['run_id']}",
                },
            },
        }
        for item in service.watchboard_runs(
            user_role=user_role,
            report_period=period,
            limit=source_limit,
        )["runs"]
    ]
    document_jobs = [
        {
            "history_type": "document_pipeline",
            "id": f"{item['stage']}::{item['report_id']}",
            "title": f"{item['stage']} · {item['company_name']}",
            "company_name": item.get("company_name"),
            "report_period": item.get("report_period"),
            "user_role": user_role,
            "status": item.get("status"),
            "created_at": item.get("completed_at"),
            "meta": {
                "stage": item.get("stage"),
                "artifact_summary": item.get("artifact_summary"),
                "route": {
                    "path": f"/api/v1/admin/document-pipeline/results/{item['stage']}/{item['report_id']}",
                },
            },
        }
        for item in service.document_pipeline_results(limit=max(source_limit, limit))["results"]
        if item.get("report_period") == period
    ]
    document_runs = [
        {
            "history_type": "document_pipeline_run",
            "id": item["run_id"],
            "title": f"{item['stage']} 批量执行",
            "company_name": "、".join(item.get("companies", [])[:3]) or None,
            "report_period": item.get("report_period"),
            "user_role": user_role,
            "status": item.get("status", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "stage": item.get("stage"),
                "processed": item.get("processed"),
                "fixed_count": item.get("execution_feedback", {}).get("fixed_count"),
                "remaining_count": item.get("execution_feedback", {}).get("remaining_count"),
                "headline": item.get("execution_feedback", {}).get("headline"),
                "contract_status": item.get("contract_status"),
                "route": {
                    "path": f"/api/v1/admin/document-pipeline/runs/{item['run_id']}",
                },
            },
        }
        for item in service.document_pipeline_runs(limit=source_limit)["runs"]
        if item.get("report_period") == period
    ]
    stress_runs = [
        {
            "history_type": "stress_test",
            "id": item["run_id"],
            "title": f"压力测试 · {item['company_name']}",
            "company_name": item.get("company_name"),
            "report_period": item.get("report_period"),
            "user_role": item.get("user_role"),
            "status": item.get("severity", {}).get("level", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "scenario": item.get("scenario"),
                "severity": item.get("severity", {}).get("label"),
                "route": {
                    "path": f"/api/v1/stress-test/runs/{item['run_id']}",
                },
            },
        }
        for item in service.stress_test_runs(
            report_period=period,
            user_role=user_role,
            limit=source_limit,
        )["runs"]
    ]
    graph_runs = [
        {
            "history_type": "graph_query",
            "id": item["run_id"],
            "title": f"图谱检索 · {item['company_name']}",
            "company_name": item.get("company_name"),
            "report_period": item.get("report_period"),
            "user_role": item.get("user_role"),
            "status": "completed",
            "created_at": item.get("created_at"),
            "meta": {
                "intent": item.get("intent"),
                "route": {
                    "path": f"/api/v1/graph-query/runs/{item['run_id']}",
                },
            },
        }
        for item in service.graph_query_runs(
            report_period=period,
            user_role=user_role,
            limit=source_limit,
        )["runs"]
    ]
    vision_runs = [
        {
            "history_type": "vision_analyze",
            "id": item["run_id"],
            "title": f"多模态解析 · {item['company_name']}",
            "company_name": item.get("company_name"),
            "report_period": item.get("report_period"),
            "user_role": item.get("user_role"),
            "status": item.get("status_label", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "headline": item.get("headline"),
                "route": {
                    "path": f"/api/v1/vision-analyze/runs/{item['run_id']}",
                },
            },
        }
        for item in service.vision_runs(
            report_period=period,
            user_role=user_role,
            limit=source_limit,
        )["runs"]
    ]
    records = analysis_runs + watch_runs + document_jobs + document_runs + stress_runs
    records += graph_runs + vision_runs
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "user_role": user_role,
        "report_period": period,
        "total": len(records),
        "records": records[:limit],
    }


def _persist_workspace_run(
    service: Any,
    payload: dict[str, Any],
    *,
    query: str,
    company_name: str | None,
    user_role: str,
) -> dict[str, Any]:
    run_id = _build_workspace_run_id(
        payload.get("company_name") or company_name or "industry",
        payload.get("query_type") or "unknown",
    )
    detail_path = _workspace_run_detail_path(service.settings, run_id)
    detail_payload = {
        "run_id": run_id,
        "query": query,
        "company_name": payload.get("company_name") or company_name,
        "report_period": payload.get("report_period"),
        "user_role": user_role,
        "query_type": payload.get("query_type"),
        "control_plane": payload.get("control_plane"),
        "agent_flow": payload.get("agent_flow"),
        "answer_sections": payload.get("answer_sections"),
        "insight_cards": payload.get("insight_cards"),
        "follow_up_questions": payload.get("follow_up_questions"),
        "formula_cards": payload.get("formula_cards"),
        "charts": payload.get("charts"),
        "evidence_groups": payload.get("evidence_groups"),
        "created_at": _utcnow_iso(),
    }
    _write_json(detail_path, detail_payload)

    manifest = _load_workspace_run_manifest(service.settings)
    record = {
        "run_id": run_id,
        "query": query,
        "company_name": detail_payload["company_name"],
        "report_period": detail_payload["report_period"],
        "user_role": user_role,
        "query_type": detail_payload["query_type"],
        "detail_path": str(detail_path),
        "created_at": detail_payload["created_at"],
        "control_plane_status": payload.get("control_plane", {}).get("session_label"),
    }
    manifest["records"] = [
        item for item in manifest["records"] if item.get("run_id") != run_id
    ]
    manifest["records"].append(record)
    _write_workspace_run_manifest(service.settings, manifest)
    return {**payload, "run_id": run_id}
