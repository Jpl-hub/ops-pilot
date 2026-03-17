from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


@dataclass(slots=True)
class Settings:
    app_name: str
    env: str
    host: str
    port: int
    default_period: str
    sample_data_path: Path
    postgres_dsn: str
    audit_min_evidence: int = 2


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    sample_path = os.getenv("OPS_PILOT_SAMPLE_DATA_PATH", "data/bootstrap")
    return Settings(
        app_name="OpsPilot-X",
        env=os.getenv("OPS_PILOT_ENV", "development"),
        host=os.getenv("OPS_PILOT_HOST", "0.0.0.0"),
        port=int(os.getenv("OPS_PILOT_PORT", "8000")),
        default_period=os.getenv("OPS_PILOT_DEFAULT_PERIOD", "2024Q3"),
        sample_data_path=(root / sample_path).resolve(),
        postgres_dsn=os.getenv(
            "OPS_PILOT_POSTGRES_DSN",
            "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot",
        ),
    )
