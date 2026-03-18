from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.official_clients import (
    _hex_xor,
    _unsbox,
    build_periodic_filename,
    CompanyProfile,
    detect_periodic_report_type,
    EastmoneyResearchClient,
    extract_report_year,
    is_periodic_report_title,
    sanitize_filename,
    select_periodic_reports,
    ReportRecord,
)


class OfficialClientHelpersTestCase(unittest.TestCase):
    def test_periodic_report_title_detection(self) -> None:
        self.assertTrue(is_periodic_report_title("宁德时代：2025年年度报告"))
        self.assertTrue(is_periodic_report_title("阳光电源：2025年三季度报告摘要"))
        self.assertTrue(is_periodic_report_title("隆基绿能：2025年第三季度报告"))
        self.assertTrue(is_periodic_report_title("通威股份有限公司2025年第三季度报告"))
        self.assertFalse(is_periodic_report_title("关于提供担保的进展公告"))
        self.assertFalse(is_periodic_report_title("阳光电源：关于2024年年度报告（英文简版）的自愿性披露公告"))
        self.assertFalse(is_periodic_report_title("中国国际金融股份有限公司关于隆基绿能科技股份有限公司2023年度持续督导年度报告书"))

    def test_periodic_report_type_detection(self) -> None:
        self.assertEqual(detect_periodic_report_type("2025年年度报告"), "年度报告")
        self.assertEqual(detect_periodic_report_type("2025年半年度报告摘要"), "半年度报告")
        self.assertEqual(detect_periodic_report_type("通威股份有限公司2025年第三季度报告"), "第三季度报告")
        self.assertEqual(extract_report_year("宁德时代：2025年年度报告", "2026-03-10"), 2025)

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

    def test_sse_cookie_helpers(self) -> None:
        arg1 = "FC174F8B2279BD57C009CF29104BBA521B956FC4"
        unsboxed = _unsbox(arg1)
        cookie = _hex_xor(unsboxed, "3000176000856006061501533003690027800375")
        self.assertEqual(len(cookie), 40)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in cookie))

    def test_select_periodic_reports_prefers_revision_and_deduplicates_period(self) -> None:
        reports = [
            ReportRecord(
                source="SSE",
                company_name="隆基绿能",
                security_code="601012",
                exchange="SSE",
                subindustry="光伏",
                title="2024年年度报告",
                publish_date="2025-04-29",
                report_type="年度报告",
                is_summary=False,
                source_url="https://example.com/base.pdf",
            ),
            ReportRecord(
                source="SSE",
                company_name="隆基绿能",
                security_code="601012",
                exchange="SSE",
                subindustry="光伏",
                title="2024年年度报告（修订版）",
                publish_date="2025-05-07",
                report_type="年度报告",
                is_summary=False,
                source_url="https://example.com/revised.pdf",
            ),
            ReportRecord(
                source="SZSE",
                company_name="阳光电源",
                security_code="300274",
                exchange="SZSE",
                subindustry="光伏",
                title="阳光电源：关于2024年年度报告（英文简版）的自愿性披露公告",
                publish_date="2025-06-13",
                report_type="年度报告",
                is_summary=False,
                source_url="https://example.com/notice.pdf",
            ),
        ]
        selected = select_periodic_reports(reports, max_items=7)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].title, "2024年年度报告（修订版）")

    def test_list_industry_reports_filters_tracked_industries(self) -> None:
        class StubResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": [
                        {
                            "title": "光伏设备行业周报",
                            "publishDate": "2025-11-01 00:00:00.000",
                            "infoCode": "AP1",
                            "industryName": "光伏设备",
                        },
                        {
                            "title": "电池行业深度",
                            "publishDate": "2025-11-02 00:00:00.000",
                            "infoCode": "AP2",
                            "industryName": "电池",
                        },
                        {
                            "title": "医药行业周报",
                            "publishDate": "2025-11-03 00:00:00.000",
                            "infoCode": "AP3",
                            "industryName": "化学制药",
                        },
                    ]
                }

        class StubSession:
            def __init__(self) -> None:
                self.trust_env = False
                self.headers = {}

            def request(self, method: str, url: str, timeout: int = 30, **kwargs):
                return StubResponse()

        client = EastmoneyResearchClient(session=StubSession())

        reports = client.list_industry_reports(
            since_date="2024-01-01",
            max_items_per_industry=1,
            tracked_industry_names=("光伏设备", "电池"),
        )

        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0].industry_name, "光伏设备")
        self.assertEqual(reports[1].industry_name, "电池")
        self.assertTrue(all(report.source == "EASTMONEY_INDUSTRY" for report in reports))


if __name__ == "__main__":
    unittest.main()
