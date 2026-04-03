from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.config import Settings
from opspilot.application.admin_delivery import _resolve_document_contract_status
from opspilot.application.runtime_manifests import _load_document_pipeline_job_manifest


def _artifact_source_label(source: str | None) -> str:
    return {
        "standard_ocr": "正式结构产物",
        "geometric_fallback": "非正式历史产物",
    }.get(source or "", source or "来源未识别")


def _is_formal_document_result(
    *, stage: str | None, artifact_source: str | None, contract_status: str | None
) -> bool:
    if stage != "cell_trace":
        return True
    return artifact_source == "standard_ocr" and contract_status == "ready"


def _document_delivery_guard_message(
    *, stage: str | None, artifact_source: str | None, contract_status: str | None
) -> str:
    if stage != "cell_trace":
        return "当前阶段尚未形成最终文档交付结果。"
    if artifact_source == "standard_ocr" and contract_status == "ready":
        return ""
    if artifact_source == "standard_ocr" and contract_status == "invalid":
        return "标准 OCR 结构契约字段不合法，当前单元格结果不能作为正式复核输入。"
    if artifact_source == "standard_ocr" and contract_status == "missing":
        return "标准 OCR 结构契约缺失，当前单元格结果不能作为正式复核输入。"
    if artifact_source:
        return (
            f"当前 cell_trace 来自{_artifact_source_label(artifact_source)}，"
            "不能直接作为正式复核输入。请补齐标准 OCR 结构契约后重跑。"
        )
    return "当前尚未形成正式 OCR 单元格产物，不能作为正式复核输入。"


def _build_document_delivery_guard_sections(
    *, stage: str | None, artifact_source: str | None, contract_status: str | None
) -> list[dict[str, Any]]:
    message = _document_delivery_guard_message(
        stage=stage,
        artifact_source=artifact_source,
        contract_status=contract_status,
    )
    if not message:
        return []
    return [
        {
            "section_type": "delivery_guard",
            "title": "正式链路未就绪",
            "count": 1,
            "items": [
                {
                    "text": message,
                    "source": artifact_source or "missing",
                }
            ],
        }
    ]


