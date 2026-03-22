"""StressService — 压力测试与冲击推演域服务。

负责：company_stress_test / stress_test_runs / stress_test_run_detail
依赖：repository, settings, facade（用于跨服务调用 company_workspace / company_graph）
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opspilot.config import Settings

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# StressService
# ---------------------------------------------------------------------------


class StressService:
    def __init__(
        self,
        repository: Any,
        settings: Settings,
        facade: Any,
    ) -> None:
        self.repository = repository
        self.settings = settings
        # facade 提供 company_workspace / company_graph 两个方法
        self.facade = facade

    async def company_stress_test(
        self,
        company_name: str,
        scenario: str,
        report_period: str | None = None,
        *,
        user_role: str = "management",
    ) -> dict[str, Any]:
        workspace = self.facade.company_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
        graph = self.facade.company_graph(
            company_name,
            workspace["report_period"],
            user_role=user_role,
        )
        from opspilot.application.agents import run_stress_agent

        agent_data = await run_stress_agent(company_name, scenario, workspace["report_period"])

        propagation_steps = agent_data.get("propagation_steps", [])
        severity = agent_data.get(
            "severity",
            {"level": "MEDIUM", "label": "Unknown", "color": "warning"},
        )
        transmission_matrix = agent_data.get("transmission_matrix", [])
        simulation_log = agent_data.get("simulation_log", [])

        graph_nodes = graph.get("nodes", [])
        graph_edges = graph.get("edges", [])

        if not propagation_steps:
            top_risks = workspace.get("top_risks", [])
            alert_items = workspace.get("alerts", {}).get("items", [])
            task_items = workspace.get("action_cards", [])
            propagation_steps = _build_stress_propagation_steps(
                company_name=company_name,
                scenario=scenario,
                graph_nodes=graph_nodes,
                graph_edges=graph_edges,
                top_risks=top_risks,
                alert_items=alert_items,
                task_items=task_items,
            )

        if not transmission_matrix:
            top_risks = workspace.get("top_risks", [])
            open_tasks = workspace.get("tasks", {}).get("summary", {}).get("in_progress", 0)
            open_alerts = workspace.get("alerts", {}).get("summary", {}).get("new", 0)
            risk_count = workspace.get("score_summary", {}).get("risk_count", 0)
            severity = _classify_stress_severity(
                scenario=scenario,
                risk_count=risk_count,
                open_tasks=open_tasks,
                open_alerts=open_alerts,
            )
            transmission_matrix = _build_stress_transmission_matrix(
                propagation_steps=propagation_steps,
                severity=severity,
                workspace=workspace,
            )

        if not simulation_log:
            simulation_log = _build_stress_simulation_log(
                company_name=company_name,
                scenario=scenario,
                propagation_steps=propagation_steps,
                workspace=workspace,
            )

        payload: dict[str, Any] = {
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
            "stress_command_surface": _build_stress_command_surface(
                company_name=company_name,
                scenario=scenario,
                severity=severity,
                transmission_matrix=transmission_matrix,
                simulation_log=simulation_log,
                workspace=workspace,
            ),
            "stress_wavefront": _build_stress_wavefront(
                propagation_steps=propagation_steps,
                transmission_matrix=transmission_matrix,
                simulation_log=simulation_log,
                severity=severity,
            ),
            "stress_impact_tape": _build_stress_impact_tape(
                transmission_matrix=transmission_matrix,
                simulation_log=simulation_log,
                severity=severity,
            ),
            "stress_recovery_sequence": _build_stress_recovery_sequence(
                actions=workspace["action_cards"],
                top_risks=workspace.get("top_risks", []),
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


# ---------------------------------------------------------------------------
# 压力测试构建函数
# ---------------------------------------------------------------------------


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
        {"step": 1, "title": "注入冲击", "detail": scenario, "tone": "input"},
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


def _build_stress_command_surface(
    *,
    company_name: str,
    scenario: str,
    severity: dict[str, Any],
    transmission_matrix: list[dict[str, Any]],
    simulation_log: list[dict[str, Any]],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    dominant = max(
        transmission_matrix,
        key=lambda item: int(item.get("impact_score", 0)),
        default={},
    )
    return {
        "title": f"{company_name} 冲击推演",
        "scenario": scenario,
        "severity": severity["level"],
        "severity_label": severity["label"],
        "headline": dominant.get("headline") or "等待冲击传导",
        "impact_label": dominant.get("impact_label") or severity["label"],
        "impact_score": int(dominant.get("impact_score", 0)),
        "energy_curve": [int(item.get("impact_score", 0)) for item in transmission_matrix[:3]],
        "watch_items": [
            {"label": "风险标签", "value": str(workspace["score_summary"]["risk_count"])},
            {"label": "在办任务", "value": str(workspace["tasks"]["summary"]["in_progress"])},
            {"label": "新增预警", "value": str(workspace["alerts"]["summary"]["new"])},
        ],
        "log_headline": simulation_log[-1]["detail"] if simulation_log else "等待推演日志",
    }


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
    top_risks = "、".join(workspace.get("top_risks", [])[:3]) or "暂无高风险标签"
    actions = workspace["action_cards"][0]["title"] if workspace["action_cards"] else "等待动作收口"
    checkpoints = [
        ("初始化", f"{company_name} / {workspace['report_period']}"),
        ("冲击注入", scenario),
        ("风险映射", top_risks),
        (
            "传导分析",
            propagation_steps[2]["detail"] if len(propagation_steps) > 2 else propagation_steps[-1]["detail"] if propagation_steps else "等待传导分析",
        ),
        ("动作收口", actions),
    ]
    return [
        {"step": index + 1, "title": title, "detail": detail}
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


def _build_stress_impact_tape(
    *,
    transmission_matrix: list[dict[str, Any]],
    simulation_log: list[dict[str, Any]],
    severity: dict[str, Any],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, item in enumerate(transmission_matrix):
        log_entry = simulation_log[min(index, len(simulation_log) - 1)] if simulation_log else {}
        impact_score = int(item.get("impact_score", 0))
        tape.append(
            {
                "step": index + 1,
                "label": item.get("stage") or f"阶段 {index + 1}",
                "headline": item.get("headline") or log_entry.get("title") or severity["label"],
                "intensity": max(12, min(100, impact_score + 18)),
                "tone": item.get("tone") or "warning",
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待推演",
                "headline": severity["label"],
                "intensity": 0,
                "tone": "warning",
            }
        )
    return tape


def _build_stress_recovery_sequence(
    *,
    actions: list[dict[str, Any]],
    top_risks: list[str],
    severity: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, action in enumerate(actions[:4]):
        items.append(
            {
                "step": index + 1,
                "title": action.get("title") or f"动作 {index + 1}",
                "detail": action.get("reason") or action.get("action") or "等待动作建议",
                "tone": "risk" if severity["level"] == "CRITICAL" and index == 0 else "accent",
            }
        )
    if not items:
        items.append(
            {
                "step": 1,
                "title": "继续跟踪",
                "detail": "、".join(top_risks[:2]) or "等待恢复路径",
                "tone": "accent",
            }
        )
    return items


# ---------------------------------------------------------------------------
# 文件 I/O 工具
# ---------------------------------------------------------------------------


def _load_stress_test_run_manifest(settings: Settings) -> dict[str, Any]:
    manifest_path = settings.bronze_data_path / "manifests" / "stress_test_runs.json"
    if not manifest_path.exists():
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}
    try:
        with manifest_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {"generated_at": _utcnow_iso(), "record_count": 0, "records": []}


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
