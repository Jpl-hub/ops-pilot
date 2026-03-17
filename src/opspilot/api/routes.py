from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from opspilot.api.schemas import BenchmarkRequest, ChatTurnRequest, ClaimVerifyRequest, ScoreRequest
from opspilot.application.services import OpsPilotService
from opspilot.config import get_settings
from opspilot.infra.hybrid_repository import HybridRepository
from opspilot.infra.official_repository import OfficialMetricsRepository
from opspilot.infra.sample_repository import SampleRepository


router = APIRouter(prefix="/api/v1")


@lru_cache(maxsize=1)
def get_service() -> OpsPilotService:
    settings = get_settings()
    repository = HybridRepository(
        official_repository=OfficialMetricsRepository(
            settings.silver_data_path,
            settings.sample_data_path.parent / "universe" / "formal_company_pool.json",
        ),
        sample_repository=SampleRepository(settings.sample_data_path),
    )
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


@router.post("/claim/verify")
def claim_verify(request: ClaimVerifyRequest) -> dict:
    try:
        return get_service().verify_claim(
            request.company_name,
            request.report_period,
            request.report_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/research-reports")
def company_research_reports(company_name: str) -> dict:
    reports = get_service().list_research_reports(company_name)
    if not reports:
        raise HTTPException(status_code=404, detail=f"未找到研报：{company_name}")
    return {"company_name": company_name, "reports": reports}


@router.get("/industry/risk-scan")
def industry_risk_scan(report_period: str | None = None) -> dict:
    return get_service().risk_scan(report_period)


@router.get("/evidence/{chunk_id}")
def evidence_detail(chunk_id: str) -> dict:
    try:
        return get_service().get_evidence(chunk_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
