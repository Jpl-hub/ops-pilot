from __future__ import annotations

from opspilot.config import Settings
from opspilot.infra.hybrid_repository import HybridRepository
from opspilot.infra.official_repository import OfficialMetricsRepository
from opspilot.infra.sample_repository import SampleRepository


def build_repository(settings: Settings) -> HybridRepository:
    sample_repository = (
        SampleRepository(settings.sample_data_path)
        if settings.allow_sample_fallback
        else None
    )
    return HybridRepository(
        official_repository=OfficialMetricsRepository(
            settings.silver_data_path,
            settings.sample_data_path.parent / "universe" / "formal_company_pool.json",
            bronze_chunks_dir=settings.bronze_data_path / "chunks",
        ),
        sample_repository=sample_repository,
        fallback_enabled=settings.allow_sample_fallback,
    )
