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

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opspilot.config import Settings
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
        if detected_company and openai_api_key and (
            query_type == "metric_query"
            or len(current_evidence) < self.settings.audit_min_evidence
        ):
            try:
                extra_chunks = await self.repository.hybrid_evidence_search(
                    company_name=detected_company,
                    query=query,
                    report_period=period,
                    dsn=self.settings.postgres_dsn,
                    top_k=4,
                )
                if extra_chunks:
                    payload["evidence"] = deduplicate(current_evidence + extra_chunks)
            except Exception as exc:
                logger.warning("Hybrid RAG enrichment failed (non-fatal): %s", exc)

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
            raise ValueError("当前样本问答需要显式包含公司名。")
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

    def get_evidence(self, chunk_id: str) -> dict[str, Any]:
        """Retrieve a single evidence chunk by ID."""
        evidence = self.repository.get_evidence(chunk_id)
        if evidence is None:
            raise ValueError(f"未找到证据：{chunk_id}")
        return evidence

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
            "run_id": run_id, "query": query,
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
            {"title": "经营结论", "lines": [
                f"{company_name} 在 {report_period} 的总分为 {scorecard.get('total_score')}，等级 {scorecard.get('grade')}。",
                f"当前处于 {payload.get('subindustry', '所属子行业')} 样本的 {scorecard.get('subindustry_percentile')}pct 位置。",
            ]},
            {"title": "重点风险", "lines": [
                item["name"] for item in scorecard.get("risk_labels", [])
            ] or ["当前没有命中高风险标签。"]},
            {"title": "优先动作", "lines": [
                f"{item['priority']} {item['title']}：{item['action']}"
                for item in payload.get("action_cards", [])[:3]
            ] or ["当前没有新增动作要求。"]},
        ]
    if query_type == "claim_verification":
        report_meta = payload.get("report_meta", {})
        return [
            {"title": "核验结论", "lines": [
                f"当前核验报期为 {report_period}，研报标题为《{report_meta.get('title', '未命名研报')}》。",
                f"匹配观点 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'match')} 条，"
                f"偏差观点 {sum(1 for item in payload.get('claim_cards', []) if item.get('status') == 'mismatch')} 条。",
            ]},
            {"title": "偏差与待核查", "lines": [
                item["claim_text"] for item in payload.get("claim_cards", [])
                if item.get("status") != "match"
            ][:3] or ["当前没有发现明显偏差。"]},
            {"title": "盈利预测", "lines": [
                f"{item['forecast_year']} 年：{item['profit_value']} 亿元，PE {item['pe_value']} 倍"
                for item in payload.get("forecast_cards", [])[:3]
            ] or ["当前研报未提取到明确盈利预测。"]},
        ]
    if query_type == "peer_benchmark":
        benchmark = payload.get("benchmark", [])
        return [
            {"title": "同业位置", "lines": [payload.get("answer_markdown", "")]},
            {"title": "头部公司", "lines": [
                f"{i + 1}. {item['company_name']} {item['total_score']} 分"
                for i, item in enumerate(benchmark[:3])
            ]},
        ]
    if query_type == "risk_scan":
        return [
            {"title": "批量预警", "lines": [
                f"{item['company_name']}：{item['summary']}"
                for item in payload.get("alert_board", [])[:4]
            ] or ["当前主周期没有新增重点预警。"]},
            {"title": "高风险公司", "lines": [
                f"{item['company_name']}：{item['risk_count']} 个风险标签"
                for item in payload.get("risk_board", [])[:5]
            ]},
        ]
    if query_type == "metric_query":
        return [{"title": "指标结果", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]}]
    if query_type == "brief_generation":
        answer = _strip_markdown(payload.get("answer_markdown", ""))
        return [{"title": "经营简报", "lines": [ln for ln in answer.splitlines() if ln.strip()]}]
    return [{"title": "分析结果", "lines": [_strip_markdown(payload.get("answer_markdown", ""))]}]


