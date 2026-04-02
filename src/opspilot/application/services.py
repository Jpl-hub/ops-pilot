from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from datetime import UTC, date, datetime
import json
import re
import time

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.catalog import METRIC_BY_CODE
from opspilot.domain.routing import detect_query_type
from opspilot.domain.rules import evaluate_opportunity_labels, evaluate_risk_labels
from opspilot.domain.scoring import score_company
from opspilot.runtime_checks import probe_llm_runtime

# 域服务 — 拆分后的模块化架构
from opspilot.application.scoring_service import ScoringService
from opspilot.application.research_claims import (
    _build_claim_cards,
    _clip_claim_excerpt,
    _infer_report_period_from_text,
)
from opspilot.application.research_reports import (
    _build_forecast_cards,
    _build_research_report_insight,
    _extract_research_body,
    _extract_research_payload,
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
    _format_target_price,
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
    _build_document_artifact_locations,
    _build_document_artifact_preview,
    _build_document_artifact_remediation,
    _build_document_consumable_sections,
    _build_document_evidence_navigation,
    _build_document_navigation_unavailable,
    _filter_document_results_for_company,
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
    _describe_external_signal_freshness,
    _gold_data_root,
    _load_company_signal_snapshot,
    _load_company_signal_timeline,
    _load_manifest_generated_at,
    _merge_streaming_anomalies_into_attention_matrix,
    _load_subindustry_signal_heatmap,
    _parse_calendar_date,
    _parse_iso_timestamp,
)
from opspilot.application.document_pipeline import (
    DocumentPipelineBlockedError,
    _document_pipeline_artifact_path,
    _infer_heading_level,
    _is_valid_standard_ocr_cells,
    _is_valid_standard_ocr_tables,
    _normalize_report_period,
    _run_document_pipeline_job,
    _settings_ocr_runtime,
    _standard_ocr_artifact_path,
    _utcnow_iso,
    _write_json,
)
from opspilot.application.runtime_manifests import (
    _append_industry_brain_snapshot,
    _build_alert_id,
    _build_document_pipeline_run_id,
    _build_graph_query_run_id,
    _build_stress_test_run_id,
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
    _load_json_if_possible,
    _load_stress_test_run_manifest,
    _load_task_board_manifest,
    _load_vision_run_manifest,
    _load_watchboard_manifest,
    _load_watchboard_runs_manifest,
    _load_workspace_run_manifest,
    _stress_test_run_detail_path,
    _vision_run_detail_path,
    _workspace_run_detail_path,
    _write_alert_board_manifest,
    _write_document_pipeline_job_manifest,
    _write_document_pipeline_run_manifest,
    _write_industry_brain_manifest,
    _write_stress_test_run_manifest,
    _write_task_board_manifest,
    _write_vision_run_manifest,
    _write_watchboard_manifest,
    _write_watchboard_runs_manifest,
    _write_workspace_run_manifest,
    _write_graph_query_run_manifest,
    _load_graph_query_run_manifest,
)
from opspilot.application.runtime_views import (
    _build_industry_brain_history_snapshot,
    _build_industry_brain_watchboard_snapshot,
    _build_runtime_capsule_module,
    _filter_workspace_runs_for_company,
    _innovation_radar_path,
)
from opspilot.application.workspace_service import ROLE_PROFILES, WorkspaceService
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
        manifests_root = self.settings.official_data_path / "manifests"
        bronze_manifests_root = self.settings.bronze_data_path / "manifests"
        silver_manifests_root = self.settings.silver_data_path / "manifests"
        gold_manifests_root = _gold_data_root(self.settings) / "manifests"
        periodic_manifest = _read_manifest(manifests_root / "periodic_reports_manifest.json")
        research_manifest = _read_manifest(manifests_root / "research_reports_manifest.json")
        industry_research_manifest = _read_manifest(
            manifests_root / "industry_research_reports_manifest.json"
        )
        bronze_periodic_manifest = _read_manifest(
            bronze_manifests_root / "parsed_periodic_reports_manifest.json"
        )
        bronze_signal_manifest = _read_manifest(
            bronze_manifests_root / "external_signal_stream_manifest.json"
        )
        silver_metrics_manifest = _read_manifest(
            silver_manifests_root / "financial_metrics_manifest.json"
        )
        silver_signal_snapshot_manifest = _read_manifest(
            silver_manifests_root / "company_signal_snapshot_manifest.json"
        )
        gold_company_timeline_manifest = _read_manifest(
            gold_manifests_root / "company_signal_timeline_manifest.json"
        )
        gold_subindustry_heatmap_manifest = _read_manifest(
            gold_manifests_root / "subindustry_signal_heatmap_manifest.json"
        )
        snapshot_manifest = _read_manifest(manifests_root / "company_snapshots_manifest.json")
        return {
            "official_data_root": str(self.settings.official_data_path),
            "bronze_data_root": str(self.settings.bronze_data_path),
            "silver_data_root": str(self.settings.silver_data_path),
            "gold_data_root": str(_gold_data_root(self.settings)),
            "periodic_reports": periodic_manifest,
            "research_reports": research_manifest,
            "industry_research_reports": industry_research_manifest,
            "company_snapshots": snapshot_manifest,
            "bronze_periodic_reports": bronze_periodic_manifest,
            "bronze_signal_events": bronze_signal_manifest,
            "silver_financial_metrics": silver_metrics_manifest,
            "silver_signal_snapshot": silver_signal_snapshot_manifest,
            "gold_company_signal_timeline": gold_company_timeline_manifest,
            "gold_subindustry_signal_heatmap": gold_subindustry_heatmap_manifest,
        }

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
        radar_path = _innovation_radar_path()
        if not radar_path.exists():
            return {
                "generated_at": None,
                "focus": "新能源企业运营决策系统",
                "items": [],
                "summary": {"total": 0, "in_progress": 0, "planned": 0},
            }
        with radar_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        items = payload.get("items", [])
        return {
            "generated_at": payload.get("generated_at"),
            "focus": payload.get("focus"),
            "items": items,
            "summary": {
                "total": len(items),
                "in_progress": sum(1 for item in items if item.get("adoption_status") == "in_progress"),
                "planned": sum(1 for item in items if item.get("adoption_status") == "planned"),
            },
        }

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


def _collect_evidence_ids(company: dict[str, Any], score_result: dict[str, Any], risks: list[dict[str, Any]], opportunities: list[dict[str, Any]]) -> list[str]:
    chunk_ids: list[str] = []
    for metric in score_result["strengths"] + score_result["weaknesses"]:
        chunk_ids.extend(company.get("metric_evidence", {}).get(metric["code"], []))
    for metric_code in ("C3", "S3"):
        chunk_ids.extend(company.get("metric_evidence", {}).get(metric_code, []))
    for label in risks + opportunities:
        chunk_ids.extend(label["evidence_refs"])
    deduped: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id not in deduped:
            deduped.append(chunk_id)
    return deduped


def _render_score_answer(company: dict[str, Any], score_result: dict[str, Any], risks: list[dict[str, Any]], opportunities: list[dict[str, Any]]) -> str:
    strong_names = "、".join(item["name"] for item in score_result["strengths"])
    weak_names = "、".join(item["name"] for item in score_result["weaknesses"])
    risk_names = "、".join(item["name"] for item in risks) or "暂无高风险标签"
    opportunity_names = "、".join(item["name"] for item in opportunities) or "暂无显著机会标签"
    return (
        f"### {company['company_name']} 运营评估\n"
        f"- 总分：**{score_result['total_score']}**（等级 **{score_result['grade']}**）\n"
        f"- 分位：**{score_result['subindustry_percentile']}pct**，对标范围：{score_result['peer_scope']}\n"
        f"- 强项 Top3：{strong_names}\n"
        f"- 弱项 Top3：{weak_names}\n"
        f"- 风险标签：{risk_names}\n"
        f"- 机会标签：{opportunity_names}"
    )


def _build_action_cards(
    company: dict[str, Any],
    score_result: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    metrics = company.get("metrics", {})
    risk_map = {item["code"]: item for item in risks}
    opportunity_map = {item["code"]: item for item in opportunities}

    if "R1" in risk_map:
        cards.append(
            {
                "priority": "P1",
                "title": "优先修复现金回款链",
                "reason": f"经营现金流/净利润仅为 {metrics.get('C1')}，利润兑现没有跟上现金回流。",
                "action": "复盘应收回款节奏、压缩赊销账期，并把大额订单回款节点纳入月度经营例会。",
            }
        )
    if "R2" in risk_map:
        cards.append(
            {
                "priority": "P1",
                "title": "压降应收扩张速度",
                "reason": f"应收增速-收入增速差达到 {metrics.get('C3')}，应收扩张快于业务增长。",
                "action": "按客户分层重做信用政策，停止低质量放量，先把存量应收回款和坏账边界看清。",
            }
        )
    if "R4" in risk_map:
        cards.append(
            {
                "priority": "P1",
                "title": "重排短债与现金储备",
                "reason": f"现金短债比/流动比率承压，当前 S4={metrics.get('S4')}，S1={metrics.get('S1')}。",
                "action": "把未来 12 个月债务到期结构和可动用现金池拉成一张表，优先处理高成本短债续作。",
            }
        )
    if "R8" in risk_map:
        cards.append(
            {
                "priority": "P1",
                "title": "复核减值与异常资产",
                "reason": "系统识别到重大减值/关联交易风险，当前资产质量判断需要更谨慎。",
                "action": "对减值资产逐项做成因复盘，拆分一次性冲击和持续性压力，避免后续继续侵蚀利润。",
            }
        )
    if "R6" in risk_map or "R7" in risk_map:
        cards.append(
            {
                "priority": "P2",
                "title": "治理与合规事项闭环",
                "reason": "审计、处罚或诉讼信号已经进入评分链，会持续压制外部信任。",
                "action": "建立专项整改台账，明确责任部门、关闭时间和对外披露口径，避免事件持续发酵。",
            }
        )
    if "O1" in opportunity_map or "O2" in opportunity_map:
        cards.append(
            {
                "priority": "P3",
                "title": "放大盈利与现金改善窗口",
                "reason": "系统识别到毛利或现金质量改善信号，这部分正向变化值得继续验证并扩大。",
                "action": "把改善来源拆到产品、客户和区域三层，确认是结构性修复还是短期波动，再决定资源倾斜。",
            }
        )

    if not cards:
        weakest_metric = score_result["weaknesses"][0]["name"] if score_result["weaknesses"] else "关键弱项"
        cards.append(
            {
                "priority": "P2",
                "title": "围绕最弱指标做季度整改",
                "reason": f"当前最弱项集中在 {weakest_metric}，需要把指标问题转成经营动作。",
                "action": "把该指标拆成业务责任项、月度跟踪项和结果验收项，连续两个经营周期跟踪闭环。",
            }
        )
    return cards[:3]


def _build_company_charts(company: dict[str, Any], score_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "radar",
            "title": "五维运营雷达",
            "options": {
                "radar": {"indicator": [{"name": name, "max": 100} for name in score_result["dimension_scores"].keys()]},
                "series": [{"type": "radar", "data": [{"value": list(score_result["dimension_scores"].values()), "name": company["company_name"]}]}],
            },
        },
        {
            "type": "line",
            "title": "历史营收与净利润",
            "options": {
                "tooltip": {"trigger": "axis"},
                "legend": {"data": ["营收", "净利润"]},
                "xAxis": {"type": "category", "data": [row["period"] for row in company["history"]]},
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "营收", "type": "line", "data": [row["revenue"] for row in company["history"]]},
                    {"name": "净利润", "type": "line", "data": [row["net_profit"] for row in company["history"]]},
                ],
            },
        },
    ]


