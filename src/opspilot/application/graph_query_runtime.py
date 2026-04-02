from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from opspilot.application.document_pipeline import _utcnow_iso, _write_json
from opspilot.application.graph_runtime import (
    _build_graph_command_surface,
    _build_graph_query_evidence_navigation,
    _build_graph_query_inference_path,
    _build_graph_query_live_frames,
    _build_graph_query_phase_track,
    _build_graph_query_signal_stream,
    _build_graph_route_bands,
    _build_graph_signal_tape,
    _retrieve_graph_paths,
)
from opspilot.application.runtime_manifests import (
    _build_graph_query_run_id,
    _graph_query_run_detail_path,
    _load_graph_query_run_manifest,
    _write_graph_query_run_manifest,
)


def _run_company_graph_query(
    service: Any,
    company_name: str,
    intent: str,
    report_period: str | None = None,
    *,
    user_role: str = "management",
) -> dict[str, Any]:
    workspace = service._company_graph_workspace(
        company_name,
        report_period,
        user_role=user_role,
    )
    graph = service.company_graph(
        company_name,
        workspace["report_period"],
        user_role=user_role,
        workspace=workspace,
    )
    retrieval = _retrieve_graph_paths(
        graph=graph,
        company_name=company_name,
        report_period=workspace["report_period"],
        intent=intent,
    )
    focal_nodes = retrieval["focal_nodes"]
    inference_path = _build_graph_query_inference_path(
        company_name=company_name,
        report_period=workspace["report_period"],
        intent=intent,
        focal_nodes=focal_nodes,
        retrieved_paths=retrieval["paths"],
        retrieval_summary=retrieval["summary"],
        workspace=workspace,
    )
    phase_track = _build_graph_query_phase_track(
        company_name=company_name,
        intent=intent,
        workspace=workspace,
        inference_path=inference_path,
        retrieval_summary=retrieval["summary"],
    )
    signal_stream = _build_graph_query_signal_stream(
        focal_nodes=focal_nodes,
        retrieved_paths=retrieval["paths"],
        workspace=workspace,
        graph_node_count=len(graph["nodes"]),
        retrieval_summary=retrieval["summary"],
    )
    evidence_navigation = _build_graph_query_evidence_navigation(workspace)
    payload = {
        "company_name": company_name,
        "report_period": workspace["report_period"],
        "user_role": user_role,
        "intent": intent,
        "summary": {
            "score": workspace["score_summary"]["total_score"],
            "grade": workspace["score_summary"]["grade"],
            "risk_count": workspace["score_summary"]["risk_count"],
            "execution_records": len(workspace["execution_stream"]["records"]),
        },
        "graph_retrieval": retrieval["summary"],
        "focal_nodes": focal_nodes,
        "inference_path": inference_path,
        "phase_track": phase_track,
        "signal_stream": signal_stream,
        "graph_command_surface": _build_graph_command_surface(
            company_name=company_name,
            intent=intent,
            focal_nodes=focal_nodes,
            inference_path=inference_path,
            phase_track=phase_track,
            signal_stream=signal_stream,
            retrieval_summary=retrieval["summary"],
            workspace=workspace,
        ),
        "graph_live_frames": _build_graph_query_live_frames(
            focal_nodes=focal_nodes,
            inference_path=inference_path,
            phase_track=phase_track,
            signal_stream=signal_stream,
        ),
        "graph_signal_tape": _build_graph_signal_tape(
            inference_path=inference_path,
            signal_stream=signal_stream,
        ),
        "graph_route_bands": _build_graph_route_bands(
            inference_path=inference_path,
            signal_stream=signal_stream,
        ),
        "execution_stream": workspace["execution_stream"]["records"][:6],
        "related_routes": [
            {
                "label": "查看企业体检",
                "path": "/score",
                "query": {"company": company_name, "period": workspace["report_period"]},
            },
            {
                "label": "查看协同分析",
                "path": "/workspace",
                "query": {"company": company_name},
            },
            {
                "label": "执行压力测试",
                "path": "/stress",
                "query": {"company": company_name, "period": workspace["report_period"]},
            },
        ],
        "evidence_navigation": evidence_navigation,
        "graph": {
            "summary": graph["summary"],
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "retrieved_path_count": retrieval["summary"]["path_count"],
            "nodes": graph["nodes"],
            "edges": graph["edges"],
        },
    }
    run_id = _build_graph_query_run_id(company_name)
    detail_path = _graph_query_run_detail_path(service.settings, run_id)
    _write_json(detail_path, payload)
    manifest = _load_graph_query_run_manifest(service.settings)
    records = [item for item in manifest["records"] if item.get("run_id") != run_id]
    records.insert(
        0,
        {
            "run_id": run_id,
            "company_name": company_name,
            "report_period": workspace["report_period"],
            "user_role": user_role,
            "intent": intent,
            "created_at": _utcnow_iso(),
            "detail_path": str(detail_path),
        },
    )
    manifest["records"] = records[:200]
    _write_graph_query_run_manifest(service.settings, manifest)
    payload["run_id"] = run_id
    return payload


def _graph_query_runs(
    service: Any,
    *,
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
) -> dict[str, Any]:
    records = [
        item
        for item in _load_graph_query_run_manifest(service.settings)["records"]
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


def _graph_query_run_detail(service: Any, run_id: str) -> dict[str, Any]:
    record = next(
        (
            item
            for item in _load_graph_query_run_manifest(service.settings)["records"]
            if item.get("run_id") == run_id
        ),
        None,
    )
    if record is None:
        raise ValueError(f"未找到图谱查询运行：{run_id}")
    detail_path = Path(record["detail_path"])
    if not detail_path.exists():
        raise ValueError(f"未找到图谱查询详情：{run_id}")
    try:
        with detail_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"图谱查询记录损坏：{run_id}") from exc
    payload["run_meta"] = {
        "run_id": run_id,
        "created_at": record.get("created_at"),
        "company_name": record.get("company_name"),
        "report_period": record.get("report_period"),
        "user_role": record.get("user_role"),
        "intent": record.get("intent"),
    }
    return payload
