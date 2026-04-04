from __future__ import annotations

from typing import Any
import time

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.rules import evaluate_risk_labels
# 域服务 — 拆分后的模块化架构
from opspilot.application.alert_runtime import (
    _alert_workflow,
    _build_alert_board,
    _create_manual_task,
    _dispatch_alert_to_task,
    _get_company_periods,
    _task_board,
    _task_queue,
    _update_alert_status,
    _update_task_status,
)
from opspilot.application.scoring_service import (
    ScoringService,
    _build_evidence_groups,
    _build_label_cards,
)
from opspilot.application.admin_delivery import (
    _build_acceptance_checklist,
    _build_admin_job_catalog,
    _build_admin_quality_overview,
    _build_delivery_readiness,
    _build_delivery_report_payload,
    _build_document_pipeline_overview,
    _build_runtime_readiness,
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
from opspilot.application.industry_signals import (
    _build_kafka_signal_runtime,
)
from opspilot.application.document_pipeline_runtime import (
    _document_pipeline_jobs,
    _document_pipeline_result_detail,
    _document_pipeline_results,
    _document_pipeline_run_detail,
    _document_pipeline_runs,
    _run_document_pipeline_stage,
)
from opspilot.application.evidence_runtime import build_evidence_detail
from opspilot.application.data_runtime import (
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
from opspilot.application.workspace_runtime import (
    _persist_workspace_run,
    _workspace_history,
)
from opspilot.application.vision_runtime import (
    _company_vision_analyze,
    _company_vision_runtime,
    _run_company_vision_analyze,
    _run_company_vision_pipeline,
    _vision_run_detail,
    _vision_runs,
)
from opspilot.application.verify_runtime import (
    _build_verify_command_surface,
    _build_verify_delta_tape,
    _persist_verify_run,
    _verify_run_detail,
    _verify_runs,
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

    def industry_brain(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _build_industry_brain_payload(
            self,
            force_refresh=True,
            user_role=user_role,
            report_period=report_period,
        )

    def industry_brain_tick(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _build_industry_brain_payload(
            self,
            force_refresh=False,
            user_role=user_role,
            report_period=report_period,
        )

    def industry_brain_history(
        self,
        limit: int = 24,
        *,
        user_role: str | None = None,
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _industry_brain_history(
            self.settings,
            limit=limit,
            user_role=user_role,
            report_period=report_period,
        )

    def workspace_overview(
        self,
        user_role: str = "investor",
        report_period: str | None = None,
    ) -> dict[str, Any]:
        return _build_workspace_overview(
            self,
            user_role=user_role,
            report_period=report_period,
        )

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
        return _alert_workflow(self, report_period=report_period)

    def update_alert_status(
        self,
        alert_id: str,
        status: str,
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return _update_alert_status(
            self,
            alert_id=alert_id,
            status=status,
            report_period=report_period,
            note=note,
        )

    def dispatch_alert_to_task(
        self,
        alert_id: str,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return _dispatch_alert_to_task(
            self,
            alert_id,
            user_role=user_role,
            report_period=report_period,
            note=note,
        )

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
        return _company_vision_analyze(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def company_vision_runtime(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _company_vision_runtime(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def run_company_vision_pipeline(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _run_company_vision_pipeline(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def run_company_vision_analyze(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        return _run_company_vision_analyze(
            self,
            company_name,
            report_period,
            user_role=user_role,
        )

    def vision_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        return _vision_runs(
            self,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            limit=limit,
        )

    def vision_run_detail(self, run_id: str) -> dict[str, Any]:
        return _vision_run_detail(self, run_id)

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

    def verify_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        report_title: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return _verify_runs(
            self,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            report_title=report_title,
            limit=limit,
        )

    def verify_run_detail(self, run_id: str) -> dict[str, Any]:
        return _verify_run_detail(self, run_id)

    def task_board(
        self, user_role: str = "management", report_period: str | None = None, limit: int = 12
    ) -> dict[str, Any]:
        return _task_board(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
        )

    def update_task_status(
        self,
        task_id: str,
        status: str,
        user_role: str = "management",
        report_period: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return _update_task_status(
            self,
            task_id=task_id,
            status=status,
            user_role=user_role,
            report_period=report_period,
            note=note,
        )

    def create_task(
        self,
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
        return _create_manual_task(
            self,
            company_name=company_name,
            title=title,
            summary=summary,
            priority=priority,
            user_role=user_role,
            report_period=report_period,
            note=note,
            source_run_id=source_run_id,
        )

    def task_queue(
        self, user_role: str = "management", report_period: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        return _task_queue(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
        )

    def document_pipeline_jobs(self) -> dict[str, Any]:
        return _document_pipeline_jobs(self.settings)

    def document_pipeline_runs(self, limit: int = 30) -> dict[str, Any]:
        return _document_pipeline_runs(self.settings, limit=limit)

    def document_pipeline_run_detail(self, run_id: str) -> dict[str, Any]:
        return _document_pipeline_run_detail(self.settings, run_id)

    def document_pipeline_results(
        self,
        stage: str | None = None,
        *,
        status: str | None = None,
        artifact_source: str | None = None,
        contract_status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return _document_pipeline_results(
            self,
            stage=stage,
            status=status,
            artifact_source=artifact_source,
            contract_status=contract_status,
            limit=limit,
        )

    def document_pipeline_result_detail(self, stage: str, report_id: str) -> dict[str, Any]:
        return _document_pipeline_result_detail(self, stage, report_id)

    def run_document_pipeline_stage(
        self,
        stage: str,
        limit: int = 5,
        *,
        artifact_source: str | None = None,
        contract_status: str | None = None,
    ) -> dict[str, Any]:
        return _run_document_pipeline_stage(
            self,
            stage,
            limit,
            artifact_source=artifact_source,
            contract_status=contract_status,
        )

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
        *,
        user_role: str = "management",
        persist_run: bool = False,
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
        payload = {
            "company_name": company["company_name"],
            "report_period": company["report_period"],
            "user_role": user_role,
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
            "related_routes": [
                {
                    "label": "回到协同分析",
                    "path": "/workspace",
                    "query": {"company": company["company_name"], "period": company["report_period"]},
                },
                {
                    "label": "查看企业体检",
                    "path": "/score",
                    "query": {"company": company["company_name"], "period": company["report_period"]},
                },
                {
                    "label": "进入图谱检索",
                    "path": "/graph",
                    "query": {"company": company["company_name"], "period": company["report_period"]},
                },
            ],
        }
        if not persist_run:
            return payload
        return _persist_verify_run(
            self,
            payload,
            user_role=user_role,
            report_title=report_title,
        )

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
        return _workspace_history(
            self,
            user_role=user_role,
            report_period=report_period,
            limit=limit,
            source_limit=source_limit,
        )

    def workspace_run_detail(self, run_id: str) -> dict[str, Any]:
        return self._workspace.workspace_run_detail(run_id)

    def metric_query(
        self, *, query: str, company_name: str | None, report_period: str | None
    ) -> dict[str, Any]:
        return self._workspace.metric_query(query=query, company_name=company_name, report_period=report_period)

    def get_evidence(self, chunk_id: str, *, user_role: str = "management") -> dict[str, Any]:
        return build_evidence_detail(self, chunk_id, user_role=user_role)

    def _persist_workspace_run(
        self,
        payload: dict[str, Any],
        *,
        query: str,
        company_name: str | None,
        user_role: str,
    ) -> dict[str, Any]:
        return _persist_workspace_run(
            self,
            payload,
            query=query,
            company_name=company_name,
            user_role=user_role,
        )

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



