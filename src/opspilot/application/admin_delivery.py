from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from opspilot.config import Settings
from opspilot.runtime_checks import probe_llm_runtime

from opspilot.application.document_pipeline import (
    _is_valid_standard_ocr_cells,
    _is_valid_standard_ocr_tables,
    _settings_ocr_runtime,
    _standard_ocr_artifact_path,
    _utcnow_iso,
    _write_json,
)
from opspilot.application.runtime_manifests import (
    _build_document_pipeline_run_id,
    _document_pipeline_run_detail_path,
    _load_document_pipeline_job_manifest,
    _load_document_pipeline_run_manifest,
    _load_json_if_possible,
    _write_document_pipeline_run_manifest,
)


def _resolve_universe_root(settings: Settings) -> Path:
    configured_root = getattr(settings, "universe_data_path", None)
    if configured_root:
        return Path(configured_root)

    official_root = Path(getattr(settings, "official_data_path", "data/raw/official"))
    if official_root.name == "official" and official_root.parent.name == "raw":
        return official_root.parent.parent / "universe"
    if official_root.name == "raw":
        return official_root.parent / "universe"
    return official_root.parent / "universe"


def _build_admin_quality_overview(settings: Settings, preferred_period: str | None) -> dict[str, Any]:
    universe_root = _resolve_universe_root(settings)
    company_pool = _load_json_records(universe_root / "formal_company_pool.json")
    raw_reports = _load_manifest_records(settings.official_data_path / "manifests" / "periodic_reports_manifest.json")
    research_reports = _load_manifest_records(
        settings.official_data_path / "manifests" / "research_reports_manifest.json"
    )
    bronze_reports = _load_manifest_records(
        settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    )
    silver_records = _load_manifest_records(
        settings.silver_data_path / "manifests" / "financial_metrics_manifest.json"
    )

    raw_by_company = _index_records_by_company(raw_reports)
    research_by_company = _index_records_by_company(research_reports)
    bronze_by_company = _index_records_by_company(bronze_reports)
    silver_by_company = _index_records_by_company(silver_records)

    company_rows: list[dict[str, Any]] = []
    for company in company_pool:
        company_name = company["company_name"]
        raw_items = raw_by_company.get(company_name, [])
        bronze_items = bronze_by_company.get(company_name, [])
        silver_items = silver_by_company.get(company_name, [])
        research_items = research_by_company.get(company_name, [])
        silver_periods = sorted(
            {
                item.get("report_period")
                for item in silver_items
                if item.get("report_period")
            },
            key=_period_order_key,
            reverse=True,
        )
        latest_period = silver_periods[0] if silver_periods else None
        preferred_period_ready = bool(preferred_period and preferred_period in silver_periods)
        issues: list[str] = []
        if not raw_items:
            issues.append("缺定期报告")
        if raw_items and not bronze_items:
            issues.append("缺页级解析")
        if bronze_items and not silver_items:
            issues.append("缺结构化指标")
        if not research_items:
            issues.append("缺研报")
        if preferred_period and not preferred_period_ready:
            issues.append("缺主周期")
        company_rows.append(
            {
                "company_name": company_name,
                "subindustry": company.get("subindustry", "未分类"),
                "raw_report_count": len(raw_items),
                "bronze_report_count": len(bronze_items),
                "silver_record_count": len(silver_items),
                "research_report_count": len(research_items),
                "latest_silver_period": latest_period,
                "preferred_period_ready": preferred_period_ready,
                "issues": issues,
            }
        )

    issue_buckets = [
        {
            "code": issue_code,
            "label": issue_code,
            "count": sum(1 for row in company_rows if issue_code in row["issues"]),
            "companies": [row["company_name"] for row in company_rows if issue_code in row["issues"]][:12],
        }
        for issue_code in ("缺主周期", "缺研报", "缺定期报告", "缺页级解析", "缺结构化指标")
    ]
    issue_buckets = [item for item in issue_buckets if item["count"] > 0]
    company_rows.sort(
        key=lambda item: (
            len(item["issues"]) == 0,
            len(item["issues"]),
            not item["preferred_period_ready"],
            item["company_name"],
        )
    )
    return {
        "preferred_period": preferred_period,
        "coverage": {
            "pool_companies": len(company_rows),
            "preferred_period_ready": sum(1 for row in company_rows if row["preferred_period_ready"]),
            "research_ready": sum(1 for row in company_rows if row["research_report_count"] > 0),
            "raw_ready": sum(1 for row in company_rows if row["raw_report_count"] > 0),
            "bronze_ready": sum(1 for row in company_rows if row["bronze_report_count"] > 0),
            "silver_ready": sum(1 for row in company_rows if row["silver_record_count"] > 0),
        },
        "issue_buckets": issue_buckets,
        "companies": company_rows,
    }


