from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any

try:
    from kafka import KafkaConsumer, TopicPartition
except ImportError:  # pragma: no cover
    KafkaConsumer = None
    TopicPartition = None

from opspilot.config import Settings


EXTERNAL_SIGNAL_PRIORITY = {
    "periodic_report": 0,
    "company_research": 1,
    "industry_research": 2,
    "company_snapshot": 3,
}

SUBINDUSTRY_SIGNAL_TOPICS = {
    "光伏": ("光伏设备",),
    "储能": ("电池", "能源金属"),
    "锂电池与电池材料": ("电池", "能源金属"),
    "风电设备与新能源装备": ("风电设备",),
}


def _gold_data_root(settings: Settings) -> Path:
    configured = getattr(settings, "gold_data_path", None)
    if isinstance(configured, Path):
        return configured
    silver_root = settings.silver_data_path
    return silver_root.parent.parent / "gold" / silver_root.name


def _load_manifest_generated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    generated_at = payload.get("generated_at")
    return generated_at if isinstance(generated_at, str) else None


def _parse_calendar_date(value: str | None) -> date | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    normalized = candidate.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _map_subindustry_topics(subindustry: str | None) -> tuple[str, ...]:
    if not subindustry:
        return ()
    normalized = str(subindustry).strip()
    topics: list[str] = []
    for key, names in SUBINDUSTRY_SIGNAL_TOPICS.items():
        if key in normalized:
            topics.extend(names)
    if not topics and "电池" in normalized:
        topics.append("电池")
    if not topics and "金属" in normalized:
        topics.append("能源金属")
    return tuple(dict.fromkeys(topics))


def _describe_external_signal_freshness(latest_publish_date: str | None) -> tuple[str, str]:
    latest_date = _parse_calendar_date(latest_publish_date)
    if latest_date is None:
        return "unavailable", "未检测到正式外部信号"
    age_days = max(0, (datetime.now(UTC).date() - latest_date).days)
    if age_days <= 1:
        return "fresh", "近 24 小时有更新"
    if age_days <= 3:
        return "recent", f"{age_days} 天内有更新"
    if age_days <= 7:
        return "warm", f"最近 {age_days} 天有更新"
    return "stale", f"最近更新距今 {age_days} 天"


def _normalize_external_signal(
    record: dict[str, Any],
    *,
    kind: str,
    status: str,
    source_name: str,
    tone: str,
) -> dict[str, Any]:
    company_name = record.get("company_name") or record.get("industry_name") or "行业信号"
    headline = record.get("title")
    if not headline and kind == "company_snapshot":
        headline = f"{company_name} 公司快照已更新"
    return {
        "kind": kind,
        "company_name": company_name,
        "headline": headline or "外部信号已更新",
        "status": status,
        "tone": tone,
        "source_name": source_name,
        "publish_date": record.get("publish_date"),
        "source_url": record.get("source_url"),
        "security_code": record.get("security_code"),
        "subindustry": record.get("subindustry"),
    }


