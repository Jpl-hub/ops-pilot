from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opspilot.api.schemas import (
    AlertDispatchRequest,
    AlertStatusUpdateRequest,
    BenchmarkRequest,
    ChatTurnRequest,
    ClaimVerifyRequest,
    DocumentPipelineRunRequest,
    LoginRequest,
    RegisterRequest,
    ScoreRequest,
    TaskStatusUpdateRequest,
    WatchCompanyRequest,
    WatchboardDispatchRequest,
    WatchboardScanRequest,
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


@router.get("/admin/innovation-radar")
def admin_innovation_radar(_: dict = Depends(require_current_user)) -> dict:
    return get_service().innovation_radar()


@router.get("/admin/document-pipeline/jobs")
def admin_document_pipeline_jobs(_: dict = Depends(require_current_user)) -> dict:
    return get_service().document_pipeline_jobs()


@router.post("/admin/document-pipeline/run")
def admin_document_pipeline_run(
    request: DocumentPipelineRunRequest, _: dict = Depends(require_current_user)
) -> dict:
    return get_service().run_document_pipeline_stage(request.stage, request.limit)


@router.get("/admin/document-pipeline/results")
def admin_document_pipeline_results(
    stage: str | None = None,
    status: str | None = None,
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().document_pipeline_results(stage=stage, status=status, limit=limit)


@router.get("/admin/document-pipeline/results/{stage}/{report_id}")
def admin_document_pipeline_result_detail(
    stage: str,
    report_id: str,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().document_pipeline_result_detail(stage, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workspace/overview")
def workspace_overview(user_role: str = "investor", _: dict = Depends(require_current_user)) -> dict:
    return get_service().workspace_overview(user_role)


@router.get("/workspace/runs")
def workspace_runs(limit: int = 20, _: dict = Depends(require_current_user)) -> dict:
    return get_service().workspace_runs(limit=limit)


@router.get("/workspace/runs/{run_id}")
def workspace_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().workspace_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/board")
def task_board(
    user_role: str = "management",
    report_period: str | None = None,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().task_board(user_role=user_role, report_period=report_period)


@router.post("/tasks/update")
def task_update(request: TaskStatusUpdateRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().update_task_status(
            task_id=request.task_id,
            status=request.status,
            user_role=request.user_role,
            report_period=request.report_period,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/alerts/board")
def alert_board(
    report_period: str | None = None,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().alert_workflow(report_period=report_period)


@router.post("/alerts/update")
def alert_update(request: AlertStatusUpdateRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().update_alert_status(
            alert_id=request.alert_id,
            status=request.status,
            report_period=request.report_period,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/alerts/dispatch")
def alert_dispatch(request: AlertDispatchRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().dispatch_alert_to_task(
            alert_id=request.alert_id,
            user_role=request.user_role,
            report_period=request.report_period,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/watchboard")
def watchboard(
    user_role: str = "management",
    report_period: str | None = None,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().watchboard(user_role=user_role, report_period=report_period)


@router.post("/watchboard/add")
def watchboard_add(request: WatchCompanyRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().add_watch_company(
            company_name=request.company_name,
            user_role=request.user_role,
            report_period=request.report_period,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/watchboard/remove")
def watchboard_remove(
    request: WatchCompanyRequest, _: dict = Depends(require_current_user)
) -> dict:
    return get_service().remove_watch_company(
        company_name=request.company_name,
        user_role=request.user_role,
        report_period=request.report_period,
    )


@router.post("/watchboard/scan")
def watchboard_scan(
    request: WatchboardScanRequest, _: dict = Depends(require_current_user)
) -> dict:
    return get_service().scan_watchboard(
        user_role=request.user_role,
        report_period=request.report_period,
    )


@router.get("/watchboard/runs")
def watchboard_runs(
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().watchboard_runs(
        user_role=user_role,
        report_period=report_period,
        limit=limit,
    )


@router.get("/watchboard/runs/{run_id}")
def watchboard_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().watchboard_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/watchboard/dispatch")
def watchboard_dispatch(
    request: WatchboardDispatchRequest, _: dict = Depends(require_current_user)
) -> dict:
    return get_service().dispatch_watchboard_alerts(
        user_role=request.user_role,
        report_period=request.report_period,
        limit=request.limit,
    )


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


@router.get("/company/timeline")
def company_timeline(company_name: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().company_timeline(company_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/workspace")
def company_workspace(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_workspace(
            company_name,
            report_period,
            user_role=user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/graph")
def company_graph(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_graph(
            company_name,
            report_period,
            user_role=user_role,
        )
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
