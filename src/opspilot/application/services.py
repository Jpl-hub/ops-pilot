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
            "company_snapshots": snapshot_manifest,
            "bronze_periodic_reports": bronze_periodic_manifest,
            "silver_financial_metrics": silver_metrics_manifest,
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
            "audit": audit,
            "scorecard": {**score_result, "risk_labels": risks, "opportunity_labels": opportunities},
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
                f"- 机会：{', '.join(item['name'] for item in scorecard['opportunity_labels']) or '暂无显著机会标签'}"
            ),
            "scorecard": scorecard,
            "evidence": score_payload["evidence"],
            "audit": score_payload["audit"],
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

        report_html = Path(report["local_path"]).read_text(encoding="utf-8")
        research_payload = _extract_research_payload(report_html)
        research_meta = _build_research_meta(report, research_payload)
        inferred_period = report_period or _infer_report_period_from_text(research_meta["title"])
        if inferred_period:
            company = self.repository.get_company(company_name, inferred_period)
            if company is None:
                raise ValueError(f"未找到与研报一致的真实报期：{company_name} {inferred_period}")
        else:
            company = self._resolve_company(company_name, None)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")

        report_body = _extract_research_body(report_html, research_payload)
        claim_cards = _build_claim_cards(company, report, report_body)
        forecast_cards = _build_forecast_cards(report, report_body, research_meta)
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
            "calculations": calculations,
            "audit": audit,
            "claim_cards": claim_cards,
            "forecast_cards": forecast_cards,
            "report_meta": research_meta,
        }

    def chat_turn(self, *, query: str, company_name: str | None = None, report_period: str | None = None) -> dict[str, Any]:
        period = report_period or self._preferred_period()
        detected_company = (
            company_name
            or self.repository.find_company_from_query(query, period)
            or self.repository.find_company_from_query(query, None)
        )
        query_type = detect_query_type(query)
        if query_type == "company_scoring" and detected_company:
            return self.score_company(detected_company, period)
        if query_type == "peer_benchmark" and detected_company:
            return self.benchmark_company(detected_company, period)
        if query_type == "claim_verification" and detected_company:
            return self.verify_claim(detected_company, report_period)
        if query_type == "brief_generation" and detected_company:
            return self.brief_company(detected_company, period)
        if query_type == "risk_scan":
            return self.risk_scan(period)
        return self.metric_query(query=query, company_name=detected_company, report_period=period)

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
        matches.sort(key=lambda item: _research_report_bucket(item, available_periods))
    return matches[0] if matches else None


