from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    query: str = Field(..., min_length=2)
    company_name: str | None = None
    report_period: str | None = None
    user_role: Literal["investor", "management", "regulator"] = "investor"


class ScoreRequest(BaseModel):
    company_name: str
    report_period: str | None = None


class BenchmarkRequest(BaseModel):
    company_name: str
    report_period: str | None = None


class ClaimVerifyRequest(BaseModel):
    company_name: str
    report_period: str | None = None
    report_title: str | None = None


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    display_name: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=64)
    role: Literal["investor", "management", "regulator"] = "investor"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=64)


class DocumentPipelineRunRequest(BaseModel):
    stage: Literal["cross_page_merge", "title_hierarchy", "cell_trace"]
    limit: int = Field(default=5, ge=1, le=20)


class TaskStatusUpdateRequest(BaseModel):
    task_id: str = Field(..., min_length=6, max_length=160)
    status: Literal["queued", "in_progress", "done", "blocked"]
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)


class AlertStatusUpdateRequest(BaseModel):
    alert_id: str = Field(..., min_length=6, max_length=160)
    status: Literal["new", "dispatched", "in_progress", "resolved", "dismissed"]
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)


class AlertDispatchRequest(BaseModel):
    alert_id: str = Field(..., min_length=6, max_length=160)
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)


class WatchCompanyRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=80)
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)


class WatchboardScanRequest(BaseModel):
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None


class WatchboardDispatchRequest(BaseModel):
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
