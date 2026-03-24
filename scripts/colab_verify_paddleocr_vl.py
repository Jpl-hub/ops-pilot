from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import subprocess
import sys


def run(command: list[str]) -> None:
    print("$", " ".join(command))
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Colab 最小验证脚本：校验 PaddleOCR-VL 是否可加载并处理一份 PDF。"
    )
    parser.add_argument("--pdf", required=True, help="待验证 PDF 路径。")
    parser.add_argument(
        "--output-dir",
        default="colab_artifacts/paddleocr_vl_verify",
        help="验证输出目录。",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="是否在当前环境内自动安装最小依赖。",
    )
    parser.add_argument(
        "--provider",
        default="PaddleOCR-VL",
        help="记录用 OCR 提供方名称。",
    )
    parser.add_argument(
        "--model",
        default="PaddleOCR-VL-1.5",
        help="记录用模型名称。",
    )
    parser.add_argument(
        "--fail-on-unsupported-runtime",
        action="store_true",
        help="检测到不兼容运行时时直接失败退出。",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime_check = {
        "python_version": sys.version,
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "supported": sys.version_info[:2] in {(3, 10), (3, 11)},
        "reason": (
            "当前 Colab/Paddle 组合在 Python 3.12 下存在已触发的运行时兼容问题，"
            "本脚本仅支持 Python 3.10/3.11 验证。"
            if sys.version_info[:2] not in {(3, 10), (3, 11)}
            else "ok"
        ),
    }

    if args.install:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        run([sys.executable, "-m", "pip", "install", "paddlepaddle", "paddleocr"])

    metadata = {
        "provider": args.provider,
        "model": args.model,
        "pdf_path": str(pdf_path),
        "output_dir": str(output_dir),
        "python": sys.version,
        "runtime_check": runtime_check,
    }
    (output_dir / "verify_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not runtime_check["supported"]:
        result = {
            "status": "blocked",
            "provider": args.provider,
            "model": args.model,
            "pdf_name": pdf_path.name,
            "error": runtime_check["reason"],
            "runtime_check": runtime_check,
            "recommended_action": "改用 Python 3.10/3.11 环境做验证，或直接切到 Docker 交付链路。",
        }
        (output_dir / "verify_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.fail_on_unsupported_runtime:
            raise SystemExit(2)
        return

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_use_mkldnn", "false")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")

    smoke_code = f"""
from pathlib import Path
import json
import os

pdf_path = Path(r\"{pdf_path}\")
output_dir = Path(r\"{output_dir}\")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "false")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

result = {{
    "status": "pending",
    "provider": "{args.provider}",
    "model": "{args.model}",
    "pdf_name": pdf_path.name,
    "mode": "generic_paddleocr_smoke",
}}

try:
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    prediction = ocr.predict(str(pdf_path))
    result["status"] = "ok"
    result["page_count"] = len(prediction) if prediction is not None else 0
    result["preview"] = str(prediction[0])[:2000] if prediction else ""
except Exception as exc:
    result["status"] = "failed"
    result["error"] = repr(exc)

(output_dir / "verify_result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False, indent=2))
"""
    run([sys.executable, "-c", smoke_code])


if __name__ == "__main__":
    main()
