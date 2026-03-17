from __future__ import annotations

from typing import Any


RISK_DEFINITIONS = {
    "R1": "利润现金背离",
    "R2": "应收扩张过快",
    "R3": "存货积压",
    "R4": "短债压力",
    "R5": "高补助依赖",
    "R6": "审计意见异常",
    "R7": "重大处罚/诉讼",
    "R8": "重大减值",
}

OPPORTUNITY_DEFINITIONS = {
    "O1": "毛利修复",
    "O2": "现金质量改善",
    "O3": "去库存改善",
    "O4": "偿债修复",
    "O5": "研发兑现信号",
}


def evaluate_risk_labels(company: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = company["metrics"]
    labels: list[dict[str, Any]] = []
    c1 = metrics.get("C1")
    g2 = metrics.get("G2")
    c3 = metrics.get("C3")
    p4 = metrics.get("P4")
    s4 = metrics.get("S4")
    s1 = metrics.get("S1")
    i1 = metrics.get("I1")
    i2 = metrics.get("I2")
    i3 = metrics.get("I3")
    i4 = metrics.get("I4")
    if c1 is not None and g2 is not None and c1 < 0.8 and g2 > 0:
        labels.append(_label(company, "R1", [c1, g2]))
    if c3 is not None and c3 > 8:
        labels.append(_label(company, "R2", [c3]))
    if p4 is not None and p4 > 120:
        labels.append(_label(company, "R3", [p4]))
    if (s4 is not None and s4 < 0.8) or (s1 is not None and s1 < 1.2):
        labels.append(_label(company, "R4", [value for value in [s4, s1] if value is not None]))
    if i1 is not None and i1 > 0.06:
        labels.append(_label(company, "R5", [i1]))
    if i2 is not None and i2 > 0:
        labels.append(_label(company, "R6", [i2]))
    if i3 is not None and i3 > 0:
        labels.append(_label(company, "R7", [i3]))
    if i4 is not None and i4 > 0.03:
        labels.append(_label(company, "R8", [i4]))
    return labels


def evaluate_opportunity_labels(company: dict[str, Any]) -> list[dict[str, Any]]:
    trends = company.get("trends", {})
    labels: list[dict[str, Any]] = []
    if trends.get("P1_delta", 0) > 1.5:
        labels.append(_label(company, "O1", [trends["P1_delta"]]))
    if trends.get("C1_delta", 0) > 0.12:
        labels.append(_label(company, "O2", [trends["C1_delta"]]))
    if trends.get("P4_delta", 0) < -5:
        labels.append(_label(company, "O3", [trends["P4_delta"]]))
    if trends.get("S4_delta", 0) > 0.1:
        labels.append(_label(company, "O4", [trends["S4_delta"]]))
    if trends.get("G3_delta", 0) > 0.5:
        labels.append(_label(company, "O5", [trends["G3_delta"]]))
    return labels


def _label(company: dict[str, Any], code: str, values: list[float]) -> dict[str, Any]:
    is_risk = code.startswith("R")
    definitions = RISK_DEFINITIONS if is_risk else OPPORTUNITY_DEFINITIONS
    return {
        "code": code,
        "name": definitions[code],
        "report_period": company["report_period"],
        "evidence_refs": company.get("label_evidence", {}).get(code, []),
        "signal_values": values,
    }
