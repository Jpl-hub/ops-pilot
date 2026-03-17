from __future__ import annotations

from collections import defaultdict
from typing import Any

from opspilot.domain.catalog import DIMENSION_WEIGHTS, METRICS, METRIC_BY_CODE


def percentile_score(values: list[float], value: float, direction: str) -> float:
    if not values:
        return 50.0
    unique = sorted(set(values))
    if len(unique) == 1:
        return 50.0
    if direction == "higher":
        rank = sum(1 for item in values if item <= value)
    else:
        rank = sum(1 for item in values if item >= value)
    return round(100.0 * rank / len(values), 2)


def _peer_group(company: dict[str, Any], peers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    same_subindustry = [
        peer
        for peer in peers
        if peer["report_period"] == company["report_period"]
        and peer["subindustry"] == company["subindustry"]
    ]
    if len(same_subindustry) >= 2:
        return same_subindustry, False
    return [peer for peer in peers if peer["report_period"] == company["report_period"]], True


def score_company(company: dict[str, Any], peers: list[dict[str, Any]]) -> dict[str, Any]:
    peer_group, used_fallback = _peer_group(company, peers)
    dimension_scores: dict[str, list[float]] = defaultdict(list)
    metric_scores: list[dict[str, Any]] = []

    for metric in METRICS:
        current_value = company["metrics"].get(metric.code)
        if current_value is None:
            continue
        values = [
            peer["metrics"][metric.code]
            for peer in peer_group
            if peer["metrics"].get(metric.code) is not None
        ]
        score = percentile_score(values, current_value, metric.direction)
        dimension_scores[metric.dimension].append(score)
        metric_scores.append(
            {
                "code": metric.code,
                "name": metric.name,
                "dimension": metric.dimension,
                "value": current_value,
                "score": score,
            }
        )

    dimension_rollup: dict[str, float] = {}
    total_score = 0.0
    available_weight = 0.0
    for dimension, weight in DIMENSION_WEIGHTS.items():
        scores = dimension_scores.get(dimension, [])
        if not scores:
            continue
        dim_score = round(sum(scores) / len(scores), 2)
        dimension_rollup[dimension] = dim_score
        available_weight += weight
        total_score += dim_score * weight

    if available_weight > 0:
        total_score = total_score / available_weight
    else:
        total_score = 0.0

    metric_scores.sort(key=lambda item: item["score"], reverse=True)
    percentile = round(
        sum(
            1
            for peer in peer_group
            if _average_metric_score(peer["metrics"], peer_group) <= total_score
        )
        / max(len(peer_group), 1)
        * 100.0,
        2,
    )

    return {
        "total_score": round(total_score, 2),
        "grade": grade_from_score(total_score),
        "subindustry_percentile": percentile,
        "dimension_scores": dimension_rollup,
        "strengths": metric_scores[:3],
        "weaknesses": list(reversed(metric_scores[-3:])),
        "drivers": _select_drivers(metric_scores),
        "metric_scores": metric_scores,
        "peer_group_size": len(peer_group),
        "peer_scope": "新能源全行业" if used_fallback else company["subindustry"],
    }


def _average_metric_score(metrics: dict[str, float], peers: list[dict[str, Any]]) -> float:
    scores = []
    for metric in METRICS:
        current_value = metrics.get(metric.code)
        if current_value is None:
            continue
        values = [
            peer["metrics"][metric.code]
            for peer in peers
            if peer["metrics"].get(metric.code) is not None
        ]
        scores.append(percentile_score(values, current_value, metric.direction))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _select_drivers(metric_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimension_counts: dict[str, int] = defaultdict(int)
    drivers: list[dict[str, Any]] = []
    for metric in metric_scores:
        dimension = METRIC_BY_CODE[metric["code"]].dimension
        if dimension_counts[dimension] >= 1:
            continue
        dimension_counts[dimension] += 1
        drivers.append(metric)
        if len(drivers) == 3:
            break
    return drivers


def grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"
