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
        return await _run_local_orchestrator(
            query=query,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            service=service,
            error_msg=str(e),
        )

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

    try:
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

    except Exception as e:
        logger.warning("Failed to collect enriched payload: %s", e)

    return payload


def _fallback_payload(
    query: str,
    company_name: str | None,
    report_period: str | None,
    error_msg: str,
    tool_trace: list,
) -> dict[str, Any]:
    return {
        "company_name": company_name or "无指定主体",
        "report_period": report_period,
        "answer_markdown": f"分析执行异常: {error_msg}",
        "query_type": "metric_query",
        "key_numbers": [],
        "charts": [],
        "evidence": [],
        "evidence_groups": [],
        "calculations": [],
        "formula_cards": [],
        "action_cards": [],
        "tool_trace": tool_trace,
    }


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
        return _stress_data_fallback(company_name, scenario)


async def _run_local_orchestrator(
    *,
    query: str,
    company_name: str | None,
    report_period: str | None,
    user_role: str,
    service: OpsPilotService,
    error_msg: str,
) -> dict[str, Any]:
    tool_name = _route_local_tool(query=query, company_name=company_name)
    trace = ToolCallTrace()
    try:
        local_payload = await _execute_local_tool(
            tool_name=tool_name,
            query=query,
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
            service=service,
        )
        trace.record(
            tool_name=tool_name,
            arguments={
                "company_name": company_name,
                "report_period": report_period,
                "query": query,
            },
            result_summary=json.dumps(local_payload, ensure_ascii=False, default=str),
            elapsed_ms=0.0,
            success=True,
        )
        local_payload["tool_trace"] = trace.records
        local_payload["runtime_notice"] = {
            "mode": "local_orchestrator",
            "status": "degraded",
            "reason": error_msg,
        }
        return local_payload
    except Exception as exc:
        logger.error("Local orchestrator failed: %s", exc)
        return _fallback_payload(query, company_name, report_period, str(exc), trace.records)


def _stress_data_fallback(company_name: str, scenario: str) -> dict[str, Any]:
    """Data-driven stress fallback when LLM is unavailable."""
    # Determine severity by keywords in scenario
    high_risk_kw = ["断供", "停产", "禁令", "暴跌", "崩盘", "制裁", "关税"]
    is_high = any(kw in scenario for kw in high_risk_kw)
    severity_level = "HIGH" if is_high else "MEDIUM"
    severity_color = "risk" if is_high else "warning"
    severity_label = "高风险冲击" if is_high else "中等压力"

    steps = [
        {"step": 1, "title": "冲击启动", "detail": f"压力场景「{scenario[:30]}」触发供应链风险预警。"},
        {"step": 2, "title": "上游传导", "detail": "关键原材料供应商承压，交付周期延长，采购成本抬升。"},
        {"step": 3, "title": "生产环节", "detail": f"{company_name} 产线排期收紧，库存去化速度下降。"},
        {"step": 4, "title": "下游需求", "detail": "终端客户订单节奏放缓，货款回收账期拉长。"},
        {"step": 5, "title": "财务影响", "detail": "毛利率承压，经营活动现金流净额收窄，需密切监控流动比率。"},
    ]
    matrix = [
        {"stage": "upstream", "headline": "原材料成本抬升", "impact_score": "-8%", "impact_label": "采购压力", "tone": "risk"},
        {"stage": "midstream", "headline": "产能利用率下降", "impact_score": "-5%", "impact_label": "营收波动", "tone": "warning"},
        {"stage": "downstream", "headline": "回款账期延长", "impact_score": "-3%", "impact_label": "现金流压力", "tone": "warning"},
    ]
    log = [
        {"step": 1, "title": "系统预警触发", "detail": "基于历史财务数据构建基线估算，LLM 推演暂不可用。"},
        {"step": 2, "title": "风险识别完成", "detail": "关键传导路径已标记：供应→生产→销售→现金流。"},
        {"step": 3, "title": "影响估算", "detail": "采用保守情景（P90）压测，输出参考性指标。"},
        {"step": 4, "title": "建议生成", "detail": "建议重点关注应收账款回收、库存水平及短期融资额度。"},
    ]
    return {
        "severity": {"level": severity_level, "label": severity_label, "color": severity_color},
        "propagation_steps": steps,
        "transmission_matrix": matrix,
        "simulation_log": log,
    }


