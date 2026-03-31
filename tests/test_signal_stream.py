from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.signal_stream import (
    build_company_signal_timeline,
    build_company_signal_features,
    build_external_signal_events,
    build_subindustry_signal_heatmap,
    write_company_signal_snapshot,
    write_company_signal_timeline,
    write_signal_event_stream,
    write_subindustry_signal_heatmap,
)


class SignalStreamTestCase(unittest.TestCase):
    def test_build_external_signal_events_and_snapshots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifests_root = root / "raw" / "official" / "manifests"
            bronze_root = root / "bronze" / "official"
            silver_root = root / "silver" / "official"
            gold_root = root / "gold" / "official"
            manifests_root.mkdir(parents=True, exist_ok=True)
            generated_at = "2026-03-25T10:00:00+00:00"

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
                                "publish_date": "2026-03-22",
                                "source_url": "https://example.com/periodic",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
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
                                "publish_date": "2026-03-25",
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
                                "publish_date": "2026-03-24",
                                "source_url": "https://example.com/industry",
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
                                "publish_date": "2026-03-25",
                                "source_url": "https://example.com/snapshot",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ingest_batch_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            events, manifest_meta = build_external_signal_events(
                root / "raw" / "official",
                ingest_batch_id=ingest_batch_id,
            )

            self.assertEqual(len(events), 4)
            self.assertEqual(events[0]["company_name"], "科陆电子")
            self.assertEqual(events[0]["signal_kind"], "company_research")
            self.assertEqual(events[1]["signal_kind"], "company_snapshot")
            self.assertEqual(events[2]["signal_kind"], "industry_research")
            self.assertEqual(manifest_meta["periodic_report"]["record_count"], 1)

            features = build_company_signal_features(events, ingest_batch_id)
            self.assertEqual(features[0]["company_name"], "科陆电子")
            self.assertEqual(features[0]["signal_count"], 2)
            self.assertEqual(features[0]["external_heat"], 4)
            company_timeline = build_company_signal_timeline(events, ingest_batch_id, window_days=4)
            subindustry_heatmap = build_subindustry_signal_heatmap(events, ingest_batch_id, window_days=4)
            self.assertEqual(company_timeline["top_companies"][0]["company_name"], "科陆电子")
            self.assertEqual(company_timeline["top_companies"][0]["total_heat"], 4)
            self.assertEqual(subindustry_heatmap["top_subindustries"][0]["subindustry"], "储能")
            self.assertEqual(subindustry_heatmap["top_subindustries"][0]["total_heat"], 4)

            stream_manifest = write_signal_event_stream(
                events,
                bronze_root,
                ingest_batch_id=ingest_batch_id,
                manifest_meta=manifest_meta,
            )
            snapshot_manifest = write_company_signal_snapshot(
                features,
                silver_root,
                ingest_batch_id=ingest_batch_id,
            )
            company_timeline_manifest = write_company_signal_timeline(company_timeline, gold_root)
            subindustry_heatmap_manifest = write_subindustry_signal_heatmap(subindustry_heatmap, gold_root)

            self.assertEqual(stream_manifest["record_count"], 4)
            self.assertEqual(stream_manifest["partition_count"], 3)
            self.assertTrue(
                (bronze_root / "stream" / "external_signal_events" / "publish_date=2026-03-25").exists()
            )
            self.assertEqual(snapshot_manifest["record_count"], 3)
            snapshot_payload = json.loads(
                (silver_root / "stream" / "company_signal_snapshot.json").read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot_payload["records"][0]["company_name"], "科陆电子")
            self.assertEqual(company_timeline_manifest["record_count"], 2)
            self.assertEqual(subindustry_heatmap_manifest["record_count"], 3)
            heatmap_payload = json.loads(
                (gold_root / "stream" / "subindustry_signal_heatmap.json").read_text(encoding="utf-8")
            )
            self.assertEqual(heatmap_payload["top_subindustries"][0]["subindustry"], "储能")


if __name__ == "__main__":
    unittest.main()
