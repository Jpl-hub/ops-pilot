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
from opspilot.domain.catalog import DIMENSION_WEIGHTS, METRICS
from opspilot.domain.routing import detect_query_type
from opspilot.domain.rules import OPPORTUNITY_DEFINITIONS, RISK_DEFINITIONS

if TYPE_CHECKING:
    from opspilot.application.services import OpsPilotService

logger = logging.getLogger(__name__)


class AgentExecutionError(RuntimeError):
    """Raised when a real LLM-backed agent chain cannot complete."""


ROLE_ANALYSIS_CONTRACT: dict[str, dict[str, str]] = {
    "investor": {
        "goal": "识别收益质量、研报偏差、行业风险与价值机会",
        "focus": "优先回答这家公司值不值得继续跟踪，最影响估值的风险在哪里。",
    },
    "management": {
        "goal": "识别经营瓶颈、现金压力、任务优先级与整改动作",
        "focus": "优先回答哪里出了问题、为什么会这样、下一步该先做什么。",
    },
    "regulator": {
        "goal": "识别异常信号、跨源共振风险、持续跟踪与处置入口",
        "focus": "优先回答哪家公司值得重点巡检、证据在哪里、处置链是否闭环。",
    },
}


def _build_metric_semantic_layer() -> str:
    dimension_lines = [
        f"- {dimension}：权重 {weight:g}"
        for dimension, weight in DIMENSION_WEIGHTS.items()
    ]
    metric_lines = [
        f"- {metric.code} {metric.name} | 维度={metric.dimension} | 方向={'越高越好' if metric.direction == 'higher' else '越低越好'}"
        for metric in METRICS
    ]
    risk_lines = [f"- {code} {label}" for code, label in RISK_DEFINITIONS.items()]
    opportunity_lines = [f"- {code} {label}" for code, label in OPPORTUNITY_DEFINITIONS.items()]
    return (
        "【评分语义层】\n"
        "五维评价体系：\n"
        f"{chr(10).join(dimension_lines)}\n"
        "核心指标定义：\n"
        f"{chr(10).join(metric_lines)}\n"
        "风险标签定义：\n"
        f"{chr(10).join(risk_lines)}\n"
        "机会标签定义：\n"
        f"{chr(10).join(opportunity_lines)}"
    )


def _build_company_business_context(
    service: OpsPilotService,
    company_name: str | None,
    report_period: str | None,
) -> str:
    if not company_name:
        return "【当前主体上下文】\n未显式指定公司，优先根据问题识别主体，再调用工具确认。"
    company = service.repository.get_company(company_name, report_period)
    if company is None:
        company = service.repository.get_company(company_name, None)
    if company is None:
        return f"【当前主体上下文】\n公司={company_name}，暂未解析到结构化财报主体，必须先通过工具确认。"

    metrics = company.get("metrics", {})
    metric_lines: list[str] = []
    for code in ("G1", "G2", "P1", "P4", "C1", "C3", "S4"):
        value = metrics.get(code)
        if value is None:
            continue
        metric = next((item for item in METRICS if item.code == code), None)
        metric_name = metric.name if metric is not None else code
        metric_lines.append(f"- {code} {metric_name}={value}")
    return (
        "【当前主体上下文】\n"
        f"- 公司：{company.get('company_name')}\n"
        f"- 报期：{company.get('report_period')}\n"
        f"- 子行业：{company.get('subindustry')}\n"
        f"- 当前关键指标：\n{chr(10).join(metric_lines) if metric_lines else '- 当前无关键指标快照'}"
    )


