from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from datetime import datetime
import json
import time

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.rules import evaluate_risk_labels
# 域服务 — 拆分后的模块化架构
from opspilot.application.alert_runtime import (
    _build_alert_board,
    _build_workspace_alert_queue,
    _get_company_periods,
)
from opspilot.application.scoring_service import (
    ScoringService,
    _build_evidence_groups,
    _build_label_cards,
)
from opspilot.application.admin_delivery import (
    _append_document_pipeline_run_record,
    _build_acceptance_checklist,
    _build_admin_job_catalog,
    _build_admin_quality_overview,
    _build_delivery_readiness,
    _build_document_pipeline_execution_feedback,
    _build_document_pipeline_overview,
    _build_runtime_readiness,
    _delivery_stage_label,
    _document_stage_label,
    _resolve_document_contract_status,
    _status_label,
    _summarize_contract_statuses,
)
from opspilot.application.research_claims import (
    _build_claim_cards,
    _clip_claim_excerpt,
    _infer_report_period_from_text,
)
from opspilot.application.research_reports import (
    _build_research_report_insight,
    _research_report_bucket,
    _research_report_content_score,
    _select_research_report,
)
from opspilot.application.research_review import (
    _build_claim_chart,
    _build_claim_evidence,
    _build_claim_evidence_groups,
    _build_research_compare_chart,
    _format_rating_text,
    _render_claim_answer,
    _summarize_forecast_cards,
)
from opspilot.application.research_compare import (
    _build_research_compare_filter_options,
    _build_research_compare_insights,
    _build_research_compare_sort_options,
    _build_research_timeline_groups,
    _filter_research_compare_rows,
    _label_research_compare_rows,
    _sort_research_compare_rows,
)
from opspilot.application.document_review import (
    _artifact_source_label,
    _build_document_artifact_locations,
    _build_document_artifact_preview,
    _build_document_artifact_remediation,
    _build_document_consumable_sections,
    _build_document_evidence_navigation,
    _build_document_navigation_unavailable,
    _load_company_document_upgrade_items,
    _load_document_artifact_payload,
)
from opspilot.application.industry_signals import (
    _build_company_signal_graph_context,
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
    _merge_streaming_anomalies_into_attention_matrix,
    _load_subindustry_signal_heatmap,
)
from opspilot.application.document_pipeline import (
    DocumentPipelineBlockedError,
    _run_document_pipeline_job,
    _settings_ocr_runtime,
    _utcnow_iso,
    _write_json,
)
from opspilot.application.runtime_manifests import (
    _append_industry_brain_snapshot,
    _build_alert_id,
    _build_graph_query_run_id,
    _build_task_id,
    _build_vision_run_id,
    _build_watchboard_run_id,
    _build_workspace_run_id,
    _document_pipeline_run_detail_path,
    _find_watchboard_record,
    _graph_query_run_detail_path,
    _load_alert_board_manifest,
    _load_document_pipeline_job_manifest,
    _load_document_pipeline_run_manifest,
    _load_industry_brain_manifest,
    _load_task_board_manifest,
    _load_vision_run_manifest,
    _load_watchboard_manifest,
    _load_watchboard_runs_manifest,
    _load_workspace_run_manifest,
    _vision_run_detail_path,
    _workspace_run_detail_path,
    _write_alert_board_manifest,
    _write_document_pipeline_job_manifest,
    _write_task_board_manifest,
    _write_vision_run_manifest,
    _write_watchboard_manifest,
    _write_watchboard_runs_manifest,
    _write_workspace_run_manifest,
    _write_graph_query_run_manifest,
    _load_graph_query_run_manifest,
)
from opspilot.application.runtime_views import (
    _build_brain_command_surface,
    _build_brain_signal_tape,
    _build_execution_bus_summary,
    _build_industry_brain_history_snapshot,
    _build_industry_brain_watchboard_snapshot,
    _build_runtime_capsule_module,
    _build_workspace_execution_bus_records,
    _filter_workspace_runs_for_company,
)
from opspilot.application.data_runtime import (
    _build_industry_live_chart,
    _build_innovation_radar,
    _build_official_data_status,
    _load_research_reports,
)
from opspilot.application.graph_runtime import (
    _build_graph_command_surface,
    _build_graph_query_evidence_navigation,
    _build_graph_query_inference_path,
    _build_graph_query_live_frames,
    _build_graph_query_phase_track,
    _build_graph_query_signal_stream,
    _build_graph_route_bands,
    _build_graph_signal_tape,
    _dedupe_graph_nodes,
    _graph_node_id,
    _retrieve_graph_paths,
)
from opspilot.application.workspace_service import ROLE_PROFILES, WorkspaceService
from opspilot.application.vision_runtime import (
    _build_vision_analysis_log,
    _build_vision_extraction_stream,
    _build_vision_phase_track,
    _build_vision_quality_summary,
    _vision_selected_item_priority,
)
from opspilot.application.verify_runtime import (
    _build_verify_command_surface,
    _build_verify_delta_tape,
)
from opspilot.application.stress_service import StressService


LABEL_METRIC_CODES = {
    "R1": ("C1", "G2"),
    "R2": ("C3",),
    "R3": ("P4",),
    "R4": ("S4", "S1"),
    "R5": ("I1",),
    "R6": ("I2",),
    "R7": ("I3",),
    "R8": ("I4",),
    "O1": ("P1",),
    "O2": ("C1",),
    "O3": ("P4",),
    "O4": ("S4",),
    "O5": ("G3",),
}
METRIC_ANCHOR_TERMS = {
    "C1": ("经营活动产生的现金流量净额", "净利润"),
    "C3": ("应收账款", "营业收入"),
    "G1": ("营业收入",),
    "G2": ("扣非净利润", "净利润"),
    "G3": ("研发费用",),
    "I1": ("政府补助",),
    "I2": ("审计", "未经审计", "无保留意见"),
    "I3": ("诉讼", "处罚"),
    "I4": ("减值", "关联交易"),
    "P1": ("毛利率", "营业成本"),
    "P4": ("存货",),
    "P5": ("应收账款",),
    "S1": ("流动资产合计", "流动负债合计"),
    "S3": ("利润总额", "利息费用"),
    "S4": ("货币资金", "短期借款"),
}

