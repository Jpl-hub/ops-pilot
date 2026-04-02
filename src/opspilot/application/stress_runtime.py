from __future__ import annotations

from typing import Any

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
        {
            "step": 1,
            "title": "注入冲击",
            "detail": scenario,
            "tone": "input",
        },
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
        {
            "step": 1,
            "label": "总分",
            "value": f"{score_result['total_score']} / {score_result['grade']}",
            "tone": "accent",
            "intensity": min(100, 30 + int(score_result["total_score"])),
        },
        {
            "step": 2,
            "label": "风险",
            "value": risks[0]["name"] if risks else "无显著风险",
            "tone": "risk" if risks else "success",
            "intensity": 76 if risks else 28,
        },
        {
            "step": 3,
            "label": "动作",
            "value": action_cards[0]["title"] if action_cards else "等待动作收口",
            "tone": "warning" if action_cards else "accent",
            "intensity": 68 if action_cards else 20,
        },
    ]
    if opportunities:
        tape.append(
            {
                "step": 4,
                "label": "机会",
                "value": opportunities[0]["name"],
                "tone": "success",
                "intensity": 54,
            }
        )
    return tape


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
        "energy_curve": [
            int(item.get("impact_score", 0))
            for item in transmission_matrix[:3]
        ],
        "watch_items": [
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
            },
            {
                "label": "在办任务",
                "value": str(workspace["tasks"]["summary"]["in_progress"]),
            },
            {
                "label": "新增预警",
                "value": str(workspace["alerts"]["summary"]["new"]),
            },
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
    top_risks = "、".join(workspace["top_risks"][:3]) or "暂无高风险标签"
    actions = workspace["action_cards"][0]["title"] if workspace["action_cards"] else "等待动作收口"
    checkpoints = [
        ("初始化", f"{company_name} / {workspace['report_period']}"),
        ("冲击注入", scenario),
        ("风险映射", top_risks),
        (
            "传导分析",
            propagation_steps[2]["detail"] if len(propagation_steps) > 2 else propagation_steps[-1]["detail"],
        ),
        ("动作收口", actions),
    ]
    return [
        {
            "step": index + 1,
            "title": title,
            "detail": detail,
        }
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
