from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.websockets import WebSocketDisconnect

from opspilot.api.schemas import (
    AlertDispatchRequest,
    AlertStatusUpdateRequest,
    BenchmarkRequest,
    ChatTurnRequest,
    ClaimVerifyRequest,
    DocumentPipelineRunRequest,
    GraphQueryRequest,
    LoginRequest,
    RegisterRequest,
    ScoreRequest,
    StressTestRequest,
    TaskCreateRequest,
    TaskStatusUpdateRequest,
    WatchCompanyRequest,
    WatchboardDispatchRequest,
    WatchboardScanRequest,
    VisionAnalyzeRequest,
    VisionPipelineRequest,
)
from opspilot.application.services import OpsPilotService
from opspilot.delivery_report import build_delivery_report_markdown
from opspilot.config import get_settings
from opspilot.infra.auth_store import AuthStore
from opspilot.infra.repository_factory import build_repository


router = APIRouter(prefix="/api/v1")
auth_scheme = HTTPBearer(auto_error=False)


def _period_order_key(period: str | None) -> tuple[int, int]:
    if not period:
        return (0, 0)
    match = re.fullmatch(r"(\d{4})(Q1|H1|Q3|FY)", period)
    if match is None:
        return (0, 0)
    suffix_rank = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
    return (int(match.group(1)), suffix_rank[match.group(2)])


@lru_cache(maxsize=1)
def get_service() -> OpsPilotService:
    settings = get_settings()
    return OpsPilotService(build_repository(settings), settings)


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


@router.get("/admin/delivery-report", response_model=None)
def admin_delivery_report(
    format: str = "json",
    _: dict = Depends(require_current_user),
) -> dict | PlainTextResponse:
    report = get_service().delivery_report()
    if format == "markdown":
        return PlainTextResponse(
            build_delivery_report_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="delivery_report.md"',
            },
        )
    return report


@router.get("/admin/innovation-radar")
def admin_innovation_radar(_: dict = Depends(require_current_user)) -> dict:
    return get_service().innovation_radar()


@router.get("/industry/brain")
def industry_brain(
    user_role: str | None = None,
    report_period: str | None = None,
    current_user: dict = Depends(require_current_user),
) -> dict:
    return get_service().industry_brain(
        user_role=user_role or current_user["role"],
        report_period=report_period,
    )


@router.get("/industry/brain/tick")
def industry_brain_tick(
    user_role: str | None = None,
    report_period: str | None = None,
    current_user: dict = Depends(require_current_user),
) -> dict:
    return get_service().industry_brain_tick(
        user_role=user_role or current_user["role"],
        report_period=report_period,
    )


@router.get("/industry/brain/history")
def industry_brain_history(
    limit: int = 24,
    user_role: str | None = None,
    report_period: str | None = None,
    current_user: dict = Depends(require_current_user),
) -> dict:
    return get_service().industry_brain_history(
        limit=limit,
        user_role=user_role or current_user["role"],
        report_period=report_period,
    )


