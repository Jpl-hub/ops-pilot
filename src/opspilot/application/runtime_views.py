from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from opspilot.config import Settings
from opspilot.application.admin_delivery import (
    _bus_type_label,
    _status_label,
)
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


def _build_brain_command_surface(
    *,
    preferred_period: str,
    market_tape: list[dict[str, Any]],
    attention_matrix: list[dict[str, Any]],
    execution_flash: list[dict[str, Any]],
) -> dict[str, Any]:
    dominant_market = market_tape[0] if market_tape else {"label": "主周期", "value": "0", "tone": "accent"}
    focus_company = attention_matrix[0] if attention_matrix else {"company_name": "等待公司", "headline": "等待关注信号"}
    latest_execution = execution_flash[0] if execution_flash else {"status": "idle"}
    focus_count = len(attention_matrix)
    dominant_label = str(dominant_market["label"])
    focus_subindustry = str(focus_company.get("subindustry") or "重点板块")
    summary = f"{focus_subindustry}板块正在抬升，值得先看进入跟踪的企业与风险链。"
    if focus_count > 1:
        summary = f"{focus_subindustry}板块正在抬升，已有 {focus_count} 家重点企业同步进入跟踪。"
    return {
        "title": "行业主线",
        "headline": f"{dominant_label}正在带动重点公司与风险面同步刷新",
        "metric": dominant_market["value"],
        "intensity": 52 + min(36, focus_count * 6),
        "watch_items": [
            {"label": dominant_market["label"], "value": dominant_market["value"]},
            {"label": "重点公司", "value": str(focus_count)},
            {"label": "最近运行", "value": latest_execution["status"]},
        ],
        "summary": summary,
        "dominant_signal": {
            "label": focus_company["company_name"],
            "value": focus_company["headline"],
            "tone": dominant_market.get("tone") or "accent",
        },
    }