def _infer_report_period_from_text(text: str) -> str | None:
    year_match = re.search(r"(\d{4})年", text)
    if not year_match:
        return None
    year = year_match.group(1)
    if "半年度" in text:
        return f"{year}H1"
    if "三季度" in text or "第三季度" in text:
        return f"{year}Q3"
    if "一季度" in text or "第一季度" in text:
        return f"{year}Q1"
    if "年度" in text:
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
    publish_date = payload.get("notice_date") or report.get("publish_date", "")
    return {
        "title": payload.get("notice_title") or report["title"],
        "publish_date": publish_date.split(" ")[0] if publish_date else "",
        "source_url": report.get("detail_url") or report["source_url"],
        "attachment_url": payload.get("attach_url"),
        "source_name": payload.get("source_sample_name"),
        "researcher": payload.get("researcher"),
        "rating_code": payload.get("rating"),
        "rating_label": rating_info.get("label"),
        "rating_action": rating_info.get("action"),
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
    sentence_match = re.search(
        r"(预计公司(?:\d{4}[~\-—至]\d{4}年|\d{4}(?:/\d{4})+年).*?(?:PE|市盈率)[^。]*评级。?)",
        report_body,
    )
    if sentence_match is None:
        return []
    sentence = sentence_match.group(1)
    years = _extract_forecast_years(sentence)
    profit_match = re.search(r"归母净利(?:润)?(?:分别为)?(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)+)亿元", sentence)
    yoy_match = re.search(
        r"同比([+-]?\d+(?:\.\d+)?%(?:/[+-]?\d+(?:\.\d+)?%)*)",
        sentence,
    )
    pe_match = re.search(
        r"(?:PE(?:为)?|市盈率(?:为)?)(\d+(?:\.\d+)?(?:x|倍)?(?:/\d+(?:\.\d+)?(?:x|倍)?)+)",
        sentence,
    )
    if not years or profit_match is None:
        return []

    profit_values = [float(item) for item in profit_match.group(1).split("/")]
    yoy_values = _split_forecast_metric_values(yoy_match.group(1), suffix="%") if yoy_match else []
    pe_values = _split_forecast_metric_values(pe_match.group(1), suffix="x") if pe_match else []
    if len(years) != len(profit_values):
        return []

    cards: list[dict[str, Any]] = []
    for index, (year, profit_value) in enumerate(zip(years, profit_values), start=1):
        cards.append(
            {
                "forecast_id": f"{report['security_code']}-forecast-{year}",
                "label": f"{year}年归母净利润预测",
                "report_period": f"{year}FY",
                "forecast_value": profit_value,
                "yoy_value": yoy_values[index - 1] if index <= len(yoy_values) else None,
                "pe_value": pe_values[index - 1] if index <= len(pe_values) else None,
                "rating_label": report_meta.get("rating_label"),
                "rating_action": report_meta.get("rating_action"),
                "excerpt": _clip_claim_excerpt(report_body, sentence, radius=240),
                "research_chunk_id": f"research-{report['security_code']}-forecast-{year}",
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


def _render_claim_answer(
    report_meta: dict[str, Any],
    report_period: str,
    claim_cards: list[dict[str, Any]],
    forecast_cards: list[dict[str, Any]],
) -> str:
    matched = sum(1 for item in claim_cards if item["status"] == "match")
    mismatched = sum(1 for item in claim_cards if item["status"] == "mismatch")
    insufficient = sum(1 for item in claim_cards if item["status"] == "insufficient_data")
    rating_parts = [
        part for part in (report_meta.get("rating_action"), report_meta.get("rating_label")) if part
    ]
    rating_text = "".join(rating_parts) or report_meta.get("rating_code") or "未披露"
    return (
        f"### 研报观点核验\n"
        f"- 研报：**{report_meta['title']}**\n"
        f"- 核验报期：**{report_period}**\n"
        f"- 投资评级：**{rating_text}**\n"
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


def _get_company_periods(repository: Any, company_name: str) -> set[str]:
    return {
        company.get("report_period")
        for company in repository.list_companies()
        if company.get("company_name") == company_name and company.get("report_period")
    }


def _research_report_bucket(report: dict[str, Any], available_periods: set[str] | None) -> int:
    inferred_period = _infer_report_period_from_text(report.get("title", ""))
    if inferred_period and (not available_periods or inferred_period in available_periods):
        return 0
    if inferred_period is None:
        return 1
    return 2


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
    if rating_code:
        return {"action": "", "label": str(rating_code)}
    return {}


def _extract_forecast_years(sentence: str) -> list[str]:
    list_match = re.search(r"预计公司(\d{4}(?:/\d{4})+)年", sentence)
    if list_match:
        return [item for item in list_match.group(1).split("/") if item]
    range_match = re.search(r"预计公司(\d{4})[~\-—至](\d{4})年", sentence)
    if range_match:
        start_year = int(range_match.group(1))
        end_year = int(range_match.group(2))
        return [str(year) for year in range(start_year, end_year + 1)]
    return []


def _split_forecast_metric_values(values_text: str, *, suffix: str) -> list[float]:
    cleaned = values_text.replace(suffix, "")
    if suffix == "x":
        cleaned = cleaned.replace("倍", "")
    return [float(item) for item in cleaned.split("/") if item]


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
