from __future__ import annotations

from opspilot.config import Settings
from opspilot.infra.hybrid_repository import HybridRepository
from opspilot.infra.official_repository import OfficialMetricsRepository


def build_repository(settings: Settings) -> HybridRepository:
    return HybridRepository(
        official_repository=OfficialMetricsRepository(
            settings.silver_data_path,
            settings.universe_data_path / "formal_company_pool.json",
            bronze_chunks_dir=settings.bronze_data_path / "chunks",
        ),
    )
