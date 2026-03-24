from __future__ import annotations

from pathlib import Path
import json

from opspilot.config import get_settings


def main() -> None:
    settings = get_settings()
    assets_root = Path(settings.ocr_assets_path)
    assets_root.mkdir(parents=True, exist_ok=True)
    manifest_path = assets_root / "ASSETS_MANIFEST.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "provider": settings.ocr_provider,
                    "model": settings.ocr_model,
                    "status": "placeholder",
                    "next_step": "将正式 OCR 模型权重和配置文件放入该目录。",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    contract_path = Path(settings.bronze_data_path) / "upgrades" / "ocr_cell_trace" / "_CONTRACT.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    if not contract_path.exists():
        contract_path.write_text(
            json.dumps(
                {
                    "artifact_type": "standard_ocr_cell_trace",
                    "path_pattern": "data/bronze/official/upgrades/ocr_cell_trace/<security_code>/<report_id>.json",
                    "required_fields": ["tables", "cells"],
                    "notes": "cell_trace 会优先消费该标准 OCR 结构输出；缺失时才回退到几何恢复。",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(str(assets_root))
