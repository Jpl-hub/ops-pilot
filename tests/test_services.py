from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.services import OpsPilotService, _build_evidence_groups, _build_label_cards


class ServicesTestCase(unittest.TestCase):
    def test_service_falls_back_to_latest_company_period(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                if report_period in (None, "2024FY"):
                    return {
                        "company_name": "测试公司",
                        "report_period": "2024FY",
                        "subindustry": "储能",
                        "metrics": {"G1": 12.0, "P2": 8.0},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period == "2024FY":
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2024FY",
                            "subindustry": "储能",
                            "metrics": {"G1": 12.0, "P2": 8.0},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                        {
                            "company_name": "对标公司",
                            "report_period": "2024FY",
                            "subindustry": "储能",
                            "metrics": {"G1": 10.0, "P2": 7.0},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                return []

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
                return "测试公司" if "测试公司" in query else None

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0

        service = OpsPilotService(StubRepository(), StubSettings())
        payload = service.score_company("测试公司")

        self.assertEqual(payload["company_name"], "测试公司")
        self.assertEqual(payload["report_period"], "2024FY")

    def test_build_label_cards_links_formula_metrics_and_evidence(self) -> None:
        company = {
            "metrics": {
                "C3": 27.43,
                "P4": 135.2,
                "I1": 0.0821,
            }
        }
        risks = [
            {
                "code": "R2",
                "name": "应收扩张过快",
                "signal_values": [27.43],
                "evidence_refs": ["c3-evidence"],
            },
            {
                "code": "R5",
                "name": "高补助依赖",
                "signal_values": [0.0821],
                "evidence_refs": ["i1-evidence"],
            },
        ]
        formula_cards = [
            {
                "metric_code": "C3",
                "title": "应收增速-收入增速差",
                "formula": "应收账款同比 - 营业收入同比",
                "value": 27.43,
                "lines": [],
                "evidence_refs": ["c3-evidence"],
            }
        ]

        cards = _build_label_cards(company, risks, [], formula_cards)

        self.assertEqual(cards[0]["code"], "R2")
        self.assertEqual(cards[0]["metrics"][0]["metric_code"], "C3")
        self.assertEqual(cards[0]["formula_metric_codes"], ["C3"])
        self.assertEqual(cards[0]["evidence_refs"], ["c3-evidence"])
        self.assertEqual(cards[0]["anchor_terms"], ["应收账款", "营业收入"])

        self.assertEqual(cards[1]["code"], "R5")
        self.assertEqual(cards[1]["metrics"][0]["metric_code"], "I1")
        self.assertEqual(cards[1]["formula_metric_codes"], [])
        self.assertEqual(cards[1]["evidence_refs"], ["i1-evidence"])
        self.assertEqual(cards[1]["anchor_terms"], ["政府补助"])

    def test_build_evidence_groups_prioritizes_label_and_formula_sections(self) -> None:
        label_cards = [
            {
                "code": "R2",
                "name": "应收扩张过快",
                "kind": "risk",
                "signal_values": [27.43],
                "evidence_refs": ["c3-evidence"],
                "metrics": [],
                "formula_metric_codes": ["C3"],
                "anchor_terms": ["应收账款", "营业收入"],
            }
        ]
        formula_cards = [
            {
                "metric_code": "C3",
                "title": "应收增速-收入增速差",
                "formula": "应收账款同比 - 营业收入同比",
                "value": 27.43,
                "lines": [],
                "evidence_refs": ["c3-evidence", "revenue-evidence"],
                "anchor_terms": ["应收账款", "营业收入"],
            }
        ]
        evidence = [
            {"chunk_id": "c3-evidence", "source_title": "报告A", "page": 8, "excerpt": "应收账款 122 亿"},
            {"chunk_id": "revenue-evidence", "source_title": "报告A", "page": 2, "excerpt": "营业收入同比 -13.10%"},
        ]

        groups = _build_evidence_groups(label_cards, formula_cards, evidence)

        self.assertEqual(groups[0]["code"], "R2")
        self.assertEqual([item["chunk_id"] for item in groups[0]["items"]], ["c3-evidence"])
        self.assertEqual(groups[0]["anchor_terms"], ["应收账款", "营业收入"])
        self.assertEqual(groups[1]["code"], "C3")
        self.assertEqual(
            [item["chunk_id"] for item in groups[1]["items"]],
            ["c3-evidence", "revenue-evidence"],
        )
        self.assertEqual(groups[1]["anchor_terms"], ["应收账款", "营业收入"])
        self.assertEqual(groups[2]["code"], "ALL")


if __name__ == "__main__":
    unittest.main()
