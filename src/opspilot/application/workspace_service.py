"""
workspace_service.py — Domain service for AI-powered collaborative analysis.

Responsibilities:
  - Multi-turn chat with Agent orchestration (WorkspaceService.chat_turn)
  - Hybrid RAG evidence enrichment (BM25 + pgvector + LLM reranker)
  - Metric direct-query with formula replay (WorkspaceService.metric_query)
  - Workspace run persistence & history (workspace_runs, workspace_run_detail)

Architecture:
  WorkspaceService orchestrates the agent pipeline defined in agents.py.
  The LLM selects tools from a role-based whitelist (Tool Calling).
  Post-answer, Hybrid RAG enriches thin evidence via BM25 ⊕ dense ANN → RRF.
"""
from __future__ import annotations

from collections import Counter
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opspilot.config import Settings
from opspilot.application.evidence_runtime import build_evidence_detail
from opspilot.domain.audit import build_audit
from opspilot.domain.catalog import METRIC_BY_CODE
from opspilot.domain.evidence import deduplicate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role profiles — used by builder helpers
# ---------------------------------------------------------------------------

ROLE_PROFILES: dict[str, dict[str, Any]] = {
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

TOOL_DISPLAY_LABELS: dict[str, str] = {
    "tool_score_company": "企业评分",
    "tool_risk_scan": "行业风险扫描",
    "tool_verify_claim": "研报核验",
    "tool_benchmark_company": "同业对标",
    "tool_stress_test": "压力测试",
    "tool_graph_query": "图谱检索",
    "tool_company_timeline": "时间线回放",
}

QUERY_TYPE_DISPLAY_LABELS: dict[str, str] = {
    "company_scoring": "经营体检",
    "claim_verification": "研报核验",
    "peer_benchmark": "同业对标",
    "risk_scan": "行业预警",
    "metric_query": "指标直查",
    "graph_query": "图谱检索",
    "stress_test": "压力测试",
    "company_timeline": "时间线回放",
    "brief_generation": "经营简报",
}


# ---------------------------------------------------------------------------
# WorkspaceService
# ---------------------------------------------------------------------------

class WorkspaceService:
    """
    AI-powered collaborative analysis service.

    Pipeline for chat_turn:
      1. Router Agent  — intent classification + company resolution
      2. Domain Agents — Tool Calling selects score/benchmark/verify/scan tools
      3. Hybrid RAG    — BM25 ⊕ pgvector ANN → RRF → LLM reranker (top-k chunks)
      4. Builder layer — workspace payload, agent flow, control plane, follow-ups
      5. Persistence   — run manifest + detail JSON for audit trail
    """

    def __init__(self, repository: Any, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    async def chat_turn(
        self,
        *,
        query: str,
        company_name: str | None = None,
        report_period: str | None = None,
        user_role: str = "investor",
        service: Any,                       # back-reference to OpsPilotService facade
    ) -> dict[str, Any]:
        """
        Single conversational turn.

        Calls the LLM orchestrator (Tool Calling), enriches evidence via
        Hybrid RAG, then builds a structured workspace payload.
        """
        from opspilot.application.agents import run_orchestrator

        period = report_period or self._preferred_period()
        detected_company = (
            company_name
            or self.repository.find_company_from_query(query, period)
            or self.repository.find_company_from_query(query, None)
        )

        # Stage 1 — Agent Orchestration (LLM Tool Calling)
        payload = await run_orchestrator(
            query=query,
            company_name=detected_company,
            report_period=period,
            user_role=user_role,
            service=service,
        )

        # Stage 2 — Hybrid RAG Evidence Enrichment
        # For metric_query or when structured evidence is thin, augment with
        # text passage retrieval: BM25 (top-20) ⊕ pgvector ANN (top-20) → RRF
        # → LLM zero-shot reranker → top-k chunks.
        query_type = payload.get("query_type", "")
        current_evidence = payload.get("evidence", [])
        openai_api_key = getattr(self.settings, "openai_api_key", "")
        retrieval_required = detected_company and (
            query_type == "metric_query"
            or len(current_evidence) < self.settings.audit_min_evidence
        )
        if retrieval_required:
            if not openai_api_key:
                raise RuntimeError("文本补证依赖的模型鉴权未配置，无法生成可核验分析结果。")
            extra_chunks = await self.repository.hybrid_evidence_search(
                company_name=detected_company,
                query=query,
                report_period=period,
                dsn=self.settings.postgres_dsn,
                top_k=4,
            )
            if extra_chunks:
                payload["evidence"] = deduplicate(current_evidence + extra_chunks)
            payload["retrieval_meta"] = {
                "attempted": True,
                "enriched_count": len(extra_chunks),
                "status": "augmented" if extra_chunks else "no_hit",
            }
        else:
            payload["retrieval_meta"] = {
                "attempted": False,
                "enriched_count": 0,
                "status": "not_required",
            }

        # Stage 3 — Build structured workspace payload
        workspace_payload = _build_workspace_payload(payload, query=query, user_role=user_role)
        return self._persist_workspace_run(
            workspace_payload,
            query=query,
            company_name=detected_company,
            user_role=user_role,
        )

    def metric_query(
        self,
        *,
        query: str,
        company_name: str | None,
        report_period: str | None,
    ) -> dict[str, Any]:
        """Direct metric lookup with formula replay and evidence chain."""
        if not company_name:
            raise ValueError("当前问答需要显式包含公司名。")
        company = self._resolve_company(company_name, report_period)
        if company is None:
            raise ValueError(f"未找到公司：{company_name}")
        metric_code = _guess_metric_code(query)
        metric_def = METRIC_BY_CODE[metric_code]
        value = company["metrics"][metric_code]
        evidence = self.repository.resolve_evidence(
            company.get("metric_evidence", {}).get(metric_code, [])
        )
        calculations = [{"step": "指标直取", "detail": f"{metric_code} = {value}"}]
        formula_cards: list[dict[str, Any]] = []
        if formula_card := _build_formula_card_simple(company, metric_code):
            formula_cards.append(formula_card)
            calculations.extend(_build_formula_calculations_simple(formula_cards))
        audit = build_audit(
            key_numbers=[{"label": metric_def.name, "value": value, "unit": ""}],
            evidence=evidence,
            calculations=calculations,
            min_evidence=self.settings.audit_min_evidence,
        )
        return {
            "company_name": company["company_name"],
            "report_period": company["report_period"],
            "answer_markdown": (
                f"**{company_name}** 在 **{company['report_period']}** 的 "
                f"**{metric_def.name}** 为 **{value}**。"
            ),
            "query_type": "metric_query",
            "key_numbers": [{"label": metric_def.name, "value": value, "unit": ""}],
            "charts": [],
            "evidence": evidence,
            "calculations": calculations,
            "formula_cards": formula_cards,
            "audit": audit,
        }

    def get_evidence(self, chunk_id: str, *, user_role: str = "management") -> dict[str, Any]:
        return build_evidence_detail(self, chunk_id, user_role=user_role)

    def workspace_runs(self, limit: int = 20) -> dict[str, Any]:
        manifest = _load_workspace_run_manifest(self.settings)
        records = sorted(
            manifest["records"],
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        return {"total": len(records), "runs": records[:limit]}

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
            raise ValueError(f"运行记录损坏：{run_id}") from exc
        return {"run": record, "detail": detail}

    def workspace_runtime_audit(
        self,
        *,
        limit: int = 10,
        lookback: int = 60,
    ) -> dict[str, Any]:
        manifest = _load_workspace_run_manifest(self.settings)
        records = sorted(
            manifest["records"],
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        selected_records = records[:lookback]

        model_counter: Counter[str] = Counter()
        tool_counter: Counter[str] = Counter()
        query_type_counter: Counter[str] = Counter()
        role_counter: Counter[str] = Counter()
        company_counter: Counter[str] = Counter()

        audited_runs = 0
        grounded_runs = 0
        complete_trace_runs = 0
        tool_enabled_runs = 0
        execution_total = 0.0
        llm_total = 0.0
        tool_total = 0.0
        execution_samples = 0
        llm_samples = 0
        tool_samples = 0
        tool_call_total = 0
        evidence_total = 0
        evidence_samples = 0

        recent_runs: list[dict[str, Any]] = []
        company_stats: dict[str, dict[str, Any]] = {}

        for record in selected_records:
            detail = _load_workspace_run_detail_safe(self.settings, record)
            sample = _build_workspace_runtime_sample(record, detail)
            recent_runs.append(sample)

            query_type_counter[sample["query_type_label"]] += 1
            role_counter[sample["role_label"]] += 1
            if sample["company_name"]:
                company_counter[sample["company_name"]] += 1
                stats = company_stats.setdefault(
                    sample["company_name"],
                    {
                        "company_name": sample["company_name"],
                        "run_count": 0,
                        "grounded_count": 0,
                        "execution_total": 0.0,
                        "execution_samples": 0,
                        "latest_run_at": sample["created_at"],
                    },
                )
                stats["run_count"] += 1
                if sample["created_at"] and sample["created_at"] > (stats.get("latest_run_at") or ""):
                    stats["latest_run_at"] = sample["created_at"]
                if sample["execution_ms"] is not None:
                    stats["execution_total"] += float(sample["execution_ms"])
                    stats["execution_samples"] += 1

            if not detail:
                continue

            audited_runs += 1
            if sample["model"]:
                model_counter[sample["model"]] += 1
            if sample["assurance_status"] == "grounded":
                grounded_runs += 1
                if sample["company_name"]:
                    company_stats[sample["company_name"]]["grounded_count"] += 1

            if sample["trace_complete"]:
                complete_trace_runs += 1
            if sample["tool_call_count"] > 0:
                tool_enabled_runs += 1
            tool_call_total += sample["tool_call_count"]

            if sample["execution_ms"] is not None:
                execution_total += float(sample["execution_ms"])
                execution_samples += 1
            if sample["llm_elapsed_ms"] is not None:
                llm_total += float(sample["llm_elapsed_ms"])
                llm_samples += 1
            if sample["tool_elapsed_ms"] is not None:
                tool_total += float(sample["tool_elapsed_ms"])
                tool_samples += 1
            if sample["evidence_count"] is not None:
                evidence_total += int(sample["evidence_count"])
                evidence_samples += 1

            for label in sample["tool_labels"]:
                tool_counter[label] += 1

        company_heat = []
        for stats in company_stats.values():
            avg_execution_ms = None
            if stats["execution_samples"]:
                avg_execution_ms = round(stats["execution_total"] / stats["execution_samples"], 1)
            company_heat.append(
                {
                    "company_name": stats["company_name"],
                    "run_count": stats["run_count"],
                    "grounded_count": stats["grounded_count"],
                    "avg_execution_ms": avg_execution_ms,
                    "latest_run_at": stats["latest_run_at"],
                }
            )
        company_heat.sort(
            key=lambda item: (
                -int(item.get("run_count") or 0),
                -int(item.get("grounded_count") or 0),
                item.get("company_name") or "",
            )
        )

        grounded_ratio = _ratio_percent(grounded_runs, audited_runs)
        trace_ratio = _ratio_percent(complete_trace_runs, audited_runs)
        tool_ratio = _ratio_percent(tool_enabled_runs, audited_runs)
        audit_status, audit_label = _resolve_workspace_runtime_audit_status(
            audited_runs=audited_runs,
            grounded_ratio=grounded_ratio,
            trace_ratio=trace_ratio,
        )

        return {
            "generated_at": _utcnow_iso(),
            "status": audit_status,
            "label": audit_label,
            "window_size": len(selected_records),
            "total_runs": len(records),
            "audited_runs": audited_runs,
            "summary_cards": {
                "grounded_ratio": grounded_ratio,
                "trace_ratio": trace_ratio,
                "tool_ratio": tool_ratio,
                "avg_execution_ms": _average_or_none(execution_total, execution_samples),
                "avg_llm_elapsed_ms": _average_or_none(llm_total, llm_samples),
                "avg_tool_elapsed_ms": _average_or_none(tool_total, tool_samples),
                "avg_tool_call_count": _average_or_none(tool_call_total, audited_runs),
                "avg_evidence_count": _average_or_none(evidence_total, evidence_samples),
            },
            "model_mix": _counter_to_ranked_items(model_counter, limit=4),
            "tool_mix": _counter_to_ranked_items(tool_counter, limit=6),
            "query_mix": _counter_to_ranked_items(query_type_counter, limit=6),
            "role_mix": _counter_to_ranked_items(role_counter, limit=3),
            "company_heat": company_heat[:6],
            "recent_runs": recent_runs[:limit],
            "latest_run_at": recent_runs[0]["created_at"] if recent_runs else None,
            "latest_company_name": recent_runs[0]["company_name"] if recent_runs else None,
        }

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

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
            "run_id": run_id, "query": query,
            "company_name": payload.get("company_name") or company_name,
            "report_period": payload.get("report_period"),
            "user_role": user_role,
            "query_type": payload.get("query_type"),
            "answer_markdown": payload.get("answer_markdown"),
            "control_plane": payload.get("control_plane"),
            "ai_assurance": payload.get("ai_assurance"),
            "agent_runtime": payload.get("agent_runtime"),
            "agent_flow": payload.get("agent_flow"),
            "tool_trace": payload.get("tool_trace"),
            "answer_sections": payload.get("answer_sections"),
            "insight_cards": payload.get("insight_cards"),
            "follow_up_questions": payload.get("follow_up_questions"),
            "action_cards": payload.get("action_cards"),
            "formula_cards": payload.get("formula_cards"),
            "charts": payload.get("charts"),
            "evidence_groups": payload.get("evidence_groups"),
            "created_at": _utcnow_iso(),
        }
        _write_json(detail_path, detail_payload)
        manifest = _load_workspace_run_manifest(self.settings)
        record = {
            "run_id": run_id, "query": query,
            "company_name": detail_payload["company_name"],
            "report_period": detail_payload["report_period"],
            "user_role": user_role,
            "query_type": detail_payload["query_type"],
            "detail_path": str(detail_path),
            "created_at": detail_payload["created_at"],
            "control_plane_status": payload.get("control_plane", {}).get("session_label"),
            "agent_model": payload.get("agent_runtime", {}).get("model"),
            "tool_call_count": payload.get("agent_runtime", {}).get("tool_call_count", 0),
            "execution_ms": payload.get("agent_runtime", {}).get("total_elapsed_ms"),
        }
        manifest["records"] = [
            item for item in manifest["records"] if item.get("run_id") != run_id
        ]
        manifest["records"].append(record)
        _write_workspace_run_manifest(self.settings, manifest)
        return {**payload, "run_id": run_id}

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
# Workspace payload builders (pure functions)
# ---------------------------------------------------------------------------

def _build_workspace_payload(
    payload: dict[str, Any],
    *,
    query: str,
    user_role: str,
) -> dict[str, Any]:
    """Assemble full workspace response including agent flow, answer sections, etc."""
    role_profile = _build_role_profile(user_role)
    agent_runtime = _build_agent_runtime(payload)
    answer_sections = _build_answer_sections(payload, role_profile["key"])
    insight_cards = _build_workspace_insight_cards(payload)
    follow_up_questions = _build_follow_up_questions(payload, role_profile["key"])
    agent_flow = _build_agent_flow(payload, query, role_profile["key"])
    ai_assurance = _build_ai_assurance(payload, agent_runtime)
    control_plane = _build_control_plane(payload, query, role_profile["key"], agent_flow, ai_assurance, agent_runtime)
    return {
        **payload,
        "role_profile": role_profile,
        "answer_sections": answer_sections,
        "insight_cards": insight_cards,
        "follow_up_questions": follow_up_questions,
        "agent_flow": agent_flow,
        "control_plane": control_plane,
        "ai_assurance": ai_assurance,
        "agent_runtime": agent_runtime,
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
        risk_names = [item["name"] for item in scorecard.get("risk_labels", [])[:2]]
        opportunity_names = [item["name"] for item in scorecard.get("opportunity_labels", [])[:2]]
        return [
            {"title": "当前判断", "lines": [
                f"{company_name} 在 {report_period} 的总分 {scorecard.get('total_score')}，当前等级 {scorecard.get('grade')}。",
                f"当前处于 {payload.get('subindustry', '所属子行业')} 的分位 {scorecard.get('subindustry_percentile')}。",
            ]},
            {"title": "为什么这样看", "lines": [
                f"风险侧先看：{'、'.join(risk_names)}。"
                if risk_names else "当前没有命中高风险标签。",
                f"机会侧还能看：{'、'.join(opportunity_names)}。"
                if opportunity_names else "当前没有明显新增机会标签。",
            ]},
            {"title": "先做什么", "lines": [
                f"{item['priority']} {item['title']}：{item['action']}"
                for item in payload.get("action_cards", [])[:3]
            ] or ["当前没有新增动作要求。"]},
        ]
    if query_type == "claim_verification":
        report_meta = payload.get("report_meta", {})
        mismatches = [
            item["claim_text"]
            for item in payload.get("claim_cards", [])
            if item.get("status") != "match"
        ][:3]
        return [
            {"title": "当前判断", "lines": [
                f"这次核对的是《{report_meta.get('title', '未命名研报')}》，报期 {report_period}。",
                f"一致 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'match')} 条，不一致 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'mismatch')} 条。",
            ]},
            {"title": "哪些地方对不上", "lines": mismatches or ["当前没有发现明显偏差。"]},
            {"title": "继续看哪里", "lines": [
                f"{item['forecast_year']} 年：{item['profit_value']} 亿元，PE {item['pe_value']} 倍"
                for item in payload.get("forecast_cards", [])[:3]
            ] or ["先回到原文页和盈利预测表继续核对。"]},
        ]
    if query_type == "peer_benchmark":
        benchmark = payload.get("benchmark", [])
        return [
            {"title": "当前判断", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]},
            {"title": "同业谁更强", "lines": [
                f"{i + 1}. {item['company_name']} {item['total_score']} 分"
                for i, item in enumerate(benchmark[:3])
            ]},
        ]
    if query_type == "graph_query":
        focal_nodes = payload.get("focal_nodes", [])
        return [
            {"title": "当前判断", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]},
            {"title": "为什么这样看", "lines": [
                f"{item.get('label')}：{item.get('reason') or item.get('type')}"
                for item in focal_nodes[:5]
            ] or ["当前未命中关键节点。"]},
            {"title": "继续看哪里", "lines": [
                f"{item.get('step')}. {item.get('title')}：{item.get('detail')}"
                for item in payload.get("inference_path", [])[:3]
            ] or ["当前未形成稳定传导路径。"]},
        ]
    if query_type == "stress_test":
        severity = payload.get("severity", {})
        action_cards = payload.get("action_cards", [])
        return [
            {"title": "当前判断", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]},
            {"title": "为什么这样看", "lines": [
                f"这轮冲击等级：{severity.get('label', '待确认')}",
                f"当前场景：{payload.get('scenario', '未提供')}",
            ]},
            {"title": "先做什么", "lines": [
                f"{item.get('title')}：{item.get('action') or item.get('reason')}"
                for item in action_cards[:3]
            ] or [
                f"{item.get('stage')}：{item.get('headline')}（{item.get('impact_label')} {item.get('impact_score')}）"
                for item in payload.get("transmission_matrix", [])[:3]
            ] or ["当前没有可用的传导链结果。"]},
        ]
    if query_type == "company_timeline":
        return [
            {"title": "当前判断", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]},
            {"title": "最近几期", "lines": [
                f"{item.get('report_period')}：总分 {item.get('total_score')}，评级 {item.get('grade')}"
                for item in payload.get("snapshots", [])[:3]
            ] or ["当前没有可回放的报期记录。"]},
        ]
    if query_type == "risk_scan":
        return [
            {"title": "当前判断", "lines": [
                f"{item['company_name']}：{item['summary']}"
                for item in payload.get("alert_board", [])[:4]
            ] or ["当前主周期没有新增重点预警。"]},
            {"title": "先盯这些公司", "lines": [
                f"{item['company_name']}：{item['risk_count']} 个风险标签"
                for item in payload.get("risk_board", [])[:5]
            ]},
        ]
    if query_type == "metric_query":
        return [{"title": "当前数字", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]}]
    if query_type == "brief_generation":
        answer = _strip_markdown(payload.get("answer_markdown", ""))
        return [{"title": "这轮简报", "lines": [ln for ln in answer.splitlines() if ln.strip()]}]
    return [{"title": "当前判断", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]}]