def _build_delivery_readiness(
    *,
    quality_overview: dict[str, Any],
    document_pipeline: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    coverage = quality_overview.get("coverage", {})
    companies = quality_overview.get("companies", [])
    issue_buckets = quality_overview.get("issue_buckets", [])
    pool_companies = coverage.get("pool_companies", 0) or 0
    preferred_period_ready = coverage.get("preferred_period_ready", 0) or 0
    silver_ready = coverage.get("silver_ready", 0) or 0
    research_ready = coverage.get("research_ready", 0) or 0
    contract_audit = document_pipeline.get("cell_trace", {}).get("contract_audit", {})
    contract_total = contract_audit.get("total", 0) or 0
    contract_ready = contract_audit.get("ready", 0) or 0
    contract_invalid = contract_audit.get("invalid", 0) or 0
    contract_missing = contract_audit.get("missing", 0) or 0
    blocker_companies = [row for row in companies if row.get("issues")]
    ready_companies = [row for row in companies if not row.get("issues")]

    coverage_ratio = round((preferred_period_ready / pool_companies) * 100) if pool_companies else 0
    silver_ratio = round((silver_ready / pool_companies) * 100) if pool_companies else 0
    research_ratio = round((research_ready / pool_companies) * 100) if pool_companies else 0
    contract_ratio = round((contract_ready / contract_total) * 100) if contract_total else 100

    if pool_companies == 0:
        stage = "bootstrapping"
    elif not ready_companies:
        stage = "blocked"
    elif contract_invalid > 0 or contract_missing > 0:
        stage = "hardening"
    elif coverage_ratio >= 85 and silver_ratio >= 85 and research_ratio >= 70 and contract_ratio >= 85:
        stage = "ready"
    else:
        stage = "hardening"

    top_blockers = sorted(issue_buckets, key=lambda item: item.get("count", 0), reverse=True)[:3]
    priority_actions = [
        {
            "title": item["label"],
            "summary": f"{item['count']} 家公司受阻，优先处理该链路。",
            "companies": item.get("companies", [])[:5],
        }
        for item in top_blockers
    ]
    if contract_invalid or contract_missing:
        priority_actions.insert(
            0,
            {
                "title": "OCR Contract 质检",
                "summary": f"{contract_ready}/{contract_total or 0} 份 contract 达标，{contract_missing} 份缺失，{contract_invalid} 份不合格。",
                "companies": [
                    item.get("company_name")
                    for item in contract_audit.get("samples", [])
                    if item.get("status") != "ready"
                ][:5],
            },
        )
    return {
        "stage": stage,
        "preferred_period": health.get("preferred_period"),
        "ready_company_count": len(ready_companies),
        "blocked_company_count": len(blocker_companies),
        "coverage_ratio": coverage_ratio,
        "silver_ratio": silver_ratio,
        "research_ratio": research_ratio,
        "contract_ratio": contract_ratio,
        "priority_actions": priority_actions[:4],
        "summary": {
            "pool_companies": pool_companies,
            "preferred_period_ready": preferred_period_ready,
            "silver_ready": silver_ready,
            "research_ready": research_ready,
            "contract_ready": contract_ready,
            "contract_total": contract_total,
            "contract_invalid": contract_invalid,
            "contract_missing": contract_missing,
        },
    }


def _build_runtime_readiness(settings: Settings) -> dict[str, Any]:
    postgres_dsn = getattr(settings, "postgres_dsn", "")
    cors_allowed_origins = tuple(getattr(settings, "cors_allowed_origins", ()) or ())
    ocr_runtime = _settings_ocr_runtime(settings)
    ocr_assets_path = Path(ocr_runtime["assets_path"])
    ocr_ready = bool(ocr_runtime["runtime_enabled"]) and ocr_assets_path.exists()
    checks = [
        probe_llm_runtime(settings),
        {
            "key": "ocr",
            "label": "OCR 标准引擎",
            "status": "ready" if ocr_ready else "blocked",
            "summary": "PaddleOCR-VL 标准链路已接通，可处理扫描件与复杂报表。"
            if ocr_ready
            else "OCR 标准链路未接通，扫描件与复杂表格解析不满足交付标准。",
            "detail": f"{ocr_runtime['provider']} / {ocr_runtime['model']} @ {ocr_assets_path}",
        },
        {
            "key": "database",
            "label": "数据库连接",
            "status": "ready" if bool(postgres_dsn) else "blocked",
            "summary": "会话、登录与运行记录依赖 PostgreSQL。"
            if postgres_dsn
            else "未配置 PostgreSQL DSN，登录与会话不可用。",
            "detail": postgres_dsn.split("@")[-1] if postgres_dsn else "missing",
        },
        {
            "key": "official_data",
            "label": "原始数据目录",
            "status": "ready" if settings.official_data_path.exists() else "blocked",
            "summary": "原始 PDF / 研报目录存在。"
            if settings.official_data_path.exists()
            else "原始数据目录不存在，数据抓取与核验链路会中断。",
            "detail": str(settings.official_data_path),
        },
        {
            "key": "silver_data",
            "label": "银层目录",
            "status": "ready" if settings.silver_data_path.exists() else "blocked",
            "summary": "结构化指标目录存在。"
            if settings.silver_data_path.exists()
            else "银层目录不存在，评分与对比能力不可交付。",
            "detail": str(settings.silver_data_path),
        },
        {
            "key": "cors",
            "label": "前端跨域",
            "status": "ready" if len(cors_allowed_origins) > 0 else "blocked",
            "summary": f"已配置 {len(cors_allowed_origins)} 个前端来源。 "
            if cors_allowed_origins
            else "未配置任何前端来源，浏览器访问会失败。",
            "detail": ", ".join(cors_allowed_origins) if cors_allowed_origins else "missing",
        },
    ]
    blocked = sum(1 for item in checks if item["status"] == "blocked")
    return {
        "status": "ready" if blocked == 0 else "blocked",
        "blocked_count": blocked,
        "checks": checks,
    }


def _build_acceptance_checklist(
    *,
    health: dict[str, Any],
    delivery_readiness: dict[str, Any],
    runtime_readiness: dict[str, Any],
    document_pipeline: dict[str, Any],
) -> dict[str, Any]:
    contract_audit = document_pipeline.get("cell_trace", {}).get("contract_audit", {})
    items = [
        {
            "key": "frontend",
            "label": "前端入口可访问",
            "status": "pass",
            "detail": "打开 http://127.0.0.1:8080 并完成登录、工作台、运营保障中心可见性检查。",
        },
        {
            "key": "api",
            "label": "API 健康检查",
            "status": "pass" if health.get("status") == "ok" else "blocked",
            "detail": "访问 http://127.0.0.1:8000/api/v1/healthz，确认 status=ok。",
        },
        {
            "key": "runtime",
            "label": "运行时依赖齐备",
            "status": "pass" if runtime_readiness.get("status") == "ready" else "blocked",
            "detail": f"当前阻断项 {runtime_readiness.get('blocked_count', 0)} 个，需全部清零。",
        },
        {
            "key": "delivery",
            "label": "系统就绪度达标",
            "status": "pass" if delivery_readiness.get("stage") == "ready" else "blocked",
            "detail": f"当前阶段 {delivery_readiness.get('stage')}，稳定可用公司数 {delivery_readiness.get('ready_company_count', 0)}。",
        },
        {
            "key": "ocr_contract",
            "label": "OCR Contract 质检通过",
            "status": "pass" if contract_audit.get("status") == "ready" else "blocked",
            "detail": f"当前达标 {contract_audit.get('ready', 0)}/{contract_audit.get('total', 0)}，缺失 {contract_audit.get('missing', 0)}，不合格 {contract_audit.get('invalid', 0)}。",
        },
    ]
    passed = sum(1 for item in items if item["status"] == "pass")
    return {
        "status": "ready" if passed == len(items) else "blocked",
        "passed": passed,
        "total": len(items),
        "items": items,
    }


def _delivery_stage_label(stage: str | None) -> str:
    mapping = {
        "bootstrapping": "启动期",
        "hardening": "加固期",
        "blocked": "阻断",
        "ready": "就绪",
    }
    return mapping.get(stage or "", stage or "-")


def _status_label(status: str | None) -> str:
    mapping = {
        "ready": "就绪",
        "blocked": "阻断",
        "pass": "通过",
        "completed": "已完成",
        "pending": "待执行",
        "invalid": "不合格",
        "missing": "缺失",
        "queued": "待启动",
        "in_progress": "处理中",
        "done": "已完成",
        "new": "新增",
        "dispatched": "已派发",
        "resolved": "已闭环",
        "dismissed": "已忽略",
        "idle": "未启动",
        "tracked": "已纳管",
        "active": "执行中",
    }
    return mapping.get(status or "", status or "-")


def _bus_type_label(bus_type: str | None) -> str:
    mapping = {
        "task": "任务推进",
        "alert": "预警处置",
        "watchboard": "重点监测",
        "analysis_run": "分析执行",
        "company_score": "经营诊断",
        "watchboard_scan": "监测扫描",
        "document_pipeline": "文档工序",
        "document_pipeline_run": "整改运行",
        "stress_run": "压力推演",
        "stress_test": "压力推演",
        "graph_run": "图谱演算",
        "graph_query": "图谱演算",
        "claim_verify": "观点核验",
        "vision_run": "多模态核验",
        "vision_analyze": "多模态核验",
    }
    return mapping.get(bus_type or "", bus_type or "-")


def _index_records_by_company(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        company_name = record.get("company_name")
        if not company_name:
            continue
        indexed.setdefault(company_name, []).append(record)
    return indexed


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def _load_manifest_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload.get("records", [])


def _period_order_key(period: str | None) -> tuple[int, int]:
    if not period:
        return (0, 0)
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|FY)", period)
    if match is None:
        return (0, 0)
    suffix_rank = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
    return (int(match.group(1)), suffix_rank[match.group(2)])


def _build_admin_job_catalog() -> list[dict[str, Any]]:
    return [
        {
            "job_id": "fetch_real_data",
            "title": "抓取真实数据",
            "description": "从交易所与研报源抓取原始公告、研报详情页与补源快照。",
            "command": "ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "raw",
        },
        {
            "job_id": "parse_official_reports",
            "title": "解析官方报告",
            "description": "把 PDF 和原始页面解析成页级文本与 chunk。",
            "command": "ops-pilot-parse-official-reports --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "bronze",
        },
        {
            "job_id": "build_silver_metrics",
            "title": "构建结构化指标",
            "description": "从 bronze 结果抽取财务指标、事件指标和证据引用。",
            "command": "ops-pilot-build-silver-metrics --codes 601012,002129,300750,300014,300274,002202",
            "output_stage": "silver",
        },
        {
            "job_id": "run_tests",
            "title": "运行系统回归",
            "description": "执行单元测试并验证核心业务链路可用。",
            "command": "python -m unittest discover -s tests -t .",
            "output_stage": "qa",
        },
    ]


def _build_document_pipeline_overview(
    data_status: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    bronze_count = data_status.get("bronze_periodic_reports", {}).get("record_count", 0)
    silver_count = data_status.get("silver_financial_metrics", {}).get("record_count", 0)
    periodic_count = data_status.get("periodic_reports", {}).get("record_count", 0)
    jobs_manifest = _load_document_pipeline_job_manifest(settings)
    records = jobs_manifest["records"]
    cross_page_completed = sum(
        1 for item in records if item["stage"] == "cross_page_merge" and item["status"] == "completed"
    )
    title_completed = sum(
        1 for item in records if item["stage"] == "title_hierarchy" and item["status"] == "completed"
    )
    ocr_runtime = _settings_ocr_runtime(settings)
    cell_completed = sum(
        1 for item in records if item["stage"] == "cell_trace" and item["status"] == "completed"
    )
    contract_audit = _build_ocr_cell_trace_contract_audit(settings, records)
    return {
        "layout_engine": ocr_runtime["layout_engine"],
        "ocr_engine": f"{ocr_runtime['provider']} / {ocr_runtime['model']}",
        "ocr_runtime_enabled": ocr_runtime["runtime_enabled"],
        "cross_page_merge": {
            "enabled": True,
            "status": f"completed {cross_page_completed}",
            "summary": "已支持基于真实页文本生成跨页续写与续表候选清单。",
        },
        "title_hierarchy": {
            "enabled": True,
            "status": f"completed {title_completed}",
            "summary": "已支持从真实页块中恢复标题层级，用于目录导航和段落定位。",
        },
        "cell_trace": {
            "enabled": True,
            "status": f"completed {cell_completed}",
            "completed": cell_completed,
            "summary": "统一文档理解链路：标准 OCR 引擎产出表格片段与单元格证据链。",
            "contract_audit": contract_audit,
        },
        "coverage": [
            {"label": "原始文档", "value": periodic_count, "unit": "份"},
            {"label": "页级解析", "value": bronze_count, "unit": "条"},
            {"label": "结构化指标", "value": silver_count, "unit": "条"},
        ],
    }


def _document_stage_label(stage: str) -> str:
    return {
        "cross_page_merge": "跨页拼接",
        "title_hierarchy": "标题层级",
        "cell_trace": "单元格溯源",
    }.get(stage, stage)


def _build_ocr_cell_trace_contract_audit(
    settings: Settings, records: list[dict[str, Any]]
) -> dict[str, Any]:
    latest_jobs: dict[str, dict[str, Any]] = {}
    for item in records:
        if item.get("stage") != "cell_trace":
            continue
        report_id = item.get("report_id")
        if not report_id:
            continue
        current = latest_jobs.get(report_id)
        current_stamp = (
            (current.get("completed_at") or current.get("created_at")) if current else ""
        )
        candidate_stamp = item.get("completed_at") or item.get("created_at") or ""
        if current is None or candidate_stamp >= current_stamp:
            latest_jobs[report_id] = item

    summary = {"ready": 0, "invalid": 0, "missing": 0}
    samples: list[dict[str, Any]] = []
    for job in latest_jobs.values():
        ocr_artifact_path = _standard_ocr_artifact_path(settings, job)
        if not ocr_artifact_path.exists():
            status = "missing"
            detail = "缺少标准 OCR contract 产物"
        else:
            payload = _load_json_if_possible(ocr_artifact_path)
            if payload and _is_valid_standard_ocr_tables(payload.get("tables", [])) and _is_valid_standard_ocr_cells(payload.get("cells", [])):
                status = "ready"
                detail = "contract 合法"
            else:
                status = "invalid"
                detail = "contract 存在但字段不合法"
        summary[status] += 1
        if len(samples) < 6:
            samples.append(
                {
                    "report_id": job.get("report_id"),
                    "company_name": job.get("company_name"),
                    "report_period": job.get("report_period"),
                    "status": status,
                    "detail": detail,
                    "path": str(ocr_artifact_path),
                }
            )
    total = sum(summary.values())
    return {
        "total": total,
        "ready": summary["ready"],
        "invalid": summary["invalid"],
        "missing": summary["missing"],
        "status": "ready" if total == 0 or (summary["invalid"] == 0 and summary["missing"] == 0) else "blocked",
        "samples": samples,
    }


def _resolve_document_contract_status(settings: Settings, item: dict[str, Any]) -> str | None:
    if item.get("stage") != "cell_trace":
        return None
    ocr_artifact_path = _standard_ocr_artifact_path(settings, item)
    if not ocr_artifact_path.exists():
        return "missing"
    payload = _load_json_if_possible(ocr_artifact_path)
    if payload and _is_valid_standard_ocr_tables(payload.get("tables", [])) and _is_valid_standard_ocr_cells(payload.get("cells", [])):
        return "ready"
    return "invalid"


def _summarize_contract_statuses(
    records: list[dict[str, Any]], *, settings: Settings, stage: str
) -> dict[str, int]:
    if stage != "cell_trace":
        return {"ready": 0, "invalid": 0, "missing": 0}
    summary = {"ready": 0, "invalid": 0, "missing": 0}
    for item in records:
        if item.get("stage") != "cell_trace":
            continue
        status = _resolve_document_contract_status(settings, item)
        if status in summary:
            summary[status] += 1
    return summary


def _build_document_pipeline_execution_feedback(
    *,
    stage: str,
    contract_status: str | None,
    processed: int,
    before_summary: dict[str, int],
    after_summary: dict[str, int],
) -> dict[str, Any]:
    fixed_count = 0
    remaining_count = 0
    if stage == "cell_trace" and contract_status in {"missing", "invalid"}:
        fixed_count = max(before_summary.get(contract_status, 0) - after_summary.get(contract_status, 0), 0)
        remaining_count = after_summary.get(contract_status, 0)
        headline = f"本次重跑处理 {processed} 份文档，修复 {fixed_count} 份，剩余 {remaining_count} 份 {contract_status}。"
    else:
        headline = f"本次执行完成 {processed} 个 {stage} 作业。"
    return {
        "headline": headline,
        "processed": processed,
        "fixed_count": fixed_count,
        "remaining_count": remaining_count,
        "before": before_summary,
        "after": after_summary,
    }


def _append_document_pipeline_run_record(
    settings: Settings,
    *,
    stage: str,
    artifact_source: str | None,
    contract_status: str | None,
    results: list[dict[str, Any]],
    execution_feedback: dict[str, Any],
) -> dict[str, Any]:
    run_id = _build_document_pipeline_run_id(stage)
    created_at = _utcnow_iso()
    detail_payload = {
        "run_id": run_id,
        "created_at": created_at,
        "stage": stage,
        "artifact_source": artifact_source,
        "contract_status": contract_status,
        "processed": len(results),
        "companies": [item.get("company_name") for item in results if item.get("company_name")],
        "results": results,
        "execution_feedback": execution_feedback,
    }
    detail_path = _document_pipeline_run_detail_path(settings, run_id)
    _write_json(detail_path, detail_payload)
    manifest = _load_document_pipeline_run_manifest(settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    report_period = None
    if results:
        first_result = results[0]
        report_id = first_result.get("report_id")
        jobs_manifest = _load_document_pipeline_job_manifest(settings)
        job = next(
            (
                item
                for item in jobs_manifest["records"]
                if item.get("stage") == stage and item.get("report_id") == report_id
            ),
            None,
        )
        report_period = job.get("report_period") if job else None
    records.append(
        {
            "run_id": run_id,
            "created_at": created_at,
            "stage": stage,
            "artifact_source": artifact_source,
            "contract_status": contract_status,
            "processed": len(results),
            "report_period": report_period,
            "companies": detail_payload["companies"],
            "status": "completed",
            "execution_feedback": execution_feedback,
        }
    )
    manifest["records"] = records[-200:]
    _write_document_pipeline_run_manifest(settings, manifest)
    return records[-1]


def _build_delivery_report_payload(
    *,
    overview: dict[str, Any],
    app_name: str,
    env: str,
) -> dict[str, Any]:
    health = overview["health"]
    runtime_readiness = overview["runtime_readiness"]
    delivery_readiness = overview["delivery_readiness"]
    acceptance_checklist = overview["acceptance_checklist"]
    quality_overview = overview["quality_overview"]
    workspace_runtime_audit = overview["workspace_runtime_audit"]
    contract_audit = overview["document_pipeline"]["cell_trace"]["contract_audit"]
    runtime_blockers = [
        {
            "label": item["label"],
            "summary": item["summary"],
            "detail": item["detail"],
            "remediation": item.get("remediation"),
        }
        for item in runtime_readiness.get("checks", [])
        if item.get("status") == "blocked"
    ]
    acceptance_blockers = [
        {"label": item["label"], "detail": item["detail"]}
        for item in acceptance_checklist.get("items", [])
        if item.get("status") == "blocked"
    ]
    remediation_runs = [
        {
            "title": item["title"],
            "created_at": item["created_at"],
            "headline": item.get("meta", {}).get("headline"),
            "processed": item.get("meta", {}).get("processed"),
            "fixed_count": item.get("meta", {}).get("fixed_count"),
            "remaining_count": item.get("meta", {}).get("remaining_count"),
        }
        for item in overview.get("workspace_history", {}).get("records", [])
        if item.get("history_type") == "document_pipeline_run"
    ][:5]
    issue_buckets = [
        {
            "label": item.get("label"),
            "count": item.get("count", 0),
            "companies": item.get("companies", [])[:5],
        }
        for item in quality_overview.get("issue_buckets", [])[:5]
    ]
    executive_summary = [
        f"当前系统阶段为{_delivery_stage_label(delivery_readiness.get('stage'))}，主周期 {health.get('preferred_period') or '-'} 稳定可用 {delivery_readiness.get('ready_company_count', 0)} 家公司。",
        f"运行阻断 {runtime_readiness.get('blocked_count', 0)} 项，关键检查通过 {acceptance_checklist.get('passed', 0)}/{acceptance_checklist.get('total', 0)} 项。",
        f"近 {workspace_runtime_audit.get('window_size', 0)} 条智能体运行里，强支撑占比 {workspace_runtime_audit.get('summary_cards', {}).get('grounded_ratio', 0)}%，完整轨迹占比 {workspace_runtime_audit.get('summary_cards', {}).get('trace_ratio', 0)}%。",
        f"OCR Contract 当前达标 {contract_audit.get('ready', 0)}/{contract_audit.get('total', 0)}，缺失 {contract_audit.get('missing', 0)}，不合格 {contract_audit.get('invalid', 0)}。",
    ]
    ready = (
        acceptance_checklist.get("status") == "ready"
        and runtime_readiness.get("status") == "ready"
    )
    return {
        "generated_at": _utcnow_iso(),
        "app_name": health.get("app_name", app_name),
        "env": health.get("env", env),
        "preferred_period": health.get("preferred_period"),
        "overall_status": "ready" if ready else "blocked",
        "overall_label": "稳定可用" if ready else "待治理",
        "executive_summary": executive_summary,
        "summary_cards": {
            "pool_companies": quality_overview.get("coverage", {}).get("pool_companies", 0),
            "ready_company_count": delivery_readiness.get("ready_company_count", 0),
            "blocked_company_count": delivery_readiness.get("blocked_company_count", 0),
            "runtime_blocked_count": runtime_readiness.get("blocked_count", 0),
            "acceptance_passed": acceptance_checklist.get("passed", 0),
            "acceptance_total": acceptance_checklist.get("total", 0),
        },
        "delivery_readiness": {
            "stage": delivery_readiness.get("stage"),
            "stage_label": _delivery_stage_label(delivery_readiness.get("stage")),
            "coverage_ratio": delivery_readiness.get("coverage_ratio", 0),
            "silver_ratio": delivery_readiness.get("silver_ratio", 0),
            "research_ratio": delivery_readiness.get("research_ratio", 0),
            "contract_ratio": delivery_readiness.get("contract_ratio", 0),
            "ready_company_count": delivery_readiness.get("ready_company_count", 0),
            "blocked_company_count": delivery_readiness.get("blocked_company_count", 0),
            "priority_actions": delivery_readiness.get("priority_actions", []),
        },
        "runtime_readiness": {
            "status": runtime_readiness.get("status"),
            "status_label": _status_label(runtime_readiness.get("status")),
            "blocked_count": runtime_readiness.get("blocked_count", 0),
            "blocked_checks": runtime_blockers,
        },
        "acceptance_checklist": {
            "status": acceptance_checklist.get("status"),
            "status_label": _status_label(acceptance_checklist.get("status")),
            "passed": acceptance_checklist.get("passed", 0),
            "total": acceptance_checklist.get("total", 0),
            "blocked_items": acceptance_blockers,
            "items": acceptance_checklist.get("items", []),
        },
        "workspace_runtime_audit": workspace_runtime_audit,
        "ocr_contract": {
            "status": contract_audit.get("status"),
            "status_label": _status_label(contract_audit.get("status")),
            "ready": contract_audit.get("ready", 0),
            "invalid": contract_audit.get("invalid", 0),
            "missing": contract_audit.get("missing", 0),
            "total": contract_audit.get("total", 0),
            "samples": contract_audit.get("samples", []),
        },
        "issue_buckets": issue_buckets,
        "recent_remediation_runs": remediation_runs,
    }
