from __future__ import annotations

from argparse import ArgumentParser
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
import hashlib
import json

from opspilot.config import get_settings

try:
    from kafka import KafkaProducer
except ImportError:  # pragma: no cover - optional dependency
    KafkaProducer = None


SOURCE_FILE_MAP = {
    "periodic_report": "periodic_reports_manifest.json",
    "company_research": "research_reports_manifest.json",
    "industry_research": "industry_research_reports_manifest.json",
    "company_snapshot": "company_snapshots_manifest.json",
}

KIND_META = {
    "periodic_report": {"status": "交易所公告", "source_name": {"SSE": "上交所公告", "SZSE": "深交所公告"}},
    "company_research": {"status": "券商研报", "source_name": {"default": "东方财富研报"}},
    "industry_research": {"status": "行业研报", "source_name": {"default": "东方财富行业研报"}},
    "company_snapshot": {"status": "公司快照", "source_name": {"default": "巨潮资讯"}},
}

KIND_PRIORITY = {
    "periodic_report": 0,
    "company_research": 1,
    "industry_research": 2,
    "company_snapshot": 3,
}

SIGNAL_KIND_WEIGHT = {
    "periodic_report": 4,
    "company_research": 3,
    "industry_research": 2,
    "company_snapshot": 1,
}


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Build external signal event stream for OpsPilot.")
    parser.add_argument(
        "--official-data-root",
        default="",
        help="Override official data root. Defaults to OPS_PILOT_OFFICIAL_DATA_PATH.",
    )
    parser.add_argument(
        "--bronze-data-root",
        default="",
        help="Override bronze data root. Defaults to OPS_PILOT_BRONZE_DATA_PATH.",
    )
    parser.add_argument(
        "--silver-data-root",
        default="",
        help="Override silver data root. Defaults to OPS_PILOT_SILVER_DATA_PATH.",
    )
    parser.add_argument(
        "--gold-data-root",
        default="",
        help="Override gold data root. Defaults to OPS_PILOT_GOLD_DATA_PATH.",
    )
    parser.add_argument(
        "--company-codes",
        default="",
        help="Comma-separated security codes to filter the stream.",
    )
    parser.add_argument(
        "--company-names",
        default="",
        help="Comma-separated company names to filter the stream.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap for emitted events after sorting.",
    )
    parser.add_argument(
        "--publish-kafka",
        action="store_true",
        help="Publish emitted events into Kafka topic defined by settings or CLI.",
    )
    parser.add_argument(
        "--kafka-bootstrap-servers",
        default="",
        help="Override OPS_PILOT_KAFKA_BOOTSTRAP_SERVERS.",
    )
    parser.add_argument(
        "--kafka-topic",
        default="",
        help="Override OPS_PILOT_KAFKA_SIGNAL_TOPIC.",
    )
    return parser


