from __future__ import annotations

from datetime import datetime
from typing import Any
import time

from opspilot.application.data_runtime import (
    _build_official_data_status,
    _build_innovation_radar,
    _build_industry_live_chart,
)
from opspilot.application.industry_signals import (
    _build_external_signal_market_tape,
    _build_external_signal_stream,
    _build_kafka_signal_market_tape,
    _build_kafka_signal_runtime,
    _build_streaming_anomaly_board,
    _build_streaming_anomaly_market_tape,
    _build_streaming_attention_matrix,
    _build_streaming_heat_chart,
    _load_company_signal_snapshot,
    _load_company_signal_timeline,
    _load_subindustry_signal_heatmap,
    _merge_streaming_anomalies_into_attention_matrix,
)
from opspilot.application.runtime_manifests import (
    _append_industry_brain_snapshot,
    _load_industry_brain_manifest,
)
from opspilot.application.runtime_views import (
    _build_brain_command_surface,
    _build_brain_signal_tape,
    _build_industry_brain_history_snapshot,
    _build_industry_brain_watchboard_snapshot,
)
from opspilot.application.workspace_service import ROLE_PROFILES
from opspilot.application.document_pipeline import _utcnow_iso


def _normalize_user_role(user_role: str | None) -> str:
    return user_role if user_role in ROLE_PROFILES else "investor"


def _industry_brain_cache_context(
    service: Any,
    *,
    user_role: str,
    report_period: str,
) -> dict[str, Any]:
    root_cache = service._industry_brain_cache
    contexts = root_cache.setdefault("contexts", {})
    cache_key = f"{user_role}:{report_period}"
    cache = contexts.get(cache_key)
    if cache is None:
        cache = {
            "generated_at": 0.0,
            "sequence": 0,
            "payload": None,
            "history": [],
        }
        contexts[cache_key] = cache
    return cache


def _role_route(
    route: dict[str, Any] | None,
    *,
    company_name: str | None,
    user_role: str,
    report_period: str,
) -> dict[str, Any]:
    payload = dict(route or {})
    payload["path"] = str(payload.get("path") or "/score")
    query = dict(payload.get("query") or {})
    if company_name and not query.get("company"):
        query["company"] = company_name
    if report_period and not query.get("period"):
        query["period"] = report_period
    query["role"] = user_role
    payload["query"] = query
    return payload


