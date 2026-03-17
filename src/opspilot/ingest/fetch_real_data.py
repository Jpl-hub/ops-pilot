from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from opspilot.ingest.official_clients import (
    EastmoneyResearchClient,
    SSEAnnouncementClient,
    SZSEAnnouncementClient,
    build_periodic_filename,
    build_research_filename,
    download_binary,
    download_text,
    load_company_pool,
    write_manifest,
)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Fetch official-source reports for OpsPilot.")
    parser.add_argument(
        "--company-pool",
        default="data/universe/formal_company_pool.json",
        help="Path to the formal company pool JSON.",
    )
    parser.add_argument(
        "--output-root",
        default="data/raw/official",
        help="Directory to store official-source raw files and manifests.",
    )
    parser.add_argument(
        "--since-date",
        default="2024-01-01",
        help="Lower bound date for report discovery.",
    )
    parser.add_argument(
        "--max-periodic",
        type=int,
        default=2,
        help="Max periodic reports to download per company.",
    )
    parser.add_argument(
        "--max-research",
        type=int,
        default=2,
        help="Max Eastmoney research pages to download per company.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated security codes to limit execution.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only produce manifests and URLs without downloading raw files.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    company_pool = load_company_pool(Path(args.company_pool))
    selected_codes = {item.strip() for item in args.codes.split(",") if item.strip()}
    if selected_codes:
        company_pool = [item for item in company_pool if item.security_code in selected_codes]

    output_root = Path(args.output_root)
    periodic_root = output_root / "periodic_reports"
    research_root = output_root / "research_reports"
    manifests_root = output_root / "manifests"

    sse_client = SSEAnnouncementClient()
    szse_client = SZSEAnnouncementClient()
    eastmoney_client = EastmoneyResearchClient()

    periodic_manifest: list[dict[str, Any]] = []
    research_manifest: list[dict[str, Any]] = []

    for company in company_pool:
        if company.exchange == "SSE":
            periodic_reports = sse_client.list_reports(
                company,
                since_date=args.since_date,
                max_items=args.max_periodic,
            )
        elif company.exchange == "SZSE":
            periodic_reports = szse_client.list_reports(
                company,
                since_date=args.since_date,
                max_items=args.max_periodic,
            )
        else:
            periodic_reports = []

        for report in periodic_reports:
            local_path = periodic_root / report.exchange / report.security_code / build_periodic_filename(report)
            if not args.skip_download:
                download_binary(report.source_url, local_path)
            record = report.to_dict()
            record["local_path"] = str(local_path)
            periodic_manifest.append(record)

        research_reports = eastmoney_client.list_reports(
            company,
            since_date=args.since_date,
            max_items=args.max_research,
        )
        for report in research_reports:
            local_path = research_root / company.security_code / build_research_filename(report)
            if not args.skip_download and report.detail_url:
                download_text(report.detail_url, local_path)
            record = report.to_dict()
            record["local_path"] = str(local_path)
            research_manifest.append(record)

    write_manifest(manifests_root / "periodic_reports_manifest.json", periodic_manifest)
    write_manifest(manifests_root / "research_reports_manifest.json", research_manifest)

    print(f"companies={len(company_pool)}")
    print(f"periodic_reports={len(periodic_manifest)}")
    print(f"research_reports={len(research_manifest)}")


if __name__ == "__main__":
    main()
