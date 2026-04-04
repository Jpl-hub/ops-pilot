from __future__ import annotations

from typing import Any

from opspilot.application.document_review import (
    _build_document_delivery_preview,
    _build_document_evidence_navigation,
    _document_delivery_guard_message,
    _is_formal_document_result,
    _load_company_document_upgrade_items,
    _load_document_artifact_payload,
)
from opspilot.application.graph_runtime import _dedupe_graph_nodes, _graph_node_id
from opspilot.application.industry_signals import _build_company_signal_graph_context
from opspilot.application.runtime_manifests import _find_watchboard_record
from opspilot.application.runtime_views import (
    _build_frontend_route,
    _build_verify_frontend_route,
    _build_runtime_capsule_module,
    _filter_workspace_runs_for_company,
)


def _company_workspace_compute(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
    profile: str = "full",
) -> dict[str, Any]:
    graph_profile = profile == "graph"
    score_payload = service.score_company(company_name, report_period)
    period = score_payload["report_period"]
    timeline_payload = service.company_timeline(company_name) if not graph_profile else None
    benchmark_payload = service.benchmark_company(company_name, period) if not graph_profile else None
    alert_workflow = service.alert_workflow(report_period=period)
    task_board = service.task_board(user_role=user_role, report_period=period, limit=20)
    document_upgrades = _build_company_document_upgrades(
        service,
        company_name,
        period,
        limit=8 if graph_profile else 20,
        include_preview=not graph_profile,
    )
    runtime_capsule = (
        _build_company_runtime_capsule(service, company_name, period, user_role=user_role)
        if not graph_profile
        else None
    )

    alert_items = [
        item for item in alert_workflow["alerts"] if item["company_name"] == company_name
    ]
    task_items = [item for item in task_board["tasks"] if item["company_name"] == company_name]
    watch_item = _find_watchboard_record(
        service.settings,
        company_name=company_name,
        user_role=user_role,
        report_period=period,
    )
    try:
        research_payload = service.verify_claim(company_name, period)
        research_meta = research_payload.get("report_meta", {})
        research_status = {
            "status": "ready",
            "report_title": research_meta.get("title") or "最新研报",
            "institution": research_meta.get("institution")
            or research_meta.get("source_name")
            or "机构未披露",
            "claim_matches": sum(
                1 for item in research_payload["claim_cards"] if item["status"] == "match"
            ),
            "claim_mismatches": sum(
                1 for item in research_payload["claim_cards"] if item["status"] == "mismatch"
            ),
            "forecast_count": len(research_payload["forecast_cards"]),
        }
    except ValueError as exc:
        research_status = {"status": "missing", "detail": str(exc)}

    payload = {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "score_summary": {
            "total_score": score_payload["scorecard"]["total_score"],
            "grade": score_payload["scorecard"]["grade"],
            "subindustry": score_payload["subindustry"],
            "subindustry_percentile": score_payload["scorecard"]["subindustry_percentile"],
            "risk_count": len(score_payload["scorecard"]["risk_labels"]),
            "opportunity_count": len(score_payload["scorecard"]["opportunity_labels"]),
        },
        "top_risks": [item["name"] for item in score_payload["scorecard"]["risk_labels"][:5]],
        "alerts": {
            "summary": {
                "total": len(alert_items),
                "new": sum(1 for item in alert_items if item["status"] == "new"),
                "in_progress": sum(
                    1 for item in alert_items if item["status"] == "in_progress"
                ),
                "resolved": sum(1 for item in alert_items if item["status"] == "resolved"),
                "dispatched": sum(
                    1 for item in alert_items if item["status"] == "dispatched"
                ),
            },
            "items": alert_items,
        },
        "tasks": {
            "summary": {
                "total": len(task_items),
                "queued": sum(1 for item in task_items if item["status"] == "queued"),
                "in_progress": sum(
                    1 for item in task_items if item["status"] == "in_progress"
                ),
                "done": sum(1 for item in task_items if item["status"] == "done"),
                "blocked": sum(1 for item in task_items if item["status"] == "blocked"),
            },
            "items": task_items,
        },
        "research": research_status,
        "watchboard": {
            "tracked": watch_item is not None,
            "note": watch_item.get("note") if watch_item else None,
            "new_alerts": sum(1 for item in alert_items if item["status"] == "new") if watch_item else 0,
            "in_progress_alerts": sum(
                1 for item in alert_items if item["status"] == "in_progress"
            )
            if watch_item
            else 0,
            "task_count": len(task_items) if watch_item else 0,
        },
        "document_upgrades": {
            "count": document_upgrades["count"],
            "stage_summary": document_upgrades["stage_summary"],
            "items": document_upgrades["items"],
        },
        "execution_stream": _build_company_execution_stream(
            service,
            company_name,
            period,
            user_role=user_role,
            limit=12 if graph_profile else 30,
        ),
        "recent_runs": _filter_workspace_runs_for_company(
            service.workspace_runs(limit=12 if graph_profile else 50)["runs"],
            company_name,
            period,
        ),
    }
    if not graph_profile and timeline_payload is not None and benchmark_payload is not None:
        payload.update(
            {
                "top_opportunities": [
                    item["name"] for item in score_payload["scorecard"]["opportunity_labels"][:5]
                ],
                "action_cards": score_payload["action_cards"][:5],
                "formula_cards": score_payload["formula_cards"][:4],
                "timeline": {
                    "latest_period": timeline_payload["latest_period"],
                    "key_numbers": timeline_payload["key_numbers"],
                    "snapshots": timeline_payload["snapshots"],
                },
                "benchmark": {
                    "target_company": company_name,
                    "top_companies": benchmark_payload["benchmark"][:5],
                },
                "intelligence_runtime": _build_company_intelligence_runtime(
                    service,
                    company_name,
                    period,
                    user_role=user_role,
                ),
                "runtime_capsule": runtime_capsule,
            }
        )
    return payload


