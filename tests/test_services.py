from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
import json
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.application.services import (
    OpsPilotService,
    _build_evidence_groups,
    _build_forecast_cards,
    _build_label_cards,
    _extract_research_body,
    _extract_research_payload,
    _select_research_report,
)
from opspilot.application.research_claims import _build_claim_cards, _infer_report_period_from_text
from opspilot.delivery_report import build_delivery_report_markdown
from opspilot.runtime_checks import build_runtime_report, validate_delivery_runtime
from opspilot.infra.sample_repository import SampleRepository


class ServicesTestCase(unittest.IsolatedAsyncioTestCase):
    def test_industry_brain_returns_realtime_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = type(
                "StubSettings",
                (),
                {
                    "app_name": "OpsPilot",
                    "env": "test",
                    "default_period": "2025Q3",
                    "audit_min_evidence": 0,
                    "sample_data_path": Path(__file__).resolve().parents[1] / "data" / "bootstrap",
                    "official_data_path": root / "raw" / "official",
                    "bronze_data_path": root / "bronze" / "official",
                    "silver_data_path": root / "silver" / "official",
                },
            )()
            repository = SampleRepository(settings.sample_data_path)
            service = OpsPilotService(repository, settings)

            payload = service.industry_brain()

            self.assertIn("metrics", payload)
            self.assertIn("charts", payload)
            self.assertIn("radar_events", payload)
            self.assertTrue(payload["stream"]["ws_connected"])
            self.assertGreaterEqual(len(payload["metrics"]), 4)
            self.assertEqual(payload["charts"][0]["title"], "主周期预警 / 任务 / 监测板实时跳动")
            self.assertIn("brain_command_surface", payload)
            self.assertTrue(payload["brain_signal_tape"])
            self.assertIn("external_signal_stream", payload)
            self.assertEqual(payload["external_signal_stream"]["status"], "unavailable")
            self.assertEqual(payload["streaming_heatmap"]["status"], "unavailable")
            self.assertEqual(payload["streaming_anomalies"]["status"], "unavailable")
            self.assertEqual(payload["streaming_anomalies"]["items"], [])
            history = service.industry_brain_history(limit=4)
            self.assertGreaterEqual(history["total"], 1)
            self.assertEqual(history["records"][0]["report_period"], payload["report_period"])
            self.assertIn("market_tape", history["records"][0])
            self.assertIn("external_signal_stream", history["records"][0])
            self.assertIn("streaming_anomalies", history["records"][0])

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
        self.assertIn("score_command_surface", payload)
        self.assertTrue(payload["score_signal_tape"])

    def test_industry_brain_surfaces_external_official_signal_stream(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                for item in self.list_companies(report_period):
                    if item["company_name"] == company_name:
                        return item
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "科陆电子",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 8.0, "C3": 11.0, "S4": 0.82},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    },
                    {
                        "company_name": "国轩高科",
                        "report_period": "2025Q3",
                        "subindustry": "锂电池与电池材料",
                        "metrics": {"G1": 7.5, "C3": 10.6, "S4": 0.84},
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
                return ["科陆电子", "国轩高科"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifests_root = root / "raw" / "official" / "manifests"
            silver_stream_root = root / "silver" / "official" / "stream"
            gold_stream_root = root / "gold" / "official" / "stream"
            manifests_root.mkdir(parents=True, exist_ok=True)
            silver_stream_root.mkdir(parents=True, exist_ok=True)
            gold_stream_root.mkdir(parents=True, exist_ok=True)
            recent_day = date.today()
            recent_text = recent_day.isoformat()
            generated_at = f"{recent_text}T08:00:00"
            (manifests_root / "research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "records": [
                            {
                                "source": "EASTMONEY",
                                "company_name": "科陆电子",
                                "security_code": "002121",
                                "exchange": "SZSE",
                                "subindustry": "储能",
                                "title": "智能电网与储能业务同步提速",
                                "publish_date": recent_text,
                                "source_url": "https://example.com/research",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests_root / "industry_research_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "records": [
                            {
                                "source": "EASTMONEY_INDUSTRY",
                                "company_name": "电池",
                                "industry_name": "电池",
                                "security_code": "INDUSTRY",
                                "subindustry": "电池",
                                "title": "储能电池周度景气跟踪",
                                "publish_date": (recent_day - timedelta(days=1)).isoformat(),
                                "source_url": "https://example.com/industry",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests_root / "periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "records": [
                            {
                                "source": "SZSE",
                                "company_name": "国轩高科",
                                "security_code": "002074",
                                "exchange": "SZSE",
                                "subindustry": "锂电池与电池材料",
                                "title": "国轩高科：2025年年度报告",
                                "publish_date": (recent_day - timedelta(days=2)).isoformat(),
                                "source_url": "https://example.com/periodic",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests_root / "company_snapshots_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "records": [
                            {
                                "source": "CNINFO_SNAPSHOT",
                                "company_name": "科陆电子",
                                "security_code": "002121",
                                "subindustry": "储能",
                                "title": "公司快照",
                                "publish_date": recent_text,
                                "source_url": "https://example.com/snapshot",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (silver_stream_root / "company_signal_snapshot.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "ingest_batch_id": "20260325080000",
                        "record_count": 2,
                        "records": [
                            {
                                "ingest_batch_id": "20260325080000",
                                "company_name": "科陆电子",
                                "security_code": "002121",
                                "subindustry": "储能",
                                "latest_event_time": f"{recent_text}T00:00:00+00:00",
                                "latest_headline": "智能电网与储能业务同步提速",
                                "latest_signal_kind": "company_research",
                                "latest_signal_status": "券商研报",
                                "signal_count": 2,
                                "source_count": 2,
                                "external_heat": 4,
                            },
                            {
                                "ingest_batch_id": "20260325080000",
                                "company_name": "国轩高科",
                                "security_code": "002074",
                                "subindustry": "锂电池与电池材料",
                                "latest_event_time": f"{recent_text}T00:00:00+00:00",
                                "latest_headline": "国轩高科：2025年年度报告",
                                "latest_signal_kind": "periodic_report",
                                "latest_signal_status": "交易所公告",
                                "signal_count": 1,
                                "source_count": 1,
                                "external_heat": 4,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (gold_stream_root / "company_signal_timeline.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "ingest_batch_id": "20260325080000",
                        "window_days": 7,
                        "date_axis": [
                            (recent_day - timedelta(days=2)).isoformat(),
                            (recent_day - timedelta(days=1)).isoformat(),
                            recent_text,
                        ],
                        "record_count": 2,
                        "top_companies": [
                            {
                                "ingest_batch_id": "20260325080000",
                                "company_name": "科陆电子",
                                "security_code": "002121",
                                "subindustry": "储能",
                                "latest_event_time": f"{recent_text}T00:00:00+00:00",
                                "latest_headline": "智能电网与储能业务同步提速",
                                "latest_signal_kind": "company_research",
                                "latest_signal_status": "券商研报",
                                "latest_heat": 3,
                                "signal_count": 2,
                                "total_heat": 4,
                                "active_days": 2,
                                "momentum": 4,
                                "timeline": [
                                    {"date": (recent_day - timedelta(days=2)).isoformat(), "signal_count": 0, "external_heat": 0},
                                    {"date": (recent_day - timedelta(days=1)).isoformat(), "signal_count": 1, "external_heat": 1},
                                    {"date": recent_text, "signal_count": 1, "external_heat": 3},
                                ],
                            },
                            {
                                "ingest_batch_id": "20260325080000",
                                "company_name": "国轩高科",
                                "security_code": "002074",
                                "subindustry": "锂电池与电池材料",
                                "latest_event_time": f"{recent_text}T00:00:00+00:00",
                                "latest_headline": "国轩高科：2025年年度报告",
                                "latest_signal_kind": "periodic_report",
                                "latest_signal_status": "交易所公告",
                                "latest_heat": 4,
                                "signal_count": 1,
                                "total_heat": 4,
                                "active_days": 1,
                                "momentum": 4,
                                "timeline": [
                                    {"date": (recent_day - timedelta(days=2)).isoformat(), "signal_count": 1, "external_heat": 4},
                                    {"date": (recent_day - timedelta(days=1)).isoformat(), "signal_count": 0, "external_heat": 0},
                                    {"date": recent_text, "signal_count": 0, "external_heat": 0},
                                ],
                            },
                        ],
                        "records": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (gold_stream_root / "subindustry_signal_heatmap.json").write_text(
                json.dumps(
                    {
                        "generated_at": generated_at,
                        "ingest_batch_id": "20260325080000",
                        "window_days": 7,
                        "date_axis": [
                            (recent_day - timedelta(days=2)).isoformat(),
                            (recent_day - timedelta(days=1)).isoformat(),
                            recent_text,
                        ],
                        "record_count": 2,
                        "top_subindustries": [
                            {
                                "ingest_batch_id": "20260325080000",
                                "subindustry": "储能",
                                "signal_count": 2,
                                "total_heat": 4,
                                "latest_heat": 3,
                                "active_days": 2,
                                "momentum": 4,
                                "timeline": [
                                    {"date": (recent_day - timedelta(days=2)).isoformat(), "signal_count": 0, "external_heat": 0},
                                    {"date": (recent_day - timedelta(days=1)).isoformat(), "signal_count": 1, "external_heat": 1},
                                    {"date": recent_text, "signal_count": 1, "external_heat": 3},
                                ],
                            },
                            {
                                "ingest_batch_id": "20260325080000",
                                "subindustry": "锂电池与电池材料",
                                "signal_count": 1,
                                "total_heat": 4,
                                "latest_heat": 0,
                                "active_days": 1,
                                "momentum": 4,
                                "timeline": [
                                    {"date": (recent_day - timedelta(days=2)).isoformat(), "signal_count": 1, "external_heat": 4},
                                    {"date": (recent_day - timedelta(days=1)).isoformat(), "signal_count": 0, "external_heat": 0},
                                    {"date": recent_text, "signal_count": 0, "external_heat": 0},
                                ],
                            },
                        ],
                        "records": [],
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

                def __init__(self) -> None:
                    self.sample_data_path = Path(__file__).resolve().parents[1] / "data" / "bootstrap"
                    self.official_data_path = root / "raw" / "official"
                    self.bronze_data_path = root / "bronze" / "official"
                    self.silver_data_path = root / "silver" / "official"
                    self.gold_data_path = root / "gold" / "official"

            service = OpsPilotService(StubRepository(), StubSettings())
            payload = service.industry_brain()

            self.assertEqual(payload["external_signal_stream"]["status"], "fresh")
            self.assertEqual(payload["external_signal_stream"]["signal_count"], 4)
            self.assertEqual(payload["external_signal_stream"]["signals"][0]["company_name"], "科陆电子")
            self.assertEqual(payload["external_signal_stream"]["signals"][0]["status"], "券商研报")
            self.assertEqual(payload["streaming_snapshot"]["status"], "fresh")
            self.assertEqual(payload["streaming_snapshot"]["top_companies"][0]["company_name"], "科陆电子")
            self.assertEqual(payload["streaming_timeline"]["status"], "fresh")
            self.assertEqual(payload["streaming_heatmap"]["status"], "fresh")
            self.assertEqual(payload["charts"][1]["title"], "子行业外部信号热度迁移")
            self.assertEqual(payload["attention_matrix"][0]["company_name"], "科陆电子")
            self.assertEqual(payload["attention_matrix"][0]["external_heat"], 4)
            self.assertEqual(payload["attention_matrix"][0]["active_days"], 2)
            self.assertEqual(payload["attention_matrix"][0]["signal_status"], "券商研报")
            self.assertEqual(payload["streaming_anomalies"]["status"], "fresh")
            self.assertGreaterEqual(payload["streaming_anomalies"]["summary"]["detected_count"], 1)
            self.assertIn(
                payload["streaming_anomalies"]["items"][0]["anomaly_type"],
                {"新发脉冲", "风险共振", "板块传导", "跨源汇聚", "持续抬升"},
            )
            self.assertGreater(payload["streaming_anomalies"]["items"][0]["score"], 0)
            self.assertIn(
                payload["attention_matrix"][0]["anomaly_severity"],
                {"critical", "high", "medium", "low"},
            )
            self.assertEqual(payload["sector_tags"][0]["label"], "储能")
            self.assertTrue(any(item["label"] == "外部信号" for item in payload["market_tape"]))
            self.assertTrue(any(item["label"] == "流式异动" for item in payload["market_tape"]))
            self.assertEqual(payload["brain_signal_tape"][3]["label"], "科陆电子")

    def test_industry_brain_surfaces_kafka_signal_runtime(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                for item in self.list_companies(report_period):
                    if item["company_name"] == company_name:
                        return item
                return None

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "科陆电子",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 8.0, "C3": 11.0, "S4": 0.82},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }
                ]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

            def list_company_names(self) -> list[str]:
                return ["科陆电子"]

        class FakeTopicPartition:
            def __init__(self, topic: str, partition: int) -> None:
                self.topic = topic
                self.partition = partition

            def __hash__(self) -> int:
                return hash((self.topic, self.partition))

            def __eq__(self, other: object) -> bool:
                if not isinstance(other, FakeTopicPartition):
                    return False
                return (self.topic, self.partition) == (other.topic, other.partition)

        class FakeRecord:
            def __init__(self, payload: dict[str, object], *, partition: int, offset: int) -> None:
                self.value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.partition = partition
                self.offset = offset

        class FakeKafkaConsumer:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN003, ANN002
                self._assigned: list[FakeTopicPartition] = []

            def partitions_for_topic(self, topic: str) -> set[int]:
                return {0, 1}

            def end_offsets(
                self,
                partitions: list[FakeTopicPartition],
            ) -> dict[FakeTopicPartition, int]:
                return {
                    partitions[0]: 12,
                    partitions[1]: 9,
                }

            def assign(self, partitions: list[FakeTopicPartition]) -> None:
                self._assigned = partitions

            def seek(self, partition: FakeTopicPartition, offset: int) -> None:
                return None

            def poll(
                self,
                timeout_ms: int = 0,
                max_records: int | None = None,
            ) -> dict[FakeTopicPartition, list[FakeRecord]]:
                partition = self._assigned[0]
                payload = {
                    "company_name": "科陆电子" if partition.partition == 1 else "国轩高科",
                    "headline": "储能业务景气度回升" if partition.partition == 1 else "行业链报价平稳",
                    "publish_date": date.today().isoformat(),
                    "event_time": f"{date.today().isoformat()}T08:00:00+00:00",
                    "signal_status": "券商研报" if partition.partition == 1 else "行业研报",
                }
                return {
                    partition: [
                        FakeRecord(payload, partition=partition.partition, offset=8 if partition.partition == 1 else 11)
                    ]
                }

            def close(self) -> None:
                return None

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for prefix in ("raw", "bronze", "silver", "gold"):
                (root / prefix / "official" / "manifests").mkdir(parents=True, exist_ok=True)

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0
                kafka_bootstrap_servers = "127.0.0.1:19092"
                kafka_signal_topic = "opspilot.external_signals"

                def __init__(self) -> None:
                    self.sample_data_path = Path(__file__).resolve().parents[1] / "data" / "bootstrap"
                    self.official_data_path = root / "raw" / "official"
                    self.bronze_data_path = root / "bronze" / "official"
                    self.silver_data_path = root / "silver" / "official"
                    self.gold_data_path = root / "gold" / "official"

            with patch("opspilot.application.services.KafkaConsumer", FakeKafkaConsumer), patch(
                "opspilot.application.services.TopicPartition",
                FakeTopicPartition,
            ):
                service = OpsPilotService(StubRepository(), StubSettings())
                payload = service.industry_brain()

            self.assertEqual(payload["kafka_signal_runtime"]["status"], "fresh")
            self.assertEqual(payload["kafka_signal_runtime"]["message_count"], 21)
            self.assertEqual(payload["kafka_signal_runtime"]["latest_company_name"], "科陆电子")
            self.assertEqual(payload["kafka_signal_runtime"]["latest_signal_status"], "券商研报")
            self.assertTrue(any(item["label"] == "Kafka 主题" for item in payload["market_tape"]))
            self.assertTrue(any(item["label"] == "实时流状态" for item in payload["market_tape"]))

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

    async def test_company_stress_test_returns_real_propagation_payload(self) -> None:
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
                    "metrics": {"G1": -6.0, "G2": -8.0, "C3": 12.5, "S4": 0.78, "S1": 1.04},
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
                        "metrics": {"G1": 8.0, "G2": 9.0, "C3": 2.1, "S4": 1.2, "S1": 1.4},
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
            with patch(
                "opspilot.application.agents.run_stress_agent",
                new=AsyncMock(return_value={}),
            ):
                payload = await service.company_stress_test(
                    "测试公司",
                    "欧盟对动力电池临时加征关税并限制关键材料进口",
                    user_role="management",
                )

            self.assertEqual(payload["company_name"], "测试公司")
            self.assertEqual(payload["report_period"], "2025Q3")
            self.assertEqual(payload["severity"]["level"], "CRITICAL")
            self.assertEqual(len(payload["propagation_steps"]), 4)
            self.assertTrue(payload["stress_wavefront"])
            self.assertIn("active_stage", payload["stress_wavefront"][0])
            self.assertTrue(payload["stress_impact_tape"])
            self.assertIn("intensity", payload["stress_impact_tape"][0])
            self.assertIn("stress_command_surface", payload)
            self.assertIn("impact_score", payload["stress_command_surface"])
            self.assertTrue(payload["stress_recovery_sequence"])
            self.assertTrue(payload["actions"])
            self.assertTrue(payload["chart"])
            self.assertIn("run_id", payload)
            self.assertTrue((root / "bronze" / "manifests" / "stress_test_runs.json").exists())

            runs = service.stress_test_runs(
                company_name="测试公司",
                report_period="2025Q3",
                user_role="management",
            )
            self.assertEqual(runs["total"], 1)
            detail = service.stress_test_run_detail(payload["run_id"])
            self.assertEqual(detail["run_meta"]["company_name"], "测试公司")

    async def test_company_stress_test_accepts_percent_impact_scores(self) -> None:
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
                    "metrics": {"G1": -6.0, "G2": -8.0, "C3": 12.5, "S4": 0.78, "S1": 1.04},
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
                        "metrics": {"G1": 8.0, "G2": 9.0, "C3": 2.1, "S4": 1.2, "S1": 1.4},
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
            with patch(
                "opspilot.application.agents.run_stress_agent",
                new=AsyncMock(
                    return_value={
                        "severity": {"level": "HIGH", "label": "高风险冲击", "color": "risk"},
                        "propagation_steps": [
                            {"step": 1, "title": "冲击启动", "detail": "外部冲击触发"},
                            {"step": 2, "title": "上游传导", "detail": "材料价格抬升"},
                            {"step": 3, "title": "生产环节", "detail": "产线排期受压"},
                        ],
                        "transmission_matrix": [
                            {"stage": "upstream", "headline": "原材料成本抬升", "impact_score": "-8%", "impact_label": "采购压力", "tone": "risk"},
                            {"stage": "midstream", "headline": "产能利用率下降", "impact_score": "-5%", "impact_label": "营收波动", "tone": "warning"},
                            {"stage": "downstream", "headline": "回款账期延长", "impact_score": "-3%", "impact_label": "现金流压力", "tone": "warning"},
                        ],
                        "simulation_log": [
                            {"step": 1, "title": "系统预警触发", "detail": "开始评估"},
                            {"step": 2, "title": "风险识别完成", "detail": "完成识别"},
                            {"step": 3, "title": "影响估算", "detail": "输出估算"},
                        ],
                    }
                ),
            ):
                payload = await service.company_stress_test(
                    "测试公司",
                    "关键供应商停产两周导致交付延迟",
                    user_role="management",
                )

            self.assertEqual(payload["stress_command_surface"]["impact_score"], 8)
            self.assertEqual(payload["stress_command_surface"]["energy_curve"], [8, 5, 3])
            self.assertEqual(payload["chart"]["series"][0]["data"][:3], [8, 5, 3])
            self.assertEqual(payload["stress_wavefront"][0]["impact_score"], 8)
            self.assertEqual(payload["stress_impact_tape"][0]["intensity"], 26)

    async def test_company_stress_test_rejects_english_agent_payload(self) -> None:
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
                    "metrics": {"G1": -6.0, "G2": -8.0, "C3": 12.5, "S4": 0.78, "S1": 1.04},
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
                        "metrics": {"G1": 8.0, "G2": 9.0, "C3": 2.1, "S4": 1.2, "S1": 1.4},
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
            with patch(
                "opspilot.application.agents.run_stress_agent",
                new=AsyncMock(
                    return_value={
                        "severity": {"level": "HIGH", "label": "High Risk", "color": "risk"},
                        "propagation_steps": [
                            {"step": 1, "title": "Initial Tariff Implementation", "detail": "Temporary tariffs are imposed."},
                            {"step": 2, "title": "Supply Chain Disruption", "detail": "Material imports are constrained."},
                        ],
                        "transmission_matrix": [
                            {
                                "stage": "upstream",
                                "headline": "Material Supply Constraints",
                                "impact_score": "-8%",
                                "impact_label": "Severe",
                                "tone": "risk",
                            },
                            {
                                "stage": "midstream",
                                "headline": "Production Delays",
                                "impact_score": "-5%",
                                "impact_label": "Moderate",
                                "tone": "warning",
                            },
                        ],
                        "simulation_log": [
                            {"step": 1, "title": "Market Reaction", "detail": "Stress scenario initiated."},
                        ],
                    }
                ),
            ):
                payload = await service.company_stress_test(
                    "测试公司",
                    "欧盟对动力电池临时加征关税并限制关键材料进口",
                    user_role="management",
                )

            self.assertIn(payload["severity"]["level"], {"HIGH", "CRITICAL", "MEDIUM"})
            self.assertEqual(payload["transmission_matrix"][0]["stage"], "上游")
            self.assertNotIn("High", payload["severity"]["label"])
            self.assertNotIn("Material", payload["stress_command_surface"]["headline"])
            self.assertNotIn("Initial", payload["propagation_steps"][0]["title"])
            self.assertEqual(payload["propagation_steps"][0]["title"], "注入冲击")
            self.assertEqual(payload["simulation_log"][0]["title"], "初始化")

    def test_company_graph_query_returns_intent_driven_path(self) -> None:
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
                    "metrics": {"G1": -6.0, "G2": -8.0, "C3": 12.5, "S4": 0.78, "S1": 1.04},
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
                        "metrics": {"G1": 8.0, "G2": 9.0, "C3": 2.1, "S4": 1.2, "S1": 1.4},
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
            with (
                patch.object(service, "company_timeline", side_effect=AssertionError("图谱查询不应加载时间轴面板")),
                patch.object(service, "benchmark_company", side_effect=AssertionError("图谱查询不应加载对标面板")),
                patch.object(service, "company_runtime_capsule", side_effect=AssertionError("图谱查询不应加载运行胶囊")),
                patch.object(service, "company_intelligence_runtime", side_effect=AssertionError("图谱查询不应加载情报运行态")),
            ):
                payload = service.company_graph_query(
                    "测试公司",
                    "应收扩张和风险传导",
                    user_role="management",
                )

            self.assertEqual(payload["company_name"], "测试公司")
            self.assertIn("run_id", payload)
            self.assertTrue(payload["focal_nodes"])
            self.assertGreaterEqual(len(payload["inference_path"]), 3)
            self.assertTrue(payload["graph_live_frames"])
            self.assertIn("active_nodes", payload["graph_live_frames"][0])
            self.assertTrue(payload["graph_signal_tape"])
            self.assertIn("intensity", payload["graph_signal_tape"][0])
            self.assertIn("graph_command_surface", payload)
            self.assertIn("graph_route_bands", payload)
            self.assertTrue(payload["graph_route_bands"])
            self.assertEqual(payload["inference_path"][0]["title"], "测试公司")
            self.assertIn("动作收口", payload["inference_path"][-1]["title"])
            self.assertIn("graph_retrieval", payload)
            self.assertGreaterEqual(payload["graph_retrieval"]["query_term_count"], 2)
            self.assertGreaterEqual(payload["graph_retrieval"]["path_count"], 1)
            self.assertIn("风险", "".join(payload["graph_retrieval"]["query_terms"]))
            self.assertIn("rank_explain", payload["focal_nodes"][0])
            self.assertIn("links", payload["evidence_navigation"])
            self.assertTrue(payload["graph"]["nodes"])
            self.assertTrue(payload["graph"]["edges"])
            self.assertGreaterEqual(payload["graph"]["retrieved_path_count"], 1)
            self.assertTrue((root / "bronze" / "manifests" / "graph_query_runs.json").exists())

            runs = service.graph_query_runs(
                company_name="测试公司",
                report_period="2025Q3",
                user_role="management",
            )
            self.assertEqual(runs["total"], 1)
            detail = service.graph_query_run_detail(payload["run_id"])
            self.assertEqual(detail["run_meta"]["company_name"], "测试公司")

            history = service.workspace_history(user_role="management", report_period="2025Q3")
            self.assertTrue(any(item["history_type"] == "graph_query" for item in history["records"]))

            execution_stream = service.company_execution_stream(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            self.assertIn("graph_query", {item["stream_type"] for item in execution_stream["records"]})

    def test_company_graph_query_surfaces_temporal_signal_context(self) -> None:
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
                    "metrics": {"G1": 6.0, "G2": 4.0, "C3": 3.8, "S4": 0.96, "S1": 1.12},
                    "history": [],
                    "metric_evidence": {},
                    "formula_context": {},
                    "label_evidence": {},
                }

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

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bronze" / "manifests").mkdir(parents=True, exist_ok=True)
            (root / "silver" / "stream").mkdir(parents=True, exist_ok=True)
            (root / "gold" / "stream").mkdir(parents=True, exist_ok=True)

            (root / "silver" / "stream" / "company_signal_snapshot.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-31T00:00:00+00:00",
                        "record_count": 1,
                        "records": [
                            {
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "subindustry": "储能",
                                "latest_event_time": "2026-03-31T00:00:00+00:00",
                                "latest_headline": "测试公司公司快照更新",
                                "latest_signal_kind": "company_snapshot",
                                "latest_signal_status": "公司快照",
                                "signal_count": 3,
                                "source_count": 2,
                                "external_heat": 7,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            timeline_payload = {
                "generated_at": "2026-03-31T00:00:00+00:00",
                "record_count": 1,
                "date_axis": [
                    "2026-03-25",
                    "2026-03-26",
                    "2026-03-27",
                    "2026-03-28",
                    "2026-03-29",
                    "2026-03-30",
                    "2026-03-31",
                ],
                "top_companies": [
                    {
                        "company_name": "测试公司",
                        "security_code": "000001",
                        "subindustry": "储能",
                        "latest_event_time": "2026-03-31T00:00:00+00:00",
                        "latest_headline": "测试公司公司快照更新",
                        "latest_signal_kind": "company_snapshot",
                        "latest_signal_status": "公司快照",
                        "latest_heat": 5,
                        "signal_count": 3,
                        "total_heat": 7,
                        "active_days": 2,
                        "momentum": 4,
                        "timeline": [
                            {"date": "2026-03-25", "signal_count": 0, "external_heat": 0},
                            {"date": "2026-03-26", "signal_count": 0, "external_heat": 0},
                            {"date": "2026-03-27", "signal_count": 1, "external_heat": 2},
                            {"date": "2026-03-28", "signal_count": 0, "external_heat": 0},
                            {"date": "2026-03-29", "signal_count": 0, "external_heat": 0},
                            {"date": "2026-03-30", "signal_count": 1, "external_heat": 0},
                            {"date": "2026-03-31", "signal_count": 1, "external_heat": 5},
                        ],
                    }
                ],
            }
            (root / "gold" / "stream" / "company_signal_timeline.json").write_text(
                json.dumps(timeline_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "gold" / "stream" / "subindustry_signal_heatmap.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-31T00:00:00+00:00",
                        "record_count": 1,
                        "date_axis": timeline_payload["date_axis"],
                        "top_subindustries": [
                            {
                                "subindustry": "储能",
                                "signal_count": 8,
                                "total_heat": 12,
                                "latest_heat": 8,
                                "active_days": 2,
                                "momentum": 6,
                                "timeline": [
                                    {"date": "2026-03-25", "signal_count": 0, "external_heat": 0},
                                    {"date": "2026-03-26", "signal_count": 0, "external_heat": 0},
                                    {"date": "2026-03-27", "signal_count": 1, "external_heat": 2},
                                    {"date": "2026-03-28", "signal_count": 0, "external_heat": 0},
                                    {"date": "2026-03-29", "signal_count": 1, "external_heat": 2},
                                    {"date": "2026-03-30", "signal_count": 2, "external_heat": 0},
                                    {"date": "2026-03-31", "signal_count": 4, "external_heat": 8},
                                ],
                            }
                        ],
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

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"
                    self.gold_data_path = root / "gold"

            service = OpsPilotService(StubRepository(), StubSettings())
            payload = service.company_graph_query(
                "测试公司",
                "最近实时异动和供应链传导",
                user_role="management",
            )

            node_types = {item["type"] for item in payload["graph"]["nodes"]}
            self.assertIn("signal_event", node_types)
            self.assertIn("signal_timeline", node_types)
            self.assertIn("subindustry_signal", node_types)
            self.assertEqual(payload["graph_retrieval"]["signal_count"], 3)
            self.assertEqual(payload["graph_retrieval"]["max_momentum"], 4)
            self.assertEqual(payload["graph_retrieval"]["time_window_days"], 7)
            self.assertIn(payload["graph_retrieval"]["freshness_status"], {"fresh", "recent"})
            self.assertTrue(any(item["label"] == "信号时效" for item in payload["graph_command_surface"]["watch_items"]))
            self.assertTrue(any(item["label"] == "最新事件" for item in payload["signal_stream"]))
            self.assertIn("最近信号", payload["inference_path"][1]["detail"])

    def test_document_pipeline_results_tolerates_broken_manifest_json(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return []

            def list_company_names(self) -> list[str]:
                return []

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bronze_manifests = root / "bronze" / "manifests"
            bronze_manifests.mkdir(parents=True, exist_ok=True)
            (bronze_manifests / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps({"records": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (bronze_manifests / "document_pipeline_jobs.json").write_text(
                '{"records":[{"stage":"cross_page_merge","report_id":"bad"',
                encoding="utf-8",
            )

            class StubSettings:
                app_name = "OpsPilot"
                env = "test"
                default_period = "2025Q3"
                audit_min_evidence = 0
                doc_layout_engine = "PP-DocLayout-V3"
                ocr_provider = "PaddleOCR-VL"
                ocr_model = "PaddleOCR-VL-1.5"
                ocr_runtime_enabled = False

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())

            payload = service.document_pipeline_results()

            self.assertEqual(payload["total"], 0)
            self.assertEqual(payload["results"], [])

    async def test_chat_turn_returns_role_driven_workspace_payload(self) -> None:
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

            service = OpsPilotService(StubRepository(), StubSettings())
            with patch(
                "opspilot.application.agents.run_orchestrator",
                new=AsyncMock(return_value=service.score_company("测试公司", "2025Q3")),
            ):
                payload = await service.chat_turn(
                    query="请给测试公司做一份经营体检评分",
                    company_name="测试公司",
                    user_role="management",
                )

            self.assertEqual(payload["role_profile"]["label"], "企业管理者")
            self.assertEqual(len(payload["agent_flow"]), 4)
            self.assertTrue(payload["answer_sections"])
            self.assertEqual(payload["answer_sections"][0]["title"], "当前判断")
            self.assertEqual(payload["answer_sections"][1]["title"], "为什么这样看")
            self.assertEqual(payload["answer_sections"][2]["title"], "先做什么")
            self.assertTrue(payload["follow_up_questions"])
            self.assertEqual(payload["insight_cards"][0]["label"], "总分")
            self.assertEqual(payload["control_plane"]["query_type"], "company_scoring")
            self.assertEqual(payload["control_plane"]["steps_completed"], 4)
            self.assertIn("真实财报指标", payload["control_plane"]["data_sources"])
            self.assertIn("assurance_label", payload["control_plane"])
            self.assertEqual(payload["control_plane"]["result_label"], "经营体检")
            self.assertEqual(payload["ai_assurance"]["status"], "review")
            self.assertEqual(payload["ai_assurance"]["tool_call_count"], 0)
            self.assertEqual(payload["agent_flow"][0]["tool"], "intent_router")
            self.assertEqual(payload["agent_flow"][0]["route"]["path"], "/score")
            self.assertEqual(payload["agent_flow"][1]["tool"], "score_engine")
            self.assertEqual(payload["agent_flow"][2]["tool"], "evidence_auditor")
            self.assertIn(
                payload["agent_flow"][2]["route"]["path"],
                ("/admin", "/score"),
            )
            self.assertEqual(payload["agent_flow"][3]["tool"], "action_planner")
            self.assertIn("run_id", payload)
            self.assertTrue((root / "bronze" / "manifests" / "workspace_runs.json").exists())

    async def test_chat_turn_fails_fast_when_llm_unavailable(self) -> None:
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
                openai_api_key = "invalid"
                postgres_dsn = "postgresql://user:pass@localhost:5432/test"

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            with patch(
                "opspilot.application.agents.generate_completion",
                new=AsyncMock(side_effect=RuntimeError("401 invalid token")),
            ):
                with self.assertRaisesRegex(RuntimeError, "协同分析依赖的大模型调用失败"):
                    await service.chat_turn(
                        query="请分析测试公司的经营表现和风险",
                        company_name="测试公司",
                        user_role="management",
                    )

    async def test_chat_turn_fails_fast_when_hybrid_rag_unavailable(self) -> None:
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
                return [self.get_company("测试公司", "2025Q3")]

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
                openai_api_key = "invalid"
                postgres_dsn = "postgresql://user:pass@localhost:5432/test"

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = root / "bronze"
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            with patch(
                "opspilot.application.agents.run_orchestrator",
                new=AsyncMock(
                    return_value={
                        **service.score_company("测试公司", "2025Q3"),
                        "query_type": "metric_query",
                        "tool_trace": [
                            {
                                "tool_name": "tool_score_company",
                                "arguments": {"company_name": "测试公司", "report_period": "2025Q3"},
                                "result_summary": "{}",
                                "elapsed_ms": 10.0,
                                "success": True,
                            }
                        ],
                    }
                ),
            ), patch.object(
                service.repository,
                "hybrid_evidence_search",
                new=AsyncMock(side_effect=RuntimeError("embedding provider unavailable")),
                create=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "embedding provider unavailable"):
                    await service.chat_turn(
                        query="请分析测试公司的经营表现和风险",
                        company_name="测试公司",
                        user_role="management",
                    )

    async def test_workspace_runs_persist_and_can_be_read_back(self) -> None:
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
            orchestrator_payload = {
                **service.score_company("测试公司", "2025Q3"),
                "query_type": "company_scoring",
                "tool_trace": [
                    {
                        "tool_name": "tool_score_company",
                        "arguments": {"company_name": "测试公司", "report_period": "2025Q3"},
                        "result_summary": "{\"total_score\": 81.0, \"grade\": \"A-\"}",
                        "elapsed_ms": 18.4,
                        "success": True,
                        "round_index": 1,
                        "executed_at": "2026-03-25T04:55:00+00:00",
                    }
                ],
                "agent_runtime": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                    "max_tool_rounds": 3,
                    "started_at": "2026-03-25T04:55:00+00:00",
                    "finished_at": "2026-03-25T04:55:01+00:00",
                    "completion_id": "chatcmpl-test",
                    "finish_reason": "stop",
                    "total_rounds": 2,
                    "llm_elapsed_ms": 621.0,
                    "tool_elapsed_ms": 18.4,
                    "total_elapsed_ms": 639.4,
                    "tool_call_count": 1,
                    "successful_tool_count": 1,
                    "failed_tool_count": 0,
                    "tool_round_count": 1,
                },
            }
            with patch(
                "opspilot.application.agents.run_orchestrator",
                new=AsyncMock(return_value=orchestrator_payload),
            ):
                payload = await service.chat_turn(
                    query="请给测试公司做一份经营体检评分",
                    company_name="测试公司",
                    user_role="management",
                )

            runs = service.workspace_runs(limit=5)
            detail = service.workspace_run_detail(payload["run_id"])

            self.assertEqual(runs["total"], 1)
            self.assertEqual(detail["run"]["run_id"], payload["run_id"])
            self.assertEqual(detail["detail"]["query"], "请给测试公司做一份经营体检评分")
            self.assertIn("ai_assurance", detail["detail"])
            self.assertEqual(payload["agent_runtime"]["model"], "gpt-4o-mini")
            self.assertEqual(payload["agent_runtime"]["tool_call_count"], 1)
            self.assertEqual(payload["agent_runtime"]["trace"][0]["tool_label"], "企业评分")
            self.assertEqual(payload["control_plane"]["model"], "gpt-4o-mini")
            self.assertEqual(detail["detail"]["agent_runtime"]["completion_id"], "chatcmpl-test")
            self.assertEqual(detail["detail"]["tool_trace"][0]["tool_name"], "tool_score_company")

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
            self.assertEqual(refreshed_task["status_label"], "处理中")
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

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
            self.assertEqual(refreshed_alert["status_label"], "处理中")
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

            dispatch = service.dispatch_watchboard_alerts(
                user_role="management",
                report_period="2025Q3",
                limit=5,
            )
            self.assertEqual(dispatch["summary"]["dispatched_alerts"], 1)
            self.assertEqual(dispatch["dispatched"][0]["company_name"], "测试公司")
            self.assertEqual(dispatch["alert_board"]["summary"]["dispatched"], 1)

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
            self.assertIsNone(results["results"][0]["artifact_source"])

            detail = service.document_pipeline_result_detail("title_hierarchy", "r-1")
            self.assertEqual(detail["job"]["report_id"], "r-1")
            self.assertTrue(detail["artifact"]["headings"])
            self.assertTrue(detail["consumable_sections"])
            self.assertEqual(detail["consumable_sections"][0]["section_type"], "heading_outline")
            self.assertEqual(detail["artifact_locations"][0]["kind"], "artifact")
            self.assertTrue(detail["remediation"])

    def test_document_pipeline_result_detail_handles_malformed_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bronze = root / "bronze" / "official"
            manifests = bronze / "manifests"
            upgrades = bronze / "upgrades"
            manifests.mkdir(parents=True, exist_ok=True)
            upgrades.mkdir(parents=True, exist_ok=True)
            bad_artifact = upgrades / "bad.json"
            bad_artifact.write_text('{"broken": true', encoding="utf-8")
            (manifests / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-bad",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2025年三季度报告",
                                "page_json_path": str(upgrades / "page.json"),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests / "document_pipeline_jobs.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-bad",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "stage": "title_hierarchy",
                                "status": "completed",
                                "artifact_path": str(bad_artifact),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class StubRepository:
                def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                    return []

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
            with self.assertRaisesRegex(ValueError, "解析产物损坏"):
                service.document_pipeline_result_detail("title_hierarchy", "r-bad")

    def test_company_vision_analyze_returns_consumable_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bronze = root / "bronze" / "official"
            manifests = bronze / "manifests"
            upgrades = bronze / "upgrades" / "title_hierarchy"
            manifests.mkdir(parents=True, exist_ok=True)
            upgrades.mkdir(parents=True, exist_ok=True)
            artifact_path = upgrades / "r-vision.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "report_id": "r-vision",
                        "summary": "目录恢复完成",
                        "headings": [{"level": 1, "text": "第一节", "page": 1}],
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
                                "report_id": "r-vision",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2025年三季度报告",
                                "report_period": "2025Q3",
                                "page_json_path": str(upgrades / "page.json"),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests / "document_pipeline_jobs.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-vision",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "report_period": "2025Q3",
                                "stage": "title_hierarchy",
                                "status": "completed",
                                "artifact_path": str(artifact_path),
                                "artifact_summary": "目录恢复完成",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            class StubRepository:
                def preferred_period(self) -> str:
                    return "2025Q3"

                def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                    return {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 12.0, "G2": 8.0, "C1": 1.2, "C3": 24.0, "S1": 1.1, "S4": 0.9},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }

                def list_companies(self, report_period: str | None = None) -> list[dict]:
                    return [self.get_company("测试公司", "2025Q3")]

                def list_company_periods(self, company_name: str) -> list[str]:
                    return ["2025Q3"]

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
                ocr_runtime_enabled = False

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = bronze
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            payload = service.run_company_vision_analyze("测试公司", "2025Q3", user_role="management")
            self.assertIn("run_id", payload)
            self.assertEqual(payload["result"]["company_name"], "测试公司")
            self.assertEqual(payload["result"]["status_label"], "已生成")
            self.assertTrue(payload["result"]["items"])
            self.assertTrue(payload["result"]["sections"])
            self.assertEqual(payload["result"]["items"][0]["stage_label"], "标题层级")
            self.assertEqual(payload["result"]["quality_summary"]["status"], "blocked")
            self.assertEqual(payload["result"]["quality_summary"]["stage_label"], "标题层级")
            self.assertTrue((bronze / "manifests" / "vision_analyze_runs.json").exists())

            runs = service.vision_runs(
                company_name="测试公司",
                report_period="2025Q3",
                user_role="management",
            )
            self.assertEqual(runs["total"], 1)
            detail = service.vision_run_detail(payload["run_id"])
            self.assertEqual(detail["run_meta"]["company_name"], "测试公司")

            history = service.workspace_history(user_role="management", report_period="2025Q3")
            self.assertTrue(any(item["history_type"] == "vision_analyze" for item in history["records"]))

            execution_stream = service.company_execution_stream(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            self.assertIn("vision_analyze", {item["stream_type"] for item in execution_stream["records"]})

    def test_company_vision_runtime_and_pipeline_return_stage_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bronze = root / "bronze" / "official"
            manifests = bronze / "manifests"
            upgrades = bronze / "upgrades"
            manifests.mkdir(parents=True, exist_ok=True)
            (upgrades / "cross_page_merge").mkdir(parents=True, exist_ok=True)
            (upgrades / "title_hierarchy").mkdir(parents=True, exist_ok=True)
            title_artifact_path = upgrades / "title_hierarchy" / "r-runtime.json"
            page_json_path = upgrades / "page.json"
            page_json_path.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [
                                    {"text": "第一节 经营情况"},
                                    {"text": "第二节 财务摘要"},
                                ],
                            },
                            {
                                "page": 2,
                                "blocks": [
                                    {"text": "续表：主营业务收入"},
                                ],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            title_artifact_path.write_text(
                json.dumps(
                    {
                        "report_id": "r-runtime",
                        "summary": "目录恢复完成",
                        "headings": [{"level": 1, "text": "第一节", "page": 1}],
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
                                "report_id": "r-runtime",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "title": "测试公司2025年三季度报告",
                                "report_period": "2025Q3",
                                "page_json_path": str(page_json_path),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (manifests / "document_pipeline_jobs.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-runtime",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "report_period": "2025Q3",
                                "stage": "cross_page_merge",
                                "status": "pending",
                                "artifact_path": "",
                                "artifact_summary": None,
                            },
                            {
                                "report_id": "r-runtime",
                                "company_name": "测试公司",
                                "security_code": "000001",
                                "report_period": "2025Q3",
                                "stage": "title_hierarchy",
                                "status": "completed",
                                "artifact_path": str(title_artifact_path),
                                "artifact_summary": "目录恢复完成",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

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
                        "metrics": {
                            "G1": 12.0,
                            "G2": 8.0,
                            "C1": 1.2,
                            "C3": 24.0,
                            "S1": 1.1,
                            "S4": 0.9,
                        },
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }

                def list_companies(self, report_period: str | None = None) -> list[dict]:
                    return [self.get_company("测试公司", "2025Q3")]

                def list_company_periods(self, company_name: str) -> list[str]:
                    return ["2025Q3"]

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
                doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
                ocr_provider = "PaddleOCR-VL"
                ocr_model = "PaddleOCR-VL-1.5"
                ocr_runtime_enabled = False

                def __init__(self) -> None:
                    self.official_data_path = root / "raw"
                    self.bronze_data_path = bronze
                    self.silver_data_path = root / "silver"

            service = OpsPilotService(StubRepository(), StubSettings())
            runtime_before = service.company_vision_runtime(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            self.assertEqual(runtime_before["runtime"]["provider"], "PaddleOCR-VL")
            self.assertEqual(runtime_before["runtime"]["model"], "PaddleOCR-VL-1.5")
            self.assertFalse(runtime_before["runtime"]["runtime_enabled"])
            self.assertEqual(runtime_before["stages"][0]["label"], "跨页拼接")
            self.assertTrue(any(item["status"] == "pending" for item in runtime_before["stages"]))
            self.assertFalse(any(item["status"] == "blocked" for item in runtime_before["stages"]))
            self.assertEqual(runtime_before["runtime"]["next_action"], "接通正式 OCR 运行时后再执行财报扫描")

            pipeline_result = service.run_company_vision_pipeline(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            self.assertIn("vision_run_id", pipeline_result)
            self.assertTrue(pipeline_result["executed"])
            self.assertTrue(pipeline_result["runtime"]["vision"]["sections"])
            self.assertTrue(any(item["status"] == "blocked" for item in pipeline_result["executed"]))

            runtime_after = service.company_vision_runtime(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            stage_status = {item["stage"]: item["status"] for item in runtime_after["stages"]}
            self.assertEqual(stage_status["cross_page_merge"], "completed")
            self.assertEqual(stage_status["title_hierarchy"], "completed")
            self.assertEqual(stage_status["cell_trace"], "blocked")
            cell_trace_stage = next(item for item in runtime_after["stages"] if item["stage"] == "cell_trace")
            self.assertEqual(cell_trace_stage["contract_status"], "missing")
            self.assertEqual(runtime_after["runtime"]["next_action"], "接通正式 OCR 运行时后再执行财报扫描")
            self.assertEqual(runtime_after["vision"]["quality_summary"]["status"], "blocked")
            self.assertTrue(
                any("标准 OCR" in item["title"] for item in runtime_after["vision"]["quality_summary"]["blockers"])
            )

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
            (root / "bronze" / "manifests" / "workspace_watchboard.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "company_name": "测试公司",
                                "user_role": "management",
                                "report_period": "2025Q3",
                                "note": "重点盯防现金链",
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
            intelligence_runtime = service.company_intelligence_runtime(
                "测试公司",
                "2025Q3",
                user_role="management",
            )
            graph = service.company_graph("测试公司", "2025Q3", user_role="management")

            self.assertEqual(workspace["company_name"], "测试公司")
            self.assertIn(workspace["score_summary"]["grade"], {"A", "B", "C", "D"})
            self.assertEqual(workspace["research"]["status"], "missing")
            self.assertGreaterEqual(workspace["document_upgrades"]["count"], 1)
            self.assertTrue(
                any(item["stage"] == "title_hierarchy" for item in workspace["document_upgrades"]["items"])
            )
            detail_item = next(
                item for item in workspace["document_upgrades"]["items"] if item["stage"] == "title_hierarchy"
            )
            self.assertEqual(detail_item["route"]["path"], "/admin")
            self.assertEqual(detail_item["route"]["query"]["stage"], "title_hierarchy")
            self.assertEqual(detail_item["artifact_preview"]["headings"][0]["text"], "第一节")
            self.assertEqual(detail_item["evidence_navigation"]["count"], 0)
            self.assertEqual(detail_item["evidence_navigation"]["status"], "blocked")
            self.assertIsNone(detail_item["evidence_navigation"]["primary_route"])
            self.assertTrue(workspace["tasks"]["items"])
            self.assertTrue(workspace["alerts"]["items"])
            self.assertGreaterEqual(workspace["execution_stream"]["total"], 3)
            self.assertEqual(intelligence_runtime["company_name"], "测试公司")
            self.assertEqual(len(intelligence_runtime["module_pulses"]), 4)
            self.assertGreaterEqual(intelligence_runtime["runtime_bus"]["total"], 1)
            self.assertEqual(len(intelligence_runtime["runtime_bus"]["records"]), 4)
            self.assertTrue(
                any(item["module_key"] == "graph" and item["intensity"] >= 0 for item in intelligence_runtime["module_pulses"])
            )
            self.assertIn("intelligence_runtime", workspace)
            self.assertGreaterEqual(workspace["intelligence_runtime"]["runtime_bus"]["total"], 1)
            self.assertGreaterEqual(workspace["execution_stream"]["summary"]["document_upgrades"], 1)
            self.assertEqual(workspace["recent_runs"]["count"], 1)
            self.assertTrue(workspace["watchboard"]["tracked"])
            self.assertEqual(workspace["watchboard"]["note"], "重点盯防现金链")
            document_upgrades = service.company_document_upgrades("测试公司", "2025Q3")
            self.assertGreaterEqual(document_upgrades["count"], 1)
            self.assertEqual(document_upgrades["stage_summary"]["title_hierarchy"], 1)
            execution_stream = service.company_execution_stream("测试公司", "2025Q3", user_role="management")
            self.assertGreaterEqual(execution_stream["total"], 3)
            self.assertIn("document_upgrade", {item["stream_type"] for item in execution_stream["records"]})
            history = service.workspace_history(user_role="management", report_period="2025Q3")
            self.assertGreaterEqual(history["total"], 2)
            self.assertTrue(any(item["history_type"] == "analysis_run" for item in history["records"]))
            analysis_record = next(item for item in history["records"] if item["history_type"] == "analysis_run")
            self.assertEqual(analysis_record["meta"]["route"]["path"], "/api/v1/workspace/runs/run-1")
            document_record = next(item for item in history["records"] if item["history_type"] == "document_pipeline")
            self.assertIn("/api/v1/admin/document-pipeline/results/title_hierarchy/demo-report", document_record["meta"]["route"]["path"])
            overview = service.workspace_overview(user_role="management")
            self.assertIn("execution_bus_summary", overview)
            self.assertIn("execution_bus_records", overview)
            self.assertGreaterEqual(overview["execution_bus_summary"]["document_pipeline"]["total"], 1)
            self.assertGreaterEqual(overview["workspace_history"]["total"], 1)
            self.assertGreaterEqual(overview["execution_bus_records"]["total"], 3)
            task_record = next(
                item for item in overview["execution_bus_records"]["records"] if item["bus_type"] == "task"
            )
            self.assertEqual(task_record["type_label"], "任务推进")
            self.assertTrue(task_record["status_label"])
            self.assertEqual(graph["company_name"], "测试公司")
            self.assertGreaterEqual(graph["summary"]["node_count"], 5)
            self.assertGreaterEqual(graph["summary"]["edge_count"], 4)
            self.assertEqual(graph["summary"]["run_count"], 1)
            self.assertTrue(graph["summary"]["watch_tracked"])
            self.assertTrue(any(node["type"] == "execution_stream" for node in graph["nodes"]))

    def test_company_workspace_research_uses_source_name_when_institution_missing(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [
                    {
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "subindustry": "储能",
                        "metrics": {"G1": 12.0},
                        "history": [],
                        "metric_evidence": {},
                        "formula_context": {},
                        "label_evidence": {},
                    }
                ]

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
            score_payload = {
                "report_period": "2025Q3",
                "subindustry": "储能",
                "scorecard": {
                    "total_score": 82.0,
                    "grade": "A",
                    "subindustry_percentile": 91.0,
                    "risk_labels": [{"name": "现金流压力"}],
                    "opportunity_labels": [{"name": "储能订单扩张"}],
                },
                "action_cards": [],
                "formula_cards": [],
            }
            with (
                patch.object(service, "score_company", return_value=score_payload),
                patch.object(
                    service,
                    "company_timeline",
                    return_value={"latest_period": "2025Q3", "key_numbers": [], "snapshots": []},
                ),
                patch.object(service, "benchmark_company", return_value={"benchmark": []}),
                patch.object(service, "alert_workflow", return_value={"alerts": []}),
                patch.object(service, "task_board", return_value={"tasks": []}),
                patch.object(
                    service,
                    "company_document_upgrades",
                    return_value={"count": 0, "stage_summary": {}, "items": []},
                ),
                patch.object(
                    service,
                    "company_execution_stream",
                    return_value={"summary": {"document_upgrades": 0}, "total": 0, "records": []},
                ),
                patch.object(service, "workspace_runs", return_value={"runs": []}),
                patch.object(
                    service,
                    "company_intelligence_runtime",
                    return_value={"runtime_bus": {"total": 0, "records": []}, "module_pulses": []},
                ),
                patch.object(service, "company_runtime_capsule", return_value=None),
                patch.object(
                    service,
                    "verify_claim",
                    return_value={
                        "report_meta": {"title": "测试研报", "source_name": "测试证券"},
                        "claim_cards": [],
                        "forecast_cards": [],
                    },
                ),
                patch(
                    "opspilot.application.services._build_company_signal_graph_context",
                    return_value={"event_available": False},
                ),
            ):
                workspace = service.company_workspace("测试公司", "2025Q3", user_role="management")
                graph = service.company_graph(
                    "测试公司",
                    "2025Q3",
                    user_role="management",
                    workspace=workspace,
                )

            self.assertEqual(workspace["research"]["status"], "ready")
            self.assertEqual(workspace["research"]["institution"], "测试证券")
            research_node = next(node for node in graph["nodes"] if node["type"] == "research_report")
            self.assertEqual(research_node["meta"]["institution"], "测试证券")

    def test_workspace_overview_keeps_company_pool_when_risk_board_is_empty(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                if report_period is None:
                    return [
                        {"company_name": "测试公司", "report_period": "2025Q3"},
                        {"company_name": "对标公司", "report_period": "2024FY"},
                    ]
                return []

            def list_company_names(self) -> list[str]:
                return ["测试公司", "对标公司"]

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0

            def __init__(self, root: Path) -> None:
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"

        with TemporaryDirectory() as temp_dir:
            service = OpsPilotService(StubRepository(), StubSettings(Path(temp_dir)))
            overview = service.workspace_overview(user_role="management")

        self.assertEqual(overview["companies"], ["测试公司", "对标公司"])
        self.assertEqual(overview["alert_summary"]["total_alerts"], 0)

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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

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
            self.assertEqual(payload["document_pipeline"]["cell_trace"]["contract_audit"]["status"], "ready")
            self.assertEqual(payload["job_catalog"][0]["job_id"], "fetch_real_data")
            self.assertIn("企业评分", payload["capabilities"])
            self.assertIn("document_pipeline_jobs", payload)
            self.assertIn("delivery_readiness", payload)
            self.assertIn("runtime_readiness", payload)
            self.assertIn("acceptance_checklist", payload)
            self.assertEqual(payload["delivery_readiness"]["stage"], "bootstrapping")
            self.assertEqual(payload["delivery_readiness"]["contract_ratio"], 100)
            self.assertEqual(payload["runtime_readiness"]["status"], "ready")
            self.assertEqual(payload["acceptance_checklist"]["status"], "blocked")
            self.assertEqual(payload["acceptance_checklist"]["total"], 5)
            self.assertIn("innovation_radar", payload)
            self.assertIn("workspace_history", payload)
            self.assertIn("workspace_runtime_audit", payload)
            self.assertEqual(payload["streaming_runtime"]["status"], "unavailable")
            self.assertEqual(payload["workspace_runtime_audit"]["status"], "unavailable")
            self.assertGreaterEqual(payload["innovation_radar"]["summary"]["total"], 1)

            report = service.delivery_report()

            self.assertEqual(report["overall_status"], "blocked")
            self.assertEqual(report["delivery_readiness"]["stage_label"], "启动期")
            self.assertEqual(report["runtime_readiness"]["status_label"], "就绪")
            self.assertEqual(report["acceptance_checklist"]["status_label"], "阻断")
            self.assertTrue(report["executive_summary"])
            markdown = build_delivery_report_markdown(report)
            self.assertIn("# OpsPilot 运行周报", markdown)
            self.assertIn("## 执行摘要", markdown)
            self.assertIn("## 智能体执行审计", markdown)

    def test_admin_overview_surfaces_workspace_runtime_audit(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            (root / "bronze" / "runs").mkdir(parents=True, exist_ok=True)

            run_1_path = root / "bronze" / "runs" / "run-1.json"
            run_2_path = root / "bronze" / "runs" / "run-2.json"
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
                                "created_at": "2026-03-25T06:00:00+00:00",
                                "detail_path": str(run_1_path),
                                "agent_model": "gpt-4o-mini",
                                "tool_call_count": 1,
                                "execution_ms": 4820.5,
                            },
                            {
                                "run_id": "run-2",
                                "query": "测试公司当前最值得警惕的风险是什么？",
                                "company_name": "测试公司",
                                "report_period": "2025Q3",
                                "query_type": "risk_scan",
                                "user_role": "investor",
                                "created_at": "2026-03-25T05:40:00+00:00",
                                "detail_path": str(run_2_path),
                                "agent_model": "gpt-4o-mini",
                                "tool_call_count": 1,
                                "execution_ms": 4581.2,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            run_1_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "query": "请给测试公司做经营体检",
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "user_role": "management",
                        "query_type": "company_scoring",
                        "ai_assurance": {
                            "status": "grounded",
                            "label": "强支撑",
                            "evidence_count": 4,
                        },
                        "agent_runtime": {
                            "model": "gpt-4o-mini",
                            "tool_call_count": 1,
                            "llm_elapsed_ms": 4200.0,
                            "tool_elapsed_ms": 620.5,
                            "total_elapsed_ms": 4820.5,
                            "trace": [
                                {
                                    "tool_name": "tool_score_company",
                                    "tool_label": "企业评分",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            run_2_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-2",
                        "query": "测试公司当前最值得警惕的风险是什么？",
                        "company_name": "测试公司",
                        "report_period": "2025Q3",
                        "user_role": "investor",
                        "query_type": "risk_scan",
                        "ai_assurance": {
                            "status": "grounded",
                            "label": "强支撑",
                            "evidence_count": 3,
                        },
                        "agent_runtime": {
                            "model": "gpt-4o-mini",
                            "tool_call_count": 1,
                            "llm_elapsed_ms": 4011.0,
                            "tool_elapsed_ms": 570.2,
                            "total_elapsed_ms": 4581.2,
                            "trace": [
                                {
                                    "tool_name": "tool_risk_scan",
                                    "tool_label": "行业风险扫描",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            payload = service.admin_overview()

            self.assertEqual(payload["workspace_runtime_audit"]["status"], "stable")
            self.assertEqual(payload["workspace_runtime_audit"]["audited_runs"], 2)
            self.assertEqual(payload["workspace_runtime_audit"]["summary_cards"]["grounded_ratio"], 100)
            self.assertEqual(payload["workspace_runtime_audit"]["summary_cards"]["trace_ratio"], 100)
            self.assertEqual(payload["workspace_runtime_audit"]["model_mix"][0]["label"], "gpt-4o-mini")
            self.assertEqual(payload["workspace_runtime_audit"]["tool_mix"][0]["count"], 1)
            self.assertEqual(payload["workspace_runtime_audit"]["company_heat"][0]["company_name"], "测试公司")
            self.assertEqual(payload["workspace_runtime_audit"]["recent_runs"][0]["trace_status_label"], "完整")
            report = service.delivery_report()
            self.assertEqual(report["workspace_runtime_audit"]["status"], "stable")

    def test_admin_overview_surfaces_kafka_streaming_runtime(self) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return [{"company_name": "测试公司", "report_period": report_period or "2025Q3"}]

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

        class FakeTopicPartition:
            def __init__(self, topic: str, partition: int) -> None:
                self.topic = topic
                self.partition = partition

            def __hash__(self) -> int:
                return hash((self.topic, self.partition))

            def __eq__(self, other: object) -> bool:
                if not isinstance(other, FakeTopicPartition):
                    return False
                return (self.topic, self.partition) == (other.topic, other.partition)

        class FakeRecord:
            def __init__(self, payload: dict[str, object], *, partition: int, offset: int) -> None:
                self.value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.partition = partition
                self.offset = offset

        class FakeKafkaConsumer:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN003, ANN002
                self._assigned: list[FakeTopicPartition] = []

            def partitions_for_topic(self, topic: str) -> set[int]:
                return {0}

            def end_offsets(
                self,
                partitions: list[FakeTopicPartition],
            ) -> dict[FakeTopicPartition, int]:
                return {partitions[0]: 5}

            def assign(self, partitions: list[FakeTopicPartition]) -> None:
                self._assigned = partitions

            def seek(self, partition: FakeTopicPartition, offset: int) -> None:
                return None

            def poll(
                self,
                timeout_ms: int = 0,
                max_records: int | None = None,
            ) -> dict[FakeTopicPartition, list[FakeRecord]]:
                partition = self._assigned[0]
                payload = {
                    "company_name": "测试公司",
                    "headline": "正式外部信号已进入 Kafka",
                    "publish_date": date.today().isoformat(),
                    "event_time": f"{date.today().isoformat()}T08:00:00+00:00",
                    "signal_status": "交易所公告",
                }
                return {partition: [FakeRecord(payload, partition=partition.partition, offset=4)]}

            def close(self) -> None:
                return None

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"
            kafka_bootstrap_servers = "127.0.0.1:19092"
            kafka_signal_topic = "opspilot.external_signals"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.gold_data_path = root / "gold"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            (root / "universe").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver", "gold"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)

            with patch("opspilot.application.services.KafkaConsumer", FakeKafkaConsumer), patch(
                "opspilot.application.services.TopicPartition",
                FakeTopicPartition,
            ):
                service = OpsPilotService(StubRepository(), StubSettings(root))
                payload = service.admin_overview()

            self.assertEqual(payload["streaming_runtime"]["status"], "fresh")
            self.assertEqual(payload["streaming_runtime"]["message_count"], 5)
            self.assertEqual(payload["streaming_runtime"]["latest_company_name"], "测试公司")
            self.assertEqual(payload["streaming_runtime"]["latest_signal_status"], "交易所公告")

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
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

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

    def test_document_pipeline_cell_trace_creates_real_table_artifact(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-table.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [
                                    {"text": "一、主要财务数据", "bbox": [0, 0, 120, 12]},
                                    {"text": "项目 本报告期 年初至报告期末", "bbox": [0, 20, 240, 32]},
                                    {"text": "营业收入 100.5 320.8", "bbox": [0, 36, 240, 48]},
                                    {"text": "归母净利润 12.2 30.4", "bbox": [0, 52, 240, 64]},
                                ],
                            }
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
                                "report_id": "demo-table",
                                "page_json_path": str(page_json),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.run_document_pipeline_stage("cell_trace", 1)

            self.assertEqual(payload["processed"], 1)
            self.assertEqual(payload["results"][0]["status"], "blocked")
            self.assertEqual(payload["results"][0]["artifact_path"], "")
            self.assertIsNone(payload["results"][0]["source"])
            detail = service.document_pipeline_result_detail("cell_trace", "demo-table")
            self.assertEqual(detail["job"]["status"], "blocked")
            self.assertEqual(detail["artifact"]["tables"], [])
            self.assertIn("正式结构产物", detail["remediation"][0]["title"])

    def test_document_pipeline_cell_trace_prefers_standard_ocr_artifact(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-ocr.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps({"pages": [{"page": 1, "blocks": [{"text": "占位", "bbox": [0, 0, 1, 1]}]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            ocr_artifact = root / "bronze" / "upgrades" / "ocr_cell_trace" / "000001" / "demo-ocr.json"
            ocr_artifact.parent.mkdir(parents=True, exist_ok=True)
            ocr_artifact.write_text(
                json.dumps(
                    {
                        "summary": "读取 OCR 标准输出",
                        "tables": [{"table_id": "ocr-1", "page": 1, "title": "OCR表", "continued": False}],
                        "cells": [{"table_id": "ocr-1", "page": 1, "row_index": 1, "column_index": 1, "text": "营业收入"}],
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
                                "report_id": "demo-ocr",
                                "page_json_path": str(page_json),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.run_document_pipeline_stage("cell_trace", 1)

            artifact_path = Path(payload["results"][0]["artifact_path"])
            artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact_payload["source"], "standard_ocr")
            self.assertEqual(artifact_payload["tables"][0]["title"], "OCR表")
            self.assertEqual(artifact_payload["cells"][0]["text"], "营业收入")

            results = service.document_pipeline_results(stage="cell_trace")
            self.assertEqual(results["results"][0]["artifact_source"], "standard_ocr")

            detail = service.document_pipeline_result_detail("cell_trace", "demo-ocr")
            self.assertEqual(detail["job"]["artifact_source"], "standard_ocr")
            self.assertEqual(detail["consumable_sections"][0]["section_type"], "artifact_provenance")
            self.assertEqual(detail["consumable_sections"][0]["items"][0]["source"], "standard_ocr")
            self.assertEqual(detail["artifact_locations"][1]["kind"], "ocr_artifact")
            self.assertIn("ocr_cell_trace", detail["remediation"][0]["detail"])

    def test_document_pipeline_cell_trace_rejects_invalid_standard_ocr_artifact(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-invalid-ocr.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [
                                    {"text": "项目 本报告期 年初至报告期末", "bbox": [0, 20, 240, 32]},
                                    {"text": "营业收入 100.5 320.8", "bbox": [0, 36, 240, 48]},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ocr_artifact = root / "bronze" / "upgrades" / "ocr_cell_trace" / "000001" / "demo-invalid-ocr.json"
            ocr_artifact.parent.mkdir(parents=True, exist_ok=True)
            ocr_artifact.write_text(
                json.dumps(
                    {
                        "summary": "损坏的 OCR 输出",
                        "tables": [{"page": "1", "title": "坏表"}],
                        "cells": [{"table_id": "ocr-1", "page": 1, "row_index": 1, "column_index": 1}],
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
                                "report_id": "demo-invalid-ocr",
                                "page_json_path": str(page_json),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            payload = service.run_document_pipeline_stage("cell_trace", 1)

            self.assertEqual(payload["processed"], 1)
            self.assertEqual(payload["results"][0]["status"], "blocked")
            self.assertEqual(payload["results"][0]["artifact_path"], "")
            self.assertIsNone(payload["results"][0]["source"])
            detail = service.document_pipeline_result_detail("cell_trace", "demo-invalid-ocr")
            self.assertEqual(detail["job"]["status"], "blocked")
            self.assertIsNone(detail["job"]["artifact_source"])
            self.assertIn("补齐正式结构产物", detail["remediation"][0]["title"])

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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

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
            self.assertEqual(payload["delivery_readiness"]["stage"], "hardening")
            self.assertEqual(payload["delivery_readiness"]["ready_company_count"], 1)
            self.assertEqual(payload["delivery_readiness"]["blocked_company_count"], 1)
            self.assertEqual(payload["delivery_readiness"]["coverage_ratio"], 50)
            self.assertEqual(payload["delivery_readiness"]["contract_ratio"], 100)
            self.assertEqual(payload["runtime_readiness"]["status"], "ready")

    def test_admin_overview_audits_ocr_contract_statuses(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            (root / "bronze" / "manifests" / "parsed_periodic_reports_manifest.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "report_id": "r-ready",
                                "company_name": "甲公司",
                                "security_code": "000001",
                                "title": "甲公司2025年三季度报告",
                                "page_json_path": str(root / "bronze" / "pages" / "r-ready.json"),
                            },
                            {
                                "report_id": "r-invalid",
                                "company_name": "乙公司",
                                "security_code": "000002",
                                "title": "乙公司2025年三季度报告",
                                "page_json_path": str(root / "bronze" / "pages" / "r-invalid.json"),
                            },
                            {
                                "report_id": "r-missing",
                                "company_name": "丙公司",
                                "security_code": "000003",
                                "title": "丙公司2025年三季度报告",
                                "page_json_path": str(root / "bronze" / "pages" / "r-missing.json"),
                            },
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
                                "report_id": "r-ready",
                                "company_name": "甲公司",
                                "security_code": "000001",
                                "report_period": "2025Q3",
                                "stage": "cell_trace",
                                "status": "completed",
                                "artifact_path": str(root / "bronze" / "upgrades" / "cell_trace" / "000001" / "r-ready.json"),
                                "artifact_source": "standard_ocr",
                                "completed_at": "2026-03-24T10:00:00Z",
                            },
                            {
                                "report_id": "r-invalid",
                                "company_name": "乙公司",
                                "security_code": "000002",
                                "report_period": "2025Q3",
                                "stage": "cell_trace",
                                "status": "completed",
                                "artifact_path": str(root / "bronze" / "upgrades" / "cell_trace" / "000002" / "r-invalid.json"),
                                "artifact_source": "standard_ocr",
                                "completed_at": "2026-03-24T10:00:00Z",
                            },
                            {
                                "report_id": "r-missing",
                                "company_name": "丙公司",
                                "security_code": "000003",
                                "report_period": "2025Q3",
                                "stage": "cell_trace",
                                "status": "completed",
                                "artifact_path": str(root / "bronze" / "upgrades" / "cell_trace" / "000003" / "r-missing.json"),
                                "artifact_source": "geometric_fallback",
                                "completed_at": "2026-03-24T10:00:00Z",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ready = root / "bronze" / "upgrades" / "ocr_cell_trace" / "000001" / "r-ready.json"
            ready.parent.mkdir(parents=True, exist_ok=True)
            ready.write_text(
                json.dumps(
                    {
                        "tables": [{"table_id": "t1", "page": 1, "title": "表1"}],
                        "cells": [{"table_id": "t1", "page": 1, "row_index": 1, "column_index": 1, "text": "营收"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            invalid = root / "bronze" / "upgrades" / "ocr_cell_trace" / "000002" / "r-invalid.json"
            invalid.parent.mkdir(parents=True, exist_ok=True)
            invalid.write_text(
                json.dumps(
                    {
                        "tables": [{"page": "1", "title": "坏表"}],
                        "cells": [{"table_id": "t1"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            payload = service.admin_overview()

            audit = payload["document_pipeline"]["cell_trace"]["contract_audit"]
            self.assertEqual(audit["total"], 3)
            self.assertEqual(audit["ready"], 1)
            self.assertEqual(audit["invalid"], 1)
            self.assertEqual(audit["missing"], 1)
            self.assertEqual(audit["status"], "blocked")
            self.assertEqual(payload["delivery_readiness"]["contract_ratio"], 33)
            self.assertEqual(payload["delivery_readiness"]["stage"], "bootstrapping")
            self.assertEqual(payload["delivery_readiness"]["priority_actions"][0]["title"], "OCR Contract 质检")
            self.assertEqual(payload["acceptance_checklist"]["status"], "blocked")
            blocked_items = [item for item in payload["acceptance_checklist"]["items"] if item["status"] == "blocked"]
            self.assertTrue(any(item["key"] == "ocr_contract" for item in blocked_items))

            ready_results = service.document_pipeline_results(
                stage="cell_trace",
                artifact_source="standard_ocr",
                contract_status="ready",
                limit=10,
            )
            self.assertEqual(ready_results["total"], 1)
            self.assertEqual(ready_results["results"][0]["report_id"], "r-ready")

            invalid_results = service.document_pipeline_results(
                stage="cell_trace",
                contract_status="invalid",
                limit=10,
            )
            self.assertEqual(invalid_results["total"], 1)
            self.assertEqual(invalid_results["results"][0]["report_id"], "r-invalid")

            missing_results = service.document_pipeline_results(
                stage="cell_trace",
                contract_status="missing",
                limit=10,
            )
            self.assertEqual(missing_results["total"], 1)
            self.assertEqual(missing_results["results"][0]["report_id"], "r-missing")

    def test_run_document_pipeline_stage_reruns_filtered_cell_trace_contract_failures(self) -> None:
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
            ocr_runtime_enabled = True
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-rerun.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [
                                    {"text": "项目 本报告期 年初至报告期末", "bbox": [0, 20, 240, 32]},
                                    {"text": "营业收入 100.5 320.8", "bbox": [0, 36, 240, 48]},
                                ],
                            }
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
                                "report_id": "demo-rerun",
                                "page_json_path": str(page_json),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            broken_contract = root / "bronze" / "upgrades" / "ocr_cell_trace" / "000001" / "demo-rerun.json"
            broken_contract.parent.mkdir(parents=True, exist_ok=True)
            broken_contract.write_text(
                json.dumps(
                    {
                        "tables": [{"page": "1", "title": "坏表"}],
                        "cells": [{"table_id": "t1"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = OpsPilotService(StubRepository(), StubSettings(root))

            initial = service.run_document_pipeline_stage("cell_trace", 1)
            self.assertEqual(initial["results"][0]["status"], "blocked")
            self.assertIsNone(initial["results"][0]["source"])

            rerun = service.run_document_pipeline_stage(
                "cell_trace",
                1,
                contract_status="invalid",
            )

            self.assertEqual(rerun["processed"], 1)
            self.assertEqual(rerun["execution_feedback"]["processed"], 1)
            self.assertIn("修复", rerun["execution_feedback"]["headline"])
            self.assertTrue(rerun["run_id"])
            self.assertEqual(rerun["results"][0]["status"], "blocked")
            self.assertEqual(rerun["results"][0]["artifact_path"], "")
            self.assertIsNone(rerun["results"][0]["source"])
            self.assertEqual(rerun["execution_feedback"]["remaining_count"], 1)
            run_detail = service.document_pipeline_run_detail(rerun["run_id"])
            self.assertEqual(run_detail["execution_feedback"]["processed"], 1)
            history = service.workspace_history(user_role="management", report_period="2025Q3", limit=20)
            self.assertTrue(any(item["history_type"] == "document_pipeline_run" for item in history["records"]))

            with self.assertRaises(ValueError):
                service.run_document_pipeline_stage("cell_trace", 1, contract_status="ready")

    @patch("opspilot.application.services.requests.post")
    def test_run_document_pipeline_stage_materializes_standard_ocr_contract_via_service(self, mock_post) -> None:
        class StubRepository:
            def preferred_period(self) -> str:
                return "2025Q3"

            def list_companies(self, report_period: str | None = None) -> list[dict]:
                return []

            def list_company_names(self) -> list[str]:
                return ["测试公司"]

            def get_company(self, company_name: str, report_period: str | None = None) -> dict | None:
                if company_name != "测试公司":
                    return None
                return {
                    "company_name": "测试公司",
                    "report_period": "2025Q3",
                    "subindustry": "储能",
                    "metrics": {"G1": 12.0, "G2": 8.0, "C1": 1.3, "C3": 24.0, "S1": 1.1, "S4": 0.9},
                    "history": [],
                    "metric_evidence": {},
                    "formula_context": {},
                    "label_evidence": {},
                }

            def list_company_periods(self, company_name: str) -> list[str]:
                return ["2025Q3"]

            def resolve_evidence(self, chunk_ids: list[str]) -> list[dict]:
                return []

            def get_evidence(self, chunk_id: str) -> dict | None:
                return None

        class StubSettings:
            app_name = "OpsPilot"
            env = "test"
            default_period = "2025Q3"
            audit_min_evidence = 0
            doc_layout_engine = "PP-DocLayout-V3 + PyMuPDF"
            ocr_provider = "PaddleOCR-VL"
            ocr_model = "PaddleOCR-VL-1.5"
            ocr_runtime_enabled = True
            ocr_runtime_mode = "service"
            ocr_service_url = "http://ocr.test"
            ocr_request_timeout_seconds = 30.0
            postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
            cors_allowed_origins = ("http://127.0.0.1:8080",)
            openai_api_key = "test-key"
            openai_base_url = "https://api.openai.com/v1"

            def __init__(self, root: Path) -> None:
                self.sample_data_path = root / "bootstrap"
                self.official_data_path = root / "raw"
                self.bronze_data_path = root / "bronze"
                self.silver_data_path = root / "silver"
                self.ocr_assets_path = root / "models" / "paddleocr-vl"
                self.ocr_assets_path.mkdir(parents=True, exist_ok=True)

        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self._payload

        mock_post.return_value = FakeResponse(
            {
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {
                                "text": (
                                    "## 合并利润表\n"
                                    "| 项目 | 本报告期 | 年初至报告期末 |\n"
                                    "| --- | --- | --- |\n"
                                    "| 营业收入 | 100.5 | 320.8 |\n"
                                    "| 归母净利润 | 12.4 | 35.7 |\n"
                                )
                            }
                        }
                    ]
                }
            }
        )

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bootstrap").mkdir(parents=True, exist_ok=True)
            for prefix in ("raw", "bronze", "silver"):
                (root / prefix / "manifests").mkdir(parents=True, exist_ok=True)
            source_pdf = root / "raw" / "official" / "periodic_reports" / "SZSE" / "000001" / "demo-service.pdf"
            source_pdf.parent.mkdir(parents=True, exist_ok=True)
            source_pdf.write_bytes(b"%PDF-1.4\\n% fake report\\n")
            page_json = root / "bronze" / "page_text" / "SZSE" / "000001" / "demo-service.json"
            page_json.parent.mkdir(parents=True, exist_ok=True)
            page_json.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "page": 1,
                                "blocks": [{"text": "合并利润表", "bbox": [0, 20, 120, 30]}],
                            }
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
                                "report_id": "demo-service",
                                "report_period": "2025Q3",
                                "page_json_path": str(page_json),
                                "file_path": str(source_pdf),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = OpsPilotService(StubRepository(), StubSettings(root))
            rerun = service.run_document_pipeline_stage("cell_trace", 1)

            self.assertEqual(rerun["processed"], 1)
            self.assertEqual(rerun["results"][0]["source"], "standard_ocr")
            artifact_path = Path(rerun["results"][0]["artifact_path"])
            artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact_payload["source"], "standard_ocr")
            self.assertEqual(artifact_payload["tables"][0]["title"], "合并利润表")
            self.assertEqual(artifact_payload["cells"][0]["text"], "项目")
            contract_path = (
                root / "bronze" / "upgrades" / "ocr_cell_trace" / "000001" / "demo-service.json"
            )
            self.assertTrue(contract_path.exists())
            runtime = service.company_vision_runtime("测试公司", "2025Q3", user_role="management")
            cell_trace_stage = next(item for item in runtime["stages"] if item["stage"] == "cell_trace")
            self.assertEqual(cell_trace_stage["contract_status"], "ready")
            self.assertEqual(runtime["vision"]["quality_summary"]["artifact_source"], "standard_ocr")

    def test_runtime_check_blocks_when_ocr_assets_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "test"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "test-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_mode = "local_assets"
                ocr_runtime_enabled = True
                ocr_assets_path = root / "models" / "missing-paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = build_runtime_report(StubSettings())

            self.assertEqual(report["status"], "blocked")
            ocr_assets = next(item for item in report["checks"] if item["key"] == "ocr_assets")
            self.assertEqual(ocr_assets["status"], "blocked")
            self.assertIn("ops-pilot-init-ocr-assets", ocr_assets["remediation"])
            self.assertTrue(report["recommended_actions"])
            with self.assertRaisesRegex(RuntimeError, "ocr_assets"):
                validate_delivery_runtime(StubSettings())

    def test_runtime_check_passes_when_delivery_assets_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "test"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "test-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_mode = "local_assets"
                ocr_runtime_enabled = True
                ocr_assets_path = root / "models" / "paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.ocr_assets_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = validate_delivery_runtime(StubSettings())

            self.assertEqual(report["status"], "ready")

    def test_runtime_check_blocks_when_ocr_service_url_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "test"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "test-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_mode = "service"
                ocr_runtime_enabled = True
                ocr_service_url = ""
                ocr_assets_path = root / "models" / "paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = build_runtime_report(StubSettings())

            ocr_service = next(item for item in report["checks"] if item["key"] == "ocr_service")
            self.assertEqual(ocr_service["status"], "blocked")
            with self.assertRaisesRegex(RuntimeError, "ocr_service"):
                validate_delivery_runtime(StubSettings())

    def test_runtime_check_passes_when_ocr_service_url_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "test"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "test-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_mode = "service"
                ocr_runtime_enabled = True
                ocr_service_url = "http://ocr.test"
                ocr_assets_path = root / "models" / "paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = validate_delivery_runtime(StubSettings())

            self.assertEqual(report["status"], "ready")

    def test_runtime_check_blocks_when_llm_auth_invalid(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "development"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "bad-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_enabled = True
                ocr_assets_path = root / "models" / "paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.ocr_assets_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("opspilot.runtime_checks.httpx.post") as mock_post:
                mock_post.return_value = type(
                    "StubResponse",
                    (),
                    {
                        "status_code": 401,
                        "is_success": False,
                        "text": "{\"error\":{\"message\":\"invalid token\"}}",
                    },
                )()
                report = build_runtime_report(StubSettings())

            llm_check = next(item for item in report["checks"] if item["key"] == "llm")
            self.assertEqual(llm_check["status"], "blocked")
            self.assertIn("401", llm_check["detail"])
            self.assertIn("OPS_PILOT_OPENAI_API_KEY", llm_check["remediation"])

    def test_runtime_startup_profile_allows_ocr_blockers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class StubSettings:
                env = "test"
                postgres_dsn = "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot"
                openai_api_key = "test-key"
                openai_base_url = "https://api.openai.com/v1"
                official_data_path = root / "raw"
                universe_data_path = root / "universe"
                silver_data_path = root / "silver"
                ocr_runtime_enabled = False
                ocr_assets_path = root / "models" / "missing-paddleocr-vl"

            StubSettings.official_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.universe_data_path.mkdir(parents=True, exist_ok=True)
            StubSettings.silver_data_path.mkdir(parents=True, exist_ok=True)
            (StubSettings.universe_data_path / "formal_company_pool.json").write_text(
                json.dumps([{"company_name": "测试公司"}], ensure_ascii=False),
                encoding="utf-8",
            )

            report = validate_delivery_runtime(StubSettings(), profile="startup")

            self.assertEqual(report["status"], "blocked")

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

    def test_select_research_report_keeps_explicit_title_when_period_is_missing(self) -> None:
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
            report_period="2025Q3",
            report_title="行业景气向上，订单持续放量",
            available_periods={"2025Q3"},
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["title"], "行业景气向上，订单持续放量")

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
            self.assertIn("verify_command_surface", payload)
            self.assertTrue(payload["verify_delta_tape"])

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