def _build_external_signal_stream(
    settings: Settings,
    *,
    focus_companies: list[dict[str, Any]],
    limit: int = 8,
) -> dict[str, Any]:
    manifests_root = settings.official_data_path / "manifests"
    company_names = {
        str(item.get("company_name")).strip()
        for item in focus_companies
        if item.get("company_name")
    }
    focus_topics: set[str] = set()
    for item in focus_companies:
        focus_topics.update(_map_subindustry_topics(item.get("subindustry")))

    periodic_path = manifests_root / "periodic_reports_manifest.json"
    research_path = manifests_root / "research_reports_manifest.json"
    industry_path = manifests_root / "industry_research_reports_manifest.json"
    snapshot_path = manifests_root / "company_snapshots_manifest.json"

    periodic_records = _load_manifest_records(periodic_path)
    research_records = _load_manifest_records(research_path)
    industry_records = _load_manifest_records(industry_path)
    snapshot_records = _load_manifest_records(snapshot_path)

    signals: list[dict[str, Any]] = []
    for record in periodic_records:
        if str(record.get("company_name") or "").strip() not in company_names:
            continue
        signals.append(
            _normalize_external_signal(
                record,
                kind="periodic_report",
                status="定期报告",
                source_name="交易所公告",
                tone="accent",
            )
        )
    for record in research_records:
        if str(record.get("company_name") or "").strip() not in company_names:
            continue
        signals.append(
            _normalize_external_signal(
                record,
                kind="company_research",
                status="券商研报",
                source_name="券商研报",
                tone="success",
            )
        )
    for record in industry_records:
        title = str(record.get("title") or "")
        if focus_topics and not any(topic in title for topic in focus_topics):
            continue
        signals.append(
            _normalize_external_signal(
                record,
                kind="industry_research",
                status="行业研报",
                source_name="行业研报",
                tone="warning",
            )
        )
    for record in snapshot_records:
        if str(record.get("company_name") or "").strip() not in company_names:
            continue
        signals.append(
            _normalize_external_signal(
                record,
                kind="company_snapshot",
                status="公司快照",
                source_name="公司快照",
                tone="risk",
            )
        )

    deduped_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for signal in signals:
        dedupe_key = (
            signal.get("kind") or "",
            signal.get("company_name") or "",
            signal.get("headline") or "",
        )
        current = deduped_by_key.get(dedupe_key)
        if current is None:
            deduped_by_key[dedupe_key] = signal
            continue
        current_date = _parse_calendar_date(current.get("publish_date"))
        candidate_date = _parse_calendar_date(signal.get("publish_date"))
        if candidate_date and (current_date is None or candidate_date > current_date):
            deduped_by_key[dedupe_key] = signal

    deduped_signals = list(deduped_by_key.values())
    deduped_signals.sort(
        key=lambda item: (
            _parse_calendar_date(item.get("publish_date")) or date.min,
            -EXTERNAL_SIGNAL_PRIORITY.get(item.get("kind") or "", 99),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    deduped_signals = deduped_signals[:limit]
    latest_publish_date = max(
        (
            item.get("publish_date")
            for item in deduped_signals
            if _parse_calendar_date(item.get("publish_date")) is not None
        ),
        default=None,
    )
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_publish_date)
    manifest_generated_at = max(
        (
            timestamp
            for timestamp in (
                _load_manifest_generated_at(periodic_path),
                _load_manifest_generated_at(research_path),
                _load_manifest_generated_at(industry_path),
                _load_manifest_generated_at(snapshot_path),
            )
            if _parse_iso_timestamp(timestamp) is not None
        ),
        default=None,
        key=lambda item: _parse_iso_timestamp(item) or datetime.min.replace(tzinfo=UTC),
    )
    source_counter = {
        "交易所公告": sum(1 for item in deduped_signals if item["kind"] == "periodic_report"),
        "券商研报": sum(1 for item in deduped_signals if item["kind"] == "company_research"),
        "行业研报": sum(1 for item in deduped_signals if item["kind"] == "industry_research"),
        "公司快照": sum(1 for item in deduped_signals if item["kind"] == "company_snapshot"),
    }
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": manifest_generated_at,
        "latest_publish_date": latest_publish_date,
        "signal_count": len(deduped_signals),
        "focus_companies": sorted(company_names),
        "sources": [
            {"label": label, "count": count}
            for label, count in source_counter.items()
            if count
        ],
        "signals": deduped_signals,
    }


def _build_external_signal_market_tape(
    external_signal_stream: dict[str, Any],
) -> list[dict[str, Any]]:
    if not external_signal_stream.get("signal_count"):
        return [
            {
                "label": "外部信号",
                "value": "0",
                "delta": "未检测到正式外部信号",
                "tone": "risk",
            }
        ]
    sources = external_signal_stream.get("sources", [])
    tone = "risk" if external_signal_stream.get("status") == "stale" else "success"
    latest_publish_date = external_signal_stream.get("latest_publish_date") or "未知"
    return [
        {
            "label": "外部信号",
            "value": str(external_signal_stream["signal_count"]),
            "delta": f"最新发布日期 {latest_publish_date}",
            "tone": tone,
        },
        {
            "label": "官方源刷新",
            "value": external_signal_stream.get("freshness_label") or "未知",
            "delta": f"{len(sources)} 类正式来源",
            "tone": tone,
        },
    ]