def _inject_role_routes(
    records: list[dict[str, Any]],
    *,
    user_role: str,
    report_period: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in records:
        company_name = item.get("company_name")
        if not item.get("route") and not company_name:
            enriched.append(item)
            continue
        enriched.append(
            {
                **item,
                "route": _role_route(
                    item.get("route"),
                    company_name=company_name,
                    user_role=user_role,
                    report_period=report_period,
                ),
            }
        )
    return enriched


def _industry_brain_history(
    settings: Any,
    *,
    limit: int = 24,
    user_role: str | None = None,
    report_period: str | None = None,
) -> dict[str, Any]:
    manifest = _load_industry_brain_manifest(settings)
    role_key = _normalize_user_role(user_role) if user_role else None
    records = []
    for item in manifest["records"]:
        item_role = item.get("user_role")
        if role_key is not None:
            if item_role is None:
                if role_key != "management":
                    continue
            elif item_role != role_key:
                continue
        if report_period is not None and item.get("report_period") != report_period:
            continue
        records.append(item)
    records.sort(key=lambda item: item.get("refreshed_at") or "", reverse=True)
    return {
        "generated_at": manifest.get("generated_at"),
        "user_role": role_key,
        "report_period": report_period,
        "total": len(records),
        "records": records[:limit],
    }


def _build_industry_brain_payload(
    service: Any,
    *,
    force_refresh: bool,
    user_role: str = "management",
    report_period: str | None = None,
) -> dict[str, Any]:
    role_key = _normalize_user_role(user_role)
    preferred_period = report_period or service._preferred_period()
    now = time.monotonic()
    cache = _industry_brain_cache_context(
        service,
        user_role=role_key,
        report_period=preferred_period,
    )
    if (
        not force_refresh
        and cache.get("payload") is not None
        and now - float(cache.get("generated_at") or 0.0) < 8.0
    ):
        payload = dict(cache["payload"])
        payload["stream"] = {
            **payload["stream"],
            "ws_connected": True,
            "refreshed_at": _utcnow_iso(),
        }
        return payload

    health = service.health()
    period_company_count = len(service.repository.list_companies(preferred_period))
    alert_workflow = service.alert_workflow(report_period=preferred_period)
    task_board = service.task_board(user_role=role_key, report_period=preferred_period, limit=200)
    risk_payload = service.risk_scan(preferred_period)
    watchboard = _build_industry_brain_watchboard_snapshot(
        service.settings,
        report_period=preferred_period,
        user_role=role_key,
        alert_workflow=alert_workflow,
        task_board=task_board,
        risk_payload=risk_payload,
        limit=8,
    )
    innovation_radar = _build_innovation_radar()
    data_status = _build_official_data_status(service.settings)
    workspace_history = _build_industry_brain_history_snapshot(
        service.settings,
        report_period=preferred_period,
        user_role=role_key,
        limit=10,
    )

    live_point = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "alerts": alert_workflow["summary"]["new"] + alert_workflow["summary"]["in_progress"],
        "tasks": task_board["summary"]["in_progress"],
        "watching": watchboard["summary"]["tracked_companies"],
        "history": workspace_history["total"],
    }
    history_points = list(cache.get("history") or [])
    history_points.append(live_point)
    history_points = history_points[-8:]
    cache["history"] = history_points
    cache["sequence"] = int(cache.get("sequence") or 0) + 1

    top_risk_companies = risk_payload["risk_board"][:8]
    recent_records = workspace_history["records"][:10]
    external_signal_stream = _build_external_signal_stream(
        service.settings,
        focus_companies=top_risk_companies,
    )
    kafka_signal_runtime = _build_kafka_signal_runtime(service.settings)
    streaming_snapshot = _load_company_signal_snapshot(service.settings)
    streaming_timeline = _load_company_signal_timeline(service.settings)
    streaming_heatmap = _load_subindustry_signal_heatmap(service.settings)
    streaming_anomalies = _build_streaming_anomaly_board(
        preferred_period=preferred_period,
        top_risk_companies=top_risk_companies,
        signal_snapshot=streaming_snapshot,
        signal_timeline=streaming_timeline,
        signal_heatmap=streaming_heatmap,
        kafka_signal_runtime=kafka_signal_runtime,
    )
    streaming_anomalies = {
        **streaming_anomalies,
        "items": _inject_role_routes(
            list(streaming_anomalies.get("items") or []),
            user_role=role_key,
            report_period=preferred_period,
        ),
    }

    market_tape = [
        {
            "label": "主周期预警",
            "value": str(alert_workflow["summary"]["new"] + alert_workflow["summary"]["in_progress"]),
            "delta": f"+{alert_workflow['summary']['new']} 新增",
            "tone": "risk",
        },
        {
            "label": "在办任务",
            "value": str(task_board["summary"]["in_progress"]),
            "delta": f"{task_board['summary']['done']} 已完成",
            "tone": "accent",
        },
        {
            "label": "监测公司",
            "value": str(watchboard["summary"]["tracked_companies"]),
            "delta": f"{watchboard['summary']['companies_with_new_alerts']} 家新增关注",
            "tone": "success",
        },
        {
            "label": "文档升级",
            "value": str(data_status.get("bronze_periodic_reports", {}).get("record_count", 0)),
            "delta": f"{data_status.get('silver_financial_metrics', {}).get('record_count', 0)} 条结构化",
            "tone": "default",
        },
    ]
    market_tape.extend(_build_external_signal_market_tape(external_signal_stream))
    market_tape.extend(_build_kafka_signal_market_tape(kafka_signal_runtime))
    market_tape.extend(_build_streaming_anomaly_market_tape(streaming_anomalies))

    execution_flash = [
        {
            "title": item.get("title", "系统执行"),
            "summary": item.get("type_label", item.get("type", "任务")),
            "status": item.get("status_label", item.get("status", "完成")),
            "route": item.get("route"),
        }
        for item in recent_records[:6]
    ]

    attention_matrix = _build_streaming_attention_matrix(
        preferred_period=preferred_period,
        top_risk_companies=top_risk_companies,
        signal_snapshot=streaming_snapshot,
        signal_timeline=streaming_timeline,
    )
    attention_matrix = _merge_streaming_anomalies_into_attention_matrix(
        attention_matrix,
        streaming_anomalies,
    )
    attention_matrix = _inject_role_routes(
        attention_matrix,
        user_role=role_key,
        report_period=preferred_period,
    )

    live_events = []
    for item in watchboard["items"][:5]:
        live_events.append(
            {
                "company_name": item["company_name"],
                "headline": item["top_risks"][0] if item["top_risks"] else "持续监测",
                "status": (
                    "新增预警"
                    if item["new_alerts"]
                    else "任务处理中"
                    if item["task_count"]
                    else "持续监测"
                ),
                "route": {
                    "path": "/score",
                    "query": {
                        "company": item["company_name"],
                        "period": preferred_period,
                        "role": role_key,
                    },
                },
            }
        )
    signal_feed = external_signal_stream.get("signals") or live_events

    payload = {
        "user_role": role_key,
        "role_label": ROLE_PROFILES[role_key]["label"],
        "focus_title": ROLE_PROFILES[role_key]["focus_title"],
        "report_period": preferred_period,
        "stream": {
            "sequence": cache["sequence"],
            "ws_connected": True,
            "refreshed_at": _utcnow_iso(),
        },
        "sector_tags": [
            {"label": item.get("subindustry"), "count": int(item.get("total_heat") or 0)}
            for item in streaming_heatmap.get("top_subindustries", [])[:4]
            if item.get("subindustry")
        ],
        "metrics": [
            {
                "label": "正式公司覆盖",
                "value": str(period_company_count),
                "hint": f"{preferred_period} 主周期已接入正式公司数",
                "tone": "accent",
            },
            {
                "label": "主周期预警",
                "value": str(alert_workflow["summary"]["new"] + alert_workflow["summary"]["in_progress"]),
                "hint": "实时来自统一预警工作流",
                "tone": "danger" if alert_workflow["summary"]["new"] else "default",
            },
            {
                "label": "监测板跟踪",
                "value": str(watchboard["summary"]["tracked_companies"]),
                "hint": "已进入持续监测的重点公司",
                "tone": "success",
            },
            {
                "label": "运行历史",
                "value": str(workspace_history["total"]),
                "hint": "统一执行总线累计记录",
            },
        ],
        "charts": [
            {
                "title": "主周期预警 / 任务 / 监测板实时跳动",
                "options": _build_industry_live_chart(history_points),
            },
            {
                "title": "子行业外部信号热度迁移",
                "options": _build_streaming_heat_chart(streaming_heatmap),
            },
        ],
        "radar_events": innovation_radar["items"][:6],
        "document_pipeline": {
            "periodic_reports": data_status.get("periodic_reports", {}).get("record_count", 0),
            "silver_metrics": data_status.get("silver_financial_metrics", {}).get("record_count", 0),
            "bronze_reports": data_status.get("bronze_periodic_reports", {}).get("record_count", 0),
        },
        "market_tape": market_tape,
        "brain_command_surface": _build_brain_command_surface(
            preferred_period=preferred_period,
            market_tape=market_tape,
            attention_matrix=attention_matrix,
            execution_flash=execution_flash,
        ),
        "brain_signal_tape": _build_brain_signal_tape(
            market_tape=market_tape,
            live_events=signal_feed,
            history_points=history_points,
        ),
        "execution_flash": execution_flash,
        "attention_matrix": attention_matrix,
        "live_events": live_events,
        "external_signal_stream": external_signal_stream,
        "kafka_signal_runtime": kafka_signal_runtime,
        "streaming_snapshot": streaming_snapshot,
        "streaming_timeline": streaming_timeline,
        "streaming_heatmap": streaming_heatmap,
        "streaming_anomalies": streaming_anomalies,
        "top_risk_companies": [
            {
                "company_name": item["company_name"],
                "subindustry": item["subindustry"],
                "risk_count": item["risk_count"],
                "risk_labels": item["risk_labels"][:3],
                "route": {
                    "path": "/score",
                    "query": {
                        "company": item["company_name"],
                        "period": preferred_period,
                        "role": role_key,
                    },
                },
            }
            for item in top_risk_companies
        ],
    }
    _append_industry_brain_snapshot(service.settings, payload)
    cache["generated_at"] = now
    cache["payload"] = payload
    return payload