def _build_company_runtime_capsule(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    latest_graph = service.graph_query_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_stress = service.stress_test_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_verify = service.verify_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_vision = service.vision_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_analysis = _filter_workspace_runs_for_company(
        service.workspace_runs(limit=200)["runs"],
        company_name,
        period,
        limit=1,
    )["items"]

    modules = [
        _build_runtime_capsule_module(
            module_key="analysis",
            label="协同分析",
            route_path="/workspace",
            company_name=company_name,
            report_period=period,
            record=latest_analysis[0] if latest_analysis else None,
            summary_key="query",
            detail_keys=("query_type",),
        ),
        _build_runtime_capsule_module(
            module_key="graph",
            label="图谱检索",
            route_path="/graph",
            company_name=company_name,
            report_period=period,
            record=latest_graph[0] if latest_graph else None,
            summary_key="intent",
            detail_keys=("created_at",),
        ),
        _build_runtime_capsule_module(
            module_key="stress",
            label="压力测试",
            route_path="/stress",
            company_name=company_name,
            report_period=period,
            record=latest_stress[0] if latest_stress else None,
            summary_key="scenario",
            detail_keys=("created_at",),
        ),
        _build_runtime_capsule_module(
            module_key="verify",
            label="观点核验",
            route_path="/verify",
            company_name=company_name,
            report_period=period,
            record=latest_verify[0] if latest_verify else None,
            summary_key="report_title",
            detail_keys=("source_name", "created_at"),
        ),
        _build_runtime_capsule_module(
            module_key="vision",
            label="多模态解析",
            route_path="/vision",
            company_name=company_name,
            report_period=period,
            record=latest_vision[0] if latest_vision else None,
            summary_key="headline",
            detail_keys=("status_label", "created_at"),
        ),
    ]
    active_count = sum(1 for item in modules if item["status"] != "idle")
    latest_records = [
        item
        for item in (
            latest_analysis[0] if latest_analysis else None,
            latest_graph[0] if latest_graph else None,
            latest_stress[0] if latest_stress else None,
            latest_verify[0] if latest_verify else None,
            latest_vision[0] if latest_vision else None,
        )
        if item is not None
    ]
    latest_records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    latest_label = None
    if latest_records:
        latest_record = latest_records[0]
        latest_label = (
            latest_record.get("query")
            or latest_record.get("intent")
            or latest_record.get("scenario")
            or latest_record.get("report_title")
            or latest_record.get("headline")
        )
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "summary": {
            "active_modules": active_count,
            "latest_label": latest_label,
        },
        "modules": modules,
        "runtime_bus": {
            "total": len([item for item in modules if item["status"] != "idle"]),
            "records": [
                {
                    "module_key": item["module_key"],
                    "label": item["label"],
                    "status": item["status"],
                    "headline": item["summary"],
                    "signal": " / ".join(item.get("details", [])) if item.get("details") else "pending",
                    "route": item["route"],
                    "meta": item.get("meta", {}),
                }
                for item in modules
            ],
        },
    }


