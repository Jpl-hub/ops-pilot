from __future__ import annotations

from datetime import UTC, date, datetime
import re
from typing import Any

from opspilot.application.industry_signals import (
    _describe_external_signal_freshness,
    _parse_calendar_date,
)

_GRAPH_QUERY_TERM_EXPANSIONS = {
    "应收": ("应收账款", "账期", "回款", "现金流"),
    "现金": ("现金流", "货币资金", "流动性", "偿债"),
    "风险": ("风险", "预警", "整改", "暴露"),
    "传导": ("传导", "路径", "影响链", "执行流"),
    "供应链": ("供应链", "上游", "下游", "链条"),
    "研报": ("研报", "观点", "预测", "核验"),
    "证据": ("证据", "页码", "字段", "导航"),
    "文档": ("文档", "解析", "标题层级", "单元格溯源"),
    "存货": ("存货", "周转", "库存", "减值"),
    "增长": ("营收", "增长", "扩张", "市场份额"),
    "价格": ("价格", "成本", "毛利率", "碳酸锂"),
    "偿债": ("偿债", "流动比率", "短期借款", "利息"),
    "实时": ("实时", "最新", "时序", "外部信号", "动量", "热度"),
    "最新": ("最新", "最近", "时效", "窗口", "外部事件"),
    "异动": ("异动", "热度", "信号", "预警", "波动"),
    "时间": ("时间线", "时序", "最近", "窗口", "日度"),
}

