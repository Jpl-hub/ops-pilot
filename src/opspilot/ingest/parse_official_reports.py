from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from opspilot.ingest.pdf_bronze import (
    build_chunks,
    extract_page_blocks,
    summarize_report,
    write_chunks_jsonl,
    write_page_json,
)
from opspilot.ingest.official_clients import sanitize_filename


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Parse official periodic report PDFs into bronze data.")
    parser.add_argument(
        "--manifest",
        default="data/raw/official/manifests/periodic_reports_manifest.json",
        help="Path to the periodic reports manifest JSON.",
    )
    parser.add_argument(
        "--output-root",
        default="data/bronze/official",
        help="Directory to store bronze parsing outputs.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated security codes to limit execution.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of reports to parse.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = payload.get("records", [])

    selected_codes = {item.strip() for item in args.codes.split(",") if item.strip()}
    if selected_codes:
        records = [item for item in records if item["security_code"] in selected_codes]
    if args.limit > 0:
        records = records[: args.limit]

    output_root = Path(args.output_root)
    pages_root = output_root / "page_text"
    chunks_root = output_root / "chunks"
    manifests_root = output_root / "manifests"

    parse_rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        pdf_path = Path(record["local_path"])
        report_id = sanitize_filename(pdf_path.stem)
        blocks = extract_page_blocks(pdf_path)
        chunks = build_chunks(blocks, report_id=report_id)
        summary = summarize_report(pdf_path, blocks, chunks)
        metadata = {
            "source": record["source"],
            "company_name": record["company_name"],
            "security_code": record["security_code"],
            "exchange": record["exchange"],
            "subindustry": record["subindustry"],
            "title": record["title"],
            "publish_date": record["publish_date"],
            "report_type": record["report_type"],
            "report_id": report_id,
        }

        page_json_path = pages_root / record["exchange"] / record["security_code"] / f"{report_id}.json"
        chunks_jsonl_path = chunks_root / record["exchange"] / record["security_code"] / f"{report_id}.jsonl"
        write_page_json(page_json_path, blocks, metadata)
        write_chunks_jsonl(chunks_jsonl_path, chunks, metadata)

        parse_rows.append(
            {
                **record,
                **summary,
                "page_json_path": str(page_json_path),
                "chunks_jsonl_path": str(chunks_jsonl_path),
            }
        )
        print(f"[{index}/{len(records)}] parsed {record['security_code']} {record['title']}")

    manifests_root.mkdir(parents=True, exist_ok=True)
    (manifests_root / "parsed_periodic_reports_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "record_count": len(parse_rows),
                "records": parse_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"parsed_reports={len(parse_rows)}")


if __name__ == "__main__":
    main()
