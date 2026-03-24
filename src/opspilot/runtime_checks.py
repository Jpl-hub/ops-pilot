from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.config import Settings, get_settings


def build_runtime_report(settings: Settings) -> dict[str, Any]:
    ocr_assets_path = Path(settings.ocr_assets_path)
    checks = [
        {
            "key": "postgres_dsn",
            "status": "ready" if bool(settings.postgres_dsn) else "blocked",
            "detail": settings.postgres_dsn.split("@")[-1] if settings.postgres_dsn else "missing",
            "summary": "数据库 DSN 已配置。" if settings.postgres_dsn else "数据库 DSN 缺失。",
            "remediation": "在 .env 中配置 OPS_PILOT_POSTGRES_DSN。",
        },
        {
            "key": "official_data",
            "status": "ready" if settings.official_data_path.exists() else "blocked",
            "detail": str(settings.official_data_path),
            "summary": "原始数据目录存在。"
            if settings.official_data_path.exists()
            else "原始数据目录不存在。",
            "remediation": "确认 data/raw/official 已挂载到交付环境。",
        },
        {
            "key": "silver_data",
            "status": "ready" if settings.silver_data_path.exists() else "blocked",
            "detail": str(settings.silver_data_path),
            "summary": "银层目录存在。"
            if settings.silver_data_path.exists()
            else "银层目录不存在。",
            "remediation": "运行 silver 指标流水线，或确认目录已挂载。",
        },
        {
            "key": "ocr_runtime_flag",
            "status": "ready" if settings.ocr_runtime_enabled else "blocked",
            "detail": str(settings.ocr_runtime_enabled).lower(),
            "summary": "OCR 运行时已启用。"
            if settings.ocr_runtime_enabled
            else "OCR 运行时未启用。",
            "remediation": "在 .env 或 docker-compose 环境中设置 OPS_PILOT_OCR_RUNTIME_ENABLED=true。",
        },
        {
            "key": "ocr_assets",
            "status": "ready" if ocr_assets_path.exists() else "blocked",
            "detail": str(ocr_assets_path),
            "summary": "OCR 模型目录存在。" if ocr_assets_path.exists() else "OCR 模型目录不存在。",
            "remediation": f"先执行 ops-pilot-init-ocr-assets，再把正式模型文件放入 {ocr_assets_path}。",
        },
    ]
    blocked = [item for item in checks if item["status"] == "blocked"]
    return {
        "status": "ready" if not blocked else "blocked",
        "blocked_count": len(blocked),
        "checks": checks,
        "recommended_actions": [item["remediation"] for item in blocked],
    }


def validate_delivery_runtime(settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    report = build_runtime_report(resolved)
    if report["status"] != "ready":
        blocked = [item for item in report["checks"] if item["status"] == "blocked"]
        reasons = ", ".join(f"{item['key']}={item['detail']}" for item in blocked)
        raise RuntimeError(f"交付运行时检查失败: {reasons}")
    return report


def main() -> None:
    report = build_runtime_report(get_settings())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ready":
        raise SystemExit(2)