def _build_company_intelligence_runtime(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    capsule = _build_company_runtime_capsule(
        service,
        company_name,
        period,
        user_role=user_role,
    )
    latest_graph_runs = service.graph_query_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_stress_runs = service.stress_test_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_verify_runs = service.verify_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_vision_runs = service.vision_runs(
        company_name=company_name,
        report_period=period,
        user_role=user_role,
        limit=1,
    )["runs"]
    latest_analysis = _filter_workspace_runs_for_company(
        service.workspace_runs(limit=200)["runs"],
        company_name,
        period,
        limit=1,
    )["items"]
    vision_runtime = service.company_vision_runtime(
        company_name,
        period,
        user_role=user_role,
    )

    graph_detail = (
        service.graph_query_run_detail(latest_graph_runs[0]["run_id"])
        if latest_graph_runs
        else None
    )
    stress_detail = (
        service.stress_test_run_detail(latest_stress_runs[0]["run_id"])
        if latest_stress_runs
        else None
    )
    verify_detail = (
        service.verify_run_detail(latest_verify_runs[0]["run_id"])
        if latest_verify_runs
        else None
    )

    runs = [
        item
        for item in (
            latest_analysis[0] if latest_analysis else None,
            latest_graph_runs[0] if latest_graph_runs else None,
            latest_stress_runs[0] if latest_stress_runs else None,
            latest_verify_runs[0] if latest_verify_runs else None,
            latest_vision_runs[0] if latest_vision_runs else None,
        )
        if item
    ]
    runs.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    module_pulses = [
        {
            "module_key": "analysis",
            "label": "协同分析",
            "status": "ready" if latest_analysis else "idle",
            "headline": (latest_analysis[0].get("query") if latest_analysis else "等待分析任务"),
            "signal": (latest_analysis[0].get("query_type") if latest_analysis else "pending"),
            "intensity": 72 if latest_analysis else 0,
            "route": {"path": "/workspace", "query": {"company": company_name, "period": period}},
        },
        {
            "module_key": "graph",
            "label": "图谱检索",
            "status": "ready" if latest_graph_runs else "idle",
            "headline": latest_graph_runs[0].get("intent") if latest_graph_runs else "等待图谱检索",
            "signal": f"{len(graph_detail.get('graph_live_frames', []))} 帧" if graph_detail else "pending",
            "intensity": (
                max((frame.get("intensity", 0) for frame in graph_detail.get("graph_live_frames", [])), default=0)
                if graph_detail
                else 0
            ),
            "route": {"path": "/graph", "query": {"company": company_name, "period": period}},
        },
        {
            "module_key": "stress",
            "label": "压力测试",
            "status": "ready" if latest_stress_runs else "idle",
            "headline": latest_stress_runs[0].get("scenario") if latest_stress_runs else "等待冲击推演",
            "signal": stress_detail.get("severity", {}).get("level") if stress_detail else "pending",
            "intensity": (
                max((frame.get("impact_score", 0) for frame in stress_detail.get("stress_wavefront", [])), default=0)
                if stress_detail
                else 0
            ),
            "route": {"path": "/stress", "query": {"company": company_name, "period": period}},
        },
        {
            "module_key": "verify",
            "label": "观点核验",
            "status": "ready" if latest_verify_runs else "idle",
            "headline": latest_verify_runs[0].get("report_title") if latest_verify_runs else "等待观点核验",
            "signal": (
                f"{latest_verify_runs[0].get('mismatch_count', 0)} 处偏差"
                if latest_verify_runs
                else "pending"
            ),
            "intensity": (
                min(
                    100,
                    32
                    + latest_verify_runs[0].get("mismatch_count", 0) * 18
                    + latest_verify_runs[0].get("insufficient_count", 0) * 12,
                )
                if verify_detail
                else 0
            ),
            "route": (
                _build_verify_frontend_route(latest_verify_runs[0])
                if latest_verify_runs
                else _build_frontend_route(
                    "/verify",
                    query={"company": company_name, "period": period},
                )
            ),
        },
        {
            "module_key": "vision",
            "label": "多模态解析",
            "status": "ready" if any(item["status"] == "completed" for item in vision_runtime["stages"]) else "idle",
            "headline": vision_runtime["vision"].get("headline") or "等待解析结果",
            "signal": f"{len(vision_runtime['stages'])} 阶段",
            "intensity": min(
                100,
                28 + 24 * sum(1 for item in vision_runtime["stages"] if item["status"] == "completed"),
            ),
            "route": {"path": "/vision", "query": {"company": company_name, "period": period}},
        },
    ]
    runtime_bus = [
        {
            "module_key": pulse["module_key"],
            "label": pulse["label"],
            "status": pulse["status"],
            "headline": pulse["headline"],
            "signal": pulse["signal"],
            "intensity": pulse["intensity"],
            "route": pulse["route"],
            "meta": {
                "created_at": (
                    latest_analysis[0].get("created_at")
                    if pulse["module_key"] == "analysis" and latest_analysis
                    else latest_graph_runs[0].get("created_at")
                    if pulse["module_key"] == "graph" and latest_graph_runs
                    else latest_stress_runs[0].get("created_at")
                    if pulse["module_key"] == "stress" and latest_stress_runs
                    else latest_verify_runs[0].get("created_at")
                    if pulse["module_key"] == "verify" and latest_verify_runs
                    else latest_vision_runs[0].get("created_at")
                    if pulse["module_key"] == "vision" and latest_vision_runs
                    else None
                ),
                "run_id": (
                    latest_analysis[0].get("run_id")
                    if pulse["module_key"] == "analysis" and latest_analysis
                    else latest_graph_runs[0].get("run_id")
                    if pulse["module_key"] == "graph" and latest_graph_runs
                    else latest_stress_runs[0].get("run_id")
                    if pulse["module_key"] == "stress" and latest_stress_runs
                    else latest_verify_runs[0].get("run_id")
                    if pulse["module_key"] == "verify" and latest_verify_runs
                    else latest_vision_runs[0].get("run_id")
                    if pulse["module_key"] == "vision" and latest_vision_runs
                    else None
                ),
            },
        }
        for pulse in module_pulses
    ]
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "summary": {
            "active_modules": capsule["summary"]["active_modules"],
            "latest_label": capsule["summary"].get("latest_label"),
            "latest_created_at": runs[0].get("created_at") if runs else None,
            "run_count": len(runs),
        },
        "module_pulses": module_pulses,
        "runtime_bus": {
            "total": len([item for item in runtime_bus if item["status"] != "idle"]),
            "records": runtime_bus,
        },
        "runtime_capsule": capsule,
    }


