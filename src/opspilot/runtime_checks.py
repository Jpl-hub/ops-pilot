from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any
import hashlib
import json
import time

import httpx

from opspilot.config import Settings, get_settings


_LLM_PROBE_CACHE_TTL = 300.0
_llm_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}

PROFILE_STARTUP = "startup"
PROFILE_DELIVERY = "delivery"


def probe_llm_runtime(settings: Settings, *, force_refresh: bool = False) -> dict[str, Any]:
    openai_api_key = getattr(settings, "openai_api_key", "")
    openai_base_url = str(getattr(settings, "openai_base_url", "") or "").rstrip("/")
    env = str(getattr(settings, "env", "") or "").lower()
    if not openai_api_key:
        return {
            "key": "llm",
            "label": "LLM 运行时",
            "status": "blocked",
            "summary": "未配置 API Key，问答与多智能体编排不可用。",
            "detail": openai_base_url or "missing",
            "remediation": "在 .env 或 docker-compose 环境中配置有效的 OPS_PILOT_OPENAI_API_KEY。",
        }
    if env == "test":
        return {
            "key": "llm",
            "label": "LLM 运行时",
            "status": "ready",
            "summary": "测试环境跳过远端鉴权探测，已按配置视为可用。",
            "detail": openai_base_url or "missing",
            "remediation": "在非测试环境中使用有效模型凭证并执行实际探测。",
        }

    cache_key = hashlib.sha1(f"{openai_base_url}|{openai_api_key}".encode("utf-8")).hexdigest()
    cached = _llm_probe_cache.get(cache_key)
    if not force_refresh and cached and time.time() - cached[0] < _LLM_PROBE_CACHE_TTL:
        return dict(cached[1])

    started_at = time.perf_counter()
    probe_model = "gpt-4o-mini"
    probe_url = f"{openai_base_url}/chat/completions" if openai_base_url else ""
    try:
        response = httpx.post(
            probe_url,
            headers={"Authorization": f"Bearer {openai_api_key}"},
            json={
                "model": probe_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=10.0,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
        detail = f"{probe_url} -> {response.status_code} ({latency_ms} ms)"
        if response.is_success:
            result = {
                "key": "llm",
                "label": "LLM 运行时",
                "status": "ready",
                "summary": f"大模型鉴权成功，最小推理请求已通过，模型 {probe_model} 可用。",
                "detail": f"{detail} | model={probe_model}",
                "remediation": "无需处理。",
                "probe_model": probe_model,
                "latency_ms": latency_ms,
            }
        else:
            error_text = response.text.strip().replace("\n", " ")
            if len(error_text) > 180:
                error_text = f"{error_text[:179]}…"
            result = {
                "key": "llm",
                "label": "LLM 运行时",
                "status": "blocked",
                "summary": f"大模型鉴权失败，远端返回 {response.status_code}。",
                "detail": f"{detail} | {error_text or 'empty response'}",
                "remediation": "检查 OPS_PILOT_OPENAI_API_KEY / OPS_PILOT_OPENAI_BASE_URL 是否正确，并重新执行运行时检查。",
            }
    except httpx.HTTPError as exc:
        latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
        result = {
            "key": "llm",
            "label": "LLM 运行时",
            "status": "blocked",
            "summary": "大模型运行时探测失败，无法确认编排能力是否可用。",
            "detail": f"{probe_url or 'missing'} -> {type(exc).__name__}: {exc} ({latency_ms} ms)",
            "remediation": "检查模型网关连通性、TLS 证书与代理设置，确认容器可以访问配置的模型端点。",
        }

    _llm_probe_cache[cache_key] = (time.time(), result)
    return dict(result)


def _resolve_universe_manifest_path(settings: Settings) -> Path:
    configured_root = getattr(settings, "universe_data_path", None)
    if configured_root:
        return Path(configured_root) / "formal_company_pool.json"

    official_root = Path(getattr(settings, "official_data_path", "data/raw/official"))
    if official_root.name == "official" and official_root.parent.name == "raw":
        return official_root.parent.parent / "universe" / "formal_company_pool.json"
    if official_root.name == "raw":
        return official_root.parent / "universe" / "formal_company_pool.json"
    return official_root.parent / "universe" / "formal_company_pool.json"


def build_runtime_report(settings: Settings) -> dict[str, Any]:
    ocr_assets_path = Path(settings.ocr_assets_path)
    universe_manifest_path = _resolve_universe_manifest_path(settings)
    checks = [
        {
            **probe_llm_runtime(settings),
            "blocking_profiles": [PROFILE_STARTUP, PROFILE_DELIVERY],
        },
        {
            "key": "postgres_dsn",
            "status": "ready" if bool(settings.postgres_dsn) else "blocked",
            "detail": settings.postgres_dsn.split("@")[-1] if settings.postgres_dsn else "missing",
            "summary": "数据库 DSN 已配置。" if settings.postgres_dsn else "数据库 DSN 缺失。",
            "remediation": "在 .env 中配置 OPS_PILOT_POSTGRES_DSN。",
            "blocking_profiles": [PROFILE_STARTUP, PROFILE_DELIVERY],
        },
        {
            "key": "official_data",
            "status": "ready" if settings.official_data_path.exists() else "blocked",
            "detail": str(settings.official_data_path),
            "summary": "原始数据目录存在。"
            if settings.official_data_path.exists()
            else "原始数据目录不存在。",
            "remediation": "确认 data/raw/official 已挂载到交付环境。",
            "blocking_profiles": [PROFILE_STARTUP, PROFILE_DELIVERY],
        },
        {
            "key": "universe_data",
            "status": "ready" if universe_manifest_path.exists() else "blocked",
            "detail": str(universe_manifest_path),
            "summary": "正式公司池目录存在。"
            if universe_manifest_path.exists()
            else "正式公司池缺失。",
            "remediation": "确认 data/universe/formal_company_pool.json 已挂载到交付环境。",
            "blocking_profiles": [PROFILE_STARTUP, PROFILE_DELIVERY],
        },
        {
            "key": "silver_data",
            "status": "ready" if settings.silver_data_path.exists() else "blocked",
            "detail": str(settings.silver_data_path),
            "summary": "银层目录存在。"
            if settings.silver_data_path.exists()
            else "银层目录不存在。",
            "remediation": "运行 silver 指标流水线，或确认目录已挂载。",
            "blocking_profiles": [PROFILE_STARTUP, PROFILE_DELIVERY],
        },
        {
            "key": "ocr_runtime_flag",
            "status": "ready" if settings.ocr_runtime_enabled else "blocked",
            "detail": str(settings.ocr_runtime_enabled).lower(),
            "summary": "OCR 运行时已启用。"
            if settings.ocr_runtime_enabled
            else "OCR 运行时未启用。",
            "remediation": "在 .env 或 docker-compose 环境中设置 OPS_PILOT_OCR_RUNTIME_ENABLED=true。",
            "blocking_profiles": [PROFILE_DELIVERY],
        },
        {
            "key": "ocr_assets",
            "status": "ready" if ocr_assets_path.exists() else "blocked",
            "detail": str(ocr_assets_path),
            "summary": "OCR 模型目录存在。" if ocr_assets_path.exists() else "OCR 模型目录不存在。",
            "remediation": f"先执行 ops-pilot-init-ocr-assets，再把正式模型文件放入 {ocr_assets_path}。",
            "blocking_profiles": [PROFILE_DELIVERY],
        },
    ]
    blocked = [item for item in checks if item["status"] == "blocked"]
    return {
        "status": "ready" if not blocked else "blocked",
        "blocked_count": len(blocked),
        "checks": checks,
        "recommended_actions": [item["remediation"] for item in blocked],
    }


def _blocking_checks(report: dict[str, Any], *, profile: str) -> list[dict[str, Any]]:
    return [
        item
        for item in report.get("checks", [])
        if item.get("status") == "blocked" and profile in item.get("blocking_profiles", [PROFILE_DELIVERY])
    ]


def validate_delivery_runtime(
    settings: Settings | None = None,
    *,
    profile: str = PROFILE_DELIVERY,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    report = build_runtime_report(resolved)
    blocked = _blocking_checks(report, profile=profile)
    if blocked:
        reasons = ", ".join(f"{item['key']}={item['detail']}" for item in blocked)
        raise RuntimeError(f"交付运行时检查失败({profile}): {reasons}")
    return report


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Validate OpsPilot runtime readiness.")
    parser.add_argument(
        "--profile",
        choices=[PROFILE_STARTUP, PROFILE_DELIVERY],
        default=PROFILE_DELIVERY,
        help="startup 仅阻断核心链路；delivery 会阻断所有未达标模块。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = build_runtime_report(get_settings())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if _blocking_checks(report, profile=args.profile):
        raise SystemExit(2)
