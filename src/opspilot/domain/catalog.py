from __future__ import annotations

from dataclasses import dataclass


DIMENSION_WEIGHTS = {
    "增长与扩张": 20.0,
    "盈利与效率": 25.0,
    "现金质量": 20.0,
    "韧性与偿债": 20.0,
    "创新与治理": 15.0,
}


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    code: str
    name: str
    dimension: str
    direction: str


METRICS = [
    MetricDefinition("G1", "营业收入同比", "增长与扩张", "higher"),
    MetricDefinition("G2", "扣非净利润同比", "增长与扩张", "higher"),
    MetricDefinition("G3", "研发费用率", "增长与扩张", "higher"),
    MetricDefinition("P1", "毛利率", "盈利与效率", "higher"),
    MetricDefinition("P2", "净利率", "盈利与效率", "higher"),
    MetricDefinition("P3", "期间费用率", "盈利与效率", "lower"),
    MetricDefinition("P4", "存货周转天数", "盈利与效率", "lower"),
    MetricDefinition("P5", "应收账款周转天数", "盈利与效率", "lower"),
    MetricDefinition("C1", "经营现金流/净利润", "现金质量", "higher"),
    MetricDefinition("C2", "经营现金流/收入", "现金质量", "higher"),
    MetricDefinition("C3", "应收增速-收入增速差", "现金质量", "lower"),
    MetricDefinition("S1", "流动比率", "韧性与偿债", "higher"),
    MetricDefinition("S2", "资产负债率", "韧性与偿债", "lower"),
    MetricDefinition("S3", "利息保障倍数", "韧性与偿债", "higher"),
    MetricDefinition("S4", "现金短债比", "韧性与偿债", "higher"),
    MetricDefinition("I1", "政府补助依赖度", "创新与治理", "lower"),
    MetricDefinition("I2", "审计意见风险", "创新与治理", "lower"),
    MetricDefinition("I3", "处罚/诉讼事件风险", "创新与治理", "lower"),
    MetricDefinition("I4", "重大减值/关联交易风险", "创新与治理", "lower"),
]

METRIC_BY_CODE = {metric.code: metric for metric in METRICS}