def _build_agent_prompt_context(
    *,
    service: OpsPilotService,
    query: str,
    company_name: str | None,
    report_period: str | None,
    user_role: str,
) -> tuple[str, str]:
    role_key = user_role if user_role in ROLE_ANALYSIS_CONTRACT else "investor"
    query_type_hint = detect_query_type(query)
    role_context = ROLE_ANALYSIS_CONTRACT[role_key]
    system_prompt = (
        "你是 OpsPilot-X 企业运营分析智能体，不是闲聊助手，也不是泛化写作助手。\n"
        "你的工作目标是基于新能源企业正式数据，为特定角色输出可核验、可追责、可执行的结论。\n"
        "回答必须围绕“问题是什么、原因是什么、下一步怎么做”组织，不准只给抽象判断。\n"
        "必须尊重业务语义层，不允许自造指标定义、口径或风险标签。\n"
        "如果用户问题需要图谱、压力测试、时间线、研报核验等能力，必须调用相应工具，不要只调用评分工具敷衍。\n"
        "最终回复用 JSON 格式:\n"
        '{"answer_markdown": "...", "query_type": "...", "key_numbers": [...], "tool_calls_made": [...]}\n'
        "query_type 取值: company_scoring | peer_benchmark | risk_scan | claim_verification | stress_test | graph_query | metric_query | company_timeline\n"
        "key_numbers 每项: {\"label\": \"...\", \"value\": ..., \"unit\": \"...\"}\n"
        "answer_markdown 要体现业务语言、证据意识和动作建议，禁止空泛表态。\n\n"
        f"{_build_metric_semantic_layer()}"
    )
    user_prompt = (
        f"用户角色: {user_role}\n"
        f"角色任务目标: {role_context['goal']}\n"
        f"角色输出偏好: {role_context['focus']}\n"
        f"任务类型初判: {query_type_hint}\n"
        f"{_build_company_business_context(service, company_name, report_period)}\n"
        f"用户问题: {query}\n"
    )
    if company_name:
        user_prompt += f"目标公司: {company_name}\n"
    if report_period:
        user_prompt += f"目标报期: {report_period}\n"
    user_prompt += "请先用真实工具拿数据，再基于语义层和角色任务给出结论。"
    return system_prompt, user_prompt

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
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Build a registry of callable tool functions bound to a service instance."""
    tool_results: dict[str, list[dict[str, Any]]] = {}

    def capture_tool_result(
        tool_name: str,
        *,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        tool_results.setdefault(tool_name, []).append(
            {"arguments": dict(arguments), "result": result}
        )

    def tool_score_company(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        period = kwargs.get("report_period") or report_period
        if not name:
            return {"error": "company_name is required"}
        result = service.score_company(name, period)
        capture_tool_result(
            "tool_score_company",
            arguments={"company_name": name, "report_period": period},
            result=result,
        )
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
        capture_tool_result(
            "tool_risk_scan",
            arguments={"report_period": period},
            result=result,
        )
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
        period = kwargs.get("report_period") or report_period
        if not name:
            return {"error": "company_name is required"}
        result = service.verify_claim(name, period)
        capture_tool_result(
            "tool_verify_claim",
            arguments={"company_name": name, "report_period": period},
            result=result,
        )
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
        period = kwargs.get("report_period") or report_period
        if not name:
            return {"error": "company_name is required"}
        result = service.benchmark_company(name, period)
        capture_tool_result(
            "tool_benchmark_company",
            arguments={"company_name": name, "report_period": period},
            result=result,
        )
        rows = result.get("benchmark", [])[:5]
        return {
            "answer": result.get("answer_markdown"),
            "top_companies": rows,
        }

    async def tool_stress_test(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        scenario = kwargs.get("scenario", "供应链中断")
        period = kwargs.get("report_period") or report_period
        if not name:
            return {"error": "company_name is required"}
        result = await service.company_stress_test(
            name, scenario, period, user_role=user_role,
        )
        capture_tool_result(
            "tool_stress_test",
            arguments={
                "company_name": name,
                "report_period": period,
                "scenario": scenario,
                "user_role": user_role,
            },
            result=result,
        )
        return {
            "severity": result.get("severity"),
            "propagation_steps": result.get("propagation_steps", [])[:3],
            "transmission_matrix": result.get("transmission_matrix", [])[:3],
        }

    def tool_graph_query(**kwargs: Any) -> dict:
        name = kwargs.get("company_name") or company_name
        intent = kwargs.get("intent", "风险传导分析")
        period = kwargs.get("report_period") or report_period
        if not name:
            return {"error": "company_name is required"}
        result = service.company_graph_query(
            name, intent, period, user_role=user_role,
        )
        capture_tool_result(
            "tool_graph_query",
            arguments={
                "company_name": name,
                "report_period": period,
                "intent": intent,
                "user_role": user_role,
            },
            result=result,
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
        capture_tool_result(
            "tool_company_timeline",
            arguments={"company_name": name},
            result=result,
        )
        return {
            "latest_period": result.get("latest_period"),
            "snapshots": result.get("snapshots", [])[:4],
        }

    return (
        {
            "tool_score_company": tool_score_company,
            "tool_risk_scan": tool_risk_scan,
            "tool_verify_claim": tool_verify_claim,
            "tool_benchmark_company": tool_benchmark_company,
            "tool_stress_test": tool_stress_test,
            "tool_graph_query": tool_graph_query,
            "tool_company_timeline": tool_company_timeline,
        },
        tool_results,
    )


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
            "description": "同业对标，比较目标公司在同子行业公司池中的排名。",
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
    all_wrappers, tool_results = _make_tool_wrappers(
        service,
        company_name,
        report_period,
        user_role,
    )
    role_key = user_role if user_role in ROLE_TOOL_WHITELIST else "investor"
    allowed = ROLE_TOOL_WHITELIST[role_key]
    tool_registry = {k: v for k, v in all_wrappers.items() if k in allowed}

    # Filter schemas to only allowed tools
    available_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed]

    # -- 2) System prompt --
    system_prompt, prompt = _build_agent_prompt_context(
        service=service,
        query=query,
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
    )

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
        tool_results=tool_results,
    )

    resolved_company_name = full_payload.get("company_name") or company_name or "无指定主体"
    resolved_report_period = full_payload.get("report_period") or report_period

    full_payload.update({
        "company_name": resolved_company_name,
        "report_period": resolved_report_period,
        "answer_markdown": answer_markdown,
        "query_type": query_type,
        "key_numbers": key_numbers,
        "tool_trace": trace.records,
        "agent_runtime": trace.snapshot(),
    })

    return full_payload


def _collect_enriched_payload(
    *,
    service: OpsPilotService,
    company_name: str | None,
    report_period: str | None,
    query_type: str,
    trace: ToolCallTrace,
    tool_results: dict[str, list[dict[str, Any]]],
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

    def latest_tool_result(tool_name: str) -> dict[str, Any] | None:
        entries = tool_results.get(tool_name) or []
        if not entries:
            return None
        result = entries[-1].get("result")
        return result if isinstance(result, dict) else None

    def attach_base_identity(result: dict[str, Any]) -> None:
        resolved_company_name = result.get("company_name")
        if isinstance(resolved_company_name, str) and resolved_company_name:
            payload["company_name"] = resolved_company_name
        resolved_report_period = result.get("report_period") or result.get("latest_period")
        if isinstance(resolved_report_period, str) and resolved_report_period:
            payload["report_period"] = resolved_report_period

    def merge_charts(charts: list[dict[str, Any]]) -> None:
        if not charts:
            return
        existing = payload.get("charts", [])
        if not existing:
            payload["charts"] = list(charts)
            return
        payload["charts"] = [*existing, *charts]

    if "tool_score_company" in tool_names_called and company_name:
        score = latest_tool_result("tool_score_company")
        if score is None:
            score = service.score_company(company_name, report_period)
        attach_base_identity(score)
        payload["scorecard"] = score.get("scorecard")
        merge_charts(score.get("charts", []))
        payload["evidence"] = score.get("evidence", [])
        payload["evidence_groups"] = score.get("evidence_groups", [])
        payload["formula_cards"] = score.get("formula_cards", [])
        payload["action_cards"] = score.get("action_cards", [])
        payload["calculations"] = score.get("calculations", [])
        payload["subindustry"] = score.get("subindustry")

    if "tool_verify_claim" in tool_names_called and company_name:
        verify = latest_tool_result("tool_verify_claim")
        if verify is None:
            verify = service.verify_claim(company_name, report_period)
        attach_base_identity(verify)
        payload["report_meta"] = verify.get("report_meta")
        payload["claim_cards"] = verify.get("claim_cards", [])
        payload["forecast_cards"] = verify.get("forecast_cards", [])
        payload["available_reports"] = verify.get("available_reports", [])
        payload["verify_command_surface"] = verify.get("verify_command_surface")
        payload["verify_delta_tape"] = verify.get("verify_delta_tape", [])
        payload["research_compare"] = verify.get("research_compare")
        payload["research_timeline"] = verify.get("research_timeline")
        if not payload.get("evidence"):
            payload["evidence"] = verify.get("evidence", [])
        if not payload.get("evidence_groups"):
            payload["evidence_groups"] = verify.get("evidence_groups", [])
        if not payload.get("calculations"):
            payload["calculations"] = verify.get("calculations", [])
        merge_charts(verify.get("charts", []))

    if "tool_benchmark_company" in tool_names_called and company_name:
        bench = latest_tool_result("tool_benchmark_company")
        if bench is None:
            bench = service.benchmark_company(company_name, report_period)
        attach_base_identity(bench)
        payload["benchmark"] = bench.get("benchmark", [])
        merge_charts(bench.get("charts", []))

    if "tool_risk_scan" in tool_names_called:
        risk = latest_tool_result("tool_risk_scan")
        if risk is None:
            risk = service.risk_scan(report_period)
        payload["risk_board"] = risk.get("risk_board", [])
        payload["alert_board"] = risk.get("alert_board", [])

    if "tool_graph_query" in tool_names_called and company_name:
        graph = latest_tool_result("tool_graph_query")
        if graph is not None:
            attach_base_identity(graph)
            payload["intent"] = graph.get("intent")
            payload["summary"] = graph.get("summary", {})
            payload["graph_retrieval"] = graph.get("graph_retrieval", {})
            payload["focal_nodes"] = graph.get("focal_nodes", [])
            payload["inference_path"] = graph.get("inference_path", [])
            payload["phase_track"] = graph.get("phase_track", [])
            payload["signal_stream"] = graph.get("signal_stream", [])
            payload["graph_command_surface"] = graph.get("graph_command_surface")
            payload["graph_live_frames"] = graph.get("graph_live_frames", [])
            payload["graph_signal_tape"] = graph.get("graph_signal_tape", [])
            payload["graph_route_bands"] = graph.get("graph_route_bands", [])
            payload["execution_stream"] = graph.get("execution_stream", [])
            payload["related_routes"] = graph.get("related_routes", [])
            payload["evidence_navigation"] = graph.get("evidence_navigation", {})
            payload["graph"] = graph.get("graph", {})

    if "tool_stress_test" in tool_names_called and company_name:
        stress = latest_tool_result("tool_stress_test")
        if stress is not None:
            attach_base_identity(stress)
            payload["scenario"] = stress.get("scenario")
            payload["severity"] = stress.get("severity", {})
            payload["affected_dimensions"] = stress.get("affected_dimensions", [])
            payload["propagation_steps"] = stress.get("propagation_steps", [])
            payload["transmission_matrix"] = stress.get("transmission_matrix", [])
            payload["simulation_log"] = stress.get("simulation_log", [])
            payload["stress_command_surface"] = stress.get("stress_command_surface")
            payload["stress_wavefront"] = stress.get("stress_wavefront", [])
            payload["stress_impact_tape"] = stress.get("stress_impact_tape", [])
            payload["stress_recovery_sequence"] = stress.get("stress_recovery_sequence", [])
            payload["actions"] = stress.get("actions", [])
            payload["related_routes"] = stress.get("related_routes", payload.get("related_routes", []))
            payload["evidence_navigation"] = stress.get("evidence_navigation", payload.get("evidence_navigation", {}))
            if stress.get("chart"):
                merge_charts([stress["chart"]])

    if "tool_company_timeline" in tool_names_called and company_name:
        timeline = latest_tool_result("tool_company_timeline")
        if timeline is None:
            timeline = service.company_timeline(company_name)
        attach_base_identity(timeline)
        payload["latest_period"] = timeline.get("latest_period")
        payload["snapshots"] = timeline.get("snapshots", [])
        merge_charts(timeline.get("charts", []))
        if not payload.get("key_numbers"):
            payload["key_numbers"] = timeline.get("key_numbers", [])

    return payload


# ---------------------------------------------------------------------------
#  Legacy agents (kept for backward compat with stress_test direct calls)
# ---------------------------------------------------------------------------

async def run_stress_agent(company_name: str, scenario: str, report_period: str | None) -> dict[str, Any]:
    """Risk Agent for Stress Testing — called by company_stress_test service."""
    system_prompt = (
        "你是新能源产业链压力推演智能体，只能输出中文 JSON，不允许输出英文标题、英文说明或英文风险标签。\n"
        "如果出现公司简称或代码，可以保留原样；除此之外，所有 title / detail / headline / impact_label / label 都必须是中文。\n"
        "返回 JSON：\n"
        '{"severity": {"level":"CRITICAL|HIGH|MEDIUM|LOW","label":"中文短语","color":"risk|warning|safe"},\n'
        ' "propagation_steps":[{"step":1,"title":"中文标题","detail":"中文说明"}],\n'
        ' "transmission_matrix":[{"stage":"upstream|midstream|downstream","headline":"中文标题","impact_score":"-X%","impact_label":"中文短语"}],\n'
        ' "simulation_log":[{"step":1,"title":"中文标题","detail":"中文说明"}]}\n'
        "禁止返回 Markdown，禁止解释，禁止附加任何多余文本。"
    )
    prompt = f"Target Company: {company_name}\nStress Scenario: {scenario}\nPeriod: {report_period}\n"
    try:
        response_text, _ = await generate_completion(
            prompt=prompt, system_prompt=system_prompt, model="gpt-4o-mini", temperature=0.2
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
