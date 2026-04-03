from __future__ import annotations

from typing import Any

from opspilot.application.alert_runtime import _build_workspace_alert_queue
from opspilot.application.document_pipeline import _utcnow_iso
from opspilot.application.runtime_manifests import (
    _build_watchboard_run_id,
    _load_watchboard_manifest,
    _load_watchboard_runs_manifest,
    _write_watchboard_manifest,
    _write_watchboard_runs_manifest,
)
from opspilot.application.runtime_views import (
    _build_execution_bus_summary,
    _build_workspace_execution_bus_records,
)
from opspilot.application.workspace_service import ROLE_PROFILES


def _build_workspace_overview(
    service: Any,
    user_role: str = "investor",
    report_period: str | None = None,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    risk_payload = service.risk_scan(period)
    role_profile = ROLE_PROFILES.get(user_role, ROLE_PROFILES["investor"])
    task_board = service.task_board(user_role=user_role, report_period=period)
    alert_workflow = service.alert_workflow(report_period=period)
    watchboard = service.watchboard(user_role=user_role, report_period=period)
    history = service.workspace_history(
        user_role=user_role,
        report_period=period,
        limit=200,
    )
    document_results = service.document_pipeline_results(limit=300)
    execution_bus = _build_workspace_execution_bus_records(
        task_board=task_board,
        alert_workflow=alert_workflow,
        watchboard=watchboard,
        workspace_history=history,
        limit=20,
    )
    return {
        "preferred_period": period,
        "role_profile": role_profile,
        "companies": service.list_company_names(),
        "watchboard": watchboard,
        "alert_queue": _build_workspace_alert_queue(alert_workflow["alerts"], user_role),
        "alert_workflow_summary": alert_workflow["summary"],
        "task_queue": task_board["tasks"],
        "task_summary": task_board["summary"],
        "workspace_history": {
            "total": history["total"],
            "records": history["records"][:10],
        },
        "execution_bus_records": execution_bus,
        "execution_bus_summary": _build_execution_bus_summary(
            task_board=task_board,
            alert_workflow=alert_workflow,
            watchboard=watchboard,
            workspace_history=history,
            document_results=document_results["results"],
            report_period=period,
            user_role=user_role,
        ),
        "alert_summary": {
            "total_alerts": len(risk_payload["alert_board"]),
            "high_risk_companies": sum(
                1 for item in risk_payload["risk_board"] if item["risk_count"] > 0
            ),
            "preferred_period": period,
            "active_companies": len(service.repository.list_companies(period)),
        },
    }


def _build_workspace_execution_bus(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    history = service.workspace_history(user_role=user_role, report_period=period, limit=200)
    task_board = service.task_board(user_role=user_role, report_period=period, limit=200)
    alert_workflow = service.alert_workflow(report_period=period)
    watchboard = service.watchboard(user_role=user_role, report_period=period)
    return _build_workspace_execution_bus_records(
        task_board=task_board,
        alert_workflow=alert_workflow,
        watchboard=watchboard,
        workspace_history=history,
        limit=limit,
        user_role=user_role,
        report_period=period,
    )


def _build_watchboard(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    include_research: bool = True,
    item_limit: int | None = None,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    manifest = _load_watchboard_manifest(service.settings)
    alert_workflow = service.alert_workflow(report_period=period)
    task_board = service.task_board(user_role=user_role, report_period=period, limit=200)
    alert_items_by_company: dict[str, list[dict[str, Any]]] = {}
    for item in alert_workflow["alerts"]:
        alert_items_by_company.setdefault(item["company_name"], []).append(item)
    task_items_by_company: dict[str, list[dict[str, Any]]] = {}
    for item in task_board["tasks"]:
        task_items_by_company.setdefault(item["company_name"], []).append(item)
    document_items_by_company: dict[str, list[dict[str, Any]]] = {}
    for item in service.document_pipeline_results(limit=300)["results"]:
        if item.get("report_period") != period:
            continue
        document_items_by_company.setdefault(item["company_name"], []).append(item)
    records = [
        item
        for item in manifest["records"]
        if item.get("user_role") == user_role and item.get("report_period") == period
    ]
    watch_items: list[dict[str, Any]] = []
    for item in records:
        company_name = item["company_name"]
        score_payload = service.score_company(company_name, period)
        alert_items = alert_items_by_company.get(company_name, [])
        task_items = task_items_by_company.get(company_name, [])
        document_items = document_items_by_company.get(company_name, [])
        if include_research:
            try:
                research_payload = service.verify_claim(company_name, period)
                research_status = "ready"
                research_title = research_payload["report_meta"]["title"]
            except ValueError:
                research_status = "missing"
                research_title = None
        else:
            research_status = "skipped"
            research_title = None
        watch_items.append(
            {
                "company_name": company_name,
                "report_period": period,
                "user_role": user_role,
                "note": item.get("note"),
                "score": score_payload["scorecard"]["total_score"],
                "grade": score_payload["scorecard"]["grade"],
                "risk_count": len(score_payload["scorecard"]["risk_labels"]),
                "task_count": len(task_items),
                "new_alerts": sum(1 for alert in alert_items if alert["status"] == "new"),
                "in_progress_alerts": sum(
                    1 for alert in alert_items if alert["status"] == "in_progress"
                ),
                "document_upgrade_count": len(document_items),
                "research_status": research_status,
                "research_title": research_title,
                "top_risks": [risk["name"] for risk in score_payload["scorecard"]["risk_labels"][:3]],
            }
        )
    watch_items.sort(
        key=lambda item: (
            item["new_alerts"],
            item["in_progress_alerts"],
            item["risk_count"],
            -item["score"],
        ),
        reverse=True,
    )
    return {
        "report_period": period,
        "user_role": user_role,
        "summary": {
            "tracked_companies": len(watch_items),
            "companies_with_new_alerts": sum(1 for item in watch_items if item["new_alerts"] > 0),
            "companies_in_progress": sum(
                1 for item in watch_items if item["in_progress_alerts"] > 0 or item["task_count"] > 0
            ),
        },
        "items": watch_items[:item_limit] if item_limit is not None else watch_items,
    }


def _scan_watchboard(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
) -> dict[str, Any]:
    board = service.watchboard(user_role=user_role, report_period=report_period)
    run_id = _build_watchboard_run_id(user_role, board["report_period"])
    manifest = _load_watchboard_runs_manifest(service.settings)
    record = {
        "run_id": run_id,
        "user_role": user_role,
        "report_period": board["report_period"],
        "summary": board["summary"],
        "companies": [item["company_name"] for item in board["items"]],
        "items": board["items"],
        "created_at": _utcnow_iso(),
    }
    manifest["records"].append(record)
    _write_watchboard_runs_manifest(service.settings, manifest)
    return {
        "run": record,
        "board": board,
    }


def _watchboard_runs(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    manifest = _load_watchboard_runs_manifest(service.settings)
    records = [
        item
        for item in manifest["records"]
        if item.get("user_role") == user_role and item.get("report_period") == period
    ]
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "user_role": user_role,
        "report_period": period,
        "total": len(records),
        "runs": records[:limit],
    }


def _watchboard_run_detail(service: Any, run_id: str) -> dict[str, Any]:
    manifest = _load_watchboard_runs_manifest(service.settings)
    record = next((item for item in manifest["records"] if item.get("run_id") == run_id), None)
    if record is None:
        raise ValueError(f"未找到监测扫描记录：{run_id}")
    return record


def _dispatch_watchboard_alerts(
    service: Any,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    board = service.watchboard(user_role=user_role, report_period=report_period)
    tracked_companies = {item["company_name"] for item in board["items"]}
    alert_workflow = service.alert_workflow(report_period=board["report_period"])
    dispatched: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for alert in alert_workflow["alerts"]:
        if len(dispatched) >= limit:
            break
        if alert["company_name"] not in tracked_companies:
            continue
        if alert["status"] != "new":
            skipped.append(
                {
                    "alert_id": alert["alert_id"],
                    "company_name": alert["company_name"],
                    "status": alert["status"],
                }
            )
            continue
        result = service.dispatch_alert_to_task(
            alert_id=alert["alert_id"],
            user_role=user_role,
            report_period=board["report_period"],
            note="来自监测板批量派发",
        )
        dispatched.append(
            {
                "alert_id": alert["alert_id"],
                "company_name": alert["company_name"],
                "task_id": result["task"]["task_id"],
                "task_title": result["task"]["title"],
            }
        )

    return {
        "report_period": board["report_period"],
        "user_role": user_role,
        "summary": {
            "tracked_companies": len(tracked_companies),
            "dispatched_alerts": len(dispatched),
            "skipped_alerts": len(skipped),
        },
        "dispatched": dispatched,
        "skipped": skipped[:limit],
        "task_board": service.task_board(user_role=user_role, report_period=board["report_period"]),
        "alert_board": service.alert_workflow(report_period=board["report_period"]),
    }


def _add_watch_company(
    service: Any,
    *,
    company_name: str,
    user_role: str = "management",
    report_period: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    company = service._resolve_company(company_name, report_period)
    if company is None:
        raise ValueError(f"未找到公司：{company_name}")
    period = report_period or company["report_period"]
    manifest = _load_watchboard_manifest(service.settings)
    records = manifest["records"]
    existing = next(
        (
            item
            for item in records
            if item["company_name"] == company_name
            and item["user_role"] == user_role
            and item["report_period"] == period
        ),
        None,
    )
    if existing is None:
        records.append(
            {
                "company_name": company_name,
                "user_role": user_role,
                "report_period": period,
                "note": note,
                "created_at": _utcnow_iso(),
            }
        )
    else:
        existing["note"] = note
        existing["updated_at"] = _utcnow_iso()
    _write_watchboard_manifest(service.settings, manifest)
    return service.watchboard(user_role=user_role, report_period=period)


def _remove_watch_company(
    service: Any,
    *,
    company_name: str,
    user_role: str = "management",
    report_period: str | None = None,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    manifest = _load_watchboard_manifest(service.settings)
    manifest["records"] = [
        item
        for item in manifest["records"]
        if not (
            item["company_name"] == company_name
            and item["user_role"] == user_role
            and item["report_period"] == period
        )
    ]
    _write_watchboard_manifest(service.settings, manifest)
    return service.watchboard(user_role=user_role, report_period=period)
