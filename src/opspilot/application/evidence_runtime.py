from __future__ import annotations

from typing import Any


SOURCE_TYPE_LABELS: dict[str, str] = {
    "official_summary_page": "定期报告页级摘要",
    "official_statement_page": "定期报告财务页",
    "official_event_page": "定期报告事项页",
    "official_snapshot_page": "文档快照页",
    "hybrid_rag_chunk": "检索证据片段",
    "research_report_excerpt": "研报证据",
    "research_forecast_excerpt": "盈利预测摘录",
    "bootstrap_note": "补充说明",
}


def build_evidence_detail(
    service: Any,
    chunk_id: str,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    repository = service.repository
    evidence = repository.get_evidence(chunk_id)
    if evidence is None:
        raise ValueError(f"未找到证据：{chunk_id}")

    detail = dict(evidence)
    company_name = str(detail.get("company_name") or "")
    report_period = _string_or_none(detail.get("report_period"))
    company = _resolve_company(repository, company_name, report_period)

    score_payload = _safe_call(service.score_company, company_name, report_period) if company_name else None
    verify_payload = _load_verify_payload(service, detail) if company_name else None
    document_payload = (
        _safe_call(
            service.company_document_upgrades,
            company_name,
            report_period,
            limit=40,
            include_preview=False,
            include_evidence_navigation=True,
        )
        if company_name and hasattr(service, "company_document_upgrades")
        else None
    )

    reference_panels: list[dict[str, Any]] = []
    if score_panel := _build_score_reference_panel(
        detail=detail,
        score_payload=score_payload,
    ):
        reference_panels.append(score_panel)
    if verify_panel := _build_verify_reference_panel(
        detail=detail,
        verify_payload=verify_payload,
    ):
        reference_panels.append(verify_panel)
    if document_panel := _build_document_reference_panel(
        detail=detail,
        document_payload=document_payload,
        user_role=user_role,
    ):
        reference_panels.append(document_panel)

    detail["source_meta"] = _build_source_meta(detail)
    detail["company_context"] = _build_company_context(
        repository=repository,
        company=company,
        company_name=company_name,
        report_period=report_period,
        score_payload=score_payload,
    )
    detail["report_context"] = _build_report_context(verify_payload) if verify_payload else None
    detail["reference_panels"] = reference_panels
    detail["workflow_links"] = _build_workflow_links(
        detail=detail,
        user_role=user_role,
        reference_panels=reference_panels,
    )
    return detail


def _build_source_meta(evidence: dict[str, Any]) -> dict[str, Any]:
    page = evidence.get("page")
    return {
        "type": evidence.get("source_type"),
        "type_label": SOURCE_TYPE_LABELS.get(str(evidence.get("source_type") or ""), "未标注"),
        "page": page,
        "page_label": f"第 {page} 页" if isinstance(page, (int, str)) and str(page) else "页码未标注",
        "source_title": evidence.get("source_title"),
        "report_period": evidence.get("report_period"),
        "source_url": evidence.get("source_url"),
        "local_path": evidence.get("local_path"),
        "fingerprint": evidence.get("fingerprint"),
    }


def _build_company_context(
    *,
    repository: Any,
    company: dict[str, Any] | None,
    company_name: str,
    report_period: str | None,
    score_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    available_periods: list[str] = []
    if company_name and hasattr(repository, "list_company_periods"):
        try:
            available_periods = list(repository.list_company_periods(company_name))
        except Exception:
            available_periods = []

    context = {
        "company_name": company_name,
        "report_period": (company or {}).get("report_period") or report_period,
        "subindustry": (company or {}).get("subindustry"),
        "ticker": (company or {}).get("ticker"),
        "available_periods": available_periods[:6],
        "score_snapshot": None,
    }

    if score_payload is not None:
        scorecard = score_payload.get("scorecard") or {}
        context["score_snapshot"] = {
            "total_score": scorecard.get("total_score"),
            "grade": scorecard.get("grade"),
            "risk_count": len(scorecard.get("risk_labels") or []),
            "opportunity_count": len(scorecard.get("opportunity_labels") or []),
        }

    return context


def _build_report_context(verify_payload: dict[str, Any]) -> dict[str, Any] | None:
    report_meta = verify_payload.get("report_meta") or {}
    if not report_meta:
        return None
    catalog_row = next(
        (
            item
            for item in verify_payload.get("available_reports", [])
            if item.get("title") == report_meta.get("title")
        ),
        {},
    )
    return {
        "title": report_meta.get("title"),
        "publish_date": report_meta.get("publish_date"),
        "source_name": report_meta.get("source_name"),
        "source_url": report_meta.get("source_url"),
        "attachment_url": report_meta.get("attachment_url"),
        "rating_text": catalog_row.get("rating_text"),
        "rating_change": catalog_row.get("rating_change"),
        "target_price": catalog_row.get("target_price"),
        "forecast_count": catalog_row.get("forecast_count"),
    }


def _build_score_reference_panel(
    *,
    detail: dict[str, Any],
    score_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if score_payload is None:
        return None
    matches = _matching_evidence_groups(score_payload.get("evidence_groups", []), detail["chunk_id"])
    if not matches:
        return None
    return {
        "kind": "score",
        "title": "经营诊断引用",
        "subtitle": f"这条证据当前支撑 {len(matches)} 组经营判断。",
        "route": {
            "label": "返回经营诊断",
            "path": "/score",
            "query": _build_query(
                company=detail.get("company_name"),
                period=score_payload.get("report_period") or detail.get("report_period"),
            ),
        },
        "entries": [_build_group_entry(group, detail["chunk_id"]) for group in matches[:4]],
    }


def _build_verify_reference_panel(
    *,
    detail: dict[str, Any],
    verify_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if verify_payload is None:
        return None
    matches = _matching_evidence_groups(verify_payload.get("evidence_groups", []), detail["chunk_id"])
    if not matches:
        return None
    report_title = verify_payload.get("report_meta", {}).get("title") or detail.get("source_title")
    return {
        "kind": "verify",
        "title": "研报核验引用",
        "subtitle": f"这条证据在研报核验里命中 {len(matches)} 条观点链路。",
        "route": {
            "label": "返回观点核验",
            "path": "/verify",
            "query": _build_query(
                company=detail.get("company_name"),
                period=detail.get("report_period"),
                report_title=report_title,
            ),
        },
        "entries": [_build_group_entry(group, detail["chunk_id"]) for group in matches[:4]],
    }


def _build_document_reference_panel(
    *,
    detail: dict[str, Any],
    document_payload: dict[str, Any] | None,
    user_role: str,
) -> dict[str, Any] | None:
    if document_payload is None:
        return None
    matches = [
        item
        for item in document_payload.get("items", [])
        if any(
            link.get("chunk_id") == detail["chunk_id"]
            for link in (item.get("evidence_navigation", {}).get("links") or [])
        )
    ]
    if not matches:
        return None
    return {
        "kind": "document",
        "title": "文档复核链路",
        "subtitle": f"这条证据已挂到 {len(matches)} 个文档工序结果。",
        "route": {
            "label": "返回文档复核",
            "path": "/vision",
            "query": _build_query(
                company=detail.get("company_name"),
                period=detail.get("report_period"),
                role=user_role,
            ),
        },
        "entries": [_build_document_entry(item, detail["chunk_id"]) for item in matches[:4]],
    }


def _build_group_entry(group: dict[str, Any], current_chunk_id: str) -> dict[str, Any]:
    anchors = group.get("anchor_terms") or []
    links = [
        _build_related_evidence_link(
            item,
            context=group.get("title"),
            anchors=anchors,
        )
        for item in group.get("items", [])
        if item.get("chunk_id") != current_chunk_id
    ]
    return {
        "title": group.get("title"),
        "detail": group.get("subtitle"),
        "links": links[:4],
    }


def _build_document_entry(item: dict[str, Any], current_chunk_id: str) -> dict[str, Any]:
    navigation = item.get("evidence_navigation") or {}
    links = []
    for link in navigation.get("links", []):
        if link.get("chunk_id") == current_chunk_id:
            continue
        links.append(
            {
                "label": link.get("label") or link.get("source_title") or "证据",
                "path": link.get("path"),
                "query": dict(link.get("query") or {}),
            }
        )
    detail_parts = [item.get("status_label") or item.get("status"), item.get("artifact_summary")]
    detail = " · ".join(part for part in detail_parts if isinstance(part, str) and part.strip())
    return {
        "title": item.get("stage") or "文档工序",
        "detail": detail or "该工序结果已挂接当前证据。",
        "links": links[:4],
    }


def _build_related_evidence_link(
    item: dict[str, Any],
    *,
    context: str | None,
    anchors: list[str],
) -> dict[str, Any]:
    label_parts: list[str] = []
    source_title = _string_or_none(item.get("source_title"))
    if source_title:
        label_parts.append(source_title)
    page = item.get("page")
    if isinstance(page, (int, str)) and str(page):
        label_parts.append(f"第{page}页")
    label = " · ".join(label_parts) or str(item.get("chunk_id") or "相关证据")
    return {
        "label": label,
        "path": f"/evidence/{item['chunk_id']}",
        "query": _build_query(
            company=item.get("company_name"),
            period=item.get("report_period"),
            context=context,
            anchors="|".join(anchors[:6]),
        ),
    }


def _build_workflow_links(
    *,
    detail: dict[str, Any],
    user_role: str,
    reference_panels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def append_link(link: dict[str, Any] | None) -> None:
        if not link:
            return
        path = str(link.get("path") or "")
        query = {
            str(key): str(value)
            for key, value in (link.get("query") or {}).items()
            if value is not None and str(value)
        }
        identity = (path, tuple(sorted(query.items())))
        if not path or identity in seen:
            return
        seen.add(identity)
        links.append({**link, "query": query})

    for panel in reference_panels:
        append_link(panel.get("route"))

    company_name = detail.get("company_name")
    report_period = detail.get("report_period")
    source_type = str(detail.get("source_type") or "")

    append_link(
        {
            "label": "继续协同分析",
            "detail": "围绕这条证据继续形成判断与动作。",
            "path": "/workspace",
            "query": _build_query(company=company_name, period=report_period, role=user_role),
        }
    )
    append_link(
        {
            "label": "查看图谱链路",
            "detail": "回到传导路径里看它怎么影响判断。",
            "path": "/graph",
            "query": _build_query(company=company_name, period=report_period, role=user_role),
        }
    )
    append_link(
        {
            "label": "回到经营诊断",
            "detail": "在指标、标签和动作卡里重新审视这条证据。",
            "path": "/score",
            "query": _build_query(company=company_name, period=report_period),
        }
    )

    if source_type.startswith("research_"):
        append_link(
            {
                "label": "回到观点核验",
                "detail": "查看这条证据对应的研报观点。",
                "path": "/verify",
                "query": _build_query(
                    company=company_name,
                    period=report_period,
                    report_title=detail.get("source_title"),
                ),
            }
        )
    else:
        append_link(
            {
                "label": "回到文档复核",
                "detail": "继续检查页码、结构契约和上游文档结果。",
                "path": "/vision",
                "query": _build_query(company=company_name, period=report_period, role=user_role),
            }
        )

    return links[:6]


def _matching_evidence_groups(groups: list[dict[str, Any]], chunk_id: str) -> list[dict[str, Any]]:
    return [
        group
        for group in groups
        if any(item.get("chunk_id") == chunk_id for item in group.get("items", []))
    ]


def _load_verify_payload(service: Any, detail: dict[str, Any]) -> dict[str, Any] | None:
    if not hasattr(service, "verify_claim"):
        return None
    company_name = _string_or_none(detail.get("company_name"))
    if not company_name:
        return None

    source_type = str(detail.get("source_type") or "")
    report_title = detail.get("source_title") if source_type.startswith("research_") else None
    period_candidates = []
    for candidate in (detail.get("report_period"), None):
        period = _string_or_none(candidate)
        if period not in period_candidates:
            period_candidates.append(period)

    for period in period_candidates:
        payload = _safe_call(service.verify_claim, company_name, period, report_title)
        if payload is None:
            continue
        if report_title or _matching_evidence_groups(payload.get("evidence_groups", []), detail["chunk_id"]):
            return payload
    return None


def _resolve_company(repository: Any, company_name: str, report_period: str | None) -> dict[str, Any] | None:
    if not company_name or not hasattr(repository, "get_company"):
        return None
    company = repository.get_company(company_name, report_period)
    if company is not None:
        return company
    return repository.get_company(company_name, None)


def _build_query(**values: Any) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in values.items()
        if value is not None and str(value)
    }


def _safe_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
