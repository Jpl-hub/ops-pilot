from __future__ import annotations

import unittest

from opspilot.ingest.official_clients import (
    build_periodic_filename,
    detect_periodic_report_type,
    is_periodic_report_title,
    sanitize_filename,
    ReportRecord,
)


class OfficialClientHelpersTestCase(unittest.TestCase):
    def test_periodic_report_title_detection(self) -> None:
        self.assertTrue(is_periodic_report_title("宁德时代：2025年年度报告"))
        self.assertTrue(is_periodic_report_title("阳光电源：2025年三季度报告摘要"))
        self.assertFalse(is_periodic_report_title("关于提供担保的进展公告"))

    def test_periodic_report_type_detection(self) -> None:
        self.assertEqual(detect_periodic_report_type("2025年年度报告"), "年度报告")
        self.assertEqual(detect_periodic_report_type("2025年半年度报告摘要"), "半年度报告")

    def test_filename_sanitizer(self) -> None:
        self.assertEqual(sanitize_filename('2025/03/10:宁德时代"年报"'), "2025_03_10_宁德时代_年报")

    def test_build_periodic_filename(self) -> None:
        report = ReportRecord(
            source="SZSE",
            company_name="宁德时代",
            security_code="300750",
            exchange="SZSE",
            subindustry="锂电池与电池材料",
            title="宁德时代：2025年年度报告",
            publish_date="2026-03-10",
            report_type="年度报告",
            is_summary=False,
            source_url="https://example.com/report.pdf",
        )
        filename = build_periodic_filename(report)
        self.assertTrue(filename.endswith(".pdf"))
        self.assertIn("300750", filename)


if __name__ == "__main__":
    unittest.main()
