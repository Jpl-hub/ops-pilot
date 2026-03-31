from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.agents import (
    _build_agent_prompt_context,
    _collect_enriched_payload,
    _make_tool_wrappers,
    run_orchestrator,
)
from opspilot.core.llm import ToolCallTrace
from opspilot.domain.routing import detect_query_type


class AgentServiceStub:
    def __init__(self) -> None:
        self.graph_calls = 0
        self.stress_calls = 0
        self.timeline_calls = 0

    def company_graph_query(
        self,
        company_name: str,
        intent: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict:
        self.graph_calls += 1
        return {
            "company_name": company_name,
            "report_period": "2025Q3",
            "user_role": user_role,
            "intent": intent,
            "summary": {"score": 78, "grade": "B"},
            "graph_retrieval": {"path_count": 2, "query_term_count": 4},
            "focal_nodes": [{"id": "risk-1", "label": "现金流压力", "type": "risk_label"}],
            "inference_path": [{"step": 1, "title": "现金流压力", "detail": "命中风险节点"}],
            "phase_track": [{"phase": "路径传导", "status": "done", "headline": "已完成", "metric": "2 paths"}],
            "signal_stream": [{"label": "焦点节点", "value": "score 9", "tone": "risk"}],
            "graph_command_surface": {"headline": "现金流压力", "metric": "2 paths"},
            "graph_live_frames": [{"frame": 1, "headline": "现金流压力", "detail": "命中风险节点"}],
            "graph_signal_tape": [{"step": 1, "label": "现金流压力", "value": "score 9"}],
            "graph_route_bands": [{"step": 1, "headline": "现金流压力", "detail": "命中风险节点"}],
            "execution_stream": [{"id": "exec-1", "title": "图谱检索", "status": "completed"}],
            "related_routes": [{"label": "查看企业体检", "path": "/score", "query": {"company": company_name}}],
            "evidence_navigation": {"links": [{"label": "查看证据", "path": "/evidence/1"}]},
            "graph": {"node_count": 3, "edge_count": 2, "nodes": [], "edges": []},
        }

    async def company_stress_test(
        self,
        company_name: str,
        scenario: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict:
        self.stress_calls += 1
        return {
            "company_name": company_name,
            "report_period": "2025Q3",
            "user_role": user_role,
            "scenario": scenario,
            "severity": {"level": "HIGH", "label": "重点关注", "color": "warning"},
            "affected_dimensions": [{"label": "风险标签", "value": 3, "hint": "B"}],
            "propagation_steps": [{"step": 1, "title": "上游冲击", "detail": scenario}],
            "transmission_matrix": [{"stage": "upstream", "headline": "原料成本承压", "impact_score": "-12%", "impact_label": "高冲击"}],
            "simulation_log": [{"step": 1, "title": "冲击注入", "detail": scenario}],
            "stress_command_surface": {"headline": "原料成本承压", "impact_label": "高冲击"},
            "stress_wavefront": [{"step": 1, "impact_score": 82}],
            "stress_impact_tape": [{"step": 1, "label": "原料成本", "value": "-12%"}],
            "stress_recovery_sequence": [{"step": 1, "title": "重排采购", "detail": "先稳住关键原料", "tone": "warning"}],
            "actions": [{"priority": "P1", "title": "重排采购"}],
            "related_routes": [{"label": "执行压力测试", "path": "/stress", "query": {"company": company_name}}],
            "evidence_navigation": {"links": [{"label": "查看推演证据", "path": "/evidence/2"}]},
            "chart": {"type": "bar", "title": "冲击传导强度", "options": {"series": [{"data": [82]}]}},
        }

    def company_timeline(self, company_name: str) -> dict:
        self.timeline_calls += 1
        return {
            "company_name": company_name,
            "latest_period": "2025Q3",
            "key_numbers": [{"label": "已覆盖报期", "value": 3, "unit": "个"}],
            "snapshots": [{"report_period": "2025Q3", "total_score": 78, "grade": "B"}],
            "charts": [{"type": "line", "title": "报期总分变化", "options": {"series": [{"data": [71, 75, 78]}]}}],
        }

    @property
    def repository(self):
        return self

    def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
        if company_name != "示例公司":
            return None
        return {
            "company_name": "示例公司",
            "report_period": report_period or "2025Q3",
            "subindustry": "储能",
            "metrics": {
                "G1": 12.5,
                "G2": -18.4,
                "P1": 19.8,
                "P4": 132,
                "C1": 0.72,
                "C3": 11.6,
                "S4": 0.81,
            },
        }


class AgentsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_collect_enriched_payload_reuses_full_tool_results(self) -> None:
        service = AgentServiceStub()
        wrappers, tool_results = _make_tool_wrappers(service, "示例公司", None, "management")

        wrappers["tool_company_timeline"]()
        wrappers["tool_graph_query"](intent="现金流风险传导")
        await wrappers["tool_stress_test"](scenario="上游断供")

        self.assertEqual(service.timeline_calls, 1)
        self.assertEqual(service.graph_calls, 1)
        self.assertEqual(service.stress_calls, 1)

        trace = ToolCallTrace()
        trace.records = [
            {"tool_name": "tool_company_timeline", "success": True},
            {"tool_name": "tool_graph_query", "success": True},
            {"tool_name": "tool_stress_test", "success": True},
        ]

        payload = _collect_enriched_payload(
            service=service,
            company_name="示例公司",
            report_period=None,
            query_type="stress_test",
            trace=trace,
            tool_results=tool_results,
        )

        self.assertEqual(service.timeline_calls, 1)
        self.assertEqual(service.graph_calls, 1)
        self.assertEqual(service.stress_calls, 1)
        self.assertEqual(payload["report_period"], "2025Q3")
        self.assertEqual(payload["graph"]["node_count"], 3)
        self.assertEqual(payload["severity"]["level"], "HIGH")
        self.assertEqual(payload["snapshots"][0]["report_period"], "2025Q3")
        self.assertEqual(len(payload["charts"]), 2)

    async def test_run_orchestrator_keeps_resolved_report_period(self) -> None:
        service = AgentServiceStub()

        async def fake_generate_completion(**kwargs):
            tool_registry = kwargs["tool_registry"]
            trace = ToolCallTrace()
            tool_registry["tool_graph_query"](intent="现金流风险传导")
            trace.records = [{"tool_name": "tool_graph_query", "success": True}]
            return (
                json.dumps(
                    {
                        "answer_markdown": "已完成图谱推理",
                        "query_type": "graph_query",
                        "key_numbers": [],
                    },
                    ensure_ascii=False,
                ),
                trace,
            )

        with patch("opspilot.application.agents.generate_completion", new=fake_generate_completion):
            payload = await run_orchestrator(
                query="帮我分析现金流风险传导",
                company_name="示例公司",
                report_period=None,
                user_role="management",
                service=service,
            )

        self.assertEqual(payload["company_name"], "示例公司")
        self.assertEqual(payload["report_period"], "2025Q3")
        self.assertEqual(payload["query_type"], "graph_query")
        self.assertIn("graph", payload)
        self.assertEqual(payload["graph"]["node_count"], 3)

    def test_prompt_context_includes_semantic_layer_and_role_goal(self) -> None:
        service = AgentServiceStub()
        system_prompt, user_prompt = _build_agent_prompt_context(
            service=service,
            query="帮我做现金流风险传导分析",
            company_name="示例公司",
            report_period="2025Q3",
            user_role="management",
        )
        self.assertIn("评分语义层", system_prompt)
        self.assertIn("G1 营业收入同比", system_prompt)
        self.assertIn("R1 利润现金背离", system_prompt)
        self.assertIn("角色任务目标", user_prompt)
        self.assertIn("任务类型初判: graph_query", user_prompt)
        self.assertIn("子行业：储能", user_prompt)

    def test_detect_query_type_supports_graph_stress_and_timeline(self) -> None:
        self.assertEqual(detect_query_type("请做一下风险传导图谱分析"), "graph_query")
        self.assertEqual(detect_query_type("帮我做供应链冲击压力测试"), "stress_test")
        self.assertEqual(detect_query_type("回放这家公司近几期时间线变化"), "company_timeline")


if __name__ == "__main__":
    unittest.main()
