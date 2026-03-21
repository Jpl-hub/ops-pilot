from __future__ import annotations

from pathlib import Path
from typing import Any
from html import unescape
from datetime import UTC, datetime
import json
import re
import time

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.catalog import METRIC_BY_CODE
from opspilot.domain.routing import detect_query_type
from opspilot.domain.rules import evaluate_opportunity_labels, evaluate_risk_labels
from opspilot.domain.scoring import score_company
from opspilot.infra.sample_repository import SampleRepository


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


class OpsPilotService:
    def __init__(self, repository: SampleRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self._industry_brain_cache: dict[str, Any] = {
            "generated_at": 0.0,
            "sequence": 0,
            "payload": None,
            "history": [],
        }

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
        periodic_manifest = _read_manifest(manifests_root / "periodic_reports_manifest.json")
        research_manifest = _read_manifest(manifests_root / "research_reports_manifest.json")
        industry_research_manifest = _read_manifest(
            manifests_root / "industry_research_reports_manifest.json"
        )
        bronze_periodic_manifest = _read_manifest(
            bronze_manifests_root / "parsed_periodic_reports_manifest.json"
        )
        silver_metrics_manifest = _read_manifest(
            silver_manifests_root / "financial_metrics_manifest.json"
        )
        snapshot_manifest = _read_manifest(manifests_root / "company_snapshots_manifest.json")
        return {
            "official_data_root": str(self.settings.official_data_path),
            "bronze_data_root": str(self.settings.bronze_data_path),
            "silver_data_root": str(self.settings.silver_data_path),
            "periodic_reports": periodic_manifest,
            "research_reports": research_manifest,
            "industry_research_reports": industry_research_manifest,
            "company_snapshots": snapshot_manifest,
            "bronze_periodic_reports": bronze_periodic_manifest,
            "silver_financial_metrics": silver_metrics_manifest,
        }

    def admin_overview(self) -> dict[str, Any]:
        health = self.health()
        data_status = self.official_data_status()
        quality_overview = _build_admin_quality_overview(self.settings, health["preferred_period"])
        document_pipeline = _build_document_pipeline_overview(data_status, self.settings)
        innovation_radar = self.innovation_radar()
        workspace_runs = self.workspace_runs(limit=8)
        workspace_history = self.workspace_history(user_role="management", report_period=health["preferred_period"], limit=12)
        return {
            "health": health,
            "data_status": data_status,
            "quality_overview": quality_overview,
            "document_pipeline": document_pipeline,
            "document_pipeline_jobs": self.document_pipeline_jobs(),
            "innovation_radar": innovation_radar,
            "workspace_runs": workspace_runs,
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
        watchboard = self.watchboard(user_role="management", report_period=preferred_period)
        risk_payload = self.risk_scan(preferred_period)
        innovation_radar = self.innovation_radar()
        data_status = self.official_data_status()
        workspace_history = self.workspace_history(
            user_role="management",
            report_period=preferred_period,
            limit=30,
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
        subindustry_counts: dict[str, int] = {}
        for item in risk_payload["risk_board"]:
            subindustry_counts[item["subindustry"]] = subindustry_counts.get(item["subindustry"], 0) + 1

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

        execution_flash = [
            {
                "title": item["title"],
                "summary": item["type_label"],
                "status": item["status_label"],
                "route": item.get("route"),
            }
            for item in recent_records[:6]
        ]

        attention_matrix = [
            {
                "company_name": item["company_name"],
                "subindustry": item["subindustry"],
                "risk_count": item["risk_count"],
                "headline": item["risk_labels"][0] if item["risk_labels"] else "继续跟踪",
                "route": item["route"],
            }
            for item in top_risk_companies[:4]
        ]

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

        payload = {
            "report_period": preferred_period,
            "stream": {
                "sequence": cache["sequence"],
                "ws_connected": True,
                "refreshed_at": _utcnow_iso(),
            },
            "sector_tags": [
                {"label": name, "count": count}
                for name, count in sorted(subindustry_counts.items(), key=lambda pair: pair[1], reverse=True)[:4]
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
                    "title": "当前高风险公司分布",
                    "options": _build_industry_risk_chart(top_risk_companies),
                },
            ],
            "radar_events": innovation_radar["items"][:6],
            "document_pipeline": {
                "periodic_reports": data_status.get("periodic_reports", {}).get("record_count", 0),
                "silver_metrics": data_status.get("silver_financial_metrics", {}).get("record_count", 0),
                "bronze_reports": data_status.get("bronze_periodic_reports", {}).get("record_count", 0),
            },
            "market_tape": market_tape,
            "execution_flash": execution_flash,
            "attention_matrix": attention_matrix,
            "live_events": live_events,
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
            "companies": [item["company_name"] for item in risk_payload["risk_board"]],
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
            try:
                research_payload = self.verify_claim(company_name, period)
                research_status = "ready"
                research_title = research_payload["report_meta"]["title"]
            except ValueError:
                research_status = "missing"
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
            "items": watch_items,
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
        period = report_period or self._preferred_period()
        company = self._resolve_company(company_name, period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")

        peers = self.repository.list_companies(company["report_period"])
        score_result = score_company(company, peers)
        risks = evaluate_risk_labels(company)
        opportunities = evaluate_opportunity_labels(company)
        formula_cards = _build_formula_cards(company)
        label_cards = _build_label_cards(company, risks, opportunities, formula_cards)
        action_cards = _build_action_cards(company, score_result, risks, opportunities)
        evidence_ids = _collect_evidence_ids(company, score_result, risks, opportunities)
        evidence = self.repository.resolve_evidence(evidence_ids)
        evidence_groups = _build_evidence_groups(label_cards, formula_cards, evidence)
        key_numbers = [
            {"label": "总分", "value": score_result["total_score"], "unit": "分"},
            {"label": "子行业分位", "value": score_result["subindustry_percentile"], "unit": "pct"},
        ]
        calculations = [{"step": "维度加权汇总", "detail": score_result["dimension_scores"]}]
        calculations.extend(_build_formula_calculations(formula_cards))
        audit = build_audit(
            key_numbers=key_numbers,
            evidence=evidence,
            calculations=calculations,
            min_evidence=self.settings.audit_min_evidence,
        )
        return {
            "company_name": company["company_name"],
            "subindustry": company["subindustry"],
            "report_period": company["report_period"],
            "answer_markdown": _render_score_answer(company, score_result, risks, opportunities),
            "query_type": "company_scoring",
            "key_numbers": key_numbers,
            "charts": _build_company_charts(company, score_result),
            "evidence": evidence,
            "evidence_groups": evidence_groups,
            "calculations": calculations,
            "formula_cards": formula_cards,
            "label_cards": label_cards,
            "action_cards": action_cards,
            "available_periods": _list_company_periods(self.repository, company_name),
            "audit": audit,
            "scorecard": {
                **score_result,
                "risk_labels": risks,
                "opportunity_labels": opportunities,
                "action_cards": action_cards,
            },
        }

    def benchmark_company(self, company_name: str, report_period: str | None = None) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        company = self._resolve_company(company_name, period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")
        peers = self.repository.list_companies(company["report_period"])
        rows = []
        for peer in peers:
            score_result = score_company(peer, peers)
            rows.append(
                {
                    "company_name": peer["company_name"],
                    "subindustry": peer["subindustry"],
                    "total_score": score_result["total_score"],
                    "grade": score_result["grade"],
                }
            )
        rows.sort(key=lambda item: item["total_score"], reverse=True)
        target = next(item for item in rows if item["company_name"] == company_name)
        return {
            "query_type": "peer_benchmark",
            "answer_markdown": f"**{company_name}** 当前总分为 **{target['total_score']} 分**，在样本集中位列第 **{rows.index(target) + 1}** 位。",
            "benchmark": rows,
            "charts": [
                {
                    "type": "bar",
                    "title": "样本集企业总分对比",
                    "options": {
                        "xAxis": {"type": "category", "data": [row["company_name"] for row in rows]},
                        "yAxis": {"type": "value", "max": 100},
                        "series": [{"type": "bar", "data": [row["total_score"] for row in rows]}],
                    },
                }
            ],
        }

    def company_timeline(self, company_name: str) -> dict[str, Any]:
        periods = _list_company_periods(self.repository, company_name)
        if not periods:
            raise ValueError(f"未找到公司：{company_name}")

        snapshots: list[dict[str, Any]] = []
        previous_snapshot: dict[str, Any] | None = None
        for period in periods:
            company = self.repository.get_company(company_name, period)
            if company is None:
                continue
            peers = self.repository.list_companies(period)
            score_result = score_company(company, peers)
            risks = evaluate_risk_labels(company)
            opportunities = evaluate_opportunity_labels(company)
            snapshot = {
                "report_period": period,
                "total_score": score_result["total_score"],
                "grade": score_result["grade"],
                "risk_count": len(risks),
                "opportunity_count": len(opportunities),
                "revenue_growth": company["metrics"].get("G1"),
                "profit_growth": company["metrics"].get("G2"),
                "cash_quality": company["metrics"].get("C1"),
                "top_risks": [item["name"] for item in risks[:3]],
                "top_opportunities": [item["name"] for item in opportunities[:3]],
            }
            if previous_snapshot is not None:
                snapshot["score_delta"] = round(
                    snapshot["total_score"] - previous_snapshot["total_score"], 2
                )
                snapshot["risk_delta"] = snapshot["risk_count"] - previous_snapshot["risk_count"]
            else:
                snapshot["score_delta"] = None
                snapshot["risk_delta"] = None
            snapshots.append(snapshot)
            previous_snapshot = snapshot

        if not snapshots:
            raise ValueError(f"未找到公司：{company_name}")

        latest = snapshots[0]
        return {
            "company_name": company_name,
            "latest_period": latest["report_period"],
            "key_numbers": [
                {"label": "已覆盖报期", "value": len(snapshots), "unit": "个"},
                {"label": "当前总分", "value": latest["total_score"], "unit": "分"},
                {"label": "当前风险数", "value": latest["risk_count"], "unit": "项"},
            ],
            "snapshots": snapshots,
            "charts": [
                {
                    "type": "line",
                    "title": "报期总分变化",
                    "options": {
                        "xAxis": {
                            "type": "category",
                            "data": [item["report_period"] for item in reversed(snapshots)],
                        },
                        "yAxis": {"type": "value", "max": 100},
                        "series": [
                            {
                                "type": "line",
                                "smooth": True,
                                "data": [item["total_score"] for item in reversed(snapshots)],
                            }
                        ],
                    },
                }
            ],
        }

    def company_workspace(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        score_payload = self.score_company(company_name, report_period)
        period = score_payload["report_period"]
        timeline_payload = self.company_timeline(company_name)
        benchmark_payload = self.benchmark_company(company_name, period)
        alert_workflow = self.alert_workflow(report_period=period)
        task_board = self.task_board(user_role=user_role, report_period=period, limit=20)
        document_upgrades = self.company_document_upgrades(company_name, period)
        runtime_capsule = self.company_runtime_capsule(
            company_name,
            period,
            user_role=user_role,
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
            research_status = {
                "status": "ready",
                "report_title": research_payload["report_meta"]["title"],
                "institution": research_payload["report_meta"]["institution"],
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

        return {
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
            "runtime_capsule": runtime_capsule,
            "execution_stream": self.company_execution_stream(
                company_name,
                period,
                user_role=user_role,
                limit=30,
            ),
            "recent_runs": _filter_workspace_runs_for_company(
                self.workspace_runs(limit=50)["runs"],
                company_name,
                period,
            ),
        }

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
            for item in self.company_document_upgrades(company_name, period, limit=100)["items"]
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
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        document_results = self.document_pipeline_results(limit=300)
        upgrade_items = _filter_document_results_for_company(
            document_results["results"], company_name, period
        )
        enriched_items: list[dict[str, Any]] = []
        stage_summary: dict[str, int] = {}
        for item in upgrade_items[:limit]:
            stage = item["stage"]
            stage_summary[stage] = stage_summary.get(stage, 0) + 1
            artifact_preview = None
            if item.get("status") == "completed":
                try:
                    detail = self.document_pipeline_result_detail(stage, item["report_id"])
                    artifact_preview = _build_document_artifact_preview(detail["artifact"])
                    evidence_navigation = detail.get("evidence_navigation")
                except ValueError:
                    artifact_preview = None
                    evidence_navigation = None
            else:
                evidence_navigation = None
            enriched_items.append(
                {
                    **item,
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
    ) -> dict[str, Any]:
        workspace = self.company_workspace(
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
                    "report_period": workspace["report_period"],
                    "score": workspace["score_summary"]["total_score"],
                    "grade": workspace["score_summary"]["grade"],
                },
            }
        )

        period_node = _graph_node_id("period", workspace["report_period"])
        nodes.append(
            {
                "id": period_node,
                "type": "report_period",
                "label": workspace["report_period"],
                "meta": {},
            }
        )
        edges.append({"source": company_node, "target": period_node, "label": "对应报期"})

        for risk_name in workspace["top_risks"]:
            risk_node = _graph_node_id("risk", risk_name)
            nodes.append({"id": risk_node, "type": "risk_label", "label": risk_name, "meta": {}})
            edges.append({"source": company_node, "target": risk_node, "label": "风险"})

        for task in workspace["tasks"]["items"][:5]:
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

        for alert in workspace["alerts"]["items"][:5]:
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

        for run in workspace["recent_runs"]["items"][:4]:
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

        if workspace["research"]["status"] == "ready":
            research_label = workspace["research"]["report_title"]
            research_node = _graph_node_id("research", research_label)
            nodes.append(
                {
                    "id": research_node,
                    "type": "research_report",
                    "label": research_label,
                    "meta": {
                        "institution": workspace["research"]["institution"],
                        "forecast_count": workspace["research"]["forecast_count"],
                    },
                }
            )
            edges.append({"source": company_node, "target": research_node, "label": "研报核验"})

        for item in workspace["document_upgrades"]["items"][:6]:
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

        if workspace["watchboard"]["tracked"]:
            monitor_node = _graph_node_id("watchboard", company_name)
            nodes.append(
                {
                    "id": monitor_node,
                    "type": "watchboard",
                    "label": "监测中",
                    "meta": {
                        "note": workspace["watchboard"]["note"],
                        "new_alerts": workspace["watchboard"]["new_alerts"],
                        "task_count": workspace["watchboard"]["task_count"],
                    },
                }
            )
            edges.append({"source": company_node, "target": monitor_node, "label": "持续监测"})

        for stream in workspace["execution_stream"]["records"][:8]:
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

        return {
            "company_name": company_name,
            "report_period": workspace["report_period"],
            "nodes": _dedupe_graph_nodes(nodes),
            "edges": edges,
            "summary": {
                "node_count": len(_dedupe_graph_nodes(nodes)),
                "edge_count": len(edges),
                "task_count": workspace["tasks"]["summary"]["total"],
                "alert_count": workspace["alerts"]["summary"]["total"],
                "document_upgrade_count": workspace["document_upgrades"]["count"],
                "run_count": workspace["recent_runs"]["count"],
                "watch_tracked": workspace["watchboard"]["tracked"],
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
        workspace = self.company_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
        graph = self.company_graph(
            company_name,
            workspace["report_period"],
            user_role=user_role,
        )
        ranked_nodes = _rank_graph_nodes_for_intent(graph["nodes"], intent)
        focal_nodes = ranked_nodes[:8]
        inference_path = _build_graph_query_inference_path(
            company_name=company_name,
            report_period=workspace["report_period"],
            intent=intent,
            focal_nodes=focal_nodes,
            workspace=workspace,
        )
        phase_track = _build_graph_query_phase_track(
            company_name=company_name,
            intent=intent,
            workspace=workspace,
            inference_path=inference_path,
        )
        signal_stream = _build_graph_query_signal_stream(
            focal_nodes=focal_nodes,
            workspace=workspace,
            graph_node_count=len(graph["nodes"]),
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
            "focal_nodes": focal_nodes,
            "inference_path": inference_path,
            "phase_track": phase_track,
            "signal_stream": signal_stream,
            "graph_live_frames": _build_graph_query_live_frames(
                focal_nodes=focal_nodes,
                inference_path=inference_path,
                phase_track=phase_track,
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
        workspace = self.company_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
        upgrades = self.company_document_upgrades(
            company_name,
            workspace["report_period"],
            limit=12,
        )
        selected_item = next(
            (
                item
                for item in upgrades["items"]
                if item.get("artifact_summary") or item.get("artifact_preview")
            ),
            upgrades["items"][0] if upgrades["items"] else None,
        )
        if selected_item is None:
            return {
                "company_name": company_name,
                "report_period": workspace["report_period"],
                "user_role": user_role,
                "result": {
                    "company_name": company_name,
                    "headline": "暂无可用解析结果",
                    "status_label": "等待解析",
                    "items": [],
                    "sections": [],
                    "evidence_navigation": {"links": []},
                },
            }

        detail = None
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
                "title": item.get("artifact_summary") or item["stage"],
                "summary": f"{item.get('report_period') or workspace['report_period']} · {item.get('status')}",
            }
            for item in upgrades["items"][:8]
        ]
        phase_track = _build_vision_phase_track(
            company_name=company_name,
            report_period=workspace["report_period"],
            selected_item=selected_item,
            detail=detail,
        )
        extraction_stream = _build_vision_extraction_stream(
            detail=detail,
            selected_item=selected_item,
        )
        analysis_log = _build_vision_analysis_log(
            company_name=company_name,
            report_period=workspace["report_period"],
            selected_item=selected_item,
            detail=detail,
        )
        return {
            "company_name": company_name,
            "report_period": workspace["report_period"],
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

    def company_stress_test(
        self,
        company_name: str,
        scenario: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        workspace = self.company_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
        graph = self.company_graph(
            company_name,
            workspace["report_period"],
            user_role=user_role,
        )
        propagation_steps = _build_stress_propagation_steps(
            company_name=company_name,
            scenario=scenario,
            graph_nodes=graph["nodes"],
            graph_edges=graph["edges"],
            top_risks=workspace["top_risks"],
            alert_items=workspace["alerts"]["items"],
            task_items=workspace["tasks"]["items"],
        )
        severity = _classify_stress_severity(
            scenario=scenario,
            risk_count=workspace["score_summary"]["risk_count"],
            open_tasks=workspace["tasks"]["summary"]["in_progress"],
            open_alerts=workspace["alerts"]["summary"]["new"]
            + workspace["alerts"]["summary"]["in_progress"],
        )
        transmission_matrix = _build_stress_transmission_matrix(
            propagation_steps=propagation_steps,
            severity=severity,
            workspace=workspace,
        )
        simulation_log = _build_stress_simulation_log(
            company_name=company_name,
            scenario=scenario,
            propagation_steps=propagation_steps,
            workspace=workspace,
        )
        payload = {
            "company_name": company_name,
            "report_period": workspace["report_period"],
            "user_role": user_role,
            "scenario": scenario,
            "severity": severity,
            "score_summary": workspace["score_summary"],
            "affected_dimensions": _build_stress_affected_dimensions(workspace),
            "propagation_steps": propagation_steps,
            "transmission_matrix": transmission_matrix,
            "simulation_log": simulation_log,
            "stress_wavefront": _build_stress_wavefront(
                propagation_steps=propagation_steps,
                transmission_matrix=transmission_matrix,
                simulation_log=simulation_log,
                severity=severity,
            ),
            "actions": [
                {
                    "priority": item["priority"],
                    "title": item["title"],
                    "action": item["action"],
                    "reason": item["reason"],
                }
                for item in workspace["action_cards"][:3]
            ],
            "related_routes": [
                {
                    "label": "查看企业体检",
                    "path": "/score",
                    "query": {"company": company_name, "period": workspace["report_period"]},
                },
                {
                    "label": "查看图谱推理",
                    "path": "/graph",
                    "query": {"company": company_name, "period": workspace["report_period"]},
                },
                {
                    "label": "返回协同分析",
                    "path": "/workspace",
                    "query": {"company": company_name},
                },
            ],
            "evidence_navigation": {
                "links": _build_stress_evidence_links(workspace),
            },
            "chart": _build_stress_test_chart(propagation_steps),
        }
        run_id = _build_stress_test_run_id(company_name)
        detail_path = _stress_test_run_detail_path(self.settings, run_id)
        _write_json(detail_path, payload)
        manifest = _load_stress_test_run_manifest(self.settings)
        records = [item for item in manifest["records"] if item.get("run_id") != run_id]
        records.insert(
            0,
            {
                "run_id": run_id,
                "company_name": company_name,
                "report_period": workspace["report_period"],
                "user_role": user_role,
                "scenario": scenario,
                "severity": severity,
                "created_at": _utcnow_iso(),
                "detail_path": str(detail_path),
            },
        )
        manifest["records"] = records[:200]
        _write_stress_test_run_manifest(self.settings, manifest)
        payload["run_id"] = run_id
        return payload

    def stress_test_runs(
        self,
        *,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "management",
        limit: int = 20,
    ) -> dict[str, Any]:
        records = [
            item
            for item in _load_stress_test_run_manifest(self.settings)["records"]
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

    def stress_test_run_detail(self, run_id: str) -> dict[str, Any]:
        record = next(
            (
                item
                for item in _load_stress_test_run_manifest(self.settings)["records"]
                if item.get("run_id") == run_id
            ),
            None,
        )
        if record is None:
            raise ValueError(f"未找到压力测试运行：{run_id}")
        detail_path = Path(record["detail_path"])
        if not detail_path.exists():
            raise ValueError(f"未找到压力测试详情：{run_id}")
        try:
            with detail_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"运行记录损坏：{run_id}") from exc
        payload["run_meta"] = {
            "run_id": run_id,
            "created_at": record.get("created_at"),
            "company_name": record.get("company_name"),
            "report_period": record.get("report_period"),
            "user_role": record.get("user_role"),
        }
        return payload

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

    def document_pipeline_results(
        self,
        stage: str | None = None,
        *,
        status: str | None = None,
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
                    "completed_at": item.get("completed_at"),
                    "detail_route": {
                        "path": f"/api/v1/admin/document-pipeline/results/{item['stage']}/{item['report_id']}",
                    },
                }
            )
        return {
            "stage": stage,
            "status": status,
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
        artifact_path = Path(job["artifact_path"])
        if not artifact_path.exists():
            raise ValueError(f"未找到解析产物：{artifact_path}")
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
        return {
            "job": {
                "stage": job["stage"],
                "report_id": job["report_id"],
                "company_name": job["company_name"],
                "security_code": job["security_code"],
                "report_period": job.get("report_period"),
                "status": job["status"],
                "artifact_path": job["artifact_path"],
                "completed_at": job.get("completed_at"),
                "artifact_summary": job.get("artifact_summary"),
            },
            "artifact": artifact,
            "evidence_navigation": evidence_navigation,
            "consumable_sections": _build_document_consumable_sections(artifact),
        }

    def run_document_pipeline_stage(self, stage: str, limit: int = 5) -> dict[str, Any]:
        jobs_manifest = _load_document_pipeline_job_manifest(self.settings)
        records = jobs_manifest["records"]
        pending_jobs = [
            item for item in records if item["stage"] == stage and item["status"] == "pending"
        ][:limit]
        results: list[dict[str, Any]] = []
        for job in pending_jobs:
            artifact_payload, artifact_path = _run_document_pipeline_job(stage, job, self.settings)
            job["status"] = "completed"
            job["artifact_path"] = str(artifact_path)
            job["completed_at"] = _utcnow_iso()
            job["artifact_summary"] = artifact_payload.get("summary")
            results.append(
                {
                    "report_id": job["report_id"],
                    "company_name": job["company_name"],
                    "artifact_path": str(artifact_path),
                    "summary": artifact_payload.get("summary"),
                }
            )
        _write_document_pipeline_job_manifest(self.settings, jobs_manifest)
        return {
            "stage": stage,
            "requested": limit,
            "processed": len(results),
            "results": results,
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
            "answer_markdown": "已完成样本集行业风险扫描，可直接查看高风险公司与标签分布。",
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
            "research_compare": self.compare_research_reports(company_name),
            "research_timeline": self.summarize_research_timeline(company_name),
        }

    def chat_turn(
        self,
        *,
        query: str,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "investor",
    ) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        detected_company = (
            company_name
            or self.repository.find_company_from_query(query, period)
            or self.repository.find_company_from_query(query, None)
        )
        query_type = detect_query_type(query)
        if query_type == "company_scoring" and detected_company:
            payload = self.score_company(detected_company, period)
            workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
            return self._persist_workspace_run(
                workspace_payload,
                query=query,
                company_name=detected_company,
                user_role=user_role,
            )
        if query_type == "peer_benchmark" and detected_company:
            payload = self.benchmark_company(detected_company, period)
            workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
            return self._persist_workspace_run(
                workspace_payload,
                query=query,
                company_name=detected_company,
                user_role=user_role,
            )
        if query_type == "claim_verification" and detected_company:
            payload = self.verify_claim(detected_company, report_period)
            workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
            return self._persist_workspace_run(
                workspace_payload,
                query=query,
                company_name=detected_company,
                user_role=user_role,
            )
        if query_type == "brief_generation" and detected_company:
            payload = self.brief_company(detected_company, period)
            workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
            return self._persist_workspace_run(
                workspace_payload,
                query=query,
                company_name=detected_company,
                user_role=user_role,
            )
        if query_type == "risk_scan":
            payload = self.risk_scan(period)
            workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
            return self._persist_workspace_run(
                workspace_payload,
                query=query,
                company_name=detected_company,
                user_role=user_role,
            )
        payload = self.metric_query(query=query, company_name=detected_company, report_period=period)
        workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
        return self._persist_workspace_run(
            workspace_payload,
            query=query,
            company_name=detected_company,
            user_role=user_role,
        )

    def workspace_runs(self, limit: int = 20) -> dict[str, Any]:
        manifest = _load_workspace_run_manifest(self.settings)
        records = sorted(
            manifest["records"],
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        return {
            "total": len(records),
            "runs": records[:limit],
        }

    def workspace_history(
        self,
        *,
        user_role: str = "management",
        report_period: str | None = None,
        limit: int = 30,
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
            for item in self.workspace_runs(limit=200)["runs"]
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
                limit=200,
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
            for item in self.document_pipeline_results(limit=300)["results"]
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
                limit=200,
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
                limit=200,
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
                limit=200,
            )["runs"]
        ]
        records = analysis_runs + watch_runs + document_jobs + stress_runs
        records += graph_runs + vision_runs
        records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {
            "user_role": user_role,
            "report_period": period,
            "total": len(records),
            "records": records[:limit],
        }

    def workspace_run_detail(self, run_id: str) -> dict[str, Any]:
        manifest = _load_workspace_run_manifest(self.settings)
        record = next((item for item in manifest["records"] if item["run_id"] == run_id), None)
        if record is None:
            raise ValueError(f"未找到运行记录：{run_id}")
        detail_path = Path(record["detail_path"])
        if not detail_path.exists():
            raise ValueError(f"未找到运行详情：{detail_path}")
        try:
            with detail_path.open("r", encoding="utf-8") as file:
                detail = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"压力测试记录损坏：{run_id}") from exc
        return {"run": record, "detail": detail}

    def metric_query(
        self, *, query: str, company_name: str | None, report_period: str | None
    ) -> dict[str, Any]:
        if not company_name:
            raise ValueError("当前样本问答需要显式包含公司名。")
        company = self._resolve_company(company_name, report_period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")
        metric_code = _guess_metric_code(query)
        metric_def = METRIC_BY_CODE[metric_code]
        value = company["metrics"][metric_code]
        evidence = self.repository.resolve_evidence(company.get("metric_evidence", {}).get(metric_code, []))
        calculations = [{"step": "指标直取", "detail": f"{metric_code} = {value}"}]
        formula_cards = []
        if formula_card := _build_formula_card(company, metric_code):
            formula_cards.append(formula_card)
            calculations.extend(_build_formula_calculations(formula_cards))
        audit = build_audit(
            key_numbers=[{"label": metric_def.name, "value": value, "unit": ""}],
            evidence=evidence,
            calculations=calculations,
            min_evidence=self.settings.audit_min_evidence,
        )
        return {
            "company_name": company["company_name"],
            "report_period": company["report_period"],
            "answer_markdown": f"**{company_name}** 在 **{company['report_period']}** 的 **{metric_def.name}** 为 **{value}**。",
            "query_type": "metric_query",
            "key_numbers": [{"label": metric_def.name, "value": value, "unit": ""}],
            "charts": [],
            "evidence": evidence,
            "calculations": calculations,
            "formula_cards": formula_cards,
            "audit": audit,
        }

    def get_evidence(self, chunk_id: str) -> dict[str, Any]:
        evidence = self.repository.get_evidence(chunk_id)
        if evidence is None:
            raise ValueError(f"未找到证据：{chunk_id}")
        return evidence

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
    if report_title:
        matches = [report for report in matches if report_title in report.get("title", "")]
    if report_period:
        period_matches = [
            report
            for report in matches
            if _infer_report_period_from_text(report.get("title", "")) == report_period
        ]
        if not period_matches:
            return None
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
    sentence = _find_forecast_sentence(report_body)
    if sentence is None:
        return []
    anchor_year = _infer_anchor_year(report_meta)
    profit_map = _extract_forecast_profit_map(sentence, anchor_year=anchor_year)
    if not profit_map:
        return []
    years = sorted(profit_map.keys())
    yoy_map = _extract_forecast_metric_map(
        sentence,
        pattern=re.compile(
            r"(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年归母净利(?:润)?(?:同增|同比增长|同比)([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"
        ),
        default_years=years,
        anchor_year=anchor_year,
        fallback_pattern=re.compile(r"同比([+\-]?\d+(?:\.\d+)?%(?:[/、,，][+\-]?\d+(?:\.\d+)?%)*)"),
        suffix="%",
    )
    pe_map = _extract_forecast_metric_map(
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


def _build_vision_phase_track(
    *,
    company_name: str,
    report_period: str,
    selected_item: dict[str, Any],
    detail: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sections = detail.get("consumable_sections", []) if detail else []
    return [
        {
            "phase": "载入报告",
            "status": "done",
            "headline": company_name,
            "metric": report_period,
        },
        {
            "phase": "解析工序",
            "status": "done" if selected_item.get("status") == "done" else "active",
            "headline": selected_item.get("stage", "document"),
            "metric": selected_item.get("status", "pending"),
        },
        {
            "phase": "结构抽取",
            "status": "done" if sections else "active",
            "headline": "标题/表格/片段",
            "metric": f"{len(sections)} sections",
        },
        {
            "phase": "证据挂接",
            "status": "active",
            "headline": "可回看原证据",
            "metric": f"{len((detail or {}).get('evidence_navigation', {}).get('links', []))} links",
        },
    ]


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
                "label": selected_item.get("stage", "document"),
                "value": selected_item.get("status", "pending"),
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
        ("定位报告", selected_item.get("report_id") or selected_item.get("stage", "document")),
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
                    f"当前处于 {payload.get('subindustry', '所属子行业')} 样本的 {scorecard.get('subindustry_percentile')}pct 位置。",
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
    return [
        {
            "step": 1,
            "agent": "总控调度",
            "status": "completed",
            "title": "识别任务并锁定公司",
            "summary": f"已将问题归类为 {payload.get('query_type')}，目标问题是：{query}",
            "source": "问题文本 + 公司池 + 报期索引",
            "tool": "intent_router",
            "handoff": "信号分析",
            "route": _build_agent_route("orchestrator", payload),
            "metrics": [
                {"label": "任务类型", "value": query_type or "unknown"},
                {"label": "目标公司", "value": payload.get("company_name", "未显式指定")},
                {"label": "目标报期", "value": payload.get("report_period", "自动选择")},
            ],
        },
        {
            "step": 2,
            "agent": "信号分析",
            "status": "completed",
            "title": "抽取经营与风险信号",
            "summary": (
                f"识别到 {risk_count} 个重点风险，生成 {formula_count} 条公式链。"
                if payload.get("query_type") == "company_scoring"
                else f"提取了 {len(payload.get('key_numbers', []))} 个关键结果。"
            ),
            "source": _resolve_agent_signal_source(query_type),
            "tool": _resolve_agent_signal_tool(query_type),
            "handoff": "证据审计",
            "route": _build_agent_route("signal_analyst", payload),
            "metrics": _build_signal_agent_metrics(payload, risk_count, formula_count, claim_count),
        },
        {
            "step": 3,
            "agent": "证据审计",
            "status": "completed",
            "title": "回放来源与可核查证据",
            "summary": f"当前返回 {evidence_count} 条证据引用，优先暴露页码和来源片段。",
            "source": "官方财报页级解析 + 研报详情页 + 公式输入字段",
            "tool": "evidence_auditor",
            "handoff": "动作生成",
            "route": _build_agent_route("evidence_auditor", payload),
            "metrics": [
                {"label": "证据条数", "value": evidence_count},
                {"label": "证据分组", "value": len(payload.get("evidence_groups", []))},
                {"label": "公式回放", "value": formula_count},
            ],
        },
        {
            "step": 4,
            "agent": "动作生成",
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
                    "terms": ",".join(first_group.get("anchor_terms", [])),
                },
            }
        return {
            "label": "查看证据页",
            "path": "/admin",
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
        return ["真实财报指标", "同子行业样本池", "横向评分结果"]
    if query_type == "risk_scan":
        return ["全公司评分快照", "主周期预警板", "行业研报观察"]
    return ["真实财报指标", "页级证据", "指标直取"]


def _resolve_agent_signal_source(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "真实财报指标 + 风险规则 + 历史报期对比",
        "claim_verification": "真实财报指标 + 研报观点抽取",
        "peer_benchmark": "同子行业评分样本 + 分位结果",
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
            {"label": "样本公司", "value": len(payload.get("benchmark", []))},
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


def _build_document_consumable_sections(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
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


def _build_document_evidence_navigation(
    *,
    repository: Any,
    company_name: str,
    report_period: str | None,
    artifact: dict[str, Any],
) -> dict[str, Any] | None:
    get_company = getattr(repository, "get_company", None)
    if get_company is None:
        return _build_document_navigation_fallback(artifact)
    company = get_company(company_name, report_period) if report_period else get_company(company_name)
    if company is None:
        return _build_document_navigation_fallback(artifact)

    candidate_pages = _collect_document_artifact_pages(artifact)
    candidate_chunk_ids = _collect_company_evidence_refs(company)
    evidence_items = repository.resolve_evidence(candidate_chunk_ids)
    if candidate_pages:
        paged_items = [item for item in evidence_items if item.get("page") in candidate_pages]
    else:
        paged_items = []
    selected_items = paged_items or evidence_items[:1]
    if not selected_items:
        return _build_document_navigation_fallback(artifact)

    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    links = [
        {
            "chunk_id": item["chunk_id"],
            "label": f"第{item.get('page', '?')}页证据" if item.get("page") else "证据",
            "path": f"/evidence/{item['chunk_id']}",
            "query": {
                "context": "文档升级结果",
                "terms": ",".join(anchor_terms[:6]),
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


def _build_document_navigation_fallback(artifact: dict[str, Any]) -> dict[str, Any]:
    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    pages = _collect_document_artifact_pages(artifact)
    route = {
        "label": "查看解析结果",
        "path": "/admin",
        "query": {
            "context": "文档升级结果",
            "terms": ",".join(anchor_terms[:6]),
        },
        "page": pages[0] if pages else None,
    }
    return {
        "count": 1,
        "anchor_terms": anchor_terms[:6],
        "pages": pages,
        "links": [route],
        "primary_route": route,
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


def _rank_graph_nodes_for_intent(nodes: list[dict[str, Any]], intent: str) -> list[dict[str, Any]]:
    lowered = intent.lower()
    ranked: list[dict[str, Any]] = []
    type_priority = {
        "risk_label": 5,
        "alert": 5,
        "research_report": 4,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "task": 3,
        "execution_stream": 3,
        "watchboard": 3,
        "company": 2,
        "report_period": 1,
    }
    tokens = [part for part in re.split(r"[\s,，。；;、\-_/]+", lowered) if len(part) >= 2]
    for node in nodes:
        label = str(node.get("label", ""))
        meta_values = " ".join(str(value) for value in (node.get("meta") or {}).values())
        haystack = f"{label} {meta_values}".lower()
        score = type_priority.get(str(node.get("type")), 0)
        for token in tokens:
            if token in haystack:
                score += 3
        ranked.append({**node, "intent_score": score})
    ranked.sort(
        key=lambda item: (item["intent_score"], type_priority.get(str(item.get("type")), 0), str(item.get("label", ""))),
        reverse=True,
    )
    return ranked


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
    if node_type == "watchboard":
        return f"监测板持续跟踪，新增预警 {meta.get('new_alerts') or 0} 条。"
    if node_type == "company":
        return f"总分 {workspace['score_summary']['total_score']}，等级 {workspace['score_summary']['grade']}。"
    return "该节点参与当前查询意图的传导路径。"


def _build_graph_query_inference_path(
    *,
    company_name: str,
    report_period: str,
    intent: str,
    focal_nodes: list[dict[str, Any]],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "step": 1,
            "title": company_name,
            "detail": f"锁定 {report_period} 作为当前分析报期。",
            "type": "company",
        }
    ]
    for index, node in enumerate(focal_nodes[:4], start=2):
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
            "detail": f"围绕“{intent}”把风险、任务、证据和执行流压成可操作结论。",
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
) -> list[dict[str, Any]]:
    evidence_groups = workspace.get("evidence_groups") or []
    return [
        {
            "phase": "查询压缩",
            "status": "done",
            "headline": intent[:22] + ("..." if len(intent) > 22 else ""),
            "metric": f"{len(intent)} chars",
        },
        {
            "phase": "节点聚焦",
            "status": "done",
            "headline": company_name,
            "metric": f"{max(len(inference_path) - 2, 1)} nodes",
        },
        {
            "phase": "路径传导",
            "status": "done",
            "headline": "影响链已展开",
            "metric": f"{len(inference_path)} steps",
        },
        {
            "phase": "证据挂接",
            "status": "active",
            "headline": "证据与动作入口",
            "metric": f"{len(evidence_groups)} sources",
        },
    ]


def _build_graph_query_signal_stream(
    *,
    focal_nodes: list[dict[str, Any]],
    workspace: dict[str, Any],
    graph_node_count: int,
) -> list[dict[str, Any]]:
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
            "id": item["task_id"],
            "title": item["title"],
            "company_name": item["company_name"],
            "status": item["status"],
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
            "id": item["alert_id"],
            "title": f"{item['company_name']} 预警",
            "company_name": item["company_name"],
            "status": item["status"],
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
            "id": f"watch::{item['company_name']}::{watchboard['report_period']}::{watchboard['user_role']}",
            "title": "重点监测",
            "company_name": item["company_name"],
            "status": "tracked",
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
            "id": item["id"],
            "title": item["title"],
            "company_name": item.get("company_name"),
            "status": item.get("status"),
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
    local_path = report.get("local_path")
    if not local_path or not Path(local_path).exists():
        return None
    report_html = Path(local_path).read_text(encoding="utf-8", errors="ignore")
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


def _research_report_content_score(report: dict[str, Any]) -> tuple[int, int]:
    insight = _build_research_report_insight(report)
    if insight is None:
        return (0, 0)
    return (len(insight["forecast_cards"]), insight["claim_signal_count"])


def _extract_research_rating(report_body: str, payload: dict[str, Any]) -> dict[str, str]:
    match = re.search(
        r"(维持|上调至|上调为|下调至|下调为|首次覆盖给予|首次给予|给予)?[“\"]([^”\"，。]{2,8})[”\"]?评级",
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


def _find_forecast_sentence(report_body: str) -> str | None:
    sentences = [
        item.strip()
        for item in re.split(r"[。\n]", report_body)
        if item.strip()
    ]
    for sentence in sentences:
        if "归母净利" not in sentence and "归母净利润" not in sentence:
            continue
        if "评级" not in sentence:
            continue
        if "预计" not in sentence and "盈利预测" not in sentence:
            continue
        return sentence
    return None


def _infer_anchor_year(report_meta: dict[str, Any]) -> int | None:
    text = f"{report_meta.get('title', '')} {report_meta.get('publish_date', '')}"
    match = re.search(r"(20\d{2})", text)
    if match is None:
        return None
    return int(match.group(1))


def _extract_forecast_profit_map(sentence: str, *, anchor_year: int | None) -> dict[str, float]:
    profit_map: dict[str, float] = {}
    patterns = [
        re.compile(
            r"(\d{2,4}(?:[/、,，~\-—至]\d{2,4})*)年(?:(?!\d{2,4}(?:[/、,，~\-—至]\d{2,4})*年)[^。；]){0,40}?归母净利(?:润)?(?:分别)?(?:同增)?(?:为|至)?([+\-]?\d+(?:\.\d+)?(?:[/、,，][+\-]?\d+(?:\.\d+)?)*?)亿元"
        ),
        re.compile(
            r"归母净利(?:润)?(?:分别)?(?:为|至)([+\-]?\d+(?:\.\d+)?(?:[/、,，][+\-]?\d+(?:\.\d+)?)+)亿元"
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(sentence):
            year_text = match.group(1) if match.lastindex and match.lastindex > 1 else ""
            values_text = match.group(match.lastindex)
            years = (
                _expand_forecast_year_group(year_text, anchor_year=anchor_year)
                if year_text
                else []
            )
            values = _split_forecast_metric_values(values_text, suffix="")
            if not years:
                continue
            if len(years) != len(values):
                continue
            for year, value in zip(years, values):
                profit_map[year] = value
        if profit_map:
            break
    return profit_map


def _extract_forecast_metric_map(
    sentence: str,
    *,
    pattern: re.Pattern[str],
    default_years: list[str],
    anchor_year: int | None,
    fallback_pattern: re.Pattern[str] | None,
    suffix: str,
) -> dict[str, float]:
    for match in pattern.finditer(sentence):
        years = _expand_forecast_year_group(match.group(1), anchor_year=anchor_year)
        values = _split_forecast_metric_values(match.group(2), suffix=suffix)
        if len(years) != len(values):
            continue
        return dict(zip(years, values))
    if fallback_pattern is None:
        return {}
    fallback = fallback_pattern.search(sentence)
    if fallback is None:
        return {}
    values = _split_forecast_metric_values(fallback.group(1), suffix=suffix)
    if len(values) != len(default_years):
        return {}
    return dict(zip(default_years, values))


def _expand_forecast_year_group(year_text: str, *, anchor_year: int | None) -> list[str]:
    normalized = year_text.replace("—", "-").replace("至", "-").replace("~", "-")
    if "-" in normalized and normalized.count("-") == 1 and "/" not in normalized:
        start_text, end_text = normalized.split("-", 1)
        start_year = _normalize_forecast_year(start_text, anchor_year=anchor_year)
        end_year = _normalize_forecast_year(end_text, anchor_year=anchor_year)
        if start_year is None or end_year is None or end_year < start_year:
            return []
        return [str(year) for year in range(start_year, end_year + 1)]
    years: list[str] = []
    for token in re.split(r"[/、,，]", normalized):
        year = _normalize_forecast_year(token, anchor_year=anchor_year)
        if year is not None:
            years.append(str(year))
    return years


def _normalize_forecast_year(year_text: str, *, anchor_year: int | None) -> int | None:
    token = year_text.strip()
    if not token.isdigit():
        return None
    if len(token) == 4:
        return int(token)
    if len(token) == 2:
        base_year = anchor_year or 2000
        century = base_year // 100 * 100
        return century + int(token)
    return None


def _split_forecast_metric_values(values_text: str, *, suffix: str) -> list[float]:
    cleaned = values_text.replace(suffix, "")
    if suffix == "x":
        cleaned = cleaned.replace("倍", "").replace("X", "x").replace("x", "")
    cleaned = cleaned.replace("%", "").replace(" ", "")
    return [
        float(item)
        for item in re.split(r"[/、,，]", cleaned)
        if item
    ]


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


def _build_admin_quality_overview(settings: Settings, preferred_period: str | None) -> dict[str, Any]:
    company_pool = _load_json_records(settings.sample_data_path.parent / "universe" / "formal_company_pool.json")
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
    cell_blocked = sum(
        1 for item in records if item["stage"] == "cell_trace" and item["status"] == "blocked"
    )
    return {
        "layout_engine": settings.doc_layout_engine,
        "ocr_engine": f"{settings.ocr_provider} / {settings.ocr_model}",
        "ocr_runtime_enabled": settings.ocr_runtime_enabled,
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
            "enabled": settings.ocr_runtime_enabled,
            "status": "runtime-ready" if settings.ocr_runtime_enabled else f"blocked {cell_blocked}",
            "summary": "单元格级溯源需要 OCR 运行时和表格结构输出，当前已挂入作业队列。",
        },
        "coverage": [
            {"label": "原始文档", "value": periodic_count, "unit": "份"},
            {"label": "页级解析", "value": bronze_count, "unit": "条"},
            {"label": "结构化指标", "value": silver_count, "unit": "条"},
        ],
    }


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
            status = "blocked" if stage == "cell_trace" and not settings.ocr_runtime_enabled else "pending"
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
        if desired["status"] != "completed":
            merged["status"] = desired["status"]
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


def _write_workspace_run_manifest(settings: Settings, payload: dict[str, Any]) -> None:
    payload["generated_at"] = _utcnow_iso()
    payload["record_count"] = len(payload.get("records", []))
    manifest_path = settings.bronze_data_path / "manifests" / "workspace_runs.json"
    _write_json(manifest_path, payload)


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
    page_json_path = Path(job["page_json_path"])
    if not page_json_path.is_absolute():
        page_json_path = (Path.cwd() / page_json_path).resolve()
    with page_json_path.open("r", encoding="utf-8") as file:
        page_payload = json.load(file)

    if stage == "cross_page_merge":
        artifact_payload = _build_cross_page_merge_artifact(job, page_payload)
    elif stage == "title_hierarchy":
        artifact_payload = _build_title_hierarchy_artifact(job, page_payload)
    else:
        artifact_payload = {
            "report_id": job["report_id"],
            "company_name": job["company_name"],
            "summary": "当前运行时未输出单元格级结构。",
            "cells": [],
        }
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


def _document_pipeline_artifact_path(settings: Settings, stage: str, record: dict[str, Any]) -> Path:
    security_code = record.get("security_code", "unknown")
    report_id = record.get("report_id", "unknown")
    return settings.bronze_data_path / "upgrades" / stage / security_code / f"{report_id}.json"


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
