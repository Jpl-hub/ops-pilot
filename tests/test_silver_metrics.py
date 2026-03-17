from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.silver_metrics import (
    apply_period_selection,
    apply_unit_scale,
    detect_unit_scale,
    derive_metric_codes,
    extract_balance_field,
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
            "revenue": {"current": 100.0, "previous": 80.0, "change_pct": 25.0, "tokens": []},
            "net_profit": {"current": 12.0, "previous": 8.0, "change_pct": 50.0, "tokens": []},
            "deducted_net_profit": {
                "current": 10.0,
                "previous": 9.0,
                "change_pct": 11.11,
                "tokens": [],
            },
            "operating_cash_flow": {
                "current": 15.0,
                "previous": 5.0,
                "change_pct": 200.0,
                "tokens": [],
            },
            "operating_revenue": {"current": 100.0, "previous": 80.0, "change_pct": None, "tokens": []},
            "operating_cost": {"current": 70.0, "previous": 60.0, "change_pct": None, "tokens": []},
            "sales_expense": {"current": 5.0, "previous": 4.0, "change_pct": None, "tokens": []},
            "admin_expense": {"current": 3.0, "previous": 2.0, "change_pct": None, "tokens": []},
            "rd_expense": {"current": 4.0, "previous": 3.0, "change_pct": None, "tokens": []},
            "finance_expense": {"current": 1.0, "previous": 0.5, "change_pct": None, "tokens": []},
            "accounts_receivable": {
                "current": 30.0,
                "previous": 20.0,
                "change_pct": None,
                "tokens": [],
            },
            "inventory": {"current": 40.0, "previous": 20.0, "change_pct": None, "tokens": []},
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
                "current": 80.0,
                "previous": 20.0,
                "change_pct": 30.0,
                "tokens": ["80.0", "20.0%", "200.0", "40.0%"],
            }
        }
        adjusted = apply_period_selection(row_values, "2025Q3")
        self.assertEqual(adjusted["revenue"]["current"], 200.0)
        self.assertIsNone(adjusted["revenue"]["previous"])
        self.assertEqual(adjusted["revenue"]["change_pct"], 40.0)

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

    def test_infer_report_period_supports_standard_report_types(self) -> None:
        self.assertEqual(infer_report_period("2025年半年度报告", "2025-08-23"), "2025H1")
        self.assertEqual(infer_report_period("宁德时代：2025年年度报告", "2026-03-10"), "2025FY")


if __name__ == "__main__":
    unittest.main()
