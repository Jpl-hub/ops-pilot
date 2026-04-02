from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.config import Settings
from opspilot.application.admin_delivery import (
    _append_document_pipeline_run_record,
    _build_document_pipeline_execution_feedback,
    _document_stage_label,
    _resolve_document_contract_status,
    _status_label,
    _summarize_contract_statuses,
)
from opspilot.application.document_pipeline import (
    DocumentPipelineBlockedError,
    _run_document_pipeline_job,
    _utcnow_iso,
)
from opspilot.application.document_review import (
    _build_document_artifact_locations,
    _build_document_artifact_remediation,
    _build_document_consumable_sections,
    _build_document_evidence_navigation,
    _build_document_navigation_unavailable,
)
from opspilot.application.runtime_manifests import (
    _document_pipeline_run_detail_path,
    _load_document_pipeline_job_manifest,
    _load_document_pipeline_run_manifest,
    _write_document_pipeline_job_manifest,
)


def _document_pipeline_jobs(settings: Settings) -> dict[str, Any]:
    jobs_manifest = _load_document_pipeline_job_manifest(settings)
    records = jobs_manifest["records"]
    stage_summary = []
    for stage in ("cross_page_merge", "title_hierarchy", "cell_trace"):
        stage_records = [item for item in records if item["stage"] == stage]
        stage_summary.append(
            {
                "stage": stage,
                "total": len(stage_records),
                "completed": sum(1 for item in stage_records if item["status"] == "completed"),
                "pending": sum(1 for item in stage_records if item["status"] == "pending"),
                "blocked": sum(1 for item in stage_records if item["status"] == "blocked"),
            }
        )
    return {
        "generated_at": jobs_manifest["generated_at"],
        "stage_summary": stage_summary,
        "jobs": records[:30],
    }


def _document_pipeline_runs(settings: Settings, limit: int = 30) -> dict[str, Any]:
    manifest = _load_document_pipeline_run_manifest(settings)
    records = list(manifest["records"])
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "generated_at": manifest["generated_at"],
        "total": len(records),
        "runs": records[:limit],
    }


def _document_pipeline_run_detail(settings: Settings, run_id: str) -> dict[str, Any]:
    manifest = _load_document_pipeline_run_manifest(settings)
    record = next((item for item in manifest["records"] if item.get("run_id") == run_id), None)
    if record is None:
        raise ValueError(f"未找到文档升级运行：{run_id}")
    detail_path = _document_pipeline_run_detail_path(settings, run_id)
    if not detail_path.exists():
        raise ValueError(f"未找到文档升级运行详情：{run_id}")
    try:
        with detail_path.open("r", encoding="utf-8") as file:
            detail = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"文档升级运行记录损坏：{run_id}") from exc
    return detail


def _document_pipeline_results(
    service: Any,
    *,
    stage: str | None = None,
    status: str | None = None,
    artifact_source: str | None = None,
    contract_status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    jobs_manifest = _load_document_pipeline_job_manifest(service.settings)
    records = jobs_manifest["records"]
    filtered = []
    for item in records:
        if stage and item["stage"] != stage:
            continue
        if status and item["status"] != status:
            continue
        item_contract_status = _resolve_document_contract_status(service.settings, item)
        item_artifact_source = item.get("artifact_source")
        if artifact_source and item_artifact_source != artifact_source:
            continue
        if contract_status and item_contract_status != contract_status:
            continue
        filtered.append(
            {
                "stage": item["stage"],
                "report_id": item["report_id"],
                "company_name": item["company_name"],
                "security_code": item["security_code"],
                "report_period": item.get("report_period"),
                "status": item["status"],
                "artifact_path": item.get("artifact_path"),
                "artifact_summary": item.get("artifact_summary"),
                "artifact_source": item_artifact_source,
                "contract_status": item_contract_status,
                "completed_at": item.get("completed_at"),
                "detail_route": {
                    "path": f"/api/v1/admin/document-pipeline/results/{item['stage']}/{item['report_id']}",
                },
            }
        )
    filtered.sort(
        key=lambda item: (
            item.get("completed_at") or "",
            item.get("report_period") or "",
            item.get("stage") or "",
            item.get("report_id") or "",
        ),
        reverse=True,
    )
    return {
        "stage": stage,
        "status": status,
        "artifact_source": artifact_source,
        "contract_status": contract_status,
        "total": len(filtered),
        "results": filtered[:limit],
    }


def _document_pipeline_result_detail(service: Any, stage: str, report_id: str) -> dict[str, Any]:
    jobs_manifest = _load_document_pipeline_job_manifest(service.settings)
    job = next(
        (
            item
            for item in jobs_manifest["records"]
            if item["stage"] == stage and item["report_id"] == report_id
        ),
        None,
    )
    if job is None:
        raise ValueError(f"未找到解析结果：{stage}/{report_id}")
    artifact_path_value = str(job.get("artifact_path") or "").strip()
    artifact_path = Path(artifact_path_value) if artifact_path_value else None
    if artifact_path is not None and artifact_path.exists():
        try:
            with artifact_path.open("r", encoding="utf-8") as file:
                artifact = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"解析产物损坏：{artifact_path}") from exc
        evidence_navigation = _build_document_evidence_navigation(
            repository=service.repository,
            company_name=job["company_name"],
            report_period=job.get("report_period"),
            artifact=artifact,
        )
        artifact_source = job.get("artifact_source") or artifact.get("source")
    elif job.get("status") == "blocked":
        artifact = {
            "report_id": job["report_id"],
            "company_name": job["company_name"],
            "summary": job.get("artifact_summary") or "当前工序已阻断，未生成可交付解析产物。",
            "tables": [],
            "cells": [],
            "headings": [],
            "merge_candidates": [],
        }
        evidence_navigation = _build_document_navigation_unavailable(
            artifact,
            message="当前工序已阻断，未形成可跳转的正式证据入口。",
        )
        artifact_source = job.get("artifact_source")
    else:
        raise ValueError(f"未找到解析产物：{artifact_path_value or '<missing>'}")
    return {
        "job": {
            "stage": job["stage"],
            "stage_label": _document_stage_label(job["stage"]),
            "report_id": job["report_id"],
            "company_name": job["company_name"],
            "security_code": job["security_code"],
            "report_period": job.get("report_period"),
            "status": job["status"],
            "status_label": _status_label(job["status"]),
            "contract_status": _resolve_document_contract_status(service.settings, job),
            "artifact_path": job["artifact_path"],
            "completed_at": job.get("completed_at"),
            "artifact_summary": job.get("artifact_summary"),
            "artifact_source": artifact_source,
        },
        "artifact": artifact,
        "artifact_locations": _build_document_artifact_locations(job, artifact)
        if artifact_path is not None and artifact_path.exists()
        else [],
        "remediation": _build_document_artifact_remediation(
            stage=job["stage"],
            artifact_source=artifact_source,
            artifact=artifact,
        ),
        "evidence_navigation": evidence_navigation,
        "consumable_sections": _build_document_consumable_sections(artifact),
    }