def _build_brain_signal_tape(
    *,
    market_tape: list[dict[str, Any]],
    live_events: list[dict[str, Any]],
    history_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, item in enumerate(market_tape[:3]):
        digits = re.sub(r"\D", "", str(item.get("value") or "0"))
        tape.append(
            {
                "step": index + 1,
                "label": item["label"],
                "value": f"{item['value']} · {item['delta']}",
                "tone": item.get("tone") or "accent",
                "intensity": min(100, 32 + index * 18 + (int(digits or "0") % 40)),
            }
        )
    if live_events:
        lead_event = live_events[0]
        lead_tone = lead_event.get("tone") or ""
        tape.append(
            {
                "step": len(tape) + 1,
                "label": lead_event["company_name"],
                "value": lead_event["headline"],
                "tone": (
                    lead_tone
                    if lead_tone in {"risk", "warning", "accent", "success"}
                    else "warning"
                    if lead_event["status"] == "新增预警"
                    else "success"
                ),
                "intensity": 72 if lead_event["status"] == "新增预警" else 56 if lead_tone == "warning" else 48,
            }
        )
    if history_points:
        latest = history_points[-1]
        tape.append(
            {
                "step": len(tape) + 1,
                "label": latest["timestamp"],
                "value": f"{latest['alerts']} 预警 / {latest['tasks']} 任务",
                "tone": "accent",
                "intensity": 58,
            }
        )
    return tape


def _build_execution_bus_summary(
    *,
    task_board: dict[str, Any],
    alert_workflow: dict[str, Any],
    watchboard: dict[str, Any],
    workspace_history: dict[str, Any],
    document_results: list[dict[str, Any]],
    report_period: str,
    user_role: str,
) -> dict[str, Any]:
    filtered_document_results = [
        item for item in document_results if item.get("report_period") == report_period
    ]
    history_records = workspace_history.get("records", [])
    return {
        "user_role": user_role,
        "report_period": report_period,
        "tasks": {
            "total": task_board["summary"]["total"],
            "active": task_board["summary"]["queued"] + task_board["summary"]["in_progress"],
            "blocked": task_board["summary"]["blocked"],
        },
        "alerts": {
            "total": alert_workflow["summary"]["total"],
            "new": alert_workflow["summary"]["new"],
            "in_progress": alert_workflow["summary"]["in_progress"],
            "dispatched": alert_workflow["summary"]["dispatched"],
        },
        "watchboard": watchboard["summary"],
        "document_pipeline": {
            "total": len(filtered_document_results),
            "completed": sum(1 for item in filtered_document_results if item.get("status") == "completed"),
            "pending": sum(1 for item in filtered_document_results if item.get("status") == "pending"),
            "blocked": sum(1 for item in filtered_document_results if item.get("status") == "blocked"),
        },
        "history": {
            "total": workspace_history.get("total", 0),
            "analysis_runs": sum(1 for item in history_records if item.get("history_type") == "analysis_run"),
            "watchboard_scans": sum(1 for item in history_records if item.get("history_type") == "watchboard_scan"),
            "document_jobs": sum(1 for item in history_records if item.get("history_type") == "document_pipeline"),
        },
    }


def _build_workspace_execution_bus_records(
    *,
    task_board: dict[str, Any],
    alert_workflow: dict[str, Any],
    watchboard: dict[str, Any],
    workspace_history: dict[str, Any],
    limit: int,
    user_role: str | None = None,
    report_period: str | None = None,
) -> dict[str, Any]:
    task_records = [
        {
            "bus_type": "task",
            "type_label": _bus_type_label("task"),
            "id": item["task_id"],
            "title": item["title"],
            "company_name": item["company_name"],
            "status": item["status"],
            "status_label": item.get("status_label", _status_label(item["status"])),
            "created_at": item.get("updated_at"),
            "meta": {
                "priority": item.get("priority"),
                "route": item.get("route"),
            },
        }
        for item in task_board["tasks"]
    ]
    alert_records = [
        {
            "bus_type": "alert",
            "type_label": _bus_type_label("alert"),
            "id": item["alert_id"],
            "title": f"{item['company_name']} 预警",
            "company_name": item["company_name"],
            "status": item["status"],
            "status_label": item.get("status_label", _status_label(item["status"])),
            "created_at": item.get("updated_at"),
            "meta": {
                "summary": item.get("summary"),
                "route": {
                    "path": "/risk",
                    "query": {
                        "company": item["company_name"],
                        "period": item.get("report_period") or report_period or alert_workflow.get("report_period"),
                    },
                },
            },
        }
        for item in alert_workflow["alerts"]
    ]
    watch_records = [
        {
            "bus_type": "watchboard",
            "type_label": _bus_type_label("watchboard"),
            "id": f"watch::{item['company_name']}::{watchboard['report_period']}::{watchboard['user_role']}",
            "title": "重点监测",
            "company_name": item["company_name"],
            "status": "tracked",
            "status_label": _status_label("tracked"),
            "created_at": None,
            "meta": {
                "new_alerts": item.get("new_alerts"),
                "task_count": item.get("task_count"),
                "route": {
                    "path": "/workspace",
                    "query": {
                        "company": item["company_name"],
                        "period": item.get("report_period") or report_period or watchboard.get("report_period"),
                    },
                },
            },
        }
        for item in watchboard["items"]
    ]
    history_records = [
        {
            "bus_type": item["history_type"],
            "type_label": _bus_type_label(item["history_type"]),
            "id": item["id"],
            "title": item["title"],
            "company_name": item.get("company_name"),
            "status": item.get("status"),
            "status_label": item.get("status_label", _status_label(item.get("status"))),
            "created_at": item.get("created_at"),
            "meta": item.get("meta"),
        }
        for item in workspace_history["records"]
    ]
    records = task_records + alert_records + watch_records + history_records
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "user_role": user_role or watchboard.get("user_role"),
        "report_period": report_period or watchboard.get("report_period"),
        "total": len(records),
        "records": records[:limit],
    }


def _guess_metric_code(query: str) -> str:
    mapping = [
        ("应收账款增速", "C3"),
        ("应收增速", "C3"),
        ("回款偏离", "C3"),
        ("利息保障倍数", "S3"),
        ("利息保障", "S3"),
        ("保障倍数", "S3"),
        ("现金质量", "C2"),
        ("净利率", "P2"),
        ("关联交易", "I4"),
        ("营收", "G1"),
        ("收入", "G1"),
        ("利润", "G2"),
        ("研发", "G3"),
        ("毛利", "P1"),
        ("费用", "P3"),
        ("存货", "P4"),
        ("应收", "P5"),
        ("现金流", "C1"),
        ("负债", "S2"),
        ("短债", "S4"),
        ("补助", "I1"),
        ("审计", "I2"),
        ("诉讼", "I3"),
        ("处罚", "I3"),
        ("减值", "I4"),
    ]
    for keyword, metric_code in mapping:
        if keyword in query:
            return metric_code
    return "G1"