def _filter_document_results_for_company(
    results: list[dict[str, Any]],
    company_name: str,
    report_period: str | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in results:
        if item["company_name"] != company_name:
            continue
        if report_period and item.get("report_period") not in (None, report_period):
            continue
        filtered.append(item)
    filtered.sort(
        key=lambda item: (
            item.get("completed_at") or "",
            item.get("stage") or "",
            item.get("report_id") or "",
        ),
        reverse=True,
    )
    return filtered


def _build_document_artifact_preview(artifact: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    if source := artifact.get("source"):
        preview["source"] = source
    if summary := artifact.get("summary"):
        preview["summary"] = summary
    if headings := artifact.get("headings"):
        preview["headings"] = [
            {
                "text": item.get("text"),
                "level": item.get("level"),
                "page": item.get("page"),
            }
            for item in headings[:5]
        ]
    if merges := artifact.get("merged_sections"):
        preview["merged_sections"] = [
            {
                "title": item.get("title"),
                "page_range": item.get("page_range"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
            }
            for item in merges[:5]
        ]
    if cells := artifact.get("cells"):
        preview["cells"] = cells[:5]
    if tables := artifact.get("tables"):
        preview["tables"] = [
            {
                "title": item.get("title"),
                "page": item.get("page"),
                "continued": item.get("continued"),
            }
            for item in tables[:5]
        ]
    return preview


def _build_document_delivery_preview(
    *,
    stage: str | None,
    artifact_source: str | None,
    contract_status: str | None,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    if _is_formal_document_result(
        stage=stage,
        artifact_source=artifact_source,
        contract_status=contract_status,
    ):
        return _build_document_artifact_preview(artifact)
    preview = {"summary": _document_delivery_guard_message(
        stage=stage,
        artifact_source=artifact_source,
        contract_status=contract_status,
    )}
    if artifact_source:
        preview["source"] = artifact_source
    return preview


def _load_document_artifact_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    artifact_path = record.get("artifact_path")
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_company_document_upgrade_items(
    settings: Settings, company_name: str, report_period: str
) -> list[dict[str, Any]]:
    jobs_manifest = _load_document_pipeline_job_manifest(settings)
    return _filter_document_results_for_company(
        [
            {
                "stage": item["stage"],
                "report_id": item["report_id"],
                "company_name": item["company_name"],
                "security_code": item["security_code"],
                "report_period": item.get("report_period"),
                "status": item["status"],
                "artifact_path": item.get("artifact_path"),
                "artifact_summary": item.get("artifact_summary"),
                "artifact_source": item.get("artifact_source"),
                "contract_status": _resolve_document_contract_status(settings, item),
                "completed_at": item.get("completed_at"),
            }
            for item in jobs_manifest["records"]
        ],
        company_name,
        report_period,
    )


def _build_document_consumable_sections(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    if source := artifact.get("source"):
        sections.append(
            {
                "section_type": "artifact_provenance",
                "title": "解析来源",
                "count": 1,
                "items": [
                    {
                        "text": _artifact_source_label(source),
                        "source": source,
                        "path": artifact.get("ocr_artifact_path"),
                    }
                ],
            }
        )
    if headings := artifact.get("headings"):
        sections.append(
            {
                "section_type": "heading_outline",
                "title": "标题层级",
                "count": len(headings),
                "items": [
                    {
                        "text": item.get("text"),
                        "level": item.get("level"),
                        "page": item.get("page"),
                    }
                    for item in headings[:20]
                ],
            }
        )
    if merges := artifact.get("merge_candidates") or artifact.get("merged_sections"):
        sections.append(
            {
                "section_type": "cross_page_merge",
                "title": "跨页候选",
                "count": len(merges),
                "items": [
                    {
                        "title": item.get("title"),
                        "from_page": item.get("from_page") or item.get("page_start"),
                        "to_page": item.get("to_page") or item.get("page_end"),
                        "reason": item.get("reason"),
                    }
                    for item in merges[:20]
                ],
            }
        )
    if tables := artifact.get("tables"):
        sections.append(
            {
                "section_type": "tables",
                "title": "表格线索",
                "count": len(tables),
                "items": [
                    {
                        "title": item.get("title"),
                        "page": item.get("page"),
                        "continued": item.get("continued"),
                    }
                    for item in tables[:20]
                ],
            }
        )
    if cells := artifact.get("cells"):
        sections.append(
            {
                "section_type": "cells",
                "title": "单元格溯源",
                "count": len(cells),
                "items": cells[:20],
            }
        )
    if not sections and artifact.get("summary"):
        sections.append(
            {
                "section_type": "summary",
                "title": "解析摘要",
                "count": 1,
                "items": [{"text": artifact["summary"]}],
            }
        )
    return sections


def _build_document_artifact_locations(
    job: dict[str, Any], artifact: dict[str, Any]
) -> list[dict[str, Any]]:
    locations = [
        {
            "label": "当前解析产物",
            "kind": "artifact",
            "path": job.get("artifact_path"),
        }
    ]
    if artifact.get("ocr_artifact_path"):
        locations.append(
            {
                "label": "正式 OCR 上游产物",
                "kind": "ocr_artifact",
                "path": artifact.get("ocr_artifact_path"),
            }
        )
    return [item for item in locations if item.get("path")]


def _build_document_artifact_remediation(
    *, stage: str, artifact_source: str | None, artifact: dict[str, Any]
) -> list[dict[str, Any]]:
    if stage != "cell_trace":
        return [
            {
                "title": "继续核验当前阶段产物",
                "detail": "确认摘要、证据导航和页码定位与原报告一致，再推进后续工序。",
            }
        ]
    if artifact_source == "standard_ocr":
        return [
            {
                "title": "核对正式结构产物",
                "detail": "优先核对 ocr_cell_trace 中 tables/cells 的页码、行列号和上游 OCR 产物路径，确保当前结构结果可复算。",
            }
        ]
    return [
        {
            "title": "补齐正式结构产物",
            "detail": "当前尚未形成合法的 tables/cells 结构结果。应先接通正式 OCR 运行时并写入 ocr_cell_trace，再重新运行 cell_trace。",
        }
    ]


def _build_document_evidence_navigation(
    *,
    repository: Any,
    company_name: str,
    report_period: str | None,
    artifact: dict[str, Any],
) -> dict[str, Any] | None:
    get_company = getattr(repository, "get_company", None)
    if get_company is None:
        return _build_document_navigation_unavailable(
            artifact,
            message="当前仓库未提供证据解析能力，暂时不能生成文档证据跳转。",
        )
    company = get_company(company_name, report_period) if report_period else get_company(company_name)
    if company is None:
        return _build_document_navigation_unavailable(
            artifact,
            message="未找到对应公司证据索引，当前无法生成文档证据跳转。",
        )

    candidate_pages = _collect_document_artifact_pages(artifact)
    candidate_chunk_ids = _collect_company_evidence_refs(company)
    selected_items: list[dict[str, Any]] = []
    page_set = set(candidate_pages)
    get_evidence = getattr(repository, "get_evidence", None)
    if get_evidence is not None:
        fallback_item = None
        for chunk_id in candidate_chunk_ids:
            item = get_evidence(chunk_id)
            if item is None:
                continue
            if fallback_item is None:
                fallback_item = item
            if page_set:
                if item.get("page") in page_set:
                    selected_items.append(item)
                    if len(selected_items) >= 5:
                        break
            else:
                selected_items = [item]
                break
        if not selected_items and fallback_item is not None:
            selected_items = [fallback_item]
    else:
        evidence_items = repository.resolve_evidence(candidate_chunk_ids)
        if candidate_pages:
            paged_items = [item for item in evidence_items if item.get("page") in candidate_pages]
        else:
            paged_items = []
        selected_items = paged_items or evidence_items[:1]
    if not selected_items:
        return _build_document_navigation_unavailable(
            artifact,
            message="当前文档结果尚未挂接到正式证据索引，暂时不能直接回看原文。",
        )

    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    links = [
        {
            "chunk_id": item["chunk_id"],
            "label": f"第{item.get('page', '?')}页证据" if item.get("page") else "证据",
            "path": f"/evidence/{item['chunk_id']}",
            "query": {
                "context": "文档升级结果",
                "anchors": "|".join(anchor_terms[:6]),
            },
            "source_title": item.get("source_title"),
            "page": item.get("page"),
        }
        for item in selected_items[:5]
    ]
    return {
        "count": len(links),
        "anchor_terms": anchor_terms[:6],
        "pages": sorted({item.get("page") for item in selected_items if item.get("page") is not None}),
        "links": links,
        "primary_route": links[0] if links else None,
    }


def _build_document_navigation_unavailable(
    artifact: dict[str, Any], *, message: str
) -> dict[str, Any]:
    anchor_terms = _collect_document_artifact_anchor_terms(artifact)
    pages = _collect_document_artifact_pages(artifact)
    return {
        "count": 0,
        "status": "blocked",
        "message": message,
        "anchor_terms": anchor_terms[:6],
        "pages": pages,
        "links": [],
        "primary_route": None,
    }


def _collect_document_artifact_pages(artifact: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for heading in artifact.get("headings", []):
        page = heading.get("page")
        if isinstance(page, int):
            pages.append(page)
    for section in artifact.get("merged_sections", []):
        for field in ("page", "page_start", "page_end", "from_page", "to_page"):
            page = section.get(field)
            if isinstance(page, int):
                pages.append(page)
        page_range = section.get("page_range") or []
        for page in page_range:
            if isinstance(page, int):
                pages.append(page)
    for table in artifact.get("tables", []):
        page = table.get("page")
        if isinstance(page, int):
            pages.append(page)
    for cell in artifact.get("cells", []):
        page = cell.get("page")
        if isinstance(page, int):
            pages.append(page)
    return sorted(set(pages))


def _collect_document_artifact_anchor_terms(artifact: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for heading in artifact.get("headings", []):
        text = (heading.get("text") or "").strip()
        if text:
            terms.append(text[:24])
    for section in artifact.get("merged_sections", []):
        title = (section.get("title") or "").strip()
        if title:
            terms.append(title[:24])
    if summary := artifact.get("summary"):
        terms.append(str(summary)[:24])
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _collect_company_evidence_refs(company: dict[str, Any]) -> list[str]:
    chunk_ids: list[str] = []
    if company.get("summary_chunk_id"):
        chunk_ids.append(company["summary_chunk_id"])
    for refs in company.get("metric_evidence", {}).values():
        chunk_ids.extend(refs)
    for refs in company.get("label_evidence", {}).values():
        chunk_ids.extend(refs)
    deduped: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id not in deduped:
            deduped.append(chunk_id)
    return deduped