def _build_workspace_insight_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cards = [
        {"label": item.get("label"), "value": item.get("value"), "unit": item.get("unit")}
        for item in payload.get("key_numbers", [])[:4]
    ]
    if payload.get("query_type") == "company_scoring":
        scorecard = payload.get("scorecard", {})
        cards.extend([
            {"label": "风险标签", "value": len(scorecard.get("risk_labels", [])), "unit": "个"},
            {"label": "建议动作", "value": len(payload.get("action_cards", [])), "unit": "项"},
        ])
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
            "step": 1, "agent_key": "router", "agent_label": "Router", "agent": "Router",
            "status": "completed", "title": "识别任务并锁定公司",
            "summary": f"已将问题归类为 {query_type}，目标问题是：{query}",
            "source": "问题文本 + 公司池 + 报期索引", "tool": "intent_router", "handoff": "data",
            "route": _build_agent_route("orchestrator", payload),
            "metrics": [
                {"label": "任务类型", "value": query_type or "unknown"},
                {"label": "目标公司", "value": payload.get("company_name", "未显式指定")},
                {"label": "目标报期", "value": payload.get("report_period", "自动选择")},
            ],
        },
        {
            "step": 2, "agent_key": "data", "agent_label": "Data Agent", "agent": "Data Agent",
            "status": "completed", "title": "抽取经营与风险信号",
            "summary": (
                f"调用了 {len(tools_called)} 个工具: {', '.join(tools_called) or '无'}。"
                f" 识别到 {risk_count} 个风险，{formula_count} 条公式链。"
                if query_type == "company_scoring"
                else f"调用了 {len(tools_called)} 个工具，提取 {len(payload.get('key_numbers', []))} 个关键结果。"
            ),
            "source": _resolve_agent_signal_source(query_type),
            "tool": _resolve_agent_signal_tool(query_type), "handoff": "risk",
            "route": _build_agent_route("signal_analyst", payload),
            "metrics": _build_signal_agent_metrics(payload, risk_count, formula_count, claim_count),
        },
        {
            "step": 3, "agent_key": "risk", "agent_label": "Risk Agent", "agent": "Risk Agent",
            "status": "completed", "title": "回放来源与可核查证据",
            "summary": f"当前返回 {evidence_count} 条证据引用，优先暴露页码和来源片段。",
            "source": "官方财报页级解析 + 研报详情页 + 公式输入字段", "tool": "evidence_auditor",
            "handoff": "strategy", "route": _build_agent_route("evidence_auditor", payload),
            "metrics": [
                {"label": "证据条数", "value": evidence_count},
                {"label": "证据分组", "value": len(payload.get("evidence_groups", []))},
                {"label": "公式回放", "value": formula_count},
            ],
        },
        {
            "step": 4, "agent_key": "strategy", "agent_label": "Strategy Agent",
            "agent": "Strategy Agent", "status": "completed", "title": "按角色给出下一步",
            "summary": (
                f"已生成 {action_count} 条角色相关动作。" if action_count
                else f"已切换到 {ROLE_PROFILES[role_key]['label']} 视角的后续问题建议。"
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
        return {"label": "进入企业体检", "path": "/score",
                "query": {"company": company_name, "period": report_period}}
    if agent_name == "signal_analyst" and query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk", "query": {}}
    if agent_name == "evidence_auditor":
        evidence_groups = payload.get("evidence_groups", [])
        first_group = evidence_groups[0] if evidence_groups else None
        first_item = first_group["items"][0] if first_group and first_group.get("items") else None
        if first_item:
            return {
                "label": "打开证据", "path": f"/evidence/{first_item['chunk_id']}",
                "query": {"context": first_group.get("title", "证据"),
                           "terms": ",".join(first_group.get("anchor_terms", []))},
            }
        return {"label": "查看证据页", "path": "/admin", "query": {}}
    if agent_name == "action_planner" and query_type == "claim_verification" and company_name:
        return {"label": "进入研报核验", "path": "/verify", "query": {"company": company_name}}
    if query_type == "risk_scan":
        return {"label": "进入行业风险", "path": "/risk", "query": {}}
    return {"label": "返回工作台", "path": "/workspace", "query": {}}


def _build_control_plane_sources(payload: dict[str, Any]) -> list[str]:
    mapping = {
        "company_scoring": ["真实财报指标", "规则引擎", "页级证据", "公式回放"],
        "claim_verification": ["真实财报指标", "东方财富研报详情页", "观点核验规则"],
        "peer_benchmark": ["真实财报指标", "同子行业样本池", "横向评分结果"],
        "risk_scan": ["全公司评分快照", "主周期预警板", "行业研报观察"],
    }
    return mapping.get(payload.get("query_type", ""), ["真实财报指标", "页级证据", "指标直取"])


def _resolve_agent_signal_source(query_type: str | None) -> str:
    mapping = {
        "company_scoring": "真实财报指标 + 风险规则 + 历史报期对比",
        "claim_verification": "真实财报指标 + 研报观点抽取",
        "peer_benchmark": "同子行业评分样本 + 分位结果",
        "risk_scan": "主周期公司池 + 历史报期预警板",
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
