from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.services import _build_evidence_groups, _build_label_cards


class ServicesTestCase(unittest.TestCase):
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