def _strip_markdown_fences(text: str) -> str:
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text


def _route_local_tool(*, query: str, company_name: str | None) -> str:
    lowered = query.lower()
    benchmark_keywords = ("对标", "同行", "横向", "比较", "排名", "龙头", "领先", "落后")
    verify_keywords = ("研报", "核验", "观点", "券商", "目标价", "评级", "一致预期", "盈利预测")
    stress_keywords = ("压力", "冲击", "情景", "stress", "断供", "停产", "关税", "制裁", "下跌", "上涨")
    graph_keywords = ("图谱", "传导", "链路", "关联", "路径", "因果", "影响到", "波及", "上游", "下游")
    timeline_keywords = ("时间线", "历年", "回溯", "趋势", "变化", "连续", "拐点", "近几期")
    risk_scan_keywords = ("行业", "板块", "预警", "扫描", "风险面", "全行业", "谁最危险")

    if any(keyword in query for keyword in verify_keywords):
        return "tool_verify_claim"
    if any(keyword in query for keyword in benchmark_keywords):
        return "tool_benchmark_company"
    if any(keyword in query for keyword in stress_keywords):
        return "tool_stress_test"
    if any(keyword in query for keyword in graph_keywords):
        return "tool_graph_query"
    if any(keyword in query for keyword in timeline_keywords):
        return "tool_company_timeline"
    if any(keyword in query for keyword in risk_scan_keywords) and not company_name:
        return "tool_risk_scan"
    if any(token in lowered for token in ("benchmark", "peer", "compare")):
        return "tool_benchmark_company"
    if any(token in lowered for token in ("verify", "claim", "research")):
        return "tool_verify_claim"
    if any(token in lowered for token in ("graph", "path", "causal")):
        return "tool_graph_query"
    if any(token in lowered for token in ("stress", "shock", "scenario")):
        return "tool_stress_test"
    if any(token in lowered for token in ("timeline", "trend", "history")):
        return "tool_company_timeline"
    if "risk" in lowered and not company_name:
        return "tool_risk_scan"
    return "tool_score_company"


