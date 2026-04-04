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

    consumer = None
    try:
        consumer = KafkaConsumer(
            bootstrap_servers=[item.strip() for item in bootstrap_servers.split(",") if item.strip()],
            enable_auto_commit=False,
            auto_offset_reset="latest",
            consumer_timeout_ms=1200,
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=5000,
            metadata_max_age_ms=5000,
        )
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
        if consumer is not None:
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


def _build_streaming_heat_chart(heatmap: dict[str, Any]) -> dict[str, Any]:
    date_axis = heatmap.get("date_axis", [])
    rows = heatmap.get("top_subindustries", [])[:4]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {
            "textStyle": {"color": "#94a3b8"},
            "data": [item.get("subindustry", "未分类") for item in rows],
        },
        "grid": {"left": 48, "right": 24, "top": 48, "bottom": 36},
        "xAxis": {
            "type": "category",
            "data": date_axis,
            "axisLine": {"lineStyle": {"color": "#334155"}},
            "axisLabel": {"color": "#94a3b8"},
        },
        "yAxis": {
            "type": "value",
            "axisLine": {"lineStyle": {"color": "#334155"}},
            "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.16)"}},
            "axisLabel": {"color": "#94a3b8"},
        },
        "series": [
            {
                "name": item.get("subindustry", "未分类"),
                "type": "line",
                "smooth": True,
                "showSymbol": False,
                "areaStyle": {"opacity": 0.12},
                "data": [point.get("external_heat", 0) for point in item.get("timeline", [])],
            }
            for item in rows
        ],
    }


