from __future__ import annotations

from typing import Any

from opspilot.application.admin_delivery import _document_stage_label, _status_label
from opspilot.application.document_review import _artifact_source_label

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
    return (
        1 if item.get("artifact_summary") or item.get("artifact_preview") else 0,
        {"cross_page_merge": 1, "title_hierarchy": 2, "cell_trace": 3}.get(item.get("stage"), 0),
        1 if item.get("status") in {"done", "completed"} else 0,
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
    dimensions = [
        {
            "key": "artifact_source",
            "label": "解析来源",
            "status": "ready" if artifact_source == "standard_ocr" else "warning" if artifact_source else "blocked",
            "summary": (
                f"当前采用 {_artifact_source_label(artifact_source)}。"
                if artifact_source
                else "尚未生成可核验的解析产物。"
            ),
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
            "value": _artifact_source_label(artifact_source),
            "tone": "success" if artifact_source == "standard_ocr" else "warning",
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