def _build_formula_cards(company: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for metric_code in ("C3", "S3"):
        if formula_card := _build_formula_card(company, metric_code):
            cards.append(formula_card)
    return cards


def _build_formula_card(company: dict[str, Any], metric_code: str) -> dict[str, Any] | None:
    context = company.get("formula_context", {}).get(metric_code)
    if not context:
        return None
    metric_def = METRIC_BY_CODE[metric_code]
    if metric_code == "C3":
        return {
            "metric_code": metric_code,
            "title": metric_def.name,
            "formula": context["formula"],
            "value": context["value"],
            "lines": [
                f"当前应收账款：{_format_number(context.get('current_receivable'))}",
                f"去年同期应收账款（{context.get('prior_period')}）：{_format_number(context.get('prior_receivable'))}",
                f"应收账款同比：{_format_pct(context.get('receivable_yoy'))}",
                f"营业收入同比：{_format_pct(context.get('revenue_yoy'))}",
                f"结果：{_format_pct(context.get('value'))}",
            ],
            "evidence_refs": company.get("metric_evidence", {}).get(metric_code, []),
            "anchor_terms": _anchor_terms_for_metrics((metric_code,)),
        }
    if metric_code == "S3":
        return {
            "metric_code": metric_code,
            "title": metric_def.name,
            "formula": context["formula"],
            "value": context["value"],
            "lines": [
                f"利润总额：{_format_number(context.get('profit_total'))}",
                f"利息费用：{_format_number(context.get('interest_expense'))}",
                f"结果：{_format_number(context.get('value'))}",
            ],
            "evidence_refs": company.get("metric_evidence", {}).get(metric_code, []),
            "anchor_terms": _anchor_terms_for_metrics((metric_code,)),
        }
    return None


def _build_formula_calculations(formula_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calculations = []
    for card in formula_cards:
        calculations.append(
            {
                "step": f"{card['metric_code']} 公式回放",
                "detail": {
                    "formula": card["formula"],
                    "value": card["value"],
                    "lines": card["lines"],
                },
            }
        )
    return calculations


def _build_label_cards(
    company: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    formula_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    formula_card_by_metric = {card["metric_code"]: card for card in formula_cards}
    label_cards = []
    for label in risks + opportunities:
        metric_rows = []
        linked_formula_cards = []
        for metric_code in LABEL_METRIC_CODES.get(label["code"], ()):
            metric_rows.append(
                {
                    "metric_code": metric_code,
                    "metric_name": METRIC_BY_CODE[metric_code].name,
                    "value": company["metrics"].get(metric_code),
                }
            )
            if metric_code in formula_card_by_metric:
                linked_formula_cards.append(metric_code)
        label_cards.append(
            {
                "code": label["code"],
                "name": label["name"],
                "kind": "risk" if label["code"].startswith("R") else "opportunity",
                "signal_values": label["signal_values"],
                "evidence_refs": label["evidence_refs"],
                "metrics": metric_rows,
                "formula_metric_codes": linked_formula_cards,
                "anchor_terms": _anchor_terms_for_metrics(LABEL_METRIC_CODES.get(label["code"], ())),
            }
        )
    return label_cards


def _build_evidence_groups(
    label_cards: list[dict[str, Any]],
    formula_cards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_by_id = {item["chunk_id"]: item for item in evidence}
    groups: list[dict[str, Any]] = []

    for card in label_cards:
        items = [
            evidence_by_id[chunk_id]
            for chunk_id in card["evidence_refs"]
            if chunk_id in evidence_by_id
        ]
        if not items:
            continue
        groups.append(
            {
                "group_type": "label",
                "code": card["code"],
                "title": f"{card['code']} {card['name']}",
                "subtitle": "标签触发证据",
                "anchor_terms": card.get("anchor_terms", []),
                "items": items,
            }
        )

    for card in formula_cards:
        items = [
            evidence_by_id[chunk_id]
            for chunk_id in card["evidence_refs"]
            if chunk_id in evidence_by_id
        ]
        if not items:
            continue
        groups.append(
            {
                "group_type": "formula",
                "code": card["metric_code"],
                "title": f"{card['metric_code']} {card['title']}",
                "subtitle": "公式输入证据",
                "anchor_terms": card.get("anchor_terms", []),
                "items": items,
            }
        )

    if evidence:
        groups.append(
            {
                "group_type": "all",
                "code": "ALL",
                "title": "全部证据",
                "subtitle": "当前评分结果涉及的完整证据包",
                "anchor_terms": [],
                "items": evidence,
            }
        )
    return groups


def _anchor_terms_for_metrics(metric_codes: tuple[str, ...] | list[str]) -> list[str]:
    terms: list[str] = []
    for metric_code in metric_codes:
        for term in METRIC_ANCHOR_TERMS.get(metric_code, (METRIC_BY_CODE[metric_code].name,)):
            if term not in terms:
                terms.append(term)
    return terms


def _format_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f} 亿元"
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _load_research_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("records", [])


def _build_industry_live_chart(points: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [item["timestamp"] for item in points]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": ["预警数", "处理中任务", "监测公司"]},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value"},
        "series": [
            {
                "name": "预警数",
                "type": "line",
                "smooth": True,
                "data": [item["alerts"] for item in points],
                "areaStyle": {},
            },
            {
                "name": "处理中任务",
                "type": "line",
                "smooth": True,
                "data": [item["tasks"] for item in points],
                "areaStyle": {},
            },
            {
                "name": "监测公司",
                "type": "line",
                "smooth": True,
                "data": [item["watching"] for item in points],
            },
        ],
    }


def _build_industry_risk_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [item["company_name"] for item in rows],
            "axisLabel": {"interval": 0, "rotate": 20},
        },
        "yAxis": {"type": "value"},
        "series": [
            {
                "name": "风险标签数",
                "type": "bar",
                "data": [item["risk_count"] for item in rows],
                "barMaxWidth": 36,
            }
        ],
    }


