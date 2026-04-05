from __future__ import annotations

from typing import Any

from opspilot.domain.rules import evaluate_risk_labels

from opspilot.application.admin_delivery import _period_order_key, _status_label
from opspilot.application.document_pipeline import _utcnow_iso
from opspilot.application.runtime_manifests import (
    _build_alert_id,
    _build_task_id,
    _load_alert_board_manifest,
    _load_task_board_manifest,
    _write_alert_board_manifest,
    _write_task_board_manifest,
)
from opspilot.application.runtime_views import _resolve_source_run_route


def _get_company_periods(repository: Any, company_name: str) -> set[str]:
    if hasattr(repository, "list_company_periods"):
        return set(repository.list_company_periods(company_name))
    return {
        company.get("report_period")
        for company in repository.list_companies()
        if company.get("company_name") == company_name and company.get("report_period")
    }


def _list_company_periods(repository: Any, company_name: str) -> list[str]:
    periods = _get_company_periods(repository, company_name)
    return sorted(periods, key=_period_order_key, reverse=True)


def _build_alert_board(repository: Any, companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for company in companies:
        periods = _list_company_periods(repository, company["company_name"])
        current_period = company["report_period"]
        if current_period not in periods:
            periods = [current_period, *periods]
        current_index = periods.index(current_period) if current_period in periods else 0
        previous_period = periods[current_index + 1] if current_index + 1 < len(periods) else None
        previous_company = (
            repository.get_company(company["company_name"], previous_period)
            if previous_period is not None
            else None
        )
        current_risks = evaluate_risk_labels(company)
        previous_risks = evaluate_risk_labels(previous_company) if previous_company is not None else []
        current_codes = {item["code"] for item in current_risks}
        previous_codes = {item["code"] for item in previous_risks}
        new_codes = sorted(current_codes - previous_codes)
        risk_delta = len(current_risks) - len(previous_risks)
        growth_metric = company.get("metrics", {}).get("G1")
        profit_metric = company.get("metrics", {}).get("G2")
        if risk_delta <= 0 and not new_codes and not (
            (growth_metric is not None and growth_metric < 0)
            or (profit_metric is not None and profit_metric < 0)
        ):
            continue
        highlights = [item["name"] for item in current_risks if item["code"] in new_codes]
        if growth_metric is not None and growth_metric < 0:
            highlights.append(f"营收同比 {growth_metric}%")
        if profit_metric is not None and profit_metric < 0:
            highlights.append(f"扣非净利润同比 {profit_metric}%")
        alerts.append(
            {
                "company_name": company["company_name"],
                "subindustry": company["subindustry"],
                "report_period": current_period,
                "previous_period": previous_period,
                "risk_count": len(current_risks),
                "risk_delta": risk_delta,
                "new_labels": highlights[:3],
                "summary": _build_alert_summary(company, risk_delta, previous_period, highlights),
            }
        )
    alerts.sort(key=lambda item: (item["risk_delta"], item["risk_count"]), reverse=True)
    return alerts[:12]


def _build_alert_summary(
    company: dict[str, Any],
    risk_delta: int,
    previous_period: str | None,
    highlights: list[str],
) -> str:
    company_name = company["company_name"]
    current_period = company["report_period"]
    if risk_delta > 0 and previous_period:
        return f"{company_name} 在 {current_period} 新增 {risk_delta} 个风险信号，较 {previous_period} 明显抬升。"
    if highlights:
        return f"{company_name} 在 {current_period} 出现重点异常：{'、'.join(highlights[:2])}。"
    return f"{company_name} 在 {current_period} 风险暴露继续抬升。"


def _build_workspace_alert_queue(alerts: list[dict[str, Any]], user_role: str) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for item in alerts[:8]:
        if user_role == "management":
            title = f"{item['company_name']} 经营整改优先级上升"
            summary = item["summary"]
            route = {
                "path": "/score",
                "query": {
                    "company": item["company_name"],
                    "period": item["report_period"],
                },
                "label": "进入企业体检",
            }
        elif user_role == "regulator":
            title = f"{item['company_name']} 风险信号需要跟踪"
            summary = item["summary"]
            route = {
                "path": "/risk",
                "query": {
                    "company": item["company_name"],
                    "period": item["report_period"],
                },
                "label": "进入行业风险",
            }
        else:
            title = f"{item['company_name']} 出现新的关注点"
            summary = item["summary"]
            route = {
                "path": "/verify",
                "query": {
                    "company": item["company_name"],
                    "period": item["report_period"],
                },
                "label": "进入研报核验",
            }
        queue.append(
            {
                "alert_id": item["alert_id"],
                "company_name": item["company_name"],
                "report_period": item["report_period"],
                "title": title,
                "summary": summary,
                "status": item["status"],
                "note": item.get("note"),
                "risk_delta": item["risk_delta"],
                "risk_count": item["risk_count"],
                "new_labels": item["new_labels"],
                "route": route,
            }
        )
    return queue


def _build_system_task_route(
    company_name: str,
    report_period: str,
    user_role: str,
) -> dict[str, Any]:
    if user_role == "investor":
        return {"path": "/verify", "query": {"company": company_name, "period": report_period}}
    if user_role == "regulator":
        return {"path": "/risk", "query": {"company": company_name, "period": report_period}}
    return {"path": "/score", "query": {"company": company_name, "period": report_period}}


def _build_manual_task_route(
    company_name: str,
    report_period: str,
    user_role: str,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    query = {
        "company": company_name,
        "period": report_period,
        "role": user_role,
    }
    if source_run_id:
        query["run"] = source_run_id
    return {"path": "/workspace", "query": query}


def _build_manual_task_payload(
    record: dict[str, Any],
    *,
    user_role: str,
    report_period: str,
) -> dict[str, Any]:
    company_name = str(record.get("company_name") or "").strip()
    priority = str(record.get("priority") or "P1").strip() or "P1"
    title = str(record.get("title") or "").strip()
    summary = str(record.get("summary") or "").strip()
    created_at = record.get("created_at") or record.get("updated_at")
    route = record.get("route") or _build_manual_task_route(
        company_name,
        report_period,
        user_role,
        source_run_id=record.get("source_run_id"),
    )
    return {
        "task_id": record["task_id"],
        "company_name": company_name,
        "report_period": report_period,
        "priority": priority,
        "title": title,
        "summary": summary,
        "label_names": record.get("label_names", []),
        "route": route,
        "owner_role": record.get("owner_role") or user_role,
        "task_source": "manual",
        "task_source_label": "协同分析动作",
        "created_at": created_at,
        "source_run_id": record.get("source_run_id"),
    }


def _alert_workflow(service: Any, report_period: str | None = None) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    risk_payload = service.risk_scan(period)
    alert_manifest = _load_alert_board_manifest(service.settings)
    status_counts = {
        "new": 0,
        "dispatched": 0,
        "in_progress": 0,
        "resolved": 0,
        "dismissed": 0,
    }
    alerts: list[dict[str, Any]] = []
    for alert in risk_payload["alert_board"]:
        alert_id = _build_alert_id(alert)
        record = alert_manifest["records"].get(alert_id, {})
        status = record.get("status", "new")
        status_counts[status] = status_counts.get(status, 0) + 1
        alerts.append(
            {
                **alert,
                "alert_id": alert_id,
                "status": status,
                "status_label": _status_label(status),
                "note": record.get("note"),
                "updated_at": record.get("updated_at"),
                "history": record.get("history", []),
            }
        )
    return {
        "report_period": period,
        "summary": {
            "total": len(alerts),
            "new": status_counts["new"],
            "dispatched": status_counts["dispatched"],
            "in_progress": status_counts["in_progress"],
            "resolved": status_counts["resolved"],
            "dismissed": status_counts["dismissed"],
        },
        "alerts": alerts,
    }


def _update_alert_status(
    service: Any,
    alert_id: str,
    status: str,
    report_period: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    workflow = _alert_workflow(service, report_period=report_period)
    alert = next((item for item in workflow["alerts"] if item["alert_id"] == alert_id), None)
    if alert is None:
        raise ValueError(f"未找到预警：{alert_id}")

    manifest = _load_alert_board_manifest(service.settings)
    record = manifest["records"].setdefault(alert_id, {})
    updated_at = _utcnow_iso()
    history = list(record.get("history", []))
    history.append({"status": status, "note": note, "updated_at": updated_at})
    record.update(
        {
            "alert_id": alert_id,
            "status": status,
            "note": note,
            "updated_at": updated_at,
            "history": history[-10:],
        }
    )
    _write_alert_board_manifest(service.settings, manifest)
    refreshed = _alert_workflow(service, report_period=report_period or workflow["report_period"])
    refreshed_alert = next(item for item in refreshed["alerts"] if item["alert_id"] == alert_id)
    return {"alert": refreshed_alert, "summary": refreshed["summary"]}


def _task_queue(
    service: Any,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    period = report_period or service._preferred_period()
    alerts = service.risk_scan(period)["alert_board"]
    tasks: list[dict[str, Any]] = []
    for alert in alerts[:limit]:
        company_name = alert["company_name"]
        score_payload = service.score_company(company_name, period)
        action_cards = score_payload["action_cards"]
        if not action_cards:
            continue
        primary_action = action_cards[0]
        task_id = _build_task_id(
            period,
            company_name,
            primary_action["priority"],
            primary_action["title"],
        )
        tasks.append(
            {
                "task_id": task_id,
                "company_name": company_name,
                "report_period": score_payload["report_period"],
                "priority": primary_action["priority"],
                "title": primary_action["title"],
                "summary": primary_action["reason"],
                "label_names": [item["name"] for item in score_payload["scorecard"]["risk_labels"][:3]],
                "route": _build_system_task_route(company_name, period, user_role),
                "owner_role": user_role,
                "task_source": "system",
                "task_source_label": "风险派生任务",
            }
        )
    return tasks


def _task_board(
    service: Any,
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    task_manifest = _load_task_board_manifest(service.settings)
    system_tasks = _task_queue(service, user_role=user_role, report_period=period, limit=limit)
    manual_tasks = [
        _build_manual_task_payload(record, user_role=user_role, report_period=period)
        for record in task_manifest["records"].values()
        if record.get("task_source") == "manual"
        and record.get("user_role") == user_role
        and record.get("report_period") == period
        and record.get("task_id")
        and str(record.get("company_name") or "").strip()
        and str(record.get("title") or "").strip()
    ]
    tasks = system_tasks + [
        item for item in manual_tasks if all(existing["task_id"] != item["task_id"] for existing in system_tasks)
    ]
    status_counts = {"queued": 0, "in_progress": 0, "done": 0, "blocked": 0}
    enriched_tasks: list[dict[str, Any]] = []
    for task in tasks:
        record = task_manifest["records"].get(task["task_id"], {})
        status = record.get("status", "queued")
        status_counts[status] = status_counts.get(status, 0) + 1
        enriched_tasks.append(
            {
                **task,
                "status": status,
                "status_label": _status_label(status),
                "note": record.get("note"),
                "updated_at": record.get("updated_at"),
                "history": record.get("history", []),
                "created_at": task.get("created_at"),
            }
        )
    return {
        "user_role": user_role,
        "report_period": period,
        "summary": {
            "total": len(enriched_tasks),
            "queued": status_counts["queued"],
            "in_progress": status_counts["in_progress"],
            "done": status_counts["done"],
            "blocked": status_counts["blocked"],
        },
        "tasks": enriched_tasks,
    }


def _create_manual_task(
    service: Any,
    *,
    company_name: str,
    title: str,
    summary: str,
    priority: str = "P1",
    user_role: str = "management",
    report_period: str | None = None,
    note: str | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    company = service._resolve_company(company_name, report_period)
    if company is None:
        raise ValueError(f"未找到公司：{company_name}")
    period = report_period or company["report_period"]
    normalized_title = title.strip()
    normalized_summary = summary.strip()
    normalized_priority = priority.strip().upper() or "P1"
    if not normalized_title:
        raise ValueError("任务标题不能为空。")
    if not normalized_summary:
        raise ValueError("任务说明不能为空。")

    task_id = _build_task_id(period, company_name, normalized_priority, normalized_title)
    existing_board = _task_board(service, user_role=user_role, report_period=period, limit=200)
    existing_task = next((item for item in existing_board["tasks"] if item["task_id"] == task_id), None)
    if existing_task is not None:
        return {
            "task": existing_task,
            "summary": existing_board["summary"],
            "created": False,
        }

    manifest = _load_task_board_manifest(service.settings)
    created_at = _utcnow_iso()
    manifest["records"][task_id] = {
        "task_id": task_id,
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "priority": normalized_priority,
        "title": normalized_title,
        "summary": normalized_summary,
        "note": note,
        "status": "queued",
        "updated_at": created_at,
        "created_at": created_at,
        "history": [
            {
                "status": "queued",
                "note": note or "由协同分析动作写入任务板",
                "updated_at": created_at,
            }
        ],
        "route": _resolve_source_run_route(
            service.settings,
            source_run_id=source_run_id,
            company_name=company_name,
            report_period=period,
            user_role=user_role,
        ),
        "owner_role": user_role,
        "task_source": "manual",
        "source_run_id": source_run_id,
        "label_names": [],
    }
    _write_task_board_manifest(service.settings, manifest)
    refreshed = _task_board(service, user_role=user_role, report_period=period, limit=200)
    created_task = next(item for item in refreshed["tasks"] if item["task_id"] == task_id)
    return {
        "task": created_task,
        "summary": refreshed["summary"],
        "created": True,
    }


def _update_task_status(
    service: Any,
    task_id: str,
    status: str,
    user_role: str = "management",
    report_period: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    task_board = _task_board(service, user_role=user_role, report_period=report_period, limit=200)
    task = next((item for item in task_board["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"未找到任务：{task_id}")

    task_manifest = _load_task_board_manifest(service.settings)
    record = task_manifest["records"].setdefault(task_id, {})
    history = list(record.get("history", []))
    updated_at = _utcnow_iso()
    history.append({"status": status, "note": note, "updated_at": updated_at})
    record.update(
        {
            "task_id": task_id,
            "status": status,
            "note": note,
            "updated_at": updated_at,
            "history": history[-10:],
        }
    )
    _write_task_board_manifest(service.settings, task_manifest)
    refreshed = _task_board(
        service,
        user_role=user_role,
        report_period=report_period or task_board["report_period"],
        limit=200,
    )
    refreshed_task = next(item for item in refreshed["tasks"] if item["task_id"] == task_id)
    return {"task": refreshed_task, "summary": refreshed["summary"]}


def _dispatch_alert_to_task(
    service: Any,
    alert_id: str,
    *,
    user_role: str = "management",
    report_period: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    workflow = _alert_workflow(service, report_period=report_period)
    alert = next((item for item in workflow["alerts"] if item["alert_id"] == alert_id), None)
    if alert is None:
        raise ValueError(f"未找到预警：{alert_id}")

    period = report_period or workflow["report_period"]
    task_board = _task_board(service, user_role=user_role, report_period=period, limit=200)
    task = next(
        (
            item
            for item in task_board["tasks"]
            if item["company_name"] == alert["company_name"] and item.get("task_source") != "manual"
        ),
        None,
    )
    if task is None:
        task = next(
            (item for item in task_board["tasks"] if item["company_name"] == alert["company_name"]),
            None,
        )
    if task is None:
        raise ValueError(f"未找到可派发任务：{alert['company_name']}")

    task_note = note or f"由预警 {alert_id} 派发"
    alert_note = note or f"已派发到任务 {task['task_id']}"
    task_payload = _update_task_status(
        service,
        task_id=task["task_id"],
        status="in_progress",
        user_role=user_role,
        report_period=period,
        note=task_note,
    )
    alert_payload = _update_alert_status(
        service,
        alert_id=alert_id,
        status="dispatched",
        report_period=period,
        note=alert_note,
    )
    return {
        "alert": alert_payload["alert"],
        "alert_summary": alert_payload["summary"],
        "task": task_payload["task"],
        "task_summary": task_payload["summary"],
    }
