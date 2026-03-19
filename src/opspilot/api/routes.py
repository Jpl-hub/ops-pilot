from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opspilot.api.schemas import (
    BenchmarkRequest,
    ChatTurnRequest,
    ClaimVerifyRequest,
    LoginRequest,
    RegisterRequest,
    ScoreRequest,
)
from opspilot.application.services import OpsPilotService
from opspilot.config import get_settings
from opspilot.infra.auth_store import AuthStore
from opspilot.infra.hybrid_repository import HybridRepository
from opspilot.infra.official_repository import OfficialMetricsRepository
from opspilot.infra.sample_repository import SampleRepository


router = APIRouter(prefix="/api/v1")
auth_scheme = HTTPBearer(auto_error=False)


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


@lru_cache(maxsize=1)
def get_auth_store() -> AuthStore:
    settings = get_settings()
    store = AuthStore(settings.postgres_dsn, session_days=settings.auth_session_days)
    return store


def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录。")
    user = get_auth_store().get_user_by_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效。")
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


@router.get("/healthz")
def healthz() -> dict:
    return get_service().health()


@router.post("/auth/register")
def auth_register(request: RegisterRequest) -> dict:
    try:
        user, token = get_auth_store().register_user(
            username=request.username,
            display_name=request.display_name,
            password=request.password,
            role=request.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "user": asdict(user)}


@router.post("/auth/login")
def auth_login(request: LoginRequest) -> dict:
    try:
        user, token = get_auth_store().login(username=request.username, password=request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "user": asdict(user)}


@router.get("/auth/me")
def auth_me(current_user: dict = Depends(require_current_user)) -> dict:
    return current_user


@router.post("/auth/logout")
def auth_logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    current_user: dict = Depends(require_current_user),
) -> dict:
    if credentials is not None:
        get_auth_store().revoke_session(credentials.credentials)
    return {"status": "ok", "username": current_user["username"]}


@router.get("/admin/official-data/status")
def official_data_status(_: dict = Depends(require_current_user)) -> dict:
    return get_service().official_data_status()


@router.get("/admin/overview")
def admin_overview(_: dict = Depends(require_current_user)) -> dict:
    return get_service().admin_overview()


@router.post("/chat/turn")
def chat_turn(request: ChatTurnRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().chat_turn(
            query=request.query,
            company_name=request.company_name,
            report_period=request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/score")
def company_score(request: ScoreRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().score_company(request.company_name, request.report_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/benchmark")
def company_benchmark(request: BenchmarkRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().benchmark_company(request.company_name, request.report_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/claim/verify")
def claim_verify(request: ClaimVerifyRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().verify_claim(
            request.company_name,
            request.report_period,
            request.report_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/research-reports")
def company_research_reports(company_name: str, _: dict = Depends(require_current_user)) -> dict:
    reports = get_service().list_research_reports(company_name)
    if not reports:
        raise HTTPException(status_code=404, detail=f"未找到研报：{company_name}")
    return {"company_name": company_name, "reports": reports}


@router.get("/company/research-compare")
def company_research_compare(
    company_name: str,
    limit: int = 6,
    sort_by: str = "priority",
    filter_mode: str = "all",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().compare_research_reports(
            company_name,
            limit,
            sort_by=sort_by,
            filter_mode=filter_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/research-timeline")
def company_research_timeline(company_name: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().summarize_research_timeline(company_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/industry/risk-scan")
def industry_risk_scan(report_period: str | None = None, _: dict = Depends(require_current_user)) -> dict:
    return get_service().risk_scan(report_period)


@router.get("/industry/research-brief")
def industry_research_brief(_: dict = Depends(require_current_user)) -> dict:
    return get_service().industry_research_brief()


@router.get("/evidence/{chunk_id}")
def evidence_detail(chunk_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().get_evidence(chunk_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