class OpsPilotService:
    def __init__(self, repository: Any, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self._industry_brain_cache: dict[str, Any] = {
            "generated_at": 0.0,
            "sequence": 0,
            "payload": None,
            "history": [],
        }
        # 域服务实例（Facade 委托）
        self._scoring = ScoringService(repository, settings)
        self._workspace = WorkspaceService(repository, settings)
        self._stress = StressService(repository, settings, facade=self)
        # TTL 内存缓存 — 避免每次切换页面都重算（TTL=5分钟）
        self._response_cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl: float = 300.0

    def _cache_get(self, key: str) -> Any | None:
        entry = self._response_cache.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.time() - ts < self._cache_ttl:
            return value
        del self._response_cache[key]
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        self._response_cache[key] = (value, time.time())

    def health(self) -> dict[str, Any]:
        preferred_period = self._preferred_period()
        return {
            "status": "ok",
            "app_name": self.settings.app_name,
            "env": self.settings.env,
            "default_period": self.settings.default_period,
            "preferred_period": preferred_period,
            "companies": len(self.repository.list_companies()),
            "preferred_period_companies": len(self.repository.list_companies(preferred_period)),
        }

    def official_data_status(self) -> dict[str, Any]:
        return _build_official_data_status(self.settings)

    def admin_overview(self) -> dict[str, Any]:
        health = self.health()
        data_status = self.official_data_status()
        streaming_runtime = _build_kafka_signal_runtime(self.settings)
        quality_overview = _build_admin_quality_overview(self.settings, health["preferred_period"])
        document_pipeline = _build_document_pipeline_overview(data_status, self.settings)
        delivery_readiness = _build_delivery_readiness(
            quality_overview=quality_overview,
            document_pipeline=document_pipeline,
            health=health,
        )
        runtime_readiness = _build_runtime_readiness(self.settings)
        acceptance_checklist = _build_acceptance_checklist(
            health=health,
            delivery_readiness=delivery_readiness,
            runtime_readiness=runtime_readiness,
            document_pipeline=document_pipeline,
        )
        innovation_radar = self.innovation_radar()
        workspace_runs = self.workspace_runs(limit=8)
        workspace_runtime_audit = self.workspace_runtime_audit()
        workspace_history = self.workspace_history(user_role="management", report_period=health["preferred_period"], limit=12)
        return {
            "health": health,
            "data_status": data_status,
            "streaming_runtime": streaming_runtime,
            "quality_overview": quality_overview,
            "document_pipeline": document_pipeline,
            "delivery_readiness": delivery_readiness,
            "runtime_readiness": runtime_readiness,
            "acceptance_checklist": acceptance_checklist,
            "document_pipeline_jobs": self.document_pipeline_jobs(),
            "innovation_radar": innovation_radar,
            "workspace_runs": workspace_runs,
            "workspace_runtime_audit": workspace_runtime_audit,
            "workspace_history": workspace_history,
            "job_catalog": _build_admin_job_catalog(),
            "capabilities": [
                "企业评分",
                "行业风险扫描",
                "研报观点核验",
                "研报横向对比",
                "机构观点轨迹",
                "证据查看",
            ],
        }

    def delivery_report(self) -> dict[str, Any]:
        overview = self.admin_overview()
        health = overview["health"]
        runtime_readiness = overview["runtime_readiness"]
        delivery_readiness = overview["delivery_readiness"]
        acceptance_checklist = overview["acceptance_checklist"]
        quality_overview = overview["quality_overview"]
        workspace_runtime_audit = overview["workspace_runtime_audit"]
        contract_audit = overview["document_pipeline"]["cell_trace"]["contract_audit"]
        runtime_blockers = [
            {
                "label": item["label"],
                "summary": item["summary"],
                "detail": item["detail"],
                "remediation": item.get("remediation"),
            }
            for item in runtime_readiness.get("checks", [])
            if item.get("status") == "blocked"
        ]
        acceptance_blockers = [
            {
                "label": item["label"],
                "detail": item["detail"],
            }
            for item in acceptance_checklist.get("items", [])
            if item.get("status") == "blocked"
        ]
        remediation_runs = [
            {
                "title": item["title"],
                "created_at": item["created_at"],
                "headline": item.get("meta", {}).get("headline"),
                "processed": item.get("meta", {}).get("processed"),
                "fixed_count": item.get("meta", {}).get("fixed_count"),
                "remaining_count": item.get("meta", {}).get("remaining_count"),
            }
            for item in overview.get("workspace_history", {}).get("records", [])
            if item.get("history_type") == "document_pipeline_run"
        ][:5]
        issue_buckets = [
            {
                "label": item.get("label"),
                "count": item.get("count", 0),
                "companies": item.get("companies", [])[:5],
            }
            for item in quality_overview.get("issue_buckets", [])[:5]
        ]
        executive_summary = [
            f"当前系统阶段为{_delivery_stage_label(delivery_readiness.get('stage'))}，主周期 {health.get('preferred_period') or '-'} 稳定可用 {delivery_readiness.get('ready_company_count', 0)} 家公司。",
            f"运行阻断 {runtime_readiness.get('blocked_count', 0)} 项，关键检查通过 {acceptance_checklist.get('passed', 0)}/{acceptance_checklist.get('total', 0)} 项。",
            f"近 {workspace_runtime_audit.get('window_size', 0)} 条智能体运行里，强支撑占比 {workspace_runtime_audit.get('summary_cards', {}).get('grounded_ratio', 0)}%，完整轨迹占比 {workspace_runtime_audit.get('summary_cards', {}).get('trace_ratio', 0)}%。",
            f"OCR Contract 当前达标 {contract_audit.get('ready', 0)}/{contract_audit.get('total', 0)}，缺失 {contract_audit.get('missing', 0)}，不合格 {contract_audit.get('invalid', 0)}。",
        ]
        return {
            "generated_at": _utcnow_iso(),
            "app_name": health.get("app_name", self.settings.app_name),
            "env": health.get("env", self.settings.env),
            "preferred_period": health.get("preferred_period"),
            "overall_status": "ready"
            if acceptance_checklist.get("status") == "ready" and runtime_readiness.get("status") == "ready"
            else "blocked",
            "overall_label": "稳定可用"
            if acceptance_checklist.get("status") == "ready" and runtime_readiness.get("status") == "ready"
            else "待治理",
            "executive_summary": executive_summary,
            "summary_cards": {
                "pool_companies": quality_overview.get("coverage", {}).get("pool_companies", 0),
                "ready_company_count": delivery_readiness.get("ready_company_count", 0),
                "blocked_company_count": delivery_readiness.get("blocked_company_count", 0),
                "runtime_blocked_count": runtime_readiness.get("blocked_count", 0),
                "acceptance_passed": acceptance_checklist.get("passed", 0),
                "acceptance_total": acceptance_checklist.get("total", 0),
            },
            "delivery_readiness": {
                "stage": delivery_readiness.get("stage"),
                "stage_label": _delivery_stage_label(delivery_readiness.get("stage")),
                "coverage_ratio": delivery_readiness.get("coverage_ratio", 0),
                "silver_ratio": delivery_readiness.get("silver_ratio", 0),
                "research_ratio": delivery_readiness.get("research_ratio", 0),
                "contract_ratio": delivery_readiness.get("contract_ratio", 0),
                "ready_company_count": delivery_readiness.get("ready_company_count", 0),
                "blocked_company_count": delivery_readiness.get("blocked_company_count", 0),
                "priority_actions": delivery_readiness.get("priority_actions", []),
            },
            "runtime_readiness": {
                "status": runtime_readiness.get("status"),
                "status_label": _status_label(runtime_readiness.get("status")),
                "blocked_count": runtime_readiness.get("blocked_count", 0),
                "blocked_checks": runtime_blockers,
            },
            "acceptance_checklist": {
                "status": acceptance_checklist.get("status"),
                "status_label": _status_label(acceptance_checklist.get("status")),
                "passed": acceptance_checklist.get("passed", 0),
                "total": acceptance_checklist.get("total", 0),
                "blocked_items": acceptance_blockers,
                "items": acceptance_checklist.get("items", []),
            },
            "workspace_runtime_audit": workspace_runtime_audit,
            "ocr_contract": {
                "status": contract_audit.get("status"),
                "status_label": _status_label(contract_audit.get("status")),
                "ready": contract_audit.get("ready", 0),
                "invalid": contract_audit.get("invalid", 0),
                "missing": contract_audit.get("missing", 0),
                "total": contract_audit.get("total", 0),
                "samples": contract_audit.get("samples", []),
            },
            "issue_buckets": issue_buckets,
            "recent_remediation_runs": remediation_runs,
        }

    def innovation_radar(self) -> dict[str, Any]:
        return _build_innovation_radar()

    def industry_brain(self) -> dict[str, Any]:
        return self._build_industry_brain_payload(force_refresh=True)

    def industry_brain_tick(self) -> dict[str, Any]:
        return self._build_industry_brain_payload(force_refresh=False)

    def industry_brain_history(self, limit: int = 24) -> dict[str, Any]:
        manifest = _load_industry_brain_manifest(self.settings)
        records = list(manifest["records"])
        records.sort(key=lambda item: item.get("refreshed_at") or "", reverse=True)
        return {
            "generated_at": manifest.get("generated_at"),
            "total": len(records),
            "records": records[:limit],
        }

    def _build_industry_brain_payload(self, *, force_refresh: bool) -> dict[str, Any]:
        now = time.monotonic()
        cache = self._industry_brain_cache
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

        preferred_period = self._preferred_period()
        health = self.health()
        alert_workflow = self.alert_workflow(report_period=preferred_period)
        task_board = self.task_board(user_role="management", report_period=preferred_period, limit=200)
        risk_payload = self.risk_scan(preferred_period)
        watchboard = _build_industry_brain_watchboard_snapshot(
            self.settings,
            report_period=preferred_period,
            user_role="management",
            alert_workflow=alert_workflow,
            task_board=task_board,
            risk_payload=risk_payload,
            limit=8,
        )
        innovation_radar = self.innovation_radar()
        data_status = self.official_data_status()
        workspace_history = _build_industry_brain_history_snapshot(
            self.settings,
            report_period=preferred_period,
            user_role="management",
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
            self.settings,
            focus_companies=top_risk_companies,
        )
        kafka_signal_runtime = _build_kafka_signal_runtime(self.settings)
        streaming_snapshot = _load_company_signal_snapshot(self.settings)
        streaming_timeline = _load_company_signal_timeline(self.settings)
        streaming_heatmap = _load_subindustry_signal_heatmap(self.settings)
        streaming_anomalies = _build_streaming_anomaly_board(
            preferred_period=preferred_period,
            top_risk_companies=top_risk_companies,
            signal_snapshot=streaming_snapshot,
            signal_timeline=streaming_timeline,
            signal_heatmap=streaming_heatmap,
            kafka_signal_runtime=kafka_signal_runtime,
        )

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
                        "query": {"company": item["company_name"], "period": preferred_period},
                    },
                }
            )
        signal_feed = external_signal_stream.get("signals") or live_events

        payload = {
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
                    "value": str(health["preferred_period_companies"]),
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
                        "query": {"company": item["company_name"], "period": preferred_period},
                    },
                }
                for item in top_risk_companies
            ],
        }
        _append_industry_brain_snapshot(self.settings, payload)
        cache["generated_at"] = now
        cache["payload"] = payload
        return payload

    def workspace_overview(self, user_role: str = "investor") -> dict[str, Any]:
        preferred_period = self._preferred_period()
        risk_payload = self.risk_scan(preferred_period)
        health = self.health()
        role_profile = ROLE_PROFILES.get(user_role, ROLE_PROFILES["investor"])
        task_board = self.task_board(user_role=user_role, report_period=preferred_period)
        alert_workflow = self.alert_workflow(report_period=preferred_period)
        watchboard = self.watchboard(user_role=user_role, report_period=preferred_period)
        history = self.workspace_history(
            user_role=user_role,
            report_period=preferred_period,
            limit=200,
        )
        document_results = self.document_pipeline_results(limit=300)
        execution_bus = _build_workspace_execution_bus_records(
            task_board=task_board,
            alert_workflow=alert_workflow,
            watchboard=watchboard,
            workspace_history=history,
            limit=20,
        )
        return {
            "preferred_period": preferred_period,
            "role_profile": role_profile,
            "companies": self.list_company_names(),
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
                report_period=preferred_period,
                user_role=user_role,
            ),
            "alert_summary": {
                "total_alerts": len(risk_payload["alert_board"]),
                "high_risk_companies": sum(
                    1 for item in risk_payload["risk_board"] if item["risk_count"] > 0
                ),
                "preferred_period": preferred_period,
            "active_companies": health["preferred_period_companies"],
            },
        }

    def workspace_execution_bus(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        history = self.workspace_history(user_role=user_role, report_period=period, limit=200)
        task_board = self.task_board(user_role=user_role, report_period=period, limit=200)
        alert_workflow = self.alert_workflow(report_period=period)
        watchboard = self.watchboard(user_role=user_role, report_period=period)
        return _build_workspace_execution_bus_records(
            task_board=task_board,
            alert_workflow=alert_workflow,
            watchboard=watchboard,
            workspace_history=history,
            limit=limit,
            user_role=user_role,
            report_period=period,
        )

    def watchboard(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        include_research: bool = True,
        item_limit: int | None = None,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        manifest = _load_watchboard_manifest(self.settings)
        alert_workflow = self.alert_workflow(report_period=period)
        task_board = self.task_board(user_role=user_role, report_period=period, limit=200)
        alert_items_by_company: dict[str, list[dict[str, Any]]] = {}
        for item in alert_workflow["alerts"]:
            alert_items_by_company.setdefault(item["company_name"], []).append(item)
        task_items_by_company: dict[str, list[dict[str, Any]]] = {}
        for item in task_board["tasks"]:
            task_items_by_company.setdefault(item["company_name"], []).append(item)
        document_items_by_company: dict[str, list[dict[str, Any]]] = {}
        for item in self.document_pipeline_results(limit=300)["results"]:
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
            score_payload = self.score_company(company_name, period)
            alert_items = alert_items_by_company.get(company_name, [])
            task_items = task_items_by_company.get(company_name, [])
            document_items = document_items_by_company.get(company_name, [])
            if include_research:
                try:
                    research_payload = self.verify_claim(company_name, period)
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

    def scan_watchboard(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        board = self.watchboard(user_role=user_role, report_period=report_period)
        run_id = _build_watchboard_run_id(user_role, board["report_period"])
        manifest = _load_watchboard_runs_manifest(self.settings)
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
        _write_watchboard_runs_manifest(self.settings, manifest)
        return {
            "run": record,
            "board": board,
        }

    def watchboard_runs(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        manifest = _load_watchboard_runs_manifest(self.settings)
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

    def watchboard_run_detail(self, run_id: str) -> dict[str, Any]:
        manifest = _load_watchboard_runs_manifest(self.settings)
        record = next((item for item in manifest["records"] if item.get("run_id") == run_id), None)
        if record is None:
            raise ValueError(f"未找到监测扫描记录：{run_id}")
        return record

    def dispatch_watchboard_alerts(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        board = self.watchboard(user_role=user_role, report_period=report_period)
        tracked_companies = {item["company_name"] for item in board["items"]}
        alert_workflow = self.alert_workflow(report_period=board["report_period"])
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
            result = self.dispatch_alert_to_task(
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
            "task_board": self.task_board(user_role=user_role, report_period=board["report_period"]),
            "alert_board": self.alert_workflow(report_period=board["report_period"]),
        }

    def add_watch_company(
        self,
        *,
        company_name: str,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        company = self._resolve_company(company_name, report_period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")
        period = report_period or company["report_period"]
        manifest = _load_watchboard_manifest(self.settings)
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
        _write_watchboard_manifest(self.settings, manifest)
        return self.watchboard(user_role=user_role, report_period=period)

    def remove_watch_company(
        self,
        *,
        company_name: str,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        manifest = _load_watchboard_manifest(self.settings)
        manifest["records"] = [
            item
            for item in manifest["records"]
            if not (
                item["company_name"] == company_name
                and item["user_role"] == user_role
                and item["report_period"] == period
            )
        ]
        _write_watchboard_manifest(self.settings, manifest)
        return self.watchboard(user_role=user_role, report_period=period)

    def alert_workflow(self, report_period: str | None = None) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        risk_payload = self.risk_scan(period)
        alert_manifest = _load_alert_board_manifest(self.settings)
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

    def update_alert_status(
        self,
        alert_id: str,
        status: str,
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.alert_workflow(report_period=report_period)
        alert = next((item for item in workflow["alerts"] if item["alert_id"] == alert_id), None)
        if alert is None:
            raise ValueError(f"未找到预警：{alert_id}")

        manifest = _load_alert_board_manifest(self.settings)
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
        _write_alert_board_manifest(self.settings, manifest)
        refreshed = self.alert_workflow(report_period=report_period or workflow["report_period"])
        refreshed_alert = next(item for item in refreshed["alerts"] if item["alert_id"] == alert_id)
        return {"alert": refreshed_alert, "summary": refreshed["summary"]}

    def dispatch_alert_to_task(
        self,
        alert_id: str,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.alert_workflow(report_period=report_period)
        alert = next((item for item in workflow["alerts"] if item["alert_id"] == alert_id), None)
        if alert is None:
            raise ValueError(f"未找到预警：{alert_id}")

        period = report_period or workflow["report_period"]
        task_board = self.task_board(user_role=user_role, report_period=period, limit=20)
        task = next(
            (item for item in task_board["tasks"] if item["company_name"] == alert["company_name"]),
            None,
        )
        if task is None:
            raise ValueError(f"未找到可派发任务：{alert['company_name']}")

        task_note = note or f"由预警 {alert_id} 派发"
        alert_note = note or f"已派发到任务 {task['task_id']}"
        task_payload = self.update_task_status(
            task_id=task["task_id"],
            status="in_progress",
            user_role=user_role,
            report_period=period,
            note=task_note,
        )
        alert_payload = self.update_alert_status(
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

    def list_company_names(self) -> list[str]:
        return self.repository.list_company_names()

    def score_company(self, company_name: str, report_period: str | None = None) -> dict[str, Any]:
        ck = f"score:{company_name}:{report_period or ''}"
        if cached := self._cache_get(ck):
            return cached
        result = self._scoring.score_company(company_name, report_period)
        self._cache_set(ck, result)
        return result

    def benchmark_company(self, company_name: str, report_period: str | None = None) -> dict[str, Any]:
        ck = f"benchmark:{company_name}:{report_period or ''}"
        if cached := self._cache_get(ck):
            return cached
        result = self._scoring.benchmark_company(company_name, report_period)
        self._cache_set(ck, result)
        return result

    def company_timeline(self, company_name: str) -> dict[str, Any]:
        ck = f"timeline:{company_name}"
        if cached := self._cache_get(ck):
            return cached
        result = self._scoring.company_timeline(company_name)
        self._cache_set(ck, result)
        return result

    def company_workspace(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        ck = f"workspace:full:{company_name}:{report_period or ''}:{user_role}"
        if cached := self._cache_get(ck):
            return cached
        result = self._company_workspace_compute(
            company_name,
            report_period,
            user_role=user_role,
            profile="full",
        )
        self._cache_set(ck, result)
        return result

    def _company_graph_workspace(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        ck = f"workspace:graph:{company_name}:{report_period or ''}:{user_role}"
        if cached := self._cache_get(ck):
            return cached
        result = self._company_workspace_compute(
            company_name,
            report_period,
            user_role=user_role,
            profile="graph",
        )
        self._cache_set(ck, result)
        return result

    def _company_workspace_compute(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
        profile: str = "full",
    ) -> dict[str, Any]:
        graph_profile = profile == "graph"
        score_payload = self.score_company(company_name, report_period)
        period = score_payload["report_period"]
        timeline_payload = self.company_timeline(company_name) if not graph_profile else None
        benchmark_payload = self.benchmark_company(company_name, period) if not graph_profile else None
        alert_workflow = self.alert_workflow(report_period=period)
        task_board = self.task_board(user_role=user_role, report_period=period, limit=20)
        document_upgrades = self.company_document_upgrades(
            company_name,
            period,
            limit=8 if graph_profile else 20,
            include_preview=not graph_profile,
        )
        runtime_capsule = (
            self.company_runtime_capsule(
                company_name,
                period,
                user_role=user_role,
            )
            if not graph_profile
            else None
        )

        alert_items = [
            item for item in alert_workflow["alerts"] if item["company_name"] == company_name
        ]
        task_items = [item for item in task_board["tasks"] if item["company_name"] == company_name]
        watch_item = _find_watchboard_record(
            self.settings,
            company_name=company_name,
            user_role=user_role,
            report_period=period,
        )
        research_status: dict[str, Any]
        try:
            research_payload = self.verify_claim(company_name, period)
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
            "execution_stream": self.company_execution_stream(
                company_name,
                period,
                user_role=user_role,
                limit=12 if graph_profile else 30,
            ),
            "recent_runs": _filter_workspace_runs_for_company(
                self.workspace_runs(limit=12 if graph_profile else 50)["runs"],
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
                    "intelligence_runtime": self.company_intelligence_runtime(
                        company_name,
                        period,
                        user_role=user_role,
                    ),
                    "runtime_capsule": runtime_capsule,
                }
            )
        return payload

    def company_runtime_capsule(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        latest_graph = self.graph_query_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_stress = self.stress_test_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_vision = self.vision_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_analysis = _filter_workspace_runs_for_company(
            self.workspace_runs(limit=200)["runs"],
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

    def company_intelligence_runtime(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        capsule = self.company_runtime_capsule(
            company_name,
            period,
            user_role=user_role,
        )
        latest_graph_runs = self.graph_query_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_stress_runs = self.stress_test_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_vision_runs = self.vision_runs(
            company_name=company_name,
            report_period=period,
            user_role=user_role,
            limit=1,
        )["runs"]
        latest_analysis = _filter_workspace_runs_for_company(
            self.workspace_runs(limit=200)["runs"],
            company_name,
            period,
            limit=1,
        )["items"]
        vision_runtime = self.company_vision_runtime(
            company_name,
            period,
            user_role=user_role,
        )

        graph_detail = (
            self.graph_query_run_detail(latest_graph_runs[0]["run_id"])
            if latest_graph_runs
            else None
        )
        stress_detail = (
            self.stress_test_run_detail(latest_stress_runs[0]["run_id"])
            if latest_stress_runs
            else None
        )

        runs = [item for item in (latest_analysis[0] if latest_analysis else None, latest_graph_runs[0] if latest_graph_runs else None, latest_stress_runs[0] if latest_stress_runs else None, latest_vision_runs[0] if latest_vision_runs else None) if item]
        runs.sort(key=lambda item: item.get("created_at") or "", reverse=True)

        module_pulses = [
            {
                "module_key": "analysis",
                "label": "协同分析",
                "status": "ready" if latest_analysis else "idle",
                "headline": (latest_analysis[0].get("query") if latest_analysis else "等待分析任务"),
                "signal": (latest_analysis[0].get("query_type") if latest_analysis else "pending"),
                "intensity": 72 if latest_analysis else 0,
                "route": {
                    "path": "/workspace",
                    "query": {"company": company_name, "period": period},
                },
            },
            {
                "module_key": "graph",
                "label": "图谱检索",
                "status": "ready" if latest_graph_runs else "idle",
                "headline": (
                    latest_graph_runs[0].get("intent")
                    if latest_graph_runs
                    else "等待图谱检索"
                ),
                "signal": (
                    f"{len(graph_detail.get('graph_live_frames', []))} 帧"
                    if graph_detail
                    else "pending"
                ),
                "intensity": (
                    max(
                        (frame.get("intensity", 0) for frame in graph_detail.get("graph_live_frames", [])),
                        default=0,
                    )
                    if graph_detail
                    else 0
                ),
                "route": {
                    "path": "/graph",
                    "query": {"company": company_name, "period": period},
                },
            },
            {
                "module_key": "stress",
                "label": "压力测试",
                "status": "ready" if latest_stress_runs else "idle",
                "headline": (
                    latest_stress_runs[0].get("scenario")
                    if latest_stress_runs
                    else "等待冲击推演"
                ),
                "signal": (
                    stress_detail.get("severity", {}).get("level")
                    if stress_detail
                    else "pending"
                ),
                "intensity": (
                    max(
                        (frame.get("impact_score", 0) for frame in stress_detail.get("stress_wavefront", [])),
                        default=0,
                    )
                    if stress_detail
                    else 0
                ),
                "route": {
                    "path": "/stress",
                    "query": {"company": company_name, "period": period},
                },
            },
            {
                "module_key": "vision",
                "label": "多模态解析",
                "status": (
                    "ready"
                    if any(item["status"] == "completed" for item in vision_runtime["stages"])
                    else "idle"
                ),
                "headline": vision_runtime["vision"].get("headline") or "等待解析结果",
                "signal": f"{len(vision_runtime['stages'])} 阶段",
                "intensity": min(
                    100,
                    28
                    + 24
                    * sum(1 for item in vision_runtime["stages"] if item["status"] == "completed"),
                ),
                "route": {
                    "path": "/vision",
                    "query": {"company": company_name, "period": period},
                },
            },
        ]
        runtime_bus = [
            {
                "module_key": "analysis",
                "label": "协同分析",
                "status": "ready" if latest_analysis else "idle",
                "headline": (latest_analysis[0].get("query") if latest_analysis else "等待分析任务"),
                "signal": (latest_analysis[0].get("query_type") if latest_analysis else "pending"),
                "intensity": 72 if latest_analysis else 0,
                "route": {
                    "path": "/workspace",
                    "query": {"company": company_name, "period": period},
                },
                "meta": {
                    "created_at": latest_analysis[0].get("created_at") if latest_analysis else None,
                    "run_id": latest_analysis[0].get("run_id") if latest_analysis else None,
                },
            },
            {
                "module_key": "graph",
                "label": "图谱检索",
                "status": "ready" if latest_graph_runs else "idle",
                "headline": (
                    latest_graph_runs[0].get("intent")
                    if latest_graph_runs
                    else "等待图谱检索"
                ),
                "signal": (
                    f"{len(graph_detail.get('graph_live_frames', []))} 帧"
                    if graph_detail
                    else "pending"
                ),
                "intensity": (
                    max(
                        (frame.get("intensity", 0) for frame in graph_detail.get("graph_live_frames", [])),
                        default=0,
                    )
                    if graph_detail
                    else 0
                ),
                "route": {
                    "path": "/graph",
                    "query": {"company": company_name, "period": period},
                },
                "meta": {
                    "created_at": latest_graph_runs[0].get("created_at") if latest_graph_runs else None,
                    "run_id": latest_graph_runs[0].get("run_id") if latest_graph_runs else None,
                },
            },
            {
                "module_key": "stress",
                "label": "压力测试",
                "status": "ready" if latest_stress_runs else "idle",
                "headline": (
                    latest_stress_runs[0].get("scenario")
                    if latest_stress_runs
                    else "等待冲击推演"
                ),
                "signal": (
                    stress_detail.get("severity", {}).get("level")
                    if stress_detail
                    else "pending"
                ),
                "intensity": (
                    max(
                        (frame.get("impact_score", 0) for frame in stress_detail.get("stress_wavefront", [])),
                        default=0,
                    )
                    if stress_detail
                    else 0
                ),
                "route": {
                    "path": "/stress",
                    "query": {"company": company_name, "period": period},
                },
                "meta": {
                    "created_at": latest_stress_runs[0].get("created_at") if latest_stress_runs else None,
                    "run_id": latest_stress_runs[0].get("run_id") if latest_stress_runs else None,
                },
            },
            {
                "module_key": "vision",
                "label": "多模态解析",
                "status": (
                    "ready"
                    if any(item["status"] == "completed" for item in vision_runtime["stages"])
                    else "idle"
                ),
                "headline": vision_runtime["vision"].get("headline") or "等待解析结果",
                "signal": f"{len(vision_runtime['stages'])} 阶段",
                "intensity": min(
                    100,
                    28
                    + 24
                    * sum(1 for item in vision_runtime["stages"] if item["status"] == "completed"),
                ),
                "route": {
                    "path": "/vision",
                    "query": {"company": company_name, "period": period},
                },
                "meta": {
                    "created_at": latest_vision_runs[0].get("created_at") if latest_vision_runs else None,
                    "run_id": latest_vision_runs[0].get("run_id") if latest_vision_runs else None,
                },
            },
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

    def company_execution_stream(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
        limit: int = 30,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
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
                    "route": {
                        "path": "/risk",
                        "query": {"company": company_name},
                    },
                },
            }
            for item in self.alert_workflow(report_period=period)["alerts"]
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
                    "route": {
                        "path": "/workspace",
                        "query": {"company": company_name},
                    },
                },
            }
            for item in self.task_board(user_role=user_role, report_period=period, limit=200)["tasks"]
            if item["company_name"] == company_name
        ]
        watch_item = _find_watchboard_record(
            self.settings,
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
                        "route": {
                            "path": "/workspace",
                            "query": {"company": company_name},
                        },
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
            for item in self.company_document_upgrades(
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
                    "route": {
                        "path": f"/api/v1/stress-test/runs/{item['run_id']}",
                    },
                },
            }
            for item in self.stress_test_runs(
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
                    "route": {
                        "path": f"/api/v1/graph-query/runs/{item['run_id']}",
                    },
                },
            }
            for item in self.graph_query_runs(
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
                    "route": {
                        "path": f"/api/v1/vision-analyze/runs/{item['run_id']}",
                    },
                },
            }
            for item in self.vision_runs(
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
                    "route": {
                        "path": f"/api/v1/workspace/runs/{item['run_id']}",
                    },
                },
            }
            for item in self.workspace_runs(limit=200)["runs"]
            if item.get("company_name") == company_name
            and item.get("report_period") == period
            and item.get("user_role") == user_role
        ]
        records = alert_items + task_items + watch_records + document_items + stress_items + graph_items + vision_items + analysis_runs
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
                "graph_queries": len(graph_items),
                "vision_runs": len(vision_items),
                "analysis_runs": len(analysis_runs),
            },
            "records": records[:limit],
        }

    def company_document_upgrades(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        limit: int = 20,
        include_preview: bool = True,
        include_evidence_navigation: bool = True,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        upgrade_items = _load_company_document_upgrade_items(self.settings, company_name, period)
        enriched_items: list[dict[str, Any]] = []
        stage_summary: dict[str, int] = {}
        for item in upgrade_items[:limit]:
            stage = item["stage"]
            stage_summary[stage] = stage_summary.get(stage, 0) + 1
            artifact_preview = None
            artifact_summary = item.get("artifact_summary")
            artifact_source = item.get("artifact_source")
            artifact_payload = None
            if item.get("status") == "completed":
                artifact_payload = _load_document_artifact_payload(item)
                if artifact_payload is not None:
                    if include_preview:
                        artifact_preview = _build_document_artifact_preview(artifact_payload)
                    artifact_summary = artifact_summary or artifact_payload.get("summary")
                    artifact_source = artifact_source or artifact_payload.get("source")
                if include_evidence_navigation and artifact_payload is not None:
                    evidence_navigation = _build_document_evidence_navigation(
                        repository=self.repository,
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
                        "query": {
                            "stage": stage,
                            "report_id": item["report_id"],
                        },
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

    def company_graph(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
        workspace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace_payload = workspace or self.company_workspace(
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
        nodes.append(
            {
                "id": period_node,
                "type": "report_period",
                "label": workspace_payload["report_period"],
                "meta": {},
            }
        )
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
                    "meta": {
                        "priority": task["priority"],
                        "status": task["status"],
                    },
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

        signal_context_cache_key = (
            "graph-signal-context:"
            f"{company_name}:{workspace_payload['score_summary'].get('subindustry') or ''}"
        )
        signal_context = self._cache_get(signal_context_cache_key)
        if signal_context is None:
            signal_context = _build_company_signal_graph_context(
                self.settings,
                company_name=company_name,
                subindustry=workspace_payload["score_summary"].get("subindustry"),
            )
            self._cache_set(signal_context_cache_key, signal_context)

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
                edges.append(
                    {
                        "source": signal_event_node,
                        "target": signal_timeline_node,
                        "label": "时序沉淀",
                    }
                )

        if signal_context.get("subindustry_available"):
            subindustry_signal_node = _graph_node_id(
                "subindustry-signal",
                str(signal_context.get("subindustry") or company_name),
            )
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
                edges.append(
                    {
                        "source": subindustry_signal_node,
                        "target": signal_timeline_node,
                        "label": "热度传导",
                    }
                )

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

    def company_graph_query(
        self,
        company_name: str,
        intent: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        workspace = self._company_graph_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
        graph = self.company_graph(
            company_name,
            workspace["report_period"],
            user_role=user_role,
            workspace=workspace,
        )
        retrieval = _retrieve_graph_paths(
            graph=graph,
            company_name=company_name,
            report_period=workspace["report_period"],
            intent=intent,
        )
        ranked_nodes = retrieval["ranked_nodes"]
        focal_nodes = retrieval["focal_nodes"]
        inference_path = _build_graph_query_inference_path(
            company_name=company_name,
            report_period=workspace["report_period"],
            intent=intent,
            focal_nodes=focal_nodes,
            retrieved_paths=retrieval["paths"],
            retrieval_summary=retrieval["summary"],
            workspace=workspace,
        )
        phase_track = _build_graph_query_phase_track(
            company_name=company_name,
            intent=intent,
            workspace=workspace,
            inference_path=inference_path,
            retrieval_summary=retrieval["summary"],
        )
        signal_stream = _build_graph_query_signal_stream(
            focal_nodes=focal_nodes,
            retrieved_paths=retrieval["paths"],
            workspace=workspace,
            graph_node_count=len(graph["nodes"]),
            retrieval_summary=retrieval["summary"],
        )
        evidence_navigation = _build_graph_query_evidence_navigation(workspace)
        payload = {
            "company_name": company_name,
            "report_period": workspace["report_period"],
            "user_role": user_role,
            "intent": intent,
            "summary": {
                "score": workspace["score_summary"]["total_score"],
                "grade": workspace["score_summary"]["grade"],
                "risk_count": workspace["score_summary"]["risk_count"],
                "execution_records": len(workspace["execution_stream"]["records"]),
            },
            "graph_retrieval": retrieval["summary"],
            "focal_nodes": focal_nodes,
            "inference_path": inference_path,
            "phase_track": phase_track,
            "signal_stream": signal_stream,
            "graph_command_surface": _build_graph_command_surface(
                company_name=company_name,
                intent=intent,
                focal_nodes=focal_nodes,
                inference_path=inference_path,
                phase_track=phase_track,
                signal_stream=signal_stream,
                retrieval_summary=retrieval["summary"],
                workspace=workspace,
            ),
            "graph_live_frames": _build_graph_query_live_frames(
                focal_nodes=focal_nodes,
                inference_path=inference_path,
                phase_track=phase_track,
                signal_stream=signal_stream,
            ),
            "graph_signal_tape": _build_graph_signal_tape(
                inference_path=inference_path,
                signal_stream=signal_stream,
            ),
            "graph_route_bands": _build_graph_route_bands(
                inference_path=inference_path,
                signal_stream=signal_stream,
            ),
            "execution_stream": workspace["execution_stream"]["records"][:6],
            "related_routes": [
                {
                    "label": "查看企业体检",
                    "path": "/score",
                    "query": {"company": company_name, "period": workspace["report_period"]},
                },
                {
                    "label": "查看协同分析",
                    "path": "/workspace",
                    "query": {"company": company_name},
                },
                {
                    "label": "执行压力测试",
                    "path": "/stress",
                    "query": {"company": company_name, "period": workspace["report_period"]},
                },
            ],
            "evidence_navigation": evidence_navigation,
            "graph": {
                "summary": graph["summary"],
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "retrieved_path_count": retrieval["summary"]["path_count"],
                "nodes": graph["nodes"],
                "edges": graph["edges"],
            },
        }
        run_id = _build_graph_query_run_id(company_name)
        detail_path = _graph_query_run_detail_path(self.settings, run_id)
        _write_json(detail_path, payload)
        manifest = _load_graph_query_run_manifest(self.settings)
        records = [item for item in manifest["records"] if item.get("run_id") != run_id]
        records.insert(
            0,
            {
                "run_id": run_id,
                "company_name": company_name,
                "report_period": workspace["report_period"],
                "user_role": user_role,
                "intent": intent,
                "created_at": _utcnow_iso(),
                "detail_path": str(detail_path),
            },
        )
        manifest["records"] = records[:200]
        _write_graph_query_run_manifest(self.settings, manifest)
        payload["run_id"] = run_id
        return payload

    def graph_query_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        records = [
            item
            for item in _load_graph_query_run_manifest(self.settings)["records"]
            if item.get("user_role") == user_role
            and (report_period is None or item.get("report_period") == report_period)
            and (company_name is None or item.get("company_name") == company_name)
        ]
        return {
            "company_name": company_name,
            "report_period": report_period,
            "user_role": user_role,
            "total": len(records),
            "runs": records[:limit],
        }

    def graph_query_run_detail(self, run_id: str) -> dict[str, Any]:
        record = next(
            (
                item
                for item in _load_graph_query_run_manifest(self.settings)["records"]
                if item.get("run_id") == run_id
            ),
            None,
        )
        if record is None:
            raise ValueError(f"未找到图谱查询运行：{run_id}")
        detail_path = Path(record["detail_path"])
        if not detail_path.exists():
            raise ValueError(f"未找到图谱查询详情：{run_id}")
        try:
            with detail_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"图谱查询记录损坏：{run_id}") from exc
        payload["run_meta"] = {
            "run_id": run_id,
            "created_at": record.get("created_at"),
            "company_name": record.get("company_name"),
            "report_period": record.get("report_period"),
            "user_role": record.get("user_role"),
            "intent": record.get("intent"),
        }
        return payload

    def company_vision_analyze(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        ocr_runtime = _settings_ocr_runtime(self.settings)
        upgrade_items = _load_company_document_upgrade_items(self.settings, company_name, period)
        selected_item = max(
            upgrade_items,
            key=_vision_selected_item_priority,
            default=None,
        )
        if selected_item is None:
            return {
                "company_name": company_name,
                "report_period": period,
                "user_role": user_role,
                "result": {
                    "company_name": company_name,
                    "headline": "暂无可用解析结果",
                    "status_label": "等待解析",
                    "quality_summary": _build_vision_quality_summary(
                        detail=None,
                        selected_item={},
                        ocr_runtime=ocr_runtime,
                    ),
                    "items": [],
                    "sections": [],
                    "evidence_navigation": {"links": []},
                },
            }

        detail = None
        selected_artifact = _load_document_artifact_payload(selected_item)
        if selected_artifact is not None:
            selected_item = {
                **selected_item,
                "artifact_summary": selected_item.get("artifact_summary")
                or selected_artifact.get("summary"),
                "artifact_source": selected_item.get("artifact_source")
                or selected_artifact.get("source"),
                "artifact_preview": _build_document_artifact_preview(selected_artifact),
            }
        try:
            detail = self.document_pipeline_result_detail(
                selected_item["stage"],
                selected_item["report_id"],
            )
        except ValueError:
            detail = None

        section_items = []
        if detail is not None:
            for section in detail.get("consumable_sections", []):
                section_items.append(
                    {
                        "section_type": section.get("section_type"),
                        "title": section.get("title"),
                        "count": section.get("count", 0),
                        "items": section.get("items", [])[:6],
                    }
                )

        result_items = [
            {
                "kind": item["stage"],
                "stage_label": _document_stage_label(item["stage"]),
                "title": item.get("artifact_summary") or _document_stage_label(item["stage"]),
                "summary": f"{item.get('report_period') or period} · {_status_label(item.get('status'))}",
            }
            for item in upgrade_items[:8]
        ]
        phase_track = _build_vision_phase_track(
            company_name=company_name,
            report_period=period,
            selected_item=selected_item,
            detail=detail,
        )
        extraction_stream = _build_vision_extraction_stream(
            detail=detail,
            selected_item=selected_item,
        )
        analysis_log = _build_vision_analysis_log(
            company_name=company_name,
            report_period=period,
            selected_item=selected_item,
            detail=detail,
        )
        quality_summary = _build_vision_quality_summary(
            detail=detail,
            selected_item=selected_item,
            ocr_runtime=ocr_runtime,
        )
        return {
            "company_name": company_name,
            "report_period": period,
            "user_role": user_role,
            "result": {
                "company_name": company_name,
                "headline": selected_item.get("artifact_summary")
                or selected_item.get("report_id")
                or "解析结果",
                "status_label": "已生成"
                if detail is not None
                or selected_item.get("artifact_summary")
                or selected_item.get("artifact_preview")
                else "处理中",
                "phase_track": phase_track,
                "quality_summary": quality_summary,
                "extraction_stream": extraction_stream,
                "analysis_log": analysis_log,
                "source_preview": selected_item.get("artifact_preview"),
                "items": result_items,
                "sections": section_items,
                "evidence_navigation": (
                    detail.get("evidence_navigation")
                    if detail is not None
                    else selected_item.get("evidence_navigation") or {"links": []}
                ),
            },
        }

    def company_vision_runtime(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        upgrade_items = _load_company_document_upgrade_items(self.settings, company_name, period)
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        ocr_runtime = _settings_ocr_runtime(self.settings)
        stages: list[dict[str, Any]] = []
        latest_jobs: list[dict[str, Any]] = []
        for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
            stage_jobs = [
                item
                for item in jobs_manifest["records"]
                if item.get("stage") == stage
                and item.get("company_name") == company_name
                and item.get("report_period") == period
            ]
            stage_jobs.sort(
                key=lambda item: item.get("completed_at") or item.get("created_at") or "",
                reverse=True,
            )
            job = stage_jobs[0] if stage_jobs else None
            if job and job.get("status") == "completed":
                artifact_payload = _load_document_artifact_payload(job)
                if artifact_payload is not None:
                    job = {
                        **job,
                        "artifact_summary": job.get("artifact_summary") or artifact_payload.get("summary"),
                        "artifact_source": job.get("artifact_source") or artifact_payload.get("source"),
                    }
            if job:
                latest_jobs.append(job)
            status = job.get("status", "missing") if job else "missing"
            contract_status = (
                _resolve_document_contract_status(self.settings, job)
                if job
                else None
            )
            stages.append(
                {
                    "stage": stage,
                    "label": _document_stage_label(stage),
                    "status": status,
                    "status_label": _status_label(status),
                    "artifact_source": job.get("artifact_source") if job else None,
                    "artifact_source_label": _artifact_source_label(
                        job.get("artifact_source") if job else None
                    ),
                    "contract_status": contract_status,
                    "summary": (
                        job.get("artifact_summary")
                        or job.get("completed_at")
                        or "等待运行"
                    )
                    if job
                    else "等待运行",
                    "report_id": job.get("report_id") if job else None,
                }
            )

        latest_jobs.sort(
            key=lambda item: item.get("completed_at") or item.get("created_at") or "",
            reverse=True,
        )
        vision = self.company_vision_analyze(
            company_name,
            period,
            user_role=user_role,
        )
        stage_status_counts: dict[str, int] = {}
        for item in stages:
            stage_status_counts[item["status"]] = stage_status_counts.get(item["status"], 0) + 1
        cell_trace_stage = next((item for item in stages if item["stage"] == "cell_trace"), None)
        if (
            cell_trace_stage
            and cell_trace_stage.get("status") == "completed"
            and cell_trace_stage.get("contract_status") in {"missing", "invalid"}
        ):
            next_action = "补齐标准 OCR 结构契约后重新运行单元格溯源"
        elif ocr_runtime["runtime_enabled"] and ocr_runtime["mode"] == "service" and not ocr_runtime["service_url"]:
            next_action = "配置 PaddleOCR-VL 服务地址后再运行财报扫描"
        elif not ocr_runtime["runtime_enabled"]:
            next_action = "接通正式 OCR 运行时后再执行财报扫描"
        elif stage_status_counts.get("pending"):
            next_action = "继续运行文档升级作业"
        elif stage_status_counts.get("completed"):
            next_action = "进入结果核验与证据回放"
        else:
            next_action = "初始化解析链路"
        return {
            "company_name": company_name,
            "report_period": period,
            "user_role": user_role,
            "runtime": {
                "provider": ocr_runtime["provider"],
                "model": ocr_runtime["model"],
                "mode": ocr_runtime["mode"],
                "service_url": ocr_runtime["service_url"],
                "runtime_enabled": ocr_runtime["runtime_enabled"],
                "layout_engine": ocr_runtime["layout_engine"],
                "next_action": next_action,
            },
            "stages": stages,
            "document_upgrades": {
                "count": len(upgrade_items),
                "stage_summary": dict(Counter(item["stage"] for item in upgrade_items)),
            },
            "latest_jobs": latest_jobs[:3],
            "vision": vision["result"],
        }

    def run_company_vision_pipeline(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        requested_stages = ["cross_page_merge", "title_hierarchy", "cell_trace"]
        executed: list[dict[str, Any]] = []
        for stage in requested_stages:
            pending_jobs = [
                item
                for item in jobs_manifest["records"]
                if item.get("stage") == stage
                and item.get("company_name") == company_name
                and item.get("report_period") == period
                and item.get("status") == "pending"
            ]
            if not pending_jobs:
                continue
            for job in pending_jobs[:1]:
                try:
                    artifact_payload, artifact_path = _run_document_pipeline_job(stage, job, self.settings)
                except DocumentPipelineBlockedError as exc:
                    job["status"] = "blocked"
                    job["artifact_path"] = ""
                    job["completed_at"] = _utcnow_iso()
                    job["artifact_summary"] = str(exc)
                    job["artifact_source"] = None
                    executed.append(
                        {
                            "stage": stage,
                            "report_id": job.get("report_id"),
                            "summary": str(exc),
                            "artifact_path": "",
                            "status": "blocked",
                            "source": None,
                        }
                    )
                    continue
                job["status"] = "completed"
                job["artifact_path"] = str(artifact_path)
                job["completed_at"] = _utcnow_iso()
                job["artifact_summary"] = artifact_payload.get("summary")
                job["artifact_source"] = artifact_payload.get("source")
                executed.append(
                    {
                        "stage": stage,
                        "report_id": job.get("report_id"),
                        "summary": artifact_payload.get("summary"),
                        "artifact_path": str(artifact_path),
                        "status": "completed",
                        "source": artifact_payload.get("source"),
                    }
                )
        if executed:
            _write_document_pipeline_job_manifest(self.settings, jobs_manifest)
        vision_payload = self.run_company_vision_analyze(
            company_name,
            period,
            user_role=user_role,
        )
        runtime_payload = self.company_vision_runtime(
            company_name,
            period,
            user_role=user_role,
        )
        return {
            "company_name": company_name,
            "report_period": period,
            "user_role": user_role,
            "executed": executed,
            "vision_run_id": vision_payload.get("run_id"),
            "runtime": runtime_payload,
        }

    def run_company_vision_analyze(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        payload = self.company_vision_analyze(
            company_name,
            report_period,
            user_role=user_role,
        )
        run_id = _build_vision_run_id(company_name)
        detail_path = _vision_run_detail_path(self.settings, run_id)
        _write_json(detail_path, payload)
        manifest = _load_vision_run_manifest(self.settings)
        records = [item for item in manifest["records"] if item.get("run_id") != run_id]
        records.insert(
            0,
            {
                "run_id": run_id,
                "company_name": company_name,
                "report_period": payload.get("report_period"),
                "user_role": user_role,
                "headline": payload.get("result", {}).get("headline"),
                "status_label": payload.get("result", {}).get("status_label"),
                "created_at": _utcnow_iso(),
                "detail_path": str(detail_path),
            },
        )
        manifest["records"] = records[:200]
        _write_vision_run_manifest(self.settings, manifest)
        payload["run_id"] = run_id
        return payload

    def vision_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        records = [
            item
            for item in _load_vision_run_manifest(self.settings)["records"]
            if item.get("user_role") == user_role
            and (report_period is None or item.get("report_period") == report_period)
            and (company_name is None or item.get("company_name") == company_name)
        ]
        return {
            "company_name": company_name,
            "report_period": report_period,
            "user_role": user_role,
            "total": len(records),
            "runs": records[:limit],
        }

    def vision_run_detail(self, run_id: str) -> dict[str, Any]:
        record = next(
            (
                item
                for item in _load_vision_run_manifest(self.settings)["records"]
                if item.get("run_id") == run_id
            ),
            None,
        )
        if record is None:
            raise ValueError(f"未找到多模态运行：{run_id}")
        detail_path = Path(record["detail_path"])
        if not detail_path.exists():
            raise ValueError(f"未找到多模态详情：{run_id}")
        try:
            with detail_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"多模态运行记录损坏：{run_id}") from exc
        payload["run_meta"] = {
            "run_id": run_id,
            "created_at": record.get("created_at"),
            "company_name": record.get("company_name"),
            "report_period": record.get("report_period"),
            "user_role": record.get("user_role"),
            "headline": record.get("headline"),
            "status_label": record.get("status_label"),
        }
        return payload

    async def company_stress_test(
        self,
        company_name: str,
        scenario: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return await self._stress.company_stress_test(
            company_name, scenario, report_period, user_role=user_role
        )

    def stress_test_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._stress.stress_test_runs(
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            limit=limit,
        )

    def stress_test_run_detail(self, run_id: str) -> dict[str, Any]:
        return self._stress.stress_test_run_detail(run_id)

    def task_board(
        self, user_role: str = "management", report_period: str | None = None, limit: int = 12
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        task_manifest = _load_task_board_manifest(self.settings)
        tasks = self.task_queue(user_role=user_role, report_period=period, limit=limit)
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

    def update_task_status(
        self,
        task_id: str,
        status: str,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        task_board = self.task_board(user_role=user_role, report_period=report_period, limit=20)
        task = next((item for item in task_board["tasks"] if item["task_id"] == task_id), None)
        if task is None:
            raise ValueError(f"未找到任务：{task_id}")

        task_manifest = _load_task_board_manifest(self.settings)
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
        _write_task_board_manifest(self.settings, task_manifest)
        refreshed = self.task_board(
            user_role=user_role,
            report_period=report_period or task_board["report_period"],
            limit=20,
        )
        refreshed_task = next(item for item in refreshed["tasks"] if item["task_id"] == task_id)
        return {"task": refreshed_task, "summary": refreshed["summary"]}

    def task_queue(
        self, user_role: str = "management", report_period: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        period = report_period or self._preferred_period()
        alerts = self.risk_scan(period)["alert_board"]
        tasks: list[dict[str, Any]] = []
        for alert in alerts[:limit]:
            company_name = alert["company_name"]
            score_payload = self.score_company(company_name, period)
            action_cards = score_payload["action_cards"]
            if not action_cards:
                continue
            primary_action = action_cards[0]
            route = {"path": "/score", "query": {"company": company_name, "period": period}}
            if user_role == "investor":
                route = {"path": "/verify", "query": {"company": company_name}}
            elif user_role == "regulator":
                route = {"path": "/risk", "query": {"company": company_name}}
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
                    "route": route,
                }
            )
        return tasks

    def document_pipeline_jobs(self) -> dict[str, Any]:
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        records = jobs_manifest["records"]
        stage_summary = []
        for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
            stage_records = [item for item in records if item["stage"] == stage]
            stage_summary.append(
                {
                    "stage": stage,
                    "total": len(stage_records),
                    "completed": sum(1 for item in stage_records if item["status"] == "completed"),
                    "pending": sum(1 for item in stage_records if item["status"] == "pending"),
                    "blocked": sum(1 for item in stage_records if item["status"] == "blocked"),
                }
            )
        return {
            "generated_at": jobs_manifest["generated_at"],
            "stage_summary": stage_summary,
            "jobs": records[:30],
        }

    def document_pipeline_runs(self, limit: int = 30) -> dict[str, Any]:
        manifest = _load_document_pipeline_run_manifest(self.settings)
        records = list(manifest["records"])
        records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {
            "generated_at": manifest["generated_at"],
            "total": len(records),
            "runs": records[:limit],
        }

    def document_pipeline_run_detail(self, run_id: str) -> dict[str, Any]:
        manifest = _load_document_pipeline_run_manifest(self.settings)
        record = next((item for item in manifest["records"] if item.get("run_id") == run_id), None)
        if record is None:
            raise ValueError(f"未找到文档升级运行：{run_id}")
        detail_path = _document_pipeline_run_detail_path(self.settings, run_id)
        if not detail_path.exists():
            raise ValueError(f"未找到文档升级运行详情：{run_id}")
        try:
            with detail_path.open("r", encoding="utf-8") as file:
                detail = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"文档升级运行记录损坏：{run_id}") from exc
        return detail

    def document_pipeline_results(
        self,
        stage: str | None = None,
        *,
        status: str | None = None,
        artifact_source: str | None = None,
        contract_status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        records = jobs_manifest["records"]
        filtered = []
        for item in records:
            if stage and item["stage"] != stage:
                continue
            if status and item["status"] != status:
                continue
            item_contract_status = _resolve_document_contract_status(self.settings, item)
            item_artifact_source = item.get("artifact_source")
            if artifact_source and item_artifact_source != artifact_source:
                continue
            if contract_status and item_contract_status != contract_status:
                continue
            filtered.append(
                {
                    "stage": item["stage"],
                    "report_id": item["report_id"],
                    "company_name": item["company_name"],
                    "security_code": item["security_code"],
                    "report_period": item.get("report_period"),
                    "status": item["status"],
                    "artifact_path": item.get("artifact_path"),
                    "artifact_summary": item.get("artifact_summary"),
                    "artifact_source": item_artifact_source,
                    "contract_status": item_contract_status,
                    "completed_at": item.get("completed_at"),
                    "detail_route": {
                        "path": f"/api/v1/admin/document-pipeline/results/{item['stage']}/{item['report_id']}",
                    },
                }
            )
        filtered.sort(
            key=lambda item: (
                item.get("completed_at") or "",
                item.get("report_period") or "",
                item.get("stage") or "",
                item.get("report_id") or "",
            ),
            reverse=True,
        )
        return {
            "stage": stage,
            "status": status,
            "artifact_source": artifact_source,
            "contract_status": contract_status,
            "total": len(filtered),
            "results": filtered[:limit],
        }

    def document_pipeline_result_detail(self, stage: str, report_id: str) -> dict[str, Any]:
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        job = next(
            (
                item
                for item in jobs_manifest["records"]
                if item["stage"] == stage and item["report_id"] == report_id
            ),
            None,
        )
        if job is None:
            raise ValueError(f"未找到解析结果：{stage}/{report_id}")
        artifact_path_value = str(job.get("artifact_path") or "").strip()
        artifact_path = Path(artifact_path_value) if artifact_path_value else None
        if artifact_path is not None and artifact_path.exists():
            try:
                with artifact_path.open("r", encoding="utf-8") as file:
                    artifact = json.load(file)
            except json.JSONDecodeError as exc:
                raise ValueError(f"解析产物损坏：{artifact_path}") from exc
            evidence_navigation = _build_document_evidence_navigation(
                repository=self.repository,
                company_name=job["company_name"],
                report_period=job.get("report_period"),
                artifact=artifact,
            )
            artifact_source = job.get("artifact_source") or artifact.get("source")
        elif job.get("status") == "blocked":
            artifact = {
                "report_id": job["report_id"],
                "company_name": job["company_name"],
                "summary": job.get("artifact_summary") or "当前工序已阻断，未生成可交付解析产物。",
                "tables": [],
                "cells": [],
                "headings": [],
                "merge_candidates": [],
            }
            evidence_navigation = _build_document_navigation_unavailable(
                artifact,
                message="当前工序已阻断，未形成可跳转的正式证据入口。",
            )
            artifact_source = job.get("artifact_source")
        else:
            raise ValueError(f"未找到解析产物：{artifact_path_value or '<missing>'}")
        return {
            "job": {
                "stage": job["stage"],
                "stage_label": _document_stage_label(job["stage"]),
                "report_id": job["report_id"],
                "company_name": job["company_name"],
                "security_code": job["security_code"],
                "report_period": job.get("report_period"),
                "status": job["status"],
                "status_label": _status_label(job["status"]),
                "contract_status": _resolve_document_contract_status(self.settings, job),
                "artifact_path": job["artifact_path"],
                "completed_at": job.get("completed_at"),
                "artifact_summary": job.get("artifact_summary"),
                "artifact_source": artifact_source,
            },
            "artifact": artifact,
            "artifact_locations": _build_document_artifact_locations(job, artifact)
            if artifact_path is not None and artifact_path.exists()
            else [],
            "remediation": _build_document_artifact_remediation(
                stage=job["stage"],
                artifact_source=artifact_source,
                artifact=artifact,
            ),
            "evidence_navigation": evidence_navigation,
            "consumable_sections": _build_document_consumable_sections(artifact),
        }

    def run_document_pipeline_stage(
        self,
        stage: str,
        limit: int = 5,
        *,
        artifact_source: str | None = None,
        contract_status: str | None = None,
    ) -> dict[str, Any]:
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        records = jobs_manifest["records"]
        if contract_status and stage != "cell_trace":
            raise ValueError("contract_status 仅支持 cell_trace 阶段。")
        if contract_status == "ready":
            raise ValueError("不允许批量重跑 contract 已达标的样本。")
        before_summary = _summarize_contract_statuses(records, settings=self.settings, stage=stage)
        candidate_jobs: list[dict[str, Any]] = []
        for item in records:
            if item["stage"] != stage:
                continue
            item_contract_status = _resolve_document_contract_status(self.settings, item)
            item_artifact_source = item.get("artifact_source")
            if artifact_source and item_artifact_source != artifact_source:
                continue
            if contract_status and item_contract_status != contract_status:
                continue
            if contract_status:
                candidate_jobs.append(item)
                continue
            if item["status"] == "pending":
                candidate_jobs.append(item)
        pending_jobs = candidate_jobs[:limit]
        results: list[dict[str, Any]] = []
        for job in pending_jobs:
            try:
                artifact_payload, artifact_path = _run_document_pipeline_job(stage, job, self.settings)
            except DocumentPipelineBlockedError as exc:
                job["status"] = "blocked"
                job["artifact_path"] = ""
                job["completed_at"] = _utcnow_iso()
                job["artifact_summary"] = str(exc)
                job["artifact_source"] = None
                results.append(
                    {
                        "report_id": job["report_id"],
                        "company_name": job["company_name"],
                        "artifact_path": "",
                        "summary": str(exc),
                        "source": None,
                        "status": "blocked",
                    }
                )
                continue
            job["status"] = "completed"
            job["artifact_path"] = str(artifact_path)
            job["completed_at"] = _utcnow_iso()
            job["artifact_summary"] = artifact_payload.get("summary")
            job["artifact_source"] = artifact_payload.get("source")
            results.append(
                {
                    "report_id": job["report_id"],
                    "company_name": job["company_name"],
                    "artifact_path": str(artifact_path),
                    "summary": artifact_payload.get("summary"),
                    "source": artifact_payload.get("source"),
                    "status": "completed",
                }
            )
        _write_document_pipeline_job_manifest(self.settings, jobs_manifest)
        after_summary = _summarize_contract_statuses(
            jobs_manifest["records"],
            settings=self.settings,
            stage=stage,
        )
        execution_feedback = _build_document_pipeline_execution_feedback(
            stage=stage,
            contract_status=contract_status,
            processed=len(results),
            before_summary=before_summary,
            after_summary=after_summary,
        )
        run_record = _append_document_pipeline_run_record(
            self.settings,
            stage=stage,
            artifact_source=artifact_source,
            contract_status=contract_status,
            results=results,
            execution_feedback=execution_feedback,
        )
        return {
            "stage": stage,
            "requested": limit,
            "artifact_source": artifact_source,
            "contract_status": contract_status,
            "processed": len(results),
            "results": results,
            "execution_feedback": execution_feedback,
            "run_id": run_record["run_id"],
            "jobs": self.document_pipeline_jobs(),
        }

    def risk_scan(self, report_period: str | None = None) -> dict[str, Any]:
        companies = (
            self.repository.list_companies(report_period)
            if report_period is not None
            else self.repository.list_companies()
        )
        board = []
        for company in companies:
            risks = evaluate_risk_labels(company)
            board.append(
                {
                    "company_name": company["company_name"],
                    "subindustry": company["subindustry"],
                    "risk_count": len(risks),
                    "risk_labels": [item["name"] for item in risks],
                }
            )
        board.sort(key=lambda item: item["risk_count"], reverse=True)
        return {
            "query_type": "risk_scan",
            "answer_markdown": "已完成行业风险扫描，可直接查看高风险公司与标签分布。",
            "risk_board": board,
            "alert_board": _build_alert_board(self.repository, companies),
            "industry_research": self.industry_research_brief(),
            "charts": [
                {
                    "type": "bar",
                    "title": "行业风险标签命中数",
                    "options": {
                        "xAxis": {"type": "category", "data": [row["company_name"] for row in board]},
                        "yAxis": {"type": "value"},
                        "series": [{"type": "bar", "data": [row["risk_count"] for row in board]}],
                    },
                }
            ],
        }

    def industry_research_brief(self) -> dict[str, Any]:
        reports = _load_research_reports(
            self.settings.official_data_path / "manifests" / "industry_research_reports_manifest.json"
        )
        grouped_reports: dict[str, list[dict[str, Any]]] = {}
        for report in reports:
            industry_name = report.get("industry_name") or report.get("company_name")
            if not industry_name:
                continue
            insight = _build_research_report_insight(report)
            if insight is None:
                continue
            report_meta = insight["report_meta"]
            grouped_reports.setdefault(industry_name, []).append(
                {
                    "industry_name": industry_name,
                    "title": report_meta["title"],
                    "publish_date": report_meta["publish_date"],
                    "source_name": report_meta.get("source_name"),
                    "rating_text": _format_rating_text(report_meta),
                    "rating_change": report_meta.get("rating_change"),
                    "attachment_url": report_meta.get("attachment_url"),
                    "source_url": report_meta.get("source_url"),
                    "excerpt": _clip_claim_excerpt(insight["report_body"], industry_name, radius=180),
                }
            )

        groups: list[dict[str, Any]] = []
        for industry_name, items in grouped_reports.items():
            ordered_items = sorted(items, key=lambda item: item["publish_date"], reverse=True)
            groups.append(
                {
                    "industry_name": industry_name,
                    "report_count": len(ordered_items),
                    "latest_report": ordered_items[0],
                    "reports": ordered_items[:3],
                }
            )
        groups.sort(key=lambda item: item["industry_name"])
        return {
            "groups": groups,
            "key_numbers": [
                {"label": "覆盖行业", "value": len(groups), "unit": "个"},
                {"label": "行业研报", "value": sum(item["report_count"] for item in groups), "unit": "篇"},
            ],
        }

    def brief_company(self, company_name: str, report_period: str | None = None) -> dict[str, Any]:
        score_payload = self.score_company(company_name, report_period)
        scorecard = score_payload["scorecard"]
        return {
            "query_type": "brief_generation",
            "answer_markdown": (
                f"### {company_name} 经营简报\n"
                f"- 总分：{scorecard['total_score']}（{scorecard['grade']}）\n"
                f"- 强项：{', '.join(item['name'] for item in scorecard['strengths'])}\n"
                f"- 弱项：{', '.join(item['name'] for item in scorecard['weaknesses'])}\n"
                f"- 风险：{', '.join(item['name'] for item in scorecard['risk_labels']) or '暂无高风险标签'}\n"
                f"- 机会：{', '.join(item['name'] for item in scorecard['opportunity_labels']) or '暂无显著机会标签'}\n"
                f"- 建议动作：{'; '.join(item['title'] for item in scorecard['action_cards']) or '保持当前经营节奏'}"
            ),
            "scorecard": scorecard,
            "evidence": score_payload["evidence"],
            "audit": score_payload["audit"],
        }

    def list_research_reports(self, company_name: str) -> list[dict[str, Any]]:
        research_reports = _load_research_reports(
            self.settings.official_data_path / "manifests" / "research_reports_manifest.json"
        )
        available_periods = _get_company_periods(self.repository, company_name)
        matches = [report for report in research_reports if report.get("company_name") == company_name]
        if not matches:
            return []
        matches.sort(key=lambda item: item.get("publish_date", ""), reverse=True)
        matches.sort(key=lambda item: _research_report_content_score(item), reverse=True)
        matches.sort(key=lambda item: _research_report_bucket(item, available_periods))
        catalog: list[dict[str, Any]] = []
        for report in matches:
            insight = _build_research_report_insight(report)
            if insight is None:
                continue
            inferred_period = _infer_report_period_from_text(insight["report_meta"]["title"])
            forecast_summary = _summarize_forecast_cards(insight["forecast_cards"])
            catalog.append(
                {
                    "title": insight["report_meta"]["title"],
                    "publish_date": insight["report_meta"]["publish_date"],
                    "report_period": inferred_period,
                    "rating_text": _format_rating_text(insight["report_meta"]),
                    "rating_change": insight["report_meta"].get("rating_change"),
                    "target_price": insight["report_meta"].get("target_price"),
                    "forecast_count": len(insight["forecast_cards"]),
                    "headline_forecast_year": forecast_summary.get("headline_year"),
                    "headline_forecast_value": forecast_summary.get("headline_value"),
                    "headline_forecast_pe": forecast_summary.get("headline_pe"),
                    "claim_signal_count": insight["claim_signal_count"],
                    "source_name": insight["report_meta"].get("source_name"),
                    "source_url": insight["report_meta"].get("source_url"),
                    "attachment_url": insight["report_meta"].get("attachment_url"),
                    "is_period_supported": (
                        inferred_period in available_periods if inferred_period is not None else True
                    ),
                }
            )
        return catalog

    def compare_research_reports(
        self,
        company_name: str,
        limit: int = 6,
        *,
        sort_by: str = "priority",
        filter_mode: str = "all",
    ) -> dict[str, Any]:
        reports = self.list_research_reports(company_name)
        if not reports:
            raise ValueError(f"未找到研报：{company_name}")
        labeled_rows = _label_research_compare_rows(reports)
        filtered_rows = _filter_research_compare_rows(labeled_rows, filter_mode)
        rows = _sort_research_compare_rows(filtered_rows, sort_by)[:limit]
        target_prices = [item["target_price"] for item in rows if item.get("target_price") is not None]
        headline_forecasts = [
            item["headline_forecast_value"]
            for item in rows
            if item.get("headline_forecast_value") is not None
        ]
        return {
            "company_name": company_name,
            "rows": rows,
            "key_numbers": [
                {"label": "对比研报", "value": len(rows), "unit": "篇"},
                {
                    "label": "目标价区间",
                    "value": (
                        round(max(target_prices) - min(target_prices), 2)
                        if len(target_prices) >= 2
                        else None
                    ),
                    "unit": "元",
                },
                {
                    "label": "预测利润区间",
                    "value": (
                        round(max(headline_forecasts) - min(headline_forecasts), 2)
                        if len(headline_forecasts) >= 2
                        else None
                    ),
                    "unit": "亿元",
                },
            ],
            "charts": [
                _build_research_compare_chart(rows),
            ],
            "insights": _build_research_compare_insights(rows),
            "selected_sort": sort_by,
            "selected_filter": filter_mode,
            "sort_options": _build_research_compare_sort_options(),
            "filter_options": _build_research_compare_filter_options(),
            "total_reports": len(reports),
            "filtered_reports": len(filtered_rows),
        }

    def summarize_research_timeline(self, company_name: str) -> dict[str, Any]:
        reports = self.list_research_reports(company_name)
        if not reports:
            raise ValueError(f"未找到研报：{company_name}")
        timeline_groups = _build_research_timeline_groups(reports)
        return {
            "company_name": company_name,
            "institutions": timeline_groups,
            "key_numbers": [
                {"label": "覆盖机构", "value": len(timeline_groups), "unit": "家"},
                {
                    "label": "持续跟踪机构",
                    "value": sum(1 for item in timeline_groups if item["report_count"] >= 2),
                    "unit": "家",
                },
                {
                    "label": "最新观点有调整",
                    "value": sum(
                        1
                        for item in timeline_groups
                        if item.get("latest_transition")
                        and item["latest_transition"].get("transition_kind") in {"rating_changed", "target_changed"}
                    ),
                    "unit": "家",
                },
            ],
        }

    def verify_claim(
        self,
        company_name: str,
        report_period: str | None = None,
        report_title: str | None = None,
    ) -> dict[str, Any]:
        research_reports = _load_research_reports(
            self.settings.official_data_path / "manifests" / "research_reports_manifest.json"
        )
        report = _select_research_report(
            research_reports,
            company_name=company_name,
            report_period=report_period,
            report_title=report_title,
            available_periods=_get_company_periods(self.repository, company_name),
        )
        if report is None:
            raise ValueError(f"未找到研报：{company_name}")

        insight = _build_research_report_insight(report)
        if insight is None:
            raise ValueError(f"研报文件不可用：{company_name}")
        research_meta = insight["report_meta"]
        inferred_period = report_period or _infer_report_period_from_text(research_meta["title"])
        if inferred_period:
            company = self.repository.get_company(company_name, inferred_period)
            if company is None:
                raise ValueError(f"未找到与研报一致的真实报期：{company_name} {inferred_period}")
        else:
            company = self._resolve_company(company_name, None)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")

        report_body = insight["report_body"]
        claim_cards = _build_claim_cards(company, report, report_body)
        forecast_cards = insight["forecast_cards"]
        evidence = _build_claim_evidence(self.repository, report, research_meta, claim_cards, forecast_cards)
        calculations = [
            {
                "step": "研报观点核验",
                "detail": {
                    "report_title": research_meta["title"],
                    "claim_count": len(claim_cards),
                    "forecast_count": len(forecast_cards),
                    "matches": sum(1 for item in claim_cards if item["status"] == "match"),
                    "mismatches": sum(1 for item in claim_cards if item["status"] == "mismatch"),
                    "insufficient": sum(
                        1 for item in claim_cards if item["status"] == "insufficient_data"
                    ),
                },
            }
        ]
        key_numbers = [
            {"label": "匹配观点", "value": sum(1 for item in claim_cards if item["status"] == "match"), "unit": "条"},
            {"label": "偏差观点", "value": sum(1 for item in claim_cards if item["status"] == "mismatch"), "unit": "条"},
            {
                "label": "待补充观点",
                "value": sum(1 for item in claim_cards if item["status"] == "insufficient_data"),
                "unit": "条",
            },
        ]
        audit = build_audit(
            key_numbers=key_numbers,
            evidence=evidence,
            calculations=calculations,
            min_evidence=self.settings.audit_min_evidence,
        )
        return {
            "company_name": company["company_name"],
            "report_period": company["report_period"],
            "answer_markdown": _render_claim_answer(
                research_meta,
                company["report_period"],
                claim_cards,
                forecast_cards,
            ),
            "query_type": "claim_verification",
            "key_numbers": key_numbers,
            "charts": [_build_claim_chart(claim_cards)],
            "evidence": evidence,
            "evidence_groups": _build_claim_evidence_groups(claim_cards, forecast_cards, evidence),
            "calculations": calculations,
            "audit": audit,
            "claim_cards": claim_cards,
            "forecast_cards": forecast_cards,
            "report_meta": research_meta,
            "available_reports": self.list_research_reports(company_name),
            "verify_command_surface": _build_verify_command_surface(
                company=company,
                research_meta=research_meta,
                claim_cards=claim_cards,
                forecast_cards=forecast_cards,
            ),
            "verify_delta_tape": _build_verify_delta_tape(
                claim_cards=claim_cards,
                forecast_cards=forecast_cards,
            ),
            "research_compare": self.compare_research_reports(company_name),
            "research_timeline": self.summarize_research_timeline(company_name),
        }

    async def chat_turn(
        self,
        *,
        query: str,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "investor",
    ) -> dict[str, Any]:
        return await self._workspace.chat_turn(
            query=query,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            service=self,
        )

    def workspace_runs(self, limit: int = 20) -> dict[str, Any]:
        return self._workspace.workspace_runs(limit=limit)

    def workspace_runtime_audit(
        self,
        *,
        limit: int = 10,
        lookback: int = 60,
    ) -> dict[str, Any]:
        return self._workspace.workspace_runtime_audit(limit=limit, lookback=lookback)

    def workspace_history(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 30,
        source_limit: int = 200,
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
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
            for item in self.workspace_runs(limit=source_limit)["runs"]
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
            for item in self.watchboard_runs(
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
            for item in self.document_pipeline_results(limit=max(source_limit, limit))["results"]
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
            for item in self.document_pipeline_runs(limit=source_limit)["runs"]
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
            for item in self.stress_test_runs(
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
            for item in self.graph_query_runs(
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
            for item in self.vision_runs(
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

    def workspace_run_detail(self, run_id: str) -> dict[str, Any]:
        return self._workspace.workspace_run_detail(run_id)

    def metric_query(
        self, *, query: str, company_name: str | None, report_period: str | None
    ) -> dict[str, Any]:
        return self._workspace.metric_query(query=query, company_name=company_name, report_period=report_period)

    def get_evidence(self, chunk_id: str) -> dict[str, Any]:
        return self._workspace.get_evidence(chunk_id)

    def _persist_workspace_run(
        self,
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
        detail_path = _workspace_run_detail_path(self.settings, run_id)
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

        manifest = _load_workspace_run_manifest(self.settings)
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
        _write_workspace_run_manifest(self.settings, manifest)
        return {**payload, "run_id": run_id}

    def _preferred_period(self) -> str:
        if hasattr(self.repository, "preferred_period"):
            preferred_period = self.repository.preferred_period()
            if preferred_period:
                return preferred_period
        return self.settings.default_period

    def _resolve_company(
        self, company_name: str, report_period: str | None
    ) -> dict[str, Any] | None:
        company = self.repository.get_company(company_name, report_period)
        if company is not None:
            return company
        return self.repository.get_company(company_name, None)