def _build_streaming_anomaly_board(
    *,
    preferred_period: str,
    top_risk_companies: list[dict[str, Any]],
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    signal_heatmap: dict[str, Any],
    kafka_signal_runtime: dict[str, Any],
    limit: int = 6,
) -> dict[str, Any]:
    risk_by_company = {
        str(item.get("company_name")): item
        for item in top_risk_companies
        if item.get("company_name")
    }
    snapshot_by_company = {
        str(item.get("company_name")): item
        for item in signal_snapshot.get("top_companies", [])
        if item.get("company_name")
    }
    timeline_by_company = {
        str(item.get("company_name")): item
        for item in signal_timeline.get("top_companies", [])
        if item.get("company_name")
    }
    heat_by_subindustry = {
        str(item.get("subindustry")): item
        for item in signal_heatmap.get("top_subindustries", [])
        if item.get("subindustry")
    }
    ordered_names: list[str] = []
    for bucket in (
        signal_timeline.get("top_companies", []),
        signal_snapshot.get("top_companies", []),
        top_risk_companies,
    ):
        for item in bucket:
            company_name = str(item.get("company_name") or "").strip()
            if company_name and company_name not in ordered_names:
                ordered_names.append(company_name)

    status, freshness_label = _summarize_streaming_anomaly_status(
        signal_snapshot=signal_snapshot,
        signal_timeline=signal_timeline,
        signal_heatmap=signal_heatmap,
        kafka_signal_runtime=kafka_signal_runtime,
    )
    items: list[dict[str, Any]] = []
    live_company = (
        str(kafka_signal_runtime.get("latest_company_name") or "").strip()
        if kafka_signal_runtime.get("status") == "fresh"
        else ""
    )
    for company_name in ordered_names:
        snapshot_item = snapshot_by_company.get(company_name, {})
        timeline_item = timeline_by_company.get(company_name, {})
        risk_item = risk_by_company.get(company_name, {})
        subindustry = (
            timeline_item.get("subindustry")
            or snapshot_item.get("subindustry")
            or risk_item.get("subindustry")
        )
        sector_item = heat_by_subindustry.get(str(subindustry), {})
        timeline_points = [
            int(point.get("external_heat") or 0)
            for point in timeline_item.get("timeline", [])
            if isinstance(point, dict)
        ]
        previous_points = timeline_points[:-1]
        latest_window_heat = int(
            timeline_item.get("latest_heat")
            or (timeline_points[-1] if timeline_points else 0)
        )
        baseline_heat = _safe_average(previous_points)
        burst_ratio = round(latest_window_heat / max(1.0, baseline_heat), 2) if latest_window_heat else 0.0
        signal_count = int(timeline_item.get("signal_count") or snapshot_item.get("signal_count") or 0)
        source_count = int(snapshot_item.get("source_count") or 0)
        external_heat = int(timeline_item.get("total_heat") or snapshot_item.get("external_heat") or 0)
        momentum = int(timeline_item.get("momentum") or 0)
        active_days = int(timeline_item.get("active_days") or 0)
        risk_count = int(risk_item.get("risk_count") or 0)
        risk_labels = list(risk_item.get("risk_labels") or [])
        sector_latest_heat = int(sector_item.get("latest_heat") or 0)
        sector_momentum = int(sector_item.get("momentum") or 0)
        is_live_company = bool(live_company and live_company == company_name)

        score = 0
        triggers: list[str] = []
        if latest_window_heat >= 3:
            score += 18
            triggers.append("最新窗口热度抬升")
        if external_heat >= 4:
            score += 14
            triggers.append("总热度进入高位")
        if momentum >= 4:
            score += min(18, momentum * 4)
            triggers.append("热度动量持续为正")
        if active_days and active_days <= 2 and signal_count >= 2:
            score += 14
            triggers.append(f"{active_days} 天内形成密集信号")
        if source_count >= 2:
            score += 12
            triggers.append(f"{source_count} 类正式来源共振")
        if burst_ratio >= 2 and latest_window_heat >= 2:
            score += 10
            triggers.append(f"窗口热度较基线放大 {burst_ratio} 倍")
        if risk_count >= 3:
            score += 14
            triggers.append(f"{risk_count} 个经营风险标签共振")
        elif risk_count > 0:
            score += 6
            triggers.append(f"叠加 {risk_count} 个经营风险标签")
        if sector_latest_heat >= 3 or sector_momentum >= 4:
            score += 8
            triggers.append(f"{subindustry or '所属板块'} 同步升温")
        if is_live_company:
            score += 8
            triggers.append("Kafka 实时流刚命中该公司")

        if score < 24:
            continue

        severity = _classify_streaming_anomaly_severity(score)
        anomaly_type = _classify_streaming_anomaly_type(
            burst_ratio=burst_ratio,
            risk_count=risk_count,
            source_count=source_count,
            sector_latest_heat=sector_latest_heat,
            latest_window_heat=latest_window_heat,
        )
        status_label = {
            "critical": "高危异动",
            "high": "重点异动",
            "medium": "持续异动",
            "low": "轻度异动",
        }.get(severity, "异动跟踪")
        items.append(
            {
                "company_name": company_name,
                "subindustry": subindustry,
                "headline": (
                    timeline_item.get("latest_headline")
                    or snapshot_item.get("latest_headline")
                    or (risk_labels[0] if risk_labels else "继续跟踪")
                ),
                "signal_status": (
                    timeline_item.get("latest_signal_status")
                    or snapshot_item.get("latest_signal_status")
                    or "风险跟踪"
                ),
                "severity": severity,
                "status_label": status_label,
                "tone": "risk" if severity in {"critical", "high"} else "warning",
                "score": score,
                "anomaly_type": anomaly_type,
                "summary": _summarize_streaming_anomaly(
                    company_name=company_name,
                    signal_status=timeline_item.get("latest_signal_status")
                    or snapshot_item.get("latest_signal_status"),
                    signal_count=signal_count,
                    source_count=source_count,
                    external_heat=external_heat,
                    latest_window_heat=latest_window_heat,
                    burst_ratio=burst_ratio,
                    risk_count=risk_count,
                    subindustry=subindustry,
                ),
                "triggers": triggers[:4],
                "evidence": [
                    f"热度 {latest_window_heat}/{external_heat}（窗口/累计）",
                    f"信号 {signal_count} 条 · 来源 {source_count} 类 · 活跃 {active_days} 天",
                    f"风险标签 {risk_count} 个",
                ],
                "risk_count": risk_count,
                "risk_labels": risk_labels[:3],
                "signal_count": signal_count,
                "source_count": source_count,
                "external_heat": external_heat,
                "latest_heat": latest_window_heat,
                "momentum": momentum,
                "active_days": active_days,
                "burst_ratio": burst_ratio,
                "latest_event_time": timeline_item.get("latest_event_time")
                or snapshot_item.get("latest_event_time"),
                "route": {
                    "path": "/score",
                    "query": {"company": company_name, "period": preferred_period},
                },
            }
        )
    items.sort(
        key=lambda item: (
            _streaming_anomaly_severity_rank(item.get("severity")),
            int(item.get("score") or 0),
            int(item.get("external_heat") or 0),
            item.get("company_name") or "",
        ),
        reverse=True,
    )
    summary = {
        "detected_count": len(items),
        "critical_count": sum(1 for item in items if item.get("severity") == "critical"),
        "high_count": sum(1 for item in items if item.get("severity") == "high"),
        "medium_count": sum(1 for item in items if item.get("severity") == "medium"),
        "risk_resonance_count": sum(
            1 for item in items if "风险" in str(item.get("anomaly_type") or "")
        ),
        "cross_source_count": sum(1 for item in items if int(item.get("source_count") or 0) >= 2),
    }
    summary["focus_line"] = (
        f"检测到 {summary['detected_count']} 家流式异动公司，"
        f"其中 {summary['critical_count'] + summary['high_count']} 家需优先处置。"
        if summary["detected_count"]
        else "当前流式快照未发现高优先级异动公司。"
    )
    return {
        "status": status,
        "freshness_label": freshness_label,
        "summary": summary,
        "items": items[:limit],
    }