@router.websocket("/ws/industry-brain")
async def industry_brain_stream(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    user = get_auth_store().get_user_by_token(token) if token else None
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            payload = await asyncio.to_thread(
                get_service().industry_brain_tick,
                user_role=websocket.query_params.get("user_role") or user.role,
                report_period=websocket.query_params.get("report_period"),
            )
            await websocket.send_json(payload)
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        return


@router.get("/admin/document-pipeline/jobs")
def admin_document_pipeline_jobs(_: dict = Depends(require_current_user)) -> dict:
    return get_service().document_pipeline_jobs()


@router.post("/admin/document-pipeline/run")
def admin_document_pipeline_run(
    request: DocumentPipelineRunRequest, _: dict = Depends(require_current_user)
) -> dict:
    try:
        return get_service().run_document_pipeline_stage(
            request.stage,
            request.limit,
            artifact_source=request.artifact_source,
            contract_status=request.contract_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/document-pipeline/results")
def admin_document_pipeline_results(
    stage: str | None = None,
    status: str | None = None,
    artifact_source: str | None = None,
    contract_status: str | None = None,
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().document_pipeline_results(
        stage=stage,
        status=status,
        artifact_source=artifact_source,
        contract_status=contract_status,
        limit=limit,
    )


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


@router.get("/admin/document-pipeline/runs/{run_id}")
def admin_document_pipeline_run_detail(
    run_id: str,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().document_pipeline_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workspace/companies")
def workspace_companies(_: dict = Depends(require_current_user)) -> dict:
    """轻量接口：仅返回公司列表和主周期，不触发风险扫描。"""
    svc = get_service()
    preferred = svc._preferred_period()
    company_records = svc.repository.list_companies()
    companies = [c["company_name"] for c in company_records]
    available_periods = sorted(
        {
            company.get("report_period")
            for company in company_records
            if company.get("report_period")
        },
        key=_period_order_key,
        reverse=True,
    )
    # deduplicate, preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for name in companies:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return {
        "companies": unique,
        "preferred_period": preferred,
        "available_periods": available_periods,
    }


@router.get("/workspace/overview")
def workspace_overview(
    user_role: str = "investor",
    report_period: str | None = None,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().workspace_overview(user_role, report_period=report_period)


@router.get("/workspace/runs")
def workspace_runs(limit: int = 20, _: dict = Depends(require_current_user)) -> dict:
    return get_service().workspace_runs(limit=limit)


@router.get("/workspace/history")
def workspace_history(
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 30,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().workspace_history(
        user_role=user_role,
        report_period=report_period,
        limit=limit,
    )


@router.get("/workspace/execution-bus")
def workspace_execution_bus(
    user_role: str = "management",
    report_period: str | None = None,
    limit: int = 50,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().workspace_execution_bus(
        user_role=user_role,
        report_period=report_period,
        limit=limit,
    )


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


@router.post("/tasks/create")
def task_create(request: TaskCreateRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().create_task(
            company_name=request.company_name,
            title=request.title,
            summary=request.summary,
            priority=request.priority,
            user_role=request.user_role,
            report_period=request.report_period,
            note=request.note,
            source_run_id=request.source_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
async def chat_turn(request: ChatTurnRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return await get_service().chat_turn(
            query=request.query,
            company_name=request.company_name,
            report_period=request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/company/score")
def company_score(request: ScoreRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().run_company_score(
            request.company_name,
            request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/score/runs")
def company_score_runs(
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().score_runs(
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
        limit=limit,
    )


@router.get("/company/score/runs/{run_id}")
def company_score_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().score_run_detail(run_id)
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


@router.get("/company/intelligence-runtime")
def company_intelligence_runtime(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_intelligence_runtime(
            company_name,
            report_period,
            user_role=user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/document-upgrades")
def company_document_upgrades(
    company_name: str,
    report_period: str | None = None,
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_document_upgrades(
            company_name,
            report_period,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/execution-stream")
def company_execution_stream(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 30,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_execution_stream(
            company_name,
            report_period,
            user_role=user_role,
            limit=limit,
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


@router.post("/company/graph-query")
def company_graph_query(
    request: GraphQueryRequest,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_graph_query(
            request.company_name,
            request.intent,
            request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/graph-query/runs")
def graph_query_runs(
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().graph_query_runs(
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
        limit=limit,
    )


@router.get("/graph-query/runs/{run_id}")
def graph_query_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().graph_query_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/vision-analyze")
def company_vision_analyze(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_vision_analyze(
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/vision-runtime")
def company_vision_runtime(
    company_name: str,
    report_period: str | None = None,
    user_role: str = "management",
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().company_vision_runtime(
            company_name=company_name,
            report_period=report_period,
            user_role=user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/vision-pipeline")
def run_company_vision_pipeline(
    request: VisionPipelineRequest,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().run_company_vision_pipeline(
            company_name=request.company_name,
            report_period=request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/vision-analyze")
def run_company_vision_analyze(
    request: VisionAnalyzeRequest,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return get_service().run_company_vision_analyze(
            company_name=request.company_name,
            report_period=request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/vision-analyze/runs")
def vision_runs(
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().vision_runs(
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
        limit=limit,
    )


@router.get("/vision-analyze/runs/{run_id}")
def vision_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().vision_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/company/stress-test")
async def company_stress_test(
    request: StressTestRequest,
    _: dict = Depends(require_current_user),
) -> dict:
    try:
        return await get_service().company_stress_test(
            request.company_name,
            request.scenario,
            request.report_period,
            user_role=request.user_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stress-test/runs")
def stress_test_runs(
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().stress_test_runs(
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
        limit=limit,
    )


@router.get("/stress-test/runs/{run_id}")
def stress_test_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().stress_test_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/claim/verify/runs")
def claim_verify_runs(
    company_name: str | None = None,
    report_period: str | None = None,
    user_role: str = "management",
    report_title: str | None = None,
    limit: int = 20,
    _: dict = Depends(require_current_user),
) -> dict:
    return get_service().verify_runs(
        company_name=company_name,
        report_period=report_period,
        user_role=user_role,
        report_title=report_title,
        limit=limit,
    )


@router.get("/claim/verify/runs/{run_id}")
def claim_verify_run_detail(run_id: str, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().verify_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/claim/verify")
def claim_verify(request: ClaimVerifyRequest, _: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().verify_claim(
            request.company_name,
            request.report_period,
            request.report_title,
            user_role=request.user_role,
            persist_run=True,
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
def evidence_detail(chunk_id: str, current_user: dict = Depends(require_current_user)) -> dict:
    try:
        return get_service().get_evidence(chunk_id, user_role=current_user["role"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
