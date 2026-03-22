"""
scoring_service.py — Domain service for enterprise scoring & benchmarking.

Responsibilities:
  - 19-indicator weighted scoring engine (ScoringService.score_company)
  - Peer-group benchmarking (ScoringService.benchmark_company)
  - Multi-period score trajectory (ScoringService.company_timeline)

Architecture:
  ScoringService is instantiated by OpsPilotService (facade pattern).
  All builder helpers are pure functions kept at module level below the class.
"""
from __future__ import annotations

from typing import Any

from opspilot.config import Settings
from opspilot.domain.audit import build_audit
from opspilot.domain.catalog import METRIC_BY_CODE
from opspilot.domain.rules import evaluate_opportunity_labels, evaluate_risk_labels
from opspilot.domain.scoring import score_company as _domain_score_company


# ---------------------------------------------------------------------------
# Shared label → metric code mapping (mirrors domain catalog)
# ---------------------------------------------------------------------------

LABEL_METRIC_CODES: dict[str, tuple[str, ...]] = {
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

METRIC_ANCHOR_TERMS: dict[str, tuple[str, ...]] = {
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


# ---------------------------------------------------------------------------
# ScoringService
# ---------------------------------------------------------------------------

class ScoringService:
    """
    Enterprise scoring domain service.

    Exposes three core capabilities:
      1. score_company   — full 19-indicator assessment + risk/opportunity labels
      2. benchmark_company — peer-group ranking within same sub-industry
      3. company_timeline  — multi-period score trajectory

    All heavy computation delegates to the pure domain layer
    (opspilot.domain.scoring, opspilot.domain.rules, opspilot.domain.catalog).
    """

    def __init__(self, repository: Any, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def score_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any]:
        """Run full 19-indicator scoring for one company/period."""
        period = report_period or self._preferred_period()
        company = self._resolve_company(company_name, period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")

        peers = self.repository.list_companies(company["report_period"])
        score_result = _domain_score_company(company, peers)
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
            "score_command_surface": _build_score_command_surface(
                company=company,
                score_result=score_result,
                risks=risks,
                opportunities=opportunities,
                action_cards=action_cards,
                timeline_payload=self.company_timeline(company_name),
            ),
            "score_signal_tape": _build_score_signal_tape(
                score_result=score_result,
                risks=risks,
                opportunities=opportunities,
                action_cards=action_cards,
            ),
            "scorecard": {
                **score_result,
                "risk_labels": risks,
                "opportunity_labels": opportunities,
                "action_cards": action_cards,
            },
        }

    def benchmark_company(
        self, company_name: str, report_period: str | None = None
    ) -> dict[str, Any]:
        """Rank company within same sub-industry peer group."""
        period = report_period or self._preferred_period()
        company = self._resolve_company(company_name, period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")
        peers = self.repository.list_companies(company["report_period"])
        rows = []
        for peer in peers:
            score_result = _domain_score_company(peer, peers)
            rows.append({
                "company_name": peer["company_name"],
                "subindustry": peer["subindustry"],
                "total_score": score_result["total_score"],
                "grade": score_result["grade"],
            })
        rows.sort(key=lambda item: item["total_score"], reverse=True)
        target = next(item for item in rows if item["company_name"] == company_name)
        return {
            "query_type": "peer_benchmark",
            "answer_markdown": (
                f"**{company_name}** 当前总分为 **{target['total_score']} 分**，"
                f"在样本集中位列第 **{rows.index(target) + 1}** 位。"
            ),
            "benchmark": rows,
            "charts": [{
                "type": "bar",
                "title": "样本集企业总分对比",
                "options": {
                    "xAxis": {"type": "category", "data": [row["company_name"] for row in rows]},
                    "yAxis": {"type": "value", "max": 100},
                    "series": [{"type": "bar", "data": [row["total_score"] for row in rows]}],
                },
            }],
        }

    def company_timeline(self, company_name: str) -> dict[str, Any]:
        """Build multi-period score trajectory with delta tracking."""
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
            score_result = _domain_score_company(company, peers)
            risks = evaluate_risk_labels(company)
            opportunities = evaluate_opportunity_labels(company)
            snapshot: dict[str, Any] = {
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
            "charts": [{
                "type": "line",
                "title": "报期总分变化",
                "options": {
                    "xAxis": {
                        "type": "category",
                        "data": [item["report_period"] for item in reversed(snapshots)],
                    },
                    "yAxis": {"type": "value", "max": 100},
                    "series": [{
                        "type": "line",
                        "smooth": True,
                        "data": [item["total_score"] for item in reversed(snapshots)],
                    }],
                },
            }],
        }

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _preferred_period(self) -> str:
        if hasattr(self.repository, "preferred_period"):
            preferred = self.repository.preferred_period()
            if preferred:
                return preferred
        return self.settings.default_period

    def _resolve_company(
        self, company_name: str, report_period: str | None
    ) -> dict[str, Any] | None:
        company = self.repository.get_company(company_name, report_period)
        if company is not None:
            return company
        return self.repository.get_company(company_name, None)


# ---------------------------------------------------------------------------
# Pure builder functions (module-level, side-effect free)
# ---------------------------------------------------------------------------

def _collect_evidence_ids(
    company: dict[str, Any],
    score_result: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
) -> list[str]:
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


def _render_score_answer(
    company: dict[str, Any],
    score_result: dict[str, Any],
    risks: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
) -> str:
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
    """Generate prioritised management action cards based on detected risk/opportunity labels."""
    cards: list[dict[str, Any]] = []
    metrics = company.get("metrics", {})
    risk_map = {item["code"]: item for item in risks}
    opportunity_map = {item["code"]: item for item in opportunities}

    if "R1" in risk_map:
        cards.append({"priority": "P1", "title": "优先修复现金回款链",
            "reason": f"经营现金流/净利润仅为 {metrics.get('C1')}，利润兑现没有跟上现金回流。",
            "action": "复盘应收回款节奏、压缩赊销账期，并把大额订单回款节点纳入月度经营例会。"})
    if "R2" in risk_map:
        cards.append({"priority": "P1", "title": "压降应收扩张速度",
            "reason": f"应收增速-收入增速差达到 {metrics.get('C3')}，应收扩张快于业务增长。",
            "action": "按客户分层重做信用政策，停止低质量放量，先把存量应收回款和坏账边界看清。"})
    if "R4" in risk_map:
        cards.append({"priority": "P1", "title": "重排短债与现金储备",
            "reason": f"现金短债比/流动比率承压，当前 S4={metrics.get('S4')}，S1={metrics.get('S1')}。",
            "action": "把未来 12 个月债务到期结构和可动用现金池拉成一张表，优先处理高成本短债续作。"})
    if "R8" in risk_map:
        cards.append({"priority": "P1", "title": "复核减值与异常资产",
            "reason": "系统识别到重大减值/关联交易风险，当前资产质量判断需要更谨慎。",
            "action": "对减值资产逐项做成因复盘，拆分一次性冲击和持续性压力，避免后续继续侵蚀利润。"})
    if "R6" in risk_map or "R7" in risk_map:
        cards.append({"priority": "P2", "title": "治理与合规事项闭环",
            "reason": "审计、处罚或诉讼信号已经进入评分链，会持续压制外部信任。",
            "action": "建立专项整改台账，明确责任部门、关闭时间和对外披露口径，避免事件持续发酵。"})
    if "O1" in opportunity_map or "O2" in opportunity_map:
        cards.append({"priority": "P3", "title": "放大盈利与现金改善窗口",
            "reason": "系统识别到毛利或现金质量改善信号，这部分正向变化值得继续验证并扩大。",
            "action": "把改善来源拆到产品、客户和区域三层，确认是结构性修复还是短期波动，再决定资源倾斜。"})
    if not cards:
        weakest = score_result["weaknesses"][0]["name"] if score_result["weaknesses"] else "关键弱项"
        cards.append({"priority": "P2", "title": "围绕最弱指标做季度整改",
            "reason": f"当前最弱项集中在 {weakest}，需要把指标问题转成经营动作。",
            "action": "把该指标拆成业务责任项、月度跟踪项和结果验收项，连续两个经营周期跟踪闭环。"})
    return cards[:3]


def _build_company_charts(
    company: dict[str, Any], score_result: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "type": "radar",
            "title": "五维运营雷达",
            "options": {
                "radar": {"indicator": [
                    {"name": name, "max": 100}
                    for name in score_result["dimension_scores"].keys()
                ]},
                "series": [{"type": "radar", "data": [{
                    "value": list(score_result["dimension_scores"].values()),
                    "name": company["company_name"],
                }]}],
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
        if card := _build_formula_card(company, metric_code):
            cards.append(card)
    return cards


def _build_formula_card(company: dict[str, Any], metric_code: str) -> dict[str, Any] | None:
    context = company.get("formula_context", {}).get(metric_code)
    if not context:
        return None
    metric_def = METRIC_BY_CODE[metric_code]
    if metric_code == "C3":
        return {
            "metric_code": metric_code, "title": metric_def.name,
            "formula": context["formula"], "value": context["value"],
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
            "metric_code": metric_code, "title": metric_def.name,
            "formula": context["formula"], "value": context["value"],
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
    return [
        {"step": f"{card['metric_code']} 公式回放", "detail": {
            "formula": card["formula"], "value": card["value"], "lines": card["lines"],
        }}
        for card in formula_cards
    ]


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
        linked_formula_codes = []
        for metric_code in LABEL_METRIC_CODES.get(label["code"], ()):
            metric_rows.append({
                "metric_code": metric_code,
                "metric_name": METRIC_BY_CODE[metric_code].name,
                "value": company["metrics"].get(metric_code),
            })
            if metric_code in formula_card_by_metric:
                linked_formula_codes.append(metric_code)
        label_cards.append({
            "code": label["code"],
            "name": label["name"],
            "kind": "risk" if label["code"].startswith("R") else "opportunity",
            "signal_values": label["signal_values"],
            "evidence_refs": label["evidence_refs"],
            "metrics": metric_rows,
            "formula_metric_codes": linked_formula_codes,
            "anchor_terms": _anchor_terms_for_metrics(LABEL_METRIC_CODES.get(label["code"], ())),
        })
    return label_cards


def _build_evidence_groups(
    label_cards: list[dict[str, Any]],
    formula_cards: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_by_id = {item["chunk_id"]: item for item in evidence}
    groups: list[dict[str, Any]] = []
    for card in label_cards:
        items = [evidence_by_id[cid] for cid in card["evidence_refs"] if cid in evidence_by_id]
        if items:
            groups.append({
                "group_type": "label", "code": card["code"],
                "title": f"{card['code']} {card['name']}", "subtitle": "标签触发证据",
                "anchor_terms": card.get("anchor_terms", []), "items": items,
            })
    for card in formula_cards:
        items = [evidence_by_id[cid] for cid in card["evidence_refs"] if cid in evidence_by_id]
        if items:
            groups.append({
                "group_type": "formula", "code": card["metric_code"],
                "title": f"{card['metric_code']} {card['title']}", "subtitle": "公式输入证据",
                "anchor_terms": card.get("anchor_terms", []), "items": items,
            })
    if evidence:
        groups.append({
            "group_type": "all", "code": "ALL",
            "title": "全部证据", "subtitle": "当前评分结果涉及的完整证据包",
            "anchor_terms": [], "items": evidence,
        })
    return groups


def _anchor_terms_for_metrics(metric_codes: tuple[str, ...] | list[str]) -> list[str]:
    terms: list[str] = []
    for code in metric_codes:
        for term in METRIC_ANCHOR_TERMS.get(code, (METRIC_BY_CODE[code].name,)):
            if term not in terms:
                terms.append(term)
    return terms


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
        {"step": 1, "label": "总分",
         "value": f"{score_result['total_score']} / {score_result['grade']}",
         "tone": "accent", "intensity": min(100, 30 + int(score_result["total_score"]))},
        {"step": 2, "label": "风险",
         "value": risks[0]["name"] if risks else "无显著风险",
         "tone": "risk" if risks else "success", "intensity": 76 if risks else 28},
        {"step": 3, "label": "动作",
         "value": action_cards[0]["title"] if action_cards else "等待动作收口",
         "tone": "warning" if action_cards else "accent", "intensity": 68 if action_cards else 20},
    ]
    if opportunities:
        tape.append({"step": 4, "label": "机会", "value": opportunities[0]["name"],
                     "tone": "success", "intensity": 54})
    return tape


def _list_company_periods(repository: Any, company_name: str) -> list[str]:
    if hasattr(repository, "list_company_periods"):
        return repository.list_company_periods(company_name)
    return []


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