def _build_company_execution_stream(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
    limit: int = 30,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    alert_items = [
        {
            "stream_type": "alert",
            "id": item["alert_id"],
            "title": f"{item['company_name']} 预警",
            "status": item["status"],
            "created_at": item.get("created_at"),
            "meta": {
                "priority": item.get("priority"),
                "reason": item.get("summary"),
                "route": _build_frontend_route(
                    "/risk",
                    query={"company": company_name, "period": period},
                ),
            },
        }
        for item in service.alert_workflow(report_period=period)["alerts"]
        if item["company_name"] == company_name
    ]
    task_items = [
        {
            "stream_type": "task",
            "id": item["task_id"],
            "title": item["title"],
            "status": item["status"],
            "created_at": item.get("created_at"),
            "meta": {
                "priority": item.get("priority"),
                "owner": item.get("owner_role"),
                "route": _build_frontend_route(
                    "/workspace",
                    query={"company": company_name, "period": period},
                ),
            },
        }
        for item in service.task_board(user_role=user_role, report_period=period, limit=200)["tasks"]
        if item["company_name"] == company_name
    ]
    watch_item = _find_watchboard_record(
        service.settings,
        company_name=company_name,
        user_role=user_role,
        report_period=period,
    )
    watch_records = []
    if watch_item is not None:
        watch_records.append(
            {
                "stream_type": "watchboard",
                "id": f"watch::{company_name}::{period}::{user_role}",
                "title": "已加入重点监测",
                "status": "tracked",
                "created_at": watch_item.get("updated_at") or watch_item.get("created_at"),
                "meta": {
                    "note": watch_item.get("note"),
                    "route": _build_frontend_route(
                        "/workspace",
                        query={"company": company_name, "period": period},
                    ),
                },
            }
        )
    document_items = [
        {
            "stream_type": "document_upgrade",
            "id": f"{item['stage']}::{item['report_id']}",
            "title": f"{item['stage']} · {item['company_name']}",
            "status": item.get("status"),
            "created_at": item.get("completed_at"),
            "meta": {
                "stage": item.get("stage"),
                "route": item.get("route"),
                "evidence_navigation": item.get("evidence_navigation"),
            },
        }
        for item in _build_company_document_upgrades(
            service,
            company_name,
            period,
            limit=100,
            include_preview=False,
        )["items"]
    ]
    stress_items = [
        {
            "stream_type": "stress_test",
            "id": item["run_id"],
            "title": f"压力测试 · {item['company_name']}",
            "status": item.get("severity", {}).get("level", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "scenario": item.get("scenario"),
                "severity": item.get("severity", {}).get("label"),
                "route": _build_frontend_route(
                    "/stress",
                    query={
                        "company": item.get("company_name"),
                        "period": item.get("report_period"),
                        "role": item.get("user_role"),
                        "run_id": item.get("run_id"),
                    },
                ),
            },
        }
        for item in service.stress_test_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=100,
        )["runs"]
    ]
    verify_items = [
        {
            "stream_type": "claim_verify",
            "id": item["run_id"],
            "title": "观点核验",
            "status": item.get("status_label", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "report_title": item.get("report_title"),
                "headline": item.get("headline"),
                "source_name": item.get("source_name"),
                "route": _build_verify_frontend_route(item),
            },
        }
        for item in service.verify_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=100,
        )["runs"]
    ]
    graph_items = [
        {
            "stream_type": "graph_query",
            "id": item["run_id"],
            "title": "图谱检索",
            "status": "completed",
            "created_at": item.get("created_at"),
            "meta": {
                "intent": item.get("intent"),
                "route": _build_frontend_route(
                    "/graph",
                    query={
                        "company": item.get("company_name"),
                        "period": item.get("report_period"),
                        "role": item.get("user_role"),
                        "run_id": item.get("run_id"),
                    },
                ),
            },
        }
        for item in service.graph_query_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=100,
        )["runs"]
    ]
    vision_items = [
        {
            "stream_type": "vision_analyze",
            "id": item["run_id"],
            "title": "多模态解析",
            "status": item.get("status_label", "completed"),
            "created_at": item.get("created_at"),
            "meta": {
                "headline": item.get("headline"),
                "route": _build_frontend_route(
                    "/vision",
                    query={
                        "company": item.get("company_name"),
                        "period": item.get("report_period"),
                        "role": item.get("user_role"),
                        "run_id": item.get("run_id"),
                    },
                ),
            },
        }
        for item in service.vision_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=100,
        )["runs"]
    ]
    analysis_runs = [
        {
            "stream_type": "analysis_run",
            "id": item["run_id"],
            "title": item.get("query") or "分析执行",
            "status": "completed",
            "created_at": item.get("created_at"),
            "meta": {
                "query_type": item.get("query_type"),
                "route": _build_frontend_route(
                    "/workspace",
                    query={
                        "company": item.get("company_name"),
                        "period": item.get("report_period"),
                        "role": item.get("user_role"),
                        "run_id": item.get("run_id"),
                    },
                ),
            },
        }
        for item in service.workspace_runs(limit=200)["runs"]
        if item.get("company_name") == company_name
        and item.get("report_period") == period
        and item.get("user_role") == user_role
    ]
    records = alert_items + task_items + watch_records + document_items + stress_items + verify_items + graph_items + vision_items + analysis_runs
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "total": len(records),
        "summary": {
            "alerts": len(alert_items),
            "tasks": len(task_items),
            "watch_records": len(watch_records),
            "document_upgrades": len(document_items),
            "verify_runs": len(verify_items),
            "graph_queries": len(graph_items),
            "vision_runs": len(vision_items),
            "analysis_runs": len(analysis_runs),
        },
        "records": records[:limit],
    }


