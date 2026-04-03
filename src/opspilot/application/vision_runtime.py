from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opspilot.application.admin_delivery import (
    _document_stage_label,
    _resolve_document_contract_status,
    _status_label,
)
from opspilot.application.document_review import _artifact_source_label
from opspilot.application.document_review import (
    _build_document_delivery_preview,
    _document_delivery_guard_message,
    _is_formal_document_result,
    _load_company_document_upgrade_items,
    _load_document_artifact_payload,
)
from opspilot.application.document_pipeline import (
    DocumentPipelineBlockedError,
    _run_document_pipeline_job,
    _settings_ocr_runtime,
    _utcnow_iso,
    _write_json,
)
from opspilot.application.runtime_manifests import (
    _build_vision_run_id,
    _load_document_pipeline_job_manifest,
    _load_vision_run_manifest,
    _vision_run_detail_path,
    _write_document_pipeline_job_manifest,
    _write_vision_run_manifest,
)

def _build_vision_phase_track(
    *,
    company_name: str,
    report_period: str,
    selected_item: dict[str, Any],
    detail: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sections = detail.get("consumable_sections", []) if detail else []
    evidence_links = (detail or {}).get("evidence_navigation", {}).get("links", [])
    stage_label = _document_stage_label(selected_item.get("stage", "document"))
    stage_status = selected_item.get("status")
    return [
        {
            "phase": "载入报告",
            "status": "done",
            "headline": company_name,
            "metric": report_period,
        },
        {
            "phase": "解析工序",
            "status": "done" if stage_status in {"done", "completed"} else "active",
            "headline": stage_label,
            "metric": _status_label(stage_status),
        },
        {
            "phase": "结构抽取",
            "status": "done" if sections else "active",
            "headline": "标题/表格/片段",
            "metric": f"{len(sections)} 类结构",
        },
        {
            "phase": "证据挂接",
            "status": "done" if evidence_links else "active",
            "headline": "可回看原证据",
            "metric": f"{len(evidence_links)} 个入口",
        },
    ]


def _vision_selected_item_priority(item: dict[str, Any]) -> tuple[int, int, int, str]:
    stage = item.get("stage")
    completed = item.get("status") in {"done", "completed"}
    formal_result = _is_formal_document_result(
        stage=stage,
        artifact_source=item.get("artifact_source"),
        contract_status=item.get("contract_status"),
    )
    if completed and stage == "cell_trace":
        delivery_rank = 4 if formal_result else 2
    elif completed:
        delivery_rank = {"cross_page_merge": 1, "title_hierarchy": 3}.get(stage, 0)
    elif item.get("artifact_summary") or item.get("artifact_preview"):
        delivery_rank = 1
    else:
        delivery_rank = 0
    return (
        delivery_rank,
        1 if item.get("artifact_summary") or item.get("artifact_preview") else 0,
        1 if completed else 0,
        item.get("completed_at") or "",
    )


def _build_vision_extraction_stream(
    *,
    detail: dict[str, Any] | None,
    selected_item: dict[str, Any],
) -> list[dict[str, Any]]:
    stream: list[dict[str, Any]] = []
    sections = detail.get("consumable_sections", []) if detail else []
    for section in sections[:4]:
        stream.append(
            {
                "label": section.get("title", "section"),
                "value": str(section.get("count", 0)),
                "tone": "accent" if section.get("section_type") in {"heading_outline", "summary"} else "success",
            }
        )
    if not stream:
        stream.append(
            {
                "label": _document_stage_label(selected_item.get("stage", "document")),
                "value": _status_label(selected_item.get("status")),
                "tone": "warning",
            }
        )
    return stream[:6]


def _build_vision_analysis_log(
    *,
    company_name: str,
    report_period: str,
    selected_item: dict[str, Any],
    detail: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sections = detail.get("consumable_sections", []) if detail else []
    checkpoints = [
        ("初始化", f"{company_name} / {report_period}"),
        (
            "定位报告",
            selected_item.get("report_id")
            or _document_stage_label(selected_item.get("stage", "document")),
        ),
        ("抽取结构", "、".join(section.get("title", "section") for section in sections[:3]) or "等待结构化结果"),
        (
            "生成摘要",
            selected_item.get("artifact_summary")
            or selected_item.get("artifact_preview")
            or "等待摘要结果",
        ),
        (
            "挂接证据",
            f"{len((detail or {}).get('evidence_navigation', {}).get('links', []))} 个入口",
        ),
    ]
    return [
        {
            "step": index + 1,
            "title": title,
            "detail": detail_text,
        }
        for index, (title, detail_text) in enumerate(checkpoints)
    ]


def _build_vision_quality_summary(
    *,
    detail: dict[str, Any] | None,
    selected_item: dict[str, Any],
    ocr_runtime: dict[str, Any],
) -> dict[str, Any]:
    artifact = detail.get("artifact", {}) if detail else {}
    job = detail.get("job", {}) if detail else {}
    sections = detail.get("consumable_sections", []) if detail else []
    evidence_links = (detail or {}).get("evidence_navigation", {}).get("links", [])
    headings = artifact.get("headings") if isinstance(artifact.get("headings"), list) else []
    tables = artifact.get("tables") if isinstance(artifact.get("tables"), list) else []
    cells = artifact.get("cells") if isinstance(artifact.get("cells"), list) else []
    merges = (
        artifact.get("merge_candidates")
        if isinstance(artifact.get("merge_candidates"), list)
        else artifact.get("merged_sections")
        if isinstance(artifact.get("merged_sections"), list)
        else []
    )
    artifact_source = (
        job.get("artifact_source")
        or selected_item.get("artifact_source")
        or artifact.get("source")
    )
    contract_status = job.get("contract_status") or selected_item.get("contract_status")
    stage = job.get("stage") or selected_item.get("stage")
    stage_label = _document_stage_label(stage) if stage else "文档解析"
    source_status = (
        "ready"
        if artifact_source == "standard_ocr"
        else "blocked"
        if stage == "cell_trace"
        else "ready"
    )
    source_summary = (
        f"当前采用 {_artifact_source_label(artifact_source)}。"
        if artifact_source
        else "当前阶段尚未进入正式 OCR 来源质检。"
        if stage and stage != "cell_trace"
        else "尚未生成可核验的解析产物。"
    )
    dimensions = [
        {
            "key": "artifact_source",
            "label": "解析来源",
            "status": source_status,
            "summary": source_summary,
        },
        {
            "key": "structure",
            "label": "结构抽取",
            "status": "ready" if sections else "blocked",
            "summary": (
                f"已形成 {len(sections)} 类结构化结果。"
                if sections
                else "当前还没有标题、表格或摘要等结构化结果。"
            ),
        },
        {
            "key": "table_trace",
            "label": "表格溯源",
            "status": "ready" if tables and cells else "warning" if tables or cells else "blocked",
            "summary": (
                f"已恢复 {len(tables)} 个表格片段、{len(cells)} 个单元格。"
                if tables or cells
                else "当前没有形成可追溯的表格与单元格结果。"
            ),
        },
        {
            "key": "evidence",
            "label": "证据回看",
            "status": "ready" if evidence_links else "warning",
            "summary": (
                f"可直接回看 {len(evidence_links)} 个证据入口。"
                if evidence_links
                else "当前结果还没有可直接跳转的证据入口。"
            ),
        },
    ]
    if stage == "cell_trace" or contract_status is not None:
        dimensions.insert(
            1,
            {
                "key": "ocr_contract",
                "label": "OCR 结构契约",
                "status": (
                    "ready"
                    if contract_status == "ready"
                    else "blocked"
                    if contract_status in {"missing", "invalid"}
                    else "warning"
                ),
                "summary": (
                    "标准 OCR contract 已通过字段校验。"
                    if contract_status == "ready"
                    else "缺少标准 OCR 结构契约，当前无法确认正式单元格产物。"
                    if contract_status == "missing"
                    else "标准 OCR 结构契约存在但字段不合法。"
                    if contract_status == "invalid"
                    else "当前阶段尚未进入 OCR 结构契约质检。"
                ),
            },
        )

    blockers: list[dict[str, str]] = []

    def add_blocker(title: str, detail_text: str) -> None:
        if any(item["title"] == title for item in blockers):
            return
        blockers.append({"title": title, "detail": detail_text})

    if detail is None:
        add_blocker("尚无可回看产物", f"{stage_label} 当前只有工序记录，尚未生成可复核的结构化结果。")
    if not ocr_runtime.get("runtime_enabled"):
        add_blocker(
            "标准 OCR 引擎未启用",
            "当前环境未开启正式 OCR 运行时，无法形成稳定的标准 OCR 交付链。",
        )
    if contract_status == "missing":
        add_blocker(
            "缺少标准 OCR 结构契约",
            "单元格溯源尚未拿到合法 tables/cells 产物，需要先补齐标准 OCR 输出。",
        )
    elif contract_status == "invalid":
        add_blocker(
            "标准 OCR 结构契约不合格",
            "tables/cells 字段校验未通过，当前产物不能作为正式交付结果。",
        )
    if stage == "cell_trace" and artifact_source != "standard_ocr":
        add_blocker(
            "标准 OCR 结果未就绪",
            "当前单元格阶段还没有形成正式 OCR 标准产物，不能直接作为交付结果。",
        )
    if not evidence_links:
        add_blocker(
            "证据入口不足",
            "当前结果还不能一键回看原文证据，复核链条不完整。",
        )
    for item in detail.get("remediation", []) if detail else []:
        title = item.get("title")
        detail_text = item.get("detail")
        if title and detail_text:
            add_blocker(title, detail_text)

    status = "ready"
    if any(item["status"] == "blocked" for item in dimensions):
        status = "blocked"
    elif any(item["status"] == "warning" for item in dimensions):
        status = "warning"

    if status == "ready":
        headline = "已达到核验条件"
        summary = "标准 OCR、结构抽取与证据回看均已接通，可直接进入人工复核。"
    elif status == "warning":
        headline = "结果可读但仍需补强"
        summary = "当前解析结果可以浏览，但仍存在来源或证据链短板，尚不建议作为正式交付版本。"
    else:
        headline = "尚未达到交付标准"
        summary = "当前解析链仍有阻断项，需要先补齐标准 OCR 或结构/证据链路。"

    metrics = [
        {
            "label": "解析来源",
            "value": _artifact_source_label(artifact_source)
            if artifact_source
            else "当前阶段不要求",
            "tone": "success" if artifact_source == "standard_ocr" or stage != "cell_trace" else "warning",
        },
        {
            "label": "标题节点",
            "value": str(len(headings)),
            "tone": "success" if headings else "warning",
        },
        {
            "label": "表格片段",
            "value": str(len(tables)),
            "tone": "success" if tables else "warning",
        },
        {
            "label": "单元格",
            "value": str(len(cells)),
            "tone": "success" if cells else "warning",
        },
        {
            "label": "跨页候选",
            "value": str(len(merges)),
            "tone": "success" if merges else "accent",
        },
        {
            "label": "证据入口",
            "value": str(len(evidence_links)),
            "tone": "success" if evidence_links else "warning",
        },
    ]
    return {
        "status": status,
        "label": {"ready": "可进入核验", "warning": "需补强", "blocked": "待补齐"}[status],
        "headline": headline,
        "summary": summary,
        "stage_label": stage_label,
        "artifact_source": artifact_source,
        "artifact_source_label": _artifact_source_label(artifact_source),
        "contract_status": contract_status,
        "metrics": metrics,
        "dimensions": dimensions,
        "blockers": blockers[:5],
        "artifact_locations": detail.get("artifact_locations", []) if detail else [],
    }


def _company_vision_analyze(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    ocr_runtime = _settings_ocr_runtime(service.settings)
    upgrade_items = _load_company_document_upgrade_items(service.settings, company_name, period)
    selected_item = max(
        upgrade_items,
        key=_vision_selected_item_priority,
        default=None,
    )
    if selected_item is None:
        return {
            "company_name": company_name,
            "report_period": period,
            "user_role": user_role,
            "result": {
                "company_name": company_name,
                "headline": "暂无可用解析结果",
                "status_label": "等待解析",
                "quality_summary": _build_vision_quality_summary(
                    detail=None,
                    selected_item={},
                    ocr_runtime=ocr_runtime,
                ),
                "items": [],
                "sections": [],
                "evidence_navigation": {"links": []},
            },
        }

    detail = None
    selected_artifact = _load_document_artifact_payload(selected_item)
    if selected_artifact is not None:
        selected_artifact_source = selected_item.get("artifact_source") or selected_artifact.get("source")
        selected_contract_status = selected_item.get("contract_status")
        selected_summary = selected_item.get("artifact_summary") or selected_artifact.get("summary")
        if not _is_formal_document_result(
            stage=selected_item.get("stage"),
            artifact_source=selected_artifact_source,
            contract_status=selected_contract_status,
        ):
            selected_summary = _document_delivery_guard_message(
                stage=selected_item.get("stage"),
                artifact_source=selected_artifact_source,
                contract_status=selected_contract_status,
            )
        selected_item = {
            **selected_item,
            "artifact_summary": selected_summary,
            "artifact_source": selected_artifact_source,
            "artifact_preview": _build_document_delivery_preview(
                stage=selected_item.get("stage"),
                artifact_source=selected_artifact_source,
                contract_status=selected_contract_status,
                artifact=selected_artifact,
            ),
        }
    try:
        detail = service.document_pipeline_result_detail(
            selected_item["stage"],
            selected_item["report_id"],
        )
    except ValueError:
        detail = None

    section_items = []
    if detail is not None:
        for section in detail.get("consumable_sections", []):
            section_items.append(
                {
                    "section_type": section.get("section_type"),
                    "title": section.get("title"),
                    "count": section.get("count", 0),
                    "items": section.get("items", [])[:6],
                }
            )

    result_items = [
        {
            "kind": item["stage"],
            "stage_label": _document_stage_label(item["stage"]),
            "title": (
                _document_delivery_guard_message(
                    stage=item.get("stage"),
                    artifact_source=item.get("artifact_source"),
                    contract_status=item.get("contract_status"),
                )
                if not _is_formal_document_result(
                    stage=item.get("stage"),
                    artifact_source=item.get("artifact_source"),
                    contract_status=item.get("contract_status"),
                )
                else item.get("artifact_summary") or _document_stage_label(item["stage"])
            ),
            "summary": f"{item.get('report_period') or period} · {_status_label(item.get('status'))}",
        }
        for item in upgrade_items[:8]
    ]
    phase_track = _build_vision_phase_track(
        company_name=company_name,
        report_period=period,
        selected_item=selected_item,
        detail=detail,
    )
    extraction_stream = _build_vision_extraction_stream(
        detail=detail,
        selected_item=selected_item,
    )
    analysis_log = _build_vision_analysis_log(
        company_name=company_name,
        report_period=period,
        selected_item=selected_item,
        detail=detail,
    )
    quality_summary = _build_vision_quality_summary(
        detail=detail,
        selected_item=selected_item,
        ocr_runtime=ocr_runtime,
    )
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "result": {
            "company_name": company_name,
            "headline": selected_item.get("artifact_summary")
            or selected_item.get("report_id")
            or "解析结果",
            "status_label": "已生成"
            if detail is not None
            or selected_item.get("artifact_summary")
            or selected_item.get("artifact_preview")
            else "处理中",
            "phase_track": phase_track,
            "quality_summary": quality_summary,
            "extraction_stream": extraction_stream,
            "analysis_log": analysis_log,
            "source_preview": selected_item.get("artifact_preview"),
            "items": result_items,
            "sections": section_items,
            "evidence_navigation": (
                detail.get("evidence_navigation")
                if detail is not None
                else selected_item.get("evidence_navigation") or {"links": []}
            ),
        },
    }


def _company_vision_runtime(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    upgrade_items = _load_company_document_upgrade_items(service.settings, company_name, period)
    jobs_manifest = _load_document_pipeline_job_manifest(service.settings)
    ocr_runtime = _settings_ocr_runtime(service.settings)
    stages: list[dict[str, Any]] = []
    latest_jobs: list[dict[str, Any]] = []
    for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
        stage_jobs = [
            item
            for item in jobs_manifest["records"]
            if item.get("stage") == stage
            and item.get("company_name") == company_name
            and item.get("report_period") == period
        ]
        stage_jobs.sort(
            key=lambda item: item.get("completed_at") or item.get("created_at") or "",
            reverse=True,
        )
        job = stage_jobs[0] if stage_jobs else None
        if job and job.get("status") == "completed":
            artifact_payload = _load_document_artifact_payload(job)
            if artifact_payload is not None:
                artifact_source = job.get("artifact_source") or artifact_payload.get("source")
                contract_status = _resolve_document_contract_status(service.settings, job)
                job = {
                    **job,
                    "artifact_summary": (
                        _document_delivery_guard_message(
                            stage=stage,
                            artifact_source=artifact_source,
                            contract_status=contract_status,
                        )
                        if not _is_formal_document_result(
                            stage=stage,
                            artifact_source=artifact_source,
                            contract_status=contract_status,
                        )
                        else job.get("artifact_summary") or artifact_payload.get("summary")
                    ),
                    "artifact_source": artifact_source,
                }
        if job:
            latest_jobs.append(job)
        status = job.get("status", "missing") if job else "missing"
        contract_status = _resolve_document_contract_status(service.settings, job) if job else None
        stages.append(
            {
                "stage": stage,
                "label": _document_stage_label(stage),
                "status": status,
                "status_label": _status_label(status),
                "artifact_source": job.get("artifact_source") if job else None,
                "artifact_source_label": _artifact_source_label(
                    job.get("artifact_source") if job else None
                ),
                "contract_status": contract_status,
                "summary": (
                    job.get("artifact_summary")
                    or job.get("completed_at")
                    or "等待运行"
                )
                if job
                else "等待运行",
                "report_id": job.get("report_id") if job else None,
            }
        )

    latest_jobs.sort(key=_vision_selected_item_priority, reverse=True)
    vision = _company_vision_analyze(
        service,
        company_name,
        period,
        user_role=user_role,
    )
    stage_status_counts: dict[str, int] = {}
    for item in stages:
        stage_status_counts[item["status"]] = stage_status_counts.get(item["status"], 0) + 1
    cell_trace_stage = next((item for item in stages if item["stage"] == "cell_trace"), None)
    if (
        cell_trace_stage
        and cell_trace_stage.get("status") == "completed"
        and cell_trace_stage.get("contract_status") in {"missing", "invalid"}
    ):
        next_action = "补齐标准 OCR 结构契约后重新运行单元格溯源"
    elif ocr_runtime["runtime_enabled"] and ocr_runtime["mode"] == "service" and not ocr_runtime["service_url"]:
        next_action = "配置 PaddleOCR-VL 服务地址后再运行财报扫描"
    elif not ocr_runtime["runtime_enabled"]:
        next_action = "接通正式 OCR 运行时后再执行财报扫描"
    elif stage_status_counts.get("pending"):
        next_action = "继续运行文档升级作业"
    elif stage_status_counts.get("completed"):
        next_action = "进入结果核验与证据回放"
    else:
        next_action = "初始化解析链路"
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "runtime": {
            "provider": ocr_runtime["provider"],
            "model": ocr_runtime["model"],
            "mode": ocr_runtime["mode"],
            "service_url": ocr_runtime["service_url"],
            "runtime_enabled": ocr_runtime["runtime_enabled"],
            "layout_engine": ocr_runtime["layout_engine"],
            "next_action": next_action,
        },
        "stages": stages,
        "document_upgrades": {
            "count": len(upgrade_items),
            "stage_summary": {
                key: sum(1 for item in upgrade_items if item["stage"] == key)
                for key in {item["stage"] for item in upgrade_items}
            },
        },
        "latest_jobs": latest_jobs[:3],
        "vision": vision["result"],
    }


def _run_company_vision_pipeline(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    period = report_period or service._preferred_period()
    jobs_manifest = _load_document_pipeline_job_manifest(service.settings)
    requested_stages = ["cross_page_merge", "title_hierarchy", "cell_trace"]
    executed: list[dict[str, Any]] = []
    for stage in requested_stages:
        pending_jobs = [
            item
            for item in jobs_manifest["records"]
            if item.get("stage") == stage
            and item.get("company_name") == company_name
            and item.get("report_period") == period
            and item.get("status") == "pending"
        ]
        if not pending_jobs:
            continue
        for job in pending_jobs[:1]:
            try:
                artifact_payload, artifact_path = _run_document_pipeline_job(stage, job, service.settings)
            except DocumentPipelineBlockedError as exc:
                job["status"] = "blocked"
                job["artifact_path"] = ""
                job["completed_at"] = _utcnow_iso()
                job["artifact_summary"] = str(exc)
                job["artifact_source"] = None
                executed.append(
                    {
                        "stage": stage,
                        "report_id": job.get("report_id"),
                        "summary": str(exc),
                        "artifact_path": "",
                        "status": "blocked",
                        "source": None,
                    }
                )
                continue
            job["status"] = "completed"
            job["artifact_path"] = str(artifact_path)
            job["completed_at"] = _utcnow_iso()
            job["artifact_summary"] = artifact_payload.get("summary")
            job["artifact_source"] = artifact_payload.get("source")
            executed.append(
                {
                    "stage": stage,
                    "report_id": job.get("report_id"),
                    "summary": artifact_payload.get("summary"),
                    "artifact_path": str(artifact_path),
                    "status": "completed",
                    "source": artifact_payload.get("source"),
                }
            )
    if executed:
        _write_document_pipeline_job_manifest(service.settings, jobs_manifest)
    vision_payload = _run_company_vision_analyze(
        service,
        company_name,
        period,
        user_role=user_role,
    )
    runtime_payload = _company_vision_runtime(
        service,
        company_name,
        period,
        user_role=user_role,
    )
    return {
        "company_name": company_name,
        "report_period": period,
        "user_role": user_role,
        "executed": executed,
        "vision_run_id": vision_payload.get("run_id"),
        "runtime": runtime_payload,
    }


def _run_company_vision_analyze(
    service: Any,
    company_name: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    payload = _company_vision_analyze(
        service,
        company_name,
        report_period,
        user_role=user_role,
    )
    run_id = _build_vision_run_id(company_name)
    detail_path = _vision_run_detail_path(service.settings, run_id)
    _write_json(detail_path, payload)
    manifest = _load_vision_run_manifest(service.settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    records.insert(
        0,
        {
            "run_id": run_id,
            "company_name": company_name,
            "report_period": payload.get("report_period"),
            "user_role": user_role,
            "headline": payload.get("result", {}).get("headline"),
            "status_label": payload.get("result", {}).get("status_label"),
            "created_at": _utcnow_iso(),
            "detail_path": str(detail_path),
        },
    )
    manifest["records"] = records[:200]
    _write_vision_run_manifest(service.settings, manifest)
    payload["run_id"] = run_id
    return payload


def _vision_runs(
    service: Any,
    *,
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
) -> dict[str, Any]:
    records = [
        item
        for item in _load_vision_run_manifest(service.settings)["records"]
        if item.get("user_role") == user_role
        and (report_period is None or item.get("report_period") == report_period)
        and (company_name is None or item.get("company_name") == company_name)
    ]
    return {
        "company_name": company_name,
        "report_period": report_period,
        "user_role": user_role,
        "total": len(records),
        "runs": records[:limit],
    }


def _vision_run_detail(service: Any, run_id: str) -> dict[str, Any]:
    record = next(
        (
            item
            for item in _load_vision_run_manifest(service.settings)["records"]
            if item.get("run_id") == run_id
        ),
        None,
    )
    if record is None:
        raise ValueError(f"未找到多模态运行：{run_id}")
    detail_path = Path(record["detail_path"])
    if not detail_path.exists():
        raise ValueError(f"未找到多模态详情：{run_id}")
    try:
        with detail_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"多模态运行记录损坏：{run_id}") from exc
    payload["run_meta"] = {
        "run_id": run_id,
        "created_at": record.get("created_at"),
        "company_name": record.get("company_name"),
        "report_period": record.get("report_period"),
        "user_role": record.get("user_role"),
        "headline": record.get("headline"),
        "status_label": record.get("status_label"),
    }
    return payload
