from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from html import unescape
from datetime import UTC, date, datetime
import base64
import json
import re
import time

import requests

try:
    from kafka import KafkaConsumer, TopicPartition
except ImportError:  # pragma: no cover
    KafkaConsumer = None
    TopicPartition = None

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.catalog import METRIC_BY_CODE
from opspilot.domain.routing import detect_query_type
from opspilot.domain.rules import evaluate_opportunity_labels, evaluate_risk_labels
from opspilot.domain.scoring import score_company
from opspilot.runtime_checks import probe_llm_runtime

# 域服务 — 拆分后的模块化架构
from opspilot.application.scoring_service import ScoringService
from opspilot.application.research_forecast import (
    extract_forecast_metric_map,
    extract_forecast_profit_map,
    find_forecast_sentence,
    infer_anchor_year,
)
from opspilot.application.workspace_service import WorkspaceService
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
TABLE_HEADER_TERMS = (
    "项目",
    "本报告期",
    "上年同期",
    "年初至报告期末",
    "期末余额",
    "期初余额",
    "增减",
    "变动",
    "单位",
    "币种",
    "合并资产负债表",
    "合并利润表",
    "合并现金流量表",
    "续表",
)
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
ROLE_PROFILES = {
    "investor": {
        "label": "投资者",
        "focus_title": "优先看收益质量、同业位置和研报分歧",
        "starter_queries": [
            "这家公司当前最值得警惕的风险是什么？",
            "把这家公司和同子行业头部公司做一下对比。",
            "最新研报和真实财报有没有偏差？",
        ],
    },
    "management": {
        "label": "企业管理者",
        "focus_title": "优先看经营瓶颈、现金压力和整改动作",
        "starter_queries": [
            "给我一份经营体检和整改优先级。",
            "现金、应收和库存哪个环节最拖后腿？",
            "如果只做三件事，当前最应该推进什么？",
        ],
    },
    "regulator": {
        "label": "监管 / 风控角色",
        "focus_title": "优先看风险暴露、事件信号和批量巡检",
        "starter_queries": [
            "当前主周期里哪些公司风险抬升最快？",
            "这家公司有哪些需要重点跟踪的事件信号？",
            "把研报观点和真实财报偏差最大的点列出来。",
        ],
    },
}

EXTERNAL_SIGNAL_PRIORITY = {
    "periodic_report": 0,
    "company_research": 1,
    "industry_research": 2,
    "company_snapshot": 3,
}

SUBINDUSTRY_SIGNAL_TOPICS = {
    "光伏": ("光伏设备",),
    "储能": ("电池", "能源金属"),
    "锂电池与电池材料": ("电池", "能源金属"),
    "风电设备与新能源装备": ("风电设备",),
}


class DocumentPipelineBlockedError(RuntimeError):
    pass


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


def _select_research_report(
    reports: list[dict[str, Any]],
    *,
    company_name: str,
    report_period: str | None,
    report_title: str | None,
    available_periods: set[str] | None = None,
) -> dict[str, Any] | None:
    matches = [report for report in reports if report.get("company_name") == company_name]
    title_matches = matches
    if report_title:
        title_matches = [report for report in matches if report_title in report.get("title", "")]
        matches = title_matches
    if report_period:
        period_matches = [
            report
            for report in matches
            if _infer_report_period_from_text(report.get("title", "")) == report_period
        ]
        if not period_matches:
            if report_title and title_matches:
                matches = title_matches
            else:
                return None
        else:
            matches = period_matches
    matches.sort(key=lambda item: item.get("publish_date", ""), reverse=True)
    if report_period is None:
        matches.sort(key=lambda item: _research_report_content_score(item), reverse=True)
        matches.sort(key=lambda item: _research_report_bucket(item, available_periods))
    return matches[0] if matches else None


def _infer_report_period_from_text(text: str) -> str | None:
    year_match = re.search(r"(\d{4})年", text)
    if not year_match:
        return None
    year = year_match.group(1)
    if "半年度" in text or "半年报" in text or "中报" in text:
        return f"{year}H1"
    if "三季度" in text or "第三季度" in text or "三季报" in text:
        return f"{year}Q3"
    if "一季度" in text or "第一季度" in text or "一季报" in text:
        return f"{year}Q1"
    if "年度" in text or "年报" in text:
        return f"{year}FY"
    return None