def _load_manifest_records(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    if not path.exists():
        return None, []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    records = payload.get("records", [])
    if not isinstance(records, list):
        return payload.get("generated_at"), []
    return payload.get("generated_at"), [item for item in records if isinstance(item, dict)]


def _parse_publish_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip().replace("Z", "+00:00")
    if not normalized:
        return None
    if "T" not in normalized and " " not in normalized:
        normalized = f"{normalized}T00:00:00+00:00"
    elif "+" not in normalized and "Z" not in normalized:
        normalized = normalized.replace(" ", "T")
        normalized = f"{normalized}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _normalize_event(record: dict[str, Any], kind: str, ingest_batch_id: str) -> dict[str, Any]:
    meta = KIND_META[kind]
    source_code = str(record.get("source") or "")
    company_name = record.get("company_name") or record.get("industry_name") or "行业信号"
    publish_dt = _parse_publish_datetime(record.get("publish_date"))
    publish_date = publish_dt.date().isoformat() if publish_dt else None
    event_key = "|".join(
        [
            kind,
            str(record.get("security_code") or ""),
            str(company_name),
            str(record.get("title") or ""),
            str(record.get("publish_date") or ""),
        ]
    )
    event_id = hashlib.sha1(event_key.encode("utf-8")).hexdigest()
    source_name = meta["source_name"].get(source_code) or meta["source_name"].get("default") or source_code
    return {
        "event_id": event_id,
        "ingest_batch_id": ingest_batch_id,
        "event_time": publish_dt.isoformat() if publish_dt else datetime.now(UTC).replace(microsecond=0).isoformat(),
        "publish_date": publish_date,
        "signal_kind": kind,
        "signal_status": meta["status"],
        "priority": KIND_PRIORITY[kind],
        "source": source_code or source_name,
        "source_name": source_name,
        "company_name": company_name,
        "industry_name": record.get("industry_name"),
        "security_code": record.get("security_code"),
        "exchange": record.get("exchange"),
        "subindustry": record.get("subindustry"),
        "headline": record.get("title") or f"{company_name} 外部信号更新",
        "source_url": record.get("source_url"),
        "detail_url": record.get("detail_url"),
        "local_path": record.get("local_path"),
        "is_summary": bool(record.get("is_summary", False)),
        "report_type": record.get("report_type"),
        "ingested_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def build_external_signal_events(
    official_data_root: Path,
    *,
    ingest_batch_id: str,
    company_codes: set[str] | None = None,
    company_names: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifests_root = official_data_root / "manifests"
    events: list[dict[str, Any]] = []
    manifest_meta: dict[str, Any] = {}
    for kind, filename in SOURCE_FILE_MAP.items():
        generated_at, records = _load_manifest_records(manifests_root / filename)
        manifest_meta[kind] = {
            "generated_at": generated_at,
            "record_count": len(records),
        }
        for record in records:
            record_code = str(record.get("security_code") or "")
            record_name = str(record.get("company_name") or record.get("industry_name") or "")
            if company_codes and record_code and record_code not in company_codes:
                continue
            if company_names and record_name and record_name not in company_names:
                continue
            events.append(_normalize_event(record, kind, ingest_batch_id))
    if not events:
        raise RuntimeError("未检测到正式外部信号记录，请先执行 ops-pilot-fetch-real-data。")
    events.sort(
        key=lambda item: (
            _parse_publish_datetime(item.get("event_time")) or datetime.min.replace(tzinfo=UTC),
            -int(item.get("priority") or 99),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    deduped_events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for event in events:
        if event["event_id"] in seen_event_ids:
            continue
        seen_event_ids.add(event["event_id"])
        deduped_events.append(event)
    return deduped_events, manifest_meta


def build_company_signal_features(events: list[dict[str, Any]], ingest_batch_id: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[(str(event.get("company_name") or ""), str(event.get("security_code") or ""))].append(event)
    features: list[dict[str, Any]] = []
    for (company_name, security_code), rows in grouped.items():
        rows.sort(
            key=lambda item: _parse_publish_datetime(item.get("event_time")) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        counts_by_kind: dict[str, int] = defaultdict(int)
        sources: set[str] = set()
        for row in rows:
            counts_by_kind[str(row.get("signal_kind") or "")] += 1
            if row.get("source_name"):
                sources.add(str(row["source_name"]))
        features.append(
            {
                "ingest_batch_id": ingest_batch_id,
                "company_name": company_name,
                "security_code": security_code or None,
                "subindustry": rows[0].get("subindustry"),
                "latest_event_time": rows[0].get("event_time"),
                "latest_headline": rows[0].get("headline"),
                "latest_signal_kind": rows[0].get("signal_kind"),
                "latest_signal_status": rows[0].get("signal_status"),
                "signal_count": len(rows),
                "periodic_report_count": counts_by_kind.get("periodic_report", 0),
                "company_research_count": counts_by_kind.get("company_research", 0),
                "industry_research_count": counts_by_kind.get("industry_research", 0),
                "company_snapshot_count": counts_by_kind.get("company_snapshot", 0),
                "source_count": len(sources),
                "external_heat": (
                    counts_by_kind.get("periodic_report", 0) * SIGNAL_KIND_WEIGHT["periodic_report"]
                    + counts_by_kind.get("company_research", 0) * SIGNAL_KIND_WEIGHT["company_research"]
                    + counts_by_kind.get("industry_research", 0) * SIGNAL_KIND_WEIGHT["industry_research"]
                    + counts_by_kind.get("company_snapshot", 0) * SIGNAL_KIND_WEIGHT["company_snapshot"]
                ),
            }
        )
    features.sort(key=lambda item: (item["external_heat"], item["signal_count"], item["company_name"]), reverse=True)
    return features


def _window_date_axis(events: list[dict[str, Any]], *, window_days: int) -> list[str]:
    latest_event_at = max(
        (
            _parse_publish_datetime(item.get("event_time"))
            for item in events
            if _parse_publish_datetime(item.get("event_time")) is not None
        ),
        default=datetime.now(UTC),
    )
    latest_date = latest_event_at.date()
    return [
        (latest_date - timedelta(days=offset)).isoformat()
        for offset in range(window_days - 1, -1, -1)
    ]


def _window_momentum(series: list[dict[str, Any]]) -> int:
    if not series:
        return 0
    recent = sum(int(item.get("external_heat") or 0) for item in series[-3:])
    previous = sum(int(item.get("external_heat") or 0) for item in series[-6:-3])
    return recent - previous


def build_company_signal_timeline(
    events: list[dict[str, Any]],
    ingest_batch_id: str,
    *,
    window_days: int = 7,
) -> dict[str, Any]:
    date_axis = _window_date_axis(events, window_days=window_days)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        company_name = str(event.get("company_name") or "").strip()
        security_code = str(event.get("security_code") or "").strip()
        if not company_name or security_code.upper() == "INDUSTRY":
            continue
        grouped[(company_name, security_code)].append(event)
    records: list[dict[str, Any]] = []
    for (company_name, security_code), rows in grouped.items():
        rows.sort(
            key=lambda item: _parse_publish_datetime(item.get("event_time")) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        timeline_index = {
            point: {"date": point, "signal_count": 0, "external_heat": 0}
            for point in date_axis
        }
        for row in rows:
            publish_date = row.get("publish_date") or ""
            if publish_date not in timeline_index:
                continue
            timeline_index[publish_date]["signal_count"] += 1
            timeline_index[publish_date]["external_heat"] += SIGNAL_KIND_WEIGHT.get(
                str(row.get("signal_kind") or ""),
                1,
            )
        timeline = [timeline_index[point] for point in date_axis]
        total_heat = sum(item["external_heat"] for item in timeline)
        if total_heat == 0:
            continue
        records.append(
            {
                "ingest_batch_id": ingest_batch_id,
                "company_name": company_name,
                "security_code": security_code or None,
                "subindustry": rows[0].get("subindustry"),
                "latest_event_time": rows[0].get("event_time"),
                "latest_headline": rows[0].get("headline"),
                "latest_signal_kind": rows[0].get("signal_kind"),
                "latest_signal_status": rows[0].get("signal_status"),
                "latest_heat": timeline[-1]["external_heat"] if timeline else 0,
                "signal_count": sum(item["signal_count"] for item in timeline),
                "total_heat": total_heat,
                "active_days": sum(1 for item in timeline if item["signal_count"] > 0),
                "momentum": _window_momentum(timeline),
                "timeline": timeline,
            }
        )
    records.sort(
        key=lambda item: (
            int(item.get("total_heat") or 0),
            int(item.get("momentum") or 0),
            int(item.get("signal_count") or 0),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ingest_batch_id": ingest_batch_id,
        "window_days": window_days,
        "date_axis": date_axis,
        "record_count": len(records),
        "top_companies": records[:8],
        "records": records,
    }


def build_subindustry_signal_heatmap(
    events: list[dict[str, Any]],
    ingest_batch_id: str,
    *,
    window_days: int = 7,
) -> dict[str, Any]:
    date_axis = _window_date_axis(events, window_days=window_days)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        subindustry = str(event.get("subindustry") or "").strip() or "未分类"
        grouped[subindustry].append(event)
    records: list[dict[str, Any]] = []
    for subindustry, rows in grouped.items():
        timeline_index = {
            point: {"date": point, "signal_count": 0, "external_heat": 0}
            for point in date_axis
        }
        for row in rows:
            publish_date = row.get("publish_date") or ""
            if publish_date not in timeline_index:
                continue
            timeline_index[publish_date]["signal_count"] += 1
            timeline_index[publish_date]["external_heat"] += SIGNAL_KIND_WEIGHT.get(
                str(row.get("signal_kind") or ""),
                1,
            )
        timeline = [timeline_index[point] for point in date_axis]
        total_heat = sum(item["external_heat"] for item in timeline)
        if total_heat == 0:
            continue
        records.append(
            {
                "ingest_batch_id": ingest_batch_id,
                "subindustry": subindustry,
                "signal_count": sum(item["signal_count"] for item in timeline),
                "total_heat": total_heat,
                "latest_heat": timeline[-1]["external_heat"] if timeline else 0,
                "active_days": sum(1 for item in timeline if item["signal_count"] > 0),
                "momentum": _window_momentum(timeline),
                "timeline": timeline,
            }
        )
    records.sort(
        key=lambda item: (
            int(item.get("total_heat") or 0),
            int(item.get("momentum") or 0),
            item.get("subindustry") or "",
        ),
        reverse=True,
    )
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ingest_batch_id": ingest_batch_id,
        "window_days": window_days,
        "date_axis": date_axis,
        "record_count": len(records),
        "top_subindustries": records[:8],
        "records": records,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def write_signal_event_stream(
    events: list[dict[str, Any]],
    bronze_data_root: Path,
    *,
    ingest_batch_id: str,
    manifest_meta: dict[str, Any],
) -> dict[str, Any]:
    base_dir = bronze_data_root / "stream" / "external_signal_events"
    partition_counts: dict[str, int] = defaultdict(int)
    lines_by_partition: dict[str, list[str]] = defaultdict(list)
    for event in events:
        partition = event.get("publish_date") or event.get("event_time", "")[:10] or "unknown"
        lines_by_partition[partition].append(json.dumps(event, ensure_ascii=False))
        partition_counts[partition] += 1
    written_files: list[str] = []
    for partition, lines in lines_by_partition.items():
        partition_path = base_dir / f"publish_date={partition}" / f"batch-{ingest_batch_id}.jsonl"
        partition_path.parent.mkdir(parents=True, exist_ok=True)
        partition_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written_files.append(str(partition_path))
    manifest = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ingest_batch_id": ingest_batch_id,
        "record_count": len(events),
        "partition_count": len(lines_by_partition),
        "partitions": [
            {"publish_date": partition, "record_count": count}
            for partition, count in sorted(partition_counts.items(), reverse=True)
        ],
        "files": written_files,
        "source_manifests": manifest_meta,
    }
    _write_json(bronze_data_root / "manifests" / "external_signal_stream_manifest.json", manifest)
    return manifest


def write_company_signal_snapshot(
    features: list[dict[str, Any]],
    silver_data_root: Path,
    *,
    ingest_batch_id: str,
) -> dict[str, Any]:
    snapshot_path = silver_data_root / "stream" / "company_signal_snapshot.json"
    payload = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "ingest_batch_id": ingest_batch_id,
        "record_count": len(features),
        "records": features,
    }
    _write_json(snapshot_path, payload)
    _write_json(silver_data_root / "manifests" / "company_signal_snapshot_manifest.json", payload)
    return payload


def write_company_signal_timeline(
    payload: dict[str, Any],
    gold_data_root: Path,
) -> dict[str, Any]:
    _write_json(gold_data_root / "stream" / "company_signal_timeline.json", payload)
    _write_json(gold_data_root / "manifests" / "company_signal_timeline_manifest.json", payload)
    return payload


def write_subindustry_signal_heatmap(
    payload: dict[str, Any],
    gold_data_root: Path,
) -> dict[str, Any]:
    _write_json(gold_data_root / "stream" / "subindustry_signal_heatmap.json", payload)
    _write_json(gold_data_root / "manifests" / "subindustry_signal_heatmap_manifest.json", payload)
    return payload


def publish_events_to_kafka(
    events: list[dict[str, Any]],
    *,
    bootstrap_servers: str,
    topic: str,
) -> int:
    if not bootstrap_servers:
        raise RuntimeError("Kafka bootstrap servers 未配置。")
    if KafkaProducer is None:
        raise RuntimeError("未安装 kafka-python-ng，请执行 pip install -e .[streaming]。")
    producer = KafkaProducer(
        bootstrap_servers=[item.strip() for item in bootstrap_servers.split(",") if item.strip()],
        value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
        key_serializer=lambda value: value.encode("utf-8"),
    )
    published = 0
    try:
        for event in events:
            producer.send(topic, key=event["event_id"], value=event)
            published += 1
        producer.flush()
    finally:
        producer.close()
    return published


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    official_data_root = Path(args.official_data_root).resolve() if args.official_data_root else settings.official_data_path
    bronze_data_root = Path(args.bronze_data_root).resolve() if args.bronze_data_root else settings.bronze_data_path
    silver_data_root = Path(args.silver_data_root).resolve() if args.silver_data_root else settings.silver_data_path
    gold_data_root = Path(args.gold_data_root).resolve() if args.gold_data_root else settings.gold_data_path
    company_codes = {item.strip() for item in args.company_codes.split(",") if item.strip()}
    company_names = {item.strip() for item in args.company_names.split(",") if item.strip()}
    ingest_batch_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    events, manifest_meta = build_external_signal_events(
        official_data_root,
        ingest_batch_id=ingest_batch_id,
        company_codes=company_codes or None,
        company_names=company_names or None,
    )
    if args.limit and args.limit > 0:
        events = events[: args.limit]
    features = build_company_signal_features(events, ingest_batch_id)
    stream_manifest = write_signal_event_stream(
        events,
        bronze_data_root,
        ingest_batch_id=ingest_batch_id,
        manifest_meta=manifest_meta,
    )
    snapshot_manifest = write_company_signal_snapshot(
        features,
        silver_data_root,
        ingest_batch_id=ingest_batch_id,
    )
    company_timeline_payload = build_company_signal_timeline(events, ingest_batch_id)
    subindustry_heatmap_payload = build_subindustry_signal_heatmap(events, ingest_batch_id)
    company_timeline_manifest = write_company_signal_timeline(company_timeline_payload, gold_data_root)
    subindustry_heatmap_manifest = write_subindustry_signal_heatmap(
        subindustry_heatmap_payload,
        gold_data_root,
    )
    published = 0
    if args.publish_kafka:
        bootstrap_servers = args.kafka_bootstrap_servers or settings.kafka_bootstrap_servers
        topic = args.kafka_topic or settings.kafka_signal_topic
        published = publish_events_to_kafka(
            events,
            bootstrap_servers=bootstrap_servers,
            topic=topic,
        )
    print(f"ingest_batch_id={ingest_batch_id}")
    print(f"event_records={stream_manifest['record_count']}")
    print(f"event_partitions={stream_manifest['partition_count']}")
    print(f"feature_records={snapshot_manifest['record_count']}")
    print(f"gold_company_records={company_timeline_manifest['record_count']}")
    print(f"gold_subindustry_records={subindustry_heatmap_manifest['record_count']}")
    print(f"kafka_published={published}")


if __name__ == "__main__":
    main()
