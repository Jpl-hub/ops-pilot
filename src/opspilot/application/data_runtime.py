from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.config import Settings
from opspilot.application.industry_signals import _gold_data_root
from opspilot.application.runtime_views import _innovation_radar_path


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "record_count": 0,
            "company_count": 0,
            "manifest_path": str(path),
        }
    with path.open("r", encoding="utf-8") as file:
        try:
            payload = json.load(file)
        except json.JSONDecodeError:
            return {
                "available": False,
                "record_count": 0,
                "company_count": 0,
                "manifest_path": str(path),
            }
    records = payload.get("records", [])
    return {
        "available": True,
        "record_count": payload.get("record_count", len(records)),
        "company_count": len(
            {record.get("security_code") for record in records if record.get("security_code")}
        ),
        "generated_at": payload.get("generated_at"),
        "manifest_path": str(path),
    }


def _build_official_data_status(settings: Settings) -> dict[str, Any]:
    manifests_root = settings.official_data_path / "manifests"
    bronze_manifests_root = settings.bronze_data_path / "manifests"
    silver_manifests_root = settings.silver_data_path / "manifests"
    gold_manifests_root = _gold_data_root(settings) / "manifests"
    periodic_manifest = _read_manifest(manifests_root / "periodic_reports_manifest.json")
    research_manifest = _read_manifest(manifests_root / "research_reports_manifest.json")
    industry_research_manifest = _read_manifest(
        manifests_root / "industry_research_reports_manifest.json"
    )
    bronze_periodic_manifest = _read_manifest(
        bronze_manifests_root / "parsed_periodic_reports_manifest.json"
    )
    bronze_signal_manifest = _read_manifest(
        bronze_manifests_root / "external_signal_stream_manifest.json"
    )
    silver_metrics_manifest = _read_manifest(
        silver_manifests_root / "financial_metrics_manifest.json"
    )
    silver_signal_snapshot_manifest = _read_manifest(
        silver_manifests_root / "company_signal_snapshot_manifest.json"
    )
    gold_company_timeline_manifest = _read_manifest(
        gold_manifests_root / "company_signal_timeline_manifest.json"
    )
    gold_subindustry_heatmap_manifest = _read_manifest(
        gold_manifests_root / "subindustry_signal_heatmap_manifest.json"
    )
    snapshot_manifest = _read_manifest(manifests_root / "company_snapshots_manifest.json")
    return {
        "official_data_root": str(settings.official_data_path),
        "bronze_data_root": str(settings.bronze_data_path),
        "silver_data_root": str(settings.silver_data_path),
        "gold_data_root": str(_gold_data_root(settings)),
        "periodic_reports": periodic_manifest,
        "research_reports": research_manifest,
        "industry_research_reports": industry_research_manifest,
        "company_snapshots": snapshot_manifest,
        "bronze_periodic_reports": bronze_periodic_manifest,
        "bronze_signal_events": bronze_signal_manifest,
        "silver_financial_metrics": silver_metrics_manifest,
        "silver_signal_snapshot": silver_signal_snapshot_manifest,
        "gold_company_signal_timeline": gold_company_timeline_manifest,
        "gold_subindustry_signal_heatmap": gold_subindustry_heatmap_manifest,
    }


def _build_innovation_radar() -> dict[str, Any]:
    radar_path = _innovation_radar_path()
    if not radar_path.exists():
        return {
            "generated_at": None,
            "focus": "新能源企业运营决策系统",
            "items": [],
            "summary": {"total": 0, "in_progress": 0, "planned": 0},
        }
    with radar_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    items = payload.get("items", [])
    return {
        "generated_at": payload.get("generated_at"),
        "focus": payload.get("focus"),
        "items": items,
        "summary": {
            "total": len(items),
            "in_progress": sum(
                1 for item in items if item.get("adoption_status") == "in_progress"
            ),
            "planned": sum(1 for item in items if item.get("adoption_status") == "planned"),
        },
    }


def _load_research_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return list(payload.get("records", []))


def _build_industry_live_chart(points: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [point["timestamp"] for point in points]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": ["预警", "任务", "跟踪", "记录"], "top": 0},
        "xAxis": {"type": "category", "data": timestamps},
        "yAxis": {"type": "value"},
        "series": [
            {"name": "预警", "type": "line", "smooth": True, "data": [point["alerts"] for point in points]},
            {"name": "任务", "type": "line", "smooth": True, "data": [point["tasks"] for point in points]},
            {"name": "跟踪", "type": "line", "smooth": True, "data": [point["watching"] for point in points]},
            {"name": "记录", "type": "bar", "data": [point["history"] for point in points]},
        ],
    }


def _build_industry_risk_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    companies = [row["company_name"] for row in rows]
    scores = [row["risk_score"] for row in rows]
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": companies},
        "yAxis": {"type": "value", "name": "风险值"},
        "series": [
            {
                "name": "风险值",
                "type": "bar",
                "data": scores,
                "itemStyle": {"color": "#ef4444"},
            }
        ],
    }
