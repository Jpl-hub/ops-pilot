from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.config import get_settings
from opspilot.domain.rules import evaluate_risk_labels
from opspilot.domain.scoring import score_company
from opspilot.infra.sample_repository import SampleRepository


class ScoringEngineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = get_settings()
        cls.repository = SampleRepository(settings.sample_data_path)
        cls.peers = cls.repository.list_companies(settings.default_period)

    def test_head_company_scores_higher_than_distressed_peer(self) -> None:
        catl = self.repository.get_company("宁德时代", "2024Q3")
        tcl = self.repository.get_company("TCL中环", "2024Q3")
        catl_score = score_company(catl, self.peers)
        tcl_score = score_company(tcl, self.peers)
        self.assertGreater(catl_score["total_score"], tcl_score["total_score"])

    def test_singleton_subindustry_falls_back_to_whole_industry(self) -> None:
        sungrow = self.repository.get_company("阳光电源", "2024Q3")
        sungrow_score = score_company(sungrow, self.peers)
        self.assertEqual(sungrow_score["peer_scope"], "新能源全行业")
        self.assertGreaterEqual(sungrow_score["subindustry_percentile"], 0)
        self.assertLessEqual(sungrow_score["subindustry_percentile"], 100)

    def test_risk_rules_capture_short_debt_pressure(self) -> None:
        goldwind = self.repository.get_company("金风科技", "2024Q3")
        labels = evaluate_risk_labels(goldwind)
        label_codes = {label["code"] for label in labels}
        self.assertIn("R4", label_codes)
        self.assertIn("R7", label_codes)


if __name__ == "__main__":
    unittest.main()