def _extract_research_payload(report_html: str) -> dict[str, Any]:
    match = re.search(r"var\s+zwinfo\s*=\s*(\{.*?\});", report_html, re.S)
    if match is None:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_research_meta(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    report_body = payload.get("notice_content", "")
    rating_info = _extract_research_rating(report_body, payload)
    target_price_info = _extract_target_price(report_body)
    publish_date = payload.get("notice_date") or report.get("publish_date", "")
    return {
        "title": payload.get("notice_title") or report["title"],
        "publish_date": publish_date.split(" ")[0] if publish_date else "",
        "source_url": report.get("detail_url") or report.get("source_url") or "",
        "attachment_url": payload.get("attach_url"),
        "source_name": payload.get("source_sample_name"),
        "researcher": payload.get("researcher"),
        "rating_code": payload.get("rating"),
        "rating_label": rating_info.get("label"),
        "rating_action": rating_info.get("action"),
        "rating_change": _classify_rating_action(rating_info.get("action")),
        "target_price": target_price_info.get("value"),
        "target_price_excerpt": target_price_info.get("excerpt"),
    }


def _extract_research_body(report_html: str, payload: dict[str, Any] | None = None) -> str:
    if payload and payload.get("notice_content"):
        return _normalize_research_text(str(payload["notice_content"]))
    match = re.search(r'<div id="ctx-content"[^>]*>(.*?)</div>', report_html, re.S)
    body = match.group(1) if match else report_html
    cleaned = re.sub(r"<br\s*/?>", "\n", body)
    cleaned = re.sub(r"</p>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return _normalize_research_text(cleaned)


def _build_claim_cards(
    company: dict[str, Any],
    report: dict[str, Any],
    report_body: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    patterns = [
        (
            "营收同比",
            "G1",
            "percent",
            re.compile(r"营收(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "营收规模",
            "RAW_REVENUE",
            "amount_100m",
            re.compile(r"营收(\d+(?:\.\d+)?)(?:/\d+(?:\.\d+)?)?亿元"),
        ),
        (
            "归母净利润同比",
            "NET_PROFIT_YOY",
            "percent",
            re.compile(r"归母净利润(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "归母净利润规模",
            "RAW_NET_PROFIT",
            "amount_100m",
            re.compile(r"归母净利润(\d+(?:\.\d+)?)(?:/\d+(?:\.\d+)?)?亿元"),
        ),
        (
            "扣非归母净利润同比",
            "G2",
            "percent",
            re.compile(r"扣非归母净利润(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?亿元，)?同比([+-]?\d+(?:\.\d+)?)%"),
        ),
        (
            "毛利率",
            "P1",
            "percent",
            re.compile(r"毛利率(\d+(?:\.\d+)?)%"),
        ),
    ]
    for index, (label, metric_key, value_type, pattern) in enumerate(patterns, start=1):
        match = pattern.search(report_body)
        if match is None:
            continue
        claimed_value = float(match.group(1))
        actual_value = _resolve_claim_actual_value(company, metric_key)
        status, delta = _compare_claim_values(claimed_value, actual_value, value_type=value_type)
        evidence_refs = _resolve_claim_evidence_refs(company, metric_key)
        cards.append(
            {
                "claim_id": f"{report['security_code']}-claim-{index}",
                "label": label,
                "metric_key": metric_key,
                "claimed_value": claimed_value,
                "actual_value": actual_value,
                "delta": delta,
                "status": status,
                "excerpt": _clip_claim_excerpt(report_body, match.group(0)),
                "research_chunk_id": f"research-{report['security_code']}-{index}",
                "evidence_refs": evidence_refs,
                "report_title": report["title"],
            }
        )
    return cards


def _build_forecast_cards(
    report: dict[str, Any],
    report_body: str,
    report_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    sentence = find_forecast_sentence(report_body)
    if sentence is None:
        return []
    anchor_year = infer_anchor_year(report_meta)
    profit_map = extract_forecast_profit_map(sentence, anchor_year=anchor_year)
    if not profit_map:
        return []
    years = sorted(profit_map.keys())
    yoy_map = extract_forecast_metric_map(
        sentence,
        pattern=re.compile(
            r"(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年归母净利(?:润)?(?:同增|同比增长|同比)([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"
        ),
        default_years=years,
        anchor_year=anchor_year,
        fallback_pattern=re.compile(r"同比([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"),
        suffix="%",
    )
    pe_map = extract_forecast_metric_map(
        sentence,
        pattern=re.compile(
            r"(?:对应)?(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年(?:PE|市盈率)(?:为)?([0-9.xX倍、/,，]+)"
        ),
        default_years=years,
        anchor_year=anchor_year,
        fallback_pattern=re.compile(r"(?:对应)?(?:PE|市盈率)(?:为)?([0-9.xX倍、/,，]+)"),
        suffix="x",
    )

    cards: list[dict[str, Any]] = []
    security_code = report.get("security_code") or report.get("company_name") or "research"
    for year in years:
        cards.append(
            {
                "forecast_id": f"{security_code}-forecast-{year}",
                "label": f"{year}年归母净利润预测",
                "report_period": f"{year}FY",
                "forecast_value": profit_map.get(year),
                "yoy_value": yoy_map.get(year),
                "pe_value": pe_map.get(year),
                "rating_label": report_meta.get("rating_label"),
                "rating_action": report_meta.get("rating_action"),
                "excerpt": _clip_claim_excerpt(report_body, sentence, radius=240),
                "research_chunk_id": f"research-{security_code}-forecast-{year}",
            }
        )
    return cards


def _resolve_claim_actual_value(company: dict[str, Any], metric_key: str) -> float | None:
    if metric_key in company.get("metrics", {}):
        return company["metrics"][metric_key]
    if metric_key in company.get("raw_metrics", {}):
        raw_value = company["raw_metrics"][metric_key]
        if raw_value is None:
            return None
        return round(raw_value / 1e8, 2)
    if metric_key == "NET_PROFIT_YOY":
        value = company.get("facts", {}).get("net_profit", {}).get("change_pct")
        return None if value is None else float(value)
    return None


def _compare_claim_values(
    claimed_value: float,
    actual_value: float | None,
    *,
    value_type: str,
) -> tuple[str, float | None]:
    if actual_value is None:
        return "insufficient_data", None
    delta = round(actual_value - claimed_value, 2)
    tolerance = 1.5 if value_type == "percent" else max(0.5, abs(claimed_value) * 0.05)
    if abs(delta) <= tolerance:
        return "match", delta
    return "mismatch", delta


def _resolve_claim_evidence_refs(company: dict[str, Any], metric_key: str) -> list[str]:
    metric_map = {
        "RAW_REVENUE": "G1",
        "RAW_NET_PROFIT": "G2",
        "NET_PROFIT_YOY": "G2",
    }
    evidence_metric = metric_map.get(metric_key, metric_key)
    refs = list(company.get("metric_evidence", {}).get(evidence_metric, []))
    if not refs and company.get("summary_chunk_id"):
        refs.append(company["summary_chunk_id"])
    return refs


def _clip_claim_excerpt(text: str, anchor: str, *, radius: int = 180) -> str:
    index = text.find(anchor)
    if index < 0:
        return text[: radius * 2]
    start = max(index - radius // 2, 0)
    end = min(index + len(anchor) + radius, len(text))
    return text[start:end]


def _build_claim_evidence(
    repository: Any,
    report: dict[str, Any],
    report_meta: dict[str, Any],
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for card in claim_cards:
        evidence.append(
            {
                "chunk_id": card["research_chunk_id"],
                "company_name": report["company_name"],
                "report_period": _infer_report_period_from_text(report_meta["title"]) or report_meta["publish_date"],
                "source_title": report_meta["title"],
                "source_type": "research_report_excerpt",
                "page": 1,
                "excerpt": card["excerpt"],
                "fingerprint": f"{report['security_code']}-{card['claim_id']}",
                "source_url": report_meta["source_url"],
                "local_path": report["local_path"],
            }
        )
        evidence.extend(repository.resolve_evidence(card["evidence_refs"]))
    for card in forecast_cards or []:
        evidence.append(
            {
                "chunk_id": card["research_chunk_id"],
                "company_name": report["company_name"],
                "report_period": card["report_period"],
                "source_title": report_meta["title"],
                "source_type": "research_forecast_excerpt",
                "page": 1,
                "excerpt": card["excerpt"],
                "fingerprint": f"{report['security_code']}-{card['forecast_id']}",
                "source_url": report_meta["source_url"],
                "local_path": report["local_path"],
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in evidence:
        if item["chunk_id"] in seen_ids:
            continue
        seen_ids.add(item["chunk_id"])
        deduped.append(item)
    return deduped


def _build_claim_evidence_groups(
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_by_id = {item["chunk_id"]: item for item in evidence}
    groups: list[dict[str, Any]] = []
    for card in claim_cards:
        refs = [card["research_chunk_id"], *card.get("evidence_refs", [])]
        items = [evidence_by_id[chunk_id] for chunk_id in refs if chunk_id in evidence_by_id]
        groups.append(
            {
                "code": card["claim_id"],
                "title": card["label"],
                "subtitle": f"核验结果：{card['status']}",
                "items": items,
                "anchor_terms": [card["label"]],
            }
        )
    for card in forecast_cards:
        refs = [card["research_chunk_id"]]
        items = [evidence_by_id[chunk_id] for chunk_id in refs if chunk_id in evidence_by_id]
        groups.append(
            {
                "code": card["forecast_id"],
                "title": f"{card['report_period']} 盈利预测",
                "subtitle": f"预测利润 {card['forecast_value']:.2f} 亿元",
                "items": items,
                "anchor_terms": [card["report_period"], "归母净利润"],
            }
        )
    return groups


def _render_claim_answer(
    report_meta: dict[str, Any],
    report_period: str,
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> str:
    matched = sum(1 for item in claim_cards if item["status"] == "match")
    mismatched = sum(1 for item in claim_cards if item["status"] == "mismatch")
    insufficient = sum(1 for item in claim_cards if item["status"] == "insufficient_data")
    rating_text = _format_rating_text(report_meta)
    return (
        f"### 研报观点核验\n"
        f"- 研报：**{report_meta['title']}**\n"
        f"- 核验报期：**{report_period}**\n"
        f"- 投资评级：**{rating_text}**\n"
        f"- 评级动作：**{report_meta.get('rating_change') or '未披露'}**\n"
        f"- 目标价：**{_format_target_price(report_meta.get('target_price'))}**\n"
        f"- 匹配：**{matched}** 条\n"
        f"- 偏差：**{mismatched}** 条\n"
        f"- 待补充：**{insufficient}** 条\n"
        f"- 盈利预测：**{len(forecast_cards)}** 个年度"
    )


def _build_claim_chart(claim_cards: list[dict[str, Any]]) -> dict[str, Any]:
    labels = ["match", "mismatch", "insufficient_data"]
    return {
        "type": "bar",
        "title": "研报观点核验结果",
        "options": {
            "xAxis": {"type": "category", "data": ["匹配", "偏差", "待补充"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [sum(1 for item in claim_cards if item["status"] == label) for label in labels],
                }
            ],
        },
    }


def _summarize_forecast_cards(forecast_cards: list[dict[str, Any]]) -> dict[str, Any]:
    if not forecast_cards:
        return {}
    headline = min(
        forecast_cards,
        key=lambda item: item.get("report_period", "9999FY"),
    )
    headline_year = headline.get("report_period", "").replace("FY", "") or None
    return {
        "headline_year": headline_year,
        "headline_value": headline.get("forecast_value"),
        "headline_pe": headline.get("pe_value"),
    }


def _build_research_compare_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [item["source_name"] or item["title"] for item in rows]
    return {
        "type": "bar",
        "title": "研报目标价与首年利润预测对比",
        "options": {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["目标价", "首年利润预测"]},
            "xAxis": {"type": "category", "data": labels},
            "yAxis": [
                {"type": "value", "name": "目标价(元)"},
                {"type": "value", "name": "利润预测(亿元)"},
            ],
            "series": [
                {
                    "name": "目标价",
                    "type": "bar",
                    "data": [item.get("target_price") for item in rows],
                },
                {
                    "name": "首年利润预测",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": [item.get("headline_forecast_value") for item in rows],
                },
            ],
        },
    }


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


def _build_research_compare_sort_options() -> dict[str, str]:
    return {
        "priority": "优先看分歧",
        "latest": "按时间最新",
        "target_price_desc": "目标价从高到低",
        "forecast_desc": "首年利润预测从高到低",
    }


def _build_research_compare_filter_options() -> dict[str, str]:
    return {
        "all": "全部研报",
        "supported": "仅报期已对齐",
        "target_price": "仅看含目标价",
        "forecast": "仅看含盈利预测",
        "divergence": "仅看分歧信号",
    }


def _label_research_compare_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labeled_rows = [dict(row) for row in rows]
    if not labeled_rows:
        return labeled_rows

    target_price_rows = [row for row in labeled_rows if row.get("target_price") is not None]
    if len(target_price_rows) >= 2:
        high_target = max(target_price_rows, key=lambda row: row["target_price"])
        low_target = min(target_price_rows, key=lambda row: row["target_price"])
        high_target.setdefault("signal_tags", []).append("目标价最高")
        low_target.setdefault("signal_tags", []).append("目标价最低")

    forecast_rows = [row for row in labeled_rows if row.get("headline_forecast_value") is not None]
    if len(forecast_rows) >= 2:
        high_forecast = max(forecast_rows, key=lambda row: row["headline_forecast_value"])
        low_forecast = min(forecast_rows, key=lambda row: row["headline_forecast_value"])
        high_forecast.setdefault("signal_tags", []).append("预测最乐观")
        low_forecast.setdefault("signal_tags", []).append("预测最谨慎")

    complete_rows = [row for row in labeled_rows if row.get("forecast_count")]
    if complete_rows:
        richest = max(
            complete_rows,
            key=lambda row: (
                row.get("forecast_count", 0),
                row.get("claim_signal_count", 0),
                row.get("target_price") is not None,
            ),
        )
        richest.setdefault("signal_tags", []).append("信息最完整")

    rating_values = {
        row["rating_text"]
        for row in labeled_rows
        if row.get("rating_text") and row["rating_text"] != "未披露"
    }
    rating_diverges = len(rating_values) > 1
    for row in labeled_rows:
        tags = row.setdefault("signal_tags", [])
        if row.get("is_period_supported"):
            tags.append("报期已对齐")
        else:
            tags.append("报期待核实")
        if row.get("target_price") is not None:
            tags.append("含目标价")
        if row.get("headline_forecast_value") is not None:
            tags.append("含盈利预测")
        if rating_diverges and row.get("rating_text") and row["rating_text"] != "未披露":
            tags.append(f"评级:{row['rating_text']}")

        row["signal_tags"] = list(dict.fromkeys(tags))
        row["divergence_score"] = _compute_research_divergence_score(row)
    return labeled_rows


def _compute_research_divergence_score(row: dict[str, Any]) -> int:
    score = 0
    for tag in row.get("signal_tags", []):
        if tag in {"目标价最高", "目标价最低", "预测最乐观", "预测最谨慎"}:
            score += 2
        elif tag.startswith("评级:"):
            score += 2
        elif tag in {"含目标价", "含盈利预测", "信息最完整"}:
            score += 1
    if not row.get("is_period_supported"):
        score -= 1
    return score


def _filter_research_compare_rows(
    rows: list[dict[str, Any]],
    filter_mode: str,
) -> list[dict[str, Any]]:
    if filter_mode == "supported":
        return [row for row in rows if row.get("is_period_supported")]
    if filter_mode == "target_price":
        return [row for row in rows if row.get("target_price") is not None]
    if filter_mode == "forecast":
        return [row for row in rows if row.get("headline_forecast_value") is not None]
    if filter_mode == "divergence":
        return [
            row
            for row in rows
            if any(
                tag in {"目标价最高", "目标价最低", "预测最乐观", "预测最谨慎"}
                or tag.startswith("评级:")
                for tag in row.get("signal_tags", [])
            )
        ]
    return rows


def _sort_research_compare_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "latest":
        return sorted(
            rows,
            key=lambda row: (
                row.get("publish_date") or "",
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    if sort_by == "target_price_desc":
        return sorted(
            rows,
            key=lambda row: (
                row.get("target_price") is not None,
                row.get("target_price") or -1,
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    if sort_by == "forecast_desc":
        return sorted(
            rows,
            key=lambda row: (
                row.get("headline_forecast_value") is not None,
                row.get("headline_forecast_value") or -1,
                row.get("divergence_score", 0),
            ),
            reverse=True,
        )
    return sorted(
        rows,
        key=lambda row: (
            row.get("divergence_score", 0),
            row.get("forecast_count", 0),
            row.get("claim_signal_count", 0),
            row.get("publish_date") or "",
        ),
        reverse=True,
    )


def _build_research_compare_insights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    rated_rows = [row for row in rows if row.get("rating_text") and row["rating_text"] != "未披露"]
    rating_values = sorted({row["rating_text"] for row in rated_rows})
    if len(rating_values) == 1 and rating_values:
        insights.append(
            {
                "kind": "consensus",
                "title": "评级观点一致",
                "detail": f"{len(rated_rows)} 篇研报均给出 {rating_values[0]}。",
            }
        )
    elif len(rating_values) > 1:
        insights.append(
            {
                "kind": "divergence",
                "title": "评级存在分歧",
                "detail": f"当前覆盖研报出现 {', '.join(rating_values)} 等不同评级。",
            }
        )

    target_price_rows = [row for row in rows if row.get("target_price") is not None]
    if len(target_price_rows) >= 2:
        high = max(target_price_rows, key=lambda row: row["target_price"])
        low = min(target_price_rows, key=lambda row: row["target_price"])
        spread = round(high["target_price"] - low["target_price"], 2)
        kind = "divergence" if spread >= 10 else "consensus"
        title = "目标价分歧明显" if spread >= 10 else "目标价较为集中"
        insights.append(
            {
                "kind": kind,
                "title": title,
                "detail": (
                    f"最高为 {high['source_name'] or high['title']} 的 {_format_target_price(high['target_price'])}，"
                    f"最低为 {low['source_name'] or low['title']} 的 {_format_target_price(low['target_price'])}，"
                    f"差值 {spread:.2f} 元。"
                ),
            }
        )

    forecast_rows = [row for row in rows if row.get("headline_forecast_value") is not None]
    if len(forecast_rows) >= 2:
        high = max(forecast_rows, key=lambda row: row["headline_forecast_value"])
        low = min(forecast_rows, key=lambda row: row["headline_forecast_value"])
        spread = round(high["headline_forecast_value"] - low["headline_forecast_value"], 2)
        kind = "divergence" if spread >= 3 else "consensus"
        title = "首年利润预测差异较大" if spread >= 3 else "首年利润预测接近"
        insights.append(
            {
                "kind": kind,
                "title": title,
                "detail": (
                    f"最高预测来自 {high['source_name'] or high['title']}，为 {high['headline_forecast_value']:.2f} 亿元；"
                    f"最低预测为 {low['headline_forecast_value']:.2f} 亿元，区间 {spread:.2f} 亿元。"
                ),
            }
        )

    return insights


def _build_research_timeline_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        institution = row.get("source_name") or "机构未披露"
        groups.setdefault(institution, []).append(dict(row))

    timeline_groups: list[dict[str, Any]] = []
    for institution, items in groups.items():
        ordered_items = sorted(items, key=lambda item: item.get("publish_date") or "")
        transitions = []
        same_rating_pairs = 0
        comparable_pairs = 0
        for previous, current in zip(ordered_items, ordered_items[1:]):
            transition = _build_research_transition(previous, current)
            transitions.append(transition)
            if (
                transition["is_rating_comparable"]
                and transition["rating_from"] != "未披露"
                and transition["rating_to"] != "未披露"
            ):
                comparable_pairs += 1
                if transition["rating_from"] == transition["rating_to"]:
                    same_rating_pairs += 1
        latest_item = ordered_items[-1]
        latest_transition = transitions[-1] if transitions else None
        timeline_groups.append(
            {
                "institution": institution,
                "report_count": len(ordered_items),
                "latest_rating": latest_item.get("rating_text") or "未披露",
                "latest_target_price": latest_item.get("target_price"),
                "latest_forecast_value": latest_item.get("headline_forecast_value"),
                "latest_transition": latest_transition,
                "rating_stability": (
                    round(same_rating_pairs / comparable_pairs * 100, 2)
                    if comparable_pairs > 0
                    else None
                ),
                "items": ordered_items,
                "transitions": transitions,
            }
        )
    return sorted(
        timeline_groups,
        key=lambda item: (
            item["report_count"],
            item.get("latest_transition", {}).get("publish_date") if item.get("latest_transition") else "",
            item["institution"],
        ),
        reverse=True,
    )


def _build_research_transition(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    is_same_period = (
        previous.get("report_period")
        and previous.get("report_period") == current.get("report_period")
    )
    is_same_forecast_year = (
        previous.get("headline_forecast_year")
        and previous.get("headline_forecast_year") == current.get("headline_forecast_year")
    )
    rating_from = previous.get("rating_text") or "未披露"
    rating_to = current.get("rating_text") or "未披露"
    if not is_same_period:
        transition_kind = "not_comparable"
        summary = "报期不同，不直接比较评级和目标价"
    elif rating_from != "未披露" and rating_to != "未披露" and rating_from != rating_to:
        transition_kind = "rating_changed"
        summary = f"评级由 {rating_from} 调整为 {rating_to}"
    else:
        transition_kind = "stable"
        summary = f"评级维持 {rating_to}"

    target_delta = None
    if (
        is_same_period
        and previous.get("target_price") is not None
        and current.get("target_price") is not None
    ):
        target_delta = round(current["target_price"] - previous["target_price"], 2)
        if target_delta != 0:
            transition_kind = "target_changed"
            direction = "上调" if target_delta > 0 else "下调"
            summary = f"目标价{direction} {abs(target_delta):.2f} 元"

    forecast_delta = None
    if (
        is_same_forecast_year
        and previous.get("headline_forecast_value") is not None
        and current.get("headline_forecast_value") is not None
    ):
        forecast_delta = round(
            current["headline_forecast_value"] - previous["headline_forecast_value"],
            2,
        )

    return {
        "publish_date": current.get("publish_date"),
        "title": current.get("title"),
        "report_period": current.get("report_period"),
        "previous_report_period": previous.get("report_period"),
        "source_url": current.get("source_url"),
        "attachment_url": current.get("attachment_url"),
        "rating_from": rating_from,
        "rating_to": rating_to,
        "target_delta": target_delta,
        "forecast_delta": forecast_delta,
        "transition_kind": transition_kind,
        "summary": summary,
        "is_rating_comparable": bool(is_same_period),
        "is_forecast_comparable": bool(is_same_forecast_year),
        "forecast_year": current.get("headline_forecast_year"),
    }


def _format_rating_text(report_meta: dict[str, Any]) -> str:
    rating_parts = [
        part for part in (report_meta.get("rating_action"), report_meta.get("rating_label")) if part
    ]
    if rating_parts:
        return "".join(rating_parts)
    rating_code = report_meta.get("rating_code")
    if isinstance(rating_code, str) and re.fullmatch(r"[A-Z]{1,3}", rating_code):
        return "未披露"
    return rating_code or "未披露"


def _format_target_price(value: float | None) -> str:
    if value is None:
        return "未披露"
    return f"{value:.2f} 元"


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


def _build_workspace_payload(
    payload: dict[str, Any],
    *,
    query: str,
    user_role: str,
) -> dict[str, Any]:
    role_profile = _build_role_profile(user_role)
    answer_sections = _build_answer_sections(payload, role_profile["key"])
    insight_cards = _build_workspace_insight_cards(payload)
    follow_up_questions = _build_follow_up_questions(payload, role_profile["key"])
    agent_flow = _build_agent_flow(payload, query, role_profile["key"])
    control_plane = _build_control_plane(payload, query, role_profile["key"], agent_flow)
    return {
        **payload,
        "role_profile": role_profile,
        "answer_sections": answer_sections,
        "insight_cards": insight_cards,
        "follow_up_questions": follow_up_questions,
        "agent_flow": agent_flow,
        "control_plane": control_plane,
    }


def _build_role_profile(user_role: str) -> dict[str, Any]:
    role_key = user_role if user_role in ROLE_PROFILES else "investor"
    profile = ROLE_PROFILES[role_key]
    return {
        "key": role_key,
        "label": profile["label"],
        "focus_title": profile["focus_title"],
        "starter_queries": profile["starter_queries"],
    }


def _build_answer_sections(payload: dict[str, Any], role_key: str) -> list[dict[str, Any]]:
    query_type = payload.get("query_type")
    company_name = payload.get("company_name", "当前公司")
    report_period = payload.get("report_period")
    if query_type == "company_scoring":
        scorecard = payload.get("scorecard", {})
        return [
            {
                "title": "经营结论",
                "lines": [
                    f"{company_name} 在 {report_period} 的总分为 {scorecard.get('total_score')}，等级 {scorecard.get('grade')}。",
                    f"当前处于 {payload.get('subindustry', '所属子行业')} 公司池的 {scorecard.get('subindustry_percentile')}pct 位置。",
                ],
            },
            {
                "title": "重点风险",
                "lines": [
                    item["name"] for item in scorecard.get("risk_labels", [])
                ]
                or ["当前没有命中高风险标签。"],
            },
            {
                "title": "优先动作",
                "lines": [
                    f"{item['priority']} {item['title']}：{item['action']}"
                    for item in payload.get("action_cards", [])[:3]
                ]
                or ["当前没有新增动作要求。"],
            },
        ]
    if query_type == "claim_verification":
        report_meta = payload.get("report_meta", {})
        return [
            {
                "title": "核验结论",
                "lines": [
                    f"当前核验报期为 {report_period}，研报标题为《{report_meta.get('title', '未命名研报')}》。",
                    f"匹配观点 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'match')} 条，偏差观点 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'mismatch')} 条。",
                ],
            },
            {
                "title": "偏差与待核查",
                "lines": [
                    item["claim_text"]
                    for item in payload.get("claim_cards", [])
                    if item.get("status") != "match"
                ][:3]
                or ["当前没有发现明显偏差。"],
            },
            {
                "title": "盈利预测",
                "lines": [
                    f"{item['forecast_year']} 年：{item['profit_value']} 亿元，PE {item['pe_value']} 倍"
                    for item in payload.get("forecast_cards", [])[:3]
                ]
                or ["当前研报未提取到明确盈利预测。"],
            },
        ]
    if query_type == "peer_benchmark":
        benchmark = payload.get("benchmark", [])
        top_rows = benchmark[:3]
        return [
            {
                "title": "同业位置",
                "lines": [payload.get("answer_markdown", "")],
            },
            {
                "title": "头部公司",
                "lines": [
                    f"{index + 1}. {item['company_name']} {item['total_score']} 分"
                    for index, item in enumerate(top_rows)
                ],
            },
        ]
    if query_type == "risk_scan":
        alert_board = payload.get("alert_board", [])
        risk_board = payload.get("risk_board", [])
        return [
            {
                "title": "批量预警",
                "lines": [
                    f"{item['company_name']}：{item['summary']}"
                    for item in alert_board[:4]
                ]
                or ["当前主周期没有新增重点预警。"],
            },
            {
                "title": "高风险公司",
                "lines": [
                    f"{item['company_name']}：{item['risk_count']} 个风险标签"
                    for item in risk_board[:5]
                ],
            },
        ]
    if query_type == "metric_query":
        return [
            {
                "title": "指标结果",
                "lines": [_strip_markdown(payload.get("answer_markdown", ""))],
            }
        ]
    if query_type == "brief_generation":
        answer = _strip_markdown(payload.get("answer_markdown", ""))
        return [{"title": "经营简报", "lines": [line for line in answer.splitlines() if line.strip()]}]
    return [
        {
            "title": "分析结果",
            "lines": [_strip_markdown(payload.get("answer_markdown", ""))],
        }
    ]


def _build_workspace_insight_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for item in payload.get("key_numbers", [])[:4]:
        cards.append(
            {
                "label": item.get("label"),
                "value": item.get("value"),
                "unit": item.get("unit"),
            }
        )
    if payload.get("query_type") == "company_scoring":
        scorecard = payload.get("scorecard", {})
        cards.extend(
            [
                {"label": "风险标签", "value": len(scorecard.get("risk_labels", [])), "unit": "个"},
                {"label": "建议动作", "value": len(payload.get("action_cards", [])), "unit": "项"},
            ]
        )
    return cards[:6]


def _build_follow_up_questions(payload: dict[str, Any], role_key: str) -> list[str]:
    company_name = payload.get("company_name")
    report_period = payload.get("report_period")
    if payload.get("query_type") == "company_scoring" and company_name and report_period:
        if role_key == "management":
            return [
                f"{company_name}{report_period}最先要修复的经营环节是什么？",
                f"{company_name}{report_period}现金和应收谁的问题更重？",
                f"{company_name}{report_period}有哪些动作能在一个季度内见效？",
            ]
        if role_key == "regulator":
            return [
                f"{company_name}{report_period}有哪些需要持续跟踪的事件信号？",
                f"{company_name}{report_period}和上一期相比新增了哪些风险？",
                f"{company_name}{report_period}是否存在研报与财报偏差？",
            ]
        return [
            f"{company_name}{report_period}和同业龙头差距主要在哪？",
            f"{company_name}{report_period}最新研报观点是否可信？",
            f"{company_name}{report_period}最影响估值的风险是什么？",
        ]
    if payload.get("query_type") == "claim_verification" and company_name:
        return [
            f"{company_name}还有哪些研报可以横向对比？",
            f"{company_name}最新评级动作和目标价是什么？",
            f"{company_name}哪些观点缺少真实财报支撑？",
        ]
    return ROLE_PROFILES[role_key]["starter_queries"]


def _build_agent_flow(payload: dict[str, Any], query: str, role_key: str) -> list[dict[str, Any]]:
    evidence_count = len(payload.get("evidence", []))
    action_count = len(payload.get("action_cards", []))
    risk_count = len(payload.get("scorecard", {}).get("risk_labels", []))
    formula_count = len(payload.get("formula_cards", []))
    claim_count = len(payload.get("claim_cards", []))
    query_type = payload.get("query_type")
    tool_trace = payload.get("tool_trace", [])
    tools_called = [t["tool_name"] for t in tool_trace if t.get("success")]
    return [
        {
            "step": 1,
            "agent_key": "router",
            "agent_label": "任务识别",
            "agent": "任务识别",
            "status": "completed",
            "title": "识别任务并锁定公司",
            "summary": f"已将问题归类为 {payload.get('query_type')}，目标问题是：{query}",
            "source": "问题文本 + 公司池 + 报期索引",
            "tool": "intent_router",
            "handoff": "data",
            "route": _build_agent_route("orchestrator", payload),
            "metrics": [
                {"label": "任务类型", "value": query_type or "unknown"},
                {"label": "目标公司", "value": payload.get("company_name", "未显式指定")},
                {"label": "目标报期", "value": payload.get("report_period", "自动选择")},
            ],
        },
        {
            "step": 2,
            "agent_key": "data",
            "agent_label": "数据分析",
            "agent": "数据分析",
            "status": "completed",
            "title": "抽取经营与风险信号",
            "summary": (
                f"调用了 {len(tools_called)} 个工具: {', '.join(tools_called) or '无'}。"
                f" 识别到 {risk_count} 个风险，{formula_count} 条公式链。"
                if payload.get("query_type") == "company_scoring"
                else f"调用了 {len(tools_called)} 个工具，提取 {len(payload.get('key_numbers', []))} 个关键结果。"
            ),
            "source": _resolve_agent_signal_source(query_type),
            "tool": _resolve_agent_signal_tool(query_type),
            "handoff": "risk",
            "route": _build_agent_route("signal_analyst", payload),
            "metrics": _build_signal_agent_metrics(payload, risk_count, formula_count, claim_count),
        },
        {
            "step": 3,
            "agent_key": "risk",
            "agent_label": "证据校验",
            "agent": "证据校验",
            "status": "completed",
            "title": "回放来源与可核查证据",
            "summary": f"当前返回 {evidence_count} 条证据引用，优先暴露页码和来源片段。",
            "source": "官方财报页级解析 + 研报详情页 + 公式输入字段",
            "tool": "evidence_auditor",
            "handoff": "strategy",
            "route": _build_agent_route("evidence_auditor", payload),
            "metrics": [
                {"label": "证据条数", "value": evidence_count},
                {"label": "证据分组", "value": len(payload.get("evidence_groups", []))},
                {"label": "公式回放", "value": formula_count},
            ],
        },
        {
            "step": 4,
            "agent_key": "strategy",
            "agent_label": "策略生成",
            "agent": "策略生成",
            "status": "completed",
            "title": "按角色给出下一步",
            "summary": (
                f"已生成 {action_count} 条角色相关动作。"
                if action_count
                else f"已切换到 {ROLE_PROFILES[role_key]['label']} 视角的后续问题建议。"
            ),
            "source": "评分结果 + 风险标签 + 角色视角",
            "tool": "action_planner",
            "handoff": "返回工作台",
            "route": _build_agent_route("action_planner", payload),
            "metrics": [
                {"label": "动作数", "value": action_count},
                {"label": "追问数", "value": len(_build_follow_up_questions(payload, role_key))},
                {"label": "角色", "value": ROLE_PROFILES[role_key]["label"]},
            ],
        },
    ]


def _build_control_plane(
    payload: dict[str, Any],
    query: str,
    role_key: str,
    agent_flow: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "session_label": f"{ROLE_PROFILES[role_key]['label']} · {payload.get('company_name', '行业视图')}",
        "query": query,
        "query_type": payload.get("query_type"),
        "role_label": ROLE_PROFILES[role_key]["label"],
        "report_period": payload.get("report_period"),
        "steps_completed": sum(1 for item in agent_flow if item.get("status") == "completed"),
        "step_total": len(agent_flow),
        "data_sources": _build_control_plane_sources(payload),
    }


def _build_agent_route(agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    company_name = payload.get("company_name")
    report_period = payload.get("report_period")
    query_type = payload.get("query_type")
    if agent_name in {"orchestrator", "signal_analyst", "action_planner"} and company_name:
        return {
            "label": "进入企业体检",
            "path": "/score",
            "query": {
                "company": company_name,
                "period": report_period,
            },
        }
    if agent_name == "signal_analyst" and query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk", "query": {}}
    if agent_name == "evidence_auditor":
        evidence_groups = payload.get("evidence_groups", [])
        first_group = evidence_groups[0] if evidence_groups else None
        first_item = first_group["items"][0] if first_group and first_group.get("items") else None
        if first_item:
            return {
                "label": "打开证据",
                "path": f"/evidence/{first_item['chunk_id']}",
                "query": {
                    "context": first_group.get("title", "证据"),
                    "anchors": "|".join(first_group.get("anchor_terms", [])),
                },
            }
        return {
            "label": "返回工作台",
            "path": "/workspace",
            "query": {},
        }
    if agent_name == "action_planner" and query_type == "claim_verification" and company_name:
        return {
            "label": "进入研报核验",
            "path": "/verify",
            "query": {
                "company": company_name,
            },
        }
    if query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk", "query": {}}
    return {"label": "返回工作台", "path": "/workspace", "query": {}}


def _build_control_plane_sources(payload: dict[str, Any]) -> list[str]:
    query_type = payload.get("query_type")
    if query_type == "company_scoring":
        return ["真实财报指标", "规则引擎", "页级证据", "公式回放"]
    if query_type == "claim_verification":
        return ["真实财报指标", "东方财富研报详情页", "观点核验规则"]
    if query_type == "peer_benchmark":
        return ["真实财报指标", "同子行业公司池", "横向评分结果"]
    if query_type == "risk_scan":
        return ["全公司评分快照", "主周期预警板", "行业研报观察"]
    return ["真实财报指标", "页级证据", "指标直取"]


def _resolve_agent_signal_source(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "真实财报指标 + 风险规则 + 历史报期对比",
        "claim_verification": "真实财报指标 + 研报观点抽取",
        "peer_benchmark": "同子行业公司池 + 分位结果",
        "risk_scan": "主周期公司池 + 历史报期预警板",
        "metric_query": "指标定义 + 页级证据",
        "brief_generation": "评分结果 + 建议动作模板",
    }
    return mapping.get(query_type, "真实财报指标")


def _resolve_agent_signal_tool(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "score_engine",
        "claim_verification": "claim_verifier",
        "peer_benchmark": "benchmark_engine",
        "risk_scan": "risk_scanner",
        "metric_query": "metric_router",
        "brief_generation": "brief_builder",
    }
    return mapping.get(query_type, "signal_router")


def _build_signal_agent_metrics(
    payload: dict[str, Any],
    risk_count: int,
    formula_count: int,
    claim_count: int,
) -> list[dict[str, Any]]:
    query_type = payload.get("query_type")
    if query_type == "company_scoring":
        return [
            {"label": "风险标签", "value": risk_count},
            {"label": "公式链", "value": formula_count},
            {"label": "建议动作", "value": len(payload.get("action_cards", []))},
        ]
    if query_type == "claim_verification":
        return [
            {"label": "匹配观点", "value": sum(1 for item in payload.get("claim_cards", []) if item.get("status") == "match")},
            {"label": "偏差观点", "value": sum(1 for item in payload.get("claim_cards", []) if item.get("status") == "mismatch")},
            {"label": "预测卡", "value": len(payload.get("forecast_cards", []))},
        ]
    if query_type == "peer_benchmark":
        return [
            {"label": "对标公司", "value": len(payload.get("benchmark", []))},
            {"label": "图表", "value": len(payload.get("charts", []))},
            {"label": "关键数", "value": len(payload.get("key_numbers", []))},
        ]
    if query_type == "risk_scan":
        return [
            {"label": "高风险公司", "value": len(payload.get("risk_board", []))},
            {"label": "主动预警", "value": len(payload.get("alert_board", []))},
            {"label": "行业研报组", "value": len(payload.get("industry_research", {}).get("groups", []))},
        ]
    return [
        {"label": "关键结果", "value": len(payload.get("key_numbers", []))},
        {"label": "证据条数", "value": len(payload.get("evidence", []))},
        {"label": "观点条数", "value": claim_count},
    ]


def _strip_markdown(value: str) -> str:
    plain = re.sub(r"[*#`>-]+", " ", value or "")
    plain = re.sub(r"\s+", " ", plain)
    return plain.strip()


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


def _build_document_consumable_sections(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    if source := artifact.get("source"):
        sections.append(
            {
                "section_type": "artifact_provenance",
                "title": "解析来源",
                "count": 1,
                "items": [
                    {
                        "text": "正式结构产物" if source == "standard_ocr" else "历史结构产物",
                        "source": source,
                        "path": artifact.get("ocr_artifact_path"),
                    }
                ],
            }
        )
    if headings := artifact.get("headings"):
        sections.append(
            {
                "section_type": "heading_outline",
                "title": "标题层级",
                "count": len(headings),
                "items": [
                    {
                        "text": item.get("text"),
                        "level": item.get("level"),
                        "page": item.get("page"),
                    }
                    for item in headings[:20]
                ],
            }
        )
    if merges := artifact.get("merge_candidates") or artifact.get("merged_sections"):
        sections.append(
            {
                "section_type": "cross_page_merge",
                "title": "跨页候选",
                "count": len(merges),
                "items": [
                    {
                        "title": item.get("title"),
                        "from_page": item.get("from_page") or item.get("page_start"),
                        "to_page": item.get("to_page") or item.get("page_end"),
                        "reason": item.get("reason"),
                    }
                    for item in merges[:20]
                ],
            }
        )
    if tables := artifact.get("tables"):
        sections.append(
            {
                "section_type": "tables",
                "title": "表格线索",
                "count": len(tables),
                "items": [
                    {
                        "title": item.get("title"),
                        "page": item.get("page"),
                        "continued": item.get("continued"),
                    }
                    for item in tables[:20]
                ],
            }
        )
    if cells := artifact.get("cells"):
        sections.append(
            {
                "section_type": "cells",
                "title": "单元格溯源",
                "count": len(cells),
                "items": cells[:20],
            }
        )
    if not sections and artifact.get("summary"):
        sections.append(
            {
                "section_type": "summary",
                "title": "解析摘要",
                "count": 1,
                "items": [{"text": artifact["summary"]}],
            }
        )
    return sections


def _build_document_artifact_locations(
    job: dict[str, Any], artifact: dict[str, Any]
) -> list[dict[str, Any]]:
    locations = [
        {
            "label": "当前解析产物",
            "kind": "artifact",
            "path": job.get("artifact_path"),
        }
    ]
    if artifact.get("ocr_artifact_path"):
        locations.append(
            {
                "label": "正式 OCR 上游产物",
                "kind": "ocr_artifact",
                "path": artifact.get("ocr_artifact_path"),
            }
        )
    return [item for item in locations if item.get("path")]


def _build_document_artifact_remediation(
    *, stage: str, artifact_source: str | None, artifact: dict[str, Any]
) -> list[dict[str, Any]]:
    if stage != "cell_trace":
        return [
            {
                "title": "继续核验当前阶段产物",
                "detail": "确认摘要、证据导航和页码定位与原报告一致，再推进后续工序。",
            }
        ]
    if artifact_source == "standard_ocr":
        return [
            {
                "title": "核对正式结构产物",
                "detail": "优先核对 ocr_cell_trace 中 tables/cells 的页码、行列号和上游 OCR 产物路径，确保当前结构结果可复算。",
            }
        ]
    return [
        {
            "title": "补齐正式结构产物",
            "detail": "当前尚未形成合法的 tables/cells 结构结果。应先接通正式 OCR 运行时并写入 ocr_cell_trace，再重新运行 cell_trace。",
        }
    ]


def _build_document_evidence_navigation(
    *,
    repository: Any,
    company_name: str,
    report_period: str | None,
    artifact: dict[str, Any],
) -> dict[str, Any] | None:
    get_company = getattr(repository, "get_company", None)
    if get_company is None:
        return _build_document_navigation_unavailable(
            artifact,
            message="当前仓库未提供证据解析能力，暂时不能生成文档证据跳转。",
        )
    company = get_company(company_name, report_period) if report_period else get_company(company_name)
    if company is None:
        return _build_document_navigation_unavailable(
            artifact,
            message="未找到对应公司证据索引，当前无法生成文档证据跳转。",
        )

    candidate_pages = _collect_document_artifact_pages(artifact)
    candidate_chunk_ids = _collect_company_evidence_refs(company)
    selected_items: list[dict[str, Any]] = []
    page_set = set(candidate_pages)
    get_evidence = getattr(repository, "get_evidence", None)
    if get_evidence is not None:
        fallback_item = None
        for chunk_id in candidate_chunk_ids:
            item = get_evidence(chunk_id)
            if item is None:
                continue
            if fallback_item is None:
                fallback_item = item
            if page_set:
                if item.get("page") in page_set:
                    selected_items.append(item)
                    if len(selected_items) >= 5:
                        break
            else:
                selected_items = [item]
                break
        if not selected_items and fallback_item is not None:
            selected_items = [fallback_item]
    else:
        evidence_items = repository.resolve_evidence(candidate_chunk_ids)
        if candidate_pages:
            paged_items = [item for item in evidence_items if item.get("page") in candidate_pages]
        else:
            paged_items = []
        selected_items = paged_items or evidence_items[:1]
    if not selected_items:
        return _build_document_navigation_unavailable(
            artifact,
            message="当前文档结果尚未挂接到正式证据索引，暂时不能直接回看原文。",
        )

    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    links = [
        {
            "chunk_id": item["chunk_id"],
            "label": f"第{item.get('page', '?')}页证据" if item.get("page") else "证据",
            "path": f"/evidence/{item['chunk_id']}",
            "query": {
                "context": "文档升级结果",
                "anchors": "|".join(anchor_terms[:6]),
            },
            "source_title": item.get("source_title"),
            "page": item.get("page"),
        }
        for item in selected_items[:5]
    ]
    return {
        "count": len(links),
        "anchor_terms": anchor_terms[:6],
        "pages": sorted({item.get("page") for item in selected_items if item.get("page") is not None}),
        "links": links,
        "primary_route": links[0] if links else None,
    }


def _build_document_navigation_unavailable(
    artifact: dict[str, Any], *, message: str
) -> dict[str, Any]:
    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    pages = _collect_document_artifact_pages(artifact)
    return {
        "count": 0,
        "status": "blocked",
        "message": message,
        "anchor_terms": anchor_terms[:6],
        "pages": pages,
        "links": [],
        "primary_route": None,
    }


def _collect_document_artifact_pages(artifact: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for heading in artifact.get("headings", []):
        page = heading.get("page")
        if isinstance(page, int):
            pages.append(page)
    for section in artifact.get("merged_sections", []):
        for field in ("page", "page_start", "page_end", "from_page", "to_page"):
            page = section.get(field)
            if isinstance(page, int):
                pages.append(page)
        page_range = section.get("page_range") or []
        for page in page_range:
            if isinstance(page, int):
                pages.append(page)
    for table in artifact.get("tables", []):
        page = table.get("page")
        if isinstance(page, int):
            pages.append(page)
    for cell in artifact.get("cells", []):
        page = cell.get("page")
        if isinstance(page, int):
            pages.append(page)
    return sorted(set(pages))


def _collect_document_artifact_anchor_terms(artifact: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for heading in artifact.get("headings", []):
        text = (heading.get("text") or "").strip()
        if text:
            terms.append(text[:24])
    for section in artifact.get("merged_sections", []):
        title = (section.get("title") or "").strip()
        if title:
            terms.append(title[:24])
    if summary := artifact.get("summary"):
        terms.append(str(summary)[:24])
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _collect_company_evidence_refs(company: dict[str, Any]) -> list[str]:
    chunk_ids: list[str] = []
    if company.get("summary_chunk_id"):
        chunk_ids.append(company["summary_chunk_id"])
    for refs in company.get("metric_evidence", {}).values():
        chunk_ids.extend(refs)
    for refs in company.get("label_evidence", {}).values():
        chunk_ids.extend(refs)
    deduped: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id not in deduped:
            deduped.append(chunk_id)
    return deduped


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


def _research_report_bucket(report: dict[str, Any], available_periods: set[str] | None) -> int:
    inferred_period = _infer_report_period_from_text(report.get("title", ""))
    if inferred_period and (not available_periods or inferred_period in available_periods):
        return 0
    if inferred_period is None:
        return 1
    return 2


def _build_research_report_insight(report: dict[str, Any]) -> dict[str, Any] | None:
    local_path = _resolve_report_local_path(report.get("local_path"))
    if local_path is None or not local_path.exists():
        return None
    report_html = local_path.read_text(encoding="utf-8", errors="ignore")
    payload = _extract_research_payload(report_html)
    report_meta = _build_research_meta(report, payload)
    report_body = _extract_research_body(report_html, payload)
    forecast_cards = _build_forecast_cards(report, report_body, report_meta)
    claim_signal_count = sum(
        1
        for pattern in (
            r"营收(?:同比|\d)",
            r"归母净利润(?:同比|\d)",
            r"扣非归母净利润(?:同比|\d)",
            r"毛利率\d",
        )
        if re.search(pattern, report_body)
    )
    return {
        "report_meta": report_meta,
        "report_body": report_body,
        "forecast_cards": forecast_cards,
        "claim_signal_count": claim_signal_count,
    }


def _resolve_report_local_path(raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    normalized = Path(str(raw_path).replace("\\", "/"))
    if normalized.is_absolute():
        return normalized
    return (Path.cwd() / normalized).resolve()


def _research_report_content_score(report: dict[str, Any]) -> tuple[int, int]:
    insight = _build_research_report_insight(report)
    if insight is None:
        return (0, 0)
    return (len(insight["forecast_cards"]), insight["claim_signal_count"])


def _extract_research_rating(report_body: str, payload: dict[str, Any]) -> dict[str, str]:
    match = re.search(
        r'(维持|上调至|上调为|下调至|下调为|首次覆盖给予|首次给予|给予)?[“”"]([^“”"，。]{2,8})[“”"]?评级',
        report_body,
    )
    if match and "投资" not in match.group(2):
        return {
            "action": (match.group(1) or "").strip(),
            "label": match.group(2).strip(),
        }
    rating_code = payload.get("rating")
    if isinstance(rating_code, str) and re.fullmatch(r"[A-Z]{1,3}", rating_code):
        return {}
    if rating_code:
        return {"action": "", "label": str(rating_code)}
    return {}


def _classify_rating_action(action: str | None) -> str | None:
    if not action:
        return None
    if action.startswith("上调"):
        return "上调"
    if action.startswith("下调"):
        return "下调"
    if action.startswith("首次"):
        return "首次覆盖"
    if action.startswith("给予"):
        return "首次给出"
    if action.startswith("维持"):
        return "维持"
    return action


def _extract_target_price(report_body: str) -> dict[str, Any]:
    match = re.search(r"目标价(?:为|至)?\s*([0-9]+(?:\.[0-9]+)?)元", report_body)
    if match is None:
        return {}
    return {
        "value": float(match.group(1)),
        "excerpt": _clip_claim_excerpt(report_body, match.group(0), radius=180),
    }


def _normalize_research_text(text: str) -> str:
    cleaned = unescape(text).replace("&nbsp;", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


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


def _gold_data_root(settings: Settings) -> Path:
    configured = getattr(settings, "gold_data_path", None)
    if isinstance(configured, Path):
        return configured
    silver_root = settings.silver_data_path
    return silver_root.parent.parent / "gold" / silver_root.name


def _load_manifest_generated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    generated_at = payload.get("generated_at")
    return generated_at if isinstance(generated_at, str) else None


def _parse_calendar_date(value: str | None) -> date | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    normalized = candidate.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _map_subindustry_topics(subindustry: str | None) -> tuple[str, ...]:
    if not subindustry:
        return ()
    normalized = str(subindustry).strip()
    topics: list[str] = []
    for key, names in SUBINDUSTRY_SIGNAL_TOPICS.items():
        if key in normalized:
            topics.extend(names)
    if not topics and "电池" in normalized:
        topics.append("电池")
    if not topics and "金属" in normalized:
        topics.append("能源金属")
    return tuple(dict.fromkeys(topics))


def _describe_external_signal_freshness(latest_publish_date: str | None) -> tuple[str, str]:
    latest_date = _parse_calendar_date(latest_publish_date)
    if latest_date is None:
        return "unavailable", "未检测到正式外部信号"
    age_days = max(0, (datetime.now(UTC).date() - latest_date).days)
    if age_days <= 1:
        return "fresh", "近 24 小时有更新"
    if age_days <= 3:
        return "recent", f"{age_days} 天内有更新"
    if age_days <= 7:
        return "warm", f"最近 {age_days} 天有更新"
    return "stale", f"最近更新距今 {age_days} 天"


def _normalize_external_signal(
    record: dict[str, Any],
    *,
    kind: str,
    status: str,
    source_name: str,
    tone: str,
) -> dict[str, Any]:
    company_name = record.get("company_name") or record.get("industry_name") or "行业信号"
    headline = record.get("title")
    if not headline and kind == "company_snapshot":
        headline = f"{company_name} 公司快照已更新"
    return {
        "kind": kind,
        "company_name": company_name,
        "headline": headline or "外部信号已更新",
        "status": status,
        "tone": tone,
        "source_name": source_name,
        "publish_date": record.get("publish_date"),
        "source_url": record.get("source_url"),
        "security_code": record.get("security_code"),
        "subindustry": record.get("subindustry"),
    }


def _build_external_signal_stream(
    settings: Settings,
    *,
    focus_companies: list[dict[str, Any]],
    limit: int = 8,
) -> dict[str, Any]:
    manifests_root = settings.official_data_path / "manifests"
    company_names = {
        str(item.get("company_name")).strip()
        for item in focus_companies
        if item.get("company_name")
    }
    focus_topics: set[str] = set()
    for item in focus_companies:
        focus_topics.update(_map_subindustry_topics(item.get("subindustry")))

    periodic_path = manifests_root / "periodic_reports_manifest.json"
    research_path = manifests_root / "research_reports_manifest.json"
    industry_path = manifests_root / "industry_research_reports_manifest.json"
    snapshot_path = manifests_root / "company_snapshots_manifest.json"

    filtered_periodic = [
        _normalize_external_signal(
            record,
            kind="periodic_report",
            status="交易所公告",
            source_name="上交所公告" if record.get("source") == "SSE" else "深交所公告",
            tone="warning",
        )
        for record in _load_manifest_records(periodic_path)
        if not company_names or record.get("company_name") in company_names
    ]
    filtered_research = [
        _normalize_external_signal(
            record,
            kind="company_research",
            status="券商研报",
            source_name="东方财富研报",
            tone="accent",
        )
        for record in _load_manifest_records(research_path)
        if not company_names or record.get("company_name") in company_names
    ]
    filtered_industry = [
        _normalize_external_signal(
            record,
            kind="industry_research",
            status="行业研报",
            source_name="东方财富行业研报",
            tone="success",
        )
        for record in _load_manifest_records(industry_path)
        if not focus_topics
        or (record.get("industry_name") or record.get("company_name")) in focus_topics
    ]
    filtered_snapshots = [
        _normalize_external_signal(
            record,
            kind="company_snapshot",
            status="公司快照",
            source_name="巨潮资讯",
            tone="default",
        )
        for record in _load_manifest_records(snapshot_path)
        if not company_names or record.get("company_name") in company_names
    ]

    latest_by_entity: dict[tuple[str, str], dict[str, Any]] = {}
    for signal in filtered_periodic + filtered_research + filtered_snapshots:
        key = (signal["kind"], signal["company_name"])
        current = latest_by_entity.get(key)
        current_date = _parse_calendar_date(current.get("publish_date")) if current else None
        candidate_date = _parse_calendar_date(signal.get("publish_date"))
        if current is None or (candidate_date and (current_date is None or candidate_date > current_date)):
            latest_by_entity[key] = signal

    latest_industry: dict[str, dict[str, Any]] = {}
    for signal in filtered_industry:
        key = signal["company_name"]
        current = latest_industry.get(key)
        current_date = _parse_calendar_date(current.get("publish_date")) if current else None
        candidate_date = _parse_calendar_date(signal.get("publish_date"))
        if current is None or (candidate_date and (current_date is None or candidate_date > current_date)):
            latest_industry[key] = signal

    signals = list(latest_by_entity.values()) + list(latest_industry.values())
    signals.sort(
        key=lambda item: (
            _parse_calendar_date(item.get("publish_date")) or date.min,
            -EXTERNAL_SIGNAL_PRIORITY.get(item.get("kind") or "", 99),
            item.get("company_name") or "",
        ),
        reverse=True,
    )

    deduped_signals: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in signals:
        signal_key = (
            item.get("kind") or "",
            item.get("company_name") or "",
            item.get("headline") or "",
        )
        if signal_key in seen_keys:
            continue
        seen_keys.add(signal_key)
        deduped_signals.append(item)
        if len(deduped_signals) >= limit:
            break

    latest_publish_date = max(
        (
            item.get("publish_date")
            for item in deduped_signals
            if _parse_calendar_date(item.get("publish_date")) is not None
        ),
        default=None,
    )
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_publish_date)
    manifest_generated_at = max(
        (
            timestamp
            for timestamp in (
                _load_manifest_generated_at(periodic_path),
                _load_manifest_generated_at(research_path),
                _load_manifest_generated_at(industry_path),
                _load_manifest_generated_at(snapshot_path),
            )
            if _parse_iso_timestamp(timestamp) is not None
        ),
        default=None,
        key=lambda item: _parse_iso_timestamp(item) or datetime.min.replace(tzinfo=UTC),
    )
    source_counter = {
        "交易所公告": sum(1 for item in deduped_signals if item["kind"] == "periodic_report"),
        "券商研报": sum(1 for item in deduped_signals if item["kind"] == "company_research"),
        "行业研报": sum(1 for item in deduped_signals if item["kind"] == "industry_research"),
        "公司快照": sum(1 for item in deduped_signals if item["kind"] == "company_snapshot"),
    }
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": manifest_generated_at,
        "latest_publish_date": latest_publish_date,
        "signal_count": len(deduped_signals),
        "focus_companies": sorted(company_names),
        "sources": [
            {"label": label, "count": count}
            for label, count in source_counter.items()
            if count
        ],
        "signals": deduped_signals,
    }


def _build_external_signal_market_tape(
    external_signal_stream: dict[str, Any],
) -> list[dict[str, Any]]:
    if not external_signal_stream.get("signal_count"):
        return [
            {
                "label": "外部信号",
                "value": "0",
                "delta": "未检测到正式外部信号",
                "tone": "risk",
            }
        ]
    sources = external_signal_stream.get("sources", [])
    tone = "risk" if external_signal_stream.get("status") == "stale" else "success"
    latest_publish_date = external_signal_stream.get("latest_publish_date") or "未知"
    return [
        {
            "label": "外部信号",
            "value": str(external_signal_stream["signal_count"]),
            "delta": f"最新发布日期 {latest_publish_date}",
            "tone": tone,
        },
        {
            "label": "官方源刷新",
            "value": external_signal_stream.get("freshness_label") or "未知",
            "delta": f"{len(sources)} 类正式来源",
            "tone": tone,
        },
    ]


def _build_kafka_signal_runtime(settings: Settings) -> dict[str, Any]:
    bootstrap_servers = str(getattr(settings, "kafka_bootstrap_servers", "") or "").strip()
    topic = str(getattr(settings, "kafka_signal_topic", "opspilot.external_signals") or "opspilot.external_signals").strip()
    base_payload = {
        "bootstrap_servers": bootstrap_servers,
        "topic": topic,
        "partition_count": 0,
        "message_count": 0,
        "latest_publish_date": None,
        "latest_event_time": None,
        "latest_company_name": None,
        "latest_headline": None,
        "latest_signal_status": None,
    }
    if not bootstrap_servers:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 未配置",
        }
    if KafkaConsumer is None or TopicPartition is None:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 依赖未安装",
        }

    consumer = KafkaConsumer(
        bootstrap_servers=[item.strip() for item in bootstrap_servers.split(",") if item.strip()],
        enable_auto_commit=False,
        auto_offset_reset="latest",
        consumer_timeout_ms=1200,
        request_timeout_ms=5000,
        api_version_auto_timeout_ms=5000,
        metadata_max_age_ms=5000,
    )
    try:
        partitions = consumer.partitions_for_topic(topic)
        if not partitions:
            return {
                **base_payload,
                "status": "unavailable",
                "freshness_label": "Kafka Topic 未发现",
            }

        topic_partitions = [TopicPartition(topic, partition) for partition in sorted(partitions)]
        end_offsets = consumer.end_offsets(topic_partitions)
        latest_candidates: list[dict[str, Any]] = []
        for topic_partition in topic_partitions:
            end_offset = int(end_offsets.get(topic_partition, 0) or 0)
            if end_offset <= 0:
                continue
            consumer.assign([topic_partition])
            consumer.seek(topic_partition, max(0, end_offset - 3))
            polled = consumer.poll(timeout_ms=600, max_records=3)
            for records in polled.values():
                for record in records:
                    decoded = _decode_kafka_signal_record(record.value)
                    if decoded is None:
                        continue
                    decoded["partition"] = getattr(record, "partition", topic_partition.partition)
                    decoded["offset"] = getattr(record, "offset", None)
                    latest_candidates.append(decoded)

        latest_candidates.sort(
            key=lambda item: (
                _parse_iso_timestamp(item.get("event_time")) or datetime.min.replace(tzinfo=UTC),
                _parse_calendar_date(item.get("publish_date")) or date.min,
                item.get("company_name") or "",
            ),
            reverse=True,
        )
        latest_signal = latest_candidates[0] if latest_candidates else {}
        latest_publish_date = latest_signal.get("publish_date")
        freshness_status, freshness_label = (
            _describe_external_signal_freshness(latest_publish_date)
            if latest_publish_date
            else ("stale", "Kafka 消息暂无日期")
        )
        return {
            **base_payload,
            "status": freshness_status,
            "freshness_label": freshness_label,
            "partition_count": len(topic_partitions),
            "message_count": sum(int(offset or 0) for offset in end_offsets.values()),
            "latest_publish_date": latest_publish_date,
            "latest_event_time": latest_signal.get("event_time"),
            "latest_company_name": latest_signal.get("company_name"),
            "latest_headline": latest_signal.get("headline"),
            "latest_signal_status": latest_signal.get("signal_status"),
            "latest_partition": latest_signal.get("partition"),
            "latest_offset": latest_signal.get("offset"),
        }
    except Exception as exc:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 主题不可读",
            "error": str(exc),
        }
    finally:
        consumer.close()


def _decode_kafka_signal_record(value: Any) -> dict[str, Any] | None:
    raw_text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else str(value)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _build_kafka_signal_market_tape(kafka_signal_runtime: dict[str, Any]) -> list[dict[str, Any]]:
    if kafka_signal_runtime.get("status") == "unavailable":
        return [
            {
                "label": "Kafka 主题",
                "value": "未接通",
                "delta": kafka_signal_runtime.get("freshness_label") or "Kafka 未就绪",
                "tone": "risk",
            }
        ]
    latest_anchor = (
        kafka_signal_runtime.get("latest_publish_date")
        or kafka_signal_runtime.get("latest_event_time")
        or "等待新消息"
    )
    tone = "risk" if kafka_signal_runtime.get("status") == "stale" else "success"
    return [
        {
            "label": "Kafka 主题",
            "value": str(kafka_signal_runtime.get("message_count") or 0),
            "delta": f"{kafka_signal_runtime.get('partition_count') or 0} 分区 · {latest_anchor}",
            "tone": tone,
        },
        {
            "label": "实时流状态",
            "value": kafka_signal_runtime.get("freshness_label") or "未知",
            "delta": kafka_signal_runtime.get("latest_company_name") or kafka_signal_runtime.get("topic") or "等待消息",
            "tone": tone,
        },
    ]


def _load_company_signal_snapshot(
    settings: Settings,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    snapshot_path = settings.silver_data_path / "stream" / "company_signal_snapshot.json"
    if not snapshot_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "流式热点快照未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "top_companies": [],
        }
    with snapshot_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    company_records = [
        item
        for item in records
        if item.get("company_name") and str(item.get("security_code") or "").upper() != "INDUSTRY"
    ]
    company_records.sort(
        key=lambda item: (
            int(item.get("external_heat") or 0),
            int(item.get("signal_count") or 0),
            _parse_iso_timestamp(item.get("latest_event_time")) or datetime.min.replace(tzinfo=UTC),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    latest_event_date = max(
        (
            _parse_calendar_date(item.get("latest_event_time"))
            for item in company_records
            if _parse_calendar_date(item.get("latest_event_time")) is not None
        ),
        default=None,
    )
    latest_event_text = latest_event_date.isoformat() if latest_event_date else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_text)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_text,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "top_companies": company_records[:limit],
    }


def _load_company_signal_timeline(
    settings: Settings,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    timeline_path = _gold_data_root(settings) / "stream" / "company_signal_timeline.json"
    if not timeline_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "公司时序热度未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "date_axis": [],
            "top_companies": [],
        }
    with timeline_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    latest_event_date = payload.get("date_axis", [])[-1] if payload.get("date_axis") else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_date)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_date,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "date_axis": payload.get("date_axis", []),
        "top_companies": [item for item in payload.get("top_companies", records[:limit]) if isinstance(item, dict)][:limit],
    }


def _load_subindustry_signal_heatmap(settings: Settings) -> dict[str, Any]:
    heatmap_path = _gold_data_root(settings) / "stream" / "subindustry_signal_heatmap.json"
    if not heatmap_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "子行业热度迁移未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "date_axis": [],
            "top_subindustries": [],
        }
    with heatmap_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    latest_event_date = payload.get("date_axis", [])[-1] if payload.get("date_axis") else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_date)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_date,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "date_axis": payload.get("date_axis", []),
        "top_subindustries": [item for item in payload.get("top_subindustries", records[:6]) if isinstance(item, dict)],
    }


def _build_company_signal_graph_context(
    settings: Settings,
    *,
    company_name: str,
    subindustry: str | None = None,
) -> dict[str, Any]:
    snapshot = _load_company_signal_snapshot(settings, limit=256)
    timeline = _load_company_signal_timeline(settings, limit=256)
    heatmap = _load_subindustry_signal_heatmap(settings)
    snapshot_item = next(
        (
            item
            for item in snapshot.get("top_companies", [])
            if str(item.get("company_name") or "").strip() == company_name
        ),
        {},
    )
    timeline_item = next(
        (
            item
            for item in timeline.get("top_companies", [])
            if str(item.get("company_name") or "").strip() == company_name
        ),
        {},
    )
    resolved_subindustry = (
        str(timeline_item.get("subindustry") or snapshot_item.get("subindustry") or subindustry or "").strip()
    )
    subindustry_item = next(
        (
            item
            for item in heatmap.get("top_subindustries", [])
            if str(item.get("subindustry") or "").strip() == resolved_subindustry
        ),
        {},
    )
    latest_event_time = timeline_item.get("latest_event_time") or snapshot_item.get("latest_event_time")
    latest_event_date = _parse_calendar_date(str(latest_event_time) if latest_event_time is not None else None)
    freshness_status, freshness_label = _describe_external_signal_freshness(
        latest_event_date.isoformat() if latest_event_date is not None else None
    )
    window_days = max(
        len(timeline.get("date_axis", [])),
        len(timeline_item.get("timeline", [])) if isinstance(timeline_item.get("timeline"), list) else 0,
        len(subindustry_item.get("timeline", [])) if isinstance(subindustry_item.get("timeline"), list) else 0,
    )
    signal_count = int(timeline_item.get("signal_count") or snapshot_item.get("signal_count") or 0)
    source_count = int(snapshot_item.get("source_count") or 0)
    total_heat = int(timeline_item.get("total_heat") or snapshot_item.get("external_heat") or 0)
    latest_heat = int(
        timeline_item.get("latest_heat")
        or (
            timeline_item.get("timeline", [])[-1].get("external_heat", 0)
            if timeline_item.get("timeline")
            else 0
        )
        or 0
    )
    momentum = int(timeline_item.get("momentum") or 0)
    active_days = int(timeline_item.get("active_days") or 0)
    latest_headline = (
        timeline_item.get("latest_headline")
        or snapshot_item.get("latest_headline")
        or None
    )
    signal_status = (
        timeline_item.get("latest_signal_status")
        or snapshot_item.get("latest_signal_status")
        or None
    )
    latest_signal_kind = (
        timeline_item.get("latest_signal_kind")
        or snapshot_item.get("latest_signal_kind")
        or None
    )
    subindustry_signal_count = int(subindustry_item.get("signal_count") or 0)
    subindustry_total_heat = int(subindustry_item.get("total_heat") or 0)
    subindustry_latest_heat = int(subindustry_item.get("latest_heat") or 0)
    subindustry_momentum = int(subindustry_item.get("momentum") or 0)
    subindustry_active_days = int(subindustry_item.get("active_days") or 0)
    return {
        "available": bool(snapshot_item or timeline_item or subindustry_item),
        "event_available": bool(snapshot_item or timeline_item),
        "timeline_available": bool(timeline_item),
        "subindustry_available": bool(subindustry_item),
        "subindustry": resolved_subindustry or None,
        "freshness_status": freshness_status,
        "freshness_label": freshness_label,
        "latest_event_time": latest_event_time,
        "latest_headline": latest_headline,
        "signal_status": signal_status,
        "latest_signal_kind": latest_signal_kind,
        "signal_count": signal_count,
        "source_count": source_count,
        "total_heat": total_heat,
        "latest_heat": latest_heat,
        "momentum": momentum,
        "active_days": active_days,
        "window_days": window_days,
        "date_axis": timeline.get("date_axis", []),
        "event_summary": (
            f"{signal_status or '外部信号'}：{latest_headline or '最近事件已更新'}；"
            f"{freshness_label}，累计 {signal_count} 条正式信号。"
        ),
        "timeline_summary": (
            f"近 {window_days or 7} 日信号 {signal_count} 条，累计热度 {total_heat}，"
            f"动量 {momentum}，活跃 {active_days} 天。"
        ),
        "subindustry_signal_count": subindustry_signal_count,
        "subindustry_total_heat": subindustry_total_heat,
        "subindustry_latest_heat": subindustry_latest_heat,
        "subindustry_momentum": subindustry_momentum,
        "subindustry_active_days": subindustry_active_days,
        "subindustry_summary": (
            f"{resolved_subindustry or '所属子行业'} 近 {window_days or 7} 日总热度 {subindustry_total_heat}，"
            f"最新窗口热度 {subindustry_latest_heat}，动量 {subindustry_momentum}。"
        ),
    }


def _build_streaming_heat_chart(heatmap: dict[str, Any]) -> dict[str, Any]:
    date_axis = heatmap.get("date_axis", [])
    rows = heatmap.get("top_subindustries", [])[:4]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {
            "textStyle": {"color": "#94a3b8"},
            "data": [item.get("subindustry", "未分类") for item in rows],
        },
        "grid": {"left": 48, "right": 24, "top": 48, "bottom": 36},
        "xAxis": {
            "type": "category",
            "data": date_axis,
            "axisLine": {"lineStyle": {"color": "#334155"}},
            "axisLabel": {"color": "#94a3b8"},
        },
        "yAxis": {
            "type": "value",
            "axisLine": {"lineStyle": {"color": "#334155"}},
            "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.16)"}},
            "axisLabel": {"color": "#94a3b8"},
        },
        "series": [
            {
                "name": item.get("subindustry", "未分类"),
                "type": "line",
                "smooth": True,
                "showSymbol": False,
                "areaStyle": {"opacity": 0.12},
                "data": [point.get("external_heat", 0) for point in item.get("timeline", [])],
            }
            for item in rows
        ],
    }


def _build_streaming_anomaly_board(
    *,
    preferred_period: str,
    top_risk_companies: list[dict[str, Any]],
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    signal_heatmap: dict[str, Any],
    kafka_signal_runtime: dict[str, Any],
    limit: int = 6,
) -> dict[str, Any]:
    risk_by_company = {
        str(item.get("company_name")): item
        for item in top_risk_companies
        if item.get("company_name")
    }
    snapshot_by_company = {
        str(item.get("company_name")): item
        for item in signal_snapshot.get("top_companies", [])
        if item.get("company_name")
    }
    timeline_by_company = {
        str(item.get("company_name")): item
        for item in signal_timeline.get("top_companies", [])
        if item.get("company_name")
    }
    heat_by_subindustry = {
        str(item.get("subindustry")): item
        for item in signal_heatmap.get("top_subindustries", [])
        if item.get("subindustry")
    }
    ordered_names: list[str] = []
    for bucket in (
        signal_timeline.get("top_companies", []),
        signal_snapshot.get("top_companies", []),
        top_risk_companies,
    ):
        for item in bucket:
            company_name = str(item.get("company_name") or "").strip()
            if company_name and company_name not in ordered_names:
                ordered_names.append(company_name)

    status, freshness_label = _summarize_streaming_anomaly_status(
        signal_snapshot=signal_snapshot,
        signal_timeline=signal_timeline,
        signal_heatmap=signal_heatmap,
        kafka_signal_runtime=kafka_signal_runtime,
    )
    items: list[dict[str, Any]] = []
    live_company = (
        str(kafka_signal_runtime.get("latest_company_name") or "").strip()
        if kafka_signal_runtime.get("status") == "fresh"
        else ""
    )
    for company_name in ordered_names:
        snapshot_item = snapshot_by_company.get(company_name, {})
        timeline_item = timeline_by_company.get(company_name, {})
        risk_item = risk_by_company.get(company_name, {})
        subindustry = (
            timeline_item.get("subindustry")
            or snapshot_item.get("subindustry")
            or risk_item.get("subindustry")
        )
        sector_item = heat_by_subindustry.get(str(subindustry), {})
        timeline_points = [
            int(point.get("external_heat") or 0)
            for point in timeline_item.get("timeline", [])
            if isinstance(point, dict)
        ]
        previous_points = timeline_points[:-1]
        latest_window_heat = int(
            timeline_item.get("latest_heat")
            or (timeline_points[-1] if timeline_points else 0)
        )
        baseline_heat = _safe_average(previous_points)
        burst_ratio = round(latest_window_heat / max(1.0, baseline_heat), 2) if latest_window_heat else 0.0
        signal_count = int(timeline_item.get("signal_count") or snapshot_item.get("signal_count") or 0)
        source_count = int(snapshot_item.get("source_count") or 0)
        external_heat = int(timeline_item.get("total_heat") or snapshot_item.get("external_heat") or 0)
        momentum = int(timeline_item.get("momentum") or 0)
        active_days = int(timeline_item.get("active_days") or 0)
        risk_count = int(risk_item.get("risk_count") or 0)
        risk_labels = list(risk_item.get("risk_labels") or [])
        sector_latest_heat = int(sector_item.get("latest_heat") or 0)
        sector_momentum = int(sector_item.get("momentum") or 0)
        is_live_company = bool(live_company and live_company == company_name)

        score = 0
        triggers: list[str] = []
        if latest_window_heat >= 3:
            score += 18
            triggers.append("最新窗口热度抬升")
        if external_heat >= 4:
            score += 14
            triggers.append("总热度进入高位")
        if momentum >= 4:
            score += min(18, momentum * 4)
            triggers.append("热度动量持续为正")
        if active_days and active_days <= 2 and signal_count >= 2:
            score += 14
            triggers.append(f"{active_days} 天内形成密集信号")
        if source_count >= 2:
            score += 12
            triggers.append(f"{source_count} 类正式来源共振")
        if burst_ratio >= 2 and latest_window_heat >= 2:
            score += 10
            triggers.append(f"窗口热度较基线放大 {burst_ratio} 倍")
        if risk_count >= 3:
            score += 14
            triggers.append(f"{risk_count} 个经营风险标签共振")
        elif risk_count > 0:
            score += 6
            triggers.append(f"叠加 {risk_count} 个经营风险标签")
        if sector_latest_heat >= 3 or sector_momentum >= 4:
            score += 8
            triggers.append(f"{subindustry or '所属板块'} 同步升温")
        if is_live_company:
            score += 8
            triggers.append("Kafka 实时流刚命中该公司")

        if score < 24:
            continue

        severity = _classify_streaming_anomaly_severity(score)
        anomaly_type = _classify_streaming_anomaly_type(
            burst_ratio=burst_ratio,
            risk_count=risk_count,
            source_count=source_count,
            sector_latest_heat=sector_latest_heat,
            latest_window_heat=latest_window_heat,
        )
        status_label = {
            "critical": "高危异动",
            "high": "重点异动",
            "medium": "持续异动",
            "low": "轻度异动",
        }.get(severity, "异动跟踪")
        items.append(
            {
                "company_name": company_name,
                "subindustry": subindustry,
                "headline": (
                    timeline_item.get("latest_headline")
                    or snapshot_item.get("latest_headline")
                    or (risk_labels[0] if risk_labels else "继续跟踪")
                ),
                "signal_status": (
                    timeline_item.get("latest_signal_status")
                    or snapshot_item.get("latest_signal_status")
                    or "风险跟踪"
                ),
                "severity": severity,
                "status_label": status_label,
                "tone": "risk" if severity in {"critical", "high"} else "warning",
                "score": score,
                "anomaly_type": anomaly_type,
                "summary": _summarize_streaming_anomaly(
                    company_name=company_name,
                    signal_status=timeline_item.get("latest_signal_status")
                    or snapshot_item.get("latest_signal_status"),
                    signal_count=signal_count,
                    source_count=source_count,
                    external_heat=external_heat,
                    latest_window_heat=latest_window_heat,
                    burst_ratio=burst_ratio,
                    risk_count=risk_count,
                    subindustry=subindustry,
                ),
                "triggers": triggers[:4],
                "evidence": [
                    f"热度 {latest_window_heat}/{external_heat}（窗口/累计）",
                    f"信号 {signal_count} 条 · 来源 {source_count} 类 · 活跃 {active_days} 天",
                    f"风险标签 {risk_count} 个",
                ],
                "risk_count": risk_count,
                "risk_labels": risk_labels[:3],
                "signal_count": signal_count,
                "source_count": source_count,
                "external_heat": external_heat,
                "latest_heat": latest_window_heat,
                "momentum": momentum,
                "active_days": active_days,
                "burst_ratio": burst_ratio,
                "latest_event_time": timeline_item.get("latest_event_time")
                or snapshot_item.get("latest_event_time"),
                "route": {
                    "path": "/score",
                    "query": {"company": company_name, "period": preferred_period},
                },
            }
        )
    items.sort(
        key=lambda item: (
            _streaming_anomaly_severity_rank(item.get("severity")),
            int(item.get("score") or 0),
            int(item.get("external_heat") or 0),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    summary = {
        "detected_count": len(items),
        "critical_count": sum(1 for item in items if item.get("severity") == "critical"),
        "high_count": sum(1 for item in items if item.get("severity") == "high"),
        "medium_count": sum(1 for item in items if item.get("severity") == "medium"),
        "risk_resonance_count": sum(
            1 for item in items if "风险" in str(item.get("anomaly_type") or "")
        ),
        "cross_source_count": sum(1 for item in items if int(item.get("source_count") or 0) >= 2),
    }
    summary["focus_line"] = (
        f"检测到 {summary['detected_count']} 家流式异动公司，"
        f"其中 {summary['critical_count'] + summary['high_count']} 家需优先处置。"
        if summary["detected_count"]
        else "当前流式快照未发现高优先级异动公司。"
    )
    return {
        "status": status,
        "freshness_label": freshness_label,
        "summary": summary,
        "items": items[:limit],
    }


def _safe_average(values: list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _summarize_streaming_anomaly_status(
    *,
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    signal_heatmap: dict[str, Any],
    kafka_signal_runtime: dict[str, Any],
) -> tuple[str, str]:
    statuses = [
        str(signal_snapshot.get("status") or ""),
        str(signal_timeline.get("status") or ""),
        str(signal_heatmap.get("status") or ""),
    ]
    if not any(status in {"fresh", "stale"} for status in statuses):
        return ("unavailable", "流式异动引擎未就绪")
    if any(status == "stale" for status in statuses):
        return ("stale", "流式异动基线已过期")
    if kafka_signal_runtime.get("status") == "fresh":
        return ("fresh", "流式异动实时订阅中")
    return ("fresh", "流式异动快照已更新")


def _classify_streaming_anomaly_type(
    *,
    burst_ratio: float,
    risk_count: int,
    source_count: int,
    sector_latest_heat: int,
    latest_window_heat: int,
) -> str:
    if risk_count >= 3 and source_count >= 2:
        return "风险共振"
    if burst_ratio >= 2 and latest_window_heat >= 2:
        return "新发脉冲"
    if sector_latest_heat >= 3:
        return "板块传导"
    if source_count >= 2:
        return "跨源汇聚"
    return "持续抬升"


def _classify_streaming_anomaly_severity(score: int) -> str:
    if score >= 64:
        return "critical"
    if score >= 46:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _streaming_anomaly_severity_rank(level: Any) -> int:
    return {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(str(level or ""), 0)


def _summarize_streaming_anomaly(
    *,
    company_name: str,
    signal_status: str | None,
    signal_count: int,
    source_count: int,
    external_heat: int,
    latest_window_heat: int,
    burst_ratio: float,
    risk_count: int,
    subindustry: str | None,
) -> str:
    summary = (
        f"{company_name} 在 {subindustry or '当前板块'} 出现 {signal_status or '正式信号'} 异动，"
        f"窗口热度 {latest_window_heat}、累计热度 {external_heat}。"
    )
    if burst_ratio >= 2:
        summary += f" 当前窗口相对历史基线放大 {burst_ratio} 倍。"
    if signal_count or source_count:
        summary += f" 近窗共捕获 {signal_count} 条信号、{source_count} 类来源。"
    if risk_count:
        summary += f" 同时叠加 {risk_count} 个经营风险标签。"
    return summary


def _build_streaming_anomaly_market_tape(
    streaming_anomalies: dict[str, Any],
) -> list[dict[str, Any]]:
    summary = streaming_anomalies.get("summary", {})
    detected_count = int(summary.get("detected_count") or 0)
    if detected_count <= 0:
        return []
    high_priority = int(summary.get("critical_count") or 0) + int(summary.get("high_count") or 0)
    tone = "risk" if high_priority else "accent"
    return [
        {
            "label": "流式异动",
            "value": str(detected_count),
            "delta": streaming_anomalies.get("freshness_label") or "异动快照已更新",
            "tone": tone,
        },
        {
            "label": "高优先级共振",
            "value": str(high_priority),
            "delta": f"{summary.get('cross_source_count', 0)} 家跨源共振",
            "tone": "risk" if high_priority else tone,
        },
    ]


def _merge_streaming_anomalies_into_attention_matrix(
    attention_matrix: list[dict[str, Any]],
    streaming_anomalies: dict[str, Any],
) -> list[dict[str, Any]]:
    anomaly_by_company = {
        str(item.get("company_name")): item
        for item in streaming_anomalies.get("items", [])
        if item.get("company_name")
    }
    merged: list[dict[str, Any]] = []
    for item in attention_matrix:
        company_name = str(item.get("company_name") or "")
        anomaly = anomaly_by_company.get(company_name)
        if anomaly is None:
            merged.append(item)
            continue
        merged.append(
            {
                **item,
                "anomaly_score": anomaly.get("score"),
                "anomaly_type": anomaly.get("anomaly_type"),
                "anomaly_severity": anomaly.get("severity"),
                "anomaly_summary": anomaly.get("summary"),
            }
        )
    return merged


def _build_streaming_attention_matrix(
    *,
    preferred_period: str,
    top_risk_companies: list[dict[str, Any]],
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    limit: int = 4,
) -> list[dict[str, Any]]:
    risk_by_company = {
        str(item.get("company_name")): item
        for item in top_risk_companies
        if item.get("company_name")
    }
    snapshot_by_company = {
        str(item.get("company_name")): item
        for item in signal_snapshot.get("top_companies", [])
        if item.get("company_name")
    }
    timeline_by_company = {
        str(item.get("company_name")): item
        for item in signal_timeline.get("top_companies", [])
        if item.get("company_name")
    }
    ordered_names: list[str] = []
    for item in signal_timeline.get("top_companies", []):
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    for item in signal_snapshot.get("top_companies", []):
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    for item in top_risk_companies:
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    matrix: list[dict[str, Any]] = []
    for company_name in ordered_names[:limit]:
        risk_item = risk_by_company.get(company_name, {})
        signal_item = snapshot_by_company.get(company_name, {})
        timeline_item = timeline_by_company.get(company_name, {})
        risk_labels = list(risk_item.get("risk_labels") or [])
        matrix.append(
            {
                "company_name": company_name,
                "subindustry": timeline_item.get("subindustry") or signal_item.get("subindustry") or risk_item.get("subindustry"),
                "risk_count": int(risk_item.get("risk_count") or 0),
                "headline": timeline_item.get("latest_headline") or signal_item.get("latest_headline") or (risk_labels[0] if risk_labels else "继续跟踪"),
                "signal_status": timeline_item.get("latest_signal_status") or signal_item.get("latest_signal_status") or "风险跟踪",
                "signal_count": int(timeline_item.get("signal_count") or signal_item.get("signal_count") or 0),
                "external_heat": int(timeline_item.get("total_heat") or signal_item.get("external_heat") or 0),
                "latest_heat": int(timeline_item.get("latest_heat") or 0),
                "momentum": int(timeline_item.get("momentum") or 0),
                "active_days": int(timeline_item.get("active_days") or 0),
                "latest_event_time": timeline_item.get("latest_event_time") or signal_item.get("latest_event_time"),
                "route": risk_item.get(
                    "route",
                    {"path": "/score", "query": {"company": company_name, "period": preferred_period}},
                ),
            }
        )
    return matrix


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


def _settings_ocr_runtime(settings: Settings) -> dict[str, Any]:
    runtime_mode = str(getattr(settings, "ocr_runtime_mode", "local_assets") or "local_assets").strip().lower()
    if runtime_mode not in {"service", "local_assets"}:
        runtime_mode = "local_assets"
    return {
        "provider": getattr(settings, "ocr_provider", "PaddleOCR-VL"),
        "model": getattr(settings, "ocr_model", "PaddleOCR-VL-1.5"),
        "mode": runtime_mode,
        "service_url": str(getattr(settings, "ocr_service_url", "") or "").strip().rstrip("/"),
        "request_timeout_seconds": float(getattr(settings, "ocr_request_timeout_seconds", 120.0)),
        "assets_path": str(getattr(settings, "ocr_assets_path", Path("models/paddleocr-vl"))),
        "runtime_enabled": getattr(settings, "ocr_runtime_enabled", False),
        "layout_engine": getattr(settings, "doc_layout_engine", "PP-DocLayout-V3 + PyMuPDF"),
    }


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


def _load_json_if_possible(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_task_board_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_task_board.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": {}}
        _write_json(manifest_path, payload)
        return payload

    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    payload.setdefault("generated_at", _utcnow_iso())
    payload.setdefault("records", {})
    payload["record_count"] = len(payload["records"])
    return payload


def _write_task_board_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", {}))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_task_board.json"
    _write_json(manifest_path, payload)


def _load_industry_brain_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_industry_brain.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
    }


def _write_industry_brain_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_industry_brain.json"
    _write_json(manifest_path, payload)


def _append_industry_brain_snapshot(settings: Settings, payload: dict[str, Any]) -> None:
    manifest = _load_industry_brain_manifest(settings)
    records = list(manifest.get("records", []))
    records.append(
        {
            "refreshed_at": payload.get("stream", {}).get("refreshed_at"),
            "report_period": payload.get("report_period"),
            "sequence": payload.get("stream", {}).get("sequence"),
            "market_tape": payload.get("market_tape", []),
            "live_events": payload.get("live_events", []),
            "external_signal_stream": payload.get("external_signal_stream", {}),
            "streaming_snapshot": payload.get("streaming_snapshot", {}),
            "streaming_anomalies": payload.get("streaming_anomalies", {}),
            "attention_matrix": payload.get("attention_matrix", []),
            "execution_flash": payload.get("execution_flash", []),
        }
    )
    manifest["records"] = records[-36:]
    _write_industry_brain_manifest(settings, manifest)


def _load_watchboard_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
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


def _write_watchboard_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard.json"
    _write_json(manifest_path, payload)


def _find_watchboard_record(
    settings: Settings,
    *,
    company_name: str,
    user_role: str,
    report_period: str,
) -> dict[str, Any] | None:
    manifest = _load_watchboard_manifest(settings)
    return next(
        (
            item
            for item in manifest["records"]
            if item.get("company_name") == company_name
            and item.get("user_role") == user_role
            and item.get("report_period") == report_period
        ),
        None,
    )


def _load_watchboard_runs_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard_runs.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
        _write_json(manifest_path, payload)
        return payload
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at"),
        "record_count": payload.get("record_count", len(payload.get("records", []))),
        "records": payload.get("records", []),
    }


def _write_watchboard_runs_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_watchboard_runs.json"
    _write_json(manifest_path, payload)


def _build_watchboard_run_id(user_role: str, report_period: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{user_role}-{report_period.lower()}"


def _build_task_id(report_period: str, company_name: str, priority: str, title: str) -> str:
    normalized_title = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", title).strip("-").lower()
    normalized_company = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{report_period}-{normalized_company}-{priority.lower()}-{normalized_title}"[:160]


def _load_alert_board_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_alert_board.json"
    if not manifest_path.exists():
        payload = {"generated_at": _utcnow_iso(), "record_count": 0, "records": {}}
        _write_json(manifest_path, payload)
        return payload

    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    payload.setdefault("generated_at", _utcnow_iso())
    payload.setdefault("records", {})
    payload["record_count"] = len(payload["records"])
    return payload


def _write_alert_board_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", {}))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_alert_board.json"
    _write_json(manifest_path, payload)


def _build_alert_id(alert: dict[str, Any]) -> str:
    normalized_company = re.sub(
        r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", alert["company_name"]
    ).strip("-").lower()
    return (
        f"{alert['report_period']}-{normalized_company}-"
        f"{alert.get('previous_period') or 'na'}-{alert['risk_count']}-{alert['risk_delta']}"
    )[:160]


def _load_document_pipeline_job_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_jobs.json"
    parsed_reports = _load_manifest_records(
        settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    )
    desired_jobs: dict[tuple[str, str], dict[str, Any]] = {}
    for record in parsed_reports:
        report_id = record.get("report_id")
        if not report_id:
            continue
        for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
            artifact_path = _document_pipeline_artifact_path(settings, stage, record)
            status = "pending"
            if artifact_path.exists():
                status = "completed"
            desired_jobs[(report_id, stage)] = {
                "stage": stage,
                "report_id": report_id,
                "company_name": record.get("company_name"),
                "security_code": record.get("security_code"),
                "report_period": _normalize_report_period(record.get("title", "")),
                "page_json_path": record.get("page_json_path"),
                "artifact_path": str(artifact_path),
                "status": status,
            }

    existing_records: dict[tuple[str, str], dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError:
            payload = {"records": []}
        for record in payload.get("records", []):
            existing_records[(record.get("report_id"), record.get("stage"))] = record

    merged_records: list[dict[str, Any]] = []
    for key, desired in desired_jobs.items():
        existing = existing_records.get(key, {})
        merged = {**desired, **existing}
        if desired["status"] == "completed":
            merged["status"] = "completed"
        elif existing.get("status") == "blocked":
            merged["status"] = "blocked"
        else:
            merged["status"] = "pending"
        merged_records.append(merged)

    merged_records.sort(
        key=lambda item: (
            item["status"] == "completed",
            item["company_name"] or "",
            item["report_id"] or "",
            item["stage"],
        )
    )
    payload = {
        "generated_at": _utcnow_iso(),
        "record_count": len(merged_records),
        "records": merged_records,
    }
    _write_json(manifest_path, payload)
    return payload


def _write_document_pipeline_job_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_jobs.json"
    _write_json(manifest_path, payload)


def _load_workspace_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
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


def _write_workspace_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_runs.json"
    _write_json(manifest_path, payload)


def _load_document_pipeline_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
    }


def _write_document_pipeline_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "document_pipeline_runs.json"
    _write_json(manifest_path, payload)


def _build_document_pipeline_run_id(stage: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{stage}-document-run"


def _document_pipeline_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "document_pipeline_runs" / f"{run_id}.json"


def _build_workspace_run_id(company_name: str, query_type: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    query_slug = re.sub(r"[^a-zA-Z0-9_]+", "-", query_type).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-{query_slug}"


def _workspace_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "runs" / f"{run_id}.json"


def _load_stress_test_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "stress_test_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
    }


def _write_stress_test_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "stress_test_runs.json"
    _write_json(manifest_path, payload)


def _build_stress_test_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-stress"


def _stress_test_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "stress_runs" / f"{run_id}.json"


def _load_graph_query_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "graph_query_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
    }


def _write_graph_query_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "graph_query_runs.json"
    _write_json(manifest_path, payload)


def _build_graph_query_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-graph"


def _graph_query_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "graph_runs" / f"{run_id}.json"


def _load_vision_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "vision_analyze_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    with manifest_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return {
        "generated_at": payload.get("generated_at", _utcnow_iso()),
        "record_count": len(payload.get("records", [])),
        "records": payload.get("records", []),
    }


def _write_vision_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "vision_analyze_runs.json"
    _write_json(manifest_path, payload)


def _build_vision_run_id(company_name: str) -> str:
    company_slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", company_name).strip("-").lower()
    return f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{company_slug}-vision"


def _vision_run_detail_path(settings: Settings, run_id: str) -> Path:
    return settings.bronze_data_path / "vision_runs" / f"{run_id}.json"


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


def _run_document_pipeline_job(
    stage: str, job: dict[str, Any], settings: Settings
) -> tuple[dict[str, Any], Path]:
    page_json_path = Path(str(job["page_json_path"]).replace("\\", "/"))
    if not page_json_path.is_absolute():
        page_json_path = (Path.cwd() / page_json_path).resolve()
    with page_json_path.open("r", encoding="utf-8") as file:
        page_payload = json.load(file)

    if stage == "cross_page_merge":
        artifact_payload = _build_cross_page_merge_artifact(job, page_payload)
    elif stage == "title_hierarchy":
        artifact_payload = _build_title_hierarchy_artifact(job, page_payload)
    else:
        artifact_payload = _build_cell_trace_artifact(job, page_payload, settings=settings)
    artifact_path = _document_pipeline_artifact_path(settings, stage, job)
    _write_json(artifact_path, artifact_payload)
    return artifact_payload, artifact_path


def _build_cross_page_merge_artifact(job: dict[str, Any], page_payload: dict[str, Any]) -> dict[str, Any]:
    pages = page_payload.get("pages", [])
    candidates: list[dict[str, Any]] = []
    for previous_page, current_page in zip(pages, pages[1:]):
        tail_text = _last_meaningful_block_text(previous_page.get("blocks", []))
        head_text = _first_meaningful_block_text(current_page.get("blocks", []))
        if not tail_text or not head_text:
            continue
        if _looks_like_cross_page_continuation(tail_text, head_text):
            candidates.append(
                {
                    "from_page": previous_page.get("page"),
                    "to_page": current_page.get("page"),
                    "tail_text": tail_text,
                    "head_text": head_text,
                    "reason": "页尾未闭合且下一页延续正文/表格。",
                }
            )
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "summary": f"识别出 {len(candidates)} 组跨页续写候选。",
        "merge_candidates": candidates,
    }


def _build_title_hierarchy_artifact(job: dict[str, Any], page_payload: dict[str, Any]) -> dict[str, Any]:
    headings: list[dict[str, Any]] = []
    for page in page_payload.get("pages", []):
        for block in page.get("blocks", []):
            text = (block.get("text") or "").strip()
            level = _infer_heading_level(text)
            if level is None:
                continue
            headings.append(
                {
                    "page": page.get("page"),
                    "text": text,
                    "level": level,
                    "bbox": block.get("bbox"),
                }
            )
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "summary": f"恢复出 {len(headings)} 个标题节点。",
        "headings": headings,
    }


def _build_cell_trace_artifact(
    job: dict[str, Any], page_payload: dict[str, Any], *, settings: Settings
) -> dict[str, Any]:
    if ocr_payload := _load_standard_ocr_cell_trace(job, settings):
        return ocr_payload
    if ocr_payload := _materialize_standard_ocr_cell_trace(job, settings):
        return ocr_payload
    raise DocumentPipelineBlockedError("标准 OCR 结果未接通，cell_trace 已阻断。")


def _document_pipeline_artifact_path(settings: Settings, stage: str, record: dict[str, Any]) -> Path:
    security_code = record.get("security_code", "unknown")
    report_id = record.get("report_id", "unknown")
    return settings.bronze_data_path / "upgrades" / stage / security_code / f"{report_id}.json"


def _standard_ocr_artifact_path(settings: Settings, record: dict[str, Any]) -> Path:
    security_code = record.get("security_code", "unknown")
    report_id = record.get("report_id", "unknown")
    return settings.bronze_data_path / "upgrades" / "ocr_cell_trace" / security_code / f"{report_id}.json"


def _resolve_report_source_path(settings: Settings, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value).replace("\\", "/"))
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    project_root = getattr(settings, "official_data_path", None)
    if project_root is not None:
        project_root_path = Path(project_root)
        if len(project_root_path.parents) >= 3:
            root_candidate = (project_root_path.parents[2] / candidate).resolve()
            if root_candidate.exists():
                return root_candidate
    return None


def _load_parsed_periodic_report_record(settings: Settings, report_id: str) -> dict[str, Any] | None:
    manifest_records = _load_manifest_records(
        settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    )
    return next((item for item in manifest_records if item.get("report_id") == report_id), None)


def _resolve_source_document_path(settings: Settings, job: dict[str, Any]) -> Path | None:
    report = _load_parsed_periodic_report_record(settings, str(job.get("report_id") or ""))
    if report is None:
        return None
    for key in ("file_path", "local_path", "source_path"):
        resolved = _resolve_report_source_path(settings, report.get(key))
        if resolved is not None:
            return resolved
    return None


def _clean_markdown_context_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^\s*[#>\-\*\u2022]+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", cleaned)
    return cleaned.strip()


def _looks_like_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2 and not MARKDOWN_TABLE_SEPARATOR_RE.match(stripped)


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    return [part.replace("\\|", "|").strip() for part in re.split(r"(?<!\\)\|", stripped)]


def _infer_markdown_table_title(lines: list[str], table_start: int, *, page: int, index: int) -> str:
    for cursor in range(table_start - 1, max(-1, table_start - 6), -1):
        if cursor < 0:
            break
        candidate = _clean_markdown_context_line(lines[cursor])
        if not candidate:
            continue
        if _looks_like_markdown_table_row(candidate) or MARKDOWN_TABLE_SEPARATOR_RE.match(candidate):
            continue
        return candidate
    return f"表格 P{page}-{index:02d}"


def _extract_tables_from_markdown(markdown_text: str, *, page: int, report_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = markdown_text.splitlines()
    tables: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    cursor = 0
    table_index = 0
    while cursor < len(lines):
        if cursor + 1 >= len(lines):
            break
        current = lines[cursor].rstrip()
        separator = lines[cursor + 1].rstrip()
        if not _looks_like_markdown_table_row(current) or not MARKDOWN_TABLE_SEPARATOR_RE.match(separator.strip()):
            cursor += 1
            continue
        header = _split_markdown_table_row(current)
        body_rows: list[list[str]] = []
        cursor += 2
        while cursor < len(lines) and _looks_like_markdown_table_row(lines[cursor]):
            body_rows.append(_split_markdown_table_row(lines[cursor]))
            cursor += 1
        rows = [header, *body_rows]
        if not rows or max((len(row) for row in rows), default=0) < 2:
            continue
        table_index += 1
        table_id = f"{report_id}-p{page}-ocr{table_index:02d}"
        title = _infer_markdown_table_title(lines, cursor - len(body_rows) - 2, page=page, index=table_index)
        column_count = max(len(row) for row in rows)
        tables.append(
            {
                "table_id": table_id,
                "page": page,
                "title": title,
                "continued": "续表" in title,
                "row_count": len(rows),
                "column_count": column_count,
                "bbox": None,
                "header_rows": 1,
            }
        )
        for row_index, row in enumerate(rows, start=1):
            for column_index, text in enumerate(row, start=1):
                cells.append(
                    {
                        "table_id": table_id,
                        "page": page,
                        "row_index": row_index,
                        "column_index": column_index,
                        "text": text,
                        "bbox": None,
                        "kind": "header" if row_index == 1 else "cell",
                        "source_block_indexes": [],
                    }
                )
    return tables, cells


def _build_standard_ocr_contract_from_layout_pages(
    job: dict[str, Any], layout_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for page_index, item in enumerate(layout_pages, start=1):
        markdown_text = (
            item.get("markdown_text")
            or ((item.get("markdown") or {}).get("text") if isinstance(item.get("markdown"), dict) else "")
            or ""
        )
        page_tables, page_cells = _extract_tables_from_markdown(
            markdown_text,
            page=page_index,
            report_id=job["report_id"],
        )
        tables.extend(page_tables)
        cells.extend(page_cells)
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "source": "standard_ocr",
        "summary": f"标准 OCR 服务输出 {len(tables)} 个表格片段、{len(cells)} 个单元格。",
        "tables": tables,
        "cells": cells,
    }


def _fetch_standard_ocr_layout_pages(source_path: Path, *, settings: Settings) -> list[dict[str, Any]]:
    ocr_runtime = _settings_ocr_runtime(settings)
    service_url = ocr_runtime["service_url"]
    if not service_url:
        raise RuntimeError("未配置 OPS_PILOT_OCR_SERVICE_URL，无法调用标准 OCR 服务。")
    suffix = source_path.suffix.lower()
    payload = {
        "file": base64.b64encode(source_path.read_bytes()).decode("utf-8"),
        "fileType": 0 if suffix == ".pdf" else 1,
    }
    response = requests.post(
        f"{service_url}/layout-parsing",
        json=payload,
        timeout=ocr_runtime["request_timeout_seconds"],
    )
    response.raise_for_status()
    data = response.json()
    layout_pages = data.get("result", {}).get("layoutParsingResults")
    if not isinstance(layout_pages, list):
        raise RuntimeError("标准 OCR 服务返回缺少 layoutParsingResults。")
    return layout_pages


def _materialize_standard_ocr_cell_trace(job: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    ocr_runtime = _settings_ocr_runtime(settings)
    if not ocr_runtime["runtime_enabled"] or ocr_runtime["mode"] != "service":
        return None
    source_path = _resolve_source_document_path(settings, job)
    if source_path is None:
        raise RuntimeError(f"未找到原始财报文件：{job.get('report_id')}")
    layout_pages = _fetch_standard_ocr_layout_pages(source_path, settings=settings)
    payload = _build_standard_ocr_contract_from_layout_pages(job, layout_pages)
    artifact_path = _standard_ocr_artifact_path(settings, job)
    _write_json(artifact_path, payload)
    return {
        **payload,
        "ocr_artifact_path": str(artifact_path),
    }


def _load_standard_ocr_cell_trace(settings_record: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    artifact_path = _standard_ocr_artifact_path(settings, settings_record)
    if not artifact_path.exists():
        return None
    try:
        with artifact_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return None
    tables = payload.get("tables")
    cells = payload.get("cells")
    if not isinstance(tables, list) or not isinstance(cells, list):
        return None
    if not _is_valid_standard_ocr_tables(tables) or not _is_valid_standard_ocr_cells(cells):
        return None
    return {
        "report_id": settings_record["report_id"],
        "company_name": settings_record["company_name"],
        "source": "standard_ocr",
        "summary": payload.get("summary") or f"读取标准 OCR 结构输出，获得 {len(tables)} 个表格片段、{len(cells)} 个单元格。",
        "tables": tables,
        "cells": cells,
        "ocr_artifact_path": str(artifact_path),
    }


def _is_valid_standard_ocr_tables(tables: list[Any]) -> bool:
    for item in tables:
        if not isinstance(item, dict):
            return False
        if not item.get("table_id"):
            return False
        if not isinstance(item.get("page"), int):
            return False
        if not item.get("title"):
            return False
    return True


def _is_valid_standard_ocr_cells(cells: list[Any]) -> bool:
    for item in cells:
        if not isinstance(item, dict):
            return False
        if not item.get("table_id"):
            return False
        if not isinstance(item.get("page"), int):
            return False
        if not isinstance(item.get("row_index"), int):
            return False
        if not isinstance(item.get("column_index"), int):
            return False
        if not isinstance(item.get("text"), str):
            return False
    return True


def _extract_page_table_traces(page: dict[str, Any]) -> list[dict[str, Any]]:
    lines = _group_blocks_into_lines(page.get("blocks", []))
    tables: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(lines):
        first_cells = _parse_line_cells(lines[cursor])
        if not _is_table_like_line(lines[cursor], first_cells):
            cursor += 1
            continue
        start = cursor
        rows: list[dict[str, Any]] = []
        while cursor < len(lines):
            parsed_cells = _parse_line_cells(lines[cursor])
            if not _is_table_like_line(lines[cursor], parsed_cells):
                break
            rows.append(
                {
                    "row_index": len(rows) + 1,
                    "bbox": _merge_bboxes([cell["bbox"] for cell in parsed_cells]),
                    "cells": parsed_cells,
                }
            )
            cursor += 1
        max_columns = max((len(row["cells"]) for row in rows), default=0)
        if len(rows) >= 2 and max_columns >= 2:
            table_title = _infer_table_title(lines, start)
            tables.append(
                {
                    "title": table_title,
                    "continued": "续表" in table_title,
                    "column_count": max_columns,
                    "header_rows": _count_header_rows(rows),
                    "rows": rows,
                    "bbox": _merge_bboxes([row["bbox"] for row in rows]),
                }
            )
    return tables


def _group_blocks_into_lines(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        text = (block.get("text") or "").strip()
        if not text:
            continue
        bbox = block.get("bbox") or [0.0, float(index) * 14.0, max(1.0, float(len(text))), float(index) * 14.0 + 10.0]
        normalized.append(
            {
                "block_index": block.get("block_index", index),
                "text": text,
                "bbox": [float(value) for value in bbox],
            }
        )
    normalized.sort(
        key=lambda item: (
            round((item["bbox"][1] + item["bbox"][3]) / 2, 1),
            round(item["bbox"][0], 1),
        )
    )

    lines: list[dict[str, Any]] = []
    for block in normalized:
        center_y = (block["bbox"][1] + block["bbox"][3]) / 2
        if lines and abs(lines[-1]["center_y"] - center_y) <= 8.0:
            lines[-1]["blocks"].append(block)
            lines[-1]["center_y"] = (lines[-1]["center_y"] + center_y) / 2
            continue
        lines.append({"center_y": center_y, "blocks": [block]})

    for line in lines:
        line["blocks"].sort(key=lambda item: item["bbox"][0])
        line["text"] = " ".join(block["text"] for block in line["blocks"])
        line["bbox"] = _merge_bboxes([block["bbox"] for block in line["blocks"]])
    return lines


def _parse_line_cells(line: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = line.get("blocks", [])
    if len(blocks) >= 2:
        return [
            {
                "column_index": index + 1,
                "text": block["text"],
                "bbox": block["bbox"],
                "kind": "value" if _contains_numeric(block["text"]) else "header",
                "source_block_indexes": [block["block_index"]],
            }
            for index, block in enumerate(blocks)
        ]

    text = (line.get("text") or "").strip()
    tokens = _split_table_tokens(text)
    if len(tokens) < 2:
        return []
    bbox = line.get("bbox") or [0.0, 0.0, float(len(text)), 10.0]
    width = max(float(bbox[2]) - float(bbox[0]), 1.0)
    total_chars = sum(max(len(token), 1) for token in tokens)
    cursor_x = float(bbox[0])
    source_index = blocks[0]["block_index"] if blocks else 0
    cells: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        token_width = width * max(len(token), 1) / total_chars
        cells.append(
            {
                "column_index": index + 1,
                "text": token,
                "bbox": [cursor_x, float(bbox[1]), cursor_x + token_width, float(bbox[3])],
                "kind": "value" if _contains_numeric(token) else "header",
                "source_block_indexes": [source_index],
            }
        )
        cursor_x += token_width
    return cells


def _split_table_tokens(text: str) -> list[str]:
    parts = [part.strip() for part in text.split(" ") if part.strip()]
    if len(parts) < 2:
        return [text]
    numeric_parts = [part for part in parts if _contains_numeric(part)]
    if len(numeric_parts) >= 2:
        label: list[str] = []
        values: list[str] = []
        numeric_started = False
        for part in parts:
            if _contains_numeric(part):
                numeric_started = True
                values.append(part)
            elif numeric_started:
                values.append(part)
            else:
                label.append(part)
        tokens: list[str] = []
        if label:
            tokens.append(" ".join(label))
        tokens.extend(values)
        return tokens if len(tokens) >= 2 else [text]
    if len(parts) <= 6 and any(term in text for term in TABLE_HEADER_TERMS):
        return parts
    return [text]


def _is_table_like_line(line: dict[str, Any], cells: list[dict[str, Any]]) -> bool:
    text = (line.get("text") or "").strip()
    if not text or _infer_heading_level(text) is not None or len(cells) < 2:
        return False
    numeric_count = sum(1 for cell in cells if _contains_numeric(cell["text"]))
    if numeric_count >= 2:
        return True
    return any(term in text for term in TABLE_HEADER_TERMS)


def _infer_table_title(lines: list[dict[str, Any]], start_index: int) -> str:
    for offset in range(1, 4):
        candidate_index = start_index - offset
        if candidate_index < 0:
            break
        candidate_text = (lines[candidate_index].get("text") or "").strip()
        if not candidate_text:
            continue
        if _infer_heading_level(candidate_text) is not None:
            return candidate_text
        if any(term in candidate_text for term in ("单位", "币种")):
            continue
        return candidate_text[:48]
    return "未命名表格片段"


def _count_header_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows[:3]:
        numeric_count = sum(1 for cell in row["cells"] if cell["kind"] == "value")
        if numeric_count <= max(1, len(row["cells"]) // 2):
            count += 1
        else:
            break
    return count


def _merge_bboxes(bboxes: list[list[float] | tuple[float, float, float, float]]) -> list[float]:
    if not bboxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(float(bbox[0]) for bbox in bboxes),
        min(float(bbox[1]) for bbox in bboxes),
        max(float(bbox[2]) for bbox in bboxes),
        max(float(bbox[3]) for bbox in bboxes),
    ]


def _contains_numeric(text: str) -> bool:
    return bool(re.search(r"[0-9]", text))


def _last_meaningful_block_text(blocks: list[dict[str, Any]]) -> str | None:
    for block in reversed(blocks):
        text = (block.get("text") or "").strip()
        if len(text) >= 8 and "证券代码" not in text and "第 " not in text:
            return text
    return None


def _first_meaningful_block_text(blocks: list[dict[str, Any]]) -> str | None:
    for block in blocks:
        text = (block.get("text") or "").strip()
        if len(text) >= 8 and "证券代码" not in text and "第 " not in text:
            return text
    return None


def _looks_like_cross_page_continuation(tail_text: str, head_text: str) -> bool:
    if tail_text.endswith(("。", "；", "：", "！", "？")):
        return False
    if head_text.startswith(("（", "公司", "本报告", "其中", "以及", "并", "的")):
        return True
    if tail_text.endswith(("、", "及", "与", "和", "为", "在", "是")):
        return True
    return bool(re.match(r"^[0-9一二三四五六七八九十]+", head_text))


def _infer_heading_level(text: str) -> int | None:
    if re.match(r"^第[一二三四五六七八九十0-9]+节", text):
        return 1
    if re.match(r"^[一二三四五六七八九十]+、", text):
        return 2
    if re.match(r"^（[一二三四五六七八九十0-9]+）", text):
        return 3
    if re.match(r"^[0-9]+(\.[0-9]+)*\s*", text):
        return 4
    if text in {"重要内容提示", "主要财务数据", "财务报表"}:
        return 2
    return None


def _normalize_report_period(title: str) -> str | None:
    match = re.search(r"(20\d{2})", title)
    if not match:
        return None
    year = match.group(1)
    if "三季度" in title:
        return f"{year}Q3"
    if "半年度" in title or "中报" in title:
        return f"{year}H1"
    if "年度报告" in title or "年报" in title:
        return f"{year}FY"
    if "一季度" in title:
        return f"{year}Q1"
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