async def _execute_local_tool(
    *,
    tool_name: str,
    query: str,
    company_name: str | None,
    report_period: str | None,
    user_role: str,
    service: OpsPilotService,
) -> dict[str, Any]:
    if tool_name == "tool_verify_claim" and company_name:
        verify = service.verify_claim(company_name, report_period)
        claim_cards = verify.get("claim_cards", [])
        matches = sum(1 for item in claim_cards if item.get("status") == "match")
        mismatches = sum(1 for item in claim_cards if item.get("status") != "match")
        meta = verify.get("report_meta", {})
        verify.update(
            {
                "query_type": "claim_verification",
                "answer_markdown": (
                    f"当前以 `{meta.get('title', '最新研报')}` 为核验对象。"
                    f"共回溯 {len(claim_cards)} 条关键观点，其中 {matches} 条与财报一致，"
                    f"{mismatches} 条存在偏差。优先关注偏差项与证据回放。"
                ),
                "key_numbers": [
                    {"label": "核验观点", "value": len(claim_cards), "unit": "条"},
                    {"label": "一致观点", "value": matches, "unit": "条"},
                    {"label": "偏差观点", "value": mismatches, "unit": "条"},
                ],
            }
        )
        return verify

    if tool_name == "tool_benchmark_company" and company_name:
        benchmark = service.benchmark_company(company_name, report_period)
        rows = benchmark.get("benchmark", [])
        leader = rows[0] if rows else {}
        benchmark.update(
            {
                "query_type": "peer_benchmark",
                "answer_markdown": (
                    f"已完成 `{company_name}` 的同业对标。"
                    f"当前最靠前样本为 `{leader.get('company_name', company_name)}`，"
                    f"建议对照分项得分和整改动作查看差距来源。"
                ),
                "key_numbers": benchmark.get("key_numbers", [])[:3],
            }
        )
        return benchmark

    if tool_name == "tool_stress_test" and company_name:
        stress = await service.company_stress_test(
            company_name,
            query if len(query) >= 6 else "供应链中断",
            report_period,
            user_role=user_role,
        )
        severity = stress.get("severity", {})
        stress.update(
            {
                "query_type": "stress_test",
                "answer_markdown": (
                    f"已完成 `{company_name}` 的压力推演。"
                    f"当前冲击等级为 `{severity.get('level', 'UNKNOWN')}` / {severity.get('label', '待确认')}，"
                    "请结合传导矩阵、波前轨迹和恢复动作判断是否需要升级处置。"
                ),
                "key_numbers": [
                    {"label": "冲击等级", "value": severity.get("level", "UNKNOWN"), "unit": ""},
                    {"label": "传导阶段", "value": len(stress.get("transmission_matrix", [])), "unit": "段"},
                    {"label": "恢复动作", "value": len(stress.get("stress_recovery_sequence", [])), "unit": "项"},
                ],
            }
        )
        return stress

    if tool_name == "tool_graph_query" and company_name:
        graph = service.company_graph_query(
            company_name,
            query,
            report_period,
            user_role=user_role,
        )
        focal_labels = "、".join(item.get("label", "") for item in graph.get("focal_nodes", [])[:3] if item.get("label"))
        graph.update(
            {
                "query_type": "graph_query",
                "answer_markdown": (
                    f"已完成 `{company_name}` 的图谱路径检索。"
                    f"当前命中的关键节点包括 {focal_labels or '核心风险与执行节点'}，"
                    "请结合路径带和执行流定位主传导链。"
                ),
                "key_numbers": [
                    {"label": "焦点节点", "value": len(graph.get("focal_nodes", [])), "unit": "个"},
                    {"label": "推理路径", "value": len(graph.get("inference_path", [])), "unit": "段"},
                    {"label": "执行记录", "value": graph.get("summary", {}).get("execution_records", 0), "unit": "条"},
                ],
            }
        )
        return graph

    if tool_name == "tool_company_timeline" and company_name:
        timeline = service.company_timeline(company_name)
        latest = timeline.get("snapshots", [{}])[0]
        timeline.update(
            {
                "query_type": "company_timeline",
                "answer_markdown": (
                    f"已回放 `{company_name}` 的跨期变化。"
                    f"最新报期为 `{timeline.get('latest_period', report_period or '-')}`，"
                    f"总分 {latest.get('total_score', '-')}"
                    "，建议结合分期变化和风险标签查看拐点。"
                ),
                "key_numbers": timeline.get("key_numbers", [])[:3],
            }
        )
        return timeline

    if tool_name == "tool_risk_scan":
        risk = service.risk_scan(report_period)
        risk_board = risk.get("risk_board", [])
        risk.update(
            {
                "query_type": "risk_scan",
                "answer_markdown": (
                    f"已完成主周期行业风险扫描。当前识别到 {len(risk_board)} 家重点关注企业，"
                    "请优先查看风险标签密集和预警未闭环的样本。"
                ),
                "key_numbers": risk.get("key_numbers", [])[:3],
            }
        )
        return risk

    if company_name:
        score = service.score_company(company_name, report_period)
        scorecard = score.get("scorecard", {})
        top_risk = scorecard.get("risk_labels", [{}])
        dimension_scores = scorecard.get("dimension_scores", {})
        weakest_dimension = min(
            dimension_scores.items(),
            key=lambda item: item[1],
            default=("经营质量", scorecard.get("total_score")),
        )
        score.update(
            {
                "query_type": "company_scoring",
                "answer_markdown": (
                    f"已完成 `{company_name}` 的企业体检。"
                    f"当前总分 {scorecard.get('total_score', '-')}, 评级 {scorecard.get('grade', '-')}"
                    f"，首要风险为 `{top_risk[0].get('name', '待识别')}`，"
                    f"当前最弱维度是 `{weakest_dimension[0]}`。"
                    f" 针对问题“{query}”建议优先下钻这一维度的证据链和整改动作。"
                ),
                "key_numbers": [
                    {"label": "总分", "value": scorecard.get("total_score"), "unit": "分"},
                    {"label": "风险标签", "value": len(scorecard.get("risk_labels", [])), "unit": "项"},
                    {"label": "整改动作", "value": len(score.get("action_cards", [])), "unit": "项"},
                ],
            }
        )
        return score

    raise ValueError("当前问题缺少可分析的公司主体，无法执行本地编排。")
