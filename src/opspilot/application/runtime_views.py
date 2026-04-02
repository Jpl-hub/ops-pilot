from __future__ import annotations

from pathlib import Path
from typing import Any

from opspilot.config import Settings
from opspilot.application.runtime_manifests import (
    _load_document_pipeline_run_manifest,
    _load_graph_query_run_manifest,
    _load_stress_test_run_manifest,
    _load_vision_run_manifest,
    _load_watchboard_manifest,
    _load_watchboard_runs_manifest,
    _load_workspace_run_manifest,
)


def _innovation_radar_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "reference" / "innovation_radar_2026.json"


def _filter_workspace_runs_for_company(
    records: list[dict[str, Any]],
    company_name: str,
    report_period: str | None = None,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    filtered = [
        item
        for item in records
        if item.get("company_name") == company_name
        and (report_period is None or item.get("report_period") == report_period)
    ]
    return {
        "count": len(filtered),
        "items": filtered[:limit],
    }


def _build_runtime_capsule_module(
    *,
    module_key: str,
    label: str,
    route_path: str,
    company_name: str,
    report_period: str,
    record: dict[str, Any] | None,
    summary_key: str,
    detail_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    if record is None:
        return {
            "module_key": module_key,
            "label": label,
            "status": "idle",
            "summary": "暂无运行记录",
            "details": [],
            "route": {
                "path": route_path,
                "query": {"company": company_name, "period": report_period},
            },
        }
    details = []
    for key in detail_keys:
        value = record.get(key)
        if value:
            details.append(str(value))
    if module_key == "analysis" and record.get("report_period"):
        details.append(str(record["report_period"]))
    return {
        "module_key": module_key,
        "label": label,
        "status": "ready",
        "summary": record.get(summary_key) or "已生成最新结果",
        "details": details[:2],
        "route": {
            "path": route_path,
            "query": {"company": company_name, "period": report_period},
        },
        "meta": {
            "run_id": record.get("run_id"),
            "created_at": record.get("created_at"),
        },
    }


def _build_industry_brain_watchboard_snapshot(
    settings: Settings,
    *,
    report_period: str,
    user_role: str,
    alert_workflow: dict[str, Any],
    task_board: dict[str, Any],
    risk_payload: dict[str, Any],
    limit: int = 8,
) -> dict[str, Any]:
    manifest = _load_watchboard_manifest(settings)
    records = [
        item
        for item in manifest["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]

    alert_items_by_company: dict[str, list[dict[str, Any]]] = {}
    for item in alert_workflow.get("alerts", []):
        alert_items_by_company.setdefault(item["company_name"], []).append(item)

    task_count_by_company: dict[str, int] = {}
    for item in task_board.get("tasks", []):
        task_count_by_company[item["company_name"]] = task_count_by_company.get(item["company_name"], 0) + 1

    risk_lookup = {
        item["company_name"]: item
        for item in risk_payload.get("risk_board", [])
        if item.get("company_name")
    }

    watch_items: list[dict[str, Any]] = []
    for item in records:
        company_name = item["company_name"]
        alert_items = alert_items_by_company.get(company_name, [])
        risk_item = risk_lookup.get(company_name, {})
        watch_items.append(
            {
                "company_name": company_name,
                "report_period": report_period,
                "user_role": user_role,
                "note": item.get("note"),
                "risk_count": int(risk_item.get("risk_count") or 0),
                "task_count": task_count_by_company.get(company_name, 0),
                "new_alerts": sum(1 for alert in alert_items if alert.get("status") == "new"),
                "in_progress_alerts": sum(
                    1 for alert in alert_items if alert.get("status") == "in_progress"
                ),
                "top_risks": (risk_item.get("risk_labels") or [])[:3],
            }
        )

    watch_items.sort(
        key=lambda item: (
            item["new_alerts"],
            item["in_progress_alerts"],
            item["risk_count"],
            item["task_count"],
        ),
        reverse=True,
    )
    return {
        "report_period": report_period,
        "user_role": user_role,
        "summary": {
            "tracked_companies": len(watch_items),
            "companies_with_new_alerts": sum(1 for item in watch_items if item["new_alerts"] > 0),
            "companies_in_progress": sum(
                1 for item in watch_items if item["in_progress_alerts"] > 0 or item["task_count"] > 0
            ),
        },
        "items": watch_items[:limit],
    }


def _build_industry_brain_history_snapshot(
    settings: Settings,
    *,
    report_period: str,
    user_role: str,
    limit: int = 10,
) -> dict[str, Any]:
    analysis_runs = [
        {
            "history_type": "analysis_run",
            "title": item.get("query") or "协同分析",
            "created_at": item.get("created_at"),
            "status_label": "已完成",
            "type_label": "协同分析",
            "route": {"path": f"/api/v1/workspace/runs/{item['run_id']}"},
        }
        for item in _load_workspace_run_manifest(settings)["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]
    watch_runs = [
        {
            "history_type": "watchboard_scan",
            "title": f"监测扫描 · {item.get('report_period')}",
            "created_at": item.get("created_at"),
            "status_label": "已完成",
            "type_label": "监测扫描",
            "route": {"path": f"/api/v1/watchboard/runs/{item['run_id']}"},
        }
        for item in _load_watchboard_runs_manifest(settings)["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]
    document_runs = [
        {
            "history_type": "document_pipeline_run",
            "title": f"{item.get('stage') or 'document'} 批量执行",
            "created_at": item.get("created_at"),
            "status_label": item.get("status", "completed"),
            "type_label": "文档升级",
            "route": {"path": f"/api/v1/admin/document-pipeline/runs/{item['run_id']}"},
        }
        for item in _load_document_pipeline_run_manifest(settings)["records"]
        if item.get("report_period") == report_period
    ]
    stress_runs = [
        {
            "history_type": "stress_test",
            "title": f"压力测试 · {item.get('company_name')}",
            "created_at": item.get("created_at"),
            "status_label": item.get("severity", {}).get("label") or "已完成",
            "type_label": "压力测试",
            "route": {"path": f"/api/v1/stress-test/runs/{item['run_id']}"},
        }
        for item in _load_stress_test_run_manifest(settings)["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]
    graph_runs = [
        {
            "history_type": "graph_query",
            "title": f"图谱检索 · {item.get('company_name')}",
            "created_at": item.get("created_at"),
            "status_label": "已完成",
            "type_label": "图谱检索",
            "route": {"path": f"/api/v1/graph-query/runs/{item['run_id']}"},
        }
        for item in _load_graph_query_run_manifest(settings)["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]
    vision_runs = [
        {
            "history_type": "vision_analyze",
            "title": f"文档复核 · {item.get('company_name')}",
            "created_at": item.get("created_at"),
            "status_label": item.get("status_label") or "已完成",
            "type_label": "文档复核",
            "route": {"path": f"/api/v1/vision-analyze/runs/{item['run_id']}"},
        }
        for item in _load_vision_run_manifest(settings)["records"]
        if item.get("user_role") == user_role and item.get("report_period") == report_period
    ]

    records = analysis_runs + watch_runs + document_runs + stress_runs + graph_runs + vision_runs
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "user_role": user_role,
        "report_period": report_period,
        "total": len(records),
        "records": records[:limit],
    }