def _build_stress_propagation_steps(
    *,
    company_name: str,
    scenario: str,
    graph_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    top_risks: list[str],
    alert_items: list[dict[str, Any]],
    task_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path_labels: list[str] = []
    node_label_map = {node["id"]: node.get("label") or node["id"] for node in graph_nodes}
    for edge in graph_edges[:4]:
        source_label = node_label_map.get(edge["source"], edge["source"])
        target_label = node_label_map.get(edge["target"], edge["target"])
        path_labels.append(f"{source_label} -> {target_label}")
    risk_summary = "、".join(top_risks[:3]) or "当前重点风险"
    alert_summary = alert_items[0]["summary"] if alert_items else "尚未形成新增预警"
    task_summary = task_items[0]["title"] if task_items else "等待生成首要动作"
    return [
        {
            "step": 1,
            "title": "注入冲击",
            "detail": scenario,
            "tone": "input",
        },
        {
            "step": 2,
            "title": "映射到当前风险面",
            "detail": f"{company_name} 当前重点关注 {risk_summary}。",
            "tone": "risk",
        },
        {
            "step": 3,
            "title": "沿图谱与执行链传导",
            "detail": "；".join(path_labels[:3]) or "执行链尚在准备中。",
            "tone": "graph",
        },
        {
            "step": 4,
            "title": "触发预警与动作",
            "detail": f"{alert_summary}；当前优先动作：{task_summary}。",
            "tone": "action",
        },
    ]


def _classify_stress_severity(
    *,
    scenario: str,
    risk_count: int,
    open_tasks: int,
    open_alerts: int,
) -> dict[str, Any]:
    scenario_weight = 0
    hard_keywords = ("禁令", "断供", "停产", "关税", "制裁", "减产", "召回", "事故", "限制", "进口")
    for keyword in hard_keywords:
        if keyword in scenario:
            scenario_weight += 2 if keyword in ("禁令", "断供", "停产", "关税", "制裁") else 1
    score = risk_count + open_tasks + open_alerts + scenario_weight
    if scenario_weight >= 4 and (risk_count >= 1 or open_alerts >= 1):
        return {"level": "CRITICAL", "label": "高压场景", "color": "risk"}
    if score >= 8:
        return {"level": "CRITICAL", "label": "高压场景", "color": "risk"}
    if score >= 5:
        return {"level": "HIGH", "label": "重点关注", "color": "warning"}
    return {"level": "MEDIUM", "label": "可控冲击", "color": "success"}


def _build_stress_affected_dimensions(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    score_summary = workspace["score_summary"]
    task_summary = workspace["tasks"]["summary"]
    alert_summary = workspace["alerts"]["summary"]
    document_count = workspace["document_upgrades"]["count"]
    return [
        {"label": "风险标签", "value": score_summary["risk_count"], "hint": score_summary["grade"]},
        {"label": "在办任务", "value": task_summary["in_progress"], "hint": "需推进"},
        {"label": "未闭环预警", "value": alert_summary["new"] + alert_summary["in_progress"], "hint": "待处理"},
        {"label": "解析支撑", "value": document_count, "hint": "解析结果"},
    ]


def _build_score_command_surface(
    *,
    company: dict[str, Any],
    score_result: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    action_cards: list[dict[str, Any]],
    timeline_payload: dict[str, Any],
) -> dict[str, Any]:
    latest_snapshot = timeline_payload["snapshots"][0] if timeline_payload.get("snapshots") else {}
    score_delta = latest_snapshot.get("score_delta")
    headline = action_cards[0]["title"] if action_cards else "等待动作收口"
    return {
        "title": f"{company['company_name']} 经营体检",
        "headline": headline,
        "grade": score_result["grade"],
        "metric": f"{score_result['total_score']} 分",
        "intensity": min(100, 38 + int(score_result["total_score"])),
        "delta_label": f"{score_delta:+.2f}" if isinstance(score_delta, (int, float)) else "首个报期",
        "watch_items": [
            {"label": "风险标签", "value": str(len(risks))},
            {"label": "机会标签", "value": str(len(opportunities))},
            {"label": "优先动作", "value": str(len(action_cards))},
        ],
        "dominant_signal": {
            "label": "当前主判断",
            "value": risks[0]["name"] if risks else opportunities[0]["name"] if opportunities else "继续观察",
            "tone": "risk" if risks else "success" if opportunities else "accent",
        },
    }


def _build_score_signal_tape(
    *,
    score_result: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    action_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape = [
        {
            "step": 1,
            "label": "总分",
            "value": f"{score_result['total_score']} / {score_result['grade']}",
            "tone": "accent",
            "intensity": min(100, 30 + int(score_result["total_score"])),
        },
        {
            "step": 2,
            "label": "风险",
            "value": risks[0]["name"] if risks else "无显著风险",
            "tone": "risk" if risks else "success",
            "intensity": 76 if risks else 28,
        },
        {
            "step": 3,
            "label": "动作",
            "value": action_cards[0]["title"] if action_cards else "等待动作收口",
            "tone": "warning" if action_cards else "accent",
            "intensity": 68 if action_cards else 20,
        },
    ]
    if opportunities:
        tape.append(
            {
                "step": 4,
                "label": "机会",
                "value": opportunities[0]["name"],
                "tone": "success",
                "intensity": 54,
            }
        )
    return tape


def _build_stress_command_surface(
    *,
    company_name: str,
    scenario: str,
    severity: dict[str, Any],
    transmission_matrix: list[dict[str, Any]],
    simulation_log: list[dict[str, Any]],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    dominant = max(
        transmission_matrix,
        key=lambda item: int(item.get("impact_score", 0)),
        default={},
    )
    return {
        "title": f"{company_name} 冲击推演",
        "scenario": scenario,
        "severity": severity["level"],
        "severity_label": severity["label"],
        "headline": dominant.get("headline") or "等待冲击传导",
        "impact_label": dominant.get("impact_label") or severity["label"],
        "impact_score": int(dominant.get("impact_score", 0)),
        "energy_curve": [
            int(item.get("impact_score", 0))
            for item in transmission_matrix[:3]
        ],
        "watch_items": [
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
            },
            {
                "label": "在办任务",
                "value": str(workspace["tasks"]["summary"]["in_progress"]),
            },
            {
                "label": "新增预警",
                "value": str(workspace["alerts"]["summary"]["new"]),
            },
        ],
        "log_headline": simulation_log[-1]["detail"] if simulation_log else "等待推演日志",
    }


def _build_stress_evidence_links(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for item in workspace["document_upgrades"]["items"][:2]:
        route = item.get("route") or {}
        if route.get("path"):
            links.append(
                {
                    "label": f"{item['stage']} 解析详情",
                    "path": route["path"],
                    "query": route.get("query") or {},
                }
            )
        evidence_navigation = item.get("evidence_navigation") or {}
        primary_route = evidence_navigation.get("primary_route") or {}
        if primary_route.get("path"):
            links.append(
                {
                    "label": "证据入口",
                    "path": primary_route["path"],
                    "query": primary_route.get("query") or {},
                }
            )
    return links[:4]


def _build_stress_test_chart(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": [item["title"] for item in steps]},
        "yAxis": {"type": "value", "max": 100},
        "series": [
            {
                "type": "line",
                "smooth": True,
                "data": [28, 46, 72, 84][: len(steps)],
                "areaStyle": {},
            }
        ],
    }


def _build_stress_transmission_matrix(
    *,
    propagation_steps: list[dict[str, Any]],
    severity: dict[str, Any],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    labels = ["上游", "中游", "下游"]
    base_scores = [68, 82, 74]
    pressure = (
        workspace["score_summary"]["risk_count"] * 4
        + workspace["tasks"]["summary"]["in_progress"] * 6
        + workspace["alerts"]["summary"]["new"] * 5
    )
    cards: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        step_index = min(index + 1, len(propagation_steps) - 1)
        step = propagation_steps[step_index]
        impact_score = min(
            97,
            base_scores[index]
            + pressure
            + (8 if severity["level"] == "CRITICAL" else 3 if severity["level"] == "HIGH" else 0),
        )
        cards.append(
            {
                "stage": label,
                "headline": step["title"],
                "detail": step["detail"],
                "impact_score": impact_score,
                "impact_label": "高冲击" if impact_score >= 85 else "中高冲击" if impact_score >= 72 else "可控冲击",
                "tone": "risk" if impact_score >= 85 else "warning" if impact_score >= 72 else "success",
            }
        )
    return cards


def _build_stress_simulation_log(
    *,
    company_name: str,
    scenario: str,
    propagation_steps: list[dict[str, Any]],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    top_risks = "、".join(workspace["top_risks"][:3]) or "暂无高风险标签"
    actions = workspace["action_cards"][0]["title"] if workspace["action_cards"] else "等待动作收口"
    checkpoints = [
        ("初始化", f"{company_name} / {workspace['report_period']}"),
        ("冲击注入", scenario),
        ("风险映射", top_risks),
        (
            "传导分析",
            propagation_steps[2]["detail"] if len(propagation_steps) > 2 else propagation_steps[-1]["detail"],
        ),
        ("动作收口", actions),
    ]
    return [
        {
            "step": index + 1,
            "title": title,
            "detail": detail,
        }
        for index, (title, detail) in enumerate(checkpoints)
    ]


def _build_stress_wavefront(
    *,
    propagation_steps: list[dict[str, Any]],
    transmission_matrix: list[dict[str, Any]],
    simulation_log: list[dict[str, Any]],
    severity: dict[str, Any],
) -> list[dict[str, Any]]:
    stage_order = ["upstream", "midstream", "downstream", "actions"]
    frames: list[dict[str, Any]] = []
    for index, step in enumerate(propagation_steps):
        matrix_entry = transmission_matrix[min(index, len(transmission_matrix) - 1)] if transmission_matrix else {}
        log_entry = simulation_log[min(index, len(simulation_log) - 1)] if simulation_log else {}
        impact_score = int(matrix_entry.get("impact_score", 0))
        frames.append(
            {
                "frame": index + 1,
                "headline": step["title"],
                "detail": step["detail"],
                "active_stage": stage_order[min(index, len(stage_order) - 1)],
                "severity": severity["level"],
                "impact_score": impact_score,
                "impact_label": matrix_entry.get("impact_label", severity["label"]),
                "log": log_entry.get("detail", step["detail"]),
                "energy": max(18, min(100, 38 + impact_score // 2 + index * 7)),
            }
        )
    if not frames:
        frames.append(
            {
                "frame": 1,
                "headline": "等待压力推演",
                "detail": "当前没有可播放的冲击传导阶段。",
                "active_stage": "upstream",
                "severity": severity["level"],
                "impact_score": 0,
                "impact_label": severity["label"],
                "log": "等待系统生成推演日志。",
                "energy": 0,
            }
        )
    return frames


def _build_stress_impact_tape(
    *,
    transmission_matrix: list[dict[str, Any]],
    simulation_log: list[dict[str, Any]],
    severity: dict[str, Any],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, item in enumerate(transmission_matrix):
        log_entry = simulation_log[min(index, len(simulation_log) - 1)] if simulation_log else {}
        impact_score = int(item.get("impact_score", 0))
        tape.append(
            {
                "step": index + 1,
                "label": item.get("stage") or f"阶段 {index + 1}",
                "headline": item.get("headline") or log_entry.get("title") or severity["label"],
                "intensity": max(12, min(100, impact_score + 18)),
                "tone": item.get("tone") or "warning",
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待推演",
                "headline": severity["label"],
                "intensity": 0,
                "tone": "warning",
            }
        )
    return tape


def _build_stress_recovery_sequence(
    *,
    actions: list[dict[str, Any]],
    top_risks: list[str],
    severity: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, action in enumerate(actions[:4]):
        items.append(
            {
                "step": index + 1,
                "title": action.get("title") or f"动作 {index + 1}",
                "detail": action.get("reason") or action.get("action") or "等待动作建议",
                "tone": "risk" if severity["level"] == "CRITICAL" and index == 0 else "accent",
            }
        )
    if not items:
        items.append(
            {
                "step": 1,
                "title": "继续跟踪",
                "detail": "、".join(top_risks[:2]) or "等待恢复路径",
                "tone": "accent",
            }
        )
    return items


def _build_vision_phase_track(
    *,
    company_name: str,
    report_period: str,
    selected_item: dict[str, Any],
    detail: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sections = detail.get("consumable_sections", []) if detail else []
    evidence_links = (detail or {}).get("evidence_navigation", {}).get("links", [])
    stage_label = _document_stage_label(selected_item.get("stage", "document"))
    stage_status = selected_item.get("status")
    return [
        {
            "phase": "载入报告",
            "status": "done",
            "headline": company_name,
            "metric": report_period,
        },
        {
            "phase": "解析工序",
            "status": "done" if stage_status in {"done", "completed"} else "active",
            "headline": stage_label,
            "metric": _status_label(stage_status),
        },
        {
            "phase": "结构抽取",
            "status": "done" if sections else "active",
            "headline": "标题/表格/片段",
            "metric": f"{len(sections)} 类结构",
        },
        {
            "phase": "证据挂接",
            "status": "done" if evidence_links else "active",
            "headline": "可回看原证据",
            "metric": f"{len(evidence_links)} 个入口",
        },
    ]


def _vision_selected_item_priority(item: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        1 if item.get("artifact_summary") or item.get("artifact_preview") else 0,
        {"cross_page_merge": 1, "title_hierarchy": 2, "cell_trace": 3}.get(item.get("stage"), 0),
        1 if item.get("status") in {"done", "completed"} else 0,
        item.get("completed_at") or "",
    )


def _build_vision_extraction_stream(
    *,
    detail: dict[str, Any] | None,
    selected_item: dict[str, Any],
) -> list[dict[str, Any]]:
    stream: list[dict[str, Any]] = []
    sections = detail.get("consumable_sections", []) if detail else []
    for section in sections[:4]:
        stream.append(
            {
                "label": section.get("title", "section"),
                "value": str(section.get("count", 0)),
                "tone": "accent" if section.get("section_type") in {"heading_outline", "summary"} else "success",
            }
        )
    if not stream:
        stream.append(
            {
                "label": _document_stage_label(selected_item.get("stage", "document")),
                "value": _status_label(selected_item.get("status")),
                "tone": "warning",
            }
        )
    return stream[:6]


def _build_vision_analysis_log(
    *,
    company_name: str,
    report_period: str,
    selected_item: dict[str, Any],
    detail: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sections = detail.get("consumable_sections", []) if detail else []
    checkpoints = [
        ("初始化", f"{company_name} / {report_period}"),
        (
            "定位报告",
            selected_item.get("report_id")
            or _document_stage_label(selected_item.get("stage", "document")),
        ),
        ("抽取结构", "、".join(section.get("title", "section") for section in sections[:3]) or "等待结构化结果"),
        (
            "生成摘要",
            selected_item.get("artifact_summary")
            or selected_item.get("artifact_preview")
            or "等待摘要结果",
        ),
        (
            "挂接证据",
            f"{len((detail or {}).get('evidence_navigation', {}).get('links', []))} 个入口",
        ),
    ]
    return [
        {
            "step": index + 1,
            "title": title,
            "detail": detail_text,
        }
        for index, (title, detail_text) in enumerate(checkpoints)
    ]


def _build_vision_quality_summary(
    *,
    detail: dict[str, Any] | None,
    selected_item: dict[str, Any],
    ocr_runtime: dict[str, Any],
) -> dict[str, Any]:
    artifact = detail.get("artifact", {}) if detail else {}
    job = detail.get("job", {}) if detail else {}
    sections = detail.get("consumable_sections", []) if detail else []
    evidence_links = (detail or {}).get("evidence_navigation", {}).get("links", [])
    headings = artifact.get("headings") if isinstance(artifact.get("headings"), list) else []
    tables = artifact.get("tables") if isinstance(artifact.get("tables"), list) else []
    cells = artifact.get("cells") if isinstance(artifact.get("cells"), list) else []
    merges = (
        artifact.get("merge_candidates")
        if isinstance(artifact.get("merge_candidates"), list)
        else artifact.get("merged_sections")
        if isinstance(artifact.get("merged_sections"), list)
        else []
    )
    artifact_source = (
        job.get("artifact_source")
        or selected_item.get("artifact_source")
        or artifact.get("source")
    )
    contract_status = job.get("contract_status") or selected_item.get("contract_status")
    stage = job.get("stage") or selected_item.get("stage")
    stage_label = _document_stage_label(stage) if stage else "文档解析"
    dimensions = [
        {
            "key": "artifact_source",
            "label": "解析来源",
            "status": "ready" if artifact_source == "standard_ocr" else "warning" if artifact_source else "blocked",
            "summary": (
                f"当前采用 {_artifact_source_label(artifact_source)}。"
                if artifact_source
                else "尚未生成可核验的解析产物。"
            ),
        },
        {
            "key": "structure",
            "label": "结构抽取",
            "status": "ready" if sections else "blocked",
            "summary": (
                f"已形成 {len(sections)} 类结构化结果。"
                if sections
                else "当前还没有标题、表格或摘要等结构化结果。"
            ),
        },
        {
            "key": "table_trace",
            "label": "表格溯源",
            "status": "ready" if tables and cells else "warning" if tables or cells else "blocked",
            "summary": (
                f"已恢复 {len(tables)} 个表格片段、{len(cells)} 个单元格。"
                if tables or cells
                else "当前没有形成可追溯的表格与单元格结果。"
            ),
        },
        {
            "key": "evidence",
            "label": "证据回看",
            "status": "ready" if evidence_links else "warning",
            "summary": (
                f"可直接回看 {len(evidence_links)} 个证据入口。"
                if evidence_links
                else "当前结果还没有可直接跳转的证据入口。"
            ),
        },
    ]
    if stage == "cell_trace" or contract_status is not None:
        dimensions.insert(
            1,
            {
                "key": "ocr_contract",
                "label": "OCR 结构契约",
                "status": (
                    "ready"
                    if contract_status == "ready"
                    else "blocked"
                    if contract_status in {"missing", "invalid"}
                    else "warning"
                ),
                "summary": (
                    "标准 OCR contract 已通过字段校验。"
                    if contract_status == "ready"
                    else "缺少标准 OCR 结构契约，当前无法确认正式单元格产物。"
                    if contract_status == "missing"
                    else "标准 OCR 结构契约存在但字段不合法。"
                    if contract_status == "invalid"
                    else "当前阶段尚未进入 OCR 结构契约质检。"
                ),
            },
        )

    blockers: list[dict[str, str]] = []

    def add_blocker(title: str, detail_text: str) -> None:
        if any(item["title"] == title for item in blockers):
            return
        blockers.append({"title": title, "detail": detail_text})

    if detail is None:
        add_blocker("尚无可回看产物", f"{stage_label} 当前只有工序记录，尚未生成可复核的结构化结果。")
    if not ocr_runtime.get("runtime_enabled"):
        add_blocker(
            "标准 OCR 引擎未启用",
            "当前环境未开启正式 OCR 运行时，无法形成稳定的标准 OCR 交付链。",
        )
    if contract_status == "missing":
        add_blocker(
            "缺少标准 OCR 结构契约",
            "单元格溯源尚未拿到合法 tables/cells 产物，需要先补齐标准 OCR 输出。",
        )
    elif contract_status == "invalid":
        add_blocker(
            "标准 OCR 结构契约不合格",
            "tables/cells 字段校验未通过，当前产物不能作为正式交付结果。",
        )
    if stage == "cell_trace" and artifact_source != "standard_ocr":
        add_blocker(
            "标准 OCR 结果未就绪",
            "当前单元格阶段还没有形成正式 OCR 标准产物，不能直接作为交付结果。",
        )
    if not evidence_links:
        add_blocker(
            "证据入口不足",
            "当前结果还不能一键回看原文证据，复核链条不完整。",
        )
    for item in detail.get("remediation", []) if detail else []:
        title = item.get("title")
        detail_text = item.get("detail")
        if title and detail_text:
            add_blocker(title, detail_text)

    status = "ready"
    if any(item["status"] == "blocked" for item in dimensions):
        status = "blocked"
    elif any(item["status"] == "warning" for item in dimensions):
        status = "warning"

    if status == "ready":
        headline = "已达到核验条件"
        summary = "标准 OCR、结构抽取与证据回看均已接通，可直接进入人工复核。"
    elif status == "warning":
        headline = "结果可读但仍需补强"
        summary = "当前解析结果可以浏览，但仍存在来源或证据链短板，尚不建议作为正式交付版本。"
    else:
        headline = "尚未达到交付标准"
        summary = "当前解析链仍有阻断项，需要先补齐标准 OCR 或结构/证据链路。"

    metrics = [
        {
            "label": "解析来源",
            "value": _artifact_source_label(artifact_source),
            "tone": "success" if artifact_source == "standard_ocr" else "warning",
        },
        {
            "label": "标题节点",
            "value": str(len(headings)),
            "tone": "success" if headings else "warning",
        },
        {
            "label": "表格片段",
            "value": str(len(tables)),
            "tone": "success" if tables else "warning",
        },
        {
            "label": "单元格",
            "value": str(len(cells)),
            "tone": "success" if cells else "warning",
        },
        {
            "label": "跨页候选",
            "value": str(len(merges)),
            "tone": "success" if merges else "accent",
        },
        {
            "label": "证据入口",
            "value": str(len(evidence_links)),
            "tone": "success" if evidence_links else "warning",
        },
    ]
    return {
        "status": status,
        "label": {"ready": "可进入核验", "warning": "需补强", "blocked": "待补齐"}[status],
        "headline": headline,
        "summary": summary,
        "stage_label": stage_label,
        "artifact_source": artifact_source,
        "artifact_source_label": _artifact_source_label(artifact_source),
        "contract_status": contract_status,
        "metrics": metrics,
        "dimensions": dimensions,
        "blockers": blockers[:5],
        "artifact_locations": detail.get("artifact_locations", []) if detail else [],
    }


def _artifact_source_label(source: str | None) -> str:
    return {
        "standard_ocr": "正式结构产物",
        "geometric_fallback": "历史结构产物",
    }.get(source or "", source or "来源未识别")


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


def _filter_document_results_for_company(
    results: list[dict[str, Any]],
    company_name: str,
    report_period: str | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in results:
        if item["company_name"] != company_name:
            continue
        if report_period and item.get("report_period") not in (None, report_period):
            continue
        filtered.append(item)
    filtered.sort(
        key=lambda item: (
            item.get("completed_at") or "",
            item.get("stage") or "",
            item.get("report_id") or "",
        ),
        reverse=True,
    )
    return filtered


def _build_document_artifact_preview(artifact: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    if source := artifact.get("source"):
        preview["source"] = source
    if summary := artifact.get("summary"):
        preview["summary"] = summary
    if headings := artifact.get("headings"):
        preview["headings"] = [
            {
                "text": item.get("text"),
                "level": item.get("level"),
                "page": item.get("page"),
            }
            for item in headings[:5]
        ]
    if merges := artifact.get("merged_sections"):
        preview["merged_sections"] = [
            {
                "title": item.get("title"),
                "page_range": item.get("page_range"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
            }
            for item in merges[:5]
        ]
    if cells := artifact.get("cells"):
        preview["cells"] = cells[:5]
    if tables := artifact.get("tables"):
        preview["tables"] = [
            {
                "title": item.get("title"),
                "page": item.get("page"),
                "continued": item.get("continued"),
            }
            for item in tables[:5]
        ]
    return preview


def _load_document_artifact_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    artifact_path = record.get("artifact_path")
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_company_document_upgrade_items(
    settings: Settings, company_name: str, report_period: str
) -> list[dict[str, Any]]:
    jobs_manifest = _load_document_pipeline_job_manifest(settings)
    return _filter_document_results_for_company(
        [
            {
                "stage": item["stage"],
                "report_id": item["report_id"],
                "company_name": item["company_name"],
                "security_code": item["security_code"],
                "report_period": item.get("report_period"),
                "status": item["status"],
                "artifact_path": item.get("artifact_path"),
                "artifact_summary": item.get("artifact_summary"),
                "artifact_source": item.get("artifact_source"),
                "contract_status": _resolve_document_contract_status(settings, item),
                "completed_at": item.get("completed_at"),
            }
            for item in jobs_manifest["records"]
        ],
        company_name,
        report_period,
    )


_GRAPH_QUERY_TERM_EXPANSIONS = {
    "应收": ("应收账款", "账期", "回款", "现金流"),
    "现金": ("现金流", "货币资金", "流动性", "偿债"),
    "风险": ("风险", "预警", "整改", "暴露"),
    "传导": ("传导", "路径", "影响链", "执行流"),
    "供应链": ("供应链", "上游", "下游", "链条"),
    "研报": ("研报", "观点", "预测", "核验"),
    "证据": ("证据", "页码", "字段", "导航"),
    "文档": ("文档", "解析", "标题层级", "单元格溯源"),
    "存货": ("存货", "周转", "库存", "减值"),
    "增长": ("营收", "增长", "扩张", "市场份额"),
    "价格": ("价格", "成本", "毛利率", "碳酸锂"),
    "偿债": ("偿债", "流动比率", "短期借款", "利息"),
    "实时": ("实时", "最新", "时序", "外部信号", "动量", "热度"),
    "最新": ("最新", "最近", "时效", "窗口", "外部事件"),
    "异动": ("异动", "热度", "信号", "预警", "波动"),
    "时间": ("时间线", "时序", "最近", "窗口", "日度"),
}

_GRAPH_INTENT_TYPE_PRIOR = {
    "price": {
        "signal_event": 5,
        "signal_timeline": 5,
        "subindustry_signal": 6,
        "risk_label": 5,
        "alert": 5,
        "research_report": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "task": 3,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "cash": {
        "signal_event": 5,
        "signal_timeline": 6,
        "subindustry_signal": 4,
        "risk_label": 6,
        "alert": 5,
        "task": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "execution_stream": 3,
        "watchboard": 3,
        "research_report": 3,
        "company": 2,
        "report_period": 1,
    },
    "growth": {
        "signal_event": 4,
        "signal_timeline": 5,
        "subindustry_signal": 5,
        "research_report": 5,
        "risk_label": 4,
        "task": 4,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "alert": 3,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "supply": {
        "signal_event": 5,
        "signal_timeline": 5,
        "subindustry_signal": 6,
        "risk_label": 5,
        "alert": 5,
        "task": 4,
        "research_report": 4,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "risk": {
        "signal_event": 6,
        "signal_timeline": 5,
        "subindustry_signal": 5,
        "risk_label": 6,
        "alert": 6,
        "task": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "research_report": 4,
        "execution_stream": 3,
        "watchboard": 3,
        "company": 2,
        "report_period": 1,
    },
}


def _dedupe_terms(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if len(normalized) < 2:
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _expand_graph_query_terms(intent: str) -> list[str]:
    lowered = intent.lower()
    terms: list[str] = []
    for part in re.split(r"[\s,，。；;、\-_/]+", lowered):
        part = part.strip()
        if len(part) >= 2:
            terms.append(part)
    chinese_spans = re.findall(r"[\u4e00-\u9fff]{2,}", intent)
    for span in chinese_spans:
        if len(span) <= 6:
            terms.append(span)
        else:
            for index in range(0, len(span) - 1):
                terms.append(span[index : index + 2])
                if index + 3 <= len(span):
                    terms.append(span[index : index + 3])
    for keyword, expansions in _GRAPH_QUERY_TERM_EXPANSIONS.items():
        if keyword in intent:
            terms.append(keyword)
            terms.extend(expansions)
    dimension = _classify_intent(intent)
    dimension_title, dimension_detail = _INTENT_DIMENSION_DESC.get(
        dimension,
        _INTENT_DIMENSION_DESC["risk"],
    )
    terms.append(dimension_title.replace("维度", ""))
    terms.extend(
        [part for part in re.findall(r"[\u4e00-\u9fff]{2,}", dimension_detail) if len(part) >= 2]
    )
    deduped: list[str] = []
    for term in terms:
        normalized = str(term).strip().lower()
        if len(normalized) < 2:
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped[:24]


def _build_graph_node_text(node: dict[str, Any]) -> str:
    meta = node.get("meta") or {}
    meta_parts: list[str] = []
    for key, value in meta.items():
        if isinstance(value, list):
            meta_parts.extend(str(item) for item in value if item is not None)
        elif value is not None:
            meta_parts.append(f"{key} {value}")
    return " ".join(
        [
            str(node.get("label") or ""),
            str(node.get("type") or ""),
            *meta_parts,
        ]
    ).lower()


def _build_graph_edge_maps(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    edge_labels_by_node: dict[str, list[str]] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        label = str(edge.get("label") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append({"node_id": target, "label": label})
        adjacency.setdefault(target, []).append({"node_id": source, "label": label})
        if label:
            edge_labels_by_node.setdefault(source, []).append(label)
            edge_labels_by_node.setdefault(target, []).append(label)
    return adjacency, edge_labels_by_node


def _graph_node_temporal_meta(node: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    meta = node.get("meta") or {}
    latest_value = (
        meta.get("latest_event_time")
        or meta.get("latest_event_date")
        or meta.get("latest_publish_date")
    )
    return (_parse_calendar_date(str(latest_value) if latest_value is not None else None), meta)


def _score_graph_temporal_signal(
    node: dict[str, Any],
    query_terms: list[str],
) -> tuple[int, list[str]]:
    node_type = str(node.get("type") or "")
    if node_type not in _GRAPH_SIGNAL_NODE_TYPES:
        return 0, []
    latest_date, meta = _graph_node_temporal_meta(node)
    score = 0
    explain: list[str] = []
    if latest_date is not None:
        age_days = max(0, (datetime.now(UTC).date() - latest_date).days)
        if age_days <= 1:
            score += 10
            explain.append("近 24 小时更新")
        elif age_days <= 3:
            score += 7
            explain.append(f"{age_days} 天内更新")
        elif age_days <= 7:
            score += 4
            explain.append(f"最近 {age_days} 天更新")
    momentum = int(meta.get("momentum") or 0)
    latest_heat = int(meta.get("latest_heat") or 0)
    external_heat = int(meta.get("external_heat") or 0)
    signal_count = int(meta.get("signal_count") or 0)
    active_days = int(meta.get("active_days") or 0)
    realtime_requested = any(term in intent_term for term in _GRAPH_REALTIME_TERMS for intent_term in query_terms)
    if momentum > 0:
        score += min(10, momentum * 2 if realtime_requested else momentum)
        explain.append(f"动量 {momentum}")
    if latest_heat > 0:
        score += min(6, latest_heat if realtime_requested else max(1, latest_heat // 2))
        explain.append(f"最新热度 {latest_heat}")
    if external_heat > 0:
        score += min(6, max(1, external_heat // 2))
        explain.append(f"累计热度 {external_heat}")
    if signal_count > 0:
        score += min(5, signal_count if realtime_requested else max(1, signal_count // 2))
        explain.append(f"{signal_count} 条正式信号")
    if active_days > 0:
        score += min(4, active_days)
        explain.append(f"活跃 {active_days} 天")
    if node_type == "subindustry_signal" and any(
        term in query_term
        for term in ("行业", "板块", "子行业", "上游", "下游", "供应链")
        for query_term in query_terms
    ):
        score += 6
        explain.append("板块共振命中")
    return score, explain[:4]


def _score_graph_edge_label(label: str, query_terms: list[str]) -> tuple[int, list[str]]:
    lowered = str(label or "").lower()
    hits = [term for term in query_terms if term in lowered]
    return (len(hits) * 2, hits)


def _rank_graph_nodes_for_intent(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    intent: str,
) -> list[dict[str, Any]]:
    dimension = _classify_intent(intent)
    type_priority = _GRAPH_INTENT_TYPE_PRIOR.get(dimension, _GRAPH_INTENT_TYPE_PRIOR["risk"])
    query_terms = _expand_graph_query_terms(intent)
    adjacency, edge_labels_by_node = _build_graph_edge_maps(edges)
    text_by_node = {str(node.get("id")): _build_graph_node_text(node) for node in nodes}
    base_scores: dict[str, int] = {}
    lexical_hits_by_node: dict[str, list[str]] = {}
    neighbor_hits_by_node: dict[str, list[str]] = {}
    edge_hits_by_node: dict[str, list[str]] = {}
    temporal_hits_by_node: dict[str, list[str]] = {}

    for node in nodes:
        node_id = str(node.get("id") or "")
        label_text = str(node.get("label") or "").lower()
        node_text = text_by_node.get(node_id, "")
        lexical_score = 0
        lexical_hits: list[str] = []
        for term in query_terms:
            if term in label_text:
                lexical_score += 8
                lexical_hits.append(term)
            elif term in node_text:
                lexical_score += 4
                lexical_hits.append(term)
        edge_score = 0
        edge_hits: list[str] = []
        for label in edge_labels_by_node.get(node_id, []):
            matched_score, matched_terms = _score_graph_edge_label(label, query_terms)
            edge_score += matched_score
            edge_hits.extend(matched_terms)
        degree_score = min(3, len(adjacency.get(node_id, [])))
        temporal_score, temporal_hits = _score_graph_temporal_signal(node, query_terms)
        base_scores[node_id] = (
            type_priority.get(str(node.get("type")), 0)
            + lexical_score
            + edge_score
            + degree_score
            + temporal_score
        )
        lexical_hits_by_node[node_id] = _dedupe_terms(lexical_hits)
        edge_hits_by_node[node_id] = _dedupe_terms(edge_hits)
        temporal_hits_by_node[node_id] = temporal_hits

    ranked: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        neighbor_terms: list[str] = []
        neighbor_score = 0
        for neighbor in adjacency.get(node_id, []):
            neighbor_id = str(neighbor.get("node_id") or "")
            neighbor_base = int(base_scores.get(neighbor_id) or 0)
            if neighbor_base <= 0:
                continue
            matched_score, matched_terms = _score_graph_edge_label(str(neighbor.get("label") or ""), query_terms)
            neighbor_text = text_by_node.get(neighbor_id, "")
            neighbor_term_hits = [term for term in query_terms if term in neighbor_text]
            if neighbor_term_hits:
                neighbor_terms.extend(neighbor_term_hits)
                neighbor_score += min(8, max(2, neighbor_base // 3))
            if matched_score:
                neighbor_terms.extend(matched_terms)
                neighbor_score += matched_score
        total_score = int(base_scores.get(node_id) or 0) + min(18, neighbor_score)
        explain_parts: list[str] = []
        if lexical_hits_by_node.get(node_id):
            explain_parts.append(f"命中查询词：{' / '.join(lexical_hits_by_node[node_id][:3])}")
        if edge_hits_by_node.get(node_id):
            explain_parts.append(f"边标签命中：{' / '.join(edge_hits_by_node[node_id][:2])}")
        deduped_neighbor_terms = _dedupe_terms(neighbor_terms)
        if deduped_neighbor_terms:
            explain_parts.append(f"邻居传播：{' / '.join(deduped_neighbor_terms[:3])}")
        if temporal_hits_by_node.get(node_id):
            explain_parts.append(f"时序加权：{' / '.join(temporal_hits_by_node[node_id][:3])}")
        explain_parts.append(f"节点类型：{node.get('type')}")
        ranked.append(
            {
                **node,
                "intent_score": total_score,
                "hit_terms": lexical_hits_by_node.get(node_id, []),
                "edge_terms": edge_hits_by_node.get(node_id, []),
                "neighbor_terms": deduped_neighbor_terms,
                "rank_explain": "；".join(explain_parts),
            }
        )

    ranked.sort(
        key=lambda item: (
            int(item.get("intent_score") or 0),
            type_priority.get(str(item.get("type")), 0),
            str(item.get("label", "")),
        ),
        reverse=True,
    )
    return ranked


def _find_graph_path(
    *,
    adjacency: dict[str, list[dict[str, Any]]],
    start_id: str,
    target_id: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not start_id or not target_id:
        return ([], [])
    if start_id == target_id:
        return ([start_id], [])
    queue: list[tuple[str, list[str], list[dict[str, Any]]]] = [(start_id, [start_id], [])]
    visited = {start_id}
    while queue:
        node_id, path_nodes, path_edges = queue.pop(0)
        for neighbor in adjacency.get(node_id, []):
            next_id = str(neighbor.get("node_id") or "")
            if not next_id or next_id in visited:
                continue
            next_nodes = [*path_nodes, next_id]
            next_edges = [*path_edges, {"source": node_id, "target": next_id, "label": neighbor.get("label")}]
            if next_id == target_id:
                return (next_nodes, next_edges)
            visited.add(next_id)
            queue.append((next_id, next_nodes, next_edges))
    return ([], [])


def _describe_graph_path(
    *,
    path_nodes: list[dict[str, Any]],
    path_edges: list[dict[str, Any]],
) -> str:
    if not path_nodes:
        return "未找到有效路径。"
    if len(path_nodes) == 1:
        return f"直接命中节点 {path_nodes[0].get('label') or '未命名节点'}。"
    parts: list[str] = []
    for index, node in enumerate(path_nodes[:-1]):
        edge = path_edges[index] if index < len(path_edges) else {}
        next_node = path_nodes[index + 1]
        parts.append(
            f"{node.get('label') or node.get('id')} --{edge.get('label') or '关联'}--> {next_node.get('label') or next_node.get('id')}"
        )
    return "；".join(parts)


def _retrieve_graph_paths(
    *,
    graph: dict[str, Any],
    company_name: str,
    report_period: str,
    intent: str,
    limit: int = 6,
) -> dict[str, Any]:
    ranked_nodes = _rank_graph_nodes_for_intent(graph.get("nodes", []), graph.get("edges", []), intent)
    node_by_id = {
        str(node.get("id")): node
        for node in ranked_nodes
        if node.get("id")
    }
    adjacency, _ = _build_graph_edge_maps(graph.get("edges", []))
    company_node_id = _graph_node_id("company", company_name)
    period_node_id = _graph_node_id("period", report_period)
    query_terms = _expand_graph_query_terms(intent)
    focal_nodes = [
        node
        for node in ranked_nodes
        if node.get("type") not in {"company", "report_period"}
    ][:8]
    paths: list[dict[str, Any]] = []
    for node in focal_nodes:
        node_id = str(node.get("id") or "")
        candidate_paths: list[tuple[list[str], list[dict[str, Any]]]] = []
        company_path = _find_graph_path(adjacency=adjacency, start_id=company_node_id, target_id=node_id)
        if company_path[0]:
            candidate_paths.append(company_path)
        period_path = _find_graph_path(adjacency=adjacency, start_id=period_node_id, target_id=node_id)
        if period_path[0]:
            candidate_paths.append(period_path)
        if not candidate_paths:
            continue
        best_nodes, best_edges = max(
            candidate_paths,
            key=lambda item: (
                -len(item[0]),
                sum(int(node_by_id.get(path_node, {}).get("intent_score") or 0) for path_node in item[0]),
            ),
        )
        path_node_items = [node_by_id.get(path_node) for path_node in best_nodes if node_by_id.get(path_node)]
        if not path_node_items:
            continue
        path_score = sum(int(item.get("intent_score") or 0) for item in path_node_items)
        support_candidates = []
        predecessor_id = best_nodes[-2] if len(best_nodes) >= 2 else None
        for neighbor in adjacency.get(node_id, []):
            support_id = str(neighbor.get("node_id") or "")
            if not support_id or support_id == predecessor_id:
                continue
            support_node = node_by_id.get(support_id)
            if support_node is None:
                continue
            support_candidates.append((int(support_node.get("intent_score") or 0), support_node, neighbor))
        support_node = None
        support_edge = None
        if support_candidates:
            support_candidates.sort(key=lambda item: item[0], reverse=True)
            _, support_node, support_edge = support_candidates[0]
        path_summary = _describe_graph_path(path_nodes=path_node_items, path_edges=best_edges)
        if support_node is not None and support_edge is not None:
            path_summary += (
                f"；继续延展到 {support_node.get('label') or support_node.get('id')}"
                f"（{support_edge.get('label') or '支撑'}）"
            )
            path_score += int(support_node.get("intent_score") or 0)
        paths.append(
            {
                "target_id": node_id,
                "target_label": node.get("label"),
                "target_type": node.get("type"),
                "target_meta": node.get("meta") or {},
                "target_score": int(node.get("intent_score") or 0),
                "path_score": path_score,
                "path_nodes": path_node_items + ([support_node] if support_node is not None else []),
                "path_edges": best_edges + (
                    [{"source": node_id, "target": support_node.get("id"), "label": support_edge.get("label")}]
                    if support_node is not None and support_edge is not None
                    else []
                ),
                "path_summary": path_summary,
                "why": node.get("rank_explain"),
                "hit_terms": node.get("hit_terms", []),
            }
        )
    paths.sort(
        key=lambda item: (
            int(item.get("path_score") or 0),
            int(item.get("target_score") or 0),
            str(item.get("target_label") or ""),
        ),
        reverse=True,
    )
    top_paths = paths[:limit]
    evidence_count = sum(
        1
        for path in top_paths
        for node in path.get("path_nodes", [])
        if str((node or {}).get("type")) in {"document_artifact", "artifact_evidence", "research_report"}
    )
    temporal_nodes = [
        node
        for path in top_paths
        for node in path.get("path_nodes", [])
        if isinstance(node, dict) and str(node.get("type") or "") in _GRAPH_SIGNAL_NODE_TYPES
    ]
    latest_signal_date = max(
        (
            _graph_node_temporal_meta(node)[0]
            for node in temporal_nodes
            if _graph_node_temporal_meta(node)[0] is not None
        ),
        default=None,
    )
    freshness_status, freshness_label = _describe_external_signal_freshness(
        latest_signal_date.isoformat() if latest_signal_date is not None else None
    )
    signal_event_node = next(
        (
            node
            for node in temporal_nodes
            if str(node.get("type") or "") == "signal_event"
        ),
        None,
    )
    signal_timeline_node = next(
        (
            node
            for node in temporal_nodes
            if str(node.get("type") or "") == "signal_timeline"
        ),
        None,
    )
    signal_meta = (signal_timeline_node or signal_event_node or {}).get("meta") or {}
    summary = {
        "intent_dimension": _classify_intent(intent),
        "query_terms": query_terms,
        "query_term_count": len(query_terms),
        "candidate_count": len(ranked_nodes),
        "focal_count": len(focal_nodes),
        "path_count": len(top_paths),
        "evidence_count": evidence_count,
        "signal_node_count": len(temporal_nodes),
        "freshness_status": freshness_status,
        "freshness_label": (
            freshness_label if temporal_nodes else "图谱内暂无时序信号"
        ),
        "latest_signal_time": signal_meta.get("latest_event_time"),
        "latest_signal_headline": (
            signal_event_node.get("label")
            if isinstance(signal_event_node, dict)
            else None
        ),
        "time_window_days": int(signal_meta.get("window_days") or 0),
        "signal_count": int(signal_meta.get("signal_count") or 0),
        "latest_heat": int(signal_meta.get("latest_heat") or 0),
        "external_heat": int(signal_meta.get("external_heat") or 0),
        "max_momentum": int(signal_meta.get("momentum") or 0),
        "active_days": int(signal_meta.get("active_days") or 0),
        "top_hit_terms": _dedupe_terms(
            [term for path in top_paths for term in path.get("hit_terms", [])]
        )[:6],
    }
    return {
        "summary": summary,
        "ranked_nodes": ranked_nodes,
        "focal_nodes": focal_nodes,
        "paths": top_paths,
    }


def _describe_graph_focus_node(node: dict[str, Any], workspace: dict[str, Any]) -> str:
    node_type = str(node.get("type"))
    meta = node.get("meta") or {}
    if node_type == "risk_label":
        return "当前体检中命中的核心风险标签之一。"
    if node_type == "alert":
        return f"主动预警状态：{meta.get('status') or 'unknown'}。"
    if node_type == "task":
        return f"整改任务优先级 {meta.get('priority') or '-'}，状态 {meta.get('status') or '-'}。"
    if node_type == "research_report":
        return f"研报核验已就绪，预测项 {meta.get('forecast_count') or 0} 条。"
    if node_type == "document_artifact":
        return f"文档升级产物：{meta.get('summary') or '已生成可消费结构'}。"
    if node_type == "artifact_evidence":
        return "可以继续下钻到证据页查看字段和页码。"
    if node_type == "execution_stream":
        return f"执行流状态：{meta.get('status') or 'tracked'}。"
    if node_type == "signal_event":
        return (
            f"最新外部信号：{meta.get('signal_status') or '事件更新'}，"
            f"{meta.get('freshness_label') or '时效待校准'}。"
        )
    if node_type == "signal_timeline":
        return (
            f"近 {meta.get('window_days') or 7} 日累计热度 {meta.get('external_heat') or 0}，"
            f"动量 {meta.get('momentum') or 0}。"
        )
    if node_type == "subindustry_signal":
        return (
            f"{meta.get('subindustry') or workspace['score_summary']['subindustry']} 板块近窗热度"
            f" {meta.get('latest_heat') or 0}，动量 {meta.get('momentum') or 0}。"
        )
    if node_type == "watchboard":
        return f"监测板持续跟踪，新增预警 {meta.get('new_alerts') or 0} 条。"
    if node_type == "company":
        return f"总分 {workspace['score_summary']['total_score']}，等级 {workspace['score_summary']['grade']}。"
    return "该节点参与当前查询意图的传导路径。"


def _classify_intent(intent: str) -> str:
    """Classify intent into a primary dimension for varied path generation."""
    price_kw = ["价格", "成本", "涨价", "跌价", "碳酸锂", "锂", "铜", "原材料"]
    risk_kw = ["风险", "断供", "停产", "下滑", "压力", "危机"]
    growth_kw = ["增长", "营收", "市场", "扩张", "需求", "份额"]
    cash_kw = ["现金", "流动", "偿债", "应收", "账期", "融资"]
    supply_kw = ["供应链", "上游", "下游", "传导", "产业链"]
    for kw in price_kw:
        if kw in intent:
            return "price"
    for kw in cash_kw:
        if kw in intent:
            return "cash"
    for kw in growth_kw:
        if kw in intent:
            return "growth"
    for kw in supply_kw:
        if kw in intent:
            return "supply"
    for kw in risk_kw:
        if kw in intent:
            return "risk"
    return "risk"


_INTENT_DIMENSION_DESC = {
    "price": ("成本传导维度", "识别关键原材料价格波动对毛利率的压缩路径。"),
    "cash": ("现金流维度", "追踪应收账款、库存占用对经营性现金流净额的拖拽。"),
    "growth": ("成长性维度", "评估营收增速驱动力与市场份额变化的可持续性。"),
    "supply": ("供应链维度", "上游集中度与下游议价能力对利润的双向挤压效应。"),
    "risk": ("风险暴露维度", "聚焦已命中的风险标签，建立从识别到行动的闭环。"),
}

_GRAPH_SIGNAL_NODE_TYPES = {"signal_event", "signal_timeline", "subindustry_signal"}
_GRAPH_REALTIME_TERMS = ("实时", "最新", "最近", "时效", "异动", "窗口", "时间", "时序", "今日", "本周")


def _build_graph_query_inference_path(
    *,
    company_name: str,
    report_period: str,
    intent: str,
    focal_nodes: list[dict[str, Any]],
    retrieved_paths: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    dim = _classify_intent(intent)
    dim_title, dim_detail = _INTENT_DIMENSION_DESC.get(dim, _INTENT_DIMENSION_DESC["risk"])
    score = workspace.get("score_summary", {})
    freshness_note = ""
    if retrieval_summary.get("latest_signal_headline"):
        freshness_note = (
            f" 最近信号：{retrieval_summary.get('latest_signal_headline')}，"
            f"{retrieval_summary.get('freshness_label') or '时效待校准'}。"
        )
    steps: list[dict[str, Any]] = [
        {
            "step": 1,
            "title": company_name,
            "detail": f"{report_period} | 总分 {score.get('total_score', '-')} / 等级 {score.get('grade', '-')}。",
            "type": "company",
        },
        {
            "step": 2,
            "title": dim_title,
            "detail": (
                f"{dim_detail} 检索词 {retrieval_summary.get('query_term_count', 0)} 个，"
                f"命中路径 {retrieval_summary.get('path_count', 0)} 条。{freshness_note}"
            ),
            "type": "intent",
        },
    ]
    graph_paths = retrieved_paths[:3]
    for index, path in enumerate(graph_paths, start=3):
        target_label = path.get("target_label") or f"命中节点 {index - 2}"
        detail = (
            f"{path.get('path_summary') or '已生成图谱路径'} "
            f"检索说明：{path.get('why') or '无'}。"
        )
        steps.append(
            {
                "step": index,
                "title": target_label,
                "detail": detail,
                "type": path.get("target_type"),
            }
        )
    if not graph_paths:
        for index, node in enumerate(focal_nodes[:3], start=3):
            steps.append(
                {
                    "step": index,
                    "title": node["label"],
                    "detail": _describe_graph_focus_node(node, workspace),
                    "type": node.get("type"),
                }
            )
    steps.append(
        {
            "step": len(steps) + 1,
            "title": "动作收口",
            "detail": (
                f"围绕「{intent}」把风险、任务、证据和执行流压成可操作结论。"
                f" 当前回收到 {retrieval_summary.get('evidence_count', 0)} 个证据型节点，"
                f"时序信号 {retrieval_summary.get('signal_count', 0)} 条。"
            ),
            "type": "action",
        }
    )
    return steps


def _build_graph_query_phase_track(
    *,
    company_name: str,
    intent: str,
    workspace: dict[str, Any],
    inference_path: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_groups = workspace.get("evidence_groups") or []
    return [
        {
            "phase": "查询压缩",
            "status": "done",
            "headline": intent[:22] + ("..." if len(intent) > 22 else ""),
            "metric": f"{retrieval_summary.get('query_term_count', 0)} terms",
        },
        {
            "phase": "时序校准",
            "status": "done",
            "headline": retrieval_summary.get("freshness_label") or "时序信号待补齐",
            "metric": (
                retrieval_summary.get("latest_signal_time")
                or f"{retrieval_summary.get('time_window_days', 0)} day window"
            ),
        },
        {
            "phase": "图检索命中",
            "status": "done",
            "headline": company_name,
            "metric": f"{retrieval_summary.get('focal_count', 0)} nodes",
        },
        {
            "phase": "路径传导",
            "status": "done",
            "headline": "影响链已展开",
            "metric": f"{retrieval_summary.get('path_count', 0)} paths",
        },
        {
            "phase": "证据挂接",
            "status": "active",
            "headline": "证据与动作入口",
            "metric": f"{max(len(evidence_groups), retrieval_summary.get('evidence_count', 0))} sources",
        },
    ]


def _build_graph_query_signal_stream(
    *,
    focal_nodes: list[dict[str, Any]],
    retrieved_paths: list[dict[str, Any]],
    workspace: dict[str, Any],
    graph_node_count: int,
    retrieval_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in retrieved_paths[:4]:
        target_type = str(path.get("target_type") or "")
        target_meta = path.get("target_meta") or {}
        if target_type == "signal_event":
            items.append(
                {
                    "label": "最新事件",
                    "value": path.get("target_label") or target_meta.get("signal_status") or "外部信号",
                    "tone": "accent"
                    if target_meta.get("freshness_status") in {"fresh", "recent", "warm"}
                    else "warning",
                }
            )
            continue
        if target_type == "signal_timeline":
            items.append(
                {
                    "label": f"近 {target_meta.get('window_days') or 7} 日热度",
                    "value": (
                        f"{target_meta.get('signal_count') or 0} 条 · 动量"
                        f" {target_meta.get('momentum') or 0}"
                    ),
                    "tone": "accent",
                }
            )
            continue
        if target_type == "subindustry_signal":
            items.append(
                {
                    "label": "板块共振",
                    "value": (
                        f"{target_meta.get('subindustry') or path.get('target_label')} · 动量"
                        f" {target_meta.get('momentum') or 0}"
                    ),
                    "tone": "success",
                }
            )
            continue
        items.append(
            {
                "label": path.get("target_label", "路径"),
                "value": f"score {path.get('path_score', 0)}",
                "tone": "risk"
                if path.get("target_type") in {"risk_label", "alert", "task"}
                else "accent",
            }
        )
    if not items:
        items = [
            {
                "label": node.get("label", "节点"),
                "value": node.get("type", "focus"),
                "tone": "risk"
                if node.get("type") in {"risk_label", "alert", "task"}
                else "accent",
            }
            for node in focal_nodes[:4]
        ]
    items.extend(
        [
            {
                "label": "信号时效",
                "value": retrieval_summary.get("freshness_label") or "待校准",
                "tone": "success"
                if retrieval_summary.get("freshness_status") in {"fresh", "recent", "warm"}
                else "warning",
            },
            {
                "label": "图谱节点",
                "value": str(graph_node_count),
                "tone": "success",
            },
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
                "tone": "risk",
            },
        ]
    )
    return items[:6]


def _build_graph_query_live_frames(
    *,
    focal_nodes: list[dict[str, Any]],
    inference_path: list[dict[str, Any]],
    phase_track: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    support_node_ids = [node.get("id") for node in focal_nodes[:3] if node.get("id")]
    for index, item in enumerate(inference_path):
        phase = phase_track[min(index, len(phase_track) - 1)] if phase_track else {}
        active_nodes = [f"path-{item['step']}"]
        if index > 0:
            active_nodes.append(f"path-{inference_path[index - 1]['step']}")
        if support_node_ids:
            active_nodes.append(support_node_ids[index % len(support_node_ids)])
        frames.append(
            {
                "frame": index + 1,
                "headline": item["title"],
                "detail": item["detail"],
                "active_nodes": active_nodes,
                "active_links": [f"link-{item['step']}"],
                "phase": phase.get("phase"),
                "metric": phase.get("metric"),
                "signal": signal_stream[index % len(signal_stream)] if signal_stream else None,
                "intensity": min(100, 52 + index * 13),
            }
        )
    if not frames:
        frames.append(
            {
                "frame": 1,
                "headline": "等待图谱推理",
                "detail": "当前没有可播放的路径阶段。",
                "active_nodes": support_node_ids,
                "active_links": [],
                "phase": None,
                "metric": None,
                "signal": signal_stream[0] if signal_stream else None,
                "intensity": 0,
            }
        )
    return frames


def _build_graph_signal_tape(
    *,
    inference_path: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, item in enumerate(inference_path):
        signal = signal_stream[index % len(signal_stream)] if signal_stream else {}
        tape.append(
            {
                "step": item.get("step", index + 1),
                "label": item.get("title") or f"阶段 {index + 1}",
                "value": signal.get("value") or signal.get("label") or "等待信号",
                "tone": signal.get("tone") or "accent",
                "intensity": min(100, 30 + index * 18),
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待推理",
                "value": "等待信号",
                "tone": "accent",
                "intensity": 0,
            }
        )
    return tape


def _build_graph_command_surface(
    *,
    company_name: str,
    intent: str,
    focal_nodes: list[dict[str, Any]],
    inference_path: list[dict[str, Any]],
    phase_track: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    focus = focal_nodes[0] if focal_nodes else {}
    latest_phase = phase_track[-1] if phase_track else {}
    dominant_signal = signal_stream[0] if signal_stream else {}
    return {
        "title": "关键证据链路",
        "intent": intent,
        "focus_label": focus.get("label") or "等待焦点节点",
        "focus_type": focus.get("type") or "graph",
        "headline": latest_phase.get("headline") or "等待图谱推理",
        "metric": latest_phase.get("metric") or "GRAPH",
        "intensity": min(100, 42 + len(inference_path) * 11),
        "route_count": len(inference_path),
        "watch_items": [
            {
                "label": "信号时效",
                "value": retrieval_summary.get("freshness_label") or "待校准",
            },
            {
                "label": "7日信号",
                "value": str(retrieval_summary.get("signal_count") or 0),
            },
            {
                "label": "热度动量",
                "value": str(retrieval_summary.get("max_momentum") or 0),
            },
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
            },
        ],
        "dominant_signal": {
            "label": dominant_signal.get("label") or "等待信号",
            "value": dominant_signal.get("value") or dominant_signal.get("label") or "N/A",
            "tone": dominant_signal.get("tone") or "accent",
        },
    }


def _build_graph_route_bands(
    *,
    inference_path: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bands: list[dict[str, Any]] = []
    for index, item in enumerate(inference_path):
        signal = signal_stream[index % len(signal_stream)] if signal_stream else {}
        bands.append(
            {
                "step": item.get("step", index + 1),
                "headline": item.get("title") or f"阶段 {index + 1}",
                "detail": item.get("detail") or "等待路径说明",
                "tone": signal.get("tone") or "accent",
                "signal": signal.get("value") or signal.get("label") or "等待信号",
                "intensity": min(100, 36 + index * 17),
            }
        )
    if not bands:
        bands.append(
            {
                "step": 1,
                "headline": "等待推理",
                "detail": "图谱路径生成后会出现在这里。",
                "tone": "accent",
                "signal": "等待信号",
                "intensity": 0,
            }
        )
    return bands


def _build_graph_query_evidence_navigation(workspace: dict[str, Any]) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    for item in workspace["document_upgrades"]["items"]:
        evidence_navigation = item.get("evidence_navigation") or {}
        links.extend(evidence_navigation.get("links", [])[:2])
    for run in workspace["recent_runs"]["items"][:2]:
        links.append(
            {
                "label": "查看分析运行",
                "path": f"/workspace?run={run['run_id']}",
                "query": {"company": workspace["company_name"]},
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        key = (str(link.get("label")), str(link.get("path")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return {
        "links": deduped[:6],
        "primary_route": deduped[0] if deduped else None,
    }


def _build_verify_command_surface(
    *,
    company: dict[str, Any],
    research_meta: dict[str, Any],
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    match_count = sum(1 for item in claim_cards if item["status"] == "match")
    mismatch_count = sum(1 for item in claim_cards if item["status"] == "mismatch")
    dominant = next((item for item in claim_cards if item["status"] != "match"), None) or (claim_cards[0] if claim_cards else None)
    return {
        "title": f"{company['company_name']} 研报核验",
        "headline": dominant["label"] if dominant else research_meta["title"],
        "metric": f"{match_count} 匹配 / {mismatch_count} 偏差",
        "intensity": min(100, 34 + mismatch_count * 22 + match_count * 8),
        "institution": research_meta.get("source_name") or "未披露",
        "watch_items": [
            {"label": "匹配", "value": str(match_count)},
            {"label": "偏差", "value": str(mismatch_count)},
            {"label": "预测", "value": str(len(forecast_cards))},
        ],
        "dominant_signal": {
            "label": "当前核验焦点",
            "value": dominant["status"] if dominant else "等待核验",
            "tone": "risk" if dominant and dominant["status"] == "mismatch" else "success",
        },
    }


def _build_verify_delta_tape(
    *,
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, card in enumerate(claim_cards[:4]):
        status = card["status"]
        tone = "success" if status == "match" else "risk" if status == "mismatch" else "warning"
        intensity = 30 if status == "match" else 86 if status == "mismatch" else 58
        tape.append(
            {
                "step": index + 1,
                "label": card["metric_key"],
                "value": card["label"],
                "tone": tone,
                "intensity": intensity,
            }
        )
    if forecast_cards:
        tape.append(
            {
                "step": len(tape) + 1,
                "label": "预测",
                "value": f"{len(forecast_cards)} 个年度",
                "tone": "accent",
                "intensity": 44,
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待核验",
                "value": "暂无观点卡",
                "tone": "accent",
                "intensity": 0,
            }
        )
    return tape


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
                "route": {"path": "/risk", "query": {"company": item["company_name"]}},
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
                "route": {"path": "/workspace", "query": {"company": item["company_name"]}},
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


def _graph_node_id(prefix: str, value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-:\u4e00-\u9fff]+", "_", value).strip("_")
    return f"{prefix}:{safe}"


def _dedupe_graph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        node_id = node["id"]
        if node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(node)
    return deduped


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


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "record_count": 0,
            "company_count": 0,
            "manifest_path": str(path),
        }
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    records = payload.get("records", [])
    return {
        "available": True,
        "record_count": payload.get("record_count", len(records)),
        "company_count": len({record.get("security_code") for record in records if record.get("security_code")}),
        "generated_at": payload.get("generated_at"),
        "manifest_path": str(path),
    }


def _resolve_universe_root(settings: Settings) -> Path:
    configured_root = getattr(settings, "universe_data_path", None)
    if configured_root:
        return Path(configured_root)

    official_root = Path(getattr(settings, "official_data_path", "data/raw/official"))
    if official_root.name == "official" and official_root.parent.name == "raw":
        return official_root.parent.parent / "universe"
    if official_root.name == "raw":
        return official_root.parent / "universe"
    return official_root.parent / "universe"


def _build_admin_quality_overview(settings: Settings, preferred_period: str | None) -> dict[str, Any]:
    universe_root = _resolve_universe_root(settings)
    company_pool = _load_json_records(universe_root / "formal_company_pool.json")
    raw_reports = _load_manifest_records(settings.official_data_path / "manifests" / "periodic_reports_manifest.json")
    research_reports = _load_manifest_records(
        settings.official_data_path / "manifests" / "research_reports_manifest.json"
    )
    bronze_reports = _load_manifest_records(
        settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    )
    silver_records = _load_manifest_records(
        settings.silver_data_path / "manifests" / "financial_metrics_manifest.json"
    )

    raw_by_company = _index_records_by_company(raw_reports)
    research_by_company = _index_records_by_company(research_reports)
    bronze_by_company = _index_records_by_company(bronze_reports)
    silver_by_company = _index_records_by_company(silver_records)

    company_rows: list[dict[str, Any]] = []
    for company in company_pool:
        company_name = company["company_name"]
        raw_items = raw_by_company.get(company_name, [])
        bronze_items = bronze_by_company.get(company_name, [])
        silver_items = silver_by_company.get(company_name, [])
        research_items = research_by_company.get(company_name, [])
        silver_periods = sorted(
            {
                item.get("report_period")
                for item in silver_items
                if item.get("report_period")
            },
            key=_period_order_key,
            reverse=True,
        )
        latest_period = silver_periods[0] if silver_periods else None
        preferred_period_ready = bool(preferred_period and preferred_period in silver_periods)
        issues: list[str] = []
        if not raw_items:
            issues.append("缺定期报告")
        if raw_items and not bronze_items:
            issues.append("缺页级解析")
        if bronze_items and not silver_items:
            issues.append("缺结构化指标")
        if not research_items:
            issues.append("缺研报")
        if preferred_period and not preferred_period_ready:
            issues.append("缺主周期")
        company_rows.append(
            {
                "company_name": company_name,
                "subindustry": company.get("subindustry", "未分类"),
                "raw_report_count": len(raw_items),
                "bronze_report_count": len(bronze_items),
                "silver_record_count": len(silver_items),
                "research_report_count": len(research_items),
                "latest_silver_period": latest_period,
                "preferred_period_ready": preferred_period_ready,
                "issues": issues,
            }
        )

    issue_buckets = [
        {
            "code": issue_code,
            "label": issue_code,
            "count": sum(1 for row in company_rows if issue_code in row["issues"]),
            "companies": [row["company_name"] for row in company_rows if issue_code in row["issues"]][:12],
        }
        for issue_code in ("缺主周期", "缺研报", "缺定期报告", "缺页级解析", "缺结构化指标")
    ]
    issue_buckets = [item for item in issue_buckets if item["count"] > 0]
    company_rows.sort(
        key=lambda item: (
            len(item["issues"]) == 0,
            len(item["issues"]),
            not item["preferred_period_ready"],
            item["company_name"],
        )
    )
    return {
        "preferred_period": preferred_period,
        "coverage": {
            "pool_companies": len(company_rows),
            "preferred_period_ready": sum(1 for row in company_rows if row["preferred_period_ready"]),
            "research_ready": sum(1 for row in company_rows if row["research_report_count"] > 0),
            "raw_ready": sum(1 for row in company_rows if row["raw_report_count"] > 0),
            "bronze_ready": sum(1 for row in company_rows if row["bronze_report_count"] > 0),
            "silver_ready": sum(1 for row in company_rows if row["silver_record_count"] > 0),
        },
        "issue_buckets": issue_buckets,
        "companies": company_rows,
    }


def _build_delivery_readiness(
    *,
    quality_overview: dict[str, Any],
    document_pipeline: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    coverage = quality_overview.get("coverage", {})
    companies = quality_overview.get("companies", [])
    issue_buckets = quality_overview.get("issue_buckets", [])
    pool_companies = coverage.get("pool_companies", 0) or 0
    preferred_period_ready = coverage.get("preferred_period_ready", 0) or 0
    silver_ready = coverage.get("silver_ready", 0) or 0
    research_ready = coverage.get("research_ready", 0) or 0
    contract_audit = document_pipeline.get("cell_trace", {}).get("contract_audit", {})
    contract_total = contract_audit.get("total", 0) or 0
    contract_ready = contract_audit.get("ready", 0) or 0
    contract_invalid = contract_audit.get("invalid", 0) or 0
    contract_missing = contract_audit.get("missing", 0) or 0
    blocker_companies = [row for row in companies if row.get("issues")]
    ready_companies = [row for row in companies if not row.get("issues")]

    coverage_ratio = round((preferred_period_ready / pool_companies) * 100) if pool_companies else 0
    silver_ratio = round((silver_ready / pool_companies) * 100) if pool_companies else 0
    research_ratio = round((research_ready / pool_companies) * 100) if pool_companies else 0
    contract_ratio = round((contract_ready / contract_total) * 100) if contract_total else 100

    if pool_companies == 0:
        stage = "bootstrapping"
    elif not ready_companies:
        stage = "blocked"
    elif contract_invalid > 0 or contract_missing > 0:
        stage = "hardening"
    elif coverage_ratio >= 85 and silver_ratio >= 85 and research_ratio >= 70 and contract_ratio >= 85:
        stage = "ready"
    else:
        stage = "hardening"

    top_blockers = sorted(issue_buckets, key=lambda item: item.get("count", 0), reverse=True)[:3]
    priority_actions = [
        {
            "title": item["label"],
            "summary": f"{item['count']} 家公司受阻，优先处理该链路。",
            "companies": item.get("companies", [])[:5],
        }
        for item in top_blockers
    ]
    if contract_invalid or contract_missing:
        priority_actions.insert(
            0,
            {
                "title": "OCR Contract 质检",
                "summary": f"{contract_ready}/{contract_total or 0} 份 contract 达标，{contract_missing} 份缺失，{contract_invalid} 份不合格。",
                "companies": [item.get("company_name") for item in contract_audit.get("samples", []) if item.get("status") != "ready"][:5],
            },
        )
    return {
        "stage": stage,
        "preferred_period": health.get("preferred_period"),
        "ready_company_count": len(ready_companies),
        "blocked_company_count": len(blocker_companies),
        "coverage_ratio": coverage_ratio,
        "silver_ratio": silver_ratio,
        "research_ratio": research_ratio,
        "contract_ratio": contract_ratio,
        "priority_actions": priority_actions[:4],
        "summary": {
            "pool_companies": pool_companies,
            "preferred_period_ready": preferred_period_ready,
            "silver_ready": silver_ready,
            "research_ready": research_ready,
            "contract_ready": contract_ready,
            "contract_total": contract_total,
            "contract_invalid": contract_invalid,
            "contract_missing": contract_missing,
        },
    }


def _build_runtime_readiness(settings: Settings) -> dict[str, Any]:
    postgres_dsn = getattr(settings, "postgres_dsn", "")
    cors_allowed_origins = tuple(getattr(settings, "cors_allowed_origins", ()) or ())
    ocr_runtime = _settings_ocr_runtime(settings)
    ocr_assets_path = Path(ocr_runtime["assets_path"])
    ocr_ready = bool(ocr_runtime["runtime_enabled"]) and ocr_assets_path.exists()
    checks = [
        probe_llm_runtime(settings),
        {
            "key": "ocr",
            "label": "OCR 标准引擎",
            "status": "ready" if ocr_ready else "blocked",
            "summary": "PaddleOCR-VL 标准链路已接通，可处理扫描件与复杂报表。"
            if ocr_ready
            else "OCR 标准链路未接通，扫描件与复杂表格解析不满足交付标准。",
            "detail": f"{ocr_runtime['provider']} / {ocr_runtime['model']} @ {ocr_assets_path}",
        },
        {
            "key": "database",
            "label": "数据库连接",
            "status": "ready" if bool(postgres_dsn) else "blocked",
            "summary": "会话、登录与运行记录依赖 PostgreSQL。"
            if postgres_dsn
            else "未配置 PostgreSQL DSN，登录与会话不可用。",
            "detail": postgres_dsn.split("@")[-1] if postgres_dsn else "missing",
        },
        {
            "key": "official_data",
            "label": "原始数据目录",
            "status": "ready" if settings.official_data_path.exists() else "blocked",
            "summary": "原始 PDF / 研报目录存在。"
            if settings.official_data_path.exists()
            else "原始数据目录不存在，数据抓取与核验链路会中断。",
            "detail": str(settings.official_data_path),
        },
        {
            "key": "silver_data",
            "label": "银层目录",
            "status": "ready" if settings.silver_data_path.exists() else "blocked",
            "summary": "结构化指标目录存在。"
            if settings.silver_data_path.exists()
            else "银层目录不存在，评分与对比能力不可交付。",
            "detail": str(settings.silver_data_path),
        },
        {
            "key": "cors",
            "label": "前端跨域",
            "status": "ready" if len(cors_allowed_origins) > 0 else "blocked",
            "summary": f"已配置 {len(cors_allowed_origins)} 个前端来源。 "
            if cors_allowed_origins
            else "未配置任何前端来源，浏览器访问会失败。",
            "detail": ", ".join(cors_allowed_origins) if cors_allowed_origins else "missing",
        },
    ]
    blocked = sum(1 for item in checks if item["status"] == "blocked")
    return {
        "status": "ready" if blocked == 0 else "blocked",
        "blocked_count": blocked,
        "checks": checks,
    }


def _build_acceptance_checklist(
    *,
    health: dict[str, Any],
    delivery_readiness: dict[str, Any],
    runtime_readiness: dict[str, Any],
    document_pipeline: dict[str, Any],
) -> dict[str, Any]:
    contract_audit = document_pipeline.get("cell_trace", {}).get("contract_audit", {})
    items = [
        {
            "key": "frontend",
            "label": "前端入口可访问",
            "status": "pass",
            "detail": "打开 http://127.0.0.1:8080 并完成登录、工作台、运营保障中心可见性检查。",
        },
        {
            "key": "api",
            "label": "API 健康检查",
            "status": "pass" if health.get("status") == "ok" else "blocked",
            "detail": "访问 http://127.0.0.1:8000/api/v1/healthz，确认 status=ok。",
        },
        {
            "key": "runtime",
            "label": "运行时依赖齐备",
            "status": "pass" if runtime_readiness.get("status") == "ready" else "blocked",
            "detail": f"当前阻断项 {runtime_readiness.get('blocked_count', 0)} 个，需全部清零。",
        },
        {
            "key": "delivery",
            "label": "系统就绪度达标",
            "status": "pass" if delivery_readiness.get("stage") == "ready" else "blocked",
            "detail": f"当前阶段 {delivery_readiness.get('stage')}，稳定可用公司数 {delivery_readiness.get('ready_company_count', 0)}。",
        },
        {
            "key": "ocr_contract",
            "label": "OCR Contract 质检通过",
            "status": "pass" if contract_audit.get("status") == "ready" else "blocked",
            "detail": f"当前达标 {contract_audit.get('ready', 0)}/{contract_audit.get('total', 0)}，缺失 {contract_audit.get('missing', 0)}，不合格 {contract_audit.get('invalid', 0)}。",
        },
    ]
    passed = sum(1 for item in items if item["status"] == "pass")
    return {
        "status": "ready" if passed == len(items) else "blocked",
        "passed": passed,
        "total": len(items),
        "items": items,
    }


def _delivery_stage_label(stage: str | None) -> str:
    mapping = {
        "bootstrapping": "启动期",
        "hardening": "加固期",
        "blocked": "阻断",
        "ready": "就绪",
    }
    return mapping.get(stage or "", stage or "-")


def _status_label(status: str | None) -> str:
    mapping = {
        "ready": "就绪",
        "blocked": "阻断",
        "pass": "通过",
        "completed": "已完成",
        "pending": "待执行",
        "invalid": "不合格",
        "missing": "缺失",
        "queued": "待启动",
        "in_progress": "处理中",
        "done": "已完成",
        "new": "新增",
        "dispatched": "已派发",
        "resolved": "已闭环",
        "dismissed": "已忽略",
        "idle": "未启动",
        "tracked": "已纳管",
        "active": "执行中",
    }
    return mapping.get(status or "", status or "-")


def _bus_type_label(bus_type: str | None) -> str:
    mapping = {
        "task": "任务推进",
        "alert": "预警处置",
        "watchboard": "重点监测",
        "analysis_run": "分析执行",
        "watchboard_scan": "监测扫描",
        "document_pipeline": "文档工序",
        "document_pipeline_run": "整改运行",
        "stress_run": "压力推演",
        "graph_run": "图谱演算",
        "vision_run": "多模态核验",
    }
    return mapping.get(bus_type or "", bus_type or "-")


def _index_records_by_company(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        company_name = record.get("company_name")
        if not company_name:
            continue
        indexed.setdefault(company_name, []).append(record)
    return indexed


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload.get("records", [])


def _period_order_key(period: str | None) -> tuple[int, int]:
    if not period:
        return (0, 0)
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|FY)", period)
    if match is None:
        return (0, 0)
    suffix_rank = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
    return (int(match.group(1)), suffix_rank[match.group(2)])


def _build_admin_job_catalog() -> list[dict[str, Any]]:
    return [
        {
            "job_id": "fetch_real_data",
            "title": "抓取真实数据",
            "description": "从交易所与研报源抓取原始公告、研报详情页与补源快照。",
            "command": "ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "raw",
        },
        {
            "job_id": "parse_official_reports",
            "title": "解析官方报告",
            "description": "把 PDF 和原始页面解析成页级文本与 chunk。",
            "command": "ops-pilot-parse-official-reports --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "bronze",
        },
        {
            "job_id": "build_silver_metrics",
            "title": "构建结构化指标",
            "description": "从 bronze 结果抽取财务指标、事件指标和证据引用。",
            "command": "ops-pilot-build-silver-metrics --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "silver",
        },
        {
            "job_id": "run_tests",
            "title": "运行系统回归",
            "description": "执行单元测试并验证核心业务链路可用。",
            "command": "python -m unittest discover -s tests -t .",
            "output_stage": "qa",
        },
    ]


def _build_document_pipeline_overview(
    data_status: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    bronze_count = data_status.get("bronze_periodic_reports", {}).get("record_count", 0)
    silver_count = data_status.get("silver_financial_metrics", {}).get("record_count", 0)
    periodic_count = data_status.get("periodic_reports", {}).get("record_count", 0)
    jobs_manifest = _load_document_pipeline_job_manifest(settings)
    records = jobs_manifest["records"]
    cross_page_completed = sum(
        1 for item in records if item["stage"] == "cross_page_merge" and item["status"] == "completed"
    )
    title_completed = sum(
        1 for item in records if item["stage"] == "title_hierarchy" and item["status"] == "completed"
    )
    ocr_runtime = _settings_ocr_runtime(settings)
    cell_completed = sum(
        1 for item in records if item["stage"] == "cell_trace" and item["status"] == "completed"
    )
    contract_audit = _build_ocr_cell_trace_contract_audit(settings, records)
    return {
        "layout_engine": ocr_runtime["layout_engine"],
        "ocr_engine": f"{ocr_runtime['provider']} / {ocr_runtime['model']}",
        "ocr_runtime_enabled": ocr_runtime["runtime_enabled"],
        "cross_page_merge": {
            "enabled": True,
            "status": f"completed {cross_page_completed}",
            "summary": "已支持基于真实页文本生成跨页续写与续表候选清单。",
        },
        "title_hierarchy": {
            "enabled": True,
            "status": f"completed {title_completed}",
            "summary": "已支持从真实页块中恢复标题层级，用于目录导航和段落定位。",
        },
        "cell_trace": {
            "enabled": True,
            "status": f"completed {cell_completed}",
            "completed": cell_completed,
            "summary": "统一文档理解链路：标准 OCR 引擎产出表格片段与单元格证据链。",
            "contract_audit": contract_audit,
        },
        "coverage": [
            {"label": "原始文档", "value": periodic_count, "unit": "份"},
            {"label": "页级解析", "value": bronze_count, "unit": "条"},
            {"label": "结构化指标", "value": silver_count, "unit": "条"},
        ],
    }


def _document_stage_label(stage: str) -> str:
    return {
        "cross_page_merge": "跨页拼接",
        "title_hierarchy": "标题层级",
        "cell_trace": "单元格溯源",
    }.get(stage, stage)


def _build_ocr_cell_trace_contract_audit(
    settings: Settings, records: list[dict[str, Any]]
) -> dict[str, Any]:
    latest_jobs: dict[str, dict[str, Any]] = {}
    for item in records:
        if item.get("stage") != "cell_trace":
            continue
        report_id = item.get("report_id")
        if not report_id:
            continue
        current = latest_jobs.get(report_id)
        current_stamp = (
            (current.get("completed_at") or current.get("created_at")) if current else ""
        )
        candidate_stamp = item.get("completed_at") or item.get("created_at") or ""
        if current is None or candidate_stamp >= current_stamp:
            latest_jobs[report_id] = item

    summary = {"ready": 0, "invalid": 0, "missing": 0}
    samples: list[dict[str, Any]] = []
    for job in latest_jobs.values():
        ocr_artifact_path = _standard_ocr_artifact_path(settings, job)
        if not ocr_artifact_path.exists():
            status = "missing"
            detail = "缺少标准 OCR contract 产物"
        else:
            payload = _load_json_if_possible(ocr_artifact_path)
            if payload and _is_valid_standard_ocr_tables(payload.get("tables", [])) and _is_valid_standard_ocr_cells(payload.get("cells", [])):
                status = "ready"
                detail = "contract 合法"
            else:
                status = "invalid"
                detail = "contract 存在但字段不合法"
        summary[status] += 1
        if len(samples) < 6:
            samples.append(
                {
                    "report_id": job.get("report_id"),
                    "company_name": job.get("company_name"),
                    "report_period": job.get("report_period"),
                    "status": status,
                    "detail": detail,
                    "path": str(ocr_artifact_path),
                }
            )
    total = sum(summary.values())
    return {
        "total": total,
        "ready": summary["ready"],
        "invalid": summary["invalid"],
        "missing": summary["missing"],
        "status": "ready" if total == 0 or (summary["invalid"] == 0 and summary["missing"] == 0) else "blocked",
        "samples": samples,
    }


def _resolve_document_contract_status(settings: Settings, item: dict[str, Any]) -> str | None:
    if item.get("stage") != "cell_trace":
        return None
    ocr_artifact_path = _standard_ocr_artifact_path(settings, item)
    if not ocr_artifact_path.exists():
        return "missing"
    payload = _load_json_if_possible(ocr_artifact_path)
    if payload and _is_valid_standard_ocr_tables(payload.get("tables", [])) and _is_valid_standard_ocr_cells(payload.get("cells", [])):
        return "ready"
    return "invalid"


def _summarize_contract_statuses(
    records: list[dict[str, Any]], *, settings: Settings, stage: str
) -> dict[str, int]:
    if stage != "cell_trace":
        return {"ready": 0, "invalid": 0, "missing": 0}
    summary = {"ready": 0, "invalid": 0, "missing": 0}
    for item in records:
        if item.get("stage") != "cell_trace":
            continue
        status = _resolve_document_contract_status(settings, item)
        if status in summary:
            summary[status] += 1
    return summary


def _build_document_pipeline_execution_feedback(
    *,
    stage: str,
    contract_status: str | None,
    processed: int,
    before_summary: dict[str, int],
    after_summary: dict[str, int],
) -> dict[str, Any]:
    fixed_count = 0
    remaining_count = 0
    if stage == "cell_trace" and contract_status in {"missing", "invalid"}:
        fixed_count = max(before_summary.get(contract_status, 0) - after_summary.get(contract_status, 0), 0)
        remaining_count = after_summary.get(contract_status, 0)
        headline = f"本次重跑处理 {processed} 份文档，修复 {fixed_count} 份，剩余 {remaining_count} 份 {contract_status}。"
    else:
        headline = f"本次执行完成 {processed} 个 {stage} 作业。"
    return {
        "headline": headline,
        "processed": processed,
        "fixed_count": fixed_count,
        "remaining_count": remaining_count,
        "before": before_summary,
        "after": after_summary,
    }


def _append_document_pipeline_run_record(
    settings: Settings,
    *,
    stage: str,
    artifact_source: str | None,
    contract_status: str | None,
    results: list[dict[str, Any]],
    execution_feedback: dict[str, Any],
) -> dict[str, Any]:
    run_id = _build_document_pipeline_run_id(stage)
    created_at = _utcnow_iso()
    detail_payload = {
        "run_id": run_id,
        "created_at": created_at,
        "stage": stage,
        "artifact_source": artifact_source,
        "contract_status": contract_status,
        "processed": len(results),
        "companies": [item.get("company_name") for item in results if item.get("company_name")],
        "results": results,
        "execution_feedback": execution_feedback,
    }
    detail_path = _document_pipeline_run_detail_path(settings, run_id)
    _write_json(detail_path, detail_payload)
    manifest = _load_document_pipeline_run_manifest(settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    report_period = None
    if results:
        first_result = results[0]
        report_id = first_result.get("report_id")
        jobs_manifest = _load_document_pipeline_job_manifest(settings)
        job = next(
            (item for item in jobs_manifest["records"] if item.get("stage") == stage and item.get("report_id") == report_id),
            None,
        )
        report_period = job.get("report_period") if job else None
    records.append(
        {
            "run_id": run_id,
            "created_at": created_at,
            "stage": stage,
            "artifact_source": artifact_source,
            "contract_status": contract_status,
            "processed": len(results),
            "report_period": report_period,
            "companies": detail_payload["companies"],
            "status": "completed",
            "execution_feedback": execution_feedback,
        }
    )
    manifest["records"] = records[-200:]
    _write_document_pipeline_run_manifest(settings, manifest)
    return records[-1]