def _build_workspace_insight_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    query_type = payload.get("query_type")
    cards = [
        {"label": item.get("label"), "value": item.get("value"), "unit": item.get("unit")}
        for item in payload.get("key_numbers", [])[:3]
        if item.get("label")
    ]
    if query_type == "company_scoring":
        scorecard = payload.get("scorecard", {})
        cards = [
            {"label": "总分", "value": scorecard.get("total_score"), "unit": "分"},
            {"label": "等级", "value": scorecard.get("grade"), "unit": ""},
            {"label": "子行业分位", "value": scorecard.get("subindustry_percentile"), "unit": ""},
        ]
    elif query_type == "claim_verification":
        cards = [
            {
                "label": "一致",
                "value": sum(1 for item in payload.get("claim_cards", []) if item.get("status") == "match"),
                "unit": "条",
            },
            {
                "label": "不一致",
                "value": sum(1 for item in payload.get("claim_cards", []) if item.get("status") == "mismatch"),
                "unit": "条",
            },
            {
                "label": "盈利预测",
                "value": len(payload.get("forecast_cards", [])),
                "unit": "组",
            },
        ]
    elif query_type == "stress_test" and not cards:
        severity = payload.get("severity", {})
        cards = [
            {"label": "冲击等级", "value": severity.get("label"), "unit": ""},
            {"label": "传导阶段", "value": len(payload.get("transmission_matrix", [])), "unit": "段"},
            {"label": "优先动作", "value": len(payload.get("action_cards", [])), "unit": "条"},
        ]
    return cards[:3]


