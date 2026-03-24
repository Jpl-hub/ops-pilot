from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.silver_metrics import (
    apply_period_selection,
    apply_unit_scale,
    build_field_evidence,
    detect_unit_scale,
    derive_metric_codes,
    enrich_comparable_metrics,
    extract_balance_field,
    extract_event_metrics,
    extract_profit_statement_values,
    infer_report_period,
    parse_value_segment,
    select_summary_page,
)


class SilverMetricsTestCase(unittest.TestCase):
    def test_parse_value_segment_handles_half_year_row(self) -> None:
        segment = "32,813,146,398.68 38,528,702,860.54 38,528,702,860.54 -14.83"
        parsed = parse_value_segment(segment)
        self.assertEqual(parsed["current"], 32813146398.68)
        self.assertEqual(parsed["previous"], 38528702860.54)
        self.assertEqual(parsed["change_pct"], -14.83)

    def test_derive_metric_codes_builds_core_scoring_metrics(self) -> None:
        row_values = {
            "revenue": {
                "current": 100000000.0,
                "previous": 80000000.0,
                "change_pct": 25.0,
                "tokens": [],
            },
            "profit_total": {
                "current": 25000000.0,
                "previous": 20000000.0,
                "change_pct": 25.0,
                "tokens": [],
            },
            "net_profit": {
                "current": 12000000.0,
                "previous": 8000000.0,
                "change_pct": 50.0,
                "tokens": [],
            },
            "deducted_net_profit": {
                "current": 10000000.0,
                "previous": 9000000.0,
                "change_pct": 11.11,
                "tokens": [],
            },
            "operating_cash_flow": {
                "current": 15000000.0,
                "previous": 5000000.0,
                "change_pct": 200.0,
                "tokens": [],
            },
            "operating_revenue": {
                "current": 100000000.0,
                "previous": 80000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "operating_cost": {
                "current": 70000000.0,
                "previous": 60000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "sales_expense": {
                "current": 5000000.0,
                "previous": 4000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "admin_expense": {
                "current": 3000000.0,
                "previous": 2000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "rd_expense": {
                "current": 4000000.0,
                "previous": 3000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "finance_expense": {
                "current": 1000000.0,
                "previous": 500000.0,
                "change_pct": None,
                "tokens": [],
            },
            "interest_expense": {
                "current": 5000000.0,
                "previous": 4000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "accounts_receivable": {
                "current": 30000000.0,
                "previous": 20000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "inventory": {
                "current": 40000000.0,
                "previous": 20000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "_meta": {"report_period": "2025H1"},
        }
        derived = derive_metric_codes(row_values)
        self.assertEqual(derived["G1"], 25.0)
        self.assertEqual(derived["G2"], 11.11)
        self.assertEqual(derived["G3"], 4.0)
        self.assertEqual(derived["P1"], 30.0)
        self.assertEqual(derived["P2"], 12.0)
        self.assertEqual(derived["P3"], 13.0)
        self.assertEqual(derived["P4"], 77.57)
        self.assertEqual(derived["P5"], 45.25)
        self.assertEqual(derived["C1"], 1.25)
        self.assertEqual(derived["C2"], 0.15)
        self.assertEqual(derived["S3"], 6.0)

    def test_select_summary_page_prefers_financial_summary(self) -> None:
        pages = [
            {"page": 1, "blocks": [{"text": "封面与目录"}]},
            {
                "page": 8,
                "blocks": [
                    {
                        "text": (
                            "营业收入 100 80 25% 归属于上市公司股东的净利润 12 8 50% "
                            "经营活动产生的现金流量净额 15 5 200% 总资产 1000 900 11% "
                            "归属于上市公司股东的净资产 500 450 11%"
                        )
                    }
                ],
            },
        ]
        summary_page = select_summary_page(pages, max_pages=10)
        self.assertEqual(summary_page["page"], 8)

    def test_apply_period_selection_uses_cumulative_values_for_q3(self) -> None:
        row_values = {
            "revenue": {
                "current": 80000000.0,
                "previous": 20000000.0,
                "change_pct": 30.0,
                "tokens": ["80000000.0", "20.0%", "200000000.0", "40.0%"],
            }
        }
        adjusted = apply_period_selection(row_values, "2025Q3")
        self.assertEqual(adjusted["revenue"]["current"], 200000000.0)
        self.assertIsNone(adjusted["revenue"]["previous"])
        self.assertEqual(adjusted["revenue"]["change_pct"], 40.0)

    def test_derive_metric_codes_rejects_implausible_revenue_outputs(self) -> None:
        row_values = {
            "revenue": {"current": -19.39, "previous": 80.0, "change_pct": -830.0, "tokens": []},
            "operating_cash_flow": {"current": 15.0, "previous": 5.0, "change_pct": 200.0, "tokens": []},
            "net_profit": {"current": 12.0, "previous": 8.0, "change_pct": 50.0, "tokens": []},
        }
        derived = derive_metric_codes(row_values)
        self.assertNotIn("RAW_REVENUE", derived)
        self.assertNotIn("G1", derived)
        self.assertNotIn("C2", derived)
        self.assertNotIn("P2", derived)

    def test_detect_and_apply_unit_scale(self) -> None:
        unit_text, unit_scale = detect_unit_scale("单位：千元 项目 2025年 2024年")
        self.assertEqual(unit_text, "单位：千元")
        scaled = apply_unit_scale(
            {
                "revenue": {
                    "current": 423701834.0,
                    "previous": 362012554.0,
                    "change_pct": 17.04,
                    "tokens": [],
                }
            },
            unit_scale,
        )
        self.assertEqual(scaled["revenue"]["current"], 423701834000.0)

    def test_extract_balance_field_skips_note_numbers(self) -> None:
        text = "一年内到期的非流动负债 七、43 1,508,150,285.79 1,902,000,262.18 其他流动负债"
        extracted = extract_balance_field(text, "一年内到期的非流动负债")
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["current"], 1508150285.79)
        self.assertEqual(extracted["previous"], 1902000262.18)

    def test_profit_statement_uses_fallback_unit_scale(self) -> None:
        pages = [
            {
                "page": 9,
                "blocks": [
                    {
                        "text": (
                            "合并利润表 二、营业总成本 231,962,490 215,471,465 "
                            "其中：营业成本 211,427,147 194,352,589 "
                            "销售费用 2,408,522 2,608,019 管理费用 8,231,715 6,774,456 "
                            "研发费用 15,067,826 13,073,136 财务费用 -7,015,786 -2,894,209"
                        )
                    }
                ],
            }
        ]
        values = extract_profit_statement_values(
            pages,
            fallback_unit_text="（千元）",
            fallback_unit_scale=1000.0,
        )
        self.assertEqual(values["operating_cost"]["current"], 211427147000.0)
        self.assertEqual(values["rd_expense"]["current"], 15067826000.0)

    def test_profit_statement_scans_following_page_for_profit_total(self) -> None:
        pages = [
            {
                "page": 9,
                "blocks": [{"text": "合并利润表 营业总成本 231,962,490 215,471,465 销售费用 2,408,522 2,608,019"}],
            },
            {
                "page": 10,
                "blocks": [
                    {
                        "text": (
                            "加：营业外收入 3,083,971.84 18,392,787.85 减：营业外支出 36,335,941.15 9,826,527.22 "
                            "四、利润总额（亏损总额以“－”号填列） -2,289,939,677.23 -971,932,511.26"
                        )
                    }
                ],
            },
        ]
        values = extract_profit_statement_values(
            pages,
            fallback_unit_text="单位：元",
            fallback_unit_scale=1.0,
        )
        self.assertEqual(values["profit_total"]["current"], -2289939677.23)

    def test_build_field_evidence_uses_statement_page_excerpt(self) -> None:
        pages = [
            {
                "page": 12,
                "blocks": [{"text": "四、利润总额（亏损总额以“－”号填列） 3,704,473,265.70 2,363,917,456.64"}],
            }
        ]
        row_values = {
            "profit_total": {
                "current": 3704473265.70,
                "previous": 2363917456.64,
                "change_pct": None,
                "tokens": [],
                "page": 12,
            }
        }
        field_evidence = build_field_evidence(pages, row_values, report_id="demo")
        self.assertEqual(field_evidence["profit_total"]["chunk_id"], "demo-field-profit_total-page-012")
        self.assertIn("利润总额", field_evidence["profit_total"]["excerpt"])

    def test_derive_metric_codes_builds_balance_sheet_ratios(self) -> None:
        row_values = {
            "assets": {"current": 1000.0, "previous": 900.0, "change_pct": 11.0, "tokens": []},
            "total_liabilities": {
                "current": 600.0,
                "previous": 550.0,
                "change_pct": None,
                "tokens": [],
            },
            "current_assets": {
                "current": 400.0,
                "previous": 380.0,
                "change_pct": None,
                "tokens": [],
            },
            "current_liabilities": {
                "current": 200.0,
                "previous": 210.0,
                "change_pct": None,
                "tokens": [],
            },
            "cash_funds": {"current": 180.0, "previous": 150.0, "change_pct": None, "tokens": []},
            "short_term_borrowings": {
                "current": 50.0,
                "previous": 40.0,
                "change_pct": None,
                "tokens": [],
            },
            "due_within_one_year_noncurrent_liabilities": {
                "current": 10.0,
                "previous": 12.0,
                "change_pct": None,
                "tokens": [],
            },
        }
        derived = derive_metric_codes(row_values)
        self.assertEqual(derived["S1"], 2.0)
        self.assertEqual(derived["S2"], 60.0)
        self.assertEqual(derived["S4"], 3.0)

    def test_extract_event_metrics_builds_i_metrics(self) -> None:
        pages = [
            {
                "page": 9,
                "blocks": [
                    {
                        "text": (
                            "九、非经常性损益项目和金额 计入当期损益的政府补助 "
                            "120,000,000.00 合计 300,000,000.00"
                        )
                    }
                ],
            },
            {
                "page": 20,
                "blocks": [
                    {
                        "text": (
                            "四、半年报审计情况 □适用√不适用 "
                            "七、重大诉讼、仲裁事项 □本报告期公司有重大诉讼、仲裁事项√本报告期公司无重大诉讼、仲裁事项 "
                            "八、上市公司及其董事、高级管理人员涉嫌违法违规、受到处罚及整改情况 □适用√不适用"
                        )
                    }
                ],
            },
            {
                "page": 31,
                "blocks": [
                    {
                        "text": (
                            "合并利润表 信用减值损失（损失以“-”号填列） -20,000,000.00 "
                            "资产减值损失（损失以“-”号填列） -50,000,000.00"
                        )
                    }
                ],
            },
        ]
        row_values = {
            "net_profit": {
                "current": 1000000000.0,
                "previous": 900000000.0,
                "change_pct": 11.0,
                "tokens": [],
            },
            "deducted_net_profit": {
                "current": 800000000.0,
                "previous": 750000000.0,
                "change_pct": 6.67,
                "tokens": [],
            },
            "operating_revenue": {
                "current": 10000000000.0,
                "previous": 9000000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "credit_impairment_loss": {
                "current": -20000000.0,
                "previous": -10000000.0,
                "change_pct": None,
                "tokens": [],
            },
            "asset_impairment_loss": {
                "current": -400000000.0,
                "previous": -200000000.0,
                "change_pct": None,
                "tokens": [],
            },
        }
        metrics, metric_evidence, evidence_rows = extract_event_metrics(
            pages,
            row_values,
            report_id="demo-report",
            report_period="2025H1",
        )
        self.assertEqual(metrics["I1"], 0.12)
        self.assertEqual(metrics["I2"], 0.0)
        self.assertEqual(metrics["I3"], 0.0)
        self.assertEqual(metrics["I4"], 0.042)
        self.assertEqual(metric_evidence["I1"], ["demo-report-event-i1-page-009"])
        self.assertEqual(metric_evidence["I4"], ["demo-report-event-i4-page-031"])
        self.assertEqual(len(evidence_rows), 4)

    def test_extract_event_metrics_detects_positive_litigation_signal(self) -> None:
        pages = [
            {
                "page": 18,
                "blocks": [
                    {
                        "text": (
                            "八、诉讼事项 重大诉讼仲裁事项 公司存在重大诉讼、仲裁事项，"
                            "报告期内收到行政处罚决定书。"
                        )
                    }
                ],
            }
        ]
        metrics, metric_evidence, evidence_rows = extract_event_metrics(
            pages,
            {},
            report_id="risk-report",
            report_period="2025H1",
        )
        self.assertEqual(metrics["I3"], 1.0)
        self.assertEqual(metric_evidence["I3"], ["risk-report-event-i3-page-018"])
        self.assertEqual(evidence_rows[0]["metric_code"], "I3")

    def test_extract_event_metrics_detects_audit_signal_beyond_page_40(self) -> None:
        pages = [
            {"page": 1, "blocks": [{"text": "封面"}]},
            {
                "page": 45,
                "blocks": [
                    {
                        "text": (
                            "四、聘任、解聘会计师事务所情况 "
                            "半年度财务报告是否已经审计 □是否 "
                            "公司半年度报告未经审计。"
                        )
                    }
                ],
            },
        ]
        metrics, metric_evidence, evidence_rows = extract_event_metrics(
            pages,
            {},
            report_id="late-audit-report",
            report_period="2025H1",
        )
        self.assertEqual(metrics["I2"], 0.0)
        self.assertEqual(metric_evidence["I2"], ["late-audit-report-event-i2-page-045"])
        self.assertEqual(evidence_rows[0]["page"], 45)

    def test_enrich_comparable_metrics_builds_c3_with_prior_year_same_period(self) -> None:
        silver_rows = [
            {
                "company_name": "测试公司",
                "report_period": "2024Q3",
                "derived_metrics": {
                    "RAW_ACCOUNTS_RECEIVABLE": 80.0,
                    "G1": 10.0,
                },
            },
            {
                "company_name": "测试公司",
                "report_period": "2025Q3",
                "derived_metrics": {
                    "RAW_ACCOUNTS_RECEIVABLE": 100.0,
                    "G1": 15.0,
                },
            },
        ]
        enrich_comparable_metrics(silver_rows)
        self.assertEqual(silver_rows[1]["derived_metrics"]["RAW_ACCOUNTS_RECEIVABLE_YOY"], 25.0)
        self.assertEqual(silver_rows[1]["derived_metrics"]["C3"], 10.0)

    def test_infer_report_period_supports_standard_report_types(self) -> None:
        self.assertEqual(infer_report_period("2025年半年度报告", "2025-08-23"), "2025H1")
        self.assertEqual(infer_report_period("宁德时代：2025年年度报告", "2026-03-10"), "2025FY")


if __name__ == "__main__":
    unittest.main()
