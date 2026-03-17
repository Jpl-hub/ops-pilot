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