def _build_follow_up_questions(payload: dict[str, Any], role_key: str) -> list[str]:
    company_name = payload.get("company_name")
    report_period = payload.get("report_period")
    company_period = (
        f"{company_name} {report_period}" if company_name and report_period else company_name
    )
    if payload.get("query_type") == "company_scoring" and company_name and report_period:
        if role_key == "management":
            return [
                f"{company_period}最先要修复的经营环节是什么？",
                f"{company_period}现金和应收谁的问题更重？",
                f"{company_period}有哪些动作能在一个季度内见效？",
            ]
        if role_key == "regulator":
            return [
                f"{company_period}有哪些需要持续跟踪的事件信号？",
                f"{company_period}和上一期相比新增了哪些风险？",
                f"{company_period}是否存在研报与财报偏差？",
            ]
        return [
            f"{company_period}和同业龙头差距主要在哪？",
            f"{company_period}最新研报观点是否可信？",
            f"{company_period}最影响估值的风险是什么？",
        ]
    if payload.get("query_type") == "claim_verification" and company_name:
        return [
            f"{company_name}还有哪些研报可以横向对比？",
            f"{company_name}最新评级动作和目标价是什么？",
            f"{company_name}哪些观点缺少真实财报支撑？",
        ]
    if payload.get("query_type") == "graph_query" and company_name:
        return [
            f"{company_name}这条主传导链里最先失稳的是哪个节点？",
            f"{company_name}上游和下游谁对当前风险更敏感？",
            f"{company_name}这条链路还需要补哪些证据？",
        ]
    if payload.get("query_type") == "stress_test" and company_name:
        return [
            f"{company_name}当前压力场景下最先要守住哪个指标？",
            f"{company_name}哪些恢复动作能优先缓解冲击？",
            f"{company_name}这个场景是否需要升级预警等级？",
        ]
    if payload.get("query_type") == "company_timeline" and company_name:
        return [
            f"{company_name}近几期最明显的拐点出现在什么时候？",
            f"{company_name}哪一个风险标签是持续恶化的？",
            f"{company_name}最新一期和上一期相比最大的变化是什么？",
        ]
    return ROLE_PROFILES[role_key]["starter_queries"]


