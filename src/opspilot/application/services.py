from __future__ import annotations

from pathlib import Path
from typing import Any
from html import unescape
import json
import re

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
        return {
            "health": health,
            "data_status": data_status,
            "quality_overview": quality_overview,
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
            return _build_workspace_payload(payload, query=query, user_role=user_role)
        if query_type == "peer_benchmark" and detected_company:
            payload = self.benchmark_company(detected_company, period)
            return _build_workspace_payload(payload, query=query, user_role=user_role)
        if query_type == "claim_verification" and detected_company:
            payload = self.verify_claim(detected_company, report_period)
            return _build_workspace_payload(payload, query=query, user_role=user_role)
        if query_type == "brief_generation" and detected_company:
            payload = self.brief_company(detected_company, period)
            return _build_workspace_payload(payload, query=query, user_role=user_role)
        if query_type == "risk_scan":
            payload = self.risk_scan(period)
            return _build_workspace_payload(payload, query=query, user_role=user_role)
        payload = self.metric_query(query=query, company_name=detected_company, report_period=period)
        return _build_workspace_payload(payload, query=query, user_role=user_role)

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