def _build_kafka_signal_runtime(settings: Settings) -> dict[str, Any]:
    bootstrap_servers = str(getattr(settings, "kafka_bootstrap_servers", "") or "").strip()
    topic = str(getattr(settings, "kafka_signal_topic", "opspilot.external_signals") or "opspilot.external_signals").strip()
    base_payload = {
        "bootstrap_servers": bootstrap_servers,
        "topic": topic,
        "partition_count": 0,
        "message_count": 0,
        "latest_publish_date": None,
        "latest_event_time": None,
        "latest_company_name": None,
        "latest_headline": None,
        "latest_signal_status": None,
    }
    if not bootstrap_servers:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 未配置",
        }
    if KafkaConsumer is None or TopicPartition is None:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 依赖未安装",
        }

    consumer = KafkaConsumer(
        bootstrap_servers=[item.strip() for item in bootstrap_servers.split(",") if item.strip()],
        enable_auto_commit=False,
        auto_offset_reset="latest",
        consumer_timeout_ms=1200,
        request_timeout_ms=5000,
        api_version_auto_timeout_ms=5000,
        metadata_max_age_ms=5000,
    )
    try:
        partitions = consumer.partitions_for_topic(topic)
        if not partitions:
            return {
                **base_payload,
                "status": "unavailable",
                "freshness_label": "Kafka Topic 未发现",
            }

        topic_partitions = [TopicPartition(topic, partition) for partition in sorted(partitions)]
        end_offsets = consumer.end_offsets(topic_partitions)
        latest_candidates: list[dict[str, Any]] = []
        for topic_partition in topic_partitions:
            end_offset = int(end_offsets.get(topic_partition, 0) or 0)
            if end_offset <= 0:
                continue
            consumer.assign([topic_partition])
            consumer.seek(topic_partition, max(0, end_offset - 3))
            polled = consumer.poll(timeout_ms=600, max_records=3)
            for records in polled.values():
                for record in records:
                    decoded = _decode_kafka_signal_record(record.value)
                    if decoded is None:
                        continue
                    decoded["partition"] = getattr(record, "partition", topic_partition.partition)
                    decoded["offset"] = getattr(record, "offset", None)
                    latest_candidates.append(decoded)

        latest_candidates.sort(
            key=lambda item: (
                _parse_iso_timestamp(item.get("event_time")) or datetime.min.replace(tzinfo=UTC),
                _parse_calendar_date(item.get("publish_date")) or date.min,
                item.get("company_name") or "",
            ),
            reverse=True,
        )
        latest_signal = latest_candidates[0] if latest_candidates else {}
        latest_publish_date = latest_signal.get("publish_date")
        freshness_status, freshness_label = (
            _describe_external_signal_freshness(latest_publish_date)
            if latest_publish_date
            else ("stale", "Kafka 消息暂无日期")
        )
        return {
            **base_payload,
            "status": freshness_status,
            "freshness_label": freshness_label,
            "partition_count": len(topic_partitions),
            "message_count": sum(int(offset or 0) for offset in end_offsets.values()),
            "latest_publish_date": latest_publish_date,
            "latest_event_time": latest_signal.get("event_time"),
            "latest_company_name": latest_signal.get("company_name"),
            "latest_headline": latest_signal.get("headline"),
            "latest_signal_status": latest_signal.get("signal_status"),
            "latest_partition": latest_signal.get("partition"),
            "latest_offset": latest_signal.get("offset"),
        }
    except Exception as exc:
        return {
            **base_payload,
            "status": "unavailable",
            "freshness_label": "Kafka 主题不可读",
            "error": str(exc),
        }
    finally:
        consumer.close()


def _decode_kafka_signal_record(value: Any) -> dict[str, Any] | None:
    raw_text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else str(value)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _build_kafka_signal_market_tape(kafka_signal_runtime: dict[str, Any]) -> list[dict[str, Any]]:
    if kafka_signal_runtime.get("status") == "unavailable":
        return [
            {
                "label": "Kafka 主题",
                "value": "未接通",
                "delta": kafka_signal_runtime.get("freshness_label") or "Kafka 未就绪",
                "tone": "risk",
            }
        ]
    latest_anchor = (
        kafka_signal_runtime.get("latest_publish_date")
        or kafka_signal_runtime.get("latest_event_time")
        or "等待新消息"
    )
    tone = "risk" if kafka_signal_runtime.get("status") == "stale" else "success"
    return [
        {
            "label": "Kafka 主题",
            "value": str(kafka_signal_runtime.get("message_count") or 0),
            "delta": f"{kafka_signal_runtime.get('partition_count') or 0} 分区 · {latest_anchor}",
            "tone": tone,
        },
        {
            "label": "实时流状态",
            "value": kafka_signal_runtime.get("freshness_label") or "未知",
            "delta": kafka_signal_runtime.get("latest_company_name") or kafka_signal_runtime.get("topic") or "等待消息",
            "tone": tone,
        },
    ]


