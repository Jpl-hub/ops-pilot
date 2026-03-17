from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json


def load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("records", [])


def merge_manifest_records(
    existing_records: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
    *,
    company_codes: Iterable[str],
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    target_codes = {code for code in company_codes if code}
    preserved = [
        record for record in existing_records if record.get("security_code") not in target_codes
    ]
    merged = preserved + list(new_records)
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in merged:
        key = tuple(record.get(field) for field in key_fields)
        deduped[key] = record
    return sorted(
        deduped.values(),
        key=lambda item: (
            item.get("security_code", ""),
            item.get("publish_date", ""),
            item.get("title", ""),
            item.get("report_id", ""),
        ),
        reverse=False,
    )
