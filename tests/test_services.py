from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.services import (
    OpsPilotService,
    _build_claim_cards,
    _build_evidence_groups,
    _build_forecast_cards,
    _build_label_cards,
    _extract_research_body,
    _extract_research_payload,
    _infer_report_period_from_text,
    _select_research_report,
)


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
                        "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period is None:
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2024FY",
                            "subindustry": "储能",
                            "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                        {
                            "company_name": "测试公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": 9.0, "P2": 6.0},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                if report_period == "2024FY":
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2024FY",
                            "subindustry": "储能",
                            "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                        {
                            "company_name": "对标公司",
                            "report_period": "2024FY",
                            "subindustry": "储能",
                            "metrics": {"G1": 10.0, "P2": 7.0, "C3": 2.0, "S4": 1.15, "S1": 1.48},
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
        self.assertEqual(payload["available_periods"], ["2025Q3", "2024FY"])
        self.assertTrue(payload["action_cards"])
        self.assertEqual(payload["action_cards"][0]["priority"], "P1")

    def test_company_timeline_returns_period_snapshots(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                records = {
                    "2025Q3": {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 12.0, "G2": 8.0, "C1": 1.1, "C3": 10.5, "S1": 1.2, "S4": 1.1},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    "2025H1": {
                        "company_name": "测试公司",
                        "report_period": "2025H1",
                        "subindustry": "储能",
                        "metrics": {"G1": 9.0, "G2": 6.0, "C1": 0.8, "C3": 2.0, "S1": 1.3, "S4": 1.25},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                }
                return records.get(report_period or "2025Q3")

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period == "2025Q3":
                    return [
                        self.get_company("测试公司", "2025Q3"),
                        {
                            "company_name": "对标公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": 10.0, "G2": 7.5, "C1": 1.3, "C3": 1.0, "S1": 1.4, "S4": 1.35},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                if report_period == "2025H1":
                    return [
                        self.get_company("测试公司", "2025H1"),
                        {
                            "company_name": "对标公司",
                            "report_period": "2025H1",
                            "subindustry": "储能",
                            "metrics": {"G1": 8.0, "G2": 5.0, "C1": 1.25, "C3": 1.5, "S1": 1.45, "S4": 1.4},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                return [self.get_company("测试公司", "2025Q3"), self.get_company("测试公司", "2025H1")]

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3", "2025H1"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0

        payload = OpsPilotService(StubRepository(), StubSettings()).company_timeline("测试公司")

        self.assertEqual(payload["company_name"], "测试公司")
        self.assertEqual(payload["key_numbers"][0]["value"], 2)
        self.assertEqual(payload["snapshots"][0]["report_period"], "2025Q3")
        self.assertIsNotNone(payload["snapshots"][1]["score_delta"])
        self.assertEqual(payload["charts"][0]["title"], "报期总分变化")

    def test_chat_turn_returns_role_driven_workspace_payload(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                return {
                    "company_name": "测试公司",
                    "report_period": "2025Q3",
                    "subindustry": "储能",
                    "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                    "history": [],
                    "metric_evidence": {},
                    "formula_context": {},
                    "label_evidence": {},
                }

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    {
                        "company_name": "对标公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 15.0, "P2": 9.5, "C3": 2.0, "S4": 1.25, "S1": 1.42},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                ]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
                return "测试公司" if "测试公司" in query else None

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bronze" / "manifests").mkdir(parents=True, exist_ok=True)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            payload = OpsPilotService(StubRepository(), StubSettings()).chat_turn(
                query="请给测试公司做一份经营体检评分",
                company_name="测试公司",
                user_role="management",
            )

            self.assertEqual(payload["role_profile"]["label"], "企业管理者")
            self.assertEqual(len(payload["agent_flow"]), 4)
            self.assertTrue(payload["answer_sections"])
            self.assertTrue(payload["follow_up_questions"])
            self.assertEqual(payload["control_plane"]["query_type"], "company_scoring")
            self.assertEqual(payload["control_plane"]["steps_completed"], 4)
            self.assertIn("真实财报指标", payload["control_plane"]["data_sources"])
            self.assertEqual(payload["agent_flow"][0]["tool"], "intent_router")
            self.assertEqual(payload["agent_flow"][0]["route"]["path"], "/score")
            self.assertEqual(payload["agent_flow"][1]["tool"], "score_engine")
            self.assertEqual(payload["agent_flow"][2]["tool"], "evidence_auditor")
            self.assertTrue(payload["agent_flow"][2]["route"]["path"].startswith("/evidence/") or payload["agent_flow"][2]["route"]["path"] == "/admin")
            self.assertEqual(payload["agent_flow"][3]["tool"], "action_planner")
            self.assertIn("run_id", payload)
            self.assertTrue((root / "bronze" / "manifests" / "workspace_runs.json").exists())

    def test_workspace_runs_persist_and_can_be_read_back(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                return {
                    "company_name": "测试公司",
                    "report_period": "2025Q3",
                    "subindustry": "储能",
                    "metrics": {"G1": 12.0, "P2": 8.0, "C3": 11.2, "S4": 0.72, "S1": 1.08},
                    "history": [],
                    "metric_evidence": {},
                    "formula_context": {},
                    "label_evidence": {},
                }

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    self.get_company("测试公司", "2025Q3"),
                    {
                        "company_name": "对标公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 15.0, "P2": 9.5, "C3": 2.0, "S4": 1.25, "S1": 1.42},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                ]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
                return "测试公司" if "测试公司" in query else None

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bronze" / "manifests").mkdir(parents=True, exist_ok=True)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            payload = service.chat_turn(
                query="请给测试公司做一份经营体检评分",
                company_name="测试公司",
                user_role="management",
            )

            runs = service.workspace_runs(limit=5)
            detail = service.workspace_run_detail(payload["run_id"])

            self.assertEqual(runs["total"], 1)
            self.assertEqual(detail["run"]["run_id"], payload["run_id"])
            self.assertEqual(detail["detail"]["query"], "请给测试公司做一份经营体检评分")

    def test_task_queue_returns_prioritized_actions(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    {
                        "company_name": "对标公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 10.0, "G2": 8.0, "C3": 1.0, "S4": 1.4, "S1": 1.5},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                ]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                for item in self.list_companies(report_period):
                    if item["company_name"] == company_name:
                        return item
                return None

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司", "对标公司"]

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0

            def __init__(self) -> None:
                self.official_data_path = Path(".")

        queue = OpsPilotService(StubRepository(), StubSettings()).task_queue("management", "2025Q3")

        self.assertTrue(queue)
        self.assertEqual(queue[0]["company_name"], "测试公司")
        self.assertEqual(queue[0]["route"]["path"], "/score")
        self.assertIn("task_id", queue[0])

    def test_task_board_persists_status_updates(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    {
                        "company_name": "对标公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 10.0, "G2": 8.0, "C3": 1.0, "S4": 1.4, "S1": 1.5},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                ]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                for item in self.list_companies(report_period):
                    if item["company_name"] == company_name:
                        return item
                return None

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司", "对标公司"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            board = service.task_board("management", "2025Q3")
            self.assertTrue(board["tasks"])
            task_id = board["tasks"][0]["task_id"]

            update_payload = service.update_task_status(
                task_id=task_id,
                status="in_progress",
                user_role="management",
                report_period="2025Q3",
                note="开始处理现金回款链路",
            )

            self.assertEqual(update_payload["task"]["status"], "in_progress")
            self.assertEqual(update_payload["task"]["note"], "开始处理现金回款链路")
            self.assertEqual(update_payload["summary"]["in_progress"], 1)

            refreshed = service.task_board("management", "2025Q3")
            refreshed_task = next(item for item in refreshed["tasks"] if item["task_id"] == task_id)
            self.assertEqual(refreshed_task["status"], "in_progress")
            self.assertEqual(refreshed_task["history"][-1]["status"], "in_progress")
            self.assertTrue((root / "bronze" / "manifests" / "workspace_task_board.json").exists())

    def test_risk_scan_builds_alert_board_from_prior_period(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period in (None, "2025Q3"):
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        }
                    ]
                if report_period == "2025H1":
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025H1",
                            "subindustry": "储能",
                            "metrics": {"G1": 6.0, "G2": 4.0, "S4": 1.3, "S1": 1.22},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        }
                    ]
                return []

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3", "2025H1"]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                matches = {
                    "2025Q3": {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    "2025H1": {
                        "company_name": "测试公司",
                        "report_period": "2025H1",
                        "subindustry": "储能",
                        "metrics": {"G1": 6.0, "G2": 4.0, "S4": 1.3, "S1": 1.22},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                }
                return matches.get(report_period or "2025Q3")

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = False

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            (root / "raw" / "manifests" / "industry_research_reports_manifest.json").write_text(
                json.dumps({"records": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.risk_scan("2025Q3")

        self.assertEqual(len(payload["alert_board"]), 1)
        alert = payload["alert_board"][0]
        self.assertEqual(alert["company_name"], "测试公司")
        self.assertEqual(alert["previous_period"], "2025H1")
        self.assertEqual(alert["risk_delta"], 2)
        self.assertIn("营收同比 -8.4%", alert["new_labels"])

    def test_alert_workflow_persists_status_updates(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period in (None, "2025Q3"):
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        }
                    ]
                if report_period == "2025H1":
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025H1",
                            "subindustry": "储能",
                            "metrics": {"G1": 6.0, "G2": 4.0, "S4": 1.3, "S1": 1.22},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        }
                    ]
                return []

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3", "2025H1"]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                matches = {
                    "2025Q3": {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    "2025H1": {
                        "company_name": "测试公司",
                        "report_period": "2025H1",
                        "subindustry": "储能",
                        "metrics": {"G1": 6.0, "G2": 4.0, "S4": 1.3, "S1": 1.22},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                }
                return matches.get(report_period or "2025Q3")

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            workflow = service.alert_workflow("2025Q3")
            self.assertEqual(workflow["summary"]["new"], 1)
            alert_id = workflow["alerts"][0]["alert_id"]

            update_payload = service.update_alert_status(
                alert_id=alert_id,
                status="in_progress",
                report_period="2025Q3",
                note="进入排查流程",
            )

            self.assertEqual(update_payload["alert"]["status"], "in_progress")
            self.assertEqual(update_payload["alert"]["note"], "进入排查流程")
            self.assertEqual(update_payload["summary"]["in_progress"], 1)

            refreshed = service.alert_workflow("2025Q3")
            refreshed_alert = next(item for item in refreshed["alerts"] if item["alert_id"] == alert_id)
            self.assertEqual(refreshed_alert["status"], "in_progress")
            self.assertEqual(refreshed_alert["history"][-1]["status"], "in_progress")
            self.assertTrue((root / "bronze" / "manifests" / "workspace_alert_board.json").exists())

    def test_alert_dispatch_updates_alert_and_task(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period in (None, "2025Q3"):
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": -8.4, "G2": -15.2, "C3": 18.0, "S4": 0.72, "S1": 0.98},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                        {
                            "company_name": "对标公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {"G1": 10.0, "G2": 8.0, "C3": 1.0, "S4": 1.4, "S1": 1.5},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                if report_period == "2025H1":
                    return [
                        {
                            "company_name": "测试公司",
                            "report_period": "2025H1",
                            "subindustry": "储能",
                            "metrics": {"G1": 6.0, "G2": 4.0, "S4": 1.3, "S1": 1.22},
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        }
                    ]
                return []

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3", "2025H1"]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                for item in self.list_companies(report_period):
                    if item["company_name"] == company_name:
                        return item
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司", "对标公司"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            workflow = service.alert_workflow("2025Q3")
            alert_id = workflow["alerts"][0]["alert_id"]

            payload = service.dispatch_alert_to_task(
                alert_id,
                user_role="management",
                report_period="2025Q3",
                note="从预警派发整改",
            )

            self.assertEqual(payload["alert"]["status"], "dispatched")
            self.assertEqual(payload["task"]["status"], "in_progress")
            self.assertEqual(payload["task"]["note"], "从预警派发整改")

    def test_watchboard_persists_company_tracking(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                return {
                    "company_name": "测试公司",
                    "report_period": report_period or "2025Q3",
                    "subindustry": "储能",
                    "metrics": {"G1": 12.0, "G2": 8.0, "C1": 1.2, "C3": 16.0, "S1": 1.1, "S4": 0.9},
                    "history": [],
                    "metric_evidence": {},
                    "formula_context": {},
                    "label_evidence": {},
                }

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [self.get_company("测试公司", report_period or "2025Q3")]

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            board = service.add_watch_company(
                company_name="测试公司",
                user_role="management",
                report_period="2025Q3",
                note="重点跟踪现金链和预警。",
            )

            self.assertEqual(board["summary"]["tracked_companies"], 1)
            self.assertEqual(board["items"][0]["company_name"], "测试公司")
            self.assertEqual(board["items"][0]["note"], "重点跟踪现金链和预警。")

            scan = service.scan_watchboard(user_role="management", report_period="2025Q3")
            self.assertEqual(scan["run"]["summary"]["tracked_companies"], 1)
            self.assertEqual(scan["run"]["items"][0]["company_name"], "测试公司")

            runs = service.watchboard_runs(user_role="management", report_period="2025Q3")
            self.assertEqual(runs["total"], 1)
            self.assertEqual(runs["runs"][0]["companies"], ["测试公司"])

            run_detail = service.watchboard_run_detail(scan["run"]["run_id"])
            self.assertEqual(run_detail["items"][0]["company_name"], "测试公司")

            board = service.remove_watch_company(
                company_name="测试公司",
                user_role="management",
                report_period="2025Q3",
            )
            self.assertEqual(board["summary"]["tracked_companies"], 0)
            self.assertTrue((root / "bronze" / "manifests" / "workspace_watchboard.json").exists())
            self.assertTrue((root / "bronze" / "manifests" / "workspace_watchboard_runs.json").exists())

    def test_document_pipeline_results_and_detail(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [{"company_name": "测试公司", "report_period": report_period or "2025Q3"}]

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bronze = root / "bronze"
            manifests = bronze / "manifests"
            page_dir = bronze / "pages"
            manifests.mkdir(parents=True, exist_ok=True)
            page_dir.mkdir(parents=True, exist_ok=True)

            page_json_path = page_dir / "sample.json"
            page_json_path.write_text(
                json.dumps(
                    {
                        "pages": [
                            {"page": 1, "blocks": [{"text": "第一节 主要财务数据"}, {"text": "本报告期公司营业收入"}]},
                            {"page": 2, "blocks": [{"text": "同比增长情况如下"}, {"text": "一、经营概况"}]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-1",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2025年三季度报告",
                                "page_json_path": str(page_json_path),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0
                ocr_runtime_enabled = False

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = bronze
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            run_payload = service.run_document_pipeline_stage("title_hierarchy", limit=1)
            self.assertEqual(run_payload["processed"], 1)

            results = service.document_pipeline_results(stage="title_hierarchy")
            self.assertEqual(results["total"], 1)

            detail = service.document_pipeline_result_detail("title_hierarchy", "r-1")
            self.assertEqual(detail["job"]["report_id"], "r-1")
            self.assertTrue(detail["artifact"]["headings"])

    def test_company_workspace_and_graph_aggregate_core_system_state(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                records = {
                    "2025Q3": {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {
                            "G1": 12.0,
                            "G2": 8.0,
                            "C1": 1.2,
                            "C3": 24.0,
                            "S1": 1.1,
                            "S4": 0.9,
                            "P4": 88.0,
                        },
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    "2025H1": {
                        "company_name": "测试公司",
                        "report_period": "2025H1",
                        "subindustry": "储能",
                        "metrics": {
                            "G1": 10.0,
                            "G2": 6.0,
                            "C1": 1.0,
                            "C3": 5.0,
                            "S1": 1.2,
                            "S4": 1.0,
                            "P4": 72.0,
                        },
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                }
                if company_name != "测试公司":
                    return None
                return records.get(report_period or "2025Q3")

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period == "2025Q3":
                    return [
                        self.get_company("测试公司", "2025Q3"),
                        {
                            "company_name": "对标公司",
                            "report_period": "2025Q3",
                            "subindustry": "储能",
                            "metrics": {
                                "G1": 9.0,
                                "G2": 7.0,
                                "C1": 1.3,
                                "C3": 2.0,
                                "S1": 1.4,
                                "S4": 1.3,
                                "P4": 68.0,
                            },
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                if report_period == "2025H1":
                    return [
                        self.get_company("测试公司", "2025H1"),
                        {
                            "company_name": "对标公司",
                            "report_period": "2025H1",
                            "subindustry": "储能",
                            "metrics": {
                                "G1": 8.0,
                                "G2": 5.0,
                                "C1": 1.2,
                                "C3": 1.5,
                                "S1": 1.45,
                                "S4": 1.2,
                                "P4": 66.0,
                            },
                            "history": [],
                            "metric_evidence": {},
                            "formula_context": {},
                            "label_evidence": {},
                        },
                    ]
                return [
                    self.get_company("测试公司", "2025Q3"),
                    self.get_company("测试公司", "2025H1"),
                ]

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3", "2025H1"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def find_company_from_query(self, query: str, report_period: str | None = None) -> str | None:
                return "测试公司" if "测试公司" in query else None

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            (root / "raw" / "manifests" / "research_reports_manifest.json").write_text(
                json.dumps({"records": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            artifact_path = (
                root
                / "bronze"
                / "upgrades"
                / "title_hierarchy"
                / "000001"
                / "demo-report.json"
            )
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(
                    {
                        "report_id": "demo-report",
                        "company_name": "测试公司",
                        "summary": "恢复出 3 个标题节点。",
                        "headings": [{"page": 1, "text": "第一节", "level": 1}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "bronze" / "manifests" / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "demo-report",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2025年三季度报告",
                                "page_json_path": str(root / "bronze" / "pages" / "demo-report.json"),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "bronze" / "manifests" / "document_pipeline_jobs.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "stage": "title_hierarchy",
                                "report_id": "demo-report",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "report_period": "2025Q3",
                                "status": "completed",
                                "artifact_path": str(artifact_path),
                                "artifact_summary": "恢复出 3 个标题节点。",
                                "completed_at": "2026-03-20T08:00:00+00:00",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "bronze" / "runs").mkdir(parents=True, exist_ok=True)
            (root / "bronze" / "runs" / "run-1.json").write_text(
                json.dumps({"run_id": "run-1", "query": "请给测试公司做经营体检"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "bronze" / "manifests" / "workspace_runs.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "run_id": "run-1",
                                "query": "请给测试公司做经营体检",
                                "company_name": "测试公司",
                                "report_period": "2025Q3",
                                "query_type": "company_scoring",
                                "user_role": "management",
                                "created_at": "2026-03-20T09:00:00+00:00",
                                "detail_path": str(root / "bronze" / "runs" / "run-1.json"),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0
                ocr_runtime_enabled = False

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            workspace = service.company_workspace("测试公司", "2025Q3", user_role="management")
            graph = service.company_graph("测试公司", "2025Q3", user_role="management")

            self.assertEqual(workspace["company_name"], "测试公司")
            self.assertIn(workspace["score_summary"]["grade"], {"A", "B", "C", "D"})
            self.assertEqual(workspace["research"]["status"], "missing")
            self.assertGreaterEqual(workspace["document_upgrades"]["count"], 1)
            self.assertTrue(
                any(item["stage"] == "title_hierarchy" for item in workspace["document_upgrades"]["items"])
            )
            self.assertTrue(workspace["tasks"]["items"])
            self.assertTrue(workspace["alerts"]["items"])
            self.assertEqual(workspace["recent_runs"]["count"], 1)
            self.assertEqual(graph["company_name"], "测试公司")
            self.assertGreaterEqual(graph["summary"]["node_count"], 5)
            self.assertGreaterEqual(graph["summary"]["edge_count"], 4)
            self.assertEqual(graph["summary"]["run_count"], 1)

    def test_admin_overview_returns_health_data_and_job_catalog(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [{"company_name": "测试公司", "report_period": report_period or "2025Q3"}]

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = False

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            (root / "universe").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.admin_overview()

            self.assertEqual(payload["health"]["status"], "ok")
            self.assertEqual(payload["data_status"]["periodic_reports"]["record_count"], 0)
            self.assertEqual(payload["quality_overview"]["coverage"]["pool_companies"], 0)
            self.assertEqual(payload["document_pipeline"]["layout_engine"], "PP-DocLayout-V3 + PyMuPDF")
            self.assertEqual(payload["document_pipeline"]["cross_page_merge"]["status"], "completed 0")
            self.assertEqual(payload["job_catalog"][0]["job_id"], "fetch_real_data")
            self.assertIn("企业评分", payload["capabilities"])
            self.assertIn("document_pipeline_jobs", payload)
            self.assertIn("innovation_radar", payload)
            self.assertGreaterEqual(payload["innovation_radar"]["summary"]["total"], 1)

    def test_document_pipeline_run_creates_upgrade_artifact(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return []

            def list_company_names(self) -> list[str]:
                return []

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = False

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-report.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [
                                    {"text": "第一节 重要内容提示", "bbox": [0, 0, 1, 1]},
                                    {"text": "本报告期营业收入继续增长及", "bbox": [0, 0, 1, 1]},
                                ],
                            },
                            {
                                "page": 2,
                                "blocks": [
                                    {"text": "其中组件业务贡献主要增量。", "bbox": [0, 0, 1, 1]},
                                    {"text": "一、经营情况讨论与分析", "bbox": [0, 0, 1, 1]},
                                ],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "bronze" / "manifests" / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司：2025年三季度报告",
                                "report_id": "demo-report",
                                "page_json_path": str(page_json),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.run_document_pipeline_stage("title_hierarchy", 1)

            self.assertEqual(payload["processed"], 1)
            artifact_path = Path(payload["results"][0]["artifact_path"])
            self.assertTrue(artifact_path.exists())
            artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact_payload["company_name"], "测试公司")
            self.assertTrue(artifact_payload["headings"])

    def test_admin_overview_reports_company_coverage_gaps(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return []

            def list_company_names(self) -> list[str]:
                return []

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = False

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            (root / "universe").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)

            (root / "universe" / "formal_company_pool.json").write_text(
                json.dumps(
                    [
                        {"company_name": "甲公司", "subindustry": "储能"},
                        {"company_name": "乙公司", "subindustry": "光伏"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "raw" / "manifests" / "periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"company_name": "甲公司"},
                            {"company_name": "乙公司"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "raw" / "manifests" / "research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"company_name": "甲公司"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "bronze" / "manifests" / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"company_name": "甲公司"},
                            {"company_name": "乙公司"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "silver" / "manifests" / "financial_metrics_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"company_name": "甲公司", "report_period": "2025Q3"},
                            {"company_name": "甲公司", "report_period": "2025H1"},
                            {"company_name": "乙公司", "report_period": "2025H1"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            payload = service.admin_overview()
            coverage = payload["quality_overview"]["coverage"]
            issue_buckets = {
                item["code"]: item for item in payload["quality_overview"]["issue_buckets"]
            }
            company_rows = {
                item["company_name"]: item for item in payload["quality_overview"]["companies"]
            }

            self.assertEqual(coverage["pool_companies"], 2)
            self.assertEqual(coverage["preferred_period_ready"], 1)
            self.assertEqual(coverage["research_ready"], 1)
            self.assertIn("缺主周期", issue_buckets)
            self.assertIn("缺研报", issue_buckets)
            self.assertEqual(company_rows["甲公司"]["issues"], [])
            self.assertEqual(company_rows["乙公司"]["issues"], ["缺研报", "缺主周期"])

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

    def test_extract_research_body_and_build_claim_cards(self) -> None:
        html = """
        <div id="ctx-content" class="ctx-content">
            <p>国轩高科(002074)</p>
            <p>前三季度公司实现营收295.08亿元，同比+17%；归母净利润25.33亿元，同比+514%；毛利率17.6%。</p>
        </div>
        """
        company = {
            "metrics": {"G1": 17.0, "P1": 17.6},
            "raw_metrics": {"RAW_REVENUE": 29_508_000_000.0, "RAW_NET_PROFIT": 2_533_000_000.0},
            "facts": {"net_profit": {"change_pct": 514.0}},
            "metric_evidence": {"G1": ["g1-evidence"], "G2": ["g2-evidence"], "P1": ["p1-evidence"]},
            "summary_chunk_id": "summary-evidence",
        }
        report = {
            "security_code": "002074",
            "company_name": "国轩高科",
            "title": "2025年三季度报告点评",
            "local_path": "x.html",
        }

        body = _extract_research_body(html)
        cards = _build_claim_cards(company, report, body)

        self.assertEqual(len(cards), 5)
        self.assertEqual(cards[0]["label"], "营收同比")
        self.assertEqual(cards[0]["status"], "match")
        self.assertEqual(cards[1]["label"], "营收规模")
        self.assertEqual(cards[1]["actual_value"], 295.08)
        self.assertEqual(cards[2]["label"], "归母净利润同比")
        self.assertEqual(cards[3]["label"], "归母净利润规模")
        self.assertEqual(cards[4]["label"], "毛利率")

    def test_extract_research_payload_and_forecast_cards(self) -> None:
        html = """
        <script>
        var zwinfo= {
            "notice_content":"预计公司2025~2027年有望分别实现归母净利33.82/25.39/32.98亿元，同比+180%/-25%/+30%，当前股价对应PE24x/31x/24x，维持\\"强烈推荐\\"评级，目标价69.2元。",
            "notice_title":"2025年三季度报告点评",
            "notice_date":"2025-11-04 00:00:00",
            "attach_url":"https://example.com/report.pdf",
            "source_sample_name":"东兴证券",
            "researcher":"分析师甲",
            "rating":"A"
        };
        </script>
        """
        report = {
            "security_code": "002074",
            "company_name": "国轩高科",
            "title": "2025年三季度报告点评",
            "publish_date": "2025-11-04",
            "source_url": "https://example.com/research",
            "detail_url": "https://example.com/research",
            "local_path": "x.html",
        }

        payload = _extract_research_payload(html)
        body = _extract_research_body(html, payload)
        forecast_cards = _build_forecast_cards(
            report,
            body,
            {
                "title": payload["notice_title"],
                "publish_date": "2025-11-04",
                "source_url": report["detail_url"],
                "attachment_url": payload["attach_url"],
                "source_name": payload["source_sample_name"],
                "researcher": payload["researcher"],
                "rating_code": payload["rating"],
                "rating_label": "强烈推荐",
                "rating_action": "维持",
            },
        )

        self.assertEqual(payload["notice_title"], "2025年三季度报告点评")
        self.assertIn("维持", body)
        self.assertEqual(len(forecast_cards), 3)
        self.assertEqual(forecast_cards[0]["report_period"], "2025FY")
        self.assertEqual(forecast_cards[0]["forecast_value"], 33.82)
        self.assertEqual(forecast_cards[0]["yoy_value"], 180.0)
        self.assertEqual(forecast_cards[1]["pe_value"], 31.0)
        self.assertEqual(forecast_cards[2]["rating_label"], "强烈推荐")

    def test_build_forecast_cards_supports_two_digit_year_ranges(self) -> None:
        report = {
            "security_code": "002202",
            "company_name": "金风科技",
            "title": "2025年三季报点评：主业经营稳健，海外积极拓展",
            "publish_date": "2025-10-30",
            "source_url": "https://example.com/research",
            "detail_url": "https://example.com/research",
            "local_path": "x.html",
        }
        report_meta = {
            "title": report["title"],
            "publish_date": report["publish_date"],
            "source_url": report["detail_url"],
            "attachment_url": None,
            "source_name": "测试证券",
            "researcher": "分析师甲",
            "rating_code": "A",
            "rating_label": "推荐",
            "rating_action": "维持",
        }
        body = (
            "投资建议：我们预计公司2025-2027年营收分别为778.1、881.4、959.1亿元，"
            "归母净利润分别为33.6、42.8、49.8亿元，增速为81%/27%/16%，"
            "对应25-27年PE为20x/16x/13x，维持“推荐”评级。"
        )

        cards = _build_forecast_cards(report, body, report_meta)

        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["report_period"], "2025FY")
        self.assertEqual(cards[0]["forecast_value"], 33.6)
        self.assertEqual(cards[1]["pe_value"], 16.0)
        self.assertEqual(cards[2]["rating_label"], "推荐")

    def test_build_forecast_cards_supports_split_year_blocks(self) -> None:
        report = {
            "security_code": "002202",
            "company_name": "金风科技",
            "title": "2025年三季报点评：风机出货景气度高，在手订单同比提升",
            "publish_date": "2025-10-31",
            "source_url": "https://example.com/research",
            "detail_url": "https://example.com/research",
            "local_path": "x.html",
        }
        report_meta = {
            "title": report["title"],
            "publish_date": report["publish_date"],
            "source_url": report["detail_url"],
            "attachment_url": None,
            "source_name": "测试证券",
            "researcher": "分析师甲",
            "rating_code": "A",
            "rating_label": "增持",
            "rating_action": "维持",
        }
        body = (
            "盈利预测与投资评级：我们维持25年盈利预测，预计25年归母净利润33.5亿元；"
            "考虑25年风机中标价小幅上涨，我们上调26~27年盈利预测，预计26~27年归母净利润为45.6/55.5亿元，"
            "25~27年归母净利润同增80%/36%/22%，对应PE19.6/14.4/11.9x，维持“增持”评级。"
        )

        cards = _build_forecast_cards(report, body, report_meta)

        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["forecast_value"], 33.5)
        self.assertEqual(cards[1]["yoy_value"], 36.0)
        self.assertEqual(cards[2]["pe_value"], 11.9)

    def test_select_research_report_prefers_available_explicit_period(self) -> None:
        reports = [
            {
                "company_name": "测试公司",
                "title": "行业景气向上，订单持续放量",
                "publish_date": "2026-01-10",
            },
            {
                "company_name": "测试公司",
                "title": "2025年三季度报告点评：盈利改善",
                "publish_date": "2025-11-04",
            },
        ]

        selected = _select_research_report(
            reports,
            company_name="测试公司",
            report_period=None,
            report_title=None,
            available_periods={"2025Q3"},
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["title"], "2025年三季度报告点评：盈利改善")

    def test_infer_report_period_supports_short_report_names(self) -> None:
        self.assertEqual(_infer_report_period_from_text("2025年三季报点评：盈利改善"), "2025Q3")
        self.assertEqual(_infer_report_period_from_text("2025年中报点评：需求修复"), "2025H1")
        self.assertEqual(_infer_report_period_from_text("2025年年报点评：业绩反转"), "2025FY")

    def test_select_research_report_prefers_richer_content_with_same_bucket(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sparse_path = root / "sparse.html"
            rich_path = root / "rich.html"
            sparse_path.write_text(
                """
                <script>
                var zwinfo= {"notice_content":"公司经营平稳，维持“买入”评级。","notice_title":"一般点评","notice_date":"2025-11-01 00:00:00","rating":"A"};
                </script>
                """,
                encoding="utf-8",
            )
            rich_path.write_text(
                """
                <script>
                var zwinfo= {"notice_content":"我们预计公司2025/2026/2027年归母净利润分别为11/12/13亿元，对应PE20x/18x/16x，维持\\"买入\\"评级。","notice_title":"深度点评","notice_date":"2025-11-05 00:00:00","rating":"A"};
                </script>
                """,
                encoding="utf-8",
            )
            reports = [
                {
                    "company_name": "测试公司",
                    "title": "一般点评",
                    "publish_date": "2025-11-01",
                    "local_path": str(sparse_path),
                },
                {
                    "company_name": "测试公司",
                    "title": "深度点评",
                    "publish_date": "2025-11-05",
                    "local_path": str(rich_path),
                },
            ]

            selected = _select_research_report(
                reports,
                company_name="测试公司",
                report_period=None,
                report_title=None,
                available_periods={"2024FY"},
            )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["title"], "深度点评")

    def test_verify_claim_uses_latest_research_report_for_company(self) -> None:
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
                        "metrics": {"G1": 10.0, "P1": 15.0},
                        "raw_metrics": {"RAW_REVENUE": 10_000_000_000.0, "RAW_NET_PROFIT": 800_000_000.0},
                        "facts": {"net_profit": {"change_pct": 12.0}},
                        "history": [],
                        "metric_evidence": {"G1": ["g1"], "G2": ["g2"], "P1": ["p1"]},
                        "formula_context": {},
                        "label_evidence": {},
                        "summary_chunk_id": "summary",
                    }
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [self.get_company("测试公司", "2024FY")]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return [
                    {
                        "chunk_id": chunk_id,
                        "company_name": "测试公司",
                        "report_period": "2024FY",
                        "source_title": "官方报告",
                        "source_type": "official_summary_page",
                        "page": 1,
                        "excerpt": "官方证据",
                        "fingerprint": chunk_id,
                        "source_url": "https://example.com/report.pdf",
                        "local_path": "report.pdf",
                    }
                    for chunk_id in chunk_ids
                ]

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

            def __init__(self, official_data_path: Path) -> None:
                self.official_data_path = official_data_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifests_root = root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            report_path = root / "report.html"
            report_path.write_text(
                """
                <script>
                var zwinfo= {
                    "notice_content":"测试公司实现营收100亿元，同比+10%；毛利率15.0%。预计公司2025/2026/2027年归母净利润分别为11/12/13亿元，对应PE20x/18x/16x，维持\\"买入\\"评级，目标价41元。",
                    "notice_title":"测试公司2024年年度点评",
                    "notice_date":"2025-01-10 00:00:00",
                    "attach_url":"https://example.com/report.pdf",
                    "source_sample_name":"测试证券",
                    "researcher":"分析师甲",
                    "rating":"A"
                };
                </script>
                """,
                encoding="utf-8",
            )
            (manifests_root / "research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2024年年度点评",
                                "publish_date": "2025-01-10",
                                "source_url": "https://example.com/research",
                                "detail_url": "https://example.com/research",
                                "local_path": str(report_path),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            payload = service.verify_claim("测试公司")

            self.assertEqual(payload["report_period"], "2024FY")
            self.assertEqual(payload["key_numbers"][0]["value"], 3)
            self.assertEqual(payload["claim_cards"][0]["status"], "match")
            self.assertEqual(payload["report_meta"]["source_name"], "测试证券")
            self.assertEqual(payload["report_meta"]["rating_label"], "买入")
            self.assertEqual(payload["report_meta"]["rating_change"], "维持")
            self.assertEqual(payload["report_meta"]["target_price"], 41.0)
            self.assertEqual(len(payload["forecast_cards"]), 3)
            self.assertTrue(payload["evidence_groups"])
            self.assertEqual(payload["evidence_groups"][0]["title"], "营收同比")

    def test_list_research_reports_returns_ranked_catalog(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                if report_period in (None, "2025Q3"):
                    return {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 10.0, "P1": 15.0},
                        "raw_metrics": {"RAW_REVENUE": 10_000_000_000.0, "RAW_NET_PROFIT": 800_000_000.0},
                        "facts": {"net_profit": {"change_pct": 12.0}},
                        "history": [],
                        "metric_evidence": {"G1": ["g1"], "G2": ["g2"], "P1": ["p1"]},
                        "formula_context": {},
                        "label_evidence": {},
                        "summary_chunk_id": "summary",
                    }
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [self.get_company("测试公司", "2025Q3")]

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

            def __init__(self, official_data_path: Path) -> None:
                self.official_data_path = official_data_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifests_root = root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            sparse_path = root / "sparse.html"
            prior_path = root / "prior.html"
            rich_path = root / "rich.html"
            sparse_path.write_text(
                """
                <script>
                var zwinfo= {"notice_content":"公司经营平稳，维持\\"买入\\"评级。","notice_title":"简版点评","notice_date":"2025-11-01 00:00:00","source_sample_name":"甲证券","rating":"A"};
                </script>
                """,
                encoding="utf-8",
            )
            prior_path.write_text(
                """
                <script>
                var zwinfo= {"notice_content":"预计公司2025/2026/2027年归母净利润分别为10/11/12亿元，对应PE22x/19x/17x，维持\\"买入\\"评级，目标价40元。","notice_title":"上一期点评","notice_date":"2025-10-20 00:00:00","source_sample_name":"乙证券","rating":"A"};
                </script>
                """,
                encoding="utf-8",
            )
            rich_path.write_text(
                """
                <script>
                var zwinfo= {"notice_content":"预计公司2025/2026/2027年归母净利润分别为11/12/13亿元，对应PE20x/18x/16x，维持\\"买入\\"评级，目标价43.5元。","notice_title":"深度点评","notice_date":"2025-11-05 00:00:00","source_sample_name":"乙证券","rating":"A"};
                </script>
                """,
                encoding="utf-8",
            )
            (manifests_root / "research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "简版点评",
                                "publish_date": "2025-11-01",
                                "source_url": "https://example.com/sparse",
                                "detail_url": "https://example.com/sparse",
                                "local_path": str(sparse_path),
                            },
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "上一期点评",
                                "publish_date": "2025-10-20",
                                "source_url": "https://example.com/prior",
                                "detail_url": "https://example.com/prior",
                                "local_path": str(prior_path),
                            },
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "深度点评",
                                "publish_date": "2025-11-05",
                                "source_url": "https://example.com/rich",
                                "detail_url": "https://example.com/rich",
                                "local_path": str(rich_path),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            reports = service.list_research_reports("测试公司")

            self.assertEqual(len(reports), 3)
            self.assertEqual(reports[0]["title"], "深度点评")
            self.assertEqual(reports[0]["forecast_count"], 3)
            self.assertEqual(reports[0]["rating_text"], "维持买入")
            self.assertEqual(reports[0]["rating_change"], "维持")
            self.assertEqual(reports[0]["target_price"], 43.5)
            self.assertEqual(reports[0]["source_url"], "https://example.com/rich")

            compare = service.compare_research_reports("测试公司")

            self.assertEqual(compare["company_name"], "测试公司")
            self.assertEqual(compare["rows"][0]["title"], "深度点评")
            self.assertEqual(compare["rows"][0]["headline_forecast_year"], "2025")
            self.assertEqual(compare["rows"][0]["headline_forecast_value"], 11.0)
            self.assertEqual(compare["rows"][0]["headline_forecast_pe"], 20.0)
            self.assertIn("信息最完整", compare["rows"][0]["signal_tags"])
            self.assertEqual(compare["key_numbers"][0]["value"], 3)
            self.assertTrue(compare["insights"])
            self.assertEqual(compare["insights"][0]["kind"], "consensus")
            self.assertEqual(compare["total_reports"], 3)
            self.assertEqual(compare["filtered_reports"], 3)

            filtered = service.compare_research_reports(
                "测试公司",
                sort_by="target_price_desc",
                filter_mode="target_price",
            )

            self.assertEqual(filtered["selected_sort"], "target_price_desc")
            self.assertEqual(filtered["selected_filter"], "target_price")
            self.assertEqual(filtered["filtered_reports"], 2)
            self.assertEqual(filtered["rows"][0]["title"], "深度点评")

            divergence = service.compare_research_reports(
                "测试公司",
                filter_mode="divergence",
            )

            self.assertEqual(divergence["filtered_reports"], 2)
            self.assertEqual(divergence["rows"][0]["title"], "深度点评")

            timeline = service.summarize_research_timeline("测试公司")

            self.assertEqual(timeline["key_numbers"][0]["value"], 2)
            self.assertEqual(timeline["key_numbers"][1]["value"], 1)
            self.assertEqual(timeline["institutions"][0]["institution"], "乙证券")
            self.assertEqual(timeline["institutions"][0]["report_count"], 2)
            self.assertIsNone(timeline["institutions"][0]["rating_stability"])
            self.assertEqual(
                timeline["institutions"][0]["latest_transition"]["transition_kind"],
                "not_comparable",
            )
            self.assertFalse(timeline["institutions"][0]["latest_transition"]["is_rating_comparable"])
            self.assertTrue(timeline["institutions"][0]["latest_transition"]["is_forecast_comparable"])
            self.assertEqual(timeline["institutions"][0]["latest_transition"]["forecast_delta"], 1.0)
            self.assertEqual(
                timeline["institutions"][0]["latest_transition"]["source_url"],
                "https://example.com/rich",
            )

    def test_industry_research_brief_returns_grouped_reports(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 10.0},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }
                ]

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0

            def __init__(self, official_data_path: Path) -> None:
                self.official_data_path = official_data_path
                self.bronze_data_path = official_data_path
                self.silver_data_path = official_data_path
                self.sample_data_path = official_data_path

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifests_root = root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            report_path = root / "industry.html"
            report_path.write_text(
                """
                <script>
                var zwinfo= {
                    "notice_content":"光伏设备行业景气延续，组件价格企稳，维持行业推荐评级。",
                    "notice_title":"光伏设备行业周报：景气延续",
                    "notice_date":"2025-11-08 00:00:00",
                    "source_sample_name":"测试证券",
                    "attach_url":"https://example.com/industry.pdf",
                    "rating":"A"
                };
                </script>
                """,
                encoding="utf-8",
            )
            (manifests_root / "industry_research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "company_name": "光伏设备",
                                "industry_name": "光伏设备",
                                "security_code": "INDUSTRY",
                                "title": "光伏设备行业周报：景气延续",
                                "publish_date": "2025-11-08",
                                "source_url": "https://example.com/industry",
                                "detail_url": "https://example.com/industry",
                                "local_path": str(report_path),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            payload = service.industry_research_brief()

            self.assertEqual(payload["key_numbers"][0]["value"], 1)
            self.assertEqual(payload["groups"][0]["industry_name"], "光伏设备")
            self.assertEqual(payload["groups"][0]["latest_report"]["source_name"], "测试证券")
            self.assertEqual(payload["groups"][0]["reports"][0]["rating_text"], "未披露")


if __name__ == "__main__":
    unittest.main()