def _build_agent_flow(
    payload: dict[str, Any], query: str, role_key: str
) -> list[dict[str, Any]]:
    """Build the 4-step agent flow display: Router → Data → Risk → Strategy."""
    evidence_count = len(payload.get("evidence", []))
    action_count = len(payload.get("action_cards", []))
    risk_count = len(payload.get("scorecard", {}).get("risk_labels", []))
    formula_count = len(payload.get("formula_cards", []))
    claim_count = len(payload.get("claim_cards", []))
    query_type = payload.get("query_type")
    tools_called = [t["tool_name"] for t in payload.get("tool_trace", []) if t.get("success")]
    return [
        {
            "step": 1, "agent_key": "router", "agent_label": "任务识别", "agent": "任务识别",
            "status": "completed", "title": "先锁定这轮问题",
            "summary": f"这轮围绕“{query}”展开，当前类型是 {QUERY_TYPE_DISPLAY_LABELS.get(str(query_type or ''), '协同分析')}。",
            "source": "问题文本 + 公司池 + 报期索引", "tool": "intent_router", "handoff": "data",
            "route": _build_agent_route("orchestrator", payload),
            "metrics": [
                {"label": "任务类型", "value": QUERY_TYPE_DISPLAY_LABELS.get(str(query_type or ''), query_type or "协同分析")},
                {"label": "目标公司", "value": payload.get("company_name", "未显式指定")},
                {"label": "目标报期", "value": payload.get("report_period", "自动选择")},
            ],
        },
        {
            "step": 2, "agent_key": "data", "agent_label": "数据分析", "agent": "数据分析",
            "status": "completed", "title": "再拉这轮关键数据",
            "summary": (
                f"已拿到 {len(payload.get('key_numbers', []))} 个关键数字，补到 {risk_count} 个风险和 {formula_count} 条公式线。"
                if query_type == "company_scoring"
                else f"已拉出 {len(payload.get('key_numbers', []))} 个关键结果，并沿当前问题补回相关数据。"
            ),
            "source": _resolve_agent_signal_source(query_type),
            "tool": _resolve_agent_signal_tool(query_type), "handoff": "risk",
            "route": _build_agent_route("signal_analyst", payload),
            "metrics": _build_signal_agent_metrics(payload, risk_count, formula_count, claim_count),
        },
        {
            "step": 3, "agent_key": "risk", "agent_label": "证据校验", "agent": "证据校验",
            "status": "completed", "title": "回到原文核对依据",
            "summary": f"这轮一共回挂 {evidence_count} 条证据，优先保留最能直接核对的原文片段。",
            "source": "官方财报页级解析 + 研报详情页 + 公式输入字段", "tool": "evidence_auditor",
            "handoff": "strategy", "route": _build_agent_route("evidence_auditor", payload),
            "metrics": [
                {"label": "证据条数", "value": evidence_count},
                {"label": "证据分组", "value": len(payload.get("evidence_groups", []))},
                {"label": "公式回放", "value": formula_count},
            ],
        },
        {
            "step": 4, "agent_key": "strategy", "agent_label": "策略生成",
            "agent": "策略生成", "status": "completed", "title": "最后落到下一步",
            "summary": (
                f"这轮已经整理出 {action_count} 条下一步。" if action_count
                else f"这轮暂时没有直接动作，先转成 {ROLE_PROFILES[role_key]['label']} 视角的继续追问。"
            ),
            "source": "评分结果 + 风险标签 + 角色视角", "tool": "action_planner",
            "handoff": "返回工作台", "route": _build_agent_route("action_planner", payload),
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
    ai_assurance: dict[str, Any],
    agent_runtime: dict[str, Any],
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
        "result_label": QUERY_TYPE_DISPLAY_LABELS.get(str(payload.get("query_type") or ""), "协同分析"),
        "next_focus": agent_flow[-1]["title"] if agent_flow else "继续追问",
        "assurance_label": ai_assurance.get("label"),
        "assurance_status": ai_assurance.get("status"),
        "model": agent_runtime.get("model"),
        "execution_ms": agent_runtime.get("total_elapsed_ms"),
        "tool_round_count": agent_runtime.get("tool_round_count"),
    }


def _build_ai_assurance(payload: dict[str, Any], agent_runtime: dict[str, Any]) -> dict[str, Any]:
    tool_trace = payload.get("tool_trace", [])
    successful_tools = [item["tool_name"] for item in tool_trace if item.get("success") and item.get("tool_name")]
    failed_tools = [item["tool_name"] for item in tool_trace if not item.get("success") and item.get("tool_name")]
    evidence_count = len(payload.get("evidence", []))
    evidence_group_count = len(payload.get("evidence_groups", []))
    formula_count = len(payload.get("formula_cards", []))
    key_number_count = len(payload.get("key_numbers", []))
    retrieval_meta = payload.get("retrieval_meta", {})
    retrieval_attempted = bool(retrieval_meta.get("attempted"))
    retrieval_enriched_count = int(retrieval_meta.get("enriched_count", 0) or 0)
    has_runtime_trace = bool(agent_runtime.get("model")) and bool(agent_runtime.get("total_elapsed_ms"))

    if not successful_tools or not has_runtime_trace:
        status = "review"
        label = "待复核"
        summary = "当前轮已有结构化结果，但智能体执行轨迹未完整落盘，不能直接作为正式交付结论。"
        tone = "warning"
    elif evidence_count >= 2 or evidence_group_count >= 1 or formula_count >= 1:
        status = "grounded"
        label = "强支撑"
        summary = "当前结论已绑定真实模型调用、工具执行和证据链，可回放、可抽检、可继续下钻。"
        tone = "success"
    else:
        status = "review"
        label = "待补证"
        summary = "当前结论已有工具结果，但证据链偏薄，适合先复核再用于正式输出。"
        tone = "warning"

    return {
        "status": status,
        "label": label,
        "tone": tone,
        "summary": summary,
        "tool_call_count": len(successful_tools),
        "failed_tool_count": len(failed_tools),
        "tool_labels": successful_tools[:6],
        "failed_tool_labels": failed_tools[:4],
        "evidence_count": evidence_count,
        "evidence_group_count": evidence_group_count,
        "formula_count": formula_count,
        "key_number_count": key_number_count,
        "retrieval_attempted": retrieval_attempted,
        "retrieval_enriched_count": retrieval_enriched_count,
        "retrieval_status": retrieval_meta.get("status"),
        "model": agent_runtime.get("model"),
        "tool_round_count": agent_runtime.get("tool_round_count"),
        "llm_elapsed_ms": agent_runtime.get("llm_elapsed_ms"),
        "total_elapsed_ms": agent_runtime.get("total_elapsed_ms"),
    }


def _build_agent_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    raw_runtime = payload.get("agent_runtime") or {}
    tool_trace = payload.get("tool_trace", [])
    trace_records = [
        {
            "index": index,
            "round_index": int(item.get("round_index") or 1),
            "tool_name": item.get("tool_name"),
            "tool_label": TOOL_DISPLAY_LABELS.get(str(item.get("tool_name") or ""), "工具执行"),
            "success": bool(item.get("success")),
            "elapsed_ms": round(float(item.get("elapsed_ms") or 0.0), 1),
            "arguments": item.get("arguments", {}),
            "arguments_preview": _compact_json_preview(item.get("arguments", {}), limit=132),
            "result_preview": _compact_json_preview(item.get("result_summary", ""), limit=180),
            "executed_at": item.get("executed_at"),
        }
        for index, item in enumerate(tool_trace, start=1)
        if isinstance(item, dict)
    ]
    tool_elapsed_ms = round(
        sum(float(item.get("elapsed_ms") or 0.0) for item in trace_records),
        1,
    )
    llm_elapsed_ms = round(float(raw_runtime.get("llm_elapsed_ms") or 0.0), 1)
    total_elapsed_ms = round(float(raw_runtime.get("total_elapsed_ms") or llm_elapsed_ms + tool_elapsed_ms), 1)
    return {
        "model": raw_runtime.get("model"),
        "temperature": raw_runtime.get("temperature"),
        "max_tool_rounds": raw_runtime.get("max_tool_rounds"),
        "started_at": raw_runtime.get("started_at"),
        "finished_at": raw_runtime.get("finished_at"),
        "completion_id": raw_runtime.get("completion_id"),
        "finish_reason": raw_runtime.get("finish_reason"),
        "total_rounds": int(raw_runtime.get("total_rounds") or 0),
        "tool_round_count": int(raw_runtime.get("tool_round_count") or len({item["round_index"] for item in trace_records})),
        "tool_call_count": len(trace_records),
        "successful_tool_count": sum(1 for item in trace_records if item.get("success")),
        "failed_tool_count": sum(1 for item in trace_records if not item.get("success")),
        "llm_elapsed_ms": llm_elapsed_ms,
        "tool_elapsed_ms": tool_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "trace": trace_records,
    }


def _build_workspace_runtime_sample(
    record: dict[str, Any],
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    detail_payload = detail or {}
    agent_runtime = detail_payload.get("agent_runtime") or {}
    ai_assurance = detail_payload.get("ai_assurance") or {}
    trace_records = agent_runtime.get("trace") or []
    if not trace_records:
        trace_records = [
            {
                "tool_name": item.get("tool_name"),
                "tool_label": TOOL_DISPLAY_LABELS.get(str(item.get("tool_name") or ""), "工具执行"),
            }
            for item in detail_payload.get("tool_trace", [])
            if isinstance(item, dict)
        ]

    tool_labels = [
        str(item.get("tool_label") or TOOL_DISPLAY_LABELS.get(str(item.get("tool_name") or ""), "工具执行"))
        for item in trace_records
        if item.get("tool_label") or item.get("tool_name")
    ]
    model = agent_runtime.get("model") or record.get("agent_model")
    tool_call_count = int(
        agent_runtime.get("tool_call_count")
        or record.get("tool_call_count")
        or len(trace_records)
        or 0
    )
    execution_ms = _to_float_or_none(agent_runtime.get("total_elapsed_ms") or record.get("execution_ms"))
    llm_elapsed_ms = _to_float_or_none(agent_runtime.get("llm_elapsed_ms"))
    tool_elapsed_ms = _to_float_or_none(agent_runtime.get("tool_elapsed_ms"))
    evidence_count = ai_assurance.get("evidence_count")
    if evidence_count is None:
        evidence_groups = detail_payload.get("evidence_groups") or []
        evidence_count = sum(
            len(group.get("items", []))
            for group in evidence_groups
            if isinstance(group, dict)
        ) or None
    trace_complete = bool(
        detail
        and model
        and execution_ms is not None
        and (tool_call_count == 0 or len(trace_records) >= tool_call_count)
    )
    return {
        "run_id": record.get("run_id"),
        "query": record.get("query"),
        "company_name": record.get("company_name"),
        "report_period": record.get("report_period"),
        "created_at": record.get("created_at"),
        "role_label": ROLE_PROFILES.get(
            str(record.get("user_role") or ""),
            ROLE_PROFILES["investor"],
        )["label"],
        "query_type": record.get("query_type"),
        "query_type_label": QUERY_TYPE_DISPLAY_LABELS.get(
            str(record.get("query_type") or ""),
            record.get("query_type") or "未知任务",
        ),
        "assurance_status": ai_assurance.get("status") or "unavailable",
        "assurance_label": ai_assurance.get("label") or ("未审计" if detail is None else "待复核"),
        "model": model,
        "tool_call_count": tool_call_count,
        "tool_labels": list(dict.fromkeys(tool_labels)),
        "execution_ms": execution_ms,
        "llm_elapsed_ms": llm_elapsed_ms,
        "tool_elapsed_ms": tool_elapsed_ms,
        "evidence_count": int(evidence_count) if evidence_count is not None else None,
        "trace_complete": trace_complete,
        "trace_status_label": "完整" if trace_complete else ("缺详情" if detail is None else "待补齐"),
    }


def _load_workspace_run_detail_safe(
    settings: Settings,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    candidate_paths: list[Path] = []
    detail_path = record.get("detail_path")
    if detail_path:
        candidate_paths.append(Path(str(detail_path)))
    run_id = str(record.get("run_id") or "")
    if run_id:
        candidate_paths.append(_workspace_run_detail_path(settings, run_id))

    seen_paths: set[str] = set()
    for path in candidate_paths:
        path_key = str(path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            logger.warning("workspace run detail unreadable: %s", path)
            return None
    return None


def _counter_to_ranked_items(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count}
        for label, count in counter.most_common(limit)
        if label
    ]


def _resolve_workspace_runtime_audit_status(
    *,
    audited_runs: int,
    grounded_ratio: int,
    trace_ratio: int,
) -> tuple[str, str]:
    if audited_runs == 0:
        return ("unavailable", "暂无审计数据")
    if grounded_ratio >= 80 and trace_ratio >= 80:
        return ("stable", "执行稳定")
    if grounded_ratio >= 60 and trace_ratio >= 60:
        return ("warming", "持续升温")
    return ("review", "待继续加固")


def _ratio_percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int(round((numerator / denominator) * 100))


def _average_or_none(total: float, count: int) -> float | None:
    if count <= 0:
        return None
    return round(total / count, 1)


def _to_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _compact_json_preview(value: Any, *, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        except TypeError:
            text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _build_agent_route(agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    company_name = payload.get("company_name")
    report_period = payload.get("report_period")
    query_type = payload.get("query_type")
    if agent_name in {"orchestrator", "signal_analyst", "action_planner"} and query_type == "graph_query" and company_name:
        return {"label": "进入图谱分析", "path": "/graph",
                "query": {"company": company_name, "period": report_period}}
    if agent_name in {"orchestrator", "signal_analyst", "action_planner"} and query_type == "stress_test" and company_name:
        return {"label": "进入压力测试", "path": "/stress",
                "query": {"company": company_name, "period": report_period}}
    if agent_name in {"orchestrator", "signal_analyst", "action_planner"} and query_type == "company_timeline" and company_name:
        return {"label": "进入时间线回放", "path": "/workspace",
                "query": {"company": company_name, "period": report_period, "mode": "timeline"}}
    if agent_name in {"orchestrator", "signal_analyst", "action_planner"} and company_name:
        return {"label": "进入企业体检", "path": "/score",
                "query": {"company": company_name, "period": report_period}}
    if agent_name == "signal_analyst" and query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk",
                "query": {"period": report_period} if report_period else {}}
    if agent_name == "evidence_auditor":
        evidence_groups = payload.get("evidence_groups", [])
        first_group = evidence_groups[0] if evidence_groups else None
        first_item = first_group["items"][0] if first_group and first_group.get("items") else None
        if first_item:
            return {
                "label": "打开证据", "path": f"/evidence/{first_item['chunk_id']}",
                "query": {"context": first_group.get("title", "证据"),
                           "anchors": "|".join(first_group.get("anchor_terms", []))},
            }
        if company_name:
            return {
                "label": "回到企业体检",
                "path": "/score",
                "query": {"company": company_name, "period": report_period},
            }
        return {"label": "返回工作台", "path": "/workspace", "query": {}}
    if agent_name == "action_planner" and query_type == "claim_verification" and company_name:
        return {
            "label": "进入研报核验",
            "path": "/verify",
            "query": {"company": company_name, "period": report_period},
        }
    if query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk",
                "query": {"period": report_period} if report_period else {}}
    return {"label": "返回工作台", "path": "/workspace", "query": {}}


def _build_control_plane_sources(payload: dict[str, Any]) -> list[str]:
    mapping = {
        "company_scoring": ["真实财报指标", "规则引擎", "页级证据", "公式回放"],
        "claim_verification": ["真实财报指标", "东方财富研报详情页", "观点核验规则"],
        "peer_benchmark": ["真实财报指标", "同子行业公司池", "横向评分结果"],
        "risk_scan": ["全公司评分快照", "主周期预警板", "行业研报观察"],
        "graph_query": ["企业关系图谱", "执行流记录", "文档升级结果"],
        "stress_test": ["企业体检结果", "图谱关系", "压力场景推演"],
        "company_timeline": ["跨期评分快照", "历史报期", "风险标签变化"],
    }
    return mapping.get(payload.get("query_type", ""), ["真实财报指标", "页级证据", "指标直取"])


def _resolve_agent_signal_source(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "真实财报指标 + 风险规则 + 历史报期对比",
        "claim_verification": "真实财报指标 + 研报观点抽取",
        "peer_benchmark": "同子行业公司池 + 分位结果",
        "risk_scan": "主周期公司池 + 历史报期预警板",
        "graph_query": "企业关系图谱 + 执行流记录 + 文档升级结果",
        "stress_test": "企业体检结果 + 压力场景推演 + 图谱传导链",
        "company_timeline": "历史报期快照 + 风险标签变化 + 图表回放",
        "metric_query": "指标定义 + 页级证据",
        "brief_generation": "评分结果 + 建议动作模板",
    }
    return mapping.get(query_type or "", "真实财报指标")


def _resolve_agent_signal_tool(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "score_engine",
        "claim_verification": "claim_verifier",
        "peer_benchmark": "benchmark_engine",
        "risk_scan": "risk_scanner",
        "graph_query": "graph_reasoner",
        "stress_test": "stress_simulator",
        "company_timeline": "timeline_replayer",
        "metric_query": "metric_router",
        "brief_generation": "brief_builder",
    }
    return mapping.get(query_type or "", "signal_router")


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
            {"label": "匹配观点", "value": sum(1 for i in payload.get("claim_cards", []) if i.get("status") == "match")},
            {"label": "偏差观点", "value": sum(1 for i in payload.get("claim_cards", []) if i.get("status") == "mismatch")},
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
    if query_type == "graph_query":
        return [
            {"label": "焦点节点", "value": len(payload.get("focal_nodes", []))},
            {"label": "推理链路", "value": len(payload.get("inference_path", []))},
            {"label": "图谱节点", "value": payload.get("graph", {}).get("node_count", 0)},
        ]
    if query_type == "stress_test":
        return [
            {"label": "冲击等级", "value": payload.get("severity", {}).get("level", "UNKNOWN")},
            {"label": "传导阶段", "value": len(payload.get("transmission_matrix", []))},
            {"label": "恢复动作", "value": len(payload.get("stress_recovery_sequence", []))},
        ]
    if query_type == "company_timeline":
        return [
            {"label": "报期数", "value": len(payload.get("snapshots", []))},
            {"label": "图表数", "value": len(payload.get("charts", []))},
            {"label": "关键结果", "value": len(payload.get("key_numbers", []))},
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


def _guess_metric_code(query: str) -> str:
    """Infer metric code from free-text query; defaults to G1 (revenue growth)."""
    keywords = {
        "G1": ("营收", "收入", "销售"),
        "G2": ("净利润", "盈利"),
        "G3": ("研发",),
        "C1": ("现金流", "经营活动"),
        "C3": ("应收账款", "应收"),
        "P1": ("毛利率", "毛利"),
        "P4": ("存货",),
        "S1": ("流动比率", "流动"),
        "S3": ("利息保障", "偿债"),
        "S4": ("货币资金", "现金短债"),
        "I1": ("政府补助",),
        "I2": ("审计",),
        "I3": ("诉讼", "处罚"),
        "I4": ("减值", "关联交易"),
    }
    for code, terms in keywords.items():
        if any(term in query for term in terms):
            return code
    return "G1"


def _build_formula_card_simple(
    company: dict[str, Any], metric_code: str
) -> dict[str, Any] | None:
    """Minimal formula card for metric_query (no scoring context needed)."""
    context = company.get("formula_context", {}).get(metric_code)
    if not context:
        return None
    metric_def = METRIC_BY_CODE[metric_code]
    return {
        "metric_code": metric_code,
        "title": metric_def.name,
        "formula": context.get("formula", ""),
        "value": context.get("value"),
        "lines": [f"结果：{context.get('value')}"],
        "evidence_refs": company.get("metric_evidence", {}).get(metric_code, []),
    }


def _build_formula_calculations_simple(
    formula_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"step": f"{card['metric_code']} 公式回放", "detail": {
            "formula": card["formula"], "value": card["value"], "lines": card["lines"],
        }}
        for card in formula_cards
    ]


# ---------------------------------------------------------------------------
# Workspace run persistence helpers
# ---------------------------------------------------------------------------

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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
