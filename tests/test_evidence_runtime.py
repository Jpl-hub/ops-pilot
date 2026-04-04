from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.evidence_runtime import build_evidence_detail


class _StubRepository:
    def __init__(self) -> None:
        self._evidence = {
            "official-1": {
                "chunk_id": "official-1",
                "company_name": "测试公司",
                "report_period": "2025Q3",
                "source_title": "测试公司：2025年三季度报告",
                "source_type": "official_statement_page",
                "page": 9,
                "excerpt": "货币资金 12 亿元，短期借款 18 亿元。",
                "fingerprint": "fp-official-1",
                "source_url": "https://example.com/report.pdf",
                "local_path": "data/raw/report.pdf",
            },
            "official-2": {
                "chunk_id": "official-2",
                "company_name": "测试公司",
                "report_period": "2025Q3",
                "source_title": "测试公司：2025年三季度报告",
                "source_type": "official_summary_page",
                "page": 10,
                "excerpt": "经营活动现金流回落。",
                "fingerprint": "fp-official-2",
                "source_url": "https://example.com/report.pdf",
                "local_path": "data/raw/report.pdf",
            },
            "research-1": {
                "chunk_id": "research-1",
                "company_name": "测试公司",
                "report_period": "2025Q3",
                "source_title": "测试公司深度：现金与盈利修复",
                "source_type": "research_report_excerpt",
                "page": 1,
                "excerpt": "我们判断公司现金压力正在缓解。",
                "fingerprint": "fp-research-1",
                "source_url": "https://example.com/research",
                "local_path": "data/raw/research.pdf",
            },
        }
        self._company = {
            "company_name": "测试公司",
            "report_period": "2025Q3",
            "subindustry": "储能",
            "ticker": "000001.SZ",
        }

    def get_evidence(self, chunk_id: str) -> dict | None:
        return self._evidence.get(chunk_id)

    def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
        if company_name != "测试公司":
            return None
        if report_period and report_period != "2025Q3":
            return None
        return dict(self._company)

    def list_company_periods(self, company_name: str) -> list[str]:
        if company_name != "测试公司":
            return []
        return ["2025Q3", "2025H1", "2024FY"]


class _StubService:
    def __init__(self) -> None:
        self.repository = _StubRepository()
        self.verify_calls: list[tuple[str, str | None, str | None]] = []

    def score_company(self, company_name: str, report_period: str | None = None) -> dict:
        return {
            "report_period": report_period or "2025Q3",
            "scorecard": {
                "total_score": 74,
                "grade": "B",
                "risk_labels": [{"code": "R4"}, {"code": "R2"}],
                "opportunity_labels": [{"code": "O2"}],
            },
            "evidence_groups": [
                {
                    "title": "现金压力",
                    "subtitle": "R4 现金承压，需要继续跟踪。",
                    "anchor_terms": ["货币资金", "短期借款"],
                    "items": [
                        self.repository.get_evidence("official-1"),
                        self.repository.get_evidence("official-2"),
                    ],
                }
            ],
        }

    def verify_claim(
        self,
        company_name: str,
        report_period: str | None = None,
        report_title: str | None = None,
    ) -> dict:
        self.verify_calls.append((company_name, report_period, report_title))
        title = report_title or "机构研报：测试公司 2025Q3 观点"
        if report_title and report_title not in {"测试公司深度：现金与盈利修复", "机构研报：测试公司 2025Q3 观点"}:
            raise ValueError("未找到研报")
        evidence_item = (
            self.repository.get_evidence("research-1")
            if report_title == "测试公司深度：现金与盈利修复"
            else self.repository.get_evidence("official-1")
        )
        return {
            "report_meta": {
                "title": title,
                "publish_date": "2025-10-20",
                "source_name": "测试证券",
                "source_url": "https://example.com/research",
                "attachment_url": "https://example.com/research.pdf",
            },
            "available_reports": [
                {
                    "title": title,
                    "rating_text": "买入",
                    "rating_change": "维持",
                    "target_price": 28.5,
                    "forecast_count": 3,
                }
            ],
            "evidence_groups": [
                {
                    "title": "研报观点核验",
                    "subtitle": "核验结果：mismatch",
                    "anchor_terms": ["现金压力"],
                    "items": [evidence_item],
                }
            ],
        }

    def company_document_upgrades(
        self,
        company_name: str,
        report_period: str | None = None,
        *,
        limit: int = 40,
        include_preview: bool = False,
        include_evidence_navigation: bool = True,
    ) -> dict:
        return {
            "items": [
                {
                    "stage": "cell_trace",
                    "status": "ready",
                    "status_label": "已完成",
                    "artifact_summary": "页级结构结果已经回挂当前证据。",
                    "evidence_navigation": {
                        "links": [
                            {
                                "chunk_id": "official-1",
                                "label": "第9页证据",
                                "path": "/evidence/official-1",
                                "query": {"context": "文档升级结果"},
                            },
                            {
                                "chunk_id": "official-2",
                                "label": "第10页证据",
                                "path": "/evidence/official-2",
                                "query": {"context": "文档升级结果"},
                            },
                        ]
                    },
                }
            ]
        }


class EvidenceRuntimeTestCase(unittest.TestCase):
    def test_build_evidence_detail_enriches_official_chunk(self) -> None:
        service = _StubService()

        payload = build_evidence_detail(service, "official-1", user_role="regulator")

        self.assertEqual(payload["source_meta"]["type_label"], "定期报告财务页")
        self.assertEqual(payload["company_context"]["ticker"], "000001.SZ")
        self.assertEqual(payload["company_context"]["score_snapshot"]["grade"], "B")
        self.assertEqual([panel["kind"] for panel in payload["reference_panels"]], ["score", "verify", "document"])
        self.assertEqual(payload["reference_panels"][0]["entries"][0]["links"][0]["path"], "/evidence/official-2")
        self.assertEqual(payload["reference_panels"][1]["route"]["query"]["report_title"], "机构研报：测试公司 2025Q3 观点")
        self.assertEqual(payload["reference_panels"][1]["route"]["query"]["period"], "2025Q3")
        self.assertEqual(payload["reference_panels"][2]["route"]["query"]["role"], "regulator")
        workflow_labels = [item["label"] for item in payload["workflow_links"]]
        self.assertIn("继续协同分析", workflow_labels)
        self.assertIn("查看图谱链路", workflow_labels)
        self.assertIn("返回观点核验", workflow_labels)
        self.assertIn("返回文档复核", workflow_labels)

    def test_build_evidence_detail_keeps_research_report_context(self) -> None:
        service = _StubService()

        payload = build_evidence_detail(service, "research-1", user_role="management")

        self.assertEqual(payload["report_context"]["title"], "测试公司深度：现金与盈利修复")
        self.assertEqual(payload["report_context"]["rating_text"], "买入")
        verify_link = next(item for item in payload["workflow_links"] if item["path"] == "/verify")
        self.assertEqual(verify_link["query"]["period"], "2025Q3")
        self.assertEqual(verify_link["query"]["report_title"], "测试公司深度：现金与盈利修复")
        self.assertIn(("测试公司", "2025Q3", "测试公司深度：现金与盈利修复"), service.verify_calls)

    def test_build_evidence_detail_raises_when_chunk_missing(self) -> None:
        service = _StubService()

        with self.assertRaisesRegex(ValueError, "未找到证据"):
            build_evidence_detail(service, "missing")


if __name__ == "__main__":
    unittest.main()