def _safe_average(values: list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _summarize_streaming_anomaly_status(
    *,
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    signal_heatmap: dict[str, Any],
    kafka_signal_runtime: dict[str, Any],
) -> tuple[str, str]:
    statuses = [
        str(signal_snapshot.get("status") or ""),
        str(signal_timeline.get("status") or ""),
        str(signal_heatmap.get("status") or ""),
    ]
    if not any(status in {"fresh", "stale"} for status in statuses):
        return ("unavailable", "流式异动引擎未就绪")
    if any(status == "stale" for status in statuses):
        return ("stale", "流式异动基线已过期")
    if kafka_signal_runtime.get("status") == "fresh":
        return ("fresh", "流式异动实时订阅中")
    return ("fresh", "流式异动快照已更新")


def _classify_streaming_anomaly_type(
    *,
    burst_ratio: float,
    risk_count: int,
    source_count: int,
    sector_latest_heat: int,
    latest_window_heat: int,
) -> str:
    if risk_count >= 3 and source_count >= 2:
        return "风险共振"
    if burst_ratio >= 2 and latest_window_heat >= 2:
        return "新发脉冲"
    if sector_latest_heat >= 3:
        return "板块传导"
    if source_count >= 2:
        return "跨源汇聚"
    return "持续抬升"


def _classify_streaming_anomaly_severity(score: int) -> str:
    if score >= 64:
        return "critical"
    if score >= 46:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _streaming_anomaly_severity_rank(level: Any) -> int:
    return {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(str(level or ""), 0)


def _summarize_streaming_anomaly(
    *,
    company_name: str,
    signal_status: str | None,
    signal_count: int,
    source_count: int,
    external_heat: int,
    latest_window_heat: int,
    burst_ratio: float,
    risk_count: int,
    subindustry: str | None,
) -> str:
    summary = (
        f"{company_name} 在 {subindustry or '当前板块'} 出现 {signal_status or '正式信号'} 异动，"
        f"窗口热度 {latest_window_heat}、累计热度 {external_heat}。"
    )
    if burst_ratio >= 2:
        summary += f" 当前窗口相对历史基线放大 {burst_ratio} 倍。"
    if signal_count or source_count:
        summary += f" 近窗共捕获 {signal_count} 条信号、{source_count} 类来源。"
    if risk_count:
        summary += f" 同时叠加 {risk_count} 个经营风险标签。"
    return summary


def _build_streaming_anomaly_market_tape(
    streaming_anomalies: dict[str, Any],
) -> list[dict[str, Any]]:
    summary = streaming_anomalies.get("summary", {})
    detected_count = int(summary.get("detected_count") or 0)
    if detected_count <= 0:
        return []
    high_priority = int(summary.get("critical_count") or 0) + int(summary.get("high_count") or 0)
    tone = "risk" if high_priority else "accent"
    return [
        {
            "label": "流式异动",
            "value": str(detected_count),
            "delta": streaming_anomalies.get("freshness_label") or "异动快照已更新",
            "tone": tone,
        },
        {
            "label": "高优先级共振",
            "value": str(high_priority),
            "delta": f"{summary.get('cross_source_count', 0)} 家跨源共振",
            "tone": "risk" if high_priority else tone,
        },
    ]


def _merge_streaming_anomalies_into_attention_matrix(
    attention_matrix: list[dict[str, Any]],
    streaming_anomalies: dict[str, Any],
) -> list[dict[str, Any]]:
    anomaly_by_company = {
        str(item.get("company_name")): item
        for item in streaming_anomalies.get("items", [])
        if item.get("company_name")
    }
    merged: list[dict[str, Any]] = []
    for item in attention_matrix:
        company_name = str(item.get("company_name") or "")
        anomaly = anomaly_by_company.get(company_name)
        if anomaly is None:
            merged.append(item)
            continue
        merged.append(
            {
                **item,
                "anomaly_score": anomaly.get("score"),
                "anomaly_type": anomaly.get("anomaly_type"),
                "anomaly_severity": anomaly.get("severity"),
                "anomaly_summary": anomaly.get("summary"),
            }
        )
    return merged


def _build_streaming_attention_matrix(
    *,
    preferred_period: str,
    top_risk_companies: list[dict[str, Any]],
    signal_snapshot: dict[str, Any],
    signal_timeline: dict[str, Any],
    limit: int = 4,
) -> list[dict[str, Any]]:
    risk_by_company = {
        str(item.get("company_name")): item
        for item in top_risk_companies
        if item.get("company_name")
    }
    snapshot_by_company = {
        str(item.get("company_name")): item
        for item in signal_snapshot.get("top_companies", [])
        if item.get("company_name")
    }
    timeline_by_company = {
        str(item.get("company_name")): item
        for item in signal_timeline.get("top_companies", [])
        if item.get("company_name")
    }
    ordered_names: list[str] = []
    for item in signal_timeline.get("top_companies", []):
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    for item in signal_snapshot.get("top_companies", []):
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    for item in top_risk_companies:
        company_name = str(item.get("company_name") or "").strip()
        if company_name and company_name not in ordered_names:
            ordered_names.append(company_name)
    matrix: list[dict[str, Any]] = []
    for company_name in ordered_names[:limit]:
        risk_item = risk_by_company.get(company_name, {})
        signal_item = snapshot_by_company.get(company_name, {})
        timeline_item = timeline_by_company.get(company_name, {})
        risk_labels = list(risk_item.get("risk_labels") or [])
        matrix.append(
            {
                "company_name": company_name,
                "subindustry": timeline_item.get("subindustry") or signal_item.get("subindustry") or risk_item.get("subindustry"),
                "risk_count": int(risk_item.get("risk_count") or 0),
                "headline": timeline_item.get("latest_headline") or signal_item.get("latest_headline") or (risk_labels[0] if risk_labels else "继续跟踪"),
                "signal_status": timeline_item.get("latest_signal_status") or signal_item.get("latest_signal_status") or "风险跟踪",
                "signal_count": int(timeline_item.get("signal_count") or signal_item.get("signal_count") or 0),
                "external_heat": int(timeline_item.get("total_heat") or signal_item.get("external_heat") or 0),
                "latest_heat": int(timeline_item.get("latest_heat") or 0),
                "momentum": int(timeline_item.get("momentum") or 0),
                "active_days": int(timeline_item.get("active_days") or 0),
                "latest_event_time": timeline_item.get("latest_event_time") or signal_item.get("latest_event_time"),
                "route": risk_item.get(
                    "route",
                    {"path": "/score", "query": {"company": company_name, "period": preferred_period}},
                ),
            }
        )
    return matrix
