from __future__ import annotations

from pathlib import Path
import argparse
import json
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
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.install:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        run([sys.executable, "-m", "pip", "install", "paddlepaddle", "paddleocr"])

    metadata = {
        "provider": args.provider,
        "model": args.model,
        "pdf_path": str(pdf_path),
        "output_dir": str(output_dir),
        "python": sys.version,
    }
    (output_dir / "verify_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    smoke_code = f"""
from pathlib import Path
import json

pdf_path = Path(r\"{pdf_path}\")
output_dir = Path(r\"{output_dir}\")

result = {{
    "status": "pending",
    "provider": "{args.provider}",
    "model": "{args.model}",
    "pdf_name": pdf_path.name,
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