def _run_document_pipeline_stage(
    service: Any,
    stage: str,
    limit: int = 5,
    *,
    artifact_source: str | None = None,
    contract_status: str | None = None,
) -> dict[str, Any]:
    jobs_manifest = _load_document_pipeline_job_manifest(service.settings)
    records = jobs_manifest["records"]
    if contract_status and stage != "cell_trace":
        raise ValueError("contract_status 仅支持 cell_trace 阶段。")
    if contract_status == "ready":
        raise ValueError("不允许批量重跑 contract 已达标的样本。")
    before_summary = _summarize_contract_statuses(records, settings=service.settings, stage=stage)
    candidate_jobs: list[dict[str, Any]] = []
    for item in records:
        if item["stage"] != stage:
            continue
        item_contract_status = _resolve_document_contract_status(service.settings, item)
        item_artifact_source = item.get("artifact_source")
        if artifact_source and item_artifact_source != artifact_source:
            continue
        if contract_status and item_contract_status != contract_status:
            continue
        if contract_status:
            candidate_jobs.append(item)
            continue
        if item["status"] == "pending":
            candidate_jobs.append(item)
    pending_jobs = candidate_jobs[:limit]
    results: list[dict[str, Any]] = []
    for job in pending_jobs:
        try:
            artifact_payload, artifact_path = _run_document_pipeline_job(stage, job, service.settings)
        except DocumentPipelineBlockedError as exc:
            job["status"] = "blocked"
            job["artifact_path"] = ""
            job["completed_at"] = _utcnow_iso()
            job["artifact_summary"] = str(exc)
            job["artifact_source"] = None
            results.append(
                {
                    "report_id": job["report_id"],
                    "company_name": job["company_name"],
                    "artifact_path": "",
                    "summary": str(exc),
                    "source": None,
                    "status": "blocked",
                }
            )
            continue
        job["status"] = "completed"
        job["artifact_path"] = str(artifact_path)
        job["completed_at"] = _utcnow_iso()
        job["artifact_summary"] = artifact_payload.get("summary")
        job["artifact_source"] = artifact_payload.get("source")
        results.append(
            {
                "report_id": job["report_id"],
                "company_name": job["company_name"],
                "artifact_path": str(artifact_path),
                "summary": artifact_payload.get("summary"),
                "source": artifact_payload.get("source"),
                "status": "completed",
            }
        )
    _write_document_pipeline_job_manifest(service.settings, jobs_manifest)
    after_summary = _summarize_contract_statuses(
        jobs_manifest["records"],
        settings=service.settings,
        stage=stage,
    )
    execution_feedback = _build_document_pipeline_execution_feedback(
        stage=stage,
        contract_status=contract_status,
        processed=len(results),
        before_summary=before_summary,
        after_summary=after_summary,
    )
    run_record = _append_document_pipeline_run_record(
        service.settings,
        stage=stage,
        artifact_source=artifact_source,
        contract_status=contract_status,
        results=results,
        execution_feedback=execution_feedback,
    )
    return {
        "stage": stage,
        "requested": limit,
        "artifact_source": artifact_source,
        "contract_status": contract_status,
        "processed": len(results),
        "results": results,
        "execution_feedback": execution_feedback,
        "run_id": run_record["run_id"],
        "jobs": service.document_pipeline_jobs(),
    }
