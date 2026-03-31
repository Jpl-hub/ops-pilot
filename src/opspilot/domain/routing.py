from __future__ import annotations


def detect_query_type(query: str) -> str:
    normalized = query.lower()
    if any(keyword in query for keyword in ("图谱", "关系", "传导", "链路", "上游", "下游")):
        return "graph_query"
    if any(keyword in query for keyword in ("压力测试", "压力", "冲击", "场景推演", "推演")):
        return "stress_test"
    if any(keyword in query for keyword in ("时间线", "历史变化", "历期", "趋势回放", "走势变化")):
        return "company_timeline"
    if any(keyword in query for keyword in ("评分", "打分", "体检", "运营评估")):
        return "company_scoring"
    if any(keyword in query for keyword in ("对标", "同行", "同业")):
        return "peer_benchmark"
    if any(keyword in query for keyword in ("风险", "机会", "扫描")):
        return "risk_scan"
    if any(keyword in query for keyword in ("研报", "核验", "验证", "观点")):
        return "claim_verification"
    if any(keyword in query for keyword in ("简报", "摘要", "汇报")):
        return "brief_generation"
    if any(keyword in normalized for keyword in ("revenue", "margin", "cash")):
        return "metric_query"
    return "metric_query"