def _load_company_signal_snapshot(
    settings: Settings,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    snapshot_path = settings.silver_data_path / "stream" / "company_signal_snapshot.json"
    if not snapshot_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "流式热点快照未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "top_companies": [],
        }
    with snapshot_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    company_records = [
        item
        for item in records
        if item.get("company_name") and str(item.get("security_code") or "").upper() != "INDUSTRY"
    ]
    company_records.sort(
        key=lambda item: (
            int(item.get("external_heat") or 0),
            int(item.get("signal_count") or 0),
            _parse_iso_timestamp(item.get("latest_event_time")) or datetime.min.replace(tzinfo=UTC),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    latest_event_date = max(
        (
            _parse_calendar_date(item.get("latest_event_time"))
            for item in company_records
            if _parse_calendar_date(item.get("latest_event_time")) is not None
        ),
        default=None,
    )
    latest_event_text = latest_event_date.isoformat() if latest_event_date else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_text)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_text,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "top_companies": company_records[:limit],
    }


def _load_company_signal_timeline(
    settings: Settings,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    timeline_path = _gold_data_root(settings) / "stream" / "company_signal_timeline.json"
    if not timeline_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "公司时序热度未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "date_axis": [],
            "top_companies": [],
        }
    with timeline_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    latest_event_date = payload.get("date_axis", [])[-1] if payload.get("date_axis") else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_date)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_date,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "date_axis": payload.get("date_axis", []),
        "top_companies": [item for item in payload.get("top_companies", records[:limit]) if isinstance(item, dict)][:limit],
    }


def _load_subindustry_signal_heatmap(settings: Settings) -> dict[str, Any]:
    heatmap_path = _gold_data_root(settings) / "stream" / "subindustry_signal_heatmap.json"
    if not heatmap_path.exists():
        return {
            "status": "unavailable",
            "freshness_label": "子行业热度迁移未就绪",
            "generated_at": None,
            "latest_event_date": None,
            "ingest_batch_id": None,
            "record_count": 0,
            "date_axis": [],
            "top_subindustries": [],
        }
    with heatmap_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_records = payload.get("records", [])
    records = [item for item in raw_records if isinstance(item, dict)]
    latest_event_date = payload.get("date_axis", [])[-1] if payload.get("date_axis") else None
    freshness_status, freshness_label = _describe_external_signal_freshness(latest_event_date)
    return {
        "status": freshness_status,
        "freshness_label": freshness_label,
        "generated_at": payload.get("generated_at"),
        "latest_event_date": latest_event_date,
        "ingest_batch_id": payload.get("ingest_batch_id"),
        "record_count": payload.get("record_count", len(records)),
        "date_axis": payload.get("date_axis", []),
        "top_subindustries": [item for item in payload.get("top_subindustries", records[:6]) if isinstance(item, dict)],
    }


