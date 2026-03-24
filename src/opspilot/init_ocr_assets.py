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
    print(str(assets_root))
