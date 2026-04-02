from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import json
import time

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.rules import evaluate_risk_labels
# 域服务 — 拆分后的模块化架构
from opspilot.application.alert_runtime import (
    _build_alert_board,
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
    _build_delivery_report_payload,
    _build_document_pipeline_execution_feedback,
    _build_document_pipeline_overview,
    _build_runtime_readiness,
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
    _build_task_id,
    _build_vision_run_id,
    _build_workspace_run_id,
    _document_pipeline_run_detail_path,
    _load_alert_board_manifest,
    _load_document_pipeline_job_manifest,
    _load_document_pipeline_run_manifest,
    _load_industry_brain_manifest,
    _load_task_board_manifest,
    _load_vision_run_manifest,
    _load_workspace_run_manifest,
    _vision_run_detail_path,
    _workspace_run_detail_path,
    _write_alert_board_manifest,
    _write_document_pipeline_job_manifest,
    _write_task_board_manifest,
    _write_vision_run_manifest,
    _write_workspace_run_manifest,
)
from opspilot.application.runtime_views import (
    _build_brain_command_surface,
    _build_brain_signal_tape,
    _build_industry_brain_history_snapshot,
    _build_industry_brain_watchboard_snapshot,
)
from opspilot.application.data_runtime import (
    _build_industry_live_chart,
    _build_innovation_radar,
    _build_official_data_status,
    _load_research_reports,
)
from opspilot.application.graph_query_runtime import (
    _graph_query_run_detail,
    _graph_query_runs,
    _run_company_graph_query,
)
from opspilot.application.workspace_service import WorkspaceService
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
from opspilot.application.industry_brain_runtime import (
    _build_industry_brain_payload,
    _industry_brain_history,
)
from opspilot.application.workspace_watchboard_runtime import (
    _add_watch_company,
    _build_watchboard,
    _build_workspace_execution_bus,
    _build_workspace_overview,
    _dispatch_watchboard_alerts,
    _remove_watch_company,
    _scan_watchboard,
    _watchboard_run_detail,
    _watchboard_runs,
)
from opspilot.application.workspace_company_runtime import (
    _build_company_document_upgrades,
    _build_company_execution_stream,
    _build_company_graph,
    _build_company_intelligence_runtime,
    _build_company_runtime_capsule,
    _company_workspace_compute,
)


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
        return _build_delivery_report_payload(
            overview=overview,
            app_name=self.settings.app_name,
            env=self.settings.env,
        )

    def innovation_radar(self) -> dict[str, Any]:
        return _build_innovation_radar()

    def industry_brain(self) -> dict[str, Any]:
        return _build_industry_brain_payload(self, force_refresh=True)

    def industry_brain_tick(self) -> dict[str, Any]:
        return _build_industry_brain_payload(self, force_refresh=False)

    def industry_brain_history(self, limit: int = 24) -> dict[str, Any]:
        return _industry_brain_history(self.settings, limit=limit)

    def workspace_overview(self, user_role: str = "investor") -> dict[str, Any]:
        return _build_workspace_overview(self, user_role=user_role)

    def workspace_execution_bus(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return _build_workspace_execution_bus(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
        )

    def watchboard(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        include_research: bool = True,
        item_limit: int | None = None,
    ) -> dict[str, Any]:
        return _build_watchboard(
            self,
            user_role=user_role,
            report_period=report_period,
            include_research=include_research,
            item_limit=item_limit,
        )

    def scan_watchboard(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _scan_watchboard(self, user_role=user_role, report_period=report_period)

    def watchboard_runs(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return _watchboard_runs(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
        )

    def watchboard_run_detail(self, run_id: str) -> dict[str, Any]:
        return _watchboard_run_detail(self, run_id)

    def dispatch_watchboard_alerts(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return _dispatch_watchboard_alerts(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
        )

    def add_watch_company(
        self,
        *,
        company_name: str,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return _add_watch_company(
            self,
            company_name=company_name,
            user_role=user_role,
            report_period=report_period,
            note=note,
        )

    def remove_watch_company(
        self,
        *,
        company_name: str,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _remove_watch_company(
            self,
            company_name=company_name,
            user_role=user_role,
            report_period=report_period,
        )

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
        result = self._company_workspace_compute(company_name, report_period, user_role=user_role, profile="full")
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
        result = self._company_workspace_compute(company_name, report_period, user_role=user_role, profile="graph")
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
        return _company_workspace_compute(
            self,
            company_name,
            report_period,
            user_role=user_role,
            profile=profile,
        )

    def company_runtime_capsule(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _build_company_runtime_capsule(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def company_intelligence_runtime(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _build_company_intelligence_runtime(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def company_execution_stream(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
        limit: int = 30,
    ) -> dict[str, Any]:
        return _build_company_execution_stream(
            self,
            company_name,
            report_period,
            user_role=user_role,
            limit=limit,
        )

    def company_document_upgrades(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        limit: int = 20,
        include_preview: bool = True,
        include_evidence_navigation: bool = True,
    ) -> dict[str, Any]:
        return _build_company_document_upgrades(
            self,
            company_name,
            report_period,
            limit=limit,
            include_preview=include_preview,
            include_evidence_navigation=include_evidence_navigation,
        )

    def company_graph(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
        workspace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _build_company_graph(
            self,
            company_name,
            report_period,
            user_role=user_role,
            workspace=workspace,
        )

    def company_graph_query(
        self,
        company_name: str,
        intent: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _run_company_graph_query(
            self,
            company_name,
            intent,
            report_period,
            user_role=user_role,
        )

    def graph_query_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        return _graph_query_runs(
            self,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            limit=limit,
        )

    def graph_query_run_detail(self, run_id: str) -> dict[str, Any]:
        return _graph_query_run_detail(self, run_id)

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




