from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.ingest.manifest_utils import load_manifest_records, merge_manifest_records


class ManifestUtilsTestCase(unittest.TestCase):
    def test_load_manifest_records_returns_empty_for_missing_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.json"
            self.assertEqual(load_manifest_records(path), [])

    def test_merge_manifest_records_replaces_target_company_only(self) -> None:
        existing = [
            {"security_code": "601012", "publish_date": "2025-10-31", "title": "A", "source": "SSE"},
            {"security_code": "300750", "publish_date": "2025-10-21", "title": "B", "source": "SZSE"},
        ]
        new = [
            {"security_code": "601012", "publish_date": "2025-11-01", "title": "A2", "source": "SSE"},
        ]

        merged = merge_manifest_records(
            existing,
            new,
            company_codes={"601012"},
            key_fields=("source", "security_code", "publish_date", "title"),
        )

        self.assertEqual(len(merged), 2)
        self.assertEqual({item["security_code"] for item in merged}, {"601012", "300750"})
        self.assertEqual(
            [item for item in merged if item["security_code"] == "601012"][0]["title"],
            "A2",
        )

    def test_merge_manifest_records_dedupes_by_key_fields(self) -> None:
        merged = merge_manifest_records(
            existing_records=[],
            new_records=[
                {"security_code": "601012", "publish_date": "2025-10-31", "title": "A", "source": "SSE", "v": 1},
                {"security_code": "601012", "publish_date": "2025-10-31", "title": "A", "source": "SSE", "v": 2},
            ],
            company_codes={"601012"},
            key_fields=("source", "security_code", "publish_date", "title"),
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["v"], 2)


if __name__ == "__main__":
    unittest.main()
