from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from opspilot.api.schemas import BenchmarkRequest, ChatTurnRequest, ScoreRequest
from opspilot.application.services import OpsPilotService
from opspilot.config import get_settings
from opspilot.infra.sample_repository import SampleRepository


router = APIRouter(prefix="/api/v1")


@lru_cache(maxsize=1)
def get_service() -> OpsPilotService:
    settings = get_settings()
    repository = SampleRepository(settings.sample_data_path)
    return OpsPilotService(repository, settings)


@router.get("/healthz")
def healthz() -> dict:
    return get_service().health()


@router.get("/admin/official-data/status")
def official_data_status() -> dict:
    return get_service().official_data_status()


@router.post("/chat/turn")
def chat_turn(request: ChatTurnRequest) -> dict:
    try:
        return get_service().chat_turn(query=request.query, company_name=request.company_name, report_period=request.report_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/score")
def company_score(request: ScoreRequest) -> dict:
    try:
        return get_service().score_company(request.company_name, request.report_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/benchmark")
def company_benchmark(request: BenchmarkRequest) -> dict:
    try:
        return get_service().benchmark_company(request.company_name, request.report_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/industry/risk-scan")
def industry_risk_scan(report_period: str | None = None) -> dict:
    return get_service().risk_scan(report_period)


@router.get("/evidence/{chunk_id}")
def evidence_detail(chunk_id: str) -> dict:
    try:
        return get_service().get_evidence(chunk_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