_GRAPH_INTENT_TYPE_PRIOR = {
    "price": {
        "signal_event": 5,
        "signal_timeline": 5,
        "subindustry_signal": 6,
        "risk_label": 5,
        "alert": 5,
        "research_report": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "task": 3,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "cash": {
        "signal_event": 5,
        "signal_timeline": 6,
        "subindustry_signal": 4,
        "risk_label": 6,
        "alert": 5,
        "task": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "execution_stream": 3,
        "watchboard": 3,
        "research_report": 3,
        "company": 2,
        "report_period": 1,
    },
    "growth": {
        "signal_event": 4,
        "signal_timeline": 5,
        "subindustry_signal": 5,
        "research_report": 5,
        "risk_label": 4,
        "task": 4,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "alert": 3,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "supply": {
        "signal_event": 5,
        "signal_timeline": 5,
        "subindustry_signal": 6,
        "risk_label": 5,
        "alert": 5,
        "task": 4,
        "research_report": 4,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "execution_stream": 3,
        "watchboard": 2,
        "company": 2,
        "report_period": 1,
    },
    "risk": {
        "signal_event": 6,
        "signal_timeline": 5,
        "subindustry_signal": 5,
        "risk_label": 6,
        "alert": 6,
        "task": 5,
        "document_artifact": 4,
        "artifact_evidence": 4,
        "research_report": 4,
        "execution_stream": 3,
        "watchboard": 3,
        "company": 2,
        "report_period": 1,
    },
}


def _dedupe_terms(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if len(normalized) < 2:
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _expand_graph_query_terms(intent: str) -> list[str]:
    lowered = intent.lower()
    terms: list[str] = []
    for part in re.split(r"[\s,，。；;、\-_/]+", lowered):
        part = part.strip()
        if len(part) >= 2:
            terms.append(part)
    chinese_spans = re.findall(r"[\u4e00-\u9fff]{2,}", intent)
    for span in chinese_spans:
        if len(span) <= 6:
            terms.append(span)
        else:
            for index in range(0, len(span) - 1):
                terms.append(span[index : index + 2])
                if index + 3 <= len(span):
                    terms.append(span[index : index + 3])
    for keyword, expansions in _GRAPH_QUERY_TERM_EXPANSIONS.items():
        if keyword in intent:
            terms.append(keyword)
            terms.extend(expansions)
    dimension = _classify_intent(intent)
    dimension_title, dimension_detail = _INTENT_DIMENSION_DESC.get(
        dimension,
        _INTENT_DIMENSION_DESC["risk"],
    )
    terms.append(dimension_title.replace("维度", ""))
    terms.extend(
        [part for part in re.findall(r"[\u4e00-\u9fff]{2,}", dimension_detail) if len(part) >= 2]
    )
    deduped: list[str] = []
    for term in terms:
        normalized = str(term).strip().lower()
        if len(normalized) < 2:
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped[:24]


def _build_graph_node_text(node: dict[str, Any]) -> str:
    meta = node.get("meta") or {}
    meta_parts: list[str] = []
    for key, value in meta.items():
        if isinstance(value, list):
            meta_parts.extend(str(item) for item in value if item is not None)
        elif value is not None:
            meta_parts.append(f"{key} {value}")
    return " ".join(
        [
            str(node.get("label") or ""),
            str(node.get("type") or ""),
            *meta_parts,
        ]
    ).lower()


def _build_graph_edge_maps(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    edge_labels_by_node: dict[str, list[str]] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        label = str(edge.get("label") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append({"node_id": target, "label": label})
        adjacency.setdefault(target, []).append({"node_id": source, "label": label})
        if label:
            edge_labels_by_node.setdefault(source, []).append(label)
            edge_labels_by_node.setdefault(target, []).append(label)
    return adjacency, edge_labels_by_node


def _graph_node_temporal_meta(node: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    meta = node.get("meta") or {}
    latest_value = (
        meta.get("latest_event_time")
        or meta.get("latest_event_date")
        or meta.get("latest_publish_date")
    )
    return (_parse_calendar_date(str(latest_value) if latest_value is not None else None), meta)


def _score_graph_temporal_signal(
    node: dict[str, Any],
    query_terms: list[str],
) -> tuple[int, list[str]]:
    node_type = str(node.get("type") or "")
    if node_type not in _GRAPH_SIGNAL_NODE_TYPES:
        return 0, []
    latest_date, meta = _graph_node_temporal_meta(node)
    score = 0
    explain: list[str] = []
    if latest_date is not None:
        age_days = max(0, (datetime.now(UTC).date() - latest_date).days)
        if age_days <= 1:
            score += 10
            explain.append("近 24 小时更新")
        elif age_days <= 3:
            score += 7
            explain.append(f"{age_days} 天内更新")
        elif age_days <= 7:
            score += 4
            explain.append(f"最近 {age_days} 天更新")
    momentum = int(meta.get("momentum") or 0)
    latest_heat = int(meta.get("latest_heat") or 0)
    external_heat = int(meta.get("external_heat") or 0)
    signal_count = int(meta.get("signal_count") or 0)
    active_days = int(meta.get("active_days") or 0)
    realtime_requested = any(term in intent_term for term in _GRAPH_REALTIME_TERMS for intent_term in query_terms)
    if momentum > 0:
        score += min(10, momentum * 2 if realtime_requested else momentum)
        explain.append(f"动量 {momentum}")
    if latest_heat > 0:
        score += min(6, latest_heat if realtime_requested else max(1, latest_heat // 2))
        explain.append(f"最新热度 {latest_heat}")
    if external_heat > 0:
        score += min(6, max(1, external_heat // 2))
        explain.append(f"累计热度 {external_heat}")
    if signal_count > 0:
        score += min(5, signal_count if realtime_requested else max(1, signal_count // 2))
        explain.append(f"{signal_count} 条正式信号")
    if active_days > 0:
        score += min(4, active_days)
        explain.append(f"活跃 {active_days} 天")
    if node_type == "subindustry_signal" and any(
        term in query_term
        for term in ("行业", "板块", "子行业", "上游", "下游", "供应链")
        for query_term in query_terms
    ):
        score += 6
        explain.append("板块共振命中")
    return score, explain[:4]


def _score_graph_edge_label(label: str, query_terms: list[str]) -> tuple[int, list[str]]:
    lowered = str(label or "").lower()
    hits = [term for term in query_terms if term in lowered]
    return (len(hits) * 2, hits)


def _rank_graph_nodes_for_intent(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    intent: str,
) -> list[dict[str, Any]]:
    dimension = _classify_intent(intent)
    type_priority = _GRAPH_INTENT_TYPE_PRIOR.get(dimension, _GRAPH_INTENT_TYPE_PRIOR["risk"])
    query_terms = _expand_graph_query_terms(intent)
    adjacency, edge_labels_by_node = _build_graph_edge_maps(edges)
    text_by_node = {str(node.get("id")): _build_graph_node_text(node) for node in nodes}
    base_scores: dict[str, int] = {}
    lexical_hits_by_node: dict[str, list[str]] = {}
    neighbor_hits_by_node: dict[str, list[str]] = {}
    edge_hits_by_node: dict[str, list[str]] = {}
    temporal_hits_by_node: dict[str, list[str]] = {}

    for node in nodes:
        node_id = str(node.get("id") or "")
        label_text = str(node.get("label") or "").lower()
        node_text = text_by_node.get(node_id, "")
        lexical_score = 0
        lexical_hits: list[str] = []
        for term in query_terms:
            if term in label_text:
                lexical_score += 8
                lexical_hits.append(term)
            elif term in node_text:
                lexical_score += 4
                lexical_hits.append(term)
        edge_score = 0
        edge_hits: list[str] = []
        for label in edge_labels_by_node.get(node_id, []):
            matched_score, matched_terms = _score_graph_edge_label(label, query_terms)
            edge_score += matched_score
            edge_hits.extend(matched_terms)
        degree_score = min(3, len(adjacency.get(node_id, [])))
        temporal_score, temporal_hits = _score_graph_temporal_signal(node, query_terms)
        base_scores[node_id] = (
            type_priority.get(str(node.get("type")), 0)
            + lexical_score
            + edge_score
            + degree_score
            + temporal_score
        )
        lexical_hits_by_node[node_id] = _dedupe_terms(lexical_hits)
        edge_hits_by_node[node_id] = _dedupe_terms(edge_hits)
        temporal_hits_by_node[node_id] = temporal_hits

    ranked: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        neighbor_terms: list[str] = []
        neighbor_score = 0
        for neighbor in adjacency.get(node_id, []):
            neighbor_id = str(neighbor.get("node_id") or "")
            neighbor_base = int(base_scores.get(neighbor_id) or 0)
            if neighbor_base <= 0:
                continue
            matched_score, matched_terms = _score_graph_edge_label(str(neighbor.get("label") or ""), query_terms)
            neighbor_text = text_by_node.get(neighbor_id, "")
            neighbor_term_hits = [term for term in query_terms if term in neighbor_text]
            if neighbor_term_hits:
                neighbor_terms.extend(neighbor_term_hits)
                neighbor_score += min(8, max(2, neighbor_base // 3))
            if matched_score:
                neighbor_terms.extend(matched_terms)
                neighbor_score += matched_score
        total_score = int(base_scores.get(node_id) or 0) + min(18, neighbor_score)
        explain_parts: list[str] = []
        if lexical_hits_by_node.get(node_id):
            explain_parts.append(f"命中查询词：{' / '.join(lexical_hits_by_node[node_id][:3])}")
        if edge_hits_by_node.get(node_id):
            explain_parts.append(f"边标签命中：{' / '.join(edge_hits_by_node[node_id][:2])}")
        deduped_neighbor_terms = _dedupe_terms(neighbor_terms)
        if deduped_neighbor_terms:
            explain_parts.append(f"邻居传播：{' / '.join(deduped_neighbor_terms[:3])}")
        if temporal_hits_by_node.get(node_id):
            explain_parts.append(f"时序加权：{' / '.join(temporal_hits_by_node[node_id][:3])}")
        explain_parts.append(f"节点类型：{node.get('type')}")
        ranked.append(
            {
                **node,
                "intent_score": total_score,
                "hit_terms": lexical_hits_by_node.get(node_id, []),
                "edge_terms": edge_hits_by_node.get(node_id, []),
                "neighbor_terms": deduped_neighbor_terms,
                "rank_explain": "；".join(explain_parts),
            }
        )

    ranked.sort(
        key=lambda item: (
            int(item.get("intent_score") or 0),
            type_priority.get(str(item.get("type")), 0),
            str(item.get("label", "")),
        ),
        reverse=True,
    )
    return ranked


def _find_graph_path(
    *,
    adjacency: dict[str, list[dict[str, Any]]],
    start_id: str,
    target_id: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not start_id or not target_id:
        return ([], [])
    if start_id == target_id:
        return ([start_id], [])
    queue: list[tuple[str, list[str], list[dict[str, Any]]]] = [(start_id, [start_id], [])]
    visited = {start_id}
    while queue:
        node_id, path_nodes, path_edges = queue.pop(0)
        for neighbor in adjacency.get(node_id, []):
            next_id = str(neighbor.get("node_id") or "")
            if not next_id or next_id in visited:
                continue
            next_nodes = [*path_nodes, next_id]
            next_edges = [*path_edges, {"source": node_id, "target": next_id, "label": neighbor.get("label")}]
            if next_id == target_id:
                return (next_nodes, next_edges)
            visited.add(next_id)
            queue.append((next_id, next_nodes, next_edges))
    return ([], [])


def _describe_graph_path(
    *,
    path_nodes: list[dict[str, Any]],
    path_edges: list[dict[str, Any]],
) -> str:
    if not path_nodes:
        return "未找到有效路径。"
    if len(path_nodes) == 1:
        return f"直接命中节点 {path_nodes[0].get('label') or '未命名节点'}。"
    parts: list[str] = []
    for index, node in enumerate(path_nodes[:-1]):
        edge = path_edges[index] if index < len(path_edges) else {}
        next_node = path_nodes[index + 1]
        parts.append(
            f"{node.get('label') or node.get('id')} --{edge.get('label') or '关联'}--> {next_node.get('label') or next_node.get('id')}"
        )
    return "；".join(parts)


def _retrieve_graph_paths(
    *,
    graph: dict[str, Any],
    company_name: str,
    report_period: str,
    intent: str,
    limit: int = 6,
) -> dict[str, Any]:
    ranked_nodes = _rank_graph_nodes_for_intent(graph.get("nodes", []), graph.get("edges", []), intent)
    node_by_id = {
        str(node.get("id")): node
        for node in ranked_nodes
        if node.get("id")
    }
    adjacency, _ = _build_graph_edge_maps(graph.get("edges", []))
    company_node_id = _graph_node_id("company", company_name)
    period_node_id = _graph_node_id("period", report_period)
    query_terms = _expand_graph_query_terms(intent)
    focal_nodes = [
        node
        for node in ranked_nodes
        if node.get("type") not in {"company", "report_period"}
    ][:8]
    paths: list[dict[str, Any]] = []
    for node in focal_nodes:
        node_id = str(node.get("id") or "")
        candidate_paths: list[tuple[list[str], list[dict[str, Any]]]] = []
        company_path = _find_graph_path(adjacency=adjacency, start_id=company_node_id, target_id=node_id)
        if company_path[0]:
            candidate_paths.append(company_path)
        period_path = _find_graph_path(adjacency=adjacency, start_id=period_node_id, target_id=node_id)
        if period_path[0]:
            candidate_paths.append(period_path)
        if not candidate_paths:
            continue
        best_nodes, best_edges = max(
            candidate_paths,
            key=lambda item: (
                -len(item[0]),
                sum(int(node_by_id.get(path_node, {}).get("intent_score") or 0) for path_node in item[0]),
            ),
        )
        path_node_items = [node_by_id.get(path_node) for path_node in best_nodes if node_by_id.get(path_node)]
        if not path_node_items:
            continue
        path_score = sum(int(item.get("intent_score") or 0) for item in path_node_items)
        support_candidates = []
        predecessor_id = best_nodes[-2] if len(best_nodes) >= 2 else None
        for neighbor in adjacency.get(node_id, []):
            support_id = str(neighbor.get("node_id") or "")
            if not support_id or support_id == predecessor_id:
                continue
            support_node = node_by_id.get(support_id)
            if support_node is None:
                continue
            support_candidates.append((int(support_node.get("intent_score") or 0), support_node, neighbor))
        support_node = None
        support_edge = None
        if support_candidates:
            support_candidates.sort(key=lambda item: item[0], reverse=True)
            _, support_node, support_edge = support_candidates[0]
        path_summary = _describe_graph_path(path_nodes=path_node_items, path_edges=best_edges)
        if support_node is not None and support_edge is not None:
            path_summary += (
                f"；继续延展到 {support_node.get('label') or support_node.get('id')}"
                f"（{support_edge.get('label') or '支撑'}）"
            )
            path_score += int(support_node.get("intent_score") or 0)
        paths.append(
            {
                "target_id": node_id,
                "target_label": node.get("label"),
                "target_type": node.get("type"),
                "target_meta": node.get("meta") or {},
                "target_score": int(node.get("intent_score") or 0),
                "path_score": path_score,
                "path_nodes": path_node_items + ([support_node] if support_node is not None else []),
                "path_edges": best_edges + (
                    [{"source": node_id, "target": support_node.get("id"), "label": support_edge.get("label")}]
                    if support_node is not None and support_edge is not None
                    else []
                ),
                "path_summary": path_summary,
                "why": node.get("rank_explain"),
                "hit_terms": node.get("hit_terms", []),
            }
        )
    paths.sort(
        key=lambda item: (
            int(item.get("path_score") or 0),
            int(item.get("target_score") or 0),
            str(item.get("target_label") or ""),
        ),
        reverse=True,
    )
    top_paths = paths[:limit]
    evidence_count = sum(
        1
        for path in top_paths
        for node in path.get("path_nodes", [])
        if str((node or {}).get("type")) in {"document_artifact", "artifact_evidence", "research_report"}
    )
    temporal_nodes = [
        node
        for path in top_paths
        for node in path.get("path_nodes", [])
        if isinstance(node, dict) and str(node.get("type") or "") in _GRAPH_SIGNAL_NODE_TYPES
    ]
    latest_signal_date = max(
        (
            _graph_node_temporal_meta(node)[0]
            for node in temporal_nodes
            if _graph_node_temporal_meta(node)[0] is not None
        ),
        default=None,
    )
    freshness_status, freshness_label = _describe_external_signal_freshness(
        latest_signal_date.isoformat() if latest_signal_date is not None else None
    )
    signal_event_node = next(
        (
            node
            for node in temporal_nodes
            if str(node.get("type") or "") == "signal_event"
        ),
        None,
    )
    signal_timeline_node = next(
        (
            node
            for node in temporal_nodes
            if str(node.get("type") or "") == "signal_timeline"
        ),
        None,
    )
    signal_meta = (signal_timeline_node or signal_event_node or {}).get("meta") or {}
    summary = {
        "intent_dimension": _classify_intent(intent),
        "query_terms": query_terms,
        "query_term_count": len(query_terms),
        "candidate_count": len(ranked_nodes),
        "focal_count": len(focal_nodes),
        "path_count": len(top_paths),
        "evidence_count": evidence_count,
        "signal_node_count": len(temporal_nodes),
        "freshness_status": freshness_status,
        "freshness_label": (
            freshness_label if temporal_nodes else "图谱内暂无时序信号"
        ),
        "latest_signal_time": signal_meta.get("latest_event_time"),
        "latest_signal_headline": (
            signal_event_node.get("label")
            if isinstance(signal_event_node, dict)
            else None
        ),
        "time_window_days": int(signal_meta.get("window_days") or 0),
        "signal_count": int(signal_meta.get("signal_count") or 0),
        "latest_heat": int(signal_meta.get("latest_heat") or 0),
        "external_heat": int(signal_meta.get("external_heat") or 0),
        "max_momentum": int(signal_meta.get("momentum") or 0),
        "active_days": int(signal_meta.get("active_days") or 0),
        "top_hit_terms": _dedupe_terms(
            [term for path in top_paths for term in path.get("hit_terms", [])]
        )[:6],
    }
    return {
        "summary": summary,
        "ranked_nodes": ranked_nodes,
        "focal_nodes": focal_nodes,
        "paths": top_paths,
    }


def _describe_graph_focus_node(node: dict[str, Any], workspace: dict[str, Any]) -> str:
    node_type = str(node.get("type"))
    meta = node.get("meta") or {}
    if node_type == "risk_label":
        return "当前体检中命中的核心风险标签之一。"
    if node_type == "alert":
        return f"主动预警状态：{meta.get('status') or 'unknown'}。"
    if node_type == "task":
        return f"整改任务优先级 {meta.get('priority') or '-'}，状态 {meta.get('status') or '-'}。"
    if node_type == "research_report":
        return f"研报核验已就绪，预测项 {meta.get('forecast_count') or 0} 条。"
    if node_type == "document_artifact":
        return f"文档升级产物：{meta.get('summary') or '已生成可消费结构'}。"
    if node_type == "artifact_evidence":
        return "可以继续下钻到证据页查看字段和页码。"
    if node_type == "execution_stream":
        return f"执行流状态：{meta.get('status') or 'tracked'}。"
    if node_type == "signal_event":
        return (
            f"最新外部信号：{meta.get('signal_status') or '事件更新'}，"
            f"{meta.get('freshness_label') or '时效待校准'}。"
        )
    if node_type == "signal_timeline":
        return (
            f"近 {meta.get('window_days') or 7} 日累计热度 {meta.get('external_heat') or 0}，"
            f"动量 {meta.get('momentum') or 0}。"
        )
    if node_type == "subindustry_signal":
        return (
            f"{meta.get('subindustry') or workspace['score_summary']['subindustry']} 板块近窗热度"
            f" {meta.get('latest_heat') or 0}，动量 {meta.get('momentum') or 0}。"
        )
    if node_type == "watchboard":
        return f"监测板持续跟踪，新增预警 {meta.get('new_alerts') or 0} 条。"
    if node_type == "company":
        return f"总分 {workspace['score_summary']['total_score']}，等级 {workspace['score_summary']['grade']}。"
    return "该节点参与当前查询意图的传导路径。"


def _classify_intent(intent: str) -> str:
    """Classify intent into a primary dimension for varied path generation."""
    price_kw = ["价格", "成本", "涨价", "跌价", "碳酸锂", "锂", "铜", "原材料"]
    risk_kw = ["风险", "断供", "停产", "下滑", "压力", "危机"]
    growth_kw = ["增长", "营收", "市场", "扩张", "需求", "份额"]
    cash_kw = ["现金", "流动", "偿债", "应收", "账期", "融资"]
    supply_kw = ["供应链", "上游", "下游", "传导", "产业链"]
    for kw in price_kw:
        if kw in intent:
            return "price"
    for kw in cash_kw:
        if kw in intent:
            return "cash"
    for kw in growth_kw:
        if kw in intent:
            return "growth"
    for kw in supply_kw:
        if kw in intent:
            return "supply"
    for kw in risk_kw:
        if kw in intent:
            return "risk"
    return "risk"


_INTENT_DIMENSION_DESC = {
    "price": ("成本传导维度", "识别关键原材料价格波动对毛利率的压缩路径。"),
    "cash": ("现金流维度", "追踪应收账款、库存占用对经营性现金流净额的拖拽。"),
    "growth": ("成长性维度", "评估营收增速驱动力与市场份额变化的可持续性。"),
    "supply": ("供应链维度", "上游集中度与下游议价能力对利润的双向挤压效应。"),
    "risk": ("风险暴露维度", "聚焦已命中的风险标签，建立从识别到行动的闭环。"),
}

_GRAPH_SIGNAL_NODE_TYPES = {"signal_event", "signal_timeline", "subindustry_signal"}
_GRAPH_REALTIME_TERMS = ("实时", "最新", "最近", "时效", "异动", "窗口", "时间", "时序", "今日", "本周")


def _build_graph_query_inference_path(
    *,
    company_name: str,
    report_period: str,
    intent: str,
    focal_nodes: list[dict[str, Any]],
    retrieved_paths: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    dim = _classify_intent(intent)
    dim_title, dim_detail = _INTENT_DIMENSION_DESC.get(dim, _INTENT_DIMENSION_DESC["risk"])
    score = workspace.get("score_summary", {})
    freshness_note = ""
    if retrieval_summary.get("latest_signal_headline"):
        freshness_note = (
            f" 最近信号：{retrieval_summary.get('latest_signal_headline')}，"
            f"{retrieval_summary.get('freshness_label') or '时效待校准'}。"
        )
    steps: list[dict[str, Any]] = [
        {
            "step": 1,
            "title": company_name,
            "detail": f"{report_period} | 总分 {score.get('total_score', '-')} / 等级 {score.get('grade', '-')}。",
            "type": "company",
        },
        {
            "step": 2,
            "title": dim_title,
            "detail": (
                f"{dim_detail} 检索词 {retrieval_summary.get('query_term_count', 0)} 个，"
                f"命中路径 {retrieval_summary.get('path_count', 0)} 条。{freshness_note}"
            ),
            "type": "intent",
        },
    ]
    graph_paths = retrieved_paths[:3]
    for index, path in enumerate(graph_paths, start=3):
        target_label = path.get("target_label") or f"命中节点 {index - 2}"
        detail = (
            f"{path.get('path_summary') or '已生成图谱路径'} "
            f"检索说明：{path.get('why') or '无'}。"
        )
        steps.append(
            {
                "step": index,
                "title": target_label,
                "detail": detail,
                "type": path.get("target_type"),
            }
        )
    if not graph_paths:
        for index, node in enumerate(focal_nodes[:3], start=3):
            steps.append(
                {
                    "step": index,
                    "title": node["label"],
                    "detail": _describe_graph_focus_node(node, workspace),
                    "type": node.get("type"),
                }
            )
    steps.append(
        {
            "step": len(steps) + 1,
            "title": "动作收口",
            "detail": (
                f"围绕「{intent}」把风险、任务、证据和执行流压成可操作结论。"
                f" 当前回收到 {retrieval_summary.get('evidence_count', 0)} 个证据型节点，"
                f"时序信号 {retrieval_summary.get('signal_count', 0)} 条。"
            ),
            "type": "action",
        }
    )
    return steps


def _build_graph_query_phase_track(
    *,
    company_name: str,
    intent: str,
    workspace: dict[str, Any],
    inference_path: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_groups = workspace.get("evidence_groups") or []
    return [
        {
            "phase": "查询压缩",
            "status": "done",
            "headline": intent[:22] + ("..." if len(intent) > 22 else ""),
            "metric": f"{retrieval_summary.get('query_term_count', 0)} terms",
        },
        {
            "phase": "时序校准",
            "status": "done",
            "headline": retrieval_summary.get("freshness_label") or "时序信号待补齐",
            "metric": (
                retrieval_summary.get("latest_signal_time")
                or f"{retrieval_summary.get('time_window_days', 0)} day window"
            ),
        },
        {
            "phase": "图检索命中",
            "status": "done",
            "headline": company_name,
            "metric": f"{retrieval_summary.get('focal_count', 0)} nodes",
        },
        {
            "phase": "路径传导",
            "status": "done",
            "headline": "影响链已展开",
            "metric": f"{retrieval_summary.get('path_count', 0)} paths",
        },
        {
            "phase": "证据挂接",
            "status": "active",
            "headline": "证据与动作入口",
            "metric": f"{max(len(evidence_groups), retrieval_summary.get('evidence_count', 0))} sources",
        },
    ]


def _build_graph_query_signal_stream(
    *,
    focal_nodes: list[dict[str, Any]],
    retrieved_paths: list[dict[str, Any]],
    workspace: dict[str, Any],
    graph_node_count: int,
    retrieval_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in retrieved_paths[:4]:
        target_type = str(path.get("target_type") or "")
        target_meta = path.get("target_meta") or {}
        if target_type == "signal_event":
            items.append(
                {
                    "label": "最新事件",
                    "value": path.get("target_label") or target_meta.get("signal_status") or "外部信号",
                    "tone": "accent"
                    if target_meta.get("freshness_status") in {"fresh", "recent", "warm"}
                    else "warning",
                }
            )
            continue
        if target_type == "signal_timeline":
            items.append(
                {
                    "label": f"近 {target_meta.get('window_days') or 7} 日热度",
                    "value": (
                        f"{target_meta.get('signal_count') or 0} 条 · 动量"
                        f" {target_meta.get('momentum') or 0}"
                    ),
                    "tone": "accent",
                }
            )
            continue
        if target_type == "subindustry_signal":
            items.append(
                {
                    "label": "板块共振",
                    "value": (
                        f"{target_meta.get('subindustry') or path.get('target_label')} · 动量"
                        f" {target_meta.get('momentum') or 0}"
                    ),
                    "tone": "success",
                }
            )
            continue
        items.append(
            {
                "label": path.get("target_label", "路径"),
                "value": f"score {path.get('path_score', 0)}",
                "tone": "risk"
                if path.get("target_type") in {"risk_label", "alert", "task"}
                else "accent",
            }
        )
    if not items:
        items = [
            {
                "label": node.get("label", "节点"),
                "value": node.get("type", "focus"),
                "tone": "risk"
                if node.get("type") in {"risk_label", "alert", "task"}
                else "accent",
            }
            for node in focal_nodes[:4]
        ]
    items.extend(
        [
            {
                "label": "信号时效",
                "value": retrieval_summary.get("freshness_label") or "待校准",
                "tone": "success"
                if retrieval_summary.get("freshness_status") in {"fresh", "recent", "warm"}
                else "warning",
            },
            {
                "label": "图谱节点",
                "value": str(graph_node_count),
                "tone": "success",
            },
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
                "tone": "risk",
            },
        ]
    )
    return items[:6]


def _build_graph_query_live_frames(
    *,
    focal_nodes: list[dict[str, Any]],
    inference_path: list[dict[str, Any]],
    phase_track: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    support_node_ids = [node.get("id") for node in focal_nodes[:3] if node.get("id")]
    for index, item in enumerate(inference_path):
        phase = phase_track[min(index, len(phase_track) - 1)] if phase_track else {}
        active_nodes = [f"path-{item['step']}"]
        if index > 0:
            active_nodes.append(f"path-{inference_path[index - 1]['step']}")
        if support_node_ids:
            active_nodes.append(support_node_ids[index % len(support_node_ids)])
        frames.append(
            {
                "frame": index + 1,
                "headline": item["title"],
                "detail": item["detail"],
                "active_nodes": active_nodes,
                "active_links": [f"link-{item['step']}"],
                "phase": phase.get("phase"),
                "metric": phase.get("metric"),
                "signal": signal_stream[index % len(signal_stream)] if signal_stream else None,
                "intensity": min(100, 52 + index * 13),
            }
        )
    if not frames:
        frames.append(
            {
                "frame": 1,
                "headline": "等待图谱推理",
                "detail": "当前没有可播放的路径阶段。",
                "active_nodes": support_node_ids,
                "active_links": [],
                "phase": None,
                "metric": None,
                "signal": signal_stream[0] if signal_stream else None,
                "intensity": 0,
            }
        )
    return frames


def _build_graph_signal_tape(
    *,
    inference_path: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tape: list[dict[str, Any]] = []
    for index, item in enumerate(inference_path):
        signal = signal_stream[index % len(signal_stream)] if signal_stream else {}
        tape.append(
            {
                "step": item.get("step", index + 1),
                "label": item.get("title") or f"阶段 {index + 1}",
                "value": signal.get("value") or signal.get("label") or "等待信号",
                "tone": signal.get("tone") or "accent",
                "intensity": min(100, 30 + index * 18),
            }
        )
    if not tape:
        tape.append(
            {
                "step": 1,
                "label": "等待推理",
                "value": "等待信号",
                "tone": "accent",
                "intensity": 0,
            }
        )
    return tape


def _build_graph_command_surface(
    *,
    company_name: str,
    intent: str,
    focal_nodes: list[dict[str, Any]],
    inference_path: list[dict[str, Any]],
    phase_track: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
    retrieval_summary: dict[str, Any],
    workspace: dict[str, Any],
) -> dict[str, Any]:
    focus = focal_nodes[0] if focal_nodes else {}
    latest_phase = phase_track[-1] if phase_track else {}
    dominant_signal = signal_stream[0] if signal_stream else {}
    return {
        "title": "关键证据链路",
        "intent": intent,
        "focus_label": focus.get("label") or "等待焦点节点",
        "focus_type": focus.get("type") or "graph",
        "headline": latest_phase.get("headline") or "等待图谱推理",
        "metric": latest_phase.get("metric") or "GRAPH",
        "intensity": min(100, 42 + len(inference_path) * 11),
        "route_count": len(inference_path),
        "watch_items": [
            {
                "label": "信号时效",
                "value": retrieval_summary.get("freshness_label") or "待校准",
            },
            {
                "label": "7日信号",
                "value": str(retrieval_summary.get("signal_count") or 0),
            },
            {
                "label": "热度动量",
                "value": str(retrieval_summary.get("max_momentum") or 0),
            },
            {
                "label": "风险标签",
                "value": str(workspace["score_summary"]["risk_count"]),
            },
        ],
        "dominant_signal": {
            "label": dominant_signal.get("label") or "等待信号",
            "value": dominant_signal.get("value") or dominant_signal.get("label") or "N/A",
            "tone": dominant_signal.get("tone") or "accent",
        },
    }


def _build_graph_route_bands(
    *,
    inference_path: list[dict[str, Any]],
    signal_stream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bands: list[dict[str, Any]] = []
    for index, item in enumerate(inference_path):
        signal = signal_stream[index % len(signal_stream)] if signal_stream else {}
        bands.append(
            {
                "step": item.get("step", index + 1),
                "headline": item.get("title") or f"阶段 {index + 1}",
                "detail": item.get("detail") or "等待路径说明",
                "tone": signal.get("tone") or "accent",
                "signal": signal.get("value") or signal.get("label") or "等待信号",
                "intensity": min(100, 36 + index * 17),
            }
        )
    if not bands:
        bands.append(
            {
                "step": 1,
                "headline": "等待推理",
                "detail": "图谱路径生成后会出现在这里。",
                "tone": "accent",
                "signal": "等待信号",
                "intensity": 0,
            }
        )
    return bands


def _build_graph_query_evidence_navigation(workspace: dict[str, Any]) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    for item in workspace["document_upgrades"]["items"]:
        evidence_navigation = item.get("evidence_navigation") or {}
        links.extend(evidence_navigation.get("links", [])[:2])
    for run in workspace["recent_runs"]["items"][:2]:
        links.append(
            {
                "label": "查看分析运行",
                "path": f"/workspace?run={run['run_id']}",
                "query": {"company": workspace["company_name"]},
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        key = (str(link.get("label")), str(link.get("path")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return {
        "links": deduped[:6],
        "primary_route": deduped[0] if deduped else None,
    }


def _graph_node_id(prefix: str, value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-:\u4e00-\u9fff]+", "_", value).strip("_")
    return f"{prefix}:{safe}"


def _dedupe_graph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        node_id = node["id"]
        if node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(node)
    return deduped
