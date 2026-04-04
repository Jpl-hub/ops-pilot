from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    user_role: Literal["investor", "management", "regulator"] = "management"


class StressTestRequest(BaseModel):
    company_name: str
    scenario: str = Field(..., min_length=6, max_length=240)
    report_period: str | None = None
    user_role: Literal["investor", "management", "regulator"] = "management"


class GraphQueryRequest(BaseModel):
    company_name: str
    intent: str = Field(..., min_length=4, max_length=240)
    report_period: str | None = None
    user_role: Literal["investor", "management", "regulator"] = "management"

    @model_validator(mode="before")
    @classmethod
    def accept_question_alias(cls, value: object) -> object:
        if isinstance(value, dict) and not value.get("intent") and value.get("question"):
            value = dict(value)
            value["intent"] = value["question"]
        return value


class VisionAnalyzeRequest(BaseModel):
    company_name: str
    report_period: str | None = None
    user_role: Literal["investor", "management", "regulator"] = "management"


class VisionPipelineRequest(BaseModel):
    company_name: str
    report_period: str | None = None
    user_role: Literal["investor", "management", "regulator"] = "management"


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
    artifact_source: str | None = None
    contract_status: Literal["ready", "invalid", "missing"] | None = None


class TaskStatusUpdateRequest(BaseModel):
    task_id: str = Field(..., min_length=6, max_length=160)
    status: Literal["queued", "in_progress", "done", "blocked"]
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)


class TaskCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=80)
    title: str = Field(..., min_length=4, max_length=120)
    summary: str = Field(..., min_length=4, max_length=240)
    priority: str = Field(default="P1", min_length=2, max_length=16)
    user_role: Literal["investor", "management", "regulator"] = "management"
    report_period: str | None = None
    note: str | None = Field(default=None, max_length=200)
    source_run_id: str | None = Field(default=None, max_length=120)


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