def _build_company_document_upgrades(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    limit: int = 20,
    include_preview: bool = True,
    include_evidence_navigation: bool = True,
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    upgrade_items = _load_company_document_upgrade_items(service.settings, company_name, period)
    enriched_items: list[dict[str, Any]] = []
    stage_summary: dict[str, int] = {}
    for item in upgrade_items[:limit]:
        stage = item["stage"]
        stage_summary[stage] = stage_summary.get(stage, 0) + 1
        artifact_preview = None
        artifact_summary = item.get("artifact_summary")
        artifact_source = item.get("artifact_source")
        contract_status = item.get("contract_status")
        artifact_payload = None
        if item.get("status") == "completed":
            artifact_payload = _load_document_artifact_payload(item)
            if artifact_payload is not None:
                artifact_source = artifact_source or artifact_payload.get("source")
                formal_result = _is_formal_document_result(
                    stage=stage,
                    artifact_source=artifact_source,
                    contract_status=contract_status,
                )
                if include_preview:
                    artifact_preview = _build_document_delivery_preview(
                        stage=stage,
                        artifact_source=artifact_source,
                        contract_status=contract_status,
                        artifact=artifact_payload,
                    )
                artifact_summary = artifact_summary or artifact_payload.get("summary")
                if not formal_result:
                    artifact_summary = _document_delivery_guard_message(
                        stage=stage,
                        artifact_source=artifact_source,
                        contract_status=contract_status,
                    )
            if include_evidence_navigation and artifact_payload is not None and _is_formal_document_result(
                stage=stage,
                artifact_source=artifact_source,
                contract_status=contract_status,
            ):
                evidence_navigation = _build_document_evidence_navigation(
                    repository=service.repository,
                    company_name=item["company_name"],
                    report_period=item.get("report_period"),
                    artifact=artifact_payload,
                )
            else:
                evidence_navigation = None
        else:
            evidence_navigation = None
        enriched_items.append(
            {
                **item,
                "artifact_summary": artifact_summary,
                "artifact_source": artifact_source,
                "artifact_preview": artifact_preview,
                "evidence_navigation": evidence_navigation,
                "route": {
                    "path": "/admin",
                    "query": {"stage": stage, "report_id": item["report_id"]},
                    "label": "查看解析详情",
                },
            }
        )
    return {
        "company_name": company_name,
        "report_period": period,
        "count": len(upgrade_items),
        "stage_summary": stage_summary,
        "items": enriched_items,
    }


def _build_company_graph(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_payload = workspace or service.company_workspace(
        company_name,
        report_period,
        user_role=user_role,
    )
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    company_node = _graph_node_id("company", company_name)
    nodes.append(
        {
            "id": company_node,
            "type": "company",
            "label": company_name,
            "meta": {
                "report_period": workspace_payload["report_period"],
                "score": workspace_payload["score_summary"]["total_score"],
                "grade": workspace_payload["score_summary"]["grade"],
            },
        }
    )
    period_node = _graph_node_id("period", workspace_payload["report_period"])
    nodes.append({"id": period_node, "type": "report_period", "label": workspace_payload["report_period"], "meta": {}})
    edges.append({"source": company_node, "target": period_node, "label": "对应报期"})

    for risk_name in workspace_payload["top_risks"]:
        risk_node = _graph_node_id("risk", risk_name)
        nodes.append({"id": risk_node, "type": "risk_label", "label": risk_name, "meta": {}})
        edges.append({"source": company_node, "target": risk_node, "label": "风险"})

    for task in workspace_payload["tasks"]["items"][:5]:
        task_node = _graph_node_id("task", task["task_id"])
        nodes.append(
            {
                "id": task_node,
                "type": "task",
                "label": task["title"],
                "meta": {"priority": task["priority"], "status": task["status"]},
            }
        )
        edges.append({"source": company_node, "target": task_node, "label": "整改任务"})

    for alert in workspace_payload["alerts"]["items"][:5]:
        alert_node = _graph_node_id("alert", alert["alert_id"])
        nodes.append(
            {
                "id": alert_node,
                "type": "alert",
                "label": alert["summary"],
                "meta": {"status": alert["status"], "risk_delta": alert["risk_delta"]},
            }
        )
        edges.append({"source": period_node, "target": alert_node, "label": "主动预警"})

    for run in workspace_payload["recent_runs"]["items"][:4]:
        run_node = _graph_node_id("run", run["run_id"])
        nodes.append(
            {
                "id": run_node,
                "type": "workspace_run",
                "label": run["query"],
                "meta": {
                    "query_type": run.get("query_type"),
                    "created_at": run.get("created_at"),
                    "user_role": run.get("user_role"),
                },
            }
        )
        edges.append({"source": company_node, "target": run_node, "label": "分析运行"})

    if workspace_payload["research"]["status"] == "ready":
        research_label = workspace_payload["research"]["report_title"]
        research_node = _graph_node_id("research", research_label)
        nodes.append(
            {
                "id": research_node,
                "type": "research_report",
                "label": research_label,
                "meta": {
                    "institution": workspace_payload["research"]["institution"],
                    "forecast_count": workspace_payload["research"]["forecast_count"],
                },
            }
        )
        edges.append({"source": company_node, "target": research_node, "label": "研报核验"})

    signal_context_cache_key = "graph-signal-context:" f"{company_name}:{workspace_payload['score_summary'].get('subindustry') or ''}"
    signal_context = service._cache_get(signal_context_cache_key)
    if signal_context is None:
        signal_context = _build_company_signal_graph_context(
            service.settings,
            company_name=company_name,
            subindustry=workspace_payload["score_summary"].get("subindustry"),
        )
        service._cache_set(signal_context_cache_key, signal_context)

    if signal_context.get("event_available"):
        latest_signal_key = (
            signal_context.get("latest_event_time")
            or signal_context.get("latest_headline")
            or signal_context.get("signal_status")
            or company_name
        )
        signal_event_node = _graph_node_id("signal", f"{company_name}::{latest_signal_key}")
        nodes.append(
            {
                "id": signal_event_node,
                "type": "signal_event",
                "label": signal_context.get("latest_headline") or "外部信号",
                "meta": {
                    "signal_status": signal_context.get("signal_status"),
                    "latest_signal_kind": signal_context.get("latest_signal_kind"),
                    "latest_event_time": signal_context.get("latest_event_time"),
                    "freshness_status": signal_context.get("freshness_status"),
                    "freshness_label": signal_context.get("freshness_label"),
                    "signal_count": signal_context.get("signal_count"),
                    "source_count": signal_context.get("source_count"),
                    "summary": signal_context.get("event_summary"),
                },
            }
        )
        edges.append({"source": company_node, "target": signal_event_node, "label": "最新信号"})
        edges.append({"source": period_node, "target": signal_event_node, "label": "报期外部事件"})

    if signal_context.get("timeline_available"):
        signal_timeline_node = _graph_node_id("signal-window", company_name)
        nodes.append(
            {
                "id": signal_timeline_node,
                "type": "signal_timeline",
                "label": f"近 {signal_context.get('window_days') or 7} 日信号窗口",
                "meta": {
                    "latest_event_time": signal_context.get("latest_event_time"),
                    "freshness_status": signal_context.get("freshness_status"),
                    "freshness_label": signal_context.get("freshness_label"),
                    "signal_count": signal_context.get("signal_count"),
                    "source_count": signal_context.get("source_count"),
                    "external_heat": signal_context.get("total_heat"),
                    "latest_heat": signal_context.get("latest_heat"),
                    "momentum": signal_context.get("momentum"),
                    "active_days": signal_context.get("active_days"),
                    "window_days": signal_context.get("window_days"),
                    "date_axis": signal_context.get("date_axis"),
                    "summary": signal_context.get("timeline_summary"),
                },
            }
        )
        edges.append({"source": company_node, "target": signal_timeline_node, "label": "时序热度"})
        edges.append({"source": period_node, "target": signal_timeline_node, "label": "窗口信号"})
        if signal_context.get("event_available"):
            edges.append({"source": signal_event_node, "target": signal_timeline_node, "label": "时序沉淀"})

    if signal_context.get("subindustry_available"):
        subindustry_signal_node = _graph_node_id("subindustry-signal", str(signal_context.get("subindustry") or company_name))
        nodes.append(
            {
                "id": subindustry_signal_node,
                "type": "subindustry_signal",
                "label": f"{signal_context.get('subindustry') or '所属子行业'} 热度迁移",
                "meta": {
                    "subindustry": signal_context.get("subindustry"),
                    "signal_count": signal_context.get("subindustry_signal_count"),
                    "external_heat": signal_context.get("subindustry_total_heat"),
                    "latest_heat": signal_context.get("subindustry_latest_heat"),
                    "momentum": signal_context.get("subindustry_momentum"),
                    "active_days": signal_context.get("subindustry_active_days"),
                    "window_days": signal_context.get("window_days"),
                    "summary": signal_context.get("subindustry_summary"),
                },
            }
        )
        edges.append({"source": company_node, "target": subindustry_signal_node, "label": "板块共振"})
        if signal_context.get("timeline_available"):
            edges.append({"source": subindustry_signal_node, "target": signal_timeline_node, "label": "热度传导"})

    for item in workspace_payload["document_upgrades"]["items"][:6]:
        artifact_node = _graph_node_id("artifact", f"{item['stage']}::{item['report_id']}")
        nodes.append(
            {
                "id": artifact_node,
                "type": "document_artifact",
                "label": item["stage"],
                "meta": {
                    "report_id": item["report_id"],
                    "status": item["status"],
                    "summary": item["artifact_summary"],
                },
            }
        )
        edges.append({"source": period_node, "target": artifact_node, "label": "解析结果"})
        evidence_navigation = item.get("evidence_navigation") or {}
        primary_route = evidence_navigation.get("primary_route") or {}
        if primary_route.get("path"):
            evidence_node = _graph_node_id("artifact_evidence", f"{item['stage']}::{item['report_id']}")
            nodes.append(
                {
                    "id": evidence_node,
                    "type": "artifact_evidence",
                    "label": "证据导航",
                    "meta": {
                        "path": primary_route.get("path"),
                        "page": primary_route.get("page"),
                        "anchor_terms": evidence_navigation.get("anchor_terms", []),
                    },
                }
            )
            edges.append({"source": artifact_node, "target": evidence_node, "label": "证据入口"})

    if workspace_payload["watchboard"]["tracked"]:
        monitor_node = _graph_node_id("watchboard", company_name)
        nodes.append(
            {
                "id": monitor_node,
                "type": "watchboard",
                "label": "监测中",
                "meta": {
                    "note": workspace_payload["watchboard"]["note"],
                    "new_alerts": workspace_payload["watchboard"]["new_alerts"],
                    "task_count": workspace_payload["watchboard"]["task_count"],
                },
            }
        )
        edges.append({"source": company_node, "target": monitor_node, "label": "持续监测"})

    for stream in workspace_payload["execution_stream"]["records"][:8]:
        stream_node = _graph_node_id("stream", f"{stream['stream_type']}::{stream['id']}")
        nodes.append(
            {
                "id": stream_node,
                "type": "execution_stream",
                "label": stream["title"],
                "meta": {
                    "stream_type": stream["stream_type"],
                    "status": stream.get("status"),
                    "created_at": stream.get("created_at"),
                },
            }
        )
        edges.append({"source": company_node, "target": stream_node, "label": "执行流"})

    deduped_nodes = _dedupe_graph_nodes(nodes)
    return {
        "company_name": company_name,
        "report_period": workspace_payload["report_period"],
        "nodes": deduped_nodes,
        "edges": edges,
        "summary": {
            "node_count": len(deduped_nodes),
            "edge_count": len(edges),
            "task_count": workspace_payload["tasks"]["summary"]["total"],
            "alert_count": workspace_payload["alerts"]["summary"]["total"],
            "document_upgrade_count": workspace_payload["document_upgrades"]["count"],
            "run_count": workspace_payload["recent_runs"]["count"],
            "watch_tracked": workspace_payload["watchboard"]["tracked"],
            "signal_count": int(signal_context.get("signal_count") or 0),
            "signal_freshness": signal_context.get("freshness_label"),
        },
    }
