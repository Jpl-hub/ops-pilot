from __future__ import annotations


def detect_query_type(query: str) -> str:
    normalized = query.lower()
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