def _build_company_signal_graph_context(
    settings: Settings,
    *,
    company_name: str,
    subindustry: str | None = None,
) -> dict[str, Any]:
    snapshot = _load_company_signal_snapshot(settings, limit=256)
    timeline = _load_company_signal_timeline(settings, limit=256)
    heatmap = _load_subindustry_signal_heatmap(settings)
    snapshot_item = next(
        (
            item
            for item in snapshot.get("top_companies", [])
            if str(item.get("company_name") or "").strip() == company_name
        ),
        {},
    )
    timeline_item = next(
        (
            item
            for item in timeline.get("top_companies", [])
            if str(item.get("company_name") or "").strip() == company_name
        ),
        {},
    )
    resolved_subindustry = (
        str(timeline_item.get("subindustry") or snapshot_item.get("subindustry") or subindustry or "").strip()
    )
    subindustry_item = next(
        (
            item
            for item in heatmap.get("top_subindustries", [])
            if str(item.get("subindustry") or "").strip() == resolved_subindustry
        ),
        {},
    )
    latest_event_time = timeline_item.get("latest_event_time") or snapshot_item.get("latest_event_time")
    latest_event_date = _parse_calendar_date(str(latest_event_time) if latest_event_time is not None else None)
    freshness_status, freshness_label = _describe_external_signal_freshness(
        latest_event_date.isoformat() if latest_event_date is not None else None
    )
    window_days = max(
        len(timeline.get("date_axis", [])),
        len(timeline_item.get("timeline", [])) if isinstance(timeline_item.get("timeline"), list) else 0,
        len(subindustry_item.get("timeline", [])) if isinstance(subindustry_item.get("timeline"), list) else 0,
    )
    signal_count = int(timeline_item.get("signal_count") or snapshot_item.get("signal_count") or 0)
    source_count = int(snapshot_item.get("source_count") or 0)
    total_heat = int(timeline_item.get("total_heat") or snapshot_item.get("external_heat") or 0)
    latest_heat = int(
        timeline_item.get("latest_heat")
        or (
            timeline_item.get("timeline", [])[-1].get("external_heat", 0)
            if timeline_item.get("timeline")
            else 0
        )
        or 0
    )
    momentum = int(timeline_item.get("momentum") or 0)
    active_days = int(timeline_item.get("active_days") or 0)
    latest_headline = (
        timeline_item.get("latest_headline")
        or snapshot_item.get("latest_headline")
        or None
    )
    signal_status = (
        timeline_item.get("latest_signal_status")
        or snapshot_item.get("latest_signal_status")
        or None
    )
    latest_signal_kind = (
        timeline_item.get("latest_signal_kind")
        or snapshot_item.get("latest_signal_kind")
        or None
    )
    subindustry_signal_count = int(subindustry_item.get("signal_count") or 0)
    subindustry_total_heat = int(subindustry_item.get("total_heat") or 0)
    subindustry_latest_heat = int(subindustry_item.get("latest_heat") or 0)
    subindustry_momentum = int(subindustry_item.get("momentum") or 0)
    subindustry_active_days = int(subindustry_item.get("active_days") or 0)
    return {
        "available": bool(snapshot_item or timeline_item or subindustry_item),
        "event_available": bool(snapshot_item or timeline_item),
        "timeline_available": bool(timeline_item),
        "subindustry_available": bool(subindustry_item),
        "subindustry": resolved_subindustry or None,
        "freshness_status": freshness_status,
        "freshness_label": freshness_label,
        "latest_event_time": latest_event_time,
        "latest_headline": latest_headline,
        "signal_status": signal_status,
        "latest_signal_kind": latest_signal_kind,
        "signal_count": signal_count,
        "source_count": source_count,
        "total_heat": total_heat,
        "latest_heat": latest_heat,
        "momentum": momentum,
        "active_days": active_days,
        "window_days": window_days,
        "date_axis": timeline.get("date_axis", []),
        "event_summary": (
            f"{signal_status or '外部信号'}：{latest_headline or '最近事件已更新'}；"
            f"{freshness_label}，累计 {signal_count} 条正式信号。"
        ),
        "timeline_summary": (
            f"近 {window_days or 7} 日信号 {signal_count} 条，累计热度 {total_heat}，"
            f"动量 {momentum}，活跃 {active_days} 天。"
        ),
        "subindustry_signal_count": subindustry_signal_count,
        "subindustry_total_heat": subindustry_total_heat,
        "subindustry_latest_heat": subindustry_latest_heat,
        "subindustry_momentum": subindustry_momentum,
        "subindustry_active_days": subindustry_active_days,
        "subindustry_summary": (
            f"{resolved_subindustry or '所属子行业'} 近 {window_days or 7} 日总热度 {subindustry_total_heat}，"
            f"最新窗口热度 {subindustry_latest_heat}，动量 {subindustry_momentum}。"
        ),
    }


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    records = payload.get("records", [])
    return [item for item in records if isinstance(item, dict)]
