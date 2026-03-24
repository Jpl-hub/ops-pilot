"""
OpsPilot-X Agentic Engine
=========================

Orchestrator + Domain Agents w/ real tool calling against OpsPilotService.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from opspilot.core.llm import generate_completion, ToolCallTrace

if TYPE_CHECKING:
    from opspilot.application.services import OpsPilotService

logger = logging.getLogger(__name__)


class AgentExecutionError(RuntimeError):
    """Raised when a real LLM-backed agent chain cannot complete."""

# ---------------------------------------------------------------------------
#  Role → Tool whitelist
# ---------------------------------------------------------------------------

ROLE_TOOL_WHITELIST: dict[str, set[str]] = {
    "investor": {
        "tool_score_company",
        "tool_verify_claim",
        "tool_benchmark_company",
        "tool_risk_scan",
        "tool_company_timeline",
        "tool_graph_query",
    },
    "management": {
        "tool_score_company",
        "tool_risk_scan",
        "tool_stress_test",
        "tool_graph_query",
        "tool_company_timeline",
        "tool_verify_claim",
        "tool_benchmark_company",
    },
    "regulator": {
        "tool_risk_scan",
        "tool_verify_claim",
        "tool_company_timeline",
        "tool_benchmark_company",
        "tool_graph_query",
    },
}

# ---------------------------------------------------------------------------
#  Tool wrapper functions (thin adapters over Service methods)
#  Each returns a trimmed dict suitable for LLM context (< 2k tokens typical)
# ---------------------------------------------------------------------------


def _make_tool_wrappers(
    service: OpsPilotService,
    company_name: str | None,
    report_period: str | None,
    user_role: str,
) -> dict[str, Any]:
    """Build a registry of callable tool functions bound to a service instance."""

    def tool_score_company(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        if not name:
            return {"error": "company_name is required"}
        result = service.score_company(name, kwargs.get("report_period") or report_period)
        sc = result.get("scorecard", {})
        return {
            "company_name": result.get("company_name"),
            "total_score": sc.get("total_score"),
            "grade": sc.get("grade"),
            "subindustry_percentile": sc.get("subindustry_percentile"),
            "risk_labels": [r["name"] for r in sc.get("risk_labels", [])[:5]],
            "opportunity_labels": [o["name"] for o in sc.get("opportunity_labels", [])[:3]],
            "action_cards": [
                {"priority": a["priority"], "title": a["title"], "action": a["action"]}
                for a in result.get("action_cards", [])[:3]
            ],
            "dimension_scores": sc.get("dimension_scores"),
        }

    def tool_risk_scan(**kwargs: Any) -> dict:
        period = kwargs.get("report_period") or report_period
        result = service.risk_scan(period)
        board = result.get("risk_board", [])[:5]
        alerts = result.get("alert_board", [])[:5]
        return {
            "risk_board": [
                {"company_name": r["company_name"], "risk_count": r.get("risk_count"), "grade": r.get("grade")}
                for r in board
            ],
            "alert_board": [
                {"company_name": a["company_name"], "summary": a.get("summary")}
                for a in alerts
            ],
            "total_companies": result.get("total_companies"),
        }

    def tool_verify_claim(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        if not name:
            return {"error": "company_name is required"}
        result = service.verify_claim(name, kwargs.get("report_period") or report_period)
        meta = result.get("report_meta", {})
        claims = result.get("claim_cards", [])
        return {
            "report_title": meta.get("title"),
            "institution": meta.get("institution"),
            "total_claims": len(claims),
            "matches": sum(1 for c in claims if c.get("status") == "match"),
            "mismatches": sum(1 for c in claims if c.get("status") == "mismatch"),
            "top_mismatches": [
                {"claim": c["claim_text"], "actual": c.get("actual_text", "")}
                for c in claims if c.get("status") == "mismatch"
            ][:3],
            "forecast_cards": result.get("forecast_cards", [])[:3],
        }

    def tool_benchmark_company(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        if not name:
            return {"error": "company_name is required"}
        result = service.benchmark_company(name, kwargs.get("report_period") or report_period)
        rows = result.get("benchmark", [])[:5]
        return {
            "answer": result.get("answer_markdown"),
            "top_companies": rows,
        }

    async def tool_stress_test(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        scenario = kwargs.get("scenario", "供应链中断")
        if not name:
            return {"error": "company_name is required"}
        result = await service.company_stress_test(
            name, scenario, kwargs.get("report_period") or report_period, user_role=user_role,
        )
        return {
            "severity": result.get("severity"),
            "propagation_steps": result.get("propagation_steps", [])[:3],
            "transmission_matrix": result.get("transmission_matrix", [])[:3],
        }

    def tool_graph_query(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        intent = kwargs.get("intent", "风险传导分析")
        if not name:
            return {"error": "company_name is required"}
        result = service.company_graph_query(
            name, intent, kwargs.get("report_period") or report_period, user_role=user_role,
        )
        return {
            "focal_nodes": result.get("focal_nodes", [])[:5],
            "inference_summary": " -> ".join(
                item.get("title", "")
                for item in result.get("inference_path", [])[:4]
                if item.get("title")
            ),
        }

    def tool_company_timeline(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        if not name:
            return {"error": "company_name is required"}
        result = service.company_timeline(name)
        return {
            "latest_period": result.get("latest_period"),
            "snapshots": result.get("snapshots", [])[:4],
        }

    return {
        "tool_score_company": tool_score_company,
        "tool_risk_scan": tool_risk_scan,
        "tool_verify_claim": tool_verify_claim,
        "tool_benchmark_company": tool_benchmark_company,
        "tool_stress_test": tool_stress_test,
        "tool_graph_query": tool_graph_query,
        "tool_company_timeline": tool_company_timeline,
    }


# ---------------------------------------------------------------------------
#  OpenAI Function-Calling tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "tool_score_company",
            "description": "评分并分析一家企业的经营状况，返回总分、风险标签、行动建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                    "report_period": {"type": "string", "description": "报期如 2024Q3"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_risk_scan",
            "description": "行业级批量风险扫描，返回高风险公司列表和预警摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_period": {"type": "string", "description": "报期"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_verify_claim",
            "description": "用官方财报核验研报观点，找出匹配/偏差的断言。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                    "report_period": {"type": "string", "description": "报期"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_benchmark_company",
            "description": "同业对标，比较目标公司在样本集中的排名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                    "report_period": {"type": "string", "description": "报期"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_stress_test",
            "description": "压力测试模拟极端场景对企业财务的传导影响。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                    "scenario": {"type": "string", "description": "场景描述如 '供应链中断'"},
                    "report_period": {"type": "string", "description": "报期"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_graph_query",
            "description": "企业关联图谱分析，提取风险传导路径和关键节点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                    "intent": {"type": "string", "description": "检索意图"},
                    "report_period": {"type": "string", "description": "报期"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_company_timeline",
            "description": "时间线回溯，查看一家企业跨报期的得分和风险变化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "公司名称"},
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
#  run_orchestrator — 半开放式 Agent 主脑
# ---------------------------------------------------------------------------

async def run_orchestrator(
    query: str,
    company_name: str | None,
    report_period: str | None,
    user_role: str,
    service: OpsPilotService,
) -> dict[str, Any]:
    """
    Semi-open orchestrator: deterministic pre-processing + constrained LLM tool selection.

    Returns a canonical payload dict suitable for _build_workspace_payload().
    """
    # -- 1) Build tool registry (filtered by role) --
    all_wrappers = _make_tool_wrappers(service, company_name, report_period, user_role)
    role_key = user_role if user_role in ROLE_TOOL_WHITELIST else "investor"
    allowed = ROLE_TOOL_WHITELIST[role_key]
    tool_registry = {k: v for k, v in all_wrappers.items() if k in allowed}

    # Filter schemas to only allowed tools
    available_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed]

    # -- 2) System prompt --
    system_prompt = (
        "你是 OpsPilot-X 企业决策智能体，用户提出经营分析相关问题，"
        "你需要选择合适的工具查询真实数据，再基于工具返回的数据给出专业分析。\n"
        "规则:\n"
        "1. 必须调用至少一个工具获取数据，不要凭空编造\n"
        "2. 始终引用工具返回的具体数值（分数、百分比、公司名等）\n"
        "3. 最终回复用 JSON 格式:\n"
        '{"answer_markdown": "...", "query_type": "...", "key_numbers": [...], "tool_calls_made": [...]}\n'
        "4. query_type 取值: company_scoring | peer_benchmark | risk_scan | claim_verification | "
        "stress_test | graph_query | metric_query\n"
        "5. key_numbers 每项: {\"label\": \"...\", \"value\": ..., \"unit\": \"...\"}"
    )

    prompt = f"用户问题: {query}\n"
    if company_name:
        prompt += f"目标公司: {company_name}\n"
    if report_period:
        prompt += f"目标报期: {report_period}\n"
    prompt += f"用户角色: {user_role}\n\n请使用工具获取数据后回答。"

    # -- 3) Execute LLM + Tool Calling --
    try:
        response_text, trace = await generate_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            model="gpt-4o-mini",
            temperature=0.3,
            tools=available_schemas,
            tool_registry=tool_registry,
            max_tool_rounds=3,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.error("Orchestrator LLM call failed: %s", e)
        raise AgentExecutionError(
            f"协同分析依赖的大模型调用失败：{e}"
        ) from e

    # -- 4) Parse response --
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        parsed = {}

    answer_markdown = parsed.get("answer_markdown", response_text)
    query_type = parsed.get("query_type", "metric_query")
    key_numbers = parsed.get("key_numbers", [])

    # -- 5) Build enriched payload from tool trace --
    # Gather full service results for downstream _build_workspace_payload
    full_payload = _collect_enriched_payload(
        service=service,
        company_name=company_name,
        report_period=report_period,
        query_type=query_type,
        trace=trace,
    )

    full_payload.update({
        "company_name": company_name or "无指定主体",
        "report_period": report_period,
        "answer_markdown": answer_markdown,
        "query_type": query_type,
        "key_numbers": key_numbers,
        "tool_trace": trace.records,
    })

    return full_payload


def _collect_enriched_payload(
    *,
    service: OpsPilotService,
    company_name: str | None,
    report_period: str | None,
    query_type: str,
    trace: ToolCallTrace,
) -> dict[str, Any]:
    """
    Based on which tools were called, fetch the FULL service results
    (not the trimmed tool returns) so that _build_workspace_payload
    downstream has all the fields it needs (scorecard, charts, evidence, etc.).
    """
    payload: dict[str, Any] = {
        "charts": [],
        "evidence": [],
        "evidence_groups": [],
        "calculations": [],
        "formula_cards": [],
        "action_cards": [],
    }

    tool_names_called = {r["tool_name"] for r in trace.records if r["success"]}

    if "tool_score_company" in tool_names_called and company_name:
        score = service.score_company(company_name, report_period)
        payload["scorecard"] = score.get("scorecard")
        payload["charts"] = score.get("charts", [])
        payload["evidence"] = score.get("evidence", [])
        payload["evidence_groups"] = score.get("evidence_groups", [])
        payload["formula_cards"] = score.get("formula_cards", [])
        payload["action_cards"] = score.get("action_cards", [])
        payload["calculations"] = score.get("calculations", [])
        payload["subindustry"] = score.get("subindustry")

    if "tool_verify_claim" in tool_names_called and company_name:
        verify = service.verify_claim(company_name, report_period)
        payload["report_meta"] = verify.get("report_meta")
        payload["claim_cards"] = verify.get("claim_cards", [])
        payload["forecast_cards"] = verify.get("forecast_cards", [])

    if "tool_benchmark_company" in tool_names_called and company_name:
        bench = service.benchmark_company(company_name, report_period)
        payload["benchmark"] = bench.get("benchmark", [])
        if not payload["charts"]:
            payload["charts"] = bench.get("charts", [])

    if "tool_risk_scan" in tool_names_called:
        risk = service.risk_scan(report_period)
        payload["risk_board"] = risk.get("risk_board", [])
        payload["alert_board"] = risk.get("alert_board", [])

    return payload


# ---------------------------------------------------------------------------
#  Legacy agents (kept for backward compat with stress_test direct calls)
# ---------------------------------------------------------------------------

async def run_stress_agent(company_name: str, scenario: str, report_period: str | None) -> dict[str, Any]:
    """Risk Agent for Stress Testing — called by company_stress_test service."""
    system_prompt = (
        "You are a Systemic Risk & Stress Test Agent modeling supply chain impacts.\n"
        "Return JSON:\n"
        '{"severity": {"level":"CRITICAL|HIGH|MEDIUM|LOW","label":"Short","color":"risk|warning|safe"},\n'
        ' "propagation_steps":[{"step":1,"title":"...","detail":"..."}],\n'
        ' "transmission_matrix":[{"stage":"upstream|midstream|downstream","headline":"...","impact_score":"-X%","impact_label":"..."}],\n'
        ' "simulation_log":[{"step":1,"title":"...","detail":"..."}]}'
    )
    prompt = f"Target Company: {company_name}\nStress Scenario: {scenario}\nPeriod: {report_period}\n"
    try:
        response_text, _ = await generate_completion(
            prompt=prompt, system_prompt=system_prompt, model="gpt-4o-mini", temperature=0.6
        )
        response_text = _strip_markdown_fences(response_text)
        return json.loads(response_text.strip())
    except Exception as e:
        logger.error("Stress Agent failed: %s", e)
        raise AgentExecutionError(
            f"压力测试依赖的大模型调用失败：{e}"
        ) from e


def _strip_markdown_fences(text: str) -> str:
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text
