from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import logging
import os

_config_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Settings:
    app_name: str
    env: str
    host: str
    port: int
    default_period: str
    sample_data_path: Path
    official_data_path: Path
    bronze_data_path: Path
    silver_data_path: Path
    postgres_dsn: str
    auth_session_days: int
    cors_allowed_origins: tuple[str, ...]
    audit_min_evidence: int = 2
    doc_layout_engine: str = "PP-DocLayout-V3 + PyMuPDF"
    ocr_provider: str = "PaddleOCR-VL"
    ocr_model: str = "PaddleOCR-VL-1.5"
    ocr_assets_path: Path = Path("models/paddleocr-vl")
    ocr_runtime_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai-proxy.org/v1"


def _resolve_data_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()

    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    return (root / candidate).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    sample_path = os.getenv("OPS_PILOT_SAMPLE_DATA_PATH", "data/bootstrap")
    settings = Settings(
        app_name="OpsPilot-X",
        env=os.getenv("OPS_PILOT_ENV", "development"),
        host=os.getenv("OPS_PILOT_HOST", "0.0.0.0"),
        port=int(os.getenv("OPS_PILOT_PORT", "8000")),
        default_period=os.getenv("OPS_PILOT_DEFAULT_PERIOD", "2024Q3"),
        sample_data_path=_resolve_data_path(root, sample_path),
        official_data_path=_resolve_data_path(
            root, os.getenv("OPS_PILOT_OFFICIAL_DATA_PATH", "data/raw/official")
        ),
        bronze_data_path=_resolve_data_path(
            root, os.getenv("OPS_PILOT_BRONZE_DATA_PATH", "data/bronze/official")
        ),
        silver_data_path=_resolve_data_path(
            root, os.getenv("OPS_PILOT_SILVER_DATA_PATH", "data/silver/official")
        ),
        postgres_dsn=os.getenv(
            "OPS_PILOT_POSTGRES_DSN",
            "postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot",
        ),
        auth_session_days=int(os.getenv("OPS_PILOT_AUTH_SESSION_DAYS", "7")),
        cors_allowed_origins=tuple(
            origin.strip()
            for origin in os.getenv(
                "OPS_PILOT_CORS_ALLOWED_ORIGINS",
                "http://127.0.0.1:8080,http://localhost:8080",
            ).split(",")
            if origin.strip()
        ),
        doc_layout_engine=os.getenv(
            "OPS_PILOT_DOC_LAYOUT_ENGINE",
            "PP-DocLayout-V3 + PyMuPDF",
        ),
        ocr_provider=os.getenv("OPS_PILOT_OCR_PROVIDER", "PaddleOCR-VL"),
        ocr_model=os.getenv("OPS_PILOT_OCR_MODEL", "PaddleOCR-VL-1.5"),
        ocr_assets_path=_resolve_data_path(
            root, os.getenv("OPS_PILOT_OCR_ASSETS_PATH", "models/paddleocr-vl")
        ),
        ocr_runtime_enabled=os.getenv("OPS_PILOT_OCR_RUNTIME_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        openai_api_key=os.getenv("OPS_PILOT_OPENAI_API_KEY", ""),
        openai_base_url=os.getenv(
            "OPS_PILOT_OPENAI_BASE_URL",
            "https://api.openai-proxy.org/v1",
        ),
    )

    if not settings.openai_api_key:
        _config_logger.warning(
            "OPS_PILOT_OPENAI_API_KEY 未设置，LLM 功能将不可用。"
            " 请通过环境变量或 .env 文件配置。"
        )

    return settings
